"""GitHub issues #1-#3 under nomenclature v2.1.

#1 (register the short-lived base specimen with its derived tubes) is now the collection flow: the specimen is a
collection record, never a tube, and the first tubes are created straight from it.
#2 occupied-slot warning. #3 time collected / received follow the received date (now on the collection form)."""
from lims.db import get_db
from conftest import sid, make_root, new_collection, add_tubes, derive, ALL_FIELDS


def _slot_codes(app):
    with app.app_context():
        conn = get_db()
        for cat, code in (("freezer", "F1"), ("rack", "R1"), ("box", "B1")):
            conn.execute("INSERT OR IGNORE INTO code_list(category, code, meaning, sort_order) VALUES (?,?,?,1)", (cat, code, code))
        conn.commit()


LOC = {"freezer": "F1", "rack": "R1", "box": "B1", "position": "A1"}


def _count(app):
    with app.app_context():
        return get_db().execute("SELECT count(*) FROM sample").fetchone()[0]


def test_collection_then_first_tubes_replaces_base_specimen(app, alice):
    r = alice.get("/register")
    assert b"Register a collection" in r.data and b"base specimen" not in r.data.lower()
    assert alice.get("/samples/new").headers["Location"].startswith("/collections/new")
    cid = new_collection(alice, specimen_code="PB", container_type="EDTA", quantity="10")
    page = alice.get(f"/collections/{cid}/tubes").data
    assert b"first-generation tubes" in page
    r = add_tubes(alice, cid, fraction="PBM", material="CPU", count="3", then="more")
    assert b"Created 3 tube" in r.data and b"Tubes made from collection" in r.data      # back on the form for the next group
    r = add_tubes(alice, cid, fraction="PLA", material="FRZ", count="2")
    with app.app_context():
        rows = get_db().execute("SELECT sample_id, parent_id, root_id, collection_id FROM sample ORDER BY sample_id").fetchall()
    assert len(rows) == 5 and all(r["parent_id"] is None and r["root_id"] == r["sample_id"] and r["collection_id"] == cid for r in rows)
    # the collection itself is recorded with its quantity and appears in the audit log once
    with app.app_context():
        c = get_db().execute("SELECT * FROM collection WHERE collection_id=?", (cid,)).fetchone()
        assert c["quantity"] == 10 and c["specimen_code"] == "PB"
        assert get_db().execute("SELECT count(*) FROM audit_log WHERE table_name='collection' AND record_id=?", (str(cid),)).fetchone()[0] == 1


def test_location_warning_on_create_then_confirm(app, alice):
    _slot_codes(app)
    cid = new_collection(alice)
    r = add_tubes(alice, cid, **LOC)
    assert b"Created 1 tube" in r.data and _count(app) == 1
    r = add_tubes(alice, cid, **LOC)
    assert b"already occupied" in r.data and b'name="confirm_location"' in r.data and _count(app) == 1
    r = add_tubes(alice, cid, **{**LOC, "box": "NA"})
    assert b"Created 1 tube" in r.data and _count(app) == 2
    r = add_tubes(alice, cid, **LOC, confirm_location="1")
    assert b"Created 1 tube" in r.data and _count(app) == 3


def test_location_warning_ignores_depleted_and_applies_to_edit(app, alice):
    _slot_codes(app)
    cid = new_collection(alice)
    add_tubes(alice, cid, **LOC)
    first = sid("PF", "PFM", "CPU")
    derive(alice, first, fraction="TUM", material="CPU")
    child = sid("PF", "TUM", "CPU")
    form = {"parent_id": first, "sop_code": "NA", "biobank_source": "IH", "quantity": "1", "unit": "NA", "status": "Available",
            "notes": "NA", **LOC}
    r = alice.post(f"/samples/{child}/edit", data=form, follow_redirects=True)
    assert b"already occupied" in r.data and first.encode() in r.data
    r = alice.post(f"/samples/{child}/edit", data={**form, "confirm_location": "1"}, follow_redirects=True)
    assert b"Sample updated" in r.data
    alice.post(f"/samples/{first}/edit", data={**form, "parent_id": "", "status": "Depleted", **{k: "NA" for k in LOC}}, follow_redirects=True)
    alice.post(f"/samples/{child}/edit", data={**form, "status": "Depleted"}, follow_redirects=True)
    r = add_tubes(alice, cid, **LOC)
    assert b"Created 1 tube" in r.data and b"already occupied" not in r.data


def test_time_fields_follow_received_date(app, alice):
    page = alice.get("/collections/new").data
    assert b'data-time-for="time_collected"' in page and b"on the received date" in page and b"other date" in page
    # the composed value (date + time) is stored on the collection
    cid = new_collection(alice, time_collected="2026-09-29T08:15", time_received="2026-09-29T09:40")
    with app.app_context():
        c = get_db().execute("SELECT time_collected, time_received FROM collection WHERE collection_id=?", (cid,)).fetchone()
    assert tuple(c) == ("2026-09-29T08:15", "2026-09-29T09:40")
