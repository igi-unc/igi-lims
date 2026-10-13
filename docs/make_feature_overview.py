"""Render docs/IGI_LIMS_feature_overview.pdf.

Run: .venv/bin/python docs/make_feature_overview.py
"""
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (ListFlowable, ListItem, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

OUT = Path(__file__).with_name("IGI_LIMS_feature_overview.pdf")

ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontSize=18, spaceAfter=8, spaceBefore=14)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontSize=13, spaceAfter=4, spaceBefore=10)
BODY = ParagraphStyle("Body", parent=ss["BodyText"], fontSize=10, leading=13.5, alignment=TA_LEFT)
SMALL = ParagraphStyle("Small", parent=BODY, fontSize=8.5, leading=11, textColor=colors.HexColor("#444444"))
MONO = ParagraphStyle("Mono", parent=BODY, fontName="Courier", fontSize=9.5, leading=12,
                      backColor=colors.HexColor("#f3f3f3"), borderPadding=4, spaceBefore=4, spaceAfter=6)
TITLE = ParagraphStyle("Title", parent=ss["Title"], fontSize=24, spaceAfter=4)
SUB = ParagraphStyle("Sub", parent=BODY, fontSize=11, textColor=colors.HexColor("#555555"))


def p(text, style=BODY):
    return Paragraph(text, style)


def bullets(items):
    return ListFlowable(
        [ListItem(p(i)) for i in items],
        bulletType="bullet", start="•", leftIndent=16, bulletFontSize=9, bulletOffsetY=-1, spaceBefore=2, spaceAfter=6,
    )


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


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#777777"))
    canvas.drawString(0.8 * inch, 0.55 * inch, "IGI LIMS feature overview")
    canvas.drawRightString(letter[0] - 0.8 * inch, 0.55 * inch, f"Page {doc.page}")
    canvas.restoreState()


story = []
story += [
    p("IGI LIMS", TITLE),
    p("Feature overview of the specimen tracking system, as built to date", SUB),
    p(f"PIRL, UNC · {date.today():%B %d, %Y} · status: prototype, specification in flight", SUB),
    Spacer(1, 14),
]

story += [p("1. Purpose", H1), p(
    "IGI LIMS is a chain-of-custody database and web interface for the biological specimens collected in the "
    "IGI cancer clinical trial. It records one row per tube. Every tube stores the tube it was made from, so the "
    "path from a collected specimen, through fractionation, cryopreservation, extraction and library preparation, "
    "to the sequencing or mass-spectrometry data file is a chain of parent links that can be walked in either "
    "direction. The system runs as a single Flask application on SQLite with no external services, suitable for a "
    "small lab (about two dozen users) on a workstation or a GCP virtual machine."),
]

story += [p("2. Tube identifiers", H1), p(
    "Identifiers are composed by the database from the tube's attributes. They are never typed by hand. The "
    "format is defined in one place (<font face='Courier'>config.py</font>, <font face='Courier'>ID_SEGMENTS</font>) "
    "so that it can change as the specification settles without touching the schema."),
    p("IGI-CC-PPPPPPP-YYMMDD-SS-FFF-MMM-AA   (35 characters)", MONO),
    table(["Segment", "Meaning", "Validation"], [
        ["IGI", "Project constant", "literal"],
        ["CC", "Cohort", "active code in the cohort list (MP, AM, TN, NC)"],
        ["PPPPPPP", "Participant code", "seven upper-case letters, no I or O"],
        ["YYMMDD", "Collection date", "parsed as a calendar date"],
        ["SS", "Specimen type", "active code in the specimen list (PF, PB, BM, TU, LN, ...)"],
        ["FFF", "Fraction", "active code in the fraction list (BLK, PLA, PBM, CD8, ...)"],
        ["MMM", "Material", "active code in the material list (NAT, CPU, DNA, LIB, PEP, ...)"],
        ["AA", "Aliquot number", "01 to 99, issued per prefix by the database, never reused"],
    ], [1.0 * inch, 1.6 * inch, 4.2 * inch]),
    p("The aliquot counter is taken over all tubes including deleted ones, so an ID can never refer to two "
      "different physical tubes. The anchored regular expression for the current format is published at "
      "<font face='Courier'>/api/pattern</font> for pipelines and validation scripts."),
]

story += [p("3. What the system enforces", H1),
    p("Controlled vocabularies", H2), p(
    "Every code used in IDs, forms and metadata lives in one code-list table and is managed on the Codes page. "
    "Codes are retired rather than deleted, so historical records keep their meaning. Currently 46 categories are "
    "defined: the core ID vocabularies (cohort, specimen, fraction, material), status, assay, biobank source, "
    "site, unit, and admin-extendable lists for SOPs, freezers, racks, boxes, positions, custody parties and "
    "purposes, kits, lots, buffers, media, antibodies, instruments and so on. Administrators can add new "
    "categories without a code change."),
    p("No free text except Notes", H2), p(
    "Every tube, custody and metadata field other than the Notes box is a dropdown backed by one of these "
    "lists. The operator must be an active user account. Server-side checks reject any value that is not an "
    "active entry, so the database cannot drift into inconsistent spellings. The only remaining free-text "
    "fields are machine identifiers copied from pipeline output (data file URI, run ID, checksum) and the "
    "participant's external site ID."),
    p("Derivation rules", H2), p(
    "A rule table (Rules page, 140 rules seeded as a starting proposal) decides which fractions a specimen type "
    "may have, which fraction-to-fraction and material-to-material transitions are allowed, which materials a "
    "root tube may arrive as, and which fractions a material may carry. A violation blocks creation and offers "
    "a Request override button instead of silently accepting the record."),
    p("Two-person agreement", H2), p(
    "Overrides of derivation rules, and by default every edit, delete or restore of a sample record, go to an "
    "Approvals queue. The requester cannot approve their own request. The approver's decision applies the "
    "change, and the audit log records the approval ID alongside the change. The scope can be relaxed in "
    "configuration to provenance-only changes (parent, ID components, delete) or switched off."),
    p("Soft deletes and full audit", H2), p(
    "Deleting a tube keeps the record, keeps the aliquot number reserved, and is refused while the tube has "
    "active children. Every write (participants, samples, custody, files, metadata, attachments, code lists, "
    "users) is recorded in the audit log with who, when, and a before and after snapshot shown as key and "
    "value lines."),
]

story += [p("4. Registration workflow", H1), p(
    "The Register landing page offers exactly three actions and nothing else, to keep one obvious path for each task."),
    bullets([
        "<b>Participant.</b> Create a participant with cohort, generated participant code, and external site ID.",
        "<b>Base specimen.</b> Register a collected tube (a root with no parent): specimen type, collection date, "
        "fraction and material on arrival, biobank source (CCPD, HemaTrack, in-house, or not applicable), "
        "operator, SOP, quantity and unit, storage location, status, and notes. All fields are required; "
        "lists carry an NA entry where the question does not apply.",
        "<b>Derived specimen.</b> Choose the participant, then the fraction and material of the tube being made. "
        "The system lists only the parent tubes from that participant that the derivation rules accept as "
        "inputs, and shows the ineligible ones with the reason. Creating the child can mark the parent as "
        "depleted in the same step.",
    ]),
    p("Each tube page shows its components, parent and children, custody events, data files, attachments, "
      "metadata, and history. Editing goes through the approval queue."),
]

story += [p("5. Browsing: Samples &amp; Participants", H1), p(
    "A single read-only page. Pick a participant and the page draws a tall, top-down tree of every collection "
    "and everything derived from it. Hovering a node shows its status, quantity, location and key metadata; "
    "clicking pins that panel with a link to the full tube page. Nothing on this page creates or changes "
    "records, so it is safe to leave open on a shared screen."),
]

story += [p("6. Metadata per fraction and material", H1), p(
    "Metadata fields are defined in one table (Fields page) and attached to a fraction or a material, so a "
    "tube shows only the fields that make sense for what it is. The create and edit forms render these fields "
    "dynamically, the tube page and the tree hover panel display them, and they are included in the audit "
    "diff. Fields are typed as number (with unit), fixed choice, admin-extendable list, yes/no, date, or "
    "date-time. There is no text type. Two fields are required at present: the assay of a sequencing library "
    "and the HLA class of a peptide eluate. 199 field definitions are active today, for example:"),
    table(["Scope", "Examples"], [
        ["Plasma, serum, supernatant", "spin protocol, hemolysis grade, time to processing, filter"],
        ["PBMC, PFMC, buffy coat", "isolation method, viable cell count, viability, hashtag, cryo medium, freeze method"],
        ["Immune, tumor, T-cell fractions", "enrichment or selection method, marker panel, purity, input cells, kit and lot"],
        ["DNA, RNA, HMW DNA/RNA, cfDNA", "extraction kit, concentration, A260/280, A260/230, RIN or DIN, fragment size, elution"],
        ["Sequencing library", "assay, library prep kit, capture kit, index, shearing, molarity, submission"],
        ["Peptide eluate", "HLA class, antibody and lot, bead type, input cells, elution, cleanup, instrument"],
        ["Tissue (snap-frozen, OCT, FFPE)", "block ID, dissociation method, input tissue mass"],
    ], [2.2 * inch, 4.6 * inch]),
]

story += [p("7. QC file import and attachments", H1), p(
    "Any file (trace, image, report) can be attached to a tube; it is stored on disk under the attachment "
    "directory with an md5 checksum. The Import QC page goes further for common instrument exports: upload one "
    "file, the system parses it, shows one row per instrument sample with a suggested tube ID (matched "
    "automatically when the sample name contains a tube ID), and writes the ticked values into the tube's "
    "metadata fields. Each imported value keeps a link back to the stored export file, so the provenance of a "
    "concentration or RIN can be checked later. Imports are direct and audited; manual metadata edits still "
    "go through approval."),
    table(["Instrument", "Format", "Values captured"], [
        ["Qubit 4", "CSV, parsed through allotropy", "concentration (original and diluted), assay, units"],
        ["NanoDrop One", "CSV, parsed through allotropy", "concentration, A260/280, A260/230"],
        ["TapeStation", "XML", "concentration, RIN or DIN, region average size, molarity, percent of total"],
        ["Countess 3", "CSV, columns from the vendor guide", "total, live and dead concentration, viability, cells counted, average size, aggregation"],
    ], [1.3 * inch, 2.2 * inch, 3.3 * inch]),
]

story += [p("8. Custody and data files", H1), p(
    "Custody events are append-only: from and to (a user or an external party such as HTSF or CCPD), purpose "
    "(extraction, sequencing submission, storage, immunopeptidomics, culture, sorting, return, shipment), "
    "timestamp, and condition on receipt. Data files, which live in Google Cloud Storage buckets, are linked "
    "to the tube that was sequenced or run (usually a library or peptide eluate) by URI, with assay, run ID, "
    "checksum and pipeline version. A file is therefore always reachable from the collected specimen it came from."),
]

story += [p("9. Users, roles and administration", H1), bullets([
    "<b>Roles.</b> admin (everything), user (create, derive, edit, approve), viewer (read only). Passwords are hashed; "
    "accounts are created and reset from the command line or the Users page.",
    "<b>Codes.</b> Add, rename or retire entries in any list; add a whole new list; see which fields use each list.",
    "<b>Rules.</b> View and edit the derivation rule table.",
    "<b>Fields.</b> Add metadata fields of any supported type, mark them required, or retire them.",
    "<b>Audit.</b> Searchable log of every change.",
]),
]

story += [p("10. Read-only JSON API", H1), p(
    "For pipelines and scripts. Authenticate with a browser session or an <font face='Courier'>X-Api-Token</font> "
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
]

story += [p("11. Technical summary", H1), bullets([
    "Python 3.10, Flask 3, Jinja templates, a small amount of vanilla JavaScript for the tree and dynamic forms.",
    "SQLite in WAL mode with foreign keys on; one file database, backed up by copying the file.",
    "Schema: code_list, derivation_rule, user, participant, sample, custody_event, data_file, approval_request, "
    "audit_log, attribute_definition, sample_attribute, attachment.",
    "Instrument parsing via allotropy (Benchling open source) for Qubit and NanoDrop; TapeStation and Countess parsed directly.",
    "38 automated tests cover ID composition, the registration and approval workflow, parsers, import, metadata and vocabulary enforcement.",
    "Deployment target: a GCP VM behind gunicorn, reachable by collaborators over the web; not yet set up.",
]),
]

story += [p("12. Open questions (tracked in NOTES.md)", H1), bullets([
    "Participant code format: seven letters as specified, or a site-style code such as P101.",
    "NTC and NRM are three-character specimen codes but the ID segment is two characters.",
    "Whether every edit should require two-person approval, or only provenance changes.",
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
