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
ID_LENGTH = 35          # set to None to skip the fixed-length check
ALIQUOT_WIDTH = 2
ALIQUOT_MAX = 99

# Characters used when the LIMS generates a participant code. I and O are
# excluded to avoid confusion with 1 and 0 on labels.
PARTICIPANT_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ"
PARTICIPANT_LENGTH = 7

# ---------------------------------------------------------------------------
# Two-person agreement
#
# Rule violations on sample creation always need a second user's approval.
# SAMPLE_EDIT_APPROVAL controls edits/deletes of existing sample records:
#   "all"        -> every edit or delete of a sample goes to the approval queue
#   "provenance" -> only parent/ID/delete changes need approval; status,
#                   quantity, location, notes are direct (but audited)
#   "none"       -> edits are direct (audited)
# ---------------------------------------------------------------------------
SAMPLE_EDIT_APPROVAL = "all"
PROVENANCE_FIELDS = {"parent_id", "root_id", "sample_id"}

# ---------------------------------------------------------------------------
# Flask / runtime
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get("LIMS_SECRET_KEY", "change-me-before-deploying")
DATABASE = os.environ.get("LIMS_DATABASE", os.path.join(os.path.dirname(__file__), "instance", "lims.db"))
# Uploaded files (QC exports, traces, images). Point at a gcsfuse mount on the GCP VM.
ATTACHMENT_DIR = os.environ.get("LIMS_ATTACHMENT_DIR", os.path.join(os.path.dirname(__file__), "instance", "attachments"))
MAX_CONTENT_LENGTH = 100 * 1024 * 1024
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
PERMANENT_SESSION_LIFETIME = 60 * 60 * 12
