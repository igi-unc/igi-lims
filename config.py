"""
Site configuration for the IGI LIMS.

Everything about the sample-ID format lives here so that spec changes are a
one-file edit. The database stores the parsed components as columns; if a
segment is added or renamed, add a column in lims/schema.sql and a line in
ID_SEGMENTS, nothing else.
"""
import os

# ---------------------------------------------------------------------------
# Sample ID format: IGI Sample Nomenclature v2.1 (2026-10-19)
#
# Each segment: (name, regex, kind). `kind` controls validation:
#   "const"         -> regex is a literal
#   "code:<cat>"    -> value must be an active code in code_list for that category
#   "date:yymmmdd"  -> 2-digit year, 3-letter uppercase month, 2-digit day (26SEP29); stored as ISO date
#   "int"           -> integer (the aliquot counter issued by the database)
#   "operator"      -> initials of an active user (2 or 3 uppercase letters)
#   None            -> regex only
#
#   IGI-CC-PNNN-UNCNNN-YYMMMDD-SS-FFF-MMM-AA-OO(O)-YYMMMDD   (51 or 52 characters)
#   IGI-MP-P101-UNC316-26SEP29-PF-TUM-HMD-01-MF-26SEP29
#
# The v2 format (35 characters, 7-letter participant code) is preserved at git tag v2-final.
# ---------------------------------------------------------------------------
_MONTH = r"(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
_DAY = r"(?:0[1-9]|[12]\d|3[01])"
ID_SEGMENTS = [
    ("project",         r"IGI",                       "const"),
    ("cohort",          r"[A-Z]{2}",                  "code:cohort"),
    ("participant",     r"P\d{3}",                    None),
    ("unc_id",          r"UNC\d{3}",                  None),
    ("received_date",   r"\d{2}" + _MONTH + _DAY,     "date:yymmmdd"),
    ("specimen",        r"[A-Z]{2}",                  "code:specimen"),
    ("fraction",        r"[A-Z0-9]{3}",               "code:fraction"),
    ("material",        r"[A-Z0-9]{3}",               "code:material"),
    ("aliquot",         r"(?:0[1-9]|[1-9]\d)",        "int"),
    ("operator",        r"[A-Z]{2,3}",                "operator"),
    ("processing_date", r"\d{2}" + _MONTH + _DAY,     "date:yymmmdd"),
]
ID_SEPARATOR = "-"
ID_LENGTH = None        # 51 or 52: the operator is 2 or 3 letters. The pattern, not the length, catches errors.
ALIQUOT_WIDTH = 2
ALIQUOT_MAX = 99
# Printed label stock (Brady M611 with M6-17-492 cryo labels: 1.0 x 0.5 inch, 300 dpi).
LABEL_STOCK = {"part": os.environ.get("LIMS_LABEL_PART", "M6-17-492"),
               "width_in": float(os.environ.get("LIMS_LABEL_WIDTH_IN", "1.0")),
               "height_in": float(os.environ.get("LIMS_LABEL_HEIGHT_IN", "0.5")),
               "dpi": int(os.environ.get("LIMS_LABEL_DPI", "300"))}
# Page layout for Windows-printer stations. "portrait" (calibration LAYOUT C: upright 0.5 x 1 in page, label turned
# left) is what Brady's M611 driver needs for M6-17-492, confirmed with a test print on 2026-10-30. Other values:
# "landscape" (A), "landscape-flip" (B), "portrait-right" (D).
LABEL_PRINT_LAYOUT = os.environ.get("LIMS_LABEL_PRINT_LAYOUT", "portrait")
BRADY_SDK_URL = os.environ.get("LIMS_BRADY_SDK_URL",
                               "https://cdn.jsdelivr.net/npm/@bradycorporation/brady-web-sdk@3.3.3/dist/bundle.js")
PRINT_JOB_MAX_LABELS = 200
# Camera scanning: browsers without a built-in Data Matrix reader (Safari on iPad/iPhone, Chrome on Windows) load
# this BarcodeDetector ponyfill (ZXing-C++ in WebAssembly, MIT licence), version pinned.
BARCODE_READER_URL = os.environ.get("LIMS_BARCODE_READER_URL",
                                    "https://fastly.jsdelivr.net/npm/barcode-detector@3.2.3/dist/es/ponyfill.min.js")
# Label: three rows of at most 18 characters, broken at hyphens, beside a Data Matrix of the full ID.
LABEL_ROWS = [["project", "cohort", "participant", "unc_id"],
              ["received_date", "specimen", "fraction", "material"],
              ["aliquot", "operator", "processing_date"]]

# IGI patient numbers are issued in sequence (P001, P002, ...) and never reused; admins may enter one.
PARTICIPANT_PREFIX = "P"
PARTICIPANT_DIGITS = 3
UNC_DIGITS = 3

# Fields printed on the tube label. Once a tube exists they cannot be edited, because the
# printed label (and any file named after the ID) would then disagree with the record.
# A mistake is fixed by adding a correction: an audited note with the right value and a
# reason, shown beside the original. The received date belongs to the collection and is
# corrected once for all of its tubes.
LABEL_FIELDS = ["received_date", "created_by", "created_datetime"]
COLLECTION_FIELDS = ["received_date"]

# Data file names: <sample ID>_<source>_<assay label>_<platform label> (nomenclature section 3).
ASSAY_LABELS = {"WES": "DNA_WES", "WGS": "DNA_WGS", "RSQ": "bulkRNA", "SCR": "scRNA", "VDJ": "scVDJ",
                "TCR": "bulkTCR", "IPX": "immunopeptidome"}
PLATFORM_LABELS = {"ILM": "Illumina", "ONT": "ONT", "10X": "10XGEX", "MS": "MS"}
TUMOR_SPECIMENS = ["PF", "TU", "LN", "BM"]       # source "tumor"; anything else is "normal"
TCELL_FRACTIONS = ["TTC", "CD4", "CD8"]          # adds "_Tcell" to the source

# ---------------------------------------------------------------------------
# Flask / runtime
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get("LIMS_SECRET_KEY", "change-me-before-deploying")
DATABASE = os.environ.get("LIMS_DATABASE", os.path.join(os.path.dirname(__file__), "instance", "lims.db"))
# A PostgreSQL URL switches the backend (used on Vercel with Supabase); leave unset for SQLite.
# POSTGRES_URL is what the Supabase integration on the Vercel marketplace sets.
DATABASE_URL = os.environ.get("LIMS_DATABASE_URL") or os.environ.get("POSTGRES_URL") or None
# Uploaded files (QC exports, traces, images). Point at a gcsfuse mount on the GCP VM.
# On Vercel the project directory is read-only, so the fallback is the (ephemeral) temp directory;
# set the Supabase Storage variables below for files that persist.
ATTACHMENT_DIR = os.environ.get("LIMS_ATTACHMENT_DIR") or (
    "/tmp/igi-lims-attachments" if os.environ.get("VERCEL") else os.path.join(os.path.dirname(__file__), "instance", "attachments"))
SUPABASE_URL = os.environ.get("LIMS_SUPABASE_URL") or os.environ.get("SUPABASE_URL") or None    # https://<ref>.supabase.co
SUPABASE_SERVICE_KEY = os.environ.get("LIMS_SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or None
STORAGE_BUCKET = os.environ.get("LIMS_STORAGE_BUCKET", "lims-attachments")

# Public demonstration instance: credentials shown on the login page, data rebuilt by
# `flask demo-reset` or the /cron/demo-reset endpoint (Vercel cron with CRON_SECRET).
DEMO_MODE = os.environ.get("LIMS_DEMO_MODE") == "1"
DEMO_PASSWORD = os.environ.get("LIMS_DEMO_PASSWORD", "try-the-lims")
CRON_SECRET = os.environ.get("CRON_SECRET") or None
MAX_CONTENT_LENGTH = 100 * 1024 * 1024
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = bool(os.environ.get("VERCEL"))     # always HTTPS there
SESSION_COOKIE_SAMESITE = "Lax"
PERMANENT_SESSION_LIFETIME = 60 * 60 * 12
