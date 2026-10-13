"""Per-fraction / per-material metadata fields (definitions + values)."""
import json
from datetime import date, datetime

from flask import g

from . import audit


def _username():
    return g.user["username"] if getattr(g, "user", None) else "system"


def definitions_for(conn, fraction=None, material=None, active_only=True):
    """Merged, ordered list of definition rows that apply to a tube with this fraction and material.
    Scope order: all, fraction, material. Duplicate keys keep the first definition."""
    where = ["(scope='all')"]
    params = []
    if fraction:
        where.append("(scope='fraction' AND code=?)"); params.append(fraction)
    if material:
        where.append("(scope='material' AND code=?)"); params.append(material)
    q = ("SELECT * FROM attribute_definition WHERE (" + " OR ".join(where) + ")" +
         (" AND active=1" if active_only else "") +
         " ORDER BY CASE scope WHEN 'all' THEN 2 WHEN 'fraction' THEN 0 ELSE 1 END, sort_order, id")
    seen, out = set(), []
    for r in conn.execute(q, params):
        if r["key"] in seen:
            continue
        seen.add(r["key"])
        out.append(r)
    return out


def options(conn, defn):
    """[(value, label)] for choice/list/bool definitions."""
    t = defn["type"]
    if t == "bool":
        return [("yes", "yes"), ("no", "no")]
    if t == "choice":
        return [(c, c) for c in (defn["choices"] or "").split("|") if c]
    if t == "list":
        return [(r["code"], f"{r['code']} – {r['meaning']}" if r["meaning"] != r["code"] else r["code"]) for r in conn.execute(
            "SELECT code, meaning FROM code_list WHERE category=? AND active=1 ORDER BY sort_order, code", (defn["choices"],))]
    return []


def all_definitions_json(conn):
    """Every active definition, grouped for the create forms' JavaScript."""
    rows = conn.execute("SELECT * FROM attribute_definition WHERE active=1 ORDER BY sort_order, id").fetchall()
    out = {"all": [], "fraction": {}, "material": {}}
    for r in rows:
        d = {k: r[k] for k in ("key", "label", "type", "unit", "choices", "required")}
        d["options"] = options(conn, r)
        if r["scope"] == "all":
            out["all"].append(d)
        else:
            out[r["scope"]].setdefault(r["code"], []).append(d)
    return json.dumps(out)


def coerce(defn, raw, conn=None):
    """Validate a raw string against a definition. Returns normalised string or None. Raises ValueError."""
    v = (raw or "").strip() if isinstance(raw, str) else raw
    if v in ("", None):
        if defn["required"]:
            raise ValueError(f"{defn['label']} is required")
        return None
    t = defn["type"]
    if t == "number":
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"{defn['label']} must be a number")
        return str(int(f)) if f.is_integer() else str(f)
    if t == "bool":
        s = str(v).lower()
        if s in ("1", "true", "yes", "y", "on"):
            return "yes"
        if s in ("0", "false", "no", "n", "off"):
            return "no"
        raise ValueError(f"{defn['label']} must be yes or no")
    if t == "choice":
        choices = (defn["choices"] or "").split("|")
        if str(v) not in choices:
            raise ValueError(f"{defn['label']} must be one of: {', '.join(choices)}")
        return str(v)
    if t == "list":
        if conn is not None and not conn.execute("SELECT 1 FROM code_list WHERE category=? AND code=? AND active=1",
                                                 (defn["choices"], str(v))).fetchone():
            raise ValueError(f"{defn['label']}: '{v}' is not in the {defn['choices']} list (add it under Codes)")
        return str(v)
    if t == "date":
        try:
            date.fromisoformat(str(v))
        except ValueError:
            raise ValueError(f"{defn['label']} must be a date (YYYY-MM-DD)")
        return str(v)
    if t == "datetime":
        try:
            datetime.fromisoformat(str(v))
        except ValueError:
            raise ValueError(f"{defn['label']} must be a date and time")
        return str(v)
    return str(v)


def collect_from_form(conn, form, fraction, material):
    """Read attr_<key> fields from a submitted form for the given fraction/material. Returns {key: value}."""
    out = {}
    for d in definitions_for(conn, fraction, material):
        out[d["key"]] = coerce(d, form.get("attr_" + d["key"], ""), conn)
    return out


def validate_dict(conn, values, fraction, material):
    """Coerce an already-collected {key: value} dict (e.g. from an approval payload)."""
    defs = {d["key"]: d for d in definitions_for(conn, fraction, material, active_only=False)}
    out = {}
    for k, v in (values or {}).items():
        if k in defs:
            out[k] = coerce(defs[k], v, conn)
        elif v not in (None, ""):
            out[k] = str(v)   # unknown key: keep as free text rather than lose data
    return out


def get(conn, sample_id):
    """{key: row} for a tube."""
    return {r["key"]: r for r in conn.execute("SELECT * FROM sample_attribute WHERE sample_id=?", (sample_id,))}


def get_labelled(conn, sample):
    """List of (definition-or-None, value_row) for display, defined fields first in definition order."""
    defs = definitions_for(conn, sample["fraction_code"], sample["material_code"], active_only=False)
    vals = get(conn, sample["sample_id"])
    out, used = [], set()
    for d in defs:
        if d["key"] in vals:
            out.append((d, vals[d["key"]])); used.add(d["key"])
    for k, v in vals.items():
        if k not in used:
            out.append((None, v))
    return out


def for_samples(conn, sample_ids):
    """{sample_id: {key: value}} for many tubes (tree hover)."""
    out = {}
    if not sample_ids:
        return out
    for chunk in (sample_ids[i:i + 500] for i in range(0, len(sample_ids), 500)):
        q = ",".join("?" for _ in chunk)
        for r in conn.execute(f"SELECT sample_id, key, value FROM sample_attribute WHERE sample_id IN ({q})", chunk):
            out.setdefault(r["sample_id"], {})[r["key"]] = r["value"]
    return out


def labels(conn):
    """{key: (label, unit)} across all definitions (first wins)."""
    out = {}
    for r in conn.execute("SELECT key, label, unit FROM attribute_definition ORDER BY id"):
        out.setdefault(r["key"], (r["label"], r["unit"]))
    return out


def set_values(conn, sample_id, values, source_attachment_id=None, approval_id=None):
    """Upsert values. None deletes. Returns {key: (old, new)} of actual changes and writes one audit row."""
    cur = {k: r["value"] for k, r in get(conn, sample_id).items()}
    changes = {}
    for k, v in values.items():
        old = cur.get(k)
        if old == v:
            continue
        changes[k] = (old, v)
        if v is None:
            conn.execute("DELETE FROM sample_attribute WHERE sample_id=? AND key=?", (sample_id, k))
        else:
            conn.execute(
                "INSERT INTO sample_attribute(sample_id, key, value, source_attachment_id, updated_by, updated_at) "
                "VALUES (?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%SZ','now')) "
                "ON CONFLICT(sample_id, key) DO UPDATE SET value=excluded.value, source_attachment_id=excluded.source_attachment_id, "
                "updated_by=excluded.updated_by, updated_at=excluded.updated_at",
                (sample_id, k, v, source_attachment_id, _username()))
    if changes:
        audit.log(conn, "sample", sample_id, "update",
                  before={"attr:" + k: o for k, (o, _) in changes.items()},
                  after={"attr:" + k: n for k, (_, n) in changes.items()}
                  | ({"source_attachment": source_attachment_id} if source_attachment_id else {}),
                  approval_id=approval_id)
    return changes
