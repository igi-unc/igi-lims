"""Sample service layer: create (root or derived), update, soft delete, lineage queries.

All writes take an open connection and do not commit; the caller commits.
Rule violations are returned, not raised; the caller may retry with force=True
and a reason, which is written to the audit log as a flagged override. Hard
validation errors (unknown participant, bad code) raise ValueError and cannot
be overridden.
"""
import json
from datetime import datetime, date

from flask import current_app, g

from . import ids, rules, audit, attributes

EDITABLE_FIELDS = [
    "parent_id", "created_datetime", "created_by", "sop_code", "biobank_source",
    "quantity", "unit", "freezer", "rack", "box", "position", "status", "notes",
]
LOCATION_FIELDS = ["freezer", "rack", "box", "position"]
FIELD_NAMES = {"received_date": "Received date", "created_by": "Operator", "created_datetime": "Processing date/time"}

# ID segment -> sample column
SEGMENT_COLUMNS = {"project": "project_code", "cohort": "cohort_code", "participant": "participant_id", "unc_id": "unc_id",
                   "received_date": "received_date", "specimen": "specimen_code", "fraction": "fraction_code",
                   "material": "material_code", "aliquot": "aliquot", "operator": "created_by",
                   "processing_date": "processing_date"}
INHERITED_SEGMENTS = ["project", "cohort", "participant", "unc_id", "received_date", "specimen"]   # segments 1-6


def label_fields():
    return list(current_app.config.get("LABEL_FIELDS", []))


def editable_fields():
    """Fields the Edit form may change: everything except what is printed on the label."""
    locked = set(label_fields())
    return [f for f in EDITABLE_FIELDS if f not in locked]


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


def get_collection(conn, collection_id):
    try:
        cid = int(collection_id)
    except (TypeError, ValueError):
        return None
    return conn.execute("SELECT * FROM collection WHERE collection_id=?", (cid,)).fetchone()


def _processing_date(p):
    dt = (p.get("created_datetime") or "").strip()
    if not dt:
        raise ValueError("Processing date/time is required (it is part of the sample ID)")
    try:
        return datetime.fromisoformat(dt).date().isoformat()
    except ValueError:
        raise ValueError("Processing date/time must be a date and time")


def _components_for(conn, p):
    """Return (components with aliquot 1, parent row or None, collection row).
    Segments 1-6 come from the parent tube, or for a first-generation tube from its collection and participant;
    fraction, material, operator and processing date come from this tube."""
    parent = None
    if p.get("parent_id"):
        parent = get_sample(conn, p["parent_id"])
        if parent is None:
            raise ValueError(f"Parent {p['parent_id']} does not exist")
        coll = get_collection(conn, parent["collection_id"])
        comp = {seg: parent[SEGMENT_COLUMNS[seg]] for seg in INHERITED_SEGMENTS}
    else:
        coll = get_collection(conn, p.get("collection_id"))
        if coll is None or coll["deleted_at"]:
            raise ValueError("A first-generation tube needs an existing collection")
        part = conn.execute("SELECT * FROM participant WHERE participant_id=? AND deleted_at IS NULL",
                            (coll["participant_id"],)).fetchone()
        if part is None:
            raise ValueError("The collection's participant does not exist")
        if not part["unc_number"]:
            raise ValueError(f"Participant {part['participant_id']} has no UNC number; add it on the participant record")
        comp = {"project": "IGI", "cohort": part["cohort_code"], "participant": part["participant_id"],
                "unc_id": ids.unc_id(part["unc_number"]), "received_date": coll["received_date"],
                "specimen": coll["specimen_code"]}
    comp["fraction"] = p.get("fraction")
    comp["material"] = p.get("material")
    comp["aliquot"] = 1
    comp["operator"] = p.get("created_by")
    comp["processing_date"] = _processing_date(p)
    for k in ("fraction", "material", "operator"):
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
    return comp, parent, coll


def _violations(conn, parent, coll, comp):
    v = rules.check_derivation(conn, parent, comp) if parent else rules.check_root(conn, comp)
    if comp["processing_date"] < comp["received_date"]:
        v.append(f"Processing date {comp['processing_date']} is before the received date {comp['received_date']}")
    if parent and parent["processing_date"] and comp["processing_date"] < parent["processing_date"]:
        v.append(f"Processing date {comp['processing_date']} is before the parent's ({parent['processing_date']})")
    return v


def preview(conn, payload):
    """Validate and return (prefix, violations) without writing anything."""
    p = _clean(payload)
    comp, parent, coll = _components_for(conn, p)
    return ids.prefix_without_aliquot(comp), _violations(conn, parent, coll, comp)


def create_samples(conn, payload, force=False, reason=None):
    """Create `count` aliquots. Returns (created_ids, violations).
    If violations exist and force is False, nothing is written."""
    p = _clean(payload)
    comp, parent, coll = _components_for(conn, p)
    violations = _violations(conn, parent, coll, comp)
    if violations and not force:
        return [], violations
    if violations:
        reason = "Rule override: " + "; ".join(violations) + (". Justification: " + reason if reason else "")

    status = p.get("status") or "Available"
    if not conn.execute("SELECT 1 FROM code_list WHERE category='status' AND code=? AND active=1", (status,)).fetchone():
        raise ValueError(f"Unknown status {status}")
    attrs = attributes.validate_dict(conn, p.get("attributes") or {}, comp["fraction"], comp["material"])
    attrs = {k: v for k, v in attrs.items() if v is not None}
    created = []
    for _ in range(p["count"]):
        comp["aliquot"] = ids.next_aliquot(conn, comp)
        sid = ids.compose(comp)
        row = {"sample_id": sid}
        for seg, col in SEGMENT_COLUMNS.items():
            row[col] = comp[seg]
        row.update({
            "collection_id": coll["collection_id"],
            "parent_id": parent["sample_id"] if parent else None,
            "root_id": parent["root_id"] if parent else sid,
            "created_datetime": p.get("created_datetime"), "sop_code": p.get("sop_code"),
            "biobank_source": p.get("biobank_source"), "quantity": p.get("quantity"), "unit": p.get("unit"),
            "freezer": p.get("freezer"), "rack": p.get("rack"), "box": p.get("box"), "position": p.get("position"),
            "status": status, "notes": p.get("notes"), "record_created_by": _username(),
        })
        cols = ", ".join(row)
        qs = ", ".join("?" for _ in row)
        conn.execute(f"INSERT INTO sample({cols}) VALUES ({qs})", list(row.values()))
        if attrs:
            attributes.set_values(conn, sid, attrs, log=False)
        # one audit row per tube, metadata included
        audit.log(conn, "sample", sid, "insert", after={**row, **{"attr:" + k: v for k, v in attrs.items()}}, reason=reason)
        created.append(sid)

    if parent and p.get("parent_consumed") and parent["status"] != "Depleted":
        before = dict(parent)
        conn.execute("UPDATE sample SET status='Depleted', record_updated_at=? WHERE sample_id=?",
                     (now_iso(), parent["sample_id"]))
        audit.log(conn, "sample", parent["sample_id"], "update",
                  before={"status": before["status"]}, after={"status": "Depleted"}, reason=reason)
    return created, violations


# ------------------------------------------------------------------ collections

COLLECTION_FIELDS_EDITABLE = ["site_code", "biobank_source", "received_from", "received_by", "time_collected", "time_received",
                              "container_type", "transport_temp", "appearance", "quantity", "unit", "notes"]


def create_collection(conn, data):
    """Register a received specimen (not a tube). Returns the new collection_id."""
    part = conn.execute("SELECT * FROM participant WHERE participant_id=? AND deleted_at IS NULL",
                        (data.get("participant_id"),)).fetchone()
    if part is None:
        raise ValueError("Participant is required and must exist")
    if not part["unc_number"]:
        raise ValueError(f"Participant {part['participant_id']} has no UNC number; add it on the participant record first")
    if not conn.execute("SELECT 1 FROM code_list WHERE category='specimen' AND code=? AND active=1", (data.get("specimen_code"),)).fetchone():
        raise ValueError("Specimen must be an active specimen code")
    try:
        received = date.fromisoformat((data.get("received_date") or "")[:10]).isoformat()
    except ValueError:
        raise ValueError("Received date is required (YYYY-MM-DD)")
    row = {"participant_id": part["participant_id"], "specimen_code": data["specimen_code"], "received_date": received}
    for f in COLLECTION_FIELDS_EDITABLE:
        v = data.get(f)
        row[f] = v.strip() if isinstance(v, str) else v
        if row[f] == "":
            row[f] = None
    if row.get("quantity") is not None:
        try:
            row["quantity"] = float(row["quantity"])
        except (TypeError, ValueError):
            raise ValueError("Quantity must be a number")
    row["site_code"] = row.get("site_code") or part["site_code"]
    row["created_by"] = _username()
    cols = ", ".join(row)
    cur = conn.execute(f"INSERT INTO collection({cols}) VALUES ({', '.join('?' for _ in row)})", list(row.values()))
    cid = cur.lastrowid
    audit.log(conn, "collection", cid, "insert", after=row)
    return cid


def update_collection(conn, collection_id, changes, reason=None):
    cur = get_collection(conn, collection_id)
    if cur is None:
        raise ValueError("Collection not found")
    d = {}
    for f in COLLECTION_FIELDS_EDITABLE:
        if f not in changes:
            continue
        new = changes[f].strip() if isinstance(changes[f], str) else changes[f]
        new = None if new == "" else new
        if f == "quantity" and new is not None:
            try:
                new = float(new)
            except ValueError:
                raise ValueError("Quantity must be a number")
        if cur[f] != new:
            d[f] = (cur[f], new)
    if d:
        conn.execute("UPDATE collection SET " + ", ".join(f"{k}=?" for k in d) + " WHERE collection_id=?",
                     [n for _, n in d.values()] + [cur["collection_id"]])
        audit.log(conn, "collection", cur["collection_id"], "update", before={k: o for k, (o, _) in d.items()},
                  after={k: n for k, (_, n) in d.items()}, reason=reason)
    return d


def collection_label(coll):
    """Short display name: 26SEP29 PF (#12)."""
    return f"{ids.format_yymmmdd(coll['received_date'])} {coll['specimen_code']} (#{coll['collection_id']})"


OCCUPYING_STATUSES = ("Available", "In use")


def location_conflicts(conn, loc, exclude=None):
    """Tubes already sitting in this freezer/rack/box/position (a real slot: no part NA or blank).
    Depleted, shipped and destroyed tubes keep their last location on record but do not occupy the slot."""
    vals = [(loc.get(f) or "").strip() for f in LOCATION_FIELDS]
    if any(v in ("", "NA") for v in vals):
        return []
    q = ("SELECT sample_id, status FROM sample WHERE freezer=? AND rack=? AND box=? AND position=? "
         "AND deleted_at IS NULL AND status IN (%s)" % ",".join("?" for _ in OCCUPYING_STATUSES))
    params = vals + list(OCCUPYING_STATUSES)
    if exclude:
        q += " AND sample_id<>?"; params.append(exclude)
    return conn.execute(q + " ORDER BY sample_id", params).fetchall()


def diff_changes(conn, sample_id, changes):
    """Return {field: (old, new)} for fields that actually change. Raises ValueError on bad input."""
    cur = get_sample(conn, sample_id)
    if cur is None:
        raise ValueError("Sample not found")
    out = {}
    locked = set(label_fields())
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
            if f in locked:
                raise ValueError(f"{FIELD_NAMES.get(f, f)} is printed on the label and cannot be edited; "
                                 "add a correction on the tube page instead")
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
    for col in ("collection_id", "participant_id", "received_date", "specimen_code"):
        if np[col] != cur[col]:
            raise ValueError(f"New parent must come from the same collection ({col} differs)")
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


def _nest(rows):
    nodes = {r["sample_id"]: {"sample": r, "children": []} for r in rows}
    roots = []
    for r in rows:
        pid = r["parent_id"]
        if pid and pid in nodes:
            nodes[pid]["children"].append(nodes[r["sample_id"]])
        else:
            roots.append(nodes[r["sample_id"]])
    return roots


def _collection_node(c, rows):
    info = {k: c[k] for k in ("collection_id", "participant_id", "specimen_code", "received_date", "quantity", "unit",
                              "biobank_source", "received_by", "time_collected", "time_received", "notes")}
    info["label"] = collection_label(c)
    return {"sample": None, "collection": info, "children": _nest(rows)}


def collection_tree(conn, collection_id, include_deleted=False):
    """{collection node -> first-generation tubes -> descendants}."""
    c = get_collection(conn, collection_id)
    q = "SELECT * FROM sample WHERE collection_id=?" + ("" if include_deleted else " AND deleted_at IS NULL") + " ORDER BY sample_id"
    return _collection_node(c, [dict(r) for r in conn.execute(q, (c["collection_id"],))])


def participant_forest(conn, participant_id, include_deleted=False):
    """Participant -> collections (oldest first) -> first-generation tubes -> descendants."""
    colls = conn.execute("SELECT * FROM collection WHERE participant_id=?" + ("" if include_deleted else " AND deleted_at IS NULL")
                         + " ORDER BY received_date, collection_id", (participant_id,)).fetchall()
    q = "SELECT * FROM sample WHERE participant_id=?" + ("" if include_deleted else " AND deleted_at IS NULL") + " ORDER BY sample_id"
    by_coll = {}
    for r in conn.execute(q, (participant_id,)):
        by_coll.setdefault(r["collection_id"], []).append(dict(r))
    return {"sample": None, "participant": participant_id,
            "children": [_collection_node(c, by_coll.get(c["collection_id"], [])) for c in colls]}


def label_rows(sample):
    """Label rows from config LABEL_ROWS (lists of segment names); breaks always fall at a hyphen."""
    sep = current_app.config["ID_SEPARATOR"]
    parts = dict(zip(ids.segment_names(), sample["sample_id"].split(sep)))
    return [sep.join(parts[n] for n in row if n in parts) for row in current_app.config["LABEL_ROWS"]]


def suggested_file_stem(sample, assay_code, platform_code):
    """<sample ID>_<source>_<assay label>_<platform label> (nomenclature v2.1, section 3)."""
    cfg = current_app.config
    source = "tumor" if sample["specimen_code"] in cfg["TUMOR_SPECIMENS"] else "normal"
    if sample["fraction_code"] in cfg["TCELL_FRACTIONS"]:
        source += "_Tcell"
    parts = [sample["sample_id"], source]
    if assay_code:
        parts.append(cfg["ASSAY_LABELS"].get(assay_code, assay_code))
    if platform_code:
        parts.append(cfg["PLATFORM_LABELS"].get(platform_code, platform_code))
    return "_".join(parts)


# ------------------------------------------------------------------ corrections to label fields

def _is_collection_field(field):
    return field in current_app.config.get("COLLECTION_FIELDS", [])


def corrections_for(conn, sample):
    """Corrections that apply to this tube, oldest first: its own, plus those on its collection."""
    return conn.execute("SELECT * FROM sample_correction WHERE sample_id=? OR collection_id=? ORDER BY id",
                        (sample["sample_id"], sample["collection_id"])).fetchall()


def corrections_for_collection(conn, collection_id):
    return conn.execute("SELECT * FROM sample_correction WHERE collection_id=? ORDER BY id", (collection_id,)).fetchall()


def effective_values(corrections):
    """{field: value now believed correct} for the label fields (latest correction wins)."""
    out = {}
    for c in corrections:
        out[c["field"]] = c["corrected_value"]
    return out


def _check_correction_value(conn, field, value):
    if field == "received_date":
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            raise ValueError("The corrected received date must be a date (YYYY-MM-DD)")
    if field == "created_datetime":
        try:
            return datetime.fromisoformat(value).strftime("%Y-%m-%dT%H:%M")
        except ValueError:
            raise ValueError("The corrected processing date must be a date and time")
    if field == "created_by":
        if not conn.execute("SELECT 1 FROM account WHERE initials=? AND active=1 AND role<>'printer'", (value,)).fetchone():
            raise ValueError(f"Operator '{value}' is not an active user")
        return value
    return value


def add_correction(conn, field, value, reason, sample_id=None, collection_id=None):
    """Record the right value for a label field without changing the stored value or any ID.
    Collection-level fields go on the collection (pass either a tube of it or the collection).
    Returns ("collection", id) or ("sample", id)."""
    if field not in label_fields():
        raise ValueError(f"{field} is not a label field; change it with Edit")
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("A reason is required for a correction")
    value = _check_correction_value(conn, field, (value or "").strip())
    s = get_sample(conn, sample_id) if sample_id else None
    if sample_id and s is None:
        raise ValueError("Sample not found")
    if _is_collection_field(field):
        coll = get_collection(conn, collection_id if collection_id is not None else (s["collection_id"] if s else None))
        if coll is None:
            raise ValueError("Collection not found")
        current = effective_values(corrections_for_collection(conn, coll["collection_id"])).get(field, coll[field])
        target = ("collection", coll["collection_id"])
    else:
        if s is None:
            raise ValueError(f"{FIELD_NAMES.get(field, field)} belongs to a tube; correct it on the tube page")
        current = effective_values(conn.execute("SELECT * FROM sample_correction WHERE sample_id=? ORDER BY id",
                                                (s["sample_id"],)).fetchall()).get(field, s[field])
        target = ("sample", s["sample_id"])
    if value == current:
        raise ValueError(f"{FIELD_NAMES.get(field, field)} is already {value}")
    cur = conn.execute("INSERT INTO sample_correction(sample_id, collection_id, field, original_value, corrected_value, reason, recorded_by) "
                       "VALUES (?,?,?,?,?,?,?)",
                       (target[1] if target[0] == "sample" else None, target[1] if target[0] == "collection" else None,
                        field, current, value, reason, _username()))
    audit.log(conn, target[0], target[1], "correct", before={field: current},
              after={field: value, "correction_id": cur.lastrowid, "note": "label value unchanged"}, reason=reason)
    return target


def ids_between(conn, first_id, last_id):
    """The tubes created together with first_id .. last_id: same prefix (segments 1-8), consecutive aliquots."""
    a, b = get_sample(conn, first_id), get_sample(conn, last_id)
    if a is None or b is None:
        return []
    comp = ids.parse(first_id)
    prefix = ids.prefix_without_aliquot(comp)
    return [r["sample_id"] for r in conn.execute(
        "SELECT sample_id FROM sample WHERE sample_id LIKE ? || '%' AND aliquot BETWEEN ? AND ? AND deleted_at IS NULL "
        "ORDER BY aliquot", (prefix, a["aliquot"], b["aliquot"]))]
