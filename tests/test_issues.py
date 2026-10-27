"""GitHub issues #1-#3: combined base+derived registration, duplicate-location warning, time-only inputs."""
from lims.db import get_db
from conftest import make_root, derive, login, ALL_FIELDS


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


def test_location_warning_on_create_then_confirm(app, alice):
    _slot_codes(app)
    r = make_root(alice, **LOC)
    assert b"Created 1 tube" in r.data and _count(app) == 1
    # same slot again: warned, nothing created, form re-shown with the confirm field
    r = make_root(alice, **LOC, collection_date="2026-09-30")
    assert b"already occupied" in r.data and b'name="confirm_location"' in r.data and _count(app) == 1
    # NA anywhere in the slot is never a conflict
    r = make_root(alice, **{**LOC, "box": "NA"}, collection_date="2026-10-01")
    assert b"Created 1 tube" in r.data and _count(app) == 2
    # confirmed: created
    r = make_root(alice, **LOC, collection_date="2026-09-30", confirm_location="1")
    assert b"Created 1 tube" in r.data and _count(app) == 3


def test_location_warning_ignores_depleted_and_applies_to_edit(app, alice):
    _slot_codes(app)
    make_root(alice, **LOC)
    with app.app_context():
        conn = get_db()
        first = conn.execute("SELECT sample_id FROM sample").fetchone()[0]
    # a derived tube elsewhere, then edit it into the occupied slot: warned, then confirmed
    r = derive(alice, first, fraction="PFS", material="NAT")
    with app.app_context():
        child = get_db().execute("SELECT sample_id FROM sample WHERE parent_id=?", (first,)).fetchone()[0]
    form = {"parent_id": first, "created_datetime": "2026-09-29T10:00", "created_by": "AA", "sop_code": "NA", "biobank_source": "IH",
            "quantity": "1", "unit": "NA", "status": "Available", "notes": "NA", **LOC}
    r = alice.post(f"/samples/{child}/edit", data=form, follow_redirects=True)
    assert b"already occupied" in r.data and first.encode() in r.data
    with app.app_context():
        assert get_db().execute("SELECT freezer FROM sample WHERE sample_id=?", (child,)).fetchone()[0] == "NA"
    r = alice.post(f"/samples/{child}/edit", data={**form, "confirm_location": "1"}, follow_redirects=True)
    assert b"Sample updated" in r.data
    # once the first tube is Depleted the slot is free: no warning for a third tube
    alice.post(f"/samples/{first}/edit", data={**form, "parent_id": "", "status": "Depleted", **{k: "NA" for k in LOC}}, follow_redirects=True)
    alice.post(f"/samples/{child}/edit", data={**form, "status": "Depleted"}, follow_redirects=True)
    r = make_root(alice, **LOC, collection_date="2026-10-02")
    assert b"Created 1 tube" in r.data and b"already occupied" not in r.data


def _with_base(client, **over):
    data = {"participant": "KXRTQVA", "collection_date": "2026-10-20", "specimen": "PB",
            "base_fraction": "BLK", "base_material": "NAT", "base_quantity": "10", "base_unit": "mL", "parent_consumed": "1",
            "fraction": "PBM", "material": "CPU", "count": "3", "quantity": "1", "unit": "mL", "created_by": "AA", **ALL_FIELDS}
    data.update(over)
    return client.post("/samples/derive/with-base", data=data, follow_redirects=True)


def test_register_base_and_derived_together(app, alice):
    r = alice.get("/samples/derive/with-base?participant=KXRTQVA&fraction=PBM&material=CPU")
    assert r.status_code == 200 and b"Base specimen (as collected)" in r.data
    r = _with_base(alice)
    assert b"Registered base specimen" in r.data and b"3 derived tube(s)" in r.data, r.data[:600]
    with app.app_context():
        conn = get_db()
        root = conn.execute("SELECT * FROM sample WHERE parent_id IS NULL").fetchone()
        kids = conn.execute("SELECT * FROM sample WHERE parent_id=? ORDER BY sample_id", (root["sample_id"],)).fetchall()
        assert root["sample_id"].endswith("-PB-BLK-NAT-01") and root["status"] == "Depleted"
        assert root["quantity"] == 10 and root["unit"] == "mL" and root["freezer"] == "NA"
        assert root["created_datetime"] == ALL_FIELDS["created_datetime"] and root["created_by"] == "AA"
        assert "registered automatically" in root["notes"]
        assert len(kids) == 3 and all(k["fraction_code"] == "PBM" and k["material_code"] == "CPU" and k["root_id"] == root["sample_id"] for k in kids)
        # the automatic base tube is flagged in the audit log so it stands out in the changes-only view
        reason = conn.execute("SELECT reason FROM audit_log WHERE table_name='sample' AND record_id=? AND action='insert'",
                              (root["sample_id"],)).fetchone()[0]
        assert "automatically" in reason
    # the picker links to the combined form
    r = alice.get("/samples/derive?participant=KXRTQVA&fraction=PBM&material=CPU")
    assert b"/samples/derive/with-base?" in r.data


def test_base_and_derived_together_is_all_or_nothing(app, alice):
    # a derived tube the rules forbid: neither the base nor the derived tube is written
    r = _with_base(alice, fraction="TUM", material="CPU")
    assert b"Not created" in r.data and b"Derived tube:" in r.data and _count(app) == 0
    # a base specimen the rules forbid
    r = _with_base(alice, base_material="DNA")   # DNA is not an as-collected material
    assert b"Base specimen:" in r.data and _count(app) == 0
    # missing fields
    r = _with_base(alice, base_quantity="")
    assert b"Missing" in r.data and _count(app) == 0
    # the base specimen may be kept (not consumed)
    r = _with_base(alice, parent_consumed="")
    assert b"Registered base specimen" in r.data and b"marked Depleted" not in r.data
    with app.app_context():
        assert get_db().execute("SELECT status FROM sample WHERE parent_id IS NULL").fetchone()[0] == "Available"


def test_time_fields_follow_collection_date(app, alice):
    # the base-specimen form carries the time-only inputs; the derive form (no collection date) does not
    r = alice.get("/samples/new")
    assert b"data-time-for" in r.data and b"on the collection date" in r.data
    make_root(alice)
    with app.app_context():
        first = get_db().execute("SELECT sample_id FROM sample").fetchone()[0]
    r = alice.get(f"/samples/{first}/derive")
    assert b'input[name=collection_date]' in r.data   # script is shared; the branch is only taken when the input exists
    # the composed value (date + time) round-trips through the normal attribute path
    r = make_root(alice, collection_date="2026-10-20", attr_time_collected="2026-10-20T08:15", attr_time_received="2026-10-20T09:40")
    assert b"Created 1 tube" in r.data
    with app.app_context():
        v = {k: val for k, val in get_db().execute("SELECT key, value FROM sample_attribute WHERE key IN ('time_collected','time_received')")}
        assert v == {"time_collected": "2026-10-20T08:15", "time_received": "2026-10-20T09:40"}
