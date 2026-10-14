"""Build a throwaway demo database, walk through the LIMS in headless Chromium,
and save annotated screenshots to docs/screenshots/ plus meta.json for the PDF.

Run from the repo root:  .venv/bin/python docs/walkthrough_capture.py
Needs: playwright (with `playwright install chromium`), pillow.
"""
import csv
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
DEMO = Path(os.environ.get("LIMS_DEMO_DIR", ROOT / "instance" / "demo"))
PORT = int(os.environ.get("LIMS_DEMO_PORT", "5055"))
BASE = f"http://127.0.0.1:{PORT}"
SCALE = 2
PW = "demo-pass-1234"
FONT = "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf"
RED = (215, 38, 61)

USERS = [("admin", "Lab Admin", "LA", "admin"), ("jdoe", "Jane Doe", "JD", "user"), ("asmith", "Alex Smith", "AS", "user")]
EXTRA_CODES = [
    ("sop", "SOP-001", "Pleural fluid receipt and aliquoting"),
    ("sop", "SOP-002", "PFMC isolation and cryopreservation"),
    ("sop", "SOP-003", "HMW DNA extraction (Nanobind)"),
    ("freezer", "FRZ-A", "-80 C freezer A, PIRL 3rd floor"),
    ("freezer", "LN2-1", "LN2 dewar 1"),
    ("rack", "R1", "Rack 1"), ("rack", "R2", "Rack 2"),
    ("box", "B01", "Box 01"), ("box", "B02", "Box 02"),
    ("kit_lot", "LOT-24091", "Nanobind lot 24091"),
    ("buffer", "EB", "Elution buffer (10 mM Tris)"),
]

meta = {"ids": {}, "shots": {}}


# ----------------------------------------------------------------------------- setup
def env():
    e = dict(os.environ)
    e.update(FLASK_APP="app", LIMS_DATABASE=str(DEMO / "lims.db"), LIMS_ATTACHMENT_DIR=str(DEMO / "attachments"),
             LIMS_SECRET_KEY="walkthrough-demo")
    return e


def build_demo_db():
    if DEMO.exists():
        shutil.rmtree(DEMO)
    DEMO.mkdir(parents=True)
    run = lambda *a: subprocess.run([sys.executable, "-m", "flask", *a], cwd=ROOT, env=env(), check=True,
                                    stdout=subprocess.DEVNULL)
    run("init-db")
    for u, name, ini, role in USERS:
        run("create-user", u, "--name", name, "--initials", ini, "--role", role, "--password", PW)
    conn = sqlite3.connect(DEMO / "lims.db")
    for i, (cat, code, meaning) in enumerate(EXTRA_CODES):
        conn.execute("INSERT OR IGNORE INTO code_list(category, code, meaning, active, sort_order) VALUES (?,?,?,1,?)",
                     (cat, code, meaning, 100 + i))
    conn.commit()
    conn.close()


def start_server():
    proc = subprocess.Popen([sys.executable, "-m", "flask", "run", "--port", str(PORT)], cwd=ROOT, env=env(),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            urllib.request.urlopen(BASE + "/login", timeout=1)
            return proc
        except Exception:
            time.sleep(0.2)
    proc.kill()
    raise RuntimeError("server did not start")


# ----------------------------------------------------------------------------- annotation
def content_bottom(im):
    """Last image row that differs from the page background (sampled at the bottom-right corner)."""
    W, H = im.size
    bg = Image.new("RGB", im.size, im.getpixel((W - 4, H - 4)))
    bbox = ImageChops.difference(im, bg).getbbox()
    return bbox[3] if bbox else H


def annotate(path, boxes, max_h=None):
    im = Image.open(path).convert("RGB")
    W, H = im.size
    if max_h and H > max_h * SCALE:
        im = im.crop((0, 0, W, max_h * SCALE))
        W, H = im.size
    low = content_bottom(im)
    d = ImageDraw.Draw(im)
    font = ImageFont.truetype(FONT, 20 * SCALE)
    s = SCALE
    for n, (bb, side) in enumerate(boxes, 1):
        if bb is None:
            continue
        x1, y1 = bb["x"] * s - 6 * s, bb["y"] * s - 6 * s
        x2, y2 = (bb["x"] + bb["width"]) * s + 6 * s, (bb["y"] + bb["height"]) * s + 6 * s
        if y1 > H:
            continue
        d.rounded_rectangle((x1, y1, x2, y2), radius=6 * s, outline=RED, width=3 * s)
        xc, yc = (x1 + x2) / 2, (y1 + y2) / 2
        if side == "auto":
            side = "left" if x1 > 120 * s else ("right" if W - x2 > 120 * s else ("top" if y1 > 90 * s else "bottom"))
        off = 60 * s
        tgt, badge = {
            "left": ((x1, yc), (x1 - off, yc)), "right": ((x2, yc), (x2 + off, yc)),
            "top": ((xc, y1), (xc, y1 - off)), "bottom": ((xc, y2), (xc, y2 + off)),
        }[side]
        r = 18 * s
        bx = min(max(badge[0], r + 2), W - r - 2)
        by = min(max(badge[1], r + 2), H - r - 2)
        # arrow shaft from badge edge to target
        dx, dy = tgt[0] - bx, tgt[1] - by
        L = max((dx * dx + dy * dy) ** 0.5, 1)
        ux, uy = dx / L, dy / L
        sx, sy = bx + ux * r, by + uy * r
        hx, hy = tgt[0] - ux * 14 * s, tgt[1] - uy * 14 * s
        d.line((sx, sy, hx, hy), fill=RED, width=4 * s)
        px, py = -uy, ux
        d.polygon([(tgt[0], tgt[1]), (hx + px * 9 * s, hy + py * 9 * s), (hx - px * 9 * s, hy - py * 9 * s)], fill=RED)
        d.ellipse((bx - r, by - r, bx + r, by + r), fill=RED, outline="white", width=2 * s)
        low = max(low, y2, by + r)
        t = str(n)
        tw, th = d.textbbox((0, 0), t, font=font)[2:]
        d.text((bx - tw / 2, by - th / 2 - 3 * s), t, fill="white", font=font)
    cut = min(H, max(int(low) + 36 * s, 360 * s))
    if cut < H:
        im = im.crop((0, 0, W, cut))
    im.save(path, optimize=True)


class Shooter:
    def __init__(self):
        OUT.mkdir(parents=True, exist_ok=True)
        for f in OUT.glob("*.png"):
            f.unlink()

    def take(self, page, name, callouts=(), full=False, max_h=None, caption=""):
        page.evaluate("window.scrollTo(0,0)")
        page.wait_for_timeout(200)
        boxes, texts = [], []
        for c in callouts:
            loc, text, side = (c + ("auto",))[:3]
            if isinstance(loc, str):
                loc = page.locator(loc)
            bb = loc.first.bounding_box() if loc.count() else None
            if bb is None:
                print(f"  [warn] {name}: no element for callout '{text}'")
                continue
            boxes.append((bb, side))
            texts.append(text)
        path = OUT / f"{name}.png"
        page.screenshot(path=str(path), full_page=full)
        annotate(path, boxes, max_h)
        meta["shots"][name] = {"callouts": texts, "caption": caption}
        print(f"  shot {name}")


# ----------------------------------------------------------------------------- helpers
def login(ctx, user):
    page = ctx.new_page()
    page.goto(BASE + "/login")
    page.fill("input[name=username]", user)
    page.fill("input[name=password]", PW)
    return page


def sel(page, name, value):
    """Select by value, falling back to the first option whose text contains `value`."""
    el = page.locator(f"select[name='{name}']").first
    if not el.count():
        print(f"  [warn] no select {name}")
        return
    ok = el.evaluate("""(s, v) => { for (const o of s.options) if (o.value === v) { s.value = v; s.dispatchEvent(new Event('change', {bubbles:true})); return true; }
                              for (const o of s.options) if (o.text.includes(v)) { s.value = o.value; s.dispatchEvent(new Event('change', {bubbles:true})); return true; } return false; }""", value)
    if not ok:
        print(f"  [warn] {name}: no option {value!r}")


def fill(page, name, value):
    el = page.locator(f"[name='{name}']").first
    if el.count():
        el.fill(str(value))
    else:
        print(f"  [warn] no field {name}")


def fill_common(page, **kw):
    """Shared tube fields (samples/_fields.html)."""
    v = dict(count=1, created_datetime="2026-10-06T14:30", created_by="JD", sop_code="SOP-001", biobank_source="IH",
             quantity=1, unit="mL", status="Available", freezer="FRZ-A", rack="R1", box="B01", position="A1", notes="NA")
    v.update(kw)
    for k in ("count", "created_datetime", "quantity", "notes"):
        fill(page, k, v[k])
    for k in ("created_by", "sop_code", "biobank_source", "unit", "status", "freezer", "rack", "box", "position"):
        sel(page, k, v[k])


def set_attrs(page, **kw):
    for k, v in kw.items():
        name = f"attr_{k}"
        loc = page.locator(f"[name='{name}']").first
        if not loc.count():
            print(f"  [warn] no attribute field {k}")
            continue
        if loc.evaluate("e => e.tagName") == "SELECT":
            sel(page, name, str(v))
        else:
            loc.fill(str(v))


def last_seg(page):
    return page.url.rstrip("/").rsplit("/", 1)[-1].split("?")[0]


# ----------------------------------------------------------------------------- walkthrough
def walkthrough():
    S = Shooter()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        mk = lambda: browser.new_context(viewport={"width": 1280, "height": 820}, device_scale_factor=SCALE)
        ctx_jd, ctx_as, ctx_admin = mk(), mk(), mk()

        # 1. Login
        page = login(ctx_jd, "jdoe")
        S.take(page, "01_login", [("input[name=username]", "Username (the account name, not the display name)"),
                                  ("form button", "Sign in")],
               caption="Every page requires a login. Accounts are created by an admin from the Users page or the command line.")
        page.click("form button")
        page.wait_for_url(BASE + "/**")

        # 2. Dashboard
        page.goto(BASE + "/")
        S.take(page, "02_dashboard", [
            ("header nav a:has-text('Register')", "Register: the only place records are created", "bottom"),
            ("header nav a:has-text('Samples')", "Samples & Participants: read-only browsing", "bottom"),
            ("header .jump input", "Jump box: scan or paste a tube ID to open it", "bottom"),
            ("header nav a:has-text('Audit')", "Audit: every write, with edits and overrides flagged", "bottom"),
            ("h2:has-text('Quick actions')", "Quick actions, counts, recent tubes and recent activity", "right"),
        ], caption="The dashboard after signing in. Nothing on it is editable; it links to the three working areas.")

        # 3. Register landing
        page.goto(BASE + "/register")
        S.take(page, "03_register", [
            ("a:has-text('Register a participant')", "Step 1: a person enrolled in the trial", "right"),
            ("a:has-text('Register a base specimen')", "Step 2: a tube as collected (root of a tree)", "right"),
            ("a:has-text('Register a derived specimen')", "Step 3: a tube made from an existing tube", "right"),
        ], caption="The Register page offers exactly three actions, in the order they happen in the lab.")

        # 4. Participant
        page.goto(BASE + "/participants/new")
        sel(page, "cohort_code", "MP")
        fill(page, "external_participant_id", "MPE-017")
        sel(page, "site_code", "UNC")
        fill(page, "notes", "Enrolled 2026-10-06, consent v3.")
        S.take(page, "04_participant_form", [
            ("input[name=participant_id]", "Left blank: the seven-letter code is generated (no I or O)"),
            ("select[name=cohort_code]", "Cohort, from the cohort code list"),
            ("input[name=external_participant_id]", "The site's own ID for cross-reference"),
            ("form button[type=submit]", "Create"),
        ], caption="Registering a participant. Only the cohort is mandatory; the participant code is issued by the system.")
        page.click("form button[type=submit]")
        page.wait_for_url(BASE + "/participants/*")
        PID = last_seg(page)
        meta["ids"]["participant"] = PID
        S.take(page, "05_participant_detail", [
            (".flash", "Confirmation with the generated code"),
            ("a:has-text('Register a collected specimen')", "Go straight to registering this participant's first tube", "right"),
            ("a:has-text('Tree view')", "Opens the read-only tree for this participant", "right"),
        ], caption="The participant record. It lists every collection and links to the tree.")

        # 6. Base specimen
        page.goto(BASE + f"/samples/new?participant={PID}")
        fill(page, "collection_date", "2026-10-06")
        sel(page, "specimen", "PF")
        sel(page, "fraction", "BLK")
        sel(page, "material", "NAT")
        page.wait_for_selector("[name=attr_container_type]", timeout=5000)
        fill_common(page, quantity=50, unit="mL", sop_code="SOP-001",
                    notes="Received from OR at 14:05. About 50 mL, cloudy, no clots.")
        set_attrs(page, container_type="BAG", time_collected="2026-10-06T13:10", time_received="2026-10-06T14:05",
                  transport_temp="4C", appearance="turbid", hemolysis_grade="none")
        S.take(page, "06_base_specimen_form", [
            ("select[name=participant]", "Participant chosen on the previous page"),
            ("select[name=specimen]", "Specimen, fraction and material as received: these become ID segments"),
            ("select[name=sop_code]", "Every field is a dropdown; lists are maintained under Codes"),
            ("select[name=freezer]", "Storage location: freezer, rack, box, position"),
            ("[name=attr_container_type]", "Metadata fields appear for the chosen fraction and material"),
            ("textarea[name=notes]", "Notes: the only free-text field in the system", "right"),
            ("button[value=create]", "Create: the tube ID is composed by the database"),
        ], full=True, max_h=1500,
            caption="Registering the collected pleural fluid. All fields are required; NA is an explicit choice where a field does not apply.")
        page.click("button[value=create]")
        page.wait_for_url(BASE + "/samples/IGI-*")
        ROOT_ID = last_seg(page)
        meta["ids"]["root"] = ROOT_ID
        S.take(page, "07_root_detail", [
            ("h1 code", "The issued ID: IGI-MP-participant-date-PF-BLK-NAT-01"),
            ("a:has-text('Derive new tube')", "Derive children directly from this tube", "right"),
            ("h2:has-text('Metadata')", "Metadata recorded on the form", "right"),
            ("a.btn:has-text('Edit')", "Edit applies at once and is flagged in the history"),
            ("h2:has-text('Chain of custody')", "Append-only hand-off log", "right"),
        ], full=True, max_h=1500, caption="The tube page for the new root specimen.")

        # 8. Derived specimen: pick parent
        page.goto(BASE + f"/samples/derive?participant={PID}&fraction=PFM&material=CPU")
        page.wait_for_selector("input[name=parent_id]")
        page.locator("input[type=radio][name=parent_id]").first.check()
        S.take(page, "08_derive_pick", [
            ("select[name=material]", "Say what the new tube will be: participant, fraction and material", "right"),
            ("button:has-text('Find eligible')", "Find eligible parent tubes", "right"),
            ("table.compact", "Only tubes the derivation rules accept as inputs are listed", "right"),
            ("button:has-text('Continue with this parent')", "Continue with the selected parent"),
        ], full=True, max_h=1100,
            caption="Registering a derived specimen starts from the product, not the parent. Here: PFMC (pleural fluid mononuclear cells), cryopreserved.")
        page.click("button:has-text('Continue with this parent')")
        page.wait_for_selector("input[name=count]")
        sel(page, "fraction", "PFM")
        sel(page, "material", "CPU")
        page.wait_for_selector("[name=attr_isolation_method]", timeout=5000)
        fill_common(page, count=2, created_datetime="2026-10-06T17:45", sop_code="SOP-002", quantity=1, unit="mL",
                    freezer="LN2-1", rack="R1", box="B02", position="A1",
                    notes="Ficoll prep, 2 vials at 5e6 cells/vial in CS10.")
        set_attrs(page, isolation_method="FICOLL", rbc_lysis="no", cell_count=12000000, viability_pct=91,
                  count_method="Countess", cryo_medium="CS10", cells_per_vial=5000000, freeze_method="MRFROSTY",
                  storage_phase="LN2 vapor")
        page.check("input[name=parent_consumed]")
        S.take(page, "09_derive_form", [
            ("h2 code", "The parent tube", "right"),
            ("input[name=count]", "Number of tubes: two aliquots get consecutive numbers"),
            ("[name=attr_isolation_method]", "Metadata for PFM and CPU: isolation, counts, viability, cryo medium"),
            ("input[name=parent_consumed]", "Marks the parent Depleted in the same step"),
            ("button[value=create]", "Create"),
        ], full=True, max_h=1500, caption="The derived-tube form. Fraction and material are fixed from step 1; the rest is filled in.")
        page.click("button[value=create]")
        page.wait_for_url(BASE + "/samples/IGI-*")
        CPU1 = last_seg(page)
        CPU2 = CPU1[:-2] + "02"
        meta["ids"]["cpu1"], meta["ids"]["cpu2"] = CPU1, CPU2
        S.take(page, "10_derived_detail", [
            (".flash", "Two tubes created: ...-01 and ...-02"),
            (f"a:has-text('{ROOT_ID}')", "Parent link; the parent is now Depleted"),
            ("h2:has-text('Metadata')", "Metadata stored with the tube", "right"),
        ], full=True, max_h=1300, caption="The first cryovial. Its parent is one click away, and so is every ancestor.")

        # 11. Blocked by rules
        page.goto(BASE + f"/samples/{ROOT_ID}/derive")
        sel(page, "fraction", "SER")
        sel(page, "material", "NAT")
        fill_common(page, sop_code="SOP-001", quantity=2, unit="mL", notes="Attempted serum from pleural fluid.")
        page.click("button[value=create]")
        page.wait_for_selector(".violations")
        page.fill(".violations textarea[name=justification]", "Pilot: serum-like supernatant requested by the biomarker group; recorded as an exception.")
        S.take(page, "11_rule_block", [
            (".violations h3", "The rule table blocks this derivation; nothing was saved"),
            (".violations ul", "The specific rules violated", "right"),
            ("button[value=override]", "Create anyway: needs a justification, and is flagged in the audit log"),
        ], full=True, max_h=1500, caption="Trying to register serum from pleural fluid. The derivation rules refuse; the operator may override with a written justification.")
        page.click("button[value=override]")
        page.wait_for_url(BASE + "/samples/IGI-*")
        SER1 = last_seg(page)
        meta["ids"]["ser"] = SER1
        S.take(page, "12_override_created", [
            (".flash", "Created, with the override noted"),
            ("a.tag.warn", "The tube carries a 'rule override' flag for life", "right"),
            ("h2:has-text('Record history')", "The history row holds the rules broken and the justification", "right"),
        ], full=True, max_h=2000, caption="The tube created by the override. It is flagged on its page and in the audit log, with the justification.")

        # 12. HMW DNA from a cryovial
        page.goto(BASE + f"/samples/{CPU1}/derive")
        sel(page, "fraction", "PFM")
        sel(page, "material", "HMD")
        page.wait_for_selector("[name=attr_extraction_kit]", timeout=5000)
        fill_common(page, created_datetime="2026-10-08T11:20", sop_code="SOP-003", quantity=40, unit="uL",
                    freezer="FRZ-A", rack="R2", box="B01", position="B3", notes="Nanobind extraction for ONT.")
        set_attrs(page, extraction_kit="NANOBIND", kit_lot="LOT-24091", concentration_ng_ul=85.2,
                  concentration_method="Qubit", a260_280=1.84, a260_230=2.1, volume_ul=40, din=9.4, n50_kb=62,
                  elution_buffer="EB", input_cells=2500000)
        page.click("button[value=create]")
        page.wait_for_url(BASE + "/samples/IGI-*")
        HMD1 = last_seg(page)
        meta["ids"]["hmd1"] = HMD1

        # 13. Browse tree
        page.goto(BASE + f"/browse?participant={PID}")
        page.wait_for_selector("#tree-svg g.node")
        S.take(page, "13_tree", [
            ("ul li.sel", "Pick a participant"),
            ("#tree-svg", "Every collection and everything derived from it, top down", "right"),
        ], caption="Samples & Participants: a read-only view. Depleted tubes are shown with their status.")
        node = page.locator("#tree-svg g.node", has_text="HMD")
        node.hover()
        page.wait_for_selector("#tree-tip:not([hidden])")
        S.take(page, "14_tree_hover", [("#tree-tip", "Hover shows status, quantity, location and key metadata")],
               caption="Hovering a node.")
        node.click()
        page.wait_for_selector("#tree-panel:not([hidden])")
        page.mouse.move(5, 5)
        page.wait_for_timeout(200)
        S.take(page, "15_tree_panel", [("#tree-panel", "Click pins the details", "right"),
                                        ("#tree-panel a:has-text('Open tube page')", "The only way out is to the tube page", "right")],
               full=True, max_h=1500, caption="Clicking a node pins its details, with all metadata, and a link to the tube page.")

        # 16. Custody
        page.goto(BASE + f"/samples/{HMD1}")
        page.click("summary:has-text('Record a hand-off')")
        fill(page, "event_datetime", "2026-10-09T09:15")
        sel(page, "from_party", "JD")
        sel(page, "to_party", "HTSF")
        sel(page, "purpose", "SEQ")
        sel(page, "condition_on_receipt", "good")
        sel(page, "set_status", "In use")
        fill(page, "notes", "Submitted for ONT sequencing, run requested.")
        form = page.locator("form[action$='/custody']")
        form.scroll_into_view_if_needed()
        S.take(page, "16_custody_form", [
            ("select[name=from_party]", "From: a user or a party such as HTSF or CCPD", "top"),
            ("select[name=purpose]", "Purpose, from the custody purpose list", "top"),
            ("select[name=set_status]", "Optionally update the tube status in the same step"),
            ("form[action$='/custody'] button", "Record"),
        ], full=True, max_h=2000, caption="Recording a hand-off of the DNA tube to the sequencing core.")
        form.locator("button").click()
        page.wait_for_load_state()

        # 17. Edit (direct, audited)
        page.goto(BASE + f"/samples/{HMD1}/edit")
        fill(page, "quantity", "36")
        fill(page, "attr_concentration_ng_ul", "82.7")
        page.fill("textarea[name=justification]", "Used 4 uL for TapeStation and Qubit re-check; concentration updated from the re-measurement.")
        S.take(page, "17_edit_form", [
            ("p.muted", "Changes apply at once and are flagged in the audit log", "right"),
            ("input[name=quantity]", "Quantity 40 to 36"),
            ("[name=attr_concentration_ng_ul]", "Metadata is edited on the same form"),
            ("textarea[name=justification]", "Optional reason, kept with the audit row"),
            ("form button[type=submit]", "Save"),
        ], full=True, max_h=1700, caption="Modifying a record. The before and after values and the reason go to the audit log.")
        page.click("form button[type=submit]")
        page.wait_for_url(BASE + f"/samples/{HMD1}")
        S.take(page, "18_edit_saved", [
            (".flash", "Saved; the number of changed fields is reported"),
            ("a.tag:has-text('edited')", "The tube is marked as edited from now on", "right"),
            ("tr:has(th:has-text('Quantity')) td", "Quantity now 36", "right"),
            ("h2:has-text('Record history')", "Flagged rows: the edit with before/after and the reason, and the custody status change", "right"),
        ], full=True, max_h=2100, caption="The DNA tube straight after the edit. Flagged history rows are anything other than the original creation.")

        # 19. A second user's edit (the audit log shows who did what)
        page2 = login(ctx_as, "asmith")
        page2.click("form button")
        page2.wait_for_url(BASE + "/**")
        page2.goto(BASE + f"/samples/{CPU2}/edit")
        sel(page2, "box", "B04")
        sel(page2, "position", "C3")
        page2.fill("textarea[name=justification]", "Moved during the LN2 rack reorganisation.")
        page2.click("form button[type=submit]")
        page2.wait_for_url(BASE + f"/samples/{CPU2}")

        # 24. Audit log: everything for one tube, then changes only
        page.goto(BASE + f"/admin/audit?record={HMD1}")
        S.take(page, "24_audit", [
            ("form.filters", "Filter by table, record ID or user, or show changes only", "right"),
            ("th:has-text('Before')", "Before and After as key: value lines", "bottom"),
            ("th:has-text('Reason')", "The operator's stated reason for edits, deletions and overrides", "bottom"),
        ], caption="The audit log filtered to one tube. Inserts, updates, custody and metadata writes all appear here; edits are flagged.")
        page.goto(BASE + "/admin/audit?changes=1")
        S.take(page, "24b_audit_changes", [
            ("input[name=changes]", "Changes only: edits, deletions, restores and rule overrides", "top"),
            ("table tbody tr.flag", "Each flagged row names who, when, what changed and why", "bottom"),
        ], full=True, max_h=2400, caption="The changes-only view: the review queue replaced by a filter. Alex Smith's vial move, Jane Doe's edit, the custody status change and the earlier rule override are all here.")

        # 25. QC import
        src = ROOT / "tests" / "fixtures" / "instrument_exports" / "countess3_synthetic.csv"
        qc = DEMO / "countess_export.csv"
        with open(src, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
        hdr = rows[0]
        i_name = hdr.index("Sample name")
        rows[1][i_name] = CPU2 + " thaw check"
        with open(qc, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)
        page.goto(BASE + "/qc/import")
        page.set_input_files("input[name=file]", str(qc))
        sel(page, "instrument", "countess3")
        S.take(page, "25_qc_upload", [
            ("input[name=file]", "One instrument export file"),
            ("select[name=instrument]", "Instrument: auto-detected if left blank"),
            ("form button[type=submit]", "Upload and parse"),
        ], caption="Importing a Countess 3 cell-count export.")
        page.click("form button[type=submit]")
        page.wait_for_url(BASE + "/qc/import/*")
        S.take(page, "26_qc_confirm", [
            ("table tbody tr:first-child td:nth-child(2) code", "The instrument's sample name"),
            ("input[name=tube_0]", "Suggested tube ID: matched because the name contains it", "bottom"),
            ("table tbody tr:first-child td:nth-child(5)", "Untick any value you do not want written", "top"),
            ("button:has-text('Write values')", "Write values to tubes"),
        ], full=True, max_h=1000, caption="One row per instrument sample. Rows with no tube ID are skipped; the blank slide stays blank.")
        page.click("button:has-text('Write values')")
        page.wait_for_load_state()
        page.goto(BASE + f"/samples/{CPU2}")
        S.take(page, "27_qc_provenance", [
            ("h2:has-text('Metadata')", "Imported values, with a link to the stored export file", "right"),
            ("a:has-text('file #')", "Source file", "right"),
        ], full=True, max_h=1300, caption="The second cryovial after import. Each imported value points back to the file it came from.")

        # 28. Admin pages
        page3 = login(ctx_admin, "admin")
        page3.click("form button")
        page3.wait_for_url(BASE + "/**")
        page3.goto(BASE + "/admin/codes?category=freezer")
        S.take(page3, "28_codes", [
            ("h3:has-text('Add a code')", "Add an entry to any list", "right"),
            ("button:has-text('Add list')", "Create a whole new list for a new metadata field", "right"),
        ], full=True, max_h=1100, caption="The Codes page. Entries are retired, never deleted, so old records keep their meaning.")
        page3.goto(BASE + "/admin/fields")
        S.take(page3, "29_fields", [("form", "Add a metadata field: scope, label, type, unit, list, required")],
               full=True, max_h=1100, caption="The Fields page defines which metadata each fraction or material carries.")
        page3.goto(BASE + "/admin/rules")
        S.take(page3, "30_rules", [], full=True, max_h=1000,
               caption="The Rules page: which fractions a specimen may have, and which transitions are allowed.")
        page3.goto(BASE + "/admin/users")
        S.take(page3, "31_users", [("form", "Create a user with a role: admin, user or viewer")],
               caption="The Users page.")

        browser.close()
    (OUT / "meta.json").write_text(json.dumps(meta, indent=1))


if __name__ == "__main__":
    print("building demo database ...")
    build_demo_db()
    proc = start_server()
    try:
        walkthrough()
    finally:
        proc.terminate()
        proc.wait()
    print("done:", OUT)
