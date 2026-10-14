"""Render docs/IGI_LIMS_feature_overview.pdf: an illustrated walkthrough of the LIMS.

Screenshots come from docs/screenshots/ (made by docs/walkthrough_capture.py).
Run from the repo root:  .venv/bin/python docs/make_feature_overview.py
"""
import json
from datetime import date
from pathlib import Path

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (Image, KeepTogether, ListFlowable, ListItem, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

HERE = Path(__file__).resolve().parent
SHOTS = HERE / "screenshots"
OUT = HERE / "IGI_LIMS_feature_overview.pdf"
META = json.loads((SHOTS / "meta.json").read_text())
IDS = META["ids"]

PAGE_W = letter[0] - 1.6 * inch
MAX_IMG_H = 7.4 * inch

ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontSize=17, spaceAfter=6, spaceBefore=14)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontSize=12.5, spaceAfter=3, spaceBefore=10)
BODY = ParagraphStyle("Body", parent=ss["BodyText"], fontSize=10, leading=13.5)
SMALL = ParagraphStyle("Small", parent=BODY, fontSize=8.5, leading=11, textColor=colors.HexColor("#444444"))
CAP = ParagraphStyle("Cap", parent=BODY, fontSize=9.5, leading=12.5, textColor=colors.HexColor("#333333"))
MONO = ParagraphStyle("Mono", parent=BODY, fontName="Courier", fontSize=9.5, leading=12,
                      backColor=colors.HexColor("#f3f3f3"), borderPadding=4, spaceBefore=4, spaceAfter=6)
TITLE = ParagraphStyle("Title", parent=ss["Title"], fontSize=24, spaceAfter=4)
SUB = ParagraphStyle("Sub", parent=BODY, fontSize=11, textColor=colors.HexColor("#555555"))


def p(text, style=BODY):
    return Paragraph(text, style)


def bullets(items, style=BODY):
    return ListFlowable([ListItem(p(i, style)) for i in items], bulletType="bullet", start="•", leftIndent=16,
                        bulletFontSize=9, bulletOffsetY=-1, spaceBefore=2, spaceAfter=6)


def numbered(items):
    return ListFlowable([ListItem(p(i, CAP)) for i in items], bulletType="1", leftIndent=18, bulletFontSize=9,
                        bulletColor=colors.HexColor("#d7263d"), bulletFontName="Helvetica-Bold", spaceBefore=2, spaceAfter=8)


def table(header, rows, widths):
    data = [[p(f"<b>{h}</b>", SMALL) for h in header]] + [[p(c, SMALL) for c in r] for r in rows]
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#bbbbbb")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    t.spaceAfter = 8
    return t


def shot(name, heading, intro=None, max_h=MAX_IMG_H, before=()):
    """Heading + intro + annotated screenshot + numbered callout legend."""
    path = SHOTS / f"{name}.png"
    m = META["shots"].get(name, {})
    w, h = PILImage.open(path).size
    iw = PAGE_W
    ih = iw * h / w
    # keep heading, caption, image and legend on one page: budget the image height
    budget = 8.3 * inch - 0.18 * inch * len(m.get("callouts", [])) - (0.45 * inch if intro else 0) - (0.3 * inch if m.get("caption") else 0)
    max_h = min(max_h, budget)
    if ih > max_h:
        ih = max_h
        iw = ih * w / h
    img = Image(str(path), width=iw, height=ih)
    img.hAlign = "LEFT"
    flow = list(before) + [p(heading, H2)]
    if intro:
        flow.append(p(intro))
    if m.get("caption"):
        flow.append(p(f"<i>{m['caption']}</i>", CAP))
    flow.append(Spacer(1, 3))
    flow.append(img)
    flow.append(numbered(m["callouts"]) if m.get("callouts") else Spacer(1, 8))
    return [KeepTogether(flow)]


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#777777"))
    canvas.drawString(0.8 * inch, 0.55 * inch, "IGI LIMS feature overview")
    canvas.drawRightString(letter[0] - 0.8 * inch, 0.55 * inch, f"Page {doc.page}")
    canvas.restoreState()


ROOT, CPU1, CPU2, HMD1, PID = IDS["root"], IDS["cpu1"], IDS["cpu2"], IDS["hmd1"], IDS["participant"]
story = []

# --------------------------------------------------------------------------- title + overview
story += [
    p("IGI LIMS", TITLE),
    p("An illustrated tour of the specimen tracking system, as built to date", SUB),
    p(f"PIRL, UNC · {date.today():%B %d, %Y} · status: prototype, specification in flight", SUB),
    Spacer(1, 12),
    p("1. What it is", H1),
    p("IGI LIMS is a chain-of-custody database and web interface for the biological specimens collected in the IGI "
      "cancer clinical trial. It records one row per tube. Every tube stores the tube it was made from, so the path from "
      "a collected specimen, through fractionation, cryopreservation, extraction and library preparation, to the "
      "sequencing or mass-spectrometry data file is a chain of parent links that can be walked in either direction. "
      "It runs as a single Flask application on SQLite with no external services, sized for a lab of about two dozen "
      "users on a workstation or a GCP virtual machine."),
    p("The screenshots in this document were taken from a throwaway demonstration database. The participant, tubes, "
      "users and lists shown are invented. Red numbered arrows mark the features explained under each picture."),
    p("2. The tube identifier", H1),
    p("Identifiers are composed by the database from the tube's attributes and are never typed by hand. The format is "
      "defined in one configuration list so that it can change as the specification settles without touching the schema."),
    p("IGI-CC-PPPPPPP-YYMMDD-SS-FFF-MMM-AA   (35 characters)", MONO),
    table(["Segment", "Meaning", "Validation"], [
        ["IGI", "Project constant", "literal"],
        ["CC", "Cohort", "active code in the cohort list (MP, AM, TN, NC)"],
        ["PPPPPPP", "Participant code", "seven upper-case letters, no I or O; generated"],
        ["YYMMDD", "Collection date", "parsed as a calendar date"],
        ["SS", "Specimen type", "active code in the specimen list (PF, PB, BM, TU, LN, ...)"],
        ["FFF", "Fraction", "active code in the fraction list (BLK, PLA, PBM, PFM, CD8, ...)"],
        ["MMM", "Material", "active code in the material list (NAT, CPU, DNA, HMD, LIB, PEP, ...)"],
        ["AA", "Aliquot number", "01 to 99, issued per prefix by the database, never reused"],
    ], [1.0 * inch, 1.6 * inch, 4.2 * inch]),
    p(f"The worked example that follows produces <font face='Courier' size='8.5'>{ROOT}</font>: cohort MP, participant "
      f"{PID}, collected 6 October 2026, pleural fluid, unfractionated, native, first aliquot. Its children keep the first "
      "five segments and change only fraction, material and aliquot."),
    p("3. What the system enforces", H1),
    bullets([
        "<b>Controlled vocabularies.</b> Every code used in IDs, forms and metadata lives in one code-list table managed on the "
        "Codes page. Codes are retired rather than deleted, so historical records keep their meaning.",
        "<b>No free text except Notes.</b> Operator, SOP, storage location, custody parties and purposes, and every metadata "
        "vocabulary (kits, lots, buffers, media, antibodies, instruments) are dropdowns. The server rejects values that are "
        "not active list entries. The only remaining free-text fields are machine identifiers (data file URI, run ID, "
        "checksum) and the participant's external site ID.",
        "<b>Derivation rules.</b> A rule table decides which fractions a specimen type may have, which fraction and material "
        "transitions are allowed, and which materials a root tube may arrive as. A violation blocks creation and offers an "
        "override request instead.",
        "<b>Changes are flagged, not queued.</b> Edits, deletions, restores and rule overrides apply immediately, "
        "with the operator's reason, and are flagged in the audit log and on the tube page. The audit log has a "
        "changes-only view for review.",
        "<b>Soft deletes and a full audit log.</b> Deleting a tube keeps the record and its aliquot number, and is refused "
        "while the tube has active children. Every write is recorded with who, when, and before and after values.",
    ]),
]

# --------------------------------------------------------------------------- walkthrough
story += [p("4. Walkthrough: signing in and finding your way", H1)]
story += shot("01_login", "4.1 Sign in")
story += shot("02_dashboard", "4.2 The dashboard")
story += shot("03_register", "4.3 The Register page",
              "All record creation starts here. The three cards are the three kinds of record a lab member creates, "
              "and the order matches the order of events: a participant enrols, a specimen is collected, tubes are derived.")

story += [PageBreak(), p("5. Walkthrough: registering a participant and a base specimen", H1)]
story += shot("04_participant_form", "5.1 Register a participant")
story += shot("05_participant_detail", "5.2 The participant record")
story += shot("06_base_specimen_form", "5.3 Register the collected specimen (the root tube)",
              "A base specimen is a tube with no parent. Its specimen type, fraction and material as received become "
              "segments of the ID. The metadata block at the bottom changes with the fraction and material chosen; for an "
              "unfractionated fluid it asks for container, collection and receipt times, transport temperature, "
              "appearance and hemolysis.")
story += shot("07_root_detail", "5.4 The tube page",
              "Every tube has one page: identity and provenance at the top, then the tube's own fields, metadata, a "
              "printable label layout, custody events, attachments, linked data files, and its full change history.")

story += [PageBreak(), p("6. Walkthrough: deriving tubes", H1),
          p("A derived tube is any tube made from another: a cryovial from a cell preparation, DNA from a pellet, a "
            "library from DNA. The registration flow asks what is being made first and then offers only the parents that "
            "the rules allow, so the operator never has to work out eligibility by hand.")]
story += shot("08_derive_pick", "6.1 Choose what to make, then choose the parent")
story += shot("09_derive_form", "6.2 Fill in the new tubes",
              "Here two cryovials of PFMC are made from the pleural fluid. Metadata for a PFM fraction (isolation method, "
              "cell count, viability, counting method) and for a CPU material (cryoprotectant, cells per vial, freezing "
              "method, storage phase) appear together.")
story += shot("10_derived_detail", "6.3 The result",
              f"The two tubes are {CPU1} and {CPU2}. The parent, now marked Depleted, is one click away.")
story += shot("11_rule_block", "6.4 When the rules say no",
              "Here the operator tried to register serum derived from pleural fluid, from a parent that is already "
              "depleted. The form refuses, lists the reasons, and offers an override request with a mandatory justification. "
              "The override needs a written justification and is flagged for life on the tube and in the audit log.")
story += shot("12_override_created", "6.5 The tube created by the override")
story += [p("A third derivation, not shown as a form, extracted high-molecular-weight DNA from the first cryovial "
            f"to make {HMD1}. It appears in the tree and is the tube edited in section 8.")]

story += [PageBreak(), p("7. Walkthrough: browsing", H1),
          p("Samples &amp; Participants is the one read-only page. It is safe to leave open on a shared screen, "
            "because nothing on it creates or changes a record.")]
story += shot("13_tree", "7.1 The participant tree")
story += shot("14_tree_hover", "7.2 Hover for details")
story += shot("15_tree_panel", "7.3 Click to pin")

story += [PageBreak()]
story += shot("16_custody_form", "8.1 Record a hand-off", before=[p("8. Walkthrough: custody and editing", H1)], intro=
              "Custody events are append-only. Each records from, to, purpose, time and condition. "
              "The DNA tube is handed to the sequencing core here and marked In use in the same step.")
story += shot("17_edit_form", "8.2 Modify a record",
              "Jane Doe re-measured the DNA and used some of it for QC, so the quantity and the concentration need to "
              "change. The edit form is the same for tube fields and metadata.")
story += shot("18_edit_saved", "8.3 The tube after the edit",
              "Quantity and concentration show the new values at once. The tube is marked as edited, and the history "
              "lists the change with before and after values and the reason, next to the custody status change and the "
              "original creation. A second user (Alex Smith) then moves a cryovial to another box the same way.")

story += [PageBreak(), p("9. Walkthrough: the audit log", H1)]
story += shot("24_audit", "9.1 Everything that happened to one tube",
              "The audit log is the system-wide version of the history block on each tube page. It covers "
              "participants, tubes, custody, data files, metadata, attachments, code lists, fields and users. "
              "Before and After are shown as one key and value per line so a reviewer can read them without parsing JSON.")
story += shot("24b_audit_changes", "9.2 Changes only",
              "One checkbox hides routine creations and logins and leaves edits, deletions, restores and rule overrides, "
              "each with who, when, before, after and the stated reason. This is the review view that replaces an approval queue.")

story += [PageBreak(), p("10. Walkthrough: importing instrument QC files", H1),
          p("Common instrument exports can be loaded directly instead of typing numbers into metadata fields. "
            "Supported today: Qubit 4 and NanoDrop One exports (parsed through the allotropy library), TapeStation XML, "
            "and Countess 3 CSV. The example below imports a Countess cell count.")]
story += shot("25_qc_upload", "10.1 Upload one export")
story += shot("26_qc_confirm", "10.2 Confirm what goes where")
story += shot("27_qc_provenance", "10.3 Provenance of imported values",
              "Each value written by an import keeps a link to the stored export file, so a concentration or viability "
              "can always be traced to the instrument run it came from. The export itself is kept as an attachment.")

story += [PageBreak(), p("11. Administration", H1),
          p("Administrators see four extra pages. None of them require a code change or a restart.")]
story += shot("28_codes", "11.1 Codes: every controlled vocabulary", max_h=4.2 * inch)
story += shot("29_fields", "11.2 Fields: which metadata each fraction and material carries",
              "Fields are typed as number (with unit), fixed choice, admin-extendable list, yes/no, date or date-time. "
              "There is no text type. A field can be marked required.", max_h=4.2 * inch)
story += shot("30_rules", "11.3 Rules: allowed specimens, fractions and transitions", max_h=4.0 * inch)
story += shot("31_users", "11.4 Users and roles",
              "Roles are admin (everything), user (create, derive, edit) and viewer (read only).", max_h=3.6 * inch)

# --------------------------------------------------------------------------- reference
story += [PageBreak(), p("12. Also available", H1),
    p("Data files", H2),
    p("Sequencing and mass-spectrometry outputs live in Google Cloud Storage buckets. A data file record links a bucket "
      "URI to the tube that was sequenced or run (usually a library or a peptide eluate), with assay, run ID, checksum and "
      "pipeline version, so a file is always reachable from the collected specimen it came from. Files can be linked from "
      "the tube page or by a pipeline through the API."),
    p("Attachments", H2),
    p("Any file (trace, image, report) can be attached to a tube. It is stored on disk under the attachment directory "
      "with an md5 checksum and listed on the tube page."),
    p("Read-only JSON API", H2),
    p("For pipelines and scripts. Authenticate with a browser session or an <font face='Courier'>X-Api-Token</font> "
      "header matching the token set in the server environment."),
    table(["Endpoint", "Returns"], [
        ["/api/pattern", "anchored regex and fixed length for IDs"],
        ["/api/validate/&lt;id&gt;", "the ID parsed into components, and whether it exists"],
        ["/api/samples?participant=&amp;root=&amp;material=&amp;status=&amp;prefix=", "list of tubes"],
        ["/api/samples/&lt;id&gt;", "one tube with custody events and files"],
        ["/api/samples/&lt;id&gt;/lineage", "ancestors (root first) and all descendants"],
        ["/api/tree/&lt;root_id&gt;", "nested tree for one collection"],
        ["/api/files", "data files with their tube and lineage"],
    ], [3.2 * inch, 3.6 * inch]),
    p("Technical summary", H2),
    bullets([
        "Python 3.10, Flask 3, Jinja templates, a small amount of vanilla JavaScript for the tree and dynamic forms.",
        "SQLite (one file, WAL mode) for local use, or PostgreSQL (Supabase) when hosted on Vercel; the same code runs on both.",
        "Tables: code_list, derivation_rule, account, participant, sample, custody_event, data_file, "
        "audit_log, attribute_definition, sample_attribute, attachment.",
        "Instrument parsing via allotropy (Benchling open source) for Qubit and NanoDrop; TapeStation and Countess parsed directly.",
        "42 automated tests cover ID composition, registration, editing, overrides, parsers, import, metadata and vocabulary enforcement; they run against SQLite and PostgreSQL.",
        "Hosting: a public demonstration instance on Vercel with Supabase Postgres (docs/DEPLOY_VERCEL_SUPABASE.md); a GCP VM remains an option for production.",
    ]),
    p("13. Open questions (tracked in NOTES.md)", H1),
    bullets([
        "Participant code format: seven letters as specified, or a site-style code such as P101.",
        "NTC and NRM are three-character specimen codes but the ID segment is two characters.",
        "The seeded derivation rules are a proposal and need review by the lab.",
        "Which metadata fields should be required.",
        "Most admin-extendable lists start with only NA and need real freezers, racks, boxes, SOPs and kits before first use.",
        "The Countess parser follows the vendor column specification and has not yet been checked against a real export.",
    ]),
]

doc = SimpleDocTemplate(str(OUT), pagesize=letter, leftMargin=0.8 * inch, rightMargin=0.8 * inch,
                        topMargin=0.8 * inch, bottomMargin=0.8 * inch,
                        title="IGI LIMS feature overview", author="PIRL, UNC")
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print(OUT)
