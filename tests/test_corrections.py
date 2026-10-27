"""Label fields are read-only once a tube exists; mistakes are fixed with an audited correction."""
from lims.db import get_db
from conftest import make_root, derive, login, ALL_FIELDS


def _ids(app):
    with app.app_context():
        rows = get_db().execute("SELECT sample_id, parent_id FROM sample ORDER BY sample_id").fetchall()
        root = next(r[0] for r in rows if r[1] is None)
        child = next(r[0] for r in rows if r[1] is not None)
        return root, child


def _edit_form(**over):
    f = {"parent_id": "", "created_datetime": "2026-09-29T10:00", "sop_code": "NA", "biobank_source": "IH", "quantity": "1",
         "unit": "NA", "status": "Available", "freezer": "NA", "rack": "NA", "box": "NA", "position": "NA", "notes": "NA"}
    f.update(over)
    return f


def test_label_fields_cannot_be_edited(app, alice):
    make_root(alice)
    root, _ = (None, None)
    with app.app_context():
        root = get_db().execute("SELECT sample_id FROM sample").fetchone()[0]
    r = alice.get(f"/samples/{root}/edit")
    assert b"Operator (on the label)" in r.data and b'name="created_by"' not in r.data
    # a hand-crafted POST that tries to change the operator is ignored by the form handler...
    r = alice.post(f"/samples/{root}/edit", data=_edit_form(created_by="BB", notes="changed"), follow_redirects=True)
    assert b"Sample updated" in r.data
    with app.app_context():
        conn = get_db()
        assert conn.execute("SELECT created_by FROM sample WHERE sample_id=?", (root,)).fetchone()[0] == "AA"
        # ...and the service layer refuses it outright
        from lims import samples as svc
        try:
            svc.update_sample(conn, root, {"created_by": "BB"})
            assert False, "operator edit should be refused"
        except ValueError as e:
            assert "printed on the label" in str(e)


def test_correction_on_tube_and_collection(app, alice, client):
    make_root(alice)
    with app.app_context():
        root = get_db().execute("SELECT sample_id FROM sample").fetchone()[0]
    derive(alice, root, fraction="PFS", material="NAT")
    root, child = _ids(app)
    # operator correction is tube-specific
    r = alice.post(f"/samples/{child}/correct", data={"field": "created_by", "value_created_by": "BB",
                                                      "reason": "Bob did the spin; Alice only logged it."}, follow_redirects=True)
    assert b"Correction recorded for operator;" in r.data and b"corrected to BB" in r.data and b">corrected<" in r.data
    # collection date correction made from the child lands on the root and shows on both tubes
    r = alice.post(f"/samples/{child}/correct", data={"field": "collection_date", "value_collection_date": "2026-09-28",
                                                      "reason": "Requisition shows the draw was the day before receipt."}, follow_redirects=True)
    assert b"on the whole collection" in r.data
    for sid in (root, child):
        page = alice.get(f"/samples/{sid}").data
        assert b"corrected to 2026-09-28" in page
    assert b"corrected to BB" not in alice.get(f"/samples/{root}").data
    hist = alice.get(f"/samples/{child}").data.split(b"Record history")[1]
    assert b"before" in hist and b"created_by" in hist and b"Bob did the spin" in hist
    with app.app_context():
        conn = get_db()
        # nothing printed changed
        row = conn.execute("SELECT collection_date, created_by FROM sample WHERE sample_id=?", (child,)).fetchone()
        assert tuple(row) == ("2026-09-29", "AA")
        assert conn.execute("SELECT count(*) FROM sample WHERE sample_id LIKE '%260928%'").fetchone()[0] == 0
        # audited and flagged
        a = conn.execute("SELECT record_id, reason FROM audit_log WHERE action='correct' ORDER BY id").fetchall()
        assert [x[0] for x in a] == [child, root] and all(x[1] for x in a)
    r = alice.get("/admin/audit?changes=1")
    assert b"Requisition shows" in r.data
    # API exposes both the printed and the corrected values
    login(client, "alice")
    j = client.get(f"/api/samples/{child}").get_json()
    assert j["corrected_values"] == {"created_by": "BB", "collection_date": "2026-09-28"}
    assert j["sample"]["created_by"] == "AA" and len(j["corrections"]) == 2


def test_correction_validation(app, alice, client):
    make_root(alice)
    with app.app_context():
        root = get_db().execute("SELECT sample_id FROM sample").fetchone()[0]
    bad = [({"field": "created_by", "value_created_by": "BB", "reason": ""}, b"reason is required"),
           ({"field": "created_by", "value_created_by": "ZZ", "reason": "x"}, b"not an active user"),
           ({"field": "collection_date", "value_collection_date": "2026-13-40", "reason": "x"}, b"must be a date"),
           ({"field": "collection_date", "value_collection_date": "2026-09-29", "reason": "x"}, b"already 2026-09-29"),
           ({"field": "notes", "value_notes": "x", "reason": "x"}, b"not a label field")]
    for data, msg in bad:
        r = alice.post(f"/samples/{root}/correct", data=data, follow_redirects=True)
        assert msg in r.data, msg
    with app.app_context():
        assert get_db().execute("SELECT count(*) FROM sample_correction").fetchone()[0] == 0
    # viewers cannot correct
    login(client, "vic")
    r = client.post(f"/samples/{root}/correct", data={"field": "created_by", "value_created_by": "BB", "reason": "x"})
    assert r.status_code == 403
