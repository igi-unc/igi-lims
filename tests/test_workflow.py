"""Walks the spec's section 5 worked example through the web UI."""
import json
from lims.db import get_db
from conftest import make_root, derive, login

P = "IGI-MP-KXRTQVA-260929-"


def ids_of(app, prefix):
    with app.app_context():
        return [r[0] for r in get_db().execute("SELECT sample_id FROM sample WHERE sample_id LIKE ? ORDER BY 1", (prefix + "%",))]


def test_worked_example(app, alice):
    # 1. pleural fluid received
    r = make_root(alice)
    assert b"Created 1 tube" in r.data
    assert ids_of(app, P + "PF-BLK-NAT") == [P + "PF-BLK-NAT-01"]
    # 2. 10 cryo tubes of bulk cells
    r = derive(alice, P + "PF-BLK-NAT-01", fraction="BLK", material="CPU", count="10")
    assert b"Created 10 tube" in r.data
    cpu = ids_of(app, P + "PF-BLK-CPU")
    assert cpu[0].endswith("-01") and cpu[-1].endswith("-10") and len(cpu) == 10
    # 3. tumour enrichment + immune fraction from tube 03
    assert b"Created 1" in derive(alice, P + "PF-BLK-CPU-03", fraction="TUM", material="CPU").data
    assert b"Created 1" in derive(alice, P + "PF-BLK-CPU-03", fraction="IMM", material="CPU").data
    # 4. CD8 from immune
    assert b"Created 1" in derive(alice, P + "PF-IMM-CPU-01", fraction="CD8", material="CPU").data
    # 5. two pellets
    assert b"Created 2" in derive(alice, P + "PF-TUM-CPU-01", fraction="TUM", material="CPL", count="2").data
    # 6. HMW DNA and RNA
    assert b"Created 1" in derive(alice, P + "PF-TUM-CPL-01", fraction="TUM", material="HMD").data
    assert b"Created 1" in derive(alice, P + "PF-TUM-CPL-02", fraction="TUM", material="RNA").data
    # 7. ONT library consumes the DNA
    assert b"Created 1" in derive(alice, P + "PF-TUM-HMD-01", fraction="TUM", material="LIB", parent_consumed="1").data
    with app.app_context():
        assert get_db().execute("SELECT status FROM sample WHERE sample_id=?", (P + "PF-TUM-HMD-01",)).fetchone()[0] == "Depleted"
    # 8-10. expansion, pellet, peptides
    assert b"Created 6" in derive(alice, P + "PF-TUM-CPU-01", fraction="TUM", material="CUL", count="6").data
    assert b"Created 1" in derive(alice, P + "PF-TUM-CUL-01", fraction="TUM", material="CPC").data
    assert b"Created 1" in derive(alice, P + "PF-TUM-CPC-01", fraction="TUM", material="PEP").data
    # matched blood
    make_root(alice, specimen="PB")
    derive(alice, P + "PB-BLK-NAT-01", fraction="SER", material="NAT")
    derive(alice, P + "PB-BLK-NAT-01", fraction="PLA", material="NAT")
    derive(alice, P + "PB-PLA-NAT-01", fraction="PLA", material="CFD")
    derive(alice, P + "PB-BLK-NAT-01", fraction="BFC", material="NAT")
    derive(alice, P + "PB-BLK-NAT-01", fraction="BFC", material="DNA")  # germline DNA straight from buffy coat step
    # back-tracking from the library
    r = alice.get(f"/api/samples/{P}PF-TUM-LIB-01/lineage")
    chain = [a["sample_id"] for a in r.get_json()["ancestors"]]
    assert chain == [P + "PF-BLK-NAT-01", P + "PF-BLK-CPU-03", P + "PF-TUM-CPU-01", P + "PF-TUM-CPL-01", P + "PF-TUM-HMD-01"]
    assert all(a["root_id"] == P + "PF-BLK-NAT-01" for a in r.get_json()["ancestors"])
    # tree and detail pages render
    assert alice.get(f"/samples/tree/{P}PF-BLK-NAT-01").status_code == 200
    assert alice.get(f"/samples/{P}PF-TUM-LIB-01").status_code == 200
    assert alice.get("/samples/?material=LIB").status_code == 200
    assert alice.get("/participants/KXRTQVA").status_code == 200
    assert alice.get("/").status_code == 200
    # label layout breaks at hyphens
    html = alice.get(f"/samples/{P}PF-TUM-HMD-01").data.decode()
    assert "IGI-MP-KXRTQVA<br>260929-PF-TUM<br>HMD-01<br>" in html


def test_aliquots_never_reused(app, alice):
    make_root(alice)
    derive(alice, P + "PF-BLK-NAT-01", fraction="BLK", material="CPU", count="2")
    with app.app_context():
        conn = get_db()
        conn.execute("UPDATE sample SET deleted_at='x' WHERE sample_id=?", (P + "PF-BLK-CPU-02",))
        conn.commit()
    derive(alice, P + "PF-BLK-NAT-01", fraction="BLK", material="CPU", count="1")
    assert ids_of(app, P + "PF-BLK-CPU") == [P + "PF-BLK-CPU-01", P + "PF-BLK-CPU-02", P + "PF-BLK-CPU-03"]


def test_rule_violation_blocks_then_override_needs_second_user(app, alice, client):
    make_root(alice)
    # RNA straight from native fluid is allowed; LIB from NAT is not
    r = derive(alice, P + "PF-BLK-NAT-01", fraction="BLK", material="LIB")
    assert b"Blocked by derivation rules" in r.data
    assert b"NAT cannot be processed into LIB" in r.data
    assert ids_of(app, P + "PF-BLK-LIB") == []
    # request override
    r = derive(alice, P + "PF-BLK-NAT-01", fraction="BLK", material="LIB", action="request_override",
               justification="direct library prep pilot")
    assert b"Override request #1 submitted" in r.data
    # requester cannot approve
    r = alice.post("/approvals/1/decide", data={"decision": "approve"}, follow_redirects=True)
    assert b"cannot be approved by the person who made it" in r.data
    assert ids_of(app, P + "PF-BLK-LIB") == []
    # bob approves -> tube created with approval id in audit log
    login(client, "bob")
    r = client.post("/approvals/1/decide", data={"decision": "approve", "note": "ok"}, follow_redirects=True)
    assert b"Approved and applied" in r.data
    assert ids_of(app, P + "PF-BLK-LIB") == [P + "PF-BLK-LIB-01"]
    with app.app_context():
        row = get_db().execute("SELECT approval_id FROM audit_log WHERE table_name='sample' AND record_id=? AND action='insert'",
                               (P + "PF-BLK-LIB-01",)).fetchone()
        assert row[0] == 1


def test_root_rule_fraction_for_specimen(app, alice):
    r = make_root(alice, specimen="PB", fraction="PFS")
    assert b"Fraction PFS is not allowed for specimen PB" in r.data


def test_cfd_requires_plasma(app, alice):
    make_root(alice, specimen="PB")
    derive(alice, P + "PB-BLK-NAT-01", fraction="BFC", material="NAT")
    r = derive(alice, P + "PB-BFC-NAT-01", fraction="BFC", material="CFD")
    assert b"requires fraction in" in r.data


def test_depleted_parent_blocks(app, alice):
    make_root(alice)
    derive(alice, P + "PF-BLK-NAT-01", fraction="BLK", material="CPU", parent_consumed="1")
    r = derive(alice, P + "PF-BLK-NAT-01", fraction="BLK", material="CPU")
    assert b"Parent status is Depleted" in r.data


def test_edit_requires_approval_and_applies(app, alice, client):
    make_root(alice)
    sid = P + "PF-BLK-NAT-01"
    r = alice.post(f"/samples/{sid}/edit", data={"status": "Shipped", "quantity": "500", "unit": "mL",
                                                 "created_by": "MF", "justification": "sent to HTSF"}, follow_redirects=True)
    assert b"Change request #1 submitted" in r.data
    with app.app_context():
        assert get_db().execute("SELECT status FROM sample WHERE sample_id=?", (sid,)).fetchone()[0] == "Available"
    login(client, "bob")
    client.post("/approvals/1/decide", data={"decision": "approve"}, follow_redirects=True)
    with app.app_context():
        assert get_db().execute("SELECT status FROM sample WHERE sample_id=?", (sid,)).fetchone()[0] == "Shipped"


def test_delete_blocked_with_children_and_soft_delete(app, alice, client):
    make_root(alice)
    derive(alice, P + "PF-BLK-NAT-01", fraction="BLK", material="CPU")
    r = alice.post(f"/samples/{P}PF-BLK-NAT-01/delete", data={"justification": "x"}, follow_redirects=True)
    assert b"active children" in r.data
    r = alice.post(f"/samples/{P}PF-BLK-CPU-01/delete", data={"justification": "mislabelled"}, follow_redirects=True)
    assert b"request #1 submitted" in r.data.lower()
    login(client, "bob")
    client.post("/approvals/1/decide", data={"decision": "approve"}, follow_redirects=True)
    with app.app_context():
        assert get_db().execute("SELECT deleted_at FROM sample WHERE sample_id=?", (P + "PF-BLK-CPU-01",)).fetchone()[0]
    # still visible with include-deleted and page renders
    assert alice.get(f"/samples/{P}PF-BLK-CPU-01").status_code == 200


def test_custody_and_files(app, alice):
    make_root(alice)
    sid = P + "PF-BLK-NAT-01"
    r = alice.post(f"/samples/{sid}/custody", data={"event_datetime": "2026-09-29T14:00", "from_party": "PIRL",
                                                    "to_party": "Ken", "purpose": "DNA/RNA extraction", "set_status": "In use"},
                   follow_redirects=True)
    assert b"Custody event recorded" in r.data
    r = alice.post(f"/samples/{sid}/files", data={"uri": f"gs://igi-bucket/{sid}_ONT-R001.bam", "assay_code": "ONT",
                                                  "run_id": "R001", "checksum_md5": "abc"}, follow_redirects=True)
    assert b"File recorded" in r.data
    j = alice.get(f"/api/samples/{sid}").get_json()
    assert j["sample"]["status"] == "In use"
    assert j["custody"][0]["to_party"] == "Ken"
    assert j["files"][0]["assay_code"] == "ONT"
    assert alice.get("/api/files?assay=ONT").get_json()[0]["participant_id"] == "KXRTQVA"


def test_viewer_is_read_only(app, client):
    login(client, "vic")
    assert client.get("/samples/").status_code == 200
    assert client.get("/samples/new").status_code == 403
    assert client.post("/samples/new", data={}).status_code == 403
    assert client.get("/admin/users").status_code == 403


def test_api_token_and_validate(app, client, monkeypatch):
    monkeypatch.setenv("LIMS_API_TOKEN", "sekrit")
    assert client.get("/api/samples").status_code == 401
    assert client.get("/api/samples", headers={"X-Api-Token": "sekrit"}).status_code == 200
    j = client.get("/api/validate/IGI-MP-KXRTQVA-260929-PF-TUM-HMD-01").get_json()
    assert j["valid"] and not j["exists"] and j["components"]["collection_date"] == "2026-09-29"
    assert client.get("/api/validate/IGI-MP-KXRTQVA-260929-PF-TUM-HMD").status_code == 400
    assert "^" in client.get("/api/pattern").get_json()["pattern"]


def test_admin_codes_and_rules(app, alice):
    r = alice.post("/admin/codes", data={"action": "add", "category": "material", "code": "XYZ", "meaning": "test"}, follow_redirects=True)
    assert b"Added material code XYZ" in r.data
    r = alice.post("/admin/rules", data={"rule_type": "material_transition", "from_code": "NAT", "to_code": "XYZ"}, follow_redirects=True)
    assert b"Rule added" in r.data
    make_root(alice)
    assert b"Created 1" in derive(alice, P + "PF-BLK-NAT-01", fraction="BLK", material="XYZ").data
    # retire the code: new tubes with it are rejected outright (not overridable)
    alice.post("/admin/codes", data={"action": "toggle", "category": "material", "code": "XYZ"}, follow_redirects=True)
    assert b"is retired" in derive(alice, P + "PF-BLK-NAT-01", fraction="BLK", material="XYZ").data


def test_all_fields_required(app, alice):
    r = make_root(alice, freezer="", notes="")
    assert b"All fields are required" in r.data and b"Freezer" in r.data and b"Notes" in r.data
    assert ids_of(app, P + "PF-BLK-NAT") == []


def test_browse_and_register_pages(app, alice):
    make_root(alice)
    derive(alice, P + "PF-BLK-NAT-01", fraction="BLK", material="CPU", count="2")
    make_root(alice, specimen="PB")
    assert alice.get("/register").status_code == 200
    r = alice.get("/browse?participant=KXRTQVA")
    assert r.status_code == 200
    html = r.data.decode()
    assert '"participant": "KXRTQVA"' in html and P + "PB-BLK-NAT-01" in html and P + "PF-BLK-CPU-02" in html
    assert alice.get("/browse").status_code == 200
    # audit page renders key/value lines
    assert "class='kv'" in alice.get("/admin/audit").data.decode()
