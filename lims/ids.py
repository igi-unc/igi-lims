"""Compose, parse and validate sample IDs according to config.ID_SEGMENTS."""
import re
import secrets
from datetime import datetime, date

from flask import current_app


class IdError(ValueError):
    pass


def _segments():
    return current_app.config["ID_SEGMENTS"]


def _sep():
    return current_app.config["ID_SEPARATOR"]


def full_pattern():
    """Anchored regex for the whole ID, e.g. for pipeline scripts."""
    parts = [f"({regex})" for _, regex, _ in _segments()]
    sep = _sep()
    sep_re = sep if sep == "-" else re.escape(sep)   # keep the published pattern readable
    return "^" + sep_re.join(parts) + "$"


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
            fmt = kind.split(":", 1)[1]
            try:
                out[name] = datetime.strptime(value, fmt).date().isoformat()
            except ValueError:
                raise IdError(f"{name} '{value}' is not a valid date")
        elif kind == "int":
            out[name] = int(value)
        else:
            out[name] = value
    return out


def check_codes(conn, components):
    """Verify code-list segments against active codes. Returns list of problems."""
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
    return problems


def compose(components):
    """Build an ID string from a components dict (dates may be ISO strings or date objects)."""
    parts = []
    for name, regex, kind in _segments():
        if kind == "const":
            parts.append(regex)
            continue
        value = components[name]
        if kind and kind.startswith("date:"):
            fmt = kind.split(":", 1)[1]
            if isinstance(value, str):
                value = date.fromisoformat(value)
            value = value.strftime(fmt)
        elif kind == "int":
            value = str(int(value)).zfill(current_app.config["ALIQUOT_WIDTH"])
        parts.append(str(value))
    sid = _sep().join(parts)
    parse(sid)  # round-trip validation
    return sid


def prefix_without_aliquot(components):
    """Everything to the left of the aliquot, used to issue the next aliquot number."""
    c = dict(components)
    c["aliquot"] = 1
    sid = compose(c)
    return sid.rsplit(_sep(), 1)[0] + _sep()


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


def new_participant_code(conn):
    alphabet = current_app.config["PARTICIPANT_ALPHABET"]
    length = current_app.config["PARTICIPANT_LENGTH"]
    for _ in range(100):
        code = "".join(secrets.choice(alphabet) for _ in range(length))
        if not conn.execute("SELECT 1 FROM participant WHERE participant_id=?", (code,)).fetchone():
            return code
    raise IdError("Could not generate a unique participant code")


def participant_pattern():
    for name, regex, _ in _segments():
        if name == "participant":
            return "^" + regex + "$"
    return None
