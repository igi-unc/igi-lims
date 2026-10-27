"""
Site configuration for the IGI LIMS.

Everything about the sample-ID format lives here so that spec changes are a
one-file edit. The database stores the parsed components as columns; if a
segment is added or renamed, add a column in lims/schema.sql and a line in
ID_SEGMENTS, nothing else.
"""
import os

# ---------------------------------------------------------------------------
# Sample ID format
#
# Each segment: (name, regex, kind). `kind` controls validation:
#   "const"     -> regex is a literal
#   "code:<cat>"-> value must be an active code in code_list for that category
#   "date:<fmt>"-> parsed with datetime.strptime(fmt); stored as ISO date
#   "int"       -> integer (the aliquot counter issued by the database)
#   None        -> regex only
#
# Current spec (35 characters):
#   IGI-CC-PPPPPPP-YYMMDD-SS-FFF-MMM-AA
# ---------------------------------------------------------------------------
ID_SEGMENTS = [
    ("project",         r"IGI",                                            "const"),
    ("cohort",          r"[A-Z]{2}",                                       "code:cohort"),
    ("participant",     r"[A-Z]{7}",                                       None),
    ("collection_date", r"\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])",  "date:%y%m%d"),
    ("specimen",        r"[A-Z]{2}",                                       "code:specimen"),
    ("fraction",        r"[A-Z0-9]{3}",                                    "code:fraction"),
    ("material",        r"[A-Z0-9]{3}",                                    "code:material"),
    ("aliquot",         r"(?:0[1-9]|[1-9]\d)",                             "int"),
]
ID_SEPARATOR = "-"

# Fields printed on the tube label. Once a tube exists they cannot be edited, because the
# printed label (and any file named after the ID) would then disagree with the record.
# A mistake is fixed by adding a correction: an audited note with the right value and a
# reason, shown beside the original. Collection-level fields (the collection date) are
# corrected once for the whole collection. When nomenclature v2.1 puts the processing date
# in the ID, add "created_datetime" here.
LABEL_FIELDS = ["collection_date", "created_by"]
COLLECTION_FIELDS = ["collection_date"]   # shared by every tube of a collection; corrected on the root
ID_LENGTH = 35          # set to None to skip the fixed-length check
ALIQUOT_WIDTH = 2
ALIQUOT_MAX = 99

# Characters used when the LIMS generates a participant code. I and O are
# excluded to avoid confusion with 1 and 0 on labels.
PARTICIPANT_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ"
PARTICIPANT_LENGTH = 7

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
