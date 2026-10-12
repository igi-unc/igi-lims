import pytest
from lims import ids


def test_pattern_matches_spec(app):
    with app.app_context():
        assert ids.full_pattern() == (
            r"^(IGI)-([A-Z]{2})-([A-Z]{7})-(\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))"
            r"-([A-Z]{2})-([A-Z0-9]{3})-([A-Z0-9]{3})-((?:0[1-9]|[1-9]\d))$")


def test_parse_and_compose_roundtrip(app):
    with app.app_context():
        sid = "IGI-MP-KXRTQVA-260929-PF-TUM-HMD-01"
        assert len(sid) == 35
        c = ids.parse(sid)
        assert c == {"project": "IGI", "cohort": "MP", "participant": "KXRTQVA", "collection_date": "2026-09-29",
                     "specimen": "PF", "fraction": "TUM", "material": "HMD", "aliquot": 1}
        assert ids.compose(c) == sid


@pytest.mark.parametrize("bad", [
    "IGI-MP-KXRTQVA-260929-PF-TUM-HMD-00",      # aliquot 00
    "IGI-MP-KXRTQVA-260931-PF-TUM-HMD-01",      # invalid date
    "igi-MP-KXRTQVA-260929-PF-TUM-HMD-01",      # lowercase
    "IGI-MP-KXRTQVA-260929-PF-TUM-HMD-01-MF",   # too long
    "IGI_MP_KXRTQVA_260929_PF_TUM_HMD_01",      # underscores
    "IGI-MP-P101-260929-PF-TUM-HMD-01",         # short participant
])
def test_rejects(app, bad):
    with app.app_context():
        with pytest.raises(ids.IdError):
            ids.parse(bad)


def test_prefix(app):
    with app.app_context():
        c = ids.parse("IGI-MP-KXRTQVA-260929-PF-TUM-HMD-07")
        assert ids.prefix_without_aliquot(c) == "IGI-MP-KXRTQVA-260929-PF-TUM-HMD-"
