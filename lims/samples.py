"""Sample service layer: create (root or derived), update, soft delete, lineage queries.

All writes take an open connection and do not commit; the caller commits.
Rule violations are returned, not raised; the caller may retry with force=True
and a reason, which is written to the audit log as a flagged override. Hard
validation errors (unknown participant, bad code) raise ValueError and cannot
be overridden.
"""
import json
from datetime import datetime

from flask import current_app, g

from . import ids, rules, audit, attributes

EDITABLE_FIELDS = [
    "parent_id", "created_datetime", "created_by", "sop_code", "biobank_source",
    "quantity", "unit", "freezer", "rack", "box", "position", "status", "notes",
]
LOCATION_FIELDS = ["freezer", "rack", "box", "position"]


def now_iso():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def get_sample(conn, sample_id, include_deleted=True):
    q = "SELECT * FROM sample WHERE sample_id=?"
    if not include_deleted:
        q += " AND deleted_at IS NULL"
    return conn.execute(q, (sample_id,)).fetchone()


def _username():
    return g.user["username"] if getattr(g, "user", None) else "system"


def _clean(payload):
    """Normalise form/JSON values: blanks -> None, quantity -> float, count -> int."""
    p = {k: (v.strip() if isinstance(v, str) else v) for k, v in payload.items()}
    if isinstance(p.get("attributes"), dict):
        p["attributes"] = {k: (v.strip() if isinstance(v, str) else v) for k, v in p["attributes"].items()}
    for k, v in list(p.items()):
        if v == "":
            p[k] = None
    if p.get("quantity") is not None:
        try:
            p["quantity"] = float(p["quantity"])
        except (TypeError, ValueError):
            raise ValueError("Quantity must be a number")
    p["count"] = int(p.get("count") or 1)
    if not 1 <= p["count"] <= current_app.config["ALIQUOT_MAX"]:
        raise ValueError("Count must be between 1 and %d" % current_app.config["ALIQUOT_MAX"])
    return p


def _components_for(conn, p):
    """Return (parsed components without aliquot, parent_row_or_None)."""
    parent = None
    if p.get("parent_id"):
        parent = get_sample(conn, p["parent_id"])
        if parent is None:
            raise ValueError(f"Parent {p['parent_id']} does not exist")
        comp = {
            "cohort": parent["cohort_code"],
            "participant": parent["participant_id"],
            "collection_date": parent["collection_date"],
            "specimen": parent["specimen_code"],
        }
    else:
        part = conn.execute("SELECT * FROM participant WHERE participant_id=? AND deleted_at IS NULL",
                            (p.get("participant"),)).fetchone()
        if part is None:
            raise ValueError("Participant is required and must exist")
        if not p.get("collection_date"):
            raise ValueError("Collection date is required")
        comp = {
            "cohort": part["cohort_code"],
            "participant": part["participant_id"],
            "collection_date": p["collection_date"],
            "specimen": p.get("specimen"),
        }
    comp["fraction"] = p.get("fraction")
    comp["material"] = p.get("material")
    comp["aliquot"] = 1
    for k in ("specimen", "fraction", "material"):
        if not comp[k]:
            raise ValueError(f"{k} is required")
    try:
        sid = ids.compose(comp)
        comp = ids.parse(sid)
    except (ids.IdError, ValueError) as e:
        raise ValueError(str(e))
    problems = ids.check_codes(conn, comp)
    if problems:
        raise ValueError("; ".join(problems))
    return comp, parent


def preview(conn, payload):
    """Validate and return (prefix, violations) without writing anything."""
    p = _clean(payload)
    comp, parent = _components_for(conn, p)
    violations = rules.check_derivation(conn, parent, comp) if parent else rules.check_root(conn, comp)
    return ids.prefix_without_aliquot(comp), violations


def create_samples(conn, payload, force=False, reason=None):
    """Create `count` aliquots. Returns (created_ids, violations).
    If violations exist and force is False, nothing is written."""
    p = _clean(payload)
    comp, parent = _components_for(conn, p)
    violations = rules.check_derivation(conn, parent, comp) if parent else rules.check_root(conn, comp)
    if violations and not force:
        return [], violations
    if violations:
        reason = "Rule override: " + "; ".join(violations) + (". Justification: " + reason if reason else "")

    status = p.get("status") or "Available"
    if not conn.execute("SELECT 1 FROM code_list WHERE category='status' AND code=? AND active=1", (status,)).fetchone():
        raise ValueError(f"Unknown status {status}")
    created = []
    for _ in range(p["count"]):
        comp["aliquot"] = ids.next_aliquot(conn, comp)
        sid = ids.compose(comp)
        root_id = parent["root_id"] if parent else sid
        row = {
            "sample_id": sid,
            "project_code": comp["project"], "cohort_code": comp["cohort"],
            "participant_id": comp["participant"], "collection_date": comp["collection_date"],
            "specimen_code": comp["specimen"], "fraction_code": comp["fraction"],
            "material_code": comp["material"], "aliquot": comp["aliquot"],
            "parent_id": parent["sample_id"] if parent else None, "root_id": root_id,
            "created_datetime": p.get("created_datetime"), "created_by": p.get("created_by"),
            "sop_code": p.get("sop_code"), "biobank_source": p.get("biobank_source"),
            "quantity": p.get("quantity"), "unit": p.get("unit"),
            "freezer": p.get("freezer"), "rack": p.get("rack"), "box": p.get("box"), "position": p.get("position"),
            "status": status, "notes": p.get("notes"),
            "record_created_by": _username(),
        }
        cols = ", ".join(row)
        qs = ", ".join("?" for _ in row)
        conn.execute(f"INSERT INTO sample({cols}) VALUES ({qs})", list(row.values()))
        audit.log(conn, "sample", sid, "insert", after=row, reason=reason)
        created.append(sid)
        if p.get("attributes"):
            attributes.set_values(conn, sid, attributes.validate_dict(conn, p["attributes"], comp["fraction"], comp["material"]),
                                  reason=reason, action="insert")

    if parent and p.get("parent_consumed") and parent["status"] != "Depleted":
        before = dict(parent)
        conn.execute("UPDATE sample SET status='Depleted', record_updated_at=? WHERE sample_id=?",
                     (now_iso(), parent["sample_id"]))
        audit.log(conn, "sample", parent["sample_id"], "update",
                  before={"status": before["status"]}, after={"status": "Depleted"}, reason=reason)
    return created, violations


def diff_changes(conn, sample_id, changes):
    """Return {field: (old, new)} for fields that actually change. Raises ValueError on bad input."""
    cur = get_sample(conn, sample_id)
    if cur is None:
        raise ValueError("Sample not found")
    out = {}
    for f in EDITABLE_FIELDS:
        if f not in changes:
            continue
        new = changes[f]
        if isinstance(new, str):
            new = new.strip() or None
        if f == "quantity" and new is not None:
            try:
                new = float(new)
            except ValueError:
                raise ValueError("Quantity must be a number")
        old = cur[f]
        if old != new:
            out[f] = (old, new)
    if isinstance(changes.get("attributes"), dict):
        new_attrs = attributes.validate_dict(conn, changes["attributes"], cur["fraction_code"], cur["material_code"])
        cur_attrs = {k: r["value"] for k, r in attributes.get(conn, sample_id).items()}
        for k, v in new_attrs.items():
            if cur_attrs.get(k) != v:
                out["attr:" + k] = (cur_attrs.get(k), v)
    if "parent_id" in out:
        _validate_new_parent(conn, cur, out["parent_id"][1])
    if "status" in out and out["status"][1] is not None:
        if not conn.execute("SELECT 1 FROM code_list WHERE category='status' AND code=?", (out["status"][1],)).fetchone():
            raise ValueError("Unknown status")
    return out


def _validate_new_parent(conn, cur, new_parent_id):
    if new_parent_id is None:
        if cur["parent_id"] is not None:
            raise ValueError("Cannot detach a derived sample from its parent; a derived tube must have a parent")
        return
    if new_parent_id == cur["sample_id"]:
        raise ValueError("A sample cannot be its own parent")
    np = get_sample(conn, new_parent_id)
    if np is None:
        raise ValueError("New parent does not exist")
    for col in ("participant_id", "collection_date", "specimen_code"):
        if np[col] != cur[col]:
            raise ValueError(f"New parent must share {col} with this sample")
    # cycle check: the new parent must not be a descendant of this sample
    for d in descendants(conn, cur["sample_id"]):
        if d["sample_id"] == new_parent_id:
            raise ValueError("New parent is a descendant of this sample (would create a cycle)")


def update_sample(conn, sample_id, changes, reason=None):
    d = diff_changes(conn, sample_id, changes)
    if not d:
        return {}
    cur = get_sample(conn, sample_id)
    attr_changes = {f[5:]: new for f, (_, new) in d.items() if f.startswith("attr:")}
    sets = {f: new for f, (_, new) in d.items() if not f.startswith("attr:")}
    if attr_changes:
        attributes.set_values(conn, sample_id, attr_changes, reason=reason)
    if not sets:
        return d
    if "parent_id" in sets:
        new_parent = get_sample(conn, sets["parent_id"]) if sets["parent_id"] else None
        new_root = new_parent["root_id"] if new_parent else sample_id
        if new_root != cur["root_id"]:
            sets["root_id"] = new_root
            for desc in descendants(conn, sample_id):
                conn.execute("UPDATE sample SET root_id=? WHERE sample_id=?", (new_root, desc["sample_id"]))
    sets["record_updated_at"] = now_iso()
    assign = ", ".join(f"{k}=?" for k in sets)
    conn.execute(f"UPDATE sample SET {assign} WHERE sample_id=?", list(sets.values()) + [sample_id])
    audit.log(conn, "sample", sample_id, "update",   # attribute changes were audited by set_values
              before={f: old for f, (old, _) in d.items() if f in sets}, after={f: new for f, (_, new) in d.items() if f in sets},
              reason=reason)
    return d


def delete_sample(conn, sample_id, reason=None):
    cur = get_sample(conn, sample_id)
    if cur is None or cur["deleted_at"]:
        raise ValueError("Sample not found or already deleted")
    kids = conn.execute("SELECT sample_id FROM sample WHERE parent_id=? AND deleted_at IS NULL", (sample_id,)).fetchall()
    if kids:
        raise ValueError("Cannot delete a sample that has active children: " + ", ".join(k["sample_id"] for k in kids))
    conn.execute("UPDATE sample SET deleted_at=?, record_updated_at=? WHERE sample_id=?", (now_iso(), now_iso(), sample_id))
    audit.log(conn, "sample", sample_id, "delete", before=cur, reason=reason)


def restore_sample(conn, sample_id, reason=None):
    cur = get_sample(conn, sample_id)
    if cur is None or not cur["deleted_at"]:
        raise ValueError("Sample not found or not deleted")
    if cur["parent_id"]:
        par = get_sample(conn, cur["parent_id"])
        if par["deleted_at"]:
            raise ValueError("Restore the parent first")
    conn.execute("UPDATE sample SET deleted_at=NULL, record_updated_at=? WHERE sample_id=?", (now_iso(), sample_id))
    audit.log(conn, "sample", sample_id, "restore", after=cur, reason=reason)


# ---------------------------------------------------------------- lineage

def ancestors(conn, sample_id):
    """Root-first list of ancestor rows (excluding the sample itself)."""
    chain = []
    cur = get_sample(conn, sample_id)
    seen = set()
    while cur is not None and cur["parent_id"] and cur["parent_id"] not in seen:
        seen.add(cur["parent_id"])
        cur = get_sample(conn, cur["parent_id"])
        chain.append(cur)
    chain.reverse()
    return chain


def descendants(conn, sample_id):
    """All descendants (any depth), as rows, breadth-first."""
    out, frontier = [], [sample_id]
    while frontier:
        q = ",".join("?" for _ in frontier)
        rows = conn.execute(f"SELECT * FROM sample WHERE parent_id IN ({q}) ORDER BY sample_id", frontier).fetchall()
        out.extend(rows)
        frontier = [r["sample_id"] for r in rows]
    return out


def tree(conn, root_id, include_deleted=False):
    """Nested dict {sample: row-dict, children: [...]} for the whole tree under root_id."""
    q = "SELECT * FROM sample WHERE root_id=?" + ("" if include_deleted else " AND deleted_at IS NULL") + " ORDER BY sample_id"
    rows = [dict(r) for r in conn.execute(q, (root_id,))]
    nodes = {r["sample_id"]: {"sample": r, "children": []} for r in rows}
    roots = []
    for r in rows:
        pid = r["parent_id"]
        if pid and pid in nodes:
            nodes[pid]["children"].append(nodes[r["sample_id"]])
        else:
            roots.append(nodes[r["sample_id"]])
    return roots[0] if len(roots) == 1 else {"sample": None, "children": roots}


def participant_forest(conn, participant_id, include_deleted=False):
    """One virtual root per participant; children are the collections' root tubes, then their trees."""
    q = "SELECT * FROM sample WHERE participant_id=?" + ("" if include_deleted else " AND deleted_at IS NULL") + " ORDER BY sample_id"
    rows = [dict(r) for r in conn.execute(q, (participant_id,))]
    nodes = {r["sample_id"]: {"sample": r, "children": []} for r in rows}
    roots = []
    for r in rows:
        pid = r["parent_id"]
        if pid and pid in nodes:
            nodes[pid]["children"].append(nodes[r["sample_id"]])
        else:
            roots.append(nodes[r["sample_id"]])
    return {"sample": None, "participant": participant_id, "children": roots}


def label_rows(sample):
    """Suggested 3-row label layout (spec section 4); breaks always fall at a hyphen."""
    sep = current_app.config["ID_SEPARATOR"]
    parts = sample["sample_id"].split(sep)
    n = len(parts)
    # project, cohort, participant | date, specimen, fraction | material, aliquot
    return [sep.join(parts[:3]), sep.join(parts[3:n - 2]), sep.join(parts[n - 2:])]
