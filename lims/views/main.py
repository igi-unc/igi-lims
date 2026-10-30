from flask import Blueprint, render_template, g, redirect, url_for, request

from ..auth import login_required
from ..db import get_db
from .. import ids, samples as svc, attributes
from .helpers import codes, code_meaning_map
import json

bp = Blueprint("main", __name__)


@bp.route("/")
@login_required
def index():
    conn = get_db()
    by_status = conn.execute(
        "SELECT status, COUNT(*) n FROM sample WHERE deleted_at IS NULL GROUP BY status ORDER BY n DESC").fetchall()
    by_material = conn.execute(
        "SELECT material_code, COUNT(*) n FROM sample WHERE deleted_at IS NULL GROUP BY material_code ORDER BY n DESC").fetchall()
    totals = conn.execute(
        "SELECT (SELECT COUNT(*) FROM sample WHERE deleted_at IS NULL) samples, "
        "(SELECT COUNT(*) FROM participant WHERE deleted_at IS NULL) participants, "
        "(SELECT COUNT(*) FROM collection WHERE deleted_at IS NULL) collections, "
        "(SELECT COUNT(*) FROM data_file WHERE deleted_at IS NULL) files").fetchone()
    recent = conn.execute(
        "SELECT * FROM audit_log WHERE table_name IN ('sample','collection','custody_event','data_file','participant') "
        "ORDER BY id DESC LIMIT 15").fetchall()
    recent_samples = conn.execute(
        "SELECT * FROM sample WHERE deleted_at IS NULL ORDER BY record_created_at DESC LIMIT 10").fetchall()
    return render_template("index.html", by_status=by_status, by_material=by_material, totals=totals,
                           recent=recent, recent_samples=recent_samples)


@bp.route("/go")
@login_required
def go():
    """Jump box: exact sample ID (e.g. from a barcode scan) or participant."""
    q = (request.args.get("q") or "").strip().upper()
    conn = get_db()
    if conn.execute("SELECT 1 FROM sample WHERE sample_id=?", (q,)).fetchone():
        return redirect(url_for("samples.detail", sample_id=q))
    if q.isdigit() and len(q) <= 7:                       # LIMS number, typed with or without leading zeros
        row = conn.execute("SELECT sample_id FROM sample WHERE serial=?", (int(q),)).fetchone()
        if row:
            return redirect(url_for("samples.detail", sample_id=row["sample_id"]))
    if conn.execute("SELECT 1 FROM participant WHERE participant_id=?", (q,)).fetchone():
        return redirect(url_for("participants.detail", participant_id=q))
    row = conn.execute("SELECT participant_id FROM participant WHERE 'UNC' || unc_number=?", (q,)).fetchone()
    if row:
        return redirect(url_for("participants.detail", participant_id=row["participant_id"]))
    return redirect(url_for("samples.list_samples", q=q))


@bp.route("/scan")
@login_required
def scan():
    """Point a phone, tablet or webcam at a tube's Data Matrix to open its page. The code holds only the sample ID;
    this page (behind the login) turns it into the tube page."""
    from flask import current_app
    return render_template("scan.html", pattern=ids.full_pattern(), reader_url=current_app.config["BARCODE_READER_URL"])


@bp.route("/browse")
@login_required
def browse():
    """Samples & Participants: pick a participant, see the tree of everything derived from them."""
    conn = get_db()
    q = (request.args.get("q") or "").strip()
    cohort = request.args.get("cohort") or ""
    where, params = ["p.deleted_at IS NULL"], []
    if q:
        where.append("(p.participant_id LIKE ? OR 'UNC' || p.unc_number LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    if cohort:
        where.append("p.cohort_code=?")
        params.append(cohort)
    participants = conn.execute(
        "SELECT p.*, (SELECT COUNT(*) FROM sample s WHERE s.participant_id=p.participant_id AND s.deleted_at IS NULL) n_samples "
        "FROM participant p WHERE " + " AND ".join(where) + " ORDER BY p.cohort_code, p.participant_id", params).fetchall()
    pid = request.args.get("participant") or ""
    selected = conn.execute("SELECT * FROM participant WHERE participant_id=?", (pid,)).fetchone() if pid else None
    forest = svc.participant_forest(conn, pid, include_deleted=request.args.get("deleted") == "1") if selected else None
    attrs = {}
    if selected:
        sids = [r["sample_id"] for r in conn.execute("SELECT sample_id FROM sample WHERE participant_id=?", (pid,))]
        attrs = attributes.for_samples(conn, sids)
    return render_template("browse.html", participants=participants, q=q, cohort=cohort, cohorts=codes("cohort"),
                           selected=selected, forest_json=json.dumps(forest, default=str) if forest else "null",
                           highlight=request.args.get("highlight", ""), meanings=code_meaning_map(),
                           meanings_json=json.dumps(code_meaning_map()), attrs_json=json.dumps(attrs),
                           attr_labels_json=json.dumps({k: v[0] + (f" ({v[1]})" if v[1] else "") for k, v in attributes.labels(conn).items()}))


@bp.route("/register")
@login_required
def register():
    return render_template("register.html")
