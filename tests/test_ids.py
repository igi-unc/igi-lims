import pytest
from lims import ids

DOC_PATTERN = (r"^IGI-[A-Z]{2}-P\d{3}-UNC\d{3}-\d{2}(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(0[1-9]|[12]\d|3[01])"
               r"-[A-Z]{2}-[A-Z0-9]{3}-[A-Z0-9]{3}-(0[1-9]|[1-9]\d)-[A-Z]{2,3}-\d{2}(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
               r"(0[1-9]|[12]\d|3[01])$")


def test_pattern_accepts_what_the_document_accepts(app):
    import re
    with app.app_context():
        for s in ("IGI-MP-P101-UNC316-26SEP29-PF-TUM-HMD-01-MF-26SEP29", "IGI-MP-P101-UNC316-26SEP29-PF-TUM-HMD-01-KEN-26OCT06",
                  "IGI-DG-P007-UNC001-25DEC31-NM-NAP-FFP-99-ABC-26JAN01"):
            assert re.match(ids.full_pattern(), s) and re.match(DOC_PATTERN, s)


def test_parse_and_compose_roundtrip(app):
    with app.app_context():
        sid = "IGI-MP-P101-UNC316-26SEP29-PF-TUM-HMD-01-KEN-26OCT06"
        assert len(sid) == 52
        c = ids.parse(sid)
        assert c == {"project": "IGI", "cohort": "MP", "participant": "P101", "unc_id": "UNC316", "received_date": "2026-09-29",
                     "specimen": "PF", "fraction": "TUM", "material": "HMD", "aliquot": 1, "operator": "KEN",
                     "processing_date": "2026-10-06"}
        assert ids.compose(c) == sid
        assert len(ids.compose({**c, "operator": "MF"})) == 51


@pytest.mark.parametrize("bad", [
    "IGI-MP-P101-UNC316-26SEP29-PF-TUM-HMD-00-MF-26SEP29",      # aliquot 00
    "IGI-MP-P101-UNC316-26SEP32-PF-TUM-HMD-01-MF-26SEP29",      # day 32
    "IGI-MP-P101-UNC316-26FEB30-PF-TUM-HMD-01-MF-26SEP29",      # 30 Feb passes the regex but is not a date
    "IGI-MP-P101-UNC316-260929-PF-TUM-HMD-01-MF-26SEP29",       # numeric date
    "IGI-MP-P101-UNC316-26Sep29-PF-TUM-HMD-01-MF-26SEP29",      # lowercase month
    "IGI-MP-P101-DUK316-26SEP29-PF-TUM-HMD-01-MF-26SEP29",      # non-UNC site
    "IGI-MP-P101-UNC316-26SEP29-NTC-TUM-HMD-01-MF-26SEP29",     # 3-letter specimen
    "IGI-MP-P101-UNC316-26SEP29-PF-TUM-HMD-01-M-26SEP29",       # 1-letter operator
    "IGI-MP-KXRTQVA-260929-PF-TUM-HMD-01",                      # a v2 ID
    "IGI_MP_P101_UNC316_26SEP29_PF_TUM_HMD_01_MF_26SEP29",      # underscores
])
def test_rejects(app, bad):
    with app.app_context():
        with pytest.raises(ids.IdError):
            ids.parse(bad)


def test_prefix_is_segments_one_to_eight(app):
    with app.app_context():
        c = ids.parse("IGI-MP-P101-UNC316-26SEP29-PF-TUM-SNF-03-MF-26OCT16")
        assert ids.prefix_without_aliquot(c) == "IGI-MP-P101-UNC316-26SEP29-PF-TUM-SNF-"


def test_dates_are_locale_independent(app):
    with app.app_context():
        assert ids.format_yymmmdd("2026-09-29") == "26SEP29" and ids.parse_yymmmdd("26DEC01") == "2026-12-01"


def test_participant_numbers_are_sequential_and_never_reused(app):
    from lims.db import get_db
    with app.app_context():
        conn = get_db()
        assert ids.new_participant_code(conn) == "P102"          # P101 exists in the fixture
        conn.execute("INSERT INTO participant(participant_id, cohort_code, unc_number, deleted_at) VALUES ('P150','MP','999','x')")
        assert ids.new_participant_code(conn) == "P151"          # deleted numbers still count
