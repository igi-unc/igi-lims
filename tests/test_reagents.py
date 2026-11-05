"""Scanning kit / reagent boxes on the registration forms (GS1 Data Matrix: GTIN, lot, expiry)."""
import datetime as dt
from lims import gs1
from lims.db import get_db
from conftest import new_collection, add_tubes, sid, login

GTIN = "02000000100012"


def test_gs1_parse():
    gs = gs1.GS
    assert gs1.parse(f"01{GTIN}17271130" + "10E2611A") == {"gtin": GTIN, "expiry": "2027-11-30", "lot": "E2611A"}
    assert gs1.parse(f"]d201{GTIN}10E26{gs}21SN1") == {"gtin": GTIN, "lot": "E26", "serial": "SN1"}
    assert gs1.parse(f"(01){GTIN}(17)270200(10)AB-1") == {"gtin": GTIN, "expiry": "2027-02-28", "lot": "AB-1"}   # DD=00: month end
    for not_gs1 in ("1000263", "LOT-123", "IGI-MP-P101", "", "01123"):
        assert gs1.parse(not_gs1) is None
    assert gs1.gtin_ok(GTIN) and not gs1.gtin_ok("02000000100013")
    assert gs1.parse(gs1.build(GTIN, "271130", "E2611A")) == {"gtin": GTIN, "expiry": "2027-11-30", "lot": "E2611A"}


def test_scan_learn_and_fill(app, alice):
    post = lambda url, body: alice.post(url, json=body)
    code = gs1.build(GTIN, "271130", "E2611A")
    # unknown product: nothing to fill, the form will ask
    r = post("/reagents/lookup", {"text": code, "fields": ["kit", "extraction_kit"]}).get_json()
    assert r["product_key"] == GTIN and r["lot"] == "E2611A" and r["matches"] == [] and not r["expired"]
    assert post("/reagents/remember", {"product_key": GTIN, "field": "kit", "code": "NOPE"}).status_code == 400
    assert post("/reagents/remember", {"product_key": GTIN, "field": "not_a_field", "code": "NA"}).status_code == 400
    with app.app_context():
        db = get_db()
        db.execute("INSERT INTO code_list(category, code, meaning) VALUES ('kit', 'EPCAM_MACS', 'EpCAM beads')")
        db.commit()
    assert post("/reagents/remember", {"product_key": GTIN, "field": "kit", "code": "EPCAM_MACS"}).get_json()["ok"]
    r = post("/reagents/lookup", {"text": code, "fields": ["kit"]}).get_json()
    assert r["matches"] == [{"field": "kit", "code": "EPCAM_MACS", "meaning": "EpCAM beads"}]
    assert r["lots"] == [{"field": "kit_lot", "exists": False, "addable": True}]
    # the lot is added to its list once, audited
    assert post("/reagents/lot", {"field": "kit_lot", "lot": "E2611A", "meaning": "EpCAM lot E2611A"}).get_json()["code"] == "E2611A"
    assert post("/reagents/lot", {"field": "kit_lot", "lot": "E2611A"}).status_code == 200
    assert post("/reagents/lot", {"field": "kit", "lot": "X"}).status_code == 400              # only lot fields
    assert post("/reagents/lot", {"field": "kit_lot", "lot": "bad lot!"}).status_code == 400
    assert post("/reagents/lookup", {"text": code, "fields": ["kit"]}).get_json()["lots"][0]["exists"] is True
    with app.app_context():
        db = get_db()
        assert db.execute("SELECT COUNT(*) FROM code_list WHERE category='kit_lot' AND code='E2611A'").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM audit_log WHERE table_name IN ('reagent_barcode','code_list')").fetchone()[0] == 2
    # expired boxes are flagged; non-GS1 codes are products by their raw text
    old = (dt.date.today() - dt.timedelta(days=40)).strftime("%y%m%d")
    assert post("/reagents/lookup", {"text": gs1.build(GTIN, old, "L1")}).get_json()["expired"] is True
    r = post("/reagents/lookup", {"text": "VENDOR-KIT-99"}).get_json()
    assert r["gs1"] is None and r["product_key"] == "VENDOR-KIT-99"
    # the mapping is listed; only an admin can forget it
    assert GTIN.encode() in alice.get("/reagents/").data


def test_scan_button_on_registration_forms(app, alice, client):
    cid = new_collection(alice)
    page = alice.get(f"/collections/{cid}/tubes").data.decode()
    assert 'id="rg-open"' in page and "reagentscan.js" in page
    add_tubes(alice, cid)
    assert 'id="rg-open"' in alice.get(f"/samples/{sid('PF', 'PFM', 'CPU', 1)}/derive").data.decode()
    login(client, "vic")                   # viewers cannot use the scan endpoints
    assert client.post("/reagents/lookup", json={"text": "x"}).status_code == 403


def test_demo_reagent_test_codes(app):
    from lims.demo import reset_demo, DEMO_REAGENTS
    app.config["DEMO_MODE"] = True
    with app.app_context():
        reset_demo(get_db(), "pw")
    c = app.test_client()
    c.post("/login", data={"username": "demo", "password": "pw"})
    page = c.get("/reagents/").data.decode()
    assert all(g in page for g, *_ in DEMO_REAGENTS) and page.count("<svg") >= len(DEMO_REAGENTS)
    assert all(gs1.gtin_ok(g) and g.startswith("02") for g, *_ in DEMO_REAGENTS)
