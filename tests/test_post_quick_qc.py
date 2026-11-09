"""tools/post_quick_qc.py builds the LIMS's QC request from a quick-qc report directory (documented layout)."""
import importlib.util
import json
import os
import pathlib

from conftest import sid, new_collection, add_tubes, derive

spec = importlib.util.spec_from_file_location("pqq", pathlib.Path(__file__).parent.parent / "tools" / "post_quick_qc.py")
pqq = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pqq)


def _report(tmp):
    d = tmp / "qc_report"
    (d / "DS1" / "P1" / "ad-wes-tumor" / "qc").mkdir(parents=True)
    (d / "qc_samples.tsv").write_text("Dataset\tPatient_Name\tRun_Name\tstatus\treads\n"
                                      "DS1\tP1\tad-wes-tumor\tWARN\t1000\nDS1\tP1\tnot-ours\tPASS\t5\n")
    (d / "qc_checks.tsv").write_text("Dataset\tPatient_Name\tRun_Name\tcheck\tstatus\tobserved\texpected\treason\n"
                                     "DS1\tP1\tad-wes-tumor\treads.coverage\tWARN\t42x\t>= 50x\tlow\n"
                                     "DS1\tP1\tad-wes-tumor\tspecies\tPASS\t0.99\t\t\n")
    (d / "DS1" / "P1" / "ad-wes-tumor" / "qc" / "ad-wes-tumor.metrics.json").write_text(
        json.dumps({"total_reads": 1000, "mean_coverage": 42.0, "nested": {"x": 1}, "inferred_sex": "F"}))
    return d


def test_build_and_post(app, alice, monkeypatch, tmp_path):
    cid = new_collection(alice)
    add_tubes(alice, cid)
    derive(alice, sid("PF", "PFM", "CPU", 1), fraction="TUM", material="DNA")
    monkeypatch.setenv("LIMS_API_WRITE_TOKEN", "w")
    c = app.test_client()
    path = "/proj/x/ad-wes-tumor_R1.fastq.gz"
    assert c.post("/api/samples/1/files", headers={"X-Api-Token": "w"}, json={
        "registry_id": "r", "instance": "igi", "paths": [path], "accessioned_by": "U1", "approved_by": "U2"}).status_code == 201
    reqs = pqq.build_requests(str(_report(tmp_path)), "run-7", {"ad-wes-tumor": ("000001", path)}, "1.0.0-dev")
    assert len(reqs) == 1 and reqs[0][0] == "000001"
    res = reqs[0][1]["results"][0]
    assert res["library"] == "ad-wes-tumor" and res["qc_status"] == "WARN" and "nested" not in res["metrics"]
    assert [ch["check"] for ch in res["checks"]] == ["reads.coverage", "species"]
    r = c.post("/api/samples/000001/qc", headers={"X-Api-Token": "w"}, json=reqs[0][1])
    assert r.status_code == 201 and r.get_json()["created"] == 1, r.get_json()
