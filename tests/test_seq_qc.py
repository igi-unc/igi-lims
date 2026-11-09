"""Sequencing QC results posted by the QC workflow (through the data librarian)."""
from lims.db import get_db
from conftest import sid, new_collection, add_tubes, derive

READ, WRITE = {"X-Api-Token": "bot-read"}, {"X-Api-Token": "bot-write"}
R1, R2 = "/proj/igi/run1/x_R1.fastq.gz", "/proj/igi/run1/x_R2.fastq.gz"


def _setup(app, alice, monkeypatch):
    cid = new_collection(alice)
    add_tubes(alice, cid)
    derive(alice, sid("PF", "PFM", "CPU", 1), fraction="TUM", material="DNA")
    dna = sid("PF", "TUM", "DNA", 1)
    monkeypatch.setenv("LIMS_API_TOKEN", "bot-read")
    monkeypatch.setenv("LIMS_API_WRITE_TOKEN", "bot-write")
    c = app.test_client()
    r = c.post(f"/api/samples/{dna}/files", headers=WRITE, json={"registry_id": "igi_x", "instance": "igi", "paths": [R1, R2],
                                                                 "accessioned_by": "U1", "approved_by": "U2"})
    assert r.status_code == 201
    return c, dna


def _body(**over):
    b = {"workflow_id": "igi_qc", "workflow_version": "0.1.0", "workflow_run_id": "run-001", "scheduler_job_id": "12345",
         "registry_id": "igi_x",
         "results": [{"path": R1, "qc_status": "pass", "md5": "0" * 32,
                      "metrics": {"total_reads": 1000000, "total_bases": 150000000, "pct_q30": 93.2, "pct_gc": 41.0,
                                  "fastqc_overrepresented": "none", "per_tile_ok": True}},
                     {"path": R2, "qc_status": "warn", "status_reason": "adapter content 6% > 5%", "metrics": {"pct_adapter": 6.0}},
                     {"qc_status": "pass", "metrics": {"mean_coverage": 31.5, "pct_duplication": 8.1},
                      "report_uri": "/proj/igi/qc/run-001/multiqc_report.html"}]}
    b.update(over)
    return b


def test_post_and_read_qc(app, alice, monkeypatch):
    c, dna = _setup(app, alice, monkeypatch)
    assert c.post(f"/api/samples/{dna}/qc", json=_body(), headers=READ).status_code == 401      # read token cannot write
    r = c.post("/api/samples/1/qc", json=_body(), headers=WRITE)
    assert r.status_code == 201 and r.get_json()["created"] == 3 and r.get_json()["md5_mismatch_file_ids"] == []
    j = c.get("/api/samples/1/qc", headers=READ).get_json()
    assert len(j["results"]) == 3
    byuri = {x["uri"]: x for x in j["results"]}
    assert byuri[R1]["total_reads"] == 1000000 and byuri[R1]["pct_q30"] == 93.2
    assert byuri[R1]["metrics"] == {"fastqc_overrepresented": "none", "per_tile_ok": True}
    assert byuri[R2]["qc_status"] == "warn" and byuri[None]["mean_coverage"] == 31.5
    with app.app_context():
        db = get_db()
        # the md5 the workflow computed fills an empty checksum
        assert db.execute("SELECT checksum_md5 FROM data_file WHERE uri=?", (R1,)).fetchone()[0] == "0" * 32
        assert db.execute("SELECT COUNT(*) FROM audit_log WHERE table_name='seq_qc' AND username='bot:igi'").fetchone()[0] == 3
    # re-posting the same run replaces, never duplicates; a different md5 is reported, not overwritten
    b = _body()
    b["results"][0].update(qc_status="fail", md5="f" * 32)
    r = c.post(f"/api/samples/{dna}/qc", json=b, headers=WRITE)
    assert r.status_code == 200 and r.get_json()["updated"] == 3 and len(r.get_json()["md5_mismatch_file_ids"]) == 1
    assert "IGI-" not in r.get_data(as_text=True) and "/proj/" not in r.get_data(as_text=True)    # no PHI echoed
    j = c.get(f"/api/samples/{dna}/qc", headers=READ).get_json()
    assert len(j["results"]) == 3 and {x["uri"]: x for x in j["results"]}[R1]["qc_status"] == "fail"
    with app.app_context():
        assert get_db().execute("SELECT checksum_md5 FROM data_file WHERE uri=?", (R1,)).fetchone()[0] == "0" * 32
    # a second run adds rows alongside
    assert c.post(f"/api/samples/{dna}/qc", json=_body(workflow_run_id="run-002"), headers=WRITE).get_json()["created"] == 3
    # shown on the tube page, with the md5 warning
    page = alice.get(f"/samples/{dna}").data.decode()
    assert "Sequencing QC" in page and "qc-warn" in page and "adapter content 6%" in page and "md5 differs" in page
    assert "1,000,000 reads" in page and "multiqc_report.html" in page


def test_qc_validation(app, alice, monkeypatch):
    c, dna = _setup(app, alice, monkeypatch)
    post = lambda body: c.post(f"/api/samples/{dna}/qc", json=body, headers=WRITE)
    assert post(_body(workflow_id="")).status_code == 400
    assert post(_body(results=[])).status_code == 400
    bad = post(_body(results=[{"path": "/not/linked.bam", "qc_status": "pass"},
                              {"path": R1, "qc_status": "great"},
                              {"path": R2, "qc_status": "pass", "metrics": {"pct_q30": 130, "total_reads": -5, "x y": 1}},
                              {"qc_status": "pass", "md5": "abc"}]))
    problems = bad.get_json()["problems"]
    assert bad.status_code == 400 and len(problems) == 8, problems   # incl. md5 without a path and two whole-dataset entries
    assert post(_body(results=[{"path": R1, "qc_status": "pass"}, {"path": R1, "qc_status": "fail"}])).status_code == 400
    assert c.post("/api/samples/IGI-NOPE/qc", json=_body(), headers=WRITE).status_code == 404
    assert c.get("/api/samples/IGI-NOPE/qc", headers=READ).status_code == 404
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM seq_qc").fetchone()[0] == 0        # nothing half-written
    assert "No QC results yet" in alice.get(f"/samples/{dna}").data.decode()


def test_quick_qc_libraries_and_checks(app, alice, monkeypatch):
    """quick-qc style: one result per library (several per tube), PASS/WARN/FAIL/NA per named check."""
    c, dna = _setup(app, alice, monkeypatch)
    body = {"workflow_id": "quick-qc", "workflow_version": "1.0.0-dev", "workflow_run_id": "r1",
            "results": [
                {"library": "ad-wes-tumor", "path": R1, "qc_status": "WARN", "metrics": {"mean_coverage": 42.0, "intron_frac": 0.01},
                 "checks": [{"check": "reads.coverage", "status": "WARN", "observed": "42x", "expected": ">= 50x", "reason": "below WES warn"},
                            {"check": "assay.capture", "status": "PASS"}, {"check": "singlecell.barcodes", "status": "NA"}]},
                {"library": "ad-wgs-tumor", "path": R1, "qc_status": "PASS", "metrics": {"mean_coverage": 31.0},
                 "checks": [{"check": "reads.coverage", "status": "PASS"}]}]}
    r = c.post(f"/api/samples/{dna}/qc", json=body, headers=WRITE)
    assert r.status_code == 201 and r.get_json()["created"] == 2, r.get_json()
    res = {x["library_name"]: x for x in c.get(f"/api/samples/{dna}/qc", headers=READ).get_json()["results"]}
    assert res["ad-wes-tumor"]["qc_status"] == "warn"
    assert {x["check"]: x["status"] for x in res["ad-wes-tumor"]["checks"]} == {
        "reads.coverage": "warn", "assay.capture": "pass", "singlecell.barcodes": "not_assessed"}
    # re-posting replaces the checks rather than appending
    body["results"][0]["checks"] = [{"check": "reads.coverage", "status": "PASS"}]
    assert c.post(f"/api/samples/{dna}/qc", json=body, headers=WRITE).get_json()["updated"] == 2
    res = {x["library_name"]: x for x in c.get(f"/api/samples/{dna}/qc", headers=READ).get_json()["results"]}
    assert [x["check"] for x in res["ad-wes-tumor"]["checks"]] == ["reads.coverage"]
    bad = c.post(f"/api/samples/{dna}/qc", headers=WRITE, json={**body, "results": [
        {"library": "x", "qc_status": "PASS", "checks": [{"check": "a b", "status": "PASS"}, {"check": "ok", "status": "MAYBE"},
                                                       {"check": "dup", "status": "PASS"}, {"check": "dup", "status": "FAIL"}]}]})
    assert bad.status_code == 400 and len(bad.get_json()["problems"]) == 3
    # the overview page and its data: rows carry assay/platform from the file, every numeric metric, the checks
    assert b"Sequencing QC" in alice.get("/seq-qc/").data
    rows = alice.get("/seq-qc/data.json").get_json()["rows"]
    wes = next(r for r in rows if r["library"] == "ad-wes-tumor")
    assert wes["file"] == "x_R1.fastq.gz"
    assert wes["metrics"] == {"mean_coverage": 42.0, "intron_frac": 0.01} and wes["checks"] == {"reads.coverage": "pass"} and wes["latest"]
    page = alice.get(f"/samples/{dna}").data.decode()
    assert "ad-wes-tumor" in page and "1 checks" in page and "Charts for P101" in page


def test_qc_page_without_results_and_access(app, alice):
    assert b"No QC results yet" in alice.get("/seq-qc/").data
    assert app.test_client().get("/seq-qc/data.json").status_code in (302, 401)     # login required


def test_demo_has_fictional_quick_qc(app):
    from lims.demo import reset_demo
    from lims import seqqc
    with app.app_context():
        conn = get_db()
        info = reset_demo(conn, "pw")
        rows = seqqc.chart_rows(conn)
        assert info["qc_results"] == len(rows) >= 30
        assert {r["status"] for r in rows} == {"pass", "warn", "fail"}
        assert all("demo values" in r["version"] for r in rows) and all(r["assay"] != "?" for r in rows)
