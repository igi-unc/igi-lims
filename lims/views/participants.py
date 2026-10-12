import re
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort

from ..auth import login_required, writer_required
from ..db import get_db
from .. import ids, audit
from .helpers import codes, code_meaning_map

bp = Blueprint("participants", __name__, url_prefix="/participants")


@bp.route("/")
@login_required
def list_participants():
    conn = get_db()
    q = (request.args.get("q") or "").strip()
    cohort = request.args.get("cohort") or ""
    where, params = ["p.deleted_at IS NULL"], []
    if q:
        where.append("(p.participant_id LIKE ? OR p.external_participant_id LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    if cohort:
        where.append("p.cohort_code=?")
        params.append(cohort)
    rows = conn.execute(
        "SELECT p.*, (SELECT COUNT(*) FROM sample s WHERE s.participant_id=p.participant_id AND s.deleted_at IS NULL) n_samples, "
        "(SELECT COUNT(DISTINCT root_id) FROM sample s WHERE s.participant_id=p.participant_id AND s.deleted_at IS NULL) n_collections "
        "FROM participant p WHERE " + " AND ".join(where) + " ORDER BY p.cohort_code, p.participant_id", params).fetchall()
    return render_template("participants/list.html", rows=rows, q=q, cohort=cohort, cohorts=codes("cohort"),
                           meanings=code_meaning_map())


@bp.route("/new", methods=("GET", "POST"))
@writer_required
def new():
    conn = get_db()
    if request.method == "POST":
        pid = (request.form.get("participant_id") or "").strip().upper() or ids.new_participant_code(conn)
        pat = ids.participant_pattern()
        if pat and not re.match(pat, pid):
            flash(f"Participant code must match {pat}", "error")
            return render_template("participants/form.html", p=request.form, cohorts=codes("cohort"), sites=codes("site"))
        if conn.execute("SELECT 1 FROM participant WHERE participant_id=?", (pid,)).fetchone():
            flash("That participant code is already in use", "error")
            return render_template("participants/form.html", p=request.form, cohorts=codes("cohort"), sites=codes("site"))
        row = {"participant_id": pid, "cohort_code": request.form["cohort_code"],
               "external_participant_id": request.form.get("external_participant_id", "").strip() or None,
               "site_code": request.form.get("site_code") or None,
               "notes": request.form.get("notes", "").strip() or None, "created_by": g.user["username"]}
        conn.execute("INSERT INTO participant(participant_id, cohort_code, external_participant_id, site_code, notes, created_by) "
                     "VALUES (:participant_id, :cohort_code, :external_participant_id, :site_code, :notes, :created_by)", row)
        audit.log(conn, "participant", pid, "insert", after=row)
        conn.commit()
        flash(f"Participant {pid} created", "ok")
        return redirect(url_for("participants.detail", participant_id=pid))
    return render_template("participants/form.html", p={}, cohorts=codes("cohort"), sites=codes("site"))


@bp.route("/<participant_id>")
@login_required
def detail(participant_id):
    conn = get_db()
    p = conn.execute("SELECT * FROM participant WHERE participant_id=?", (participant_id,)).fetchone()
    if p is None:
        abort(404)
    collections = conn.execute(
        "SELECT root_id, collection_date, specimen_code, COUNT(*) n, SUM(status='Available') n_avail "
        "FROM sample WHERE participant_id=? AND deleted_at IS NULL GROUP BY root_id ORDER BY collection_date, root_id",
        (participant_id,)).fetchall()
    return render_template("participants/detail.html", p=p, collections=collections, meanings=code_meaning_map())


@bp.route("/<participant_id>/edit", methods=("GET", "POST"))
@writer_required
def edit(participant_id):
    conn = get_db()
    p = conn.execute("SELECT * FROM participant WHERE participant_id=?", (participant_id,)).fetchone()
    if p is None:
        abort(404)
    if request.method == "POST":
        new = {"cohort_code": request.form["cohort_code"],
               "external_participant_id": request.form.get("external_participant_id", "").strip() or None,
               "site_code": request.form.get("site_code") or None,
               "notes": request.form.get("notes", "").strip() or None}
        if new["cohort_code"] != p["cohort_code"] and conn.execute(
                "SELECT 1 FROM sample WHERE participant_id=?", (participant_id,)).fetchone():
            flash("Cohort cannot change once samples exist (it is part of every sample ID)", "error")
            return render_template("participants/form.html", p=p, cohorts=codes("cohort"), sites=codes("site"), editing=True)
        conn.execute("UPDATE participant SET cohort_code=:cohort_code, external_participant_id=:external_participant_id, "
                     "site_code=:site_code, notes=:notes WHERE participant_id=:pid", {**new, "pid": participant_id})
        audit.log(conn, "participant", participant_id, "update", before=p, after=new)
        conn.commit()
        flash("Participant updated", "ok")
        return redirect(url_for("participants.detail", participant_id=participant_id))
    return render_template("participants/form.html", p=p, cohorts=codes("cohort"), sites=codes("site"), editing=True)
