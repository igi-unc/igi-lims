"""Label fields (received date, operator, processing date) are read-only once a tube exists; mistakes are fixed
with an audited correction. The received date belongs to the collection and is corrected once for all its tubes."""
from lims.db import get_db
from conftest import sid, make_root, new_collection, add_tubes, derive, login


def test_label_fields_cannot_be_edited(app, alice):
    make_root(alice)
    root = sid("PF", "PFM", "CPU")
    page = alice.get(f"/samples/{root}/edit").data
    assert b"Operator (on the label)" in page and b'name="created_by"' not in page
    assert b"Processed on (on the label)" in page and b'name="created_datetime"' not in page
    r = alice.post(f"/samples/{root}/edit", data={"created_by": "BB", "created_datetime": "2026-09-30T10:00", "notes": "changed",
                                                  "sop_code": "NA", "biobank_source": "IH", "quantity": "1", "unit": "mL",
                                                  "status": "Available", "freezer": "NA", "rack": "NA", "box": "NA", "position": "A1"},
                   follow_redirects=True)
    assert b"Sample updated" in r.data
    with app.app_context():
        conn = get_db()
        assert tuple(conn.execute("SELECT created_by, created_datetime FROM sample WHERE sample_id=?", (root,)).fetchone()) == ("AA", "2026-09-29T10:00")
        from lims import samples as svc
        for change in ({"created_by": "BB"}, {"created_datetime": "2026-09-30T10:00"}):
            try:
                svc.update_sample(conn, root, change)
                assert False, change
            except ValueError as e:
                assert "printed on the label" in str(e)


def test_corrections_on_tube_and_collection(app, alice, client):
    cid = new_collection(alice)
    add_tubes(alice, cid)
    first = sid("PF", "PFM", "CPU")
    derive(alice, first, fraction="TUM", material="CPU")
    child = sid("PF", "TUM", "CPU")
    r = alice.post(f"/samples/{child}/correct", data={"field": "created_by", "value_created_by": "BB",
                                                      "reason": "Bob did the enrichment; Alice only logged it."}, follow_redirects=True)
    assert b"Correction recorded for operator;" in r.data and b"corrected to BB" in r.data and b">corrected<" in r.data
    r = alice.post(f"/samples/{child}/correct", data={"field": "created_datetime", "value_created_datetime": "2026-09-29T16:30",
                                                      "reason": "Logged at the start of the run."}, follow_redirects=True)
    assert b"corrected to 2026-09-29T16:30" in r.data
    # received date from a tube page lands on the collection and shows on every tube
    r = alice.post(f"/samples/{child}/correct", data={"field": "received_date", "value_received_date": "2026-09-28",
                                                      "reason": "Courier log shows receipt the evening before."}, follow_redirects=True)
    assert b"on the whole collection" in r.data
    for s in (first, child):
        assert b"corrected to 2026-09-28" in alice.get(f"/samples/{s}").data
    assert b"corrected to 2026-09-28" in alice.get(f"/collections/{cid}").data
    assert b"corrected to BB" not in alice.get(f"/samples/{first}").data
    # or directly on the collection page
    r = alice.post(f"/collections/{cid}/correct", data={"value_received_date": "2026-09-27", "reason": "Second look at the log."},
                   follow_redirects=True)
    assert b"Correction recorded for the received date" in r.data
    with app.app_context():
        conn = get_db()
        row = conn.execute("SELECT received_date, created_by FROM sample WHERE sample_id=?", (child,)).fetchone()
        assert tuple(row) == ("2026-09-29", "AA")                                   # nothing printed changed
        assert conn.execute("SELECT received_date FROM collection WHERE collection_id=?", (cid,)).fetchone()[0] == "2026-09-29"
        a = conn.execute("SELECT table_name, record_id FROM audit_log WHERE action='correct' ORDER BY id").fetchall()
        assert [tuple(x) for x in a] == [("sample", child), ("sample", child), ("collection", str(cid)), ("collection", str(cid))]
        prev = conn.execute("SELECT original_value FROM sample_correction WHERE collection_id=? ORDER BY id DESC", (cid,)).fetchone()[0]
        assert prev == "2026-09-28"                                                 # the second correction builds on the first
    assert b"Courier log shows" in alice.get("/admin/audit?changes=1").data
    login(client, "alice")
    j = client.get(f"/api/samples/{child}").get_json()
    assert j["corrected_values"] == {"created_by": "BB", "created_datetime": "2026-09-29T16:30", "received_date": "2026-09-27"}
    assert j["sample"]["created_by"] == "AA" and len(j["corrections"]) == 4


def test_correction_validation(app, alice, client):
    make_root(alice)
    root = sid("PF", "PFM", "CPU")
    bad = [({"field": "created_by", "value_created_by": "BB", "reason": ""}, b"reason is required"),
           ({"field": "created_by", "value_created_by": "ZZ", "reason": "x"}, b"not an active user"),
           ({"field": "received_date", "value_received_date": "2026-13-40", "reason": "x"}, b"must be a date"),
           ({"field": "received_date", "value_received_date": "2026-09-29", "reason": "x"}, b"already 2026-09-29"),
           ({"field": "notes", "value_notes": "x", "reason": "x"}, b"not a label field")]
    for data, msg in bad:
        r = alice.post(f"/samples/{root}/correct", data=data, follow_redirects=True)
        assert msg in r.data, msg
    with app.app_context():
        assert get_db().execute("SELECT count(*) FROM sample_correction").fetchone()[0] == 0
    login(client, "vic")
    assert client.post(f"/samples/{root}/correct", data={"field": "created_by", "value_created_by": "BB", "reason": "x"}).status_code == 403
