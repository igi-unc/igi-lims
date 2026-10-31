"""Walks the nomenclature v2.1 worked example (section 5) through the web UI, plus the core rules."""
import re
from lims.db import get_db
from conftest import P, sid, make_root, new_collection, add_tubes, derive, login


def ids_of(app, prefix):
    with app.app_context():
        return [r[0] for r in get_db().execute("SELECT sample_id FROM sample WHERE sample_id LIKE ? ORDER BY 1", (prefix + "%",))]


def test_worked_example(app, alice):
    # the pleural fluid is registered as a collection; it is not a tube
    pf = new_collection(alice)
    assert isinstance(pf, int) and ids_of(app, P) == []
    # 1-2. first-generation tubes straight from the fluid
    r = add_tubes(alice, pf, fraction="PFS", material="FRZ", count="4", created_by="MF", created_datetime="2026-09-29T11:00")
    assert b"Created 4 tube" in r.data
    r = add_tubes(alice, pf, fraction="PFM", material="CPU", count="10", created_by="MF", created_datetime="2026-09-29T14:00")
    pfm = ids_of(app, P + "PF-PFM-CPU")
    assert len(pfm) == 10 and pfm[2] == sid("PF", "PFM", "CPU", 3, "MF")
    with app.app_context():
        assert get_db().execute("SELECT count(*) FROM sample WHERE parent_id IS NULL AND collection_id=?", (pf,)).fetchone()[0] == 14
    vial3 = pfm[2]
    # 3. tumour and immune fractions from vial 03, made on 1 Oct
    oct1 = {"created_by": "MF", "created_datetime": "2026-10-01T10:00"}
    assert b"Created 1" in derive(alice, vial3, fraction="TUM", material="CPU", **oct1).data
    assert b"Created 1" in derive(alice, vial3, fraction="IMM", material="CPU", **oct1).data
    # 4. CD8 from the immune fraction, 2 Oct
    assert b"Created 1" in derive(alice, sid("PF", "IMM", "CPU", 1, "MF", "26OCT01"), fraction="CD8", material="CPU",
                                  created_by="MF", created_datetime="2026-10-02T10:00").data
    # 5. two pellets from the same run; the vial is used up
    assert b"Created 2" in derive(alice, vial3, fraction="TUM", material="SNF", count="2", parent_consumed="1", **oct1).data
    # 6. Ken extracts HMW DNA and RNA on 6 Oct
    ken = {"created_by": "KEN", "created_datetime": "2026-10-06T11:00"}
    assert b"Created 1" in derive(alice, sid("PF", "TUM", "SNF", 1, "MF", "26OCT01"), fraction="TUM", material="HMD", parent_consumed="1", **ken).data
    assert b"Created 1" in derive(alice, sid("PF", "TUM", "SNF", 2, "MF", "26OCT01"), fraction="TUM", material="RNA", **ken).data
    hmd = sid("PF", "TUM", "HMD", 1, "KEN", "26OCT06")
    assert hmd == "IGI-MP-P101-UNC316-26SEP29-PF-TUM-HMD-01-KEN-26OCT06" and ids_of(app, hmd) == [hmd]
    # 7-9. culture, a pellet on 16 Oct (aliquot 03: counted within segments 1-8), peptides on 17 Oct
    assert b"Created 6" in derive(alice, sid("PF", "TUM", "CPU", 1, "MF", "26OCT01"), fraction="TUM", material="CUL", count="6",
                                  created_by="MF", created_datetime="2026-10-02T15:00").data
    assert b"Created 1" in derive(alice, sid("PF", "TUM", "CUL", 1, "MF", "26OCT02"), fraction="TUM", material="SNF",
                                  created_by="MF", created_datetime="2026-10-16T10:00").data
    snf3 = sid("PF", "TUM", "SNF", 3, "MF", "26OCT16")
    assert ids_of(app, snf3) == [snf3]
    assert b"Created 1" in derive(alice, snf3, fraction="TUM", material="PEP", created_by="MF", created_datetime="2026-10-17T17:00").data
    # matched blood: a separate collection with the same received date
    pb = new_collection(alice, specimen_code="PB", container_type="EDTA", quantity="20")
    add_tubes(alice, pb, fraction="SER", material="FRZ", created_by="MF")
    add_tubes(alice, pb, fraction="PLA", material="FRZ", created_by="MF")
    add_tubes(alice, pb, fraction="BFC", material="FRZ", created_by="MF")
    assert b"Created 1" in derive(alice, sid("PB", "PLA", "FRZ", 1, "MF"), fraction="PLA", material="CFD", created_by="MF",
                                  created_datetime="2026-09-30T10:00").data
    assert b"Created 1" in derive(alice, sid("PB", "BFC", "FRZ", 1, "MF"), fraction="BFC", material="DNA", **ken).data
    assert ids_of(app, P + "PB-PLA-CFD") == ["IGI-MP-P101-UNC316-26SEP29-PB-PLA-CFD-01-MF-26SEP30"]
    # back-tracking from the HMW DNA tube, as in the document
    chain = [a["sample_id"] for a in alice.get(f"/api/samples/{hmd}/lineage").get_json()["ancestors"]]
    assert chain == [vial3, sid("PF", "TUM", "SNF", 1, "MF", "26OCT01")]
    with app.app_context():
        conn = get_db()
        assert conn.execute("SELECT collection_id FROM sample WHERE sample_id=?", (hmd,)).fetchone()[0] == pf
        assert conn.execute("SELECT status FROM sample WHERE sample_id=?", (vial3,)).fetchone()[0] == "Depleted"
        # one audit row per created tube
        assert conn.execute("SELECT max(n) FROM (SELECT count(*) n FROM audit_log WHERE table_name='sample' "
                            "AND action='insert' GROUP BY record_id) x").fetchone()[0] == 1
    # pages render
    for url in (f"/collections/{pf}", f"/collections/{pf}/tree", f"/samples/{hmd}", f"/samples/?collection={pf}",
                "/participants/P101", "/browse?participant=P101", "/", f"/samples/tree/{vial3}"):
        r = alice.get(url, follow_redirects=True)
        assert r.status_code == 200, url
    # label: three rows of at most 18 characters, broken at hyphens
    rows = re.findall(r"<text [^>]*>([^<]*)</text>", alice.get(f"/samples/{hmd}/label.svg").data.decode())
    assert rows[:3] == ["IGI-MP-P101-UNC316", "26SEP29-PF-TUM-HMD", "01-KEN-26OCT06"] and max(map(len, rows)) <= 18
    assert len(rows) == 4 and re.fullmatch(r"\d{9}", rows[3])                    # the LIMS number, nine digits


def test_aliquots_never_reused_and_counted_within_segments_1_to_8(app, alice):
    cid = new_collection(alice)
    add_tubes(alice, cid, count="2")
    with app.app_context():
        conn = get_db()
        conn.execute("UPDATE sample SET deleted_at='x' WHERE sample_id=?", (sid("PF", "PFM", "CPU", 2),))
        conn.commit()
    # same tube type, another operator on another day: the next number, not 01
    add_tubes(alice, cid, created_by="BB", created_datetime="2026-09-30T09:00")
    assert ids_of(app, P + "PF-PFM-CPU") == [sid("PF", "PFM", "CPU", 1), sid("PF", "PFM", "CPU", 2),
                                             sid("PF", "PFM", "CPU", 3, "BB", "26SEP30")]


def test_rule_violation_blocks_then_override_is_flagged(app, alice, client):
    make_root(alice)
    parent = sid("PF", "PFM", "CPU")
    # CPU cannot become PEP directly (it must be pelleted first)
    r = derive(alice, parent, fraction="TUM", material="PEP")
    assert b"Blocked by derivation rules" in r.data and b"CPU cannot be processed into PEP" in r.data
    assert ids_of(app, P + "PF-TUM-PEP") == []
    r = derive(alice, parent, fraction="TUM", material="PEP", action="override")
    assert b"justification is required" in r.data and ids_of(app, P + "PF-TUM-PEP") == []
    r = derive(alice, parent, fraction="TUM", material="PEP", action="override", justification="direct lysis pilot")
    assert b"rule override recorded" in r.data
    pep = sid("PF", "TUM", "PEP")
    with app.app_context():
        row = get_db().execute("SELECT reason FROM audit_log WHERE table_name='sample' AND record_id=? AND action='insert'",
                               (pep,)).fetchone()
        assert row[0].startswith("Rule override: ") and "direct lysis pilot" in row[0]
    r = alice.get(f"/samples/{pep}")
    assert b"rule override" in r.data and b"direct lysis pilot" in r.data
    login(client, "vic")
    r = client.get("/admin/audit?changes=1")
    assert r.status_code == 200 and b"direct lysis pilot" in r.data


def test_first_generation_rules(app, alice):
    r = make_root(alice, specimen="PB", fraction="PFS", material="FRZ")
    assert b"Fraction PFS is not allowed for specimen PB" in r.data
    r = make_root(alice, specimen="PF", fraction="TUM", material="PEP", attr_hla_class="I")
    assert b"cannot be made directly from a received specimen" in r.data
    r = make_root(alice, specimen="PF", fraction="PFM", material="FRZ")     # FRZ is for fluids, not cells
    assert b"requires fraction in" in r.data


def test_processing_before_received_is_flagged(app, alice):
    r = make_root(alice, created_datetime="2026-09-28T10:00")
    assert b"is before the received date" in r.data and ids_of(app, P) == []


def test_cfd_requires_plasma(app, alice):
    cid = new_collection(alice, specimen_code="PB")
    add_tubes(alice, cid, fraction="BFC", material="FRZ")
    r = derive(alice, sid("PB", "BFC", "FRZ"), fraction="BFC", material="CFD")
    assert b"requires fraction in" in r.data


def test_depleted_parent_blocks(app, alice):
    make_root(alice)
    derive(alice, sid("PF", "PFM", "CPU"), fraction="PFM", material="CPU", parent_consumed="1")
    r = derive(alice, sid("PF", "PFM", "CPU"), fraction="PFM", material="CPU")
    assert b"Parent status is Depleted" in r.data


def test_edit_is_direct_and_flagged_in_audit(app, alice, client):
    make_root(alice)
    s = sid("PF", "PFM", "CPU")
    r = alice.post(f"/samples/{s}/edit", data={"status": "Shipped", "quantity": "500", "unit": "mL",
                                               "justification": "sent to HTSF"}, follow_redirects=True)
    assert b"Sample updated" in r.data and b"edited" in r.data
    with app.app_context():
        conn = get_db()
        assert conn.execute("SELECT status FROM sample WHERE sample_id=?", (s,)).fetchone()[0] == "Shipped"
        row = conn.execute("SELECT before_json, after_json, reason FROM audit_log WHERE table_name='sample' AND record_id=? AND action='update'",
                           (s,)).fetchone()
        assert '"Available"' in row[0] and '"Shipped"' in row[1] and row[2] == "sent to HTSF"
    assert b"Shipped" in alice.get("/samples/").data
    alice.post(f"/samples/{s}/edit", data={"status": "Available", "quantity": "500", "unit": "mL",
                                           "freezer": "NA", "rack": "NA", "box": "NA", "position": "A1"}, follow_redirects=True)
    assert b"<td>A1</td>" in alice.get("/samples/").data


def test_delete_blocked_with_children_and_soft_delete(app, alice, client):
    make_root(alice)
    parent, child = sid("PF", "PFM", "CPU"), sid("PF", "TUM", "CPU")
    derive(alice, parent, fraction="TUM", material="CPU")
    r = alice.post(f"/samples/{parent}/delete", data={"justification": "x"}, follow_redirects=True)
    assert b"active children" in r.data
    r = alice.post(f"/samples/{child}/delete", data={"justification": "mislabelled"}, follow_redirects=True)
    assert b"Record deleted" in r.data
    with app.app_context():
        conn = get_db()
        assert conn.execute("SELECT deleted_at FROM sample WHERE sample_id=?", (child,)).fetchone()[0]
        assert conn.execute("SELECT reason FROM audit_log WHERE action='delete' AND record_id=?", (child,)).fetchone()[0] == "mislabelled"
    assert alice.get(f"/samples/{child}").status_code == 200


def test_collection_without_tubes_can_be_deleted(app, alice):
    cid = new_collection(alice)
    r = alice.post(f"/collections/{cid}/delete", data={"justification": "entered twice"}, follow_redirects=True)
    assert b"Collection deleted" in r.data
    cid2 = new_collection(alice)
    add_tubes(alice, cid2)
    r = alice.post(f"/collections/{cid2}/delete", data={}, follow_redirects=True)
    assert b"cannot be deleted" in r.data


def test_custody_and_files_with_platform_and_suggested_name(app, alice):
    cid = new_collection(alice)
    add_tubes(alice, cid, fraction="TUM", material="SNF", unit="cells")
    snf = sid("PF", "TUM", "SNF")
    derive(alice, snf, fraction="TUM", material="HMD", created_by="KEN", created_datetime="2026-10-06T11:00")
    hmd = sid("PF", "TUM", "HMD", 1, "KEN", "26OCT06")
    r = alice.post(f"/samples/{hmd}/custody", data={"event_datetime": "2026-10-07T09:00", "from_party": "KEN", "to_party": "HTSF",
                                                    "purpose": "SEQ", "condition_on_receipt": "good", "set_status": "In use"},
                   follow_redirects=True)
    assert b"Custody event recorded" in r.data
    page = alice.get(f"/samples/{hmd}").data.decode()
    assert f'data-stem="{hmd}_tumor"' in page and 'data-label="DNA_WGS"' in page and 'data-label="ONT"' in page
    # platform is required
    r = alice.post(f"/samples/{hmd}/files", data={"uri": f"gs://b/{hmd}_tumor_DNA_WGS_ONT.bam", "assay_code": "WGS"}, follow_redirects=True)
    assert b"assay and platform are required" in r.data
    r = alice.post(f"/samples/{hmd}/files", data={"uri": f"gs://b/{hmd}_tumor_DNA_WGS_ONT.bam", "assay_code": "WGS",
                                                  "platform_code": "ONT", "run_id": "R001", "checksum_md5": "abc"}, follow_redirects=True)
    assert b"File recorded" in r.data and b"should start with" not in r.data
    j = alice.get(f"/api/samples/{hmd}").get_json()
    assert j["sample"]["status"] == "In use" and j["custody"][0]["to_party"] == "HTSF"
    assert j["files"][0]["platform_code"] == "ONT" and j["collection"]["collection_id"] == cid
    assert alice.get("/api/files?assay=WGS").get_json()[0]["participant_id"] == "P101"


def test_viewer_is_read_only(app, client):
    login(client, "vic")
    assert client.get("/samples/").status_code == 200
    assert client.get("/collections/new").status_code == 403
    assert client.post("/collections/new", data={}).status_code == 403
    assert client.get("/admin/users").status_code == 403


def test_api_token_and_validate(app, client, monkeypatch):
    monkeypatch.setenv("LIMS_API_TOKEN", "sekrit")
    assert client.get("/api/samples").status_code == 401
    assert client.get("/api/samples", headers={"X-Api-Token": "sekrit"}).status_code == 200
    j = client.get("/api/validate/IGI-MP-P101-UNC316-26SEP29-PF-TUM-HMD-01-KEN-26OCT06").get_json()
    assert j["valid"] and not j["exists"] and j["components"]["received_date"] == "2026-09-29"
    assert j["components"]["operator"] == "KEN" and j["components"]["processing_date"] == "2026-10-06"
    assert client.get("/api/validate/IGI-MP-KXRTQVA-260929-PF-TUM-HMD-01").status_code == 400
    assert client.get("/api/pattern").get_json()["pattern"].startswith("^(IGI)-")


def test_admin_codes_widths_and_rules(app, alice):
    r = alice.post("/admin/codes", data={"action": "add", "category": "specimen", "code": "NTC", "meaning": "too long"}, follow_redirects=True)
    assert b"must match" in r.data
    r = alice.post("/admin/codes", data={"action": "add", "category": "material", "code": "XYZ", "meaning": "test"}, follow_redirects=True)
    assert b"Added material code XYZ" in r.data
    r = alice.post("/admin/rules", data={"rule_type": "material_transition", "from_code": "CPU", "to_code": "XYZ"}, follow_redirects=True)
    assert b"Rule added" in r.data
    make_root(alice)
    assert b"Created 1" in derive(alice, sid("PF", "PFM", "CPU"), fraction="PFM", material="XYZ").data
    alice.post("/admin/codes", data={"action": "toggle", "category": "material", "code": "XYZ"}, follow_redirects=True)
    assert b"is retired" in derive(alice, sid("PF", "PFM", "CPU"), fraction="PFM", material="XYZ").data


def test_operator_codes(app, alice):
    from lims.auth import create_user
    with app.app_context():
        conn = get_db()
        for bad in ("A", "ABCD", "a1"):
            try:
                create_user(conn, "x" + bad, "X", bad, "password1")
                assert False, bad
            except ValueError:
                pass
        try:
            create_user(conn, "dup", "Dup", "MF", "password1")
            assert False
        except ValueError as e:
            assert "unique" in str(e)


def test_all_fields_required(app, alice):
    r = make_root(alice, freezer="", notes="")
    assert b"All fields are required" in r.data and b"Freezer" in r.data and b"Notes" in r.data
    assert ids_of(app, P) == []
    r = alice.post("/collections/new", data={"participant_id": "P101", "received_date": "2026-09-29"})
    assert b"All fields are required" in r.data


def test_participants(app, alice, client):
    r = alice.get("/participants/new")
    assert b'value="P102"' in r.data
    r = alice.post("/participants/new", data={"participant_id": "P102", "unc_number": "316", "cohort_code": "MP"}, follow_redirects=True)
    assert b"already participant P101" in r.data
    r = alice.post("/participants/new", data={"participant_id": "P102", "unc_number": "12", "cohort_code": "MP"}, follow_redirects=True)
    assert b"exactly 3 digits" in r.data
    r = alice.post("/participants/new", data={"participant_id": "P120", "unc_number": "UNC327", "cohort_code": "AM"}, follow_redirects=True)
    assert b"Participant P120 (UNC327) created" in r.data
    # a non-admin cannot choose the number
    login(client, "bob")
    r = client.post("/participants/new", data={"participant_id": "P500", "unc_number": "400", "cohort_code": "TN"}, follow_redirects=True)
    assert b"Participant P121 (UNC400) created" in r.data
    # jump box finds a participant by UNC ID
    r = alice.get("/go?q=unc327")
    assert r.headers["Location"].endswith("/participants/P120")
    # UNC number is locked once tubes exist
    make_root(alice)
    r = alice.post("/participants/P101/edit", data={"unc_number": "317", "cohort_code": "MP"}, follow_redirects=True)
    assert b"cannot change once tubes exist" in r.data


def test_browse_and_register_pages(app, alice):
    make_root(alice)
    derive(alice, sid("PF", "PFM", "CPU"), fraction="TUM", material="CPU", count="2")
    empty = new_collection(alice, specimen_code="PB")
    assert alice.get("/register").status_code == 200
    html = alice.get("/browse?participant=P101").data.decode()
    assert '"participant": "P101"' in html and sid("PF", "TUM", "CPU", 2) in html
    assert '"collection": {"collection_id": %d' % empty in html          # a collection with no tubes still shows
    assert "class='kv'" in alice.get("/admin/audit").data.decode()


def test_register_derived_picker(app, alice):
    cid = new_collection(alice)
    add_tubes(alice, cid)
    derive(alice, sid("PF", "PFM", "CPU"), fraction="PFM", material="CPU", parent_consumed="1")
    assert alice.get("/samples/derive").status_code == 200
    html = alice.get("/samples/derive?participant=P101&fraction=TUM&material=SNF").data.decode()
    assert f'value="{sid("PF", "PFM", "CPU", 2)}" required' in html            # the live vial
    assert "Parent status is Depleted" in html                                   # the used-up one
    assert f'value="C:{cid}" required' in html                                   # straight from the collection
    # PEP cannot be made directly from a specimen or from CPU
    html = alice.get("/samples/derive?participant=P101&fraction=TUM&material=PEP").data.decode()
    assert "No tube from P101 can be the parent" in html and f'value="C:{cid}"' not in html
    r = alice.post("/samples/derive", data={"parent_id": f"C:{cid}", "fraction": "TUM", "material": "SNF"})
    assert r.headers["Location"].endswith(f"/collections/{cid}/tubes?fraction=TUM&material=SNF")
    r = alice.post("/samples/derive", data={"parent_id": "nope"}, follow_redirects=True)
    assert b"No tube with ID NOPE" in r.data
