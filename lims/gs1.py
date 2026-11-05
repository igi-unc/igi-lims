"""Parse GS1 element strings, as printed in the Data Matrix on reagent and kit boxes.

Accepts the raw scanner output (application identifiers separated by the GS character, optionally after the
']d2' / ']C1' / ']Q3' symbology prefix) and the human-readable form with brackets, '(01)…(17)…(10)…'.
Only the identifiers that matter for a lab bench are named; others are kept by number.
"""
import calendar
import datetime as dt
import re

GS = "\x1d"
# AI -> (name, fixed length or None for variable, max length)
_AIS = {"00": ("sscc", 18, 18), "01": ("gtin", 14, 14), "02": ("content_gtin", 14, 14), "10": ("lot", None, 20),
        "11": ("production_date", 6, 6), "13": ("packaging_date", 6, 6), "15": ("best_before", 6, 6), "17": ("expiry", 6, 6),
        "21": ("serial", None, 20), "22": ("cpv", None, 20), "240": ("product_id", None, 30), "241": ("customer_part", None, 30),
        "30": ("count", None, 8), "37": ("units", None, 8), "90": ("internal", None, 30), "91": ("company_91", None, 90),
        "92": ("company_92", None, 90), "93": ("company_93", None, 90)}
_DATE_AIS = {"11", "13", "15", "17"}


def _date(yymmdd):
    """GS1 date: YYMMDD, DD=00 means the last day of the month; the century follows GS1's sliding window."""
    yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:])
    this = dt.date.today().year
    year = 2000 + yy
    if year - this > 50:
        year -= 100
    elif this - year > 49:
        year += 100
    if not 1 <= mm <= 12:
        return None
    if dd == 0:
        dd = calendar.monthrange(year, mm)[1]
    try:
        return dt.date(year, mm, dd).isoformat()
    except ValueError:
        return None


def parse(text):
    """{'gtin', 'lot', 'expiry' (ISO date), 'serial', ...} for a GS1 string, or None if the text is not GS1."""
    if not text:
        return None
    s = text.strip()
    s = re.sub(r"^\][A-Za-z]\d", "", s)            # symbology identifier
    if s.startswith("("):                           # human-readable: (01)09506000134352(17)270331(10)AB12
        if not re.fullmatch(r"(\(\d{2,4}\)[^()]+)+", s):
            return None
        pairs = [(a, v.strip()) for a, v in re.findall(r"\((\d{2,4})\)([^(]*)", s)]
    else:
        s = s.lstrip(GS)
        if not re.match(r"^(00\d{18}|0[12]\d{14})", s):     # product codes lead with the GTIN (or an SSCC)
            return None
        pairs, i = [], 0
        while i < len(s):
            ai = next((a for a in sorted(_AIS, key=len, reverse=True) if s.startswith(a, i)), None)
            if ai is None:
                return None
            name, fixed, mx = _AIS[ai]
            i += len(ai)
            if fixed:
                v = s[i:i + fixed]
                if len(v) != fixed:
                    return None
                i += fixed
                if i < len(s) and s[i] == GS:
                    i += 1
            else:
                end = s.find(GS, i)
                end = len(s) if end < 0 else end
                v = s[i:end][:mx]
                i = end + 1
            pairs.append((ai, v))
    out = {}
    for ai, v in pairs:
        name = _AIS.get(ai, (f"ai_{ai}",))[0]
        if ai in _DATE_AIS:
            if not re.fullmatch(r"\d{6}", v):
                return None
            out[name] = _date(v)
        else:
            out[name] = v
    if "gtin" in out and not re.fullmatch(r"\d{14}", out["gtin"]):
        return None
    return out or None


def gtin_ok(gtin):
    """GS1 mod-10 check digit."""
    if not re.fullmatch(r"\d{14}", gtin or ""):
        return False
    digits = [int(c) for c in gtin]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(digits[:-1]))
    return (10 - total % 10) % 10 == digits[-1]


def build(gtin, expiry=None, lot=None, serial=None):
    """The raw element string a scanner returns (used for demo test codes)."""
    s = "01" + gtin
    if expiry:
        s += "17" + expiry
    if lot:
        s += "10" + lot + (GS if serial else "")
    if serial:
        s += "21" + serial
    return s
