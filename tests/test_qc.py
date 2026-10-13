import io
import os
import pytest
from lims import qc_parsers
from lims.db import get_db
from conftest import make_root, derive, login

FX = os.path.join(os.path.dirname(__file__), "fixtures", "instrument_exports")
P = "IGI-MP-KXRTQVA-260929-"


def test_qubit_parser():
    ms = qc_parsers.parse_qubit4(os.path.join(FX, "qubit4_example_1.csv"))
    assert [m.sample_name for m in ms] == ["Sample_#231212-064054", "Sample_#231212-020958"]
    assert ms[0].values["concentration_ng_ul"] == (6.08, "ng/µL")
    assert ms[1].values["concentration_ng_ul"][0] == 112.0
    assert ms[0].values["concentration_method"][0] == "Qubit"


def test_nanodrop_parser():
    ms = qc_parsers.parse_nanodrop_one(os.path.join(FX, "nanodrop_one_dsDNA.csv"))
    assert ms[0].sample_name == "Sample 1"
    assert ms[0].values["concentration_ng_ul"][0] == 715.462
    assert ms[0].values["a260_280"][0] == 1.882 and ms[0].values["a260_230"][0] == 1.954


def test_tapestation_rna_parser():
    ms = qc_parsers.parse_tapestation(os.path.join(FX, "tapestation_example_01.xml"))
    assert all(m.extra["observations"] != "Ladder" for m in ms)
    a1 = ms[0]
    assert a1.extra["well"] == "A1" and a1.values["rin"][0] == 8.6 and a1.values["concentration_ng_ul"][0] == 363.0


def test_tapestation_cfdna_parser():
    ms = qc_parsers.parse_tapestation(os.path.join(FX, "tapestation_example_03.xml"))
    b1 = ms[0]
    assert b1.extra["well"] == "B1" and b1.values["concentration_ng_ul"][0] == 646.0
    assert b1.values["mean_fragment_bp"][0] == 375.0 and b1.values["cfdna_peak_bp"][0] == 375.0
    assert abs(b1.values["concentration_nm"][0] - 1.77) < 1e-9


def test_countess_parser_and_detect():
    path = os.path.join(FX, "countess3_synthetic.csv")
    assert qc_parsers.detect(path, "countess3_synthetic.csv") == "countess3"
    ms = qc_parsers.parse_countess3(path)
    assert ms[0].sample_name == P + "PF-TUM-CPU-01"
    assert ms[0].values["viability_pct"] == (86.2, "%") and ms[0].values["concentration_cells_ml"][0] == 1.52e6
    assert qc_parsers.detect(os.path.join(FX, "qubit4_example_1.csv"), "x.csv") == "qubit4"
    assert qc_parsers.detect(os.path.join(FX, "nanodrop_one_dsDNA.csv"), "x.csv") == "nanodrop_one"
    assert qc_parsers.detect(os.path.join(FX, "tapestation_example_01.xml"), "x.xml") == "tapestation"


def test_import_flow_writes_attributes_with_provenance(app, alice, tmp_path):
    app.config["ATTACHMENT_DIR"] = str(tmp_path)
    make_root(alice)
    derive(alice, P + "PF-BLK-NAT-01", fraction="TUM", material="CPU")
    with open(os.path.join(FX, "countess3_synthetic.csv"), "rb") as f:
        r = alice.post("/qc/import", data={"file": (io.BytesIO(f.read()), "countess3_synthetic.csv"), "instrument": ""},
                       content_type="multipart/form-data")
    assert r.status_code == 302 and "/qc/import/" in r.headers["Location"]
    page = alice.get(r.headers["Location"]).data.decode()
    assert "Countess 3" in page and f'value="{P}PF-TUM-CPU-01"' in page   # auto-matched from the sample name
    r = alice.post(r.headers["Location"], data={"tube_0": P + "PF-TUM-CPU-01", "use_0_viability_pct": "1",
                                                "use_0_concentration_cells_ml": "1", "use_0_count_method": "1"}, follow_redirects=True)
    assert b"Wrote values to 1 tube" in r.data
    with app.app_context():
        conn = get_db()
        rows = {r["key"]: r for r in conn.execute("SELECT * FROM sample_attribute WHERE sample_id=?", (P + "PF-TUM-CPU-01",))}
        assert rows["viability_pct"]["value"] == "86.2" and rows["viability_pct"]["source_attachment_id"] == 1
        assert rows["count_method"]["value"] == "Countess"
        assert "concentration_cells_ml" in rows and "cells_counted" not in rows
        att = conn.execute("SELECT * FROM attachment WHERE id=1").fetchone()
        assert att["kind"] == "qc_export" and att["instrument"] == "countess3" and att["sample_id"] is None
        assert os.path.exists(os.path.join(str(tmp_path), att["stored_path"]))
    html = alice.get(f"/samples/{P}PF-TUM-CPU-01").data.decode()
    assert "Viability" in html and "86.2" in html and "file #1" in html and "countess3_synthetic.csv" in html
    assert "(shared import)" in html


def test_import_bad_file(app, alice, tmp_path):
    app.config["ATTACHMENT_DIR"] = str(tmp_path)
    r = alice.post("/qc/import", data={"file": (io.BytesIO(b"hello,world\n1,2\n"), "junk.csv"), "instrument": ""},
                   content_type="multipart/form-data", follow_redirects=True)
    assert b"Could not recognise the instrument format" in r.data


def test_attributes_on_create_edit_and_required(app, alice, client, tmp_path):
    make_root(alice, attr_container_type="EDTA", attr_appearance="clear", attr_qc_result="pass")
    with app.app_context():
        vals = {r["key"]: r["value"] for r in get_db().execute("SELECT key, value FROM sample_attribute WHERE sample_id=?", (P + "PF-BLK-NAT-01",))}
    assert vals == {"container_type": "EDTA", "appearance": "clear", "qc_result": "pass"}
    # invalid choice is rejected before anything is written
    r = derive(alice, P + "PF-BLK-NAT-01", fraction="BLK", material="CPU", attr_storage_phase="moon")
    assert b"Storage phase must be one of" in r.data
    # LIB requires an assay
    derive(alice, P + "PF-BLK-NAT-01", fraction="BLK", material="DNA")
    r = derive(alice, P + "PF-BLK-DNA-01", fraction="BLK", material="LIB", attr_assay="")
    assert b"Assay is required" in r.data
    r = derive(alice, P + "PF-BLK-DNA-01", fraction="BLK", material="LIB", attr_assay="WGS", attr_pcr_cycles="6")
    assert b"Created 1" in r.data
    # editing an attribute goes through approval like any other edit
    sid = P + "PF-BLK-LIB-01"
    r = alice.post(f"/samples/{sid}/edit", data={"parent_id": P + "PF-BLK-DNA-01", "status": "Available", "quantity": "1", "unit": "NA", "created_by": "AA",
                                                 "created_datetime": "2026-09-29T10:00", "sop_code": "NA", "biobank_source": "IH",
                                                 "freezer": "NA", "rack": "NA", "box": "NA", "position": "A1", "notes": "NA",
                                                 "attr_assay": "WGS", "attr_pcr_cycles": "8", "justification": "typo"}, follow_redirects=True)
    assert b"Change request #1 submitted" in r.data
    login(client, "bob")
    client.post("/approvals/1/decide", data={"decision": "approve"}, follow_redirects=True)
    with app.app_context():
        assert get_db().execute("SELECT value FROM sample_attribute WHERE sample_id=? AND key='pcr_cycles'", (sid,)).fetchone()[0] == "8"


def test_attachment_upload_download_delete(app, alice, tmp_path):
    app.config["ATTACHMENT_DIR"] = str(tmp_path)
    make_root(alice)
    sid = P + "PF-BLK-NAT-01"
    r = alice.post(f"/samples/{sid}/attachments", data={"file": (io.BytesIO(b"trace data"), "trace.png"), "kind": "trace"},
                   content_type="multipart/form-data", follow_redirects=True)
    assert b"Attached trace.png" in r.data
    r = alice.get("/samples/attachments/1")
    assert r.status_code == 200 and r.data == b"trace data"
    alice.post("/samples/attachments/1/delete", follow_redirects=True)
    assert alice.get("/samples/attachments/1").status_code == 404


def test_admin_fields_page(app, alice):
    assert alice.get("/admin/fields?scope=material&code=LIB").status_code == 200
    r = alice.post("/admin/fields", data={"action": "add", "scope": "material", "code": "LIB", "key": "flowcell", "label": "Flowcell", "type": "text"}, follow_redirects=True)
    assert b"Field added" in r.data
    assert b"flowcell" in alice.get("/admin/fields?scope=material&code=LIB").data


def test_no_free_text_fields_in_seed(app):
    with app.app_context():
        rows = get_db().execute("SELECT key FROM attribute_definition WHERE active=1 AND type='text'").fetchall()
    assert rows == []


def test_coded_fields_rejected_when_not_in_list(app, alice):
    r = make_root(alice, freezer="F9")
    assert b"F9" in r.data and b"is not in the freezer list" in r.data
    r = make_root(alice, created_by="ZZ")
    assert b"ZZ" in r.data and b"is not an active user" in r.data
    r = make_root(alice, attr_container_type="PAPER_CUP")
    assert b"not in the container_type list" in r.data
    # admin adds the freezer, then it works
    alice.post("/admin/codes", data={"action": "add", "category": "freezer", "code": "F9", "meaning": "Basement -80 #9"}, follow_redirects=True)
    assert b"Created 1" in make_root(alice, freezer="F9").data


def test_custody_rejects_unknown_party(app, alice):
    make_root(alice)
    sid = P + "PF-BLK-NAT-01"
    r = alice.post(f"/samples/{sid}/custody", data={"event_datetime": "2026-09-29T14:00", "from_party": "PIRL", "to_party": "Ken",
                                                    "purpose": "EXTRACT", "condition_on_receipt": "good"}, follow_redirects=True)
    assert b"From and To must be a user or an entry in the party list" in r.data


def test_new_list_category_and_list_field(app, alice):
    r = alice.post("/admin/codes", data={"action": "new_category", "new_category": "flowcell type"}, follow_redirects=True)
    assert r.status_code == 200
    alice.post("/admin/codes", data={"action": "add", "category": "flowcell_type", "code": "R10.4.1", "meaning": "ONT R10.4.1"}, follow_redirects=True)
    r = alice.post("/admin/fields", data={"action": "add", "scope": "material", "code": "LIB", "key": "flowcell", "label": "Flowcell",
                                          "type": "list", "list_category": "flowcell_type"}, follow_redirects=True)
    assert b"Field added" in r.data
    html = alice.get("/samples/new").data.decode()
    assert '"flowcell"' in html and "R10.4.1" in html
