import json
"""Data-librarian (Slack bot) integration: registry prefill fields and the write-back of dataset links."""
from lims.db import get_db
from conftest import sid, new_collection, add_tubes, derive

READ, WRITE = {"X-Api-Token": "bot-read"}, {"X-Api-Token": "bot-write"}


def _tube(alice):
    cid = new_collection(alice)
    add_tubes(alice, cid)
    parent = sid("PF", "PFM", "CPU", 1)
    derive(alice, parent, fraction="TUM", material="HMD")
    return parent, sid("PF", "TUM", "HMD", 1)


def test_registry_fields(app, alice, monkeypatch):
    parent, dna = _tube(alice)
    monkeypatch.setenv("LIMS_API_TOKEN", "bot-read")
    c = app.test_client()
    assert c.get(f"/api/samples/{dna}/registry-fields").status_code == 401
    j = c.get(f"/api/samples/{dna}/registry-fields", headers=READ).get_json()
    assert j["found"] and j["lims_number"] == "000001" and not j["deleted"]
    assert j["safe"] == {"participant_id": "P101", "sample_type": "tumor", "analyte": "dna", "platform": None,
                         "library_type": None, "species": "human"}
    assert j["phi"]["sample_id"] == dna and j["phi"]["unc_id"] == "UNC316"
    # outside `phi` nothing identifies the patient: no sample ID, UNC ID or date anywhere else in the response
    outside = json.dumps({k: v for k, v in j.items() if k != "phi"})
    assert dna not in outside and "UNC316" not in outside and "26SEP29" not in outside and "2026-09-29" not in outside
    assert set(j["unmapped_reasons"]) == {"platform", "library_type"}
    # by LIMS number, with or without zeros, gives the same answer
    assert c.get("/api/samples/1/registry-fields", headers=READ).get_json()["phi"]["sample_id"] == dna
    assert c.get("/api/samples/000000001/registry-fields", headers=READ).get_json()["phi"]["sample_id"] == dna
    # CPU is not an analyte: null, never a guess
    assert c.get(f"/api/samples/{parent}/registry-fields", headers=READ).get_json()["safe"]["analyte"] is None
    r404 = c.get("/api/samples/IGI-NOPE/registry-fields", headers=READ)
    assert r404.status_code == 404 and r404.get_json() == {"found": False, "exists": False}
    # one platform and one assay on the tube's files -> mapped; mixed -> null
    with app.app_context():
        db = get_db()
        db.execute("INSERT INTO data_file(sample_id, uri, assay_code, platform_code, recorded_by) VALUES (?,?,?,?,?)",
                   (dna, "/data/a.bam", "WGS", "ONT", "alice"))
        db.commit()
    f = c.get(f"/api/samples/{dna}/registry-fields", headers=READ).get_json()["safe"]
    assert f["platform"] == "ont" and f["library_type"] == "wgs"
    with app.app_context():
        db = get_db()
        db.execute("INSERT INTO data_file(sample_id, uri, assay_code, platform_code, recorded_by) VALUES (?,?,?,?,?)",
                   (dna, "/data/b.bam", "WES", "ILM", "alice"))
        db.commit()
    f = c.get(f"/api/samples/{dna}/registry-fields", headers=READ).get_json()["safe"]
    assert f["platform"] is None and f["library_type"] is None


def test_post_files_write_back(app, alice, monkeypatch):
    _, dna = _tube(alice)
    c = app.test_client()
    body = {"registry_id": "igi_p101_igimp_tumor_dna_ont", "instance": "igi", "paths": ["/proj/igi/run1/a.bam", "/proj/igi/run1/a.bam.bai"],
            "accessioned_by": "U123", "approved_by": "U456"}
    # no write token configured: writes are off, even with the read token
    monkeypatch.setenv("LIMS_API_TOKEN", "bot-read")
    assert c.post("/api/samples/1/files", json=body, headers=READ).status_code == 403
    monkeypatch.setenv("LIMS_API_WRITE_TOKEN", "bot-write")
    assert c.post("/api/samples/1/files", json=body, headers=READ).status_code == 401      # read token cannot write
    assert alice.post("/api/samples/1/files", json=body).status_code == 401                # nor can a browser session
    bad = c.post("/api/samples/1/files", json={**body, "paths": [], "instance": "IGI LIMS!"}, headers=WRITE)
    assert bad.status_code == 400 and len(bad.get_json()["problems"]) == 2
    assert c.post("/api/samples/1/files", json={**body, "assay_code": "XYZ"}, headers=WRITE).status_code == 400
    r = c.post("/api/samples/1/files", json={**body, "assay_code": "wgs", "platform_code": "ONT"}, headers=WRITE)
    assert r.status_code == 201 and r.get_json()["created"] == 2 and r.get_json()["status"] == "created"
    assert "IGI-" not in r.get_data(as_text=True) and "/proj/" not in r.get_data(as_text=True)    # no PHI echoed
    # a retry is idempotent
    r = c.post(f"/api/samples/{dna}/files", json=body, headers=WRITE)
    assert r.status_code == 200 and r.get_json()["created"] == 0 and r.get_json()["already_linked"] == 2
    assert r.get_json()["status"] == "exists"
    with app.app_context():
        db = get_db()
        rows = db.execute("SELECT * FROM data_file WHERE sample_id=? ORDER BY id", (dna,)).fetchall()
        assert len(rows) == 2 and rows[0]["registry_id"] == body["registry_id"] and rows[0]["registry_instance"] == "igi"
        assert rows[0]["recorded_by"] == "bot:igi" and "U123" in rows[0]["notes"] and rows[0]["assay_code"] == "WGS"
        assert db.execute("SELECT COUNT(*) FROM audit_log WHERE table_name='data_file' AND username='bot:igi'").fetchone()[0] == 2
    # the same path cannot be claimed by another tube
    r = c.post(f"/api/samples/{sid('PF', 'PFM', 'CPU', 1)}/files", json={**body, "registry_id": "other"}, headers=WRITE)
    assert r.status_code == 409 and "IGI-" not in r.get_data(as_text=True) and "/proj/" not in r.get_data(as_text=True)
    # shown on the tube page
    page = alice.get(f"/samples/{dna}").data.decode()
    assert body["registry_id"] in page and "registry (igi)" in page
    assert c.post("/api/samples/999999/files", json=body, headers=WRITE).status_code == 404


def test_existing_database_gains_registry_columns(app, alice):
    """A database from before this version (no registry columns) is upgraded by the first request, data kept."""
    _, dna = _tube(alice)
    with app.app_context():
        db = get_db()
        db.execute("DROP INDEX IF EXISTS idx_file_registry")
        for col in ("registry_id", "registry_instance"):
            db.execute(f"ALTER TABLE data_file DROP COLUMN {col}")
        db.commit()
    app.extensions.pop("igi_schema_ok", None)
    assert alice.get(f"/samples/{dna}").status_code == 200
    with app.app_context():
        cols = {r[1] for r in get_db().execute("PRAGMA table_info(data_file)")} if not app.config.get("DATABASE_URL") else None
        if cols is not None:
            assert {"registry_id", "registry_instance"} <= cols
        assert get_db().execute("SELECT COUNT(*) FROM sample").fetchone()[0] == 2


def test_registry_platform_pacbio_and_10x_ont(app, alice, monkeypatch):
    cid = new_collection(alice)
    add_tubes(alice, cid)
    derive(alice, sid("PF", "PFM", "CPU", 1), fraction="TUM", material="SCS")
    scs = sid("PF", "TUM", "SCS", 1)
    monkeypatch.setenv("LIMS_API_TOKEN", "bot-read")
    c = app.test_client()
    with app.app_context():
        db = get_db()
        db.execute("INSERT INTO data_file(sample_id, uri, assay_code, platform_code, recorded_by) VALUES (?,?,?,?,?)",
                   (scs, "/data/sc_ont.fastq.gz", "SCR", "ONT", "alice"))
        db.commit()
    assert c.get(f"/api/samples/{scs}/registry-fields", headers=READ).get_json()["safe"]["platform"] == "10x-ont"
    with app.app_context():
        db = get_db()
        db.execute("UPDATE data_file SET platform_code='PAC' WHERE sample_id=?", (scs,))
        db.commit()
    assert c.get(f"/api/samples/{scs}/registry-fields", headers=READ).get_json()["safe"]["platform"] == "pacbio"
