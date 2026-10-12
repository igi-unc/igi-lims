import json
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort, current_app

from ..auth import login_required, writer_required
from ..db import get_db
from .. import samples as svc, approvals, audit, ids
from .helpers import codes, code_meaning_map

bp = Blueprint("samples", __name__, url_prefix="/samples")

FORM_FIELDS = ["fraction", "material", "count", "created_datetime", "created_by", "sop_code", "biobank_source",
               "quantity", "unit", "freezer", "rack", "box", "position", "status", "notes"]


def _form_payload(extra=()):
    p = {f: request.form.get(f, "") for f in FORM_FIELDS + list(extra)}
    p["parent_consumed"] = bool(request.form.get("parent_consumed"))
    return p


def _needs_approval(diff):
    mode = current_app.config["SAMPLE_EDIT_APPROVAL"]
    if mode == "all":
        return True
    if mode == "provenance":
        return bool(set(diff) & current_app.config["PROVENANCE_FIELDS"])
    return False


@bp.route("/")
@login_required
def list_samples():
    conn = get_db()
    f = {k: (request.args.get(k) or "").strip() for k in
         ("q", "participant", "cohort", "specimen", "fraction", "material", "status", "root")}
    show_deleted = request.args.get("deleted") == "1"
    where, params = [], []
    if not show_deleted:
        where.append("deleted_at IS NULL")
    if f["q"]:
        where.append("sample_id LIKE ?")
        params.append(f"%{f['q'].upper()}%")
    for key, col in (("participant", "participant_id"), ("cohort", "cohort_code"), ("specimen", "specimen_code"),
                     ("fraction", "fraction_code"), ("material", "material_code"), ("status", "status"),
                     ("root", "root_id")):
        if f[key]:
            where.append(f"{col}=?")
            params.append(f[key])
    sql = "SELECT * FROM sample" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY sample_id"
    page = max(int(request.args.get("page", 1)), 1)
    per = 100
    rows = conn.execute(sql + f" LIMIT {per + 1} OFFSET {(page - 1) * per}", params).fetchall()
    has_more = len(rows) > per
    return render_template("samples/list.html", rows=rows[:per], f=f, page=page, has_more=has_more,
                           show_deleted=show_deleted, cohorts=codes("cohort"), specimens=codes("specimen"),
                           fractions=codes("fraction"), materials=codes("material"), statuses=codes("status"))


@bp.route("/<sample_id>")
@login_required
def detail(sample_id):
    conn = get_db()
    s = svc.get_sample(conn, sample_id)
    if s is None:
        abort(404)
    children = conn.execute("SELECT * FROM sample WHERE parent_id=? ORDER BY sample_id", (sample_id,)).fetchall()
    custody = conn.execute("SELECT * FROM custody_event WHERE sample_id=? ORDER BY event_datetime, id", (sample_id,)).fetchall()
    files = conn.execute("SELECT * FROM data_file WHERE sample_id=? AND deleted_at IS NULL ORDER BY uri", (sample_id,)).fetchall()
    history = conn.execute("SELECT * FROM audit_log WHERE table_name='sample' AND record_id=? ORDER BY id DESC", (sample_id,)).fetchall()
    pending = conn.execute("SELECT * FROM approval_request WHERE target_id=? AND status='pending'", (sample_id,)).fetchall()
    participant = conn.execute("SELECT * FROM participant WHERE participant_id=?", (s["participant_id"],)).fetchone()
    return render_template("samples/detail.html", s=s, children=children, ancestors=svc.ancestors(conn, sample_id),
                           custody=custody, files=files, history=history, pending=pending, participant=participant,
                           label=svc.label_rows(s), meanings=code_meaning_map(), assays=codes("assay"),
                           json=json)


@bp.route("/tree/<root_id>")
@login_required
def tree(root_id):
    conn = get_db()
    root = svc.get_sample(conn, root_id)
    if root is None:
        abort(404)
    t = svc.tree(conn, root["root_id"], include_deleted=request.args.get("deleted") == "1")
    return render_template("samples/tree.html", root=root, tree_json=json.dumps(t, default=str),
                           highlight=request.args.get("highlight", ""), meanings=code_meaning_map())


# ------------------------------------------------------------------ create

def _render_form(template, payload, violations=None, prefix=None, **ctx):
    return render_template(template, p=payload, violations=violations or [], prefix=prefix,
                           fractions=codes("fraction"), materials=codes("material"), statuses=codes("status"),
                           units=codes("unit"), biobanks=codes("biobank_source"), specimens=codes("specimen"),
                           sops=codes("sop"), **ctx)


def _handle_create(payload, template, **ctx):
    """Shared POST logic for root and derived creation."""
    conn = get_db()
    action = request.form.get("action", "create")
    try:
        if action == "request_override":
            just = request.form.get("justification", "").strip()
            if not just:
                flash("A justification is required to request an override", "error")
                prefix, violations = svc.preview(conn, payload)
                return _render_form(template, payload, violations, prefix, **ctx)
            prefix, violations = svc.preview(conn, payload)
            rid = approvals.request(conn, "create_sample", payload, just, violations=violations)
            conn.commit()
            flash(f"Override request #{rid} submitted; another user must approve it", "ok")
            return redirect(url_for("approvals.detail", request_id=rid))
        created, violations = svc.create_samples(conn, payload)
        if violations:
            prefix, _ = svc.preview(conn, payload)
            return _render_form(template, payload, violations, prefix, **ctx)
        conn.commit()
        flash(f"Created {len(created)} tube(s): {created[0]}" + (f" … {created[-1]}" if len(created) > 1 else ""), "ok")
        return redirect(url_for("samples.detail", sample_id=created[0]))
    except ValueError as e:
        conn.rollback()
        flash(str(e), "error")
        return _render_form(template, payload, **ctx)


@bp.route("/new", methods=("GET", "POST"))
@writer_required
def new_root():
    conn = get_db()
    participants = conn.execute("SELECT * FROM participant WHERE deleted_at IS NULL ORDER BY participant_id").fetchall()
    if request.method == "POST":
        payload = _form_payload(extra=("participant", "collection_date", "specimen"))
        return _handle_create(payload, "samples/new_root.html", participants=participants)
    payload = {"fraction": "BLK", "material": "NAT", "count": 1, "status": "Available",
               "created_by": g.user["initials"], "participant": request.args.get("participant", "")}
    return _render_form("samples/new_root.html", payload, participants=participants)


@bp.route("/<sample_id>/derive", methods=("GET", "POST"))
@writer_required
def derive(sample_id):
    conn = get_db()
    parent = svc.get_sample(conn, sample_id)
    if parent is None:
        abort(404)
    if request.method == "POST":
        payload = _form_payload()
        payload["parent_id"] = sample_id
        return _handle_create(payload, "samples/derive.html", parent=parent)
    allowed_fr = {r["to_code"] for r in conn.execute(
        "SELECT to_code FROM derivation_rule WHERE rule_type='fraction_transition' AND from_code=?", (parent["fraction_code"],))}
    allowed_fr.add(parent["fraction_code"])
    allowed_mat = {r["to_code"] for r in conn.execute(
        "SELECT to_code FROM derivation_rule WHERE rule_type='material_transition' AND from_code=?", (parent["material_code"],))}
    payload = {"fraction": parent["fraction_code"], "material": "", "count": 1, "status": "Available",
               "created_by": g.user["initials"], "biobank_source": parent["biobank_source"]}
    return _render_form("samples/derive.html", payload, parent=parent, allowed_fr=allowed_fr, allowed_mat=allowed_mat)


# ------------------------------------------------------------------ edit / delete

@bp.route("/<sample_id>/edit", methods=("GET", "POST"))
@writer_required
def edit(sample_id):
    conn = get_db()
    s = svc.get_sample(conn, sample_id)
    if s is None:
        abort(404)
    if request.method == "POST":
        changes = {f: request.form.get(f, "") for f in svc.EDITABLE_FIELDS}
        try:
            diff = svc.diff_changes(conn, sample_id, changes)
            if not diff:
                flash("No changes", "ok")
                return redirect(url_for("samples.detail", sample_id=sample_id))
            if _needs_approval(diff):
                just = request.form.get("justification", "").strip()
                if not just:
                    flash("Edits to sample records need a justification and a second user's approval", "error")
                    return render_template("samples/edit.html", s=s, p=changes, statuses=codes("status"),
                                           units=codes("unit"), biobanks=codes("biobank_source"), sops=codes("sop"),
                                           needs_approval=True)
                rid = approvals.request(conn, "update_sample", {f: n for f, (_, n) in diff.items()}, just,
                                        target_id=sample_id, violations={f: [o, n] for f, (o, n) in diff.items()})
                conn.commit()
                flash(f"Change request #{rid} submitted for approval", "ok")
                return redirect(url_for("approvals.detail", request_id=rid))
            svc.update_sample(conn, sample_id, changes)
            conn.commit()
            flash("Sample updated", "ok")
            return redirect(url_for("samples.detail", sample_id=sample_id))
        except ValueError as e:
            conn.rollback()
            flash(str(e), "error")
            return render_template("samples/edit.html", s=s, p=changes, statuses=codes("status"), units=codes("unit"),
                                   biobanks=codes("biobank_source"), sops=codes("sop"),
                                   needs_approval=current_app.config["SAMPLE_EDIT_APPROVAL"] != "none")
    return render_template("samples/edit.html", s=s, p=dict(s), statuses=codes("status"), units=codes("unit"),
                           biobanks=codes("biobank_source"), sops=codes("sop"),
                           needs_approval=current_app.config["SAMPLE_EDIT_APPROVAL"] != "none")


@bp.route("/<sample_id>/delete", methods=("POST",))
@writer_required
def delete(sample_id):
    conn = get_db()
    s = svc.get_sample(conn, sample_id)
    if s is None:
        abort(404)
    action = "restore_sample" if s["deleted_at"] else "delete_sample"
    just = request.form.get("justification", "").strip()
    try:
        if current_app.config["SAMPLE_EDIT_APPROVAL"] == "none":
            (svc.restore_sample if s["deleted_at"] else svc.delete_sample)(conn, sample_id)
            conn.commit()
            flash("Done", "ok")
        else:
            if not just:
                flash("A justification is required", "error")
                return redirect(url_for("samples.detail", sample_id=sample_id))
            # fail early on things that approval cannot fix
            if action == "delete_sample" and conn.execute(
                    "SELECT 1 FROM sample WHERE parent_id=? AND deleted_at IS NULL", (sample_id,)).fetchone():
                raise ValueError("Cannot delete a sample with active children; delete the children first")
            rid = approvals.request(conn, action, {}, just, target_id=sample_id)
            conn.commit()
            flash(f"{action.replace('_', ' ').title()} request #{rid} submitted for approval", "ok")
    except ValueError as e:
        conn.rollback()
        flash(str(e), "error")
    return redirect(url_for("samples.detail", sample_id=sample_id))


# ------------------------------------------------------------------ custody + files

@bp.route("/<sample_id>/custody", methods=("POST",))
@writer_required
def add_custody(sample_id):
    conn = get_db()
    if svc.get_sample(conn, sample_id) is None:
        abort(404)
    f = {k: request.form.get(k, "").strip() or None for k in
         ("event_datetime", "from_party", "to_party", "purpose", "condition_on_receipt", "initials", "notes")}
    if not (f["event_datetime"] and f["from_party"] and f["to_party"]):
        flash("Date/time, from and to are required", "error")
        return redirect(url_for("samples.detail", sample_id=sample_id))
    cur = conn.execute(
        "INSERT INTO custody_event(sample_id, event_datetime, from_party, to_party, purpose, condition_on_receipt, "
        "initials, notes, recorded_by) VALUES (?,?,?,?,?,?,?,?,?)",
        (sample_id, f["event_datetime"], f["from_party"], f["to_party"], f["purpose"], f["condition_on_receipt"],
         f["initials"] or g.user["initials"], f["notes"], g.user["username"]))
    audit.log(conn, "custody_event", cur.lastrowid, "insert", after={"sample_id": sample_id, **f})
    new_status = request.form.get("set_status")
    if new_status:
        svc.update_sample(conn, sample_id, {"status": new_status})
    conn.commit()
    flash("Custody event recorded", "ok")
    return redirect(url_for("samples.detail", sample_id=sample_id))


@bp.route("/<sample_id>/files", methods=("POST",))
@writer_required
def add_file(sample_id):
    conn = get_db()
    if svc.get_sample(conn, sample_id) is None:
        abort(404)
    f = {k: request.form.get(k, "").strip() or None for k in
         ("uri", "assay_code", "run_id", "checksum_md5", "pipeline", "pipeline_version", "notes")}
    if not f["uri"]:
        flash("A file URI is required", "error")
        return redirect(url_for("samples.detail", sample_id=sample_id))
    base = f["uri"].rsplit("/", 1)[-1]
    if not base.startswith(sample_id):
        flash(f"Warning: file name does not start with the sample ID ({base})", "error")
    try:
        cur = conn.execute(
            "INSERT INTO data_file(sample_id, uri, assay_code, run_id, checksum_md5, pipeline, pipeline_version, notes, recorded_by) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (sample_id, f["uri"], f["assay_code"], f["run_id"], f["checksum_md5"], f["pipeline"], f["pipeline_version"],
             f["notes"], g.user["username"]))
    except Exception as e:  # unique uri
        conn.rollback()
        flash("Could not add file: " + str(e), "error")
        return redirect(url_for("samples.detail", sample_id=sample_id))
    audit.log(conn, "data_file", cur.lastrowid, "insert", after={"sample_id": sample_id, **f})
    conn.commit()
    flash("File recorded", "ok")
    return redirect(url_for("samples.detail", sample_id=sample_id))


@bp.route("/<sample_id>/files/<int:file_id>/delete", methods=("POST",))
@writer_required
def delete_file(sample_id, file_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM data_file WHERE id=? AND sample_id=?", (file_id, sample_id)).fetchone()
    if row is None:
        abort(404)
    conn.execute("UPDATE data_file SET deleted_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?", (file_id,))
    audit.log(conn, "data_file", file_id, "delete", before=row)
    conn.commit()
    flash("File record removed", "ok")
    return redirect(url_for("samples.detail", sample_id=sample_id))
