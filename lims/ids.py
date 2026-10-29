"""Compose, parse and validate sample IDs according to config.ID_SEGMENTS."""
import re
from datetime import datetime, date

from flask import current_app

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


class IdError(ValueError):
    pass


def _segments():
    return current_app.config["ID_SEGMENTS"]


def _sep():
    return current_app.config["ID_SEPARATOR"]


def segment_names():
    return [name for name, _, _ in _segments()]


def full_pattern():
    """Anchored regex for the whole ID, e.g. for pipeline scripts."""
    parts = [f"({regex})" for _, regex, _ in _segments()]
    sep = _sep()
    sep_re = sep if sep == "-" else re.escape(sep)   # keep the published pattern readable
    return "^" + sep_re.join(parts) + "$"


# ------------------------------------------------------------------ dates

def format_yymmmdd(value):
    """date or ISO string -> 26SEP29 (locale independent, always uppercase)."""
    if isinstance(value, str):
        value = date.fromisoformat(value[:10])
    return f"{value.year % 100:02d}{MONTHS[value.month - 1]}{value.day:02d}"


def parse_yymmmdd(text):
    """26SEP29 -> ISO date string. Raises ValueError for impossible dates (26FEB31)."""
    m = re.fullmatch(r"(\d{2})([A-Z]{3})(\d{2})", text)
    if not m or m.group(2) not in MONTHS:
        raise ValueError(f"'{text}' is not a YYMMMDD date")
    return date(2000 + int(m.group(1)), MONTHS.index(m.group(2)) + 1, int(m.group(3))).isoformat()


def _format_date(kind, value):
    fmt = kind.split(":", 1)[1]
    if fmt == "yymmmdd":
        return format_yymmmdd(value)
    if isinstance(value, str):
        value = date.fromisoformat(value[:10])
    return value.strftime(fmt)


def _parse_date(kind, text):
    fmt = kind.split(":", 1)[1]
    if fmt == "yymmmdd":
        return parse_yymmmdd(text)
    return datetime.strptime(text, fmt).date().isoformat()


# ------------------------------------------------------------------ parse / compose

def parse(sample_id):
    """Return dict of components (dates as ISO strings, aliquot as int). Raises IdError."""
    if not isinstance(sample_id, str):
        raise IdError("ID must be a string")
    expected_len = current_app.config.get("ID_LENGTH")
    if expected_len and len(sample_id) != expected_len:
        raise IdError(f"ID must be exactly {expected_len} characters (got {len(sample_id)})")
    m = re.match(full_pattern(), sample_id)
    if not m:
        raise IdError("ID does not match the required pattern " + full_pattern())
    out = {}
    for (name, _, kind), value in zip(_segments(), m.groups()):
        if kind and kind.startswith("date:"):
            try:
                out[name] = _parse_date(kind, value)
            except ValueError:
                raise IdError(f"{name} '{value}' is not a valid date")
        elif kind == "int":
            out[name] = int(value)
        else:
            out[name] = value
    return out


def _format_segment(name, regex, kind, components):
    if kind == "const":
        return regex
    value = components[name]
    if value is None or value == "":
        raise IdError(f"{name} is required")
    if kind and kind.startswith("date:"):
        return _format_date(kind, value)
    if kind == "int":
        return str(int(value)).zfill(current_app.config["ALIQUOT_WIDTH"])
    return str(value)


def compose(components):
    """Build an ID string from a components dict (dates may be ISO strings or date objects)."""
    sid = _sep().join(_format_segment(n, r, k, components) for n, r, k in _segments())
    parse(sid)  # round-trip validation
    return sid


def check_codes(conn, components):
    """Verify code-list and operator segments. Returns list of problems."""
    problems = []
    for name, _, kind in _segments():
        if kind and kind.startswith("code:"):
            category = kind.split(":", 1)[1]
            row = conn.execute(
                "SELECT active FROM code_list WHERE category=? AND code=?", (category, components[name])
            ).fetchone()
            if row is None:
                problems.append(f"{name} code '{components[name]}' is not in the {category} code list")
            elif not row["active"]:
                problems.append(f"{name} code '{components[name]}' is retired")
        elif kind == "operator":
            if not conn.execute("SELECT 1 FROM account WHERE initials=? AND active=1 AND role<>'printer'", (components[name],)).fetchone():
                problems.append(f"Operator '{components[name]}' is not an active user")
    return problems


def prefix_without_aliquot(components):
    """Every segment to the left of the aliquot, plus the separator: aliquots are unique within this prefix."""
    parts = []
    for name, regex, kind in _segments():
        if kind == "int":
            break
        parts.append(_format_segment(name, regex, kind, components))
    return _sep().join(parts) + _sep()


def next_aliquot(conn, components):
    """Issue the next aliquot for this prefix. Never reuses numbers, including soft-deleted tubes."""
    prefix = prefix_without_aliquot(components)
    row = conn.execute(
        "SELECT MAX(aliquot) AS m FROM sample WHERE sample_id LIKE ? || '%'", (prefix,)
    ).fetchone()
    n = (row["m"] or 0) + 1
    if n > current_app.config["ALIQUOT_MAX"]:
        raise IdError(f"Aliquot counter exhausted for {prefix} (max {current_app.config['ALIQUOT_MAX']})")
    return n


def segment_regex(name):
    for n, regex, _ in _segments():
        if n == name:
            return regex
    return None


def code_segment_regex(category):
    """Regex an ID code of this category must match (cohort, specimen, fraction, material), or None."""
    for _, regex, kind in _segments():
        if kind == f"code:{category}":
            return regex
    return None


# ------------------------------------------------------------------ participants

def participant_pattern():
    r = segment_regex("participant")
    return "^" + r + "$" if r else None


def new_participant_code(conn):
    """Next IGI patient number (P001, P002, ...), above every number ever issued, so none is reused."""
    prefix, digits = current_app.config["PARTICIPANT_PREFIX"], current_app.config["PARTICIPANT_DIGITS"]
    n = 0
    for (pid,) in conn.execute("SELECT participant_id FROM participant"):
        m = re.fullmatch(re.escape(prefix) + r"(\d+)", pid or "")
        if m:
            n = max(n, int(m.group(1)))
    if n + 1 >= 10 ** digits:
        raise IdError("IGI patient numbers are exhausted")
    return f"{prefix}{n + 1:0{digits}d}"


def unc_id(unc_number):
    return "UNC" + str(unc_number)
