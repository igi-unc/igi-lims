from flask import Blueprint, render_template, g, redirect, url_for, request

from ..auth import login_required
from ..db import get_db
from .. import ids

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
        "(SELECT COUNT(DISTINCT root_id) FROM sample WHERE deleted_at IS NULL) collections, "
        "(SELECT COUNT(*) FROM data_file WHERE deleted_at IS NULL) files").fetchone()
    recent = conn.execute(
        "SELECT * FROM audit_log WHERE table_name IN ('sample','custody_event','data_file','participant') "
        "ORDER BY id DESC LIMIT 15").fetchall()
    recent_samples = conn.execute(
        "SELECT * FROM sample WHERE deleted_at IS NULL ORDER BY record_created_at DESC LIMIT 10").fetchall()
    return render_template("index.html", by_status=by_status, by_material=by_material, totals=totals,
                           recent=recent, recent_samples=recent_samples, pattern=ids.full_pattern())


@bp.route("/go")
@login_required
def go():
    """Jump box: exact sample ID (e.g. from a barcode scan) or participant."""
    q = (request.args.get("q") or "").strip().upper()
    conn = get_db()
    if conn.execute("SELECT 1 FROM sample WHERE sample_id=?", (q,)).fetchone():
        return redirect(url_for("samples.detail", sample_id=q))
    if conn.execute("SELECT 1 FROM participant WHERE participant_id=?", (q,)).fetchone():
        return redirect(url_for("participants.detail", participant_id=q))
    return redirect(url_for("samples.list_samples", q=q))
