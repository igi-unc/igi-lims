"""Collections (nomenclature v2.1): a specimen as received, which is not itself labelled or stored as a tube.

Every tube made straight from it is a first-generation tube with no parent; all tubes from it share its
received date and its collection_id.
"""
import json

from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort, current_app

from ..auth import login_required, writer_required
from ..db import get_db
from .. import samples as svc, audit, rules
from .helpers import codes, code_meaning_map
from . import samples as sviews

bp = Blueprint("collections", __name__, url_prefix="/collections")

FORM_FIELDS = ["participant_id", "received_date", "specimen_code"] + svc.COLLECTION_FIELDS_EDITABLE
REQUIRED = ["participant_id", "received_date", "specimen_code", "biobank_source", "received_from", "received_by",
            "container_type", "transport_temp", "appearance", "quantity", "unit", "notes"]
LABELS = {"participant_id": "Participant", "received_date": "Received date", "specimen_code": "Specimen",
          "biobank_source": "Biobank source", "received_from": "Received from", "received_by": "Received by",
          "container_type": "Container", "transport_temp": "Transport temperature", "appearance": "Appearance",
          "quantity": "Quantity received", "unit": "Unit", "notes": "Notes"}


def _form_ctx(conn):
    return {"participants": conn.execute("SELECT * FROM participant WHERE deleted_at IS NULL ORDER BY participant_id").fetchall(),
            "specimens": codes("specimen"), "sites": codes("site"), "biobanks": codes("biobank_source"),
            "parties": codes("party"), "containers": codes("container_type"), "units": codes("unit"),
            "users": conn.execute("SELECT initials, display_name FROM account WHERE active=1 AND role<>'printer' ORDER BY initials").fetchall()}


def _get_or_404(conn, collection_id):
    c = svc.get_collection(conn, collection_id)
    if c is None:
        abort(404)
    return c


@bp.route("/new", methods=("GET", "POST"))
@writer_required
def new():
    conn = get_db()
    if request.method == "POST":
        data = {f: request.form.get(f, "") for f in FORM_FIELDS}
        missing = [LABELS[f] for f in REQUIRED if not str(data.get(f) or "").strip()]
        if missing:
            flash("All fields are required (choose NA where not applicable). Missing: " + ", ".join(missing), "error")
            return render_template("collections/form.html", c=data, **_form_ctx(conn))
        try:
            cid = svc.create_collection(conn, data)
            conn.commit()
        except ValueError as e:
            conn.rollback()
            flash(str(e), "error")
            return render_template("collections/form.html", c=data, **_form_ctx(conn))
        flash("Collection registered. Now add the tubes made from it.", "ok")
        return redirect(url_for("collections.add_tubes", collection_id=cid))
    data = {"participant_id": request.args.get("participant", ""), "received_by": g.user["initials"]}
    return render_template("collections/form.html", c=data, **_form_ctx(conn))


@bp.route("/<int:collection_id>")
@login_required
def detail(collection_id):
    conn = get_db()
    c = _get_or_404(conn, collection_id)
    tubes = conn.execute("SELECT * FROM sample WHERE collection_id=? ORDER BY sample_id", (collection_id,)).fetchall()
    corrections = svc.corrections_for_collection(conn, collection_id)
    from . import printing
    printed = printing.printed_ids(conn, [t["sample_id"] for t in tubes])
    waiting = set()
    for r in conn.execute("SELECT sample_ids FROM print_job WHERE status IN ('queued','printing')"):
        waiting.update(json.loads(r["sample_ids"]))
    history = conn.execute("SELECT * FROM audit_log WHERE table_name='collection' AND record_id=? ORDER BY id DESC",
                           (str(collection_id),)).fetchall()
    participant = conn.execute("SELECT * FROM participant WHERE participant_id=?", (c["participant_id"],)).fetchone()
    return render_template("collections/detail.html", c=c, label=svc.collection_label(c), tubes=tubes,
                           first_gen=[t for t in tubes if not t["parent_id"]], participant=participant,
                           corrections=corrections, effective=svc.effective_values(corrections), history=history,
                           printed=printed, waiting=waiting,
                           meanings=code_meaning_map(), json=json)


@bp.route("/<int:collection_id>/edit", methods=("GET", "POST"))
@writer_required
def edit(collection_id):
    conn = get_db()
    c = _get_or_404(conn, collection_id)
    if request.method == "POST":
        changes = {f: request.form.get(f, "") for f in svc.COLLECTION_FIELDS_EDITABLE}
        try:
            d = svc.update_collection(conn, collection_id, changes, reason=request.form.get("justification", "").strip() or None)
            conn.commit()
            flash(f"Collection updated ({len(d)} field(s) changed; recorded in the audit log)" if d else "No changes", "ok")
            return redirect(url_for("collections.detail", collection_id=collection_id))
        except ValueError as e:
            conn.rollback()
            flash(str(e), "error")
            return render_template("collections/form.html", c={**dict(c), **changes}, editing=True, **_form_ctx(conn))
    return render_template("collections/form.html", c=dict(c), editing=True, **_form_ctx(conn))


@bp.route("/<int:collection_id>/tubes", methods=("GET", "POST"))
@writer_required
def add_tubes(collection_id):
    """First-generation tubes, made straight from the received specimen."""
    conn = get_db()
    c = _get_or_404(conn, collection_id)
    if c["deleted_at"]:
        abort(404)
    ctx = {"coll": c, "coll_label": svc.collection_label(c),
           "allowed_fr": {r["to_code"] for r in conn.execute(
               "SELECT to_code FROM derivation_rule WHERE rule_type='specimen_fraction' AND from_code=?", (c["specimen_code"],))},
           "allowed_mat": {r["to_code"] for r in conn.execute(
               "SELECT to_code FROM derivation_rule WHERE rule_type='root_material' AND from_code='*'")},
           "n_tubes": conn.execute("SELECT count(*) FROM sample WHERE collection_id=?", (collection_id,)).fetchone()[0]}
    if request.method == "POST":
        payload = sviews._form_payload()
        payload["collection_id"] = collection_id
        return sviews._handle_create(payload, "collections/add_tubes.html", **ctx)
    payload = {"fraction": request.args.get("fraction", ""), "material": request.args.get("material", ""), "count": 1,
               "status": "Available", "created_by": g.user["initials"], "biobank_source": c["biobank_source"],
               "created_datetime": c["time_received"] or (c["received_date"] + "T12:00")}
    return sviews._render_form("collections/add_tubes.html", payload, **ctx)


@bp.route("/<int:collection_id>/tree")
@login_required
def tree(collection_id):
    conn = get_db()
    c = _get_or_404(conn, collection_id)
    t = svc.collection_tree(conn, collection_id, include_deleted=request.args.get("deleted") == "1")
    return render_template("collections/tree.html", c=c, label=svc.collection_label(c), tree_json=json.dumps(t, default=str),
                           highlight=request.args.get("highlight", ""), meanings=code_meaning_map())


@bp.route("/<int:collection_id>/correct", methods=("POST",))
@writer_required
def correct(collection_id):
    conn = get_db()
    _get_or_404(conn, collection_id)
    try:
        svc.add_correction(conn, "received_date", request.form.get("value_received_date", ""), request.form.get("reason", ""),
                           collection_id=collection_id)
        conn.commit()
        flash("Correction recorded for the received date of every tube in this collection; labels and IDs are unchanged.", "ok")
    except ValueError as e:
        conn.rollback()
        flash(str(e), "error")
    return redirect(url_for("collections.detail", collection_id=collection_id))


@bp.route("/<int:collection_id>/delete", methods=("POST",))
@writer_required
def delete(collection_id):
    conn = get_db()
    c = _get_or_404(conn, collection_id)
    if conn.execute("SELECT 1 FROM sample WHERE collection_id=? AND deleted_at IS NULL", (collection_id,)).fetchone():
        flash("A collection with tubes cannot be deleted; delete or move the tubes first", "error")
        return redirect(url_for("collections.detail", collection_id=collection_id))
    if c["deleted_at"]:
        conn.execute("UPDATE collection SET deleted_at=NULL WHERE collection_id=?", (collection_id,))
        audit.log(conn, "collection", collection_id, "restore", reason=request.form.get("justification", "").strip() or None)
        flash("Collection restored", "ok")
    else:
        conn.execute("UPDATE collection SET deleted_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE collection_id=?", (collection_id,))
        audit.log(conn, "collection", collection_id, "delete", before=c, reason=request.form.get("justification", "").strip() or None)
        flash("Collection deleted (soft delete; the record is kept)", "ok")
    conn.commit()
    return redirect(url_for("collections.detail", collection_id=collection_id))
