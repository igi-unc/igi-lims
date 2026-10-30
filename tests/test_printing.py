"""Print queue and print station (Brady M611 via the Web SDK; the SDK itself is exercised in the browser)."""
import json
import re
from lims.db import get_db
from lims.auth import create_user
from conftest import sid, new_collection, add_tubes, login


def _station(app):
    with app.app_context():
        conn = get_db()
        create_user(conn, "station", "Print station", "PRN", "password1", "printer")
        conn.commit()


def test_queue_claim_and_finish(app, alice, client):
    _station(app)
    cid = new_collection(alice)
    r = add_tubes(alice, cid, count="3")
    tubes = [sid("PF", "PFM", "CPU", i) for i in (1, 2, 3)]
    # creating tubes offers to print exactly those tubes (on the page the form lands on)
    page = r.data.decode()
    assert "Send 3 label(s) to the printer" in page and all(f'value="{t}"' in page for t in tubes)
    assert "Send 3 label(s)" not in alice.get(f"/samples/{tubes[0]}").data.decode()     # offered once
    r = alice.post("/print/jobs", data={"sample_id": tubes, "next": f"/samples/{tubes[0]}"}, follow_redirects=True)
    assert b"Sent 3 label(s) to the printer as job #1" in r.data
    add_tubes(alice, cid, fraction="PFS", material="FRZ")
    other = sid("PF", "PFS", "FRZ")
    alice.post("/print/jobs", data={"sample_id": [other], "header": "0"})
    assert b"#2" in alice.get("/print/jobs").data
    # the station claims the oldest job, with a header label first
    login(client, "station")
    j = client.post("/print/station/claim").get_json()
    job = j["job"]
    assert job["id"] == 1 and job["n_labels"] == 3 and j["queued"] == 1
    assert [i["kind"] for i in job["images"]] == ["header", "label", "label", "label"]
    assert [i.get("sample_id") for i in job["images"][1:]] == tubes
    # it can fetch exactly the images it prints
    svg = client.get(job["images"][1]["url"]).data.decode()
    assert 'width="300" height="150"' in svg and "<path" in svg
    assert re.findall(r">([^<]+)</text>", svg) == ["IGI-MP-P101-UNC316", "26SEP29-PF-PFM-CPU", "01-AA-26SEP29"]
    assert "PRINT JOB #1" in client.get(job["images"][0]["url"]).data.decode()
    # the wrong token is refused; the right one finishes the job
    assert client.post("/print/station/1/done", json={"token": "nope", "ok": True}).status_code == 409
    assert client.post("/print/station/1/done", json={"token": job["token"], "ok": True}).get_json()["ok"]
    j2 = client.post("/print/station/claim").get_json()["job"]
    assert j2["id"] == 2 and [i["kind"] for i in j2["images"]] == ["label"]
    client.post("/print/station/2/done", json={"token": j2["token"], "ok": False, "error": "Out of labels"})
    assert client.post("/print/station/claim").get_json()["job"] is None
    with app.app_context():
        rows = {r["id"]: (r["status"], r["error"]) for r in get_db().execute("SELECT id, status, error FROM print_job")}
    assert rows == {1: ("printed", None), 2: ("failed", "Out of labels")}
    # the job as a spreadsheet for Brady's own apps
    login(client, "alice")
    csv_text = client.get("/print/jobs/1.csv").data.decode().splitlines()
    assert csv_text[0] == "barcode,line1,line2,line3"
    assert csv_text[1] == f"{tubes[0]},IGI-MP-P101-UNC316,26SEP29-PF-PFM-CPU,01-AA-26SEP29" and len(csv_text) == 4
    # the requester can requeue the failed job
    login(client, "alice")
    r = client.post("/print/jobs/2/requeue", follow_redirects=True)
    assert b"requeue done" in r.data
    login(client, "station")
    assert client.post("/print/station/claim").get_json()["job"]["id"] == 2


def test_station_account_sees_nothing_else(app, alice, client):
    _station(app)
    cid = new_collection(alice)
    add_tubes(alice, cid)
    # the station's initials never appear as an operator choice or pass as one
    form = alice.get(f"/collections/{cid}/tubes").data.decode()
    assert 'value="PRN"' not in form
    r = add_tubes(alice, cid, created_by="PRN")
    assert b"not an active user" in r.data
    login(client, "station")
    r = client.get("/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/print/station")
    for url in ("/browse", "/samples/", f"/collections/{cid}", "/participants/P101", "/admin/audit", "/print/jobs", "/api/samples"):
        r = client.get(url)
        assert r.status_code == 302 and "/print/station" in r.headers["Location"], url
    assert client.post("/print/jobs", data={"sample_id": sid("PF", "PFM", "CPU")}).status_code == 403
    assert client.post(f"/collections/{cid}/tubes", data={}).status_code == 403
    page = client.get("/print/station").data.decode()
    assert "Connect printer" in page and "station.js" in page
    # Windows-printer mode: the kiosk-printing shortcut for this very page, and label-sized print pages
    assert "--kiosk-printing --app=http://localhost/print/station" in page
    assert 'id="st-orient"' in page and 'value="landscape-flip"' in page and 'value="portrait-right"' in page and 'id="st-wcal"' in page and 'id="print-area"' in page
    assert "LAYOUT C" in client.get("/print/station/align.svg?tag=c").data.decode()
    assert client.get("/print/station/align.svg").status_code == 200 and ">TOP<" in client.get("/print/station/align.svg").data.decode()
    js = client.get("/static/station.js").data.decode()
    assert "rotate(-90deg)" in js and "@page lay-${o} { size: ${r.pw}in ${r.ph}in" in js and "page: lay-${o}" in js
    assert "<nav>" not in page                                  # the station account gets no menu
    assert client.get("/print/station/test.svg").status_code == 200


def test_ordinary_users_cannot_claim_and_viewers_cannot_queue(app, client):
    login(client, "bob")
    assert client.post("/print/station/claim").status_code == 403
    login(client, "vic")
    assert client.post("/print/jobs", data={"sample_id": "x"}).status_code == 403
    assert client.get("/print/jobs").status_code == 200                     # viewers can see the queue


def test_job_validation_and_collection_selection(app, alice):
    cid = new_collection(alice)
    add_tubes(alice, cid, count="2")
    r = alice.post("/print/jobs", data={}, follow_redirects=True)
    assert b"Choose at least one tube" in r.data
    r = alice.post("/print/jobs", data={"sample_id": ["IGI-NOPE"]}, follow_redirects=True)
    assert b"No tube IGI-NOPE" in r.data
    page = alice.get(f"/collections/{cid}").data.decode()
    assert 'id="print-form"' in page and page.count('name="sample_id"') == 2
    # duplicates collapse, order is kept
    alice.post("/print/jobs", data={"sample_id": [sid("PF", "PFM", "CPU", 2), sid("PF", "PFM", "CPU", 1), sid("PF", "PFM", "CPU", 2)]})
    with app.app_context():
        ids = json.loads(get_db().execute("SELECT sample_ids FROM print_job").fetchone()[0])
    assert ids == [sid("PF", "PFM", "CPU", 2), sid("PF", "PFM", "CPU", 1)]


def test_print_label_geometry(app):
    from lims.labels import label_print_svg, barcode_matrix
    with app.app_context():
        svg = label_print_svg({"sample_id": "IGI-MP-P101-UNC316-26SEP29-PF-TUM-HMD-01-KEN-26OCT06"})
    assert 'width="300" height="150"' in svg
    n = len(barcode_matrix("IGI-MP-P101-UNC316-26SEP29-PF-TUM-HMD-01-KEN-26OCT06"))
    module = (150 - 2 * 6) // (n + 2)
    assert module >= 3                                 # at least 0.25 mm per module at 300 dpi
    # every path segment is on whole dots
    assert all(float(v).is_integer() for v in re.findall(r"[Mhv](-?[\d.]+)", svg))


def test_each_label_is_printed_once(app, alice, client):
    _station(app)
    cid = new_collection(alice)
    add_tubes(alice, cid, count="2")
    t1, t2 = sid("PF", "PFM", "CPU", 1), sid("PF", "PFM", "CPU", 2)
    alice.post("/print/jobs", data={"sample_id": [t1]})
    # already waiting: cannot be queued again
    r = alice.post("/print/jobs", data={"sample_id": [t1, t2]}, follow_redirects=True)
    assert b"already waiting in print job #1" in r.data
    login(client, "station")
    job = client.post("/print/station/claim").get_json()["job"]
    client.post(f"/print/station/{job['id']}/done", json={"token": job["token"], "ok": True})
    login(client, "alice")
    # printed: refused without a reason, from any page
    r = client.post("/print/jobs", data={"sample_id": [t1, t2]}, follow_redirects=True)
    assert b"already has a printed label" in r.data
    with app.app_context():
        assert get_db().execute("SELECT count(*) FROM print_job").fetchone()[0] == 1
    page = client.get(f"/samples/{t1}").data.decode()
    assert "label printed" in page and "Reprint this label" in page and "Send this label to the printer" not in page
    coll = client.get(f"/collections/{cid}").data.decode()
    assert f'value="{t1}"' not in coll and f'value="{t2}"' in coll and ">printed<" in coll
    # a printed job cannot simply be requeued
    r = client.post("/print/jobs/1/requeue", follow_redirects=True)
    assert b"reprinted one tube at a time" in r.data
    # a deliberate reprint with a reason is accepted, flagged and recorded
    r = client.post("/print/jobs", data={"sample_id": [t1], "reprint_reason": "label smudged in LN2"}, follow_redirects=True)
    assert b"as job #2" in r.data
    assert b"label smudged in LN2" in client.get("/admin/audit?changes=1").data
    login(client, "station")
    job = client.post("/print/station/claim").get_json()["job"]
    client.post(f"/print/station/{job['id']}/done", json={"token": job["token"], "ok": True})
    with app.app_context():
        rows = get_db().execute("SELECT job_id, reprint_reason FROM label_print WHERE sample_id=? ORDER BY id", (t1,)).fetchall()
    assert [tuple(r) for r in rows] == [(1, None), (2, "label smudged in LN2")]
    login(client, "alice")
    assert "printed 2 times" in client.get(f"/samples/{t1}").data.decode()


def test_stuck_job_requeue_needs_a_reason(app, alice, client):
    _station(app)
    cid = new_collection(alice)
    add_tubes(alice, cid)
    alice.post("/print/jobs", data={"sample_id": [sid("PF", "PFM", "CPU")]})
    login(client, "station")
    client.post("/print/station/claim")                      # station takes it and never reports back
    login(client, "alice")
    r = client.post("/print/jobs/1/requeue", follow_redirects=True)
    assert b"may already have printed" in r.data
    r = client.post("/print/jobs/1/requeue", data={"reason": "printer jammed, nothing came out"}, follow_redirects=True)
    assert b"requeue done" in r.data
    with app.app_context():
        assert get_db().execute("SELECT status, reprint_reason FROM print_job WHERE id=1").fetchone()[0] == "queued"


def test_upgrade_from_first_printing_release(app, alice):
    """A database from the first printing release (print_job without reprint_reason, no label_print) upgrades itself."""
    from lims.db import is_postgres
    with app.app_context():
        conn = get_db()
        c = " CASCADE" if is_postgres(conn) else ""
        conn.execute("DROP TABLE label_print" + c)
        conn.execute("DROP TABLE print_job" + c)
        key = "id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY" if is_postgres(conn) else "id INTEGER PRIMARY KEY AUTOINCREMENT"
        conn.execute(f"CREATE TABLE print_job ({key}, requested_by TEXT NOT NULL, requested_initials TEXT, "
                     "requested_at TEXT, sample_ids TEXT NOT NULL, n_labels INTEGER NOT NULL, header INTEGER NOT NULL DEFAULT 1, "
                     "status TEXT NOT NULL DEFAULT 'queued', station TEXT, claim_token TEXT, claimed_at TEXT, finished_at TEXT, error TEXT)")
        conn.commit()
    app.extensions.pop("igi_schema_ok", None)
    cid = new_collection(alice)
    add_tubes(alice, cid)
    r = alice.post("/print/jobs", data={"sample_id": [sid("PF", "PFM", "CPU")]}, follow_redirects=True)
    assert b"Sent 1 label(s)" in r.data
    with app.app_context():
        assert get_db().execute("SELECT count(*) FROM label_print").fetchone()[0] == 0
