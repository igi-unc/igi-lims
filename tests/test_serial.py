"""LIMS numbers: 0000000-9999999, issued by the LIMS at registration, unique, assigned under a lock."""
import threading
from flask import g
from lims.db import get_db
from lims import samples as svc
from conftest import sid, new_collection, add_tubes, derive, login


def _serials(app):
    with app.app_context():
        return [r[0] for r in get_db().execute("SELECT serial FROM sample ORDER BY serial")]


def test_numbers_start_at_zero_and_are_consecutive(app, alice):
    cid = new_collection(alice)
    add_tubes(alice, cid, count="3")
    derive(alice, sid("PF", "PFM", "CPU", 1), fraction="TUM", material="CPU", count="2")
    assert _serials(app) == [0, 1, 2, 3, 4]
    with app.app_context():
        assert get_db().execute("SELECT serial FROM sample WHERE sample_id=?", (sid("PF", "PFM", "CPU", 1),)).fetchone()[0] == 0
    # a registration refused by the rules uses no numbers
    r = derive(alice, sid("PF", "PFM", "CPU", 2), fraction="TUM", material="PEP")
    assert b"Blocked by derivation rules" in r.data
    add_tubes(alice, cid)
    assert _serials(app) == [0, 1, 2, 3, 4, 5]
    # shown on the tube page and the list, found by the search box with or without zeros
    page = alice.get(f"/samples/{sid('PF', 'PFM', 'CPU', 1)}").data.decode()
    assert "No. 0000000" in page and "LIMS number" in page
    assert "<code>0000004</code>" in alice.get("/samples/").data.decode()
    for q in ("0000004", "4"):
        assert alice.get(f"/go?q={q}").headers["Location"].endswith(sid("PF", "TUM", "CPU", 2))
    # the API gives the seven-digit form too
    assert alice.get(f"/api/samples/{sid('PF', 'PFM', 'CPU', 1)}").get_json()["sample"]["lims_number"] == "0000000"
    # printed under the 2D code, seven digits
    assert ">0000000</text>" in alice.get(f"/samples/{sid('PF', 'PFM', 'CPU', 1)}/label.svg?print=1").data.decode()


def test_concurrent_registrations_never_share_a_number(app, alice):
    cid = new_collection(alice)
    with app.app_context():
        user = dict(get_db().execute("SELECT * FROM account WHERE username='alice'").fetchone())
    payload = {"collection_id": cid, "fraction": "PFM", "material": "CPU", "count": 3, "created_datetime": "2026-09-29T10:00",
               "created_by": "AA", "sop_code": "NA", "biobank_source": "IH", "quantity": 1, "unit": "mL", "freezer": "NA",
               "rack": "NA", "box": "NA", "position": "NA", "status": "Available", "notes": "NA"}
    errors, barrier = [], threading.Barrier(8)

    def worker():
        try:
            barrier.wait()                          # all eight start together
            with app.app_context():                 # (before taking a connection: the Postgres pool holds only two)
                g.user = user
                conn = get_db()
                svc.create_samples(conn, dict(payload))
                conn.commit()
        except Exception as e:                      # surfaced below
            errors.append(repr(e))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert errors == []
    serials = _serials(app)
    assert serials == list(range(24))               # 8 x 3 tubes: unique, no gaps
    with app.app_context():
        assert get_db().execute("SELECT count(DISTINCT sample_id) FROM sample").fetchone()[0] == 24


def test_ceiling_and_unique_backstop(app, alice):
    cid = new_collection(alice)
    with app.app_context():
        conn = get_db()
        conn.execute("UPDATE id_counter SET value=9999998 WHERE name='sample_serial'")
        conn.commit()
    add_tubes(alice, cid)
    assert _serials(app) == [9999999]
    r = add_tubes(alice, cid)
    assert b"LIMS numbers are exhausted" in r.data and _serials(app) == [9999999]
    # the database itself refuses a duplicate even if code went wrong
    with app.app_context():
        conn = get_db()
        try:
            conn.execute("UPDATE sample SET serial=9999999 WHERE serial IS NULL OR serial<>9999999")
            conn.execute("INSERT INTO sample(sample_id, serial, project_code, cohort_code, participant_id, unc_id, received_date, "
                         "specimen_code, fraction_code, material_code, aliquot, processing_date, collection_id, root_id) "
                         "SELECT 'X', 9999999, project_code, cohort_code, participant_id, unc_id, received_date, specimen_code, "
                         "fraction_code, material_code, 99, processing_date, collection_id, root_id FROM sample")
            assert False, "duplicate number accepted"
        except Exception as e:
            assert "unique" in str(e).lower() or "duplicate" in str(e).lower()
            conn.rollback()


def test_existing_tubes_are_numbered_in_creation_order(app, alice):
    from lims.db import init_db
    cid = new_collection(alice)
    add_tubes(alice, cid, count="3")
    with app.app_context():
        conn = get_db()
        conn.execute("UPDATE sample SET serial=NULL")
        conn.execute("UPDATE id_counter SET value=-1")
        conn.execute("UPDATE sample SET record_created_at='2020-01-01T00:00:00Z' WHERE sample_id=?", (sid("PF", "PFM", "CPU", 3),))
        conn.commit()
        init_db(conn)
        got = {r[0]: r[1] for r in conn.execute("SELECT sample_id, serial FROM sample")}
    assert got[sid("PF", "PFM", "CPU", 3)] == 0 and sorted(got.values()) == [0, 1, 2]
    add_tubes(alice, cid)
    assert _serials(app) == [0, 1, 2, 3]
