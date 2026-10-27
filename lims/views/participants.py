import re
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort, current_app

from ..auth import login_required, writer_required
from ..db import get_db
from .. import ids, audit, samples as svc
from .helpers import codes, code_meaning_map

bp = Blueprint("participants", __name__, url_prefix="/participants")


@bp.route("/")
@login_required
def list_participants():
    conn = get_db()
    q = (request.args.get("q") or "").strip().upper()
    cohort = request.args.get("cohort") or ""
    where, params = ["p.deleted_at IS NULL"], []
    if q:
        where.append("(p.participant_id LIKE ? OR 'UNC' || p.unc_number LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    if cohort:
        where.append("p.cohort_code=?")
        params.append(cohort)
    rows = conn.execute(
        "SELECT p.*, (SELECT COUNT(*) FROM sample s WHERE s.participant_id=p.participant_id AND s.deleted_at IS NULL) n_samples, "
        "(SELECT COUNT(*) FROM collection c WHERE c.participant_id=p.participant_id AND c.deleted_at IS NULL) n_collections "
        "FROM participant p WHERE " + " AND ".join(where) + " ORDER BY p.participant_id", params).fetchall()
    return render_template("participants/list.html", rows=rows, q=q, cohort=cohort, cohorts=codes("cohort"),
                           meanings=code_meaning_map())


def _form(p, editing=False, locked=False):
    return render_template("participants/form.html", p=p, cohorts=codes("cohort"), sites=codes("site"), editing=editing,
                           locked=locked, unc_digits=current_app.config["UNC_DIGITS"])


def _check_unc(conn, unc, own=None):
    digits = current_app.config["UNC_DIGITS"]
    if not re.fullmatch(r"\d{%d}" % digits, unc or ""):
        raise ValueError(f"UNC number must be exactly {digits} digits (UNC316 is entered as 316)")
    row = conn.execute("SELECT participant_id FROM participant WHERE unc_number=?", (unc,)).fetchone()
    if row and row["participant_id"] != own:
        raise ValueError(f"UNC{unc} is already participant {row['participant_id']}")


@bp.route("/new", methods=("GET", "POST"))
@writer_required
def new():
    conn = get_db()
    if request.method == "POST":
        f = request.form
        pid = (f.get("participant_id") or "").strip().upper()
        if not pid or g.user["role"] != "admin":     # only admins may enter an existing number
            pid = ids.new_participant_code(conn)
        unc = (f.get("unc_number") or "").strip().upper().removeprefix("UNC")
        try:
            pat = ids.participant_pattern()
            if pat and not re.match(pat, pid):
                raise ValueError(f"IGI patient ID must match {pat} (e.g. P101)")
            if conn.execute("SELECT 1 FROM participant WHERE participant_id=?", (pid,)).fetchone():
                raise ValueError(f"{pid} is already in use (IGI patient IDs are never reused)")
            _check_unc(conn, unc)
            if (f.get("site_code") or "UNC") != "UNC":
                raise ValueError("Only UNC participants are supported for now (the ID carries a UNC number)")
            if not conn.execute("SELECT 1 FROM code_list WHERE category='cohort' AND code=? AND active=1", (f.get("cohort_code"),)).fetchone():
                raise ValueError("Choose a cohort")
        except ValueError as e:
            flash(str(e), "error")
            return _form({**f, "participant_id": f.get("participant_id", "")})
        row = {"participant_id": pid, "cohort_code": f["cohort_code"], "unc_number": unc, "site_code": "UNC",
               "notes": f.get("notes", "").strip() or None, "created_by": g.user["username"]}
        conn.execute("INSERT INTO participant(participant_id, cohort_code, unc_number, site_code, notes, created_by) "
                     "VALUES (:participant_id, :cohort_code, :unc_number, :site_code, :notes, :created_by)", row)
        audit.log(conn, "participant", pid, "insert", after=row)
        conn.commit()
        flash(f"Participant {pid} (UNC{unc}) created", "ok")
        return redirect(url_for("participants.detail", participant_id=pid))
    return _form({"participant_id": ids.new_participant_code(conn), "site_code": "UNC"})


@bp.route("/<participant_id>")
@login_required
def detail(participant_id):
    conn = get_db()
    p = conn.execute("SELECT * FROM participant WHERE participant_id=?", (participant_id,)).fetchone()
    if p is None:
        abort(404)
    collections = conn.execute(
        "SELECT c.*, (SELECT COUNT(*) FROM sample s WHERE s.collection_id=c.collection_id AND s.deleted_at IS NULL) n, "
        "(SELECT COUNT(*) FROM sample s WHERE s.collection_id=c.collection_id AND s.deleted_at IS NULL AND s.status='Available') n_avail "
        "FROM collection c WHERE c.participant_id=? AND c.deleted_at IS NULL ORDER BY c.received_date, c.collection_id",
        (participant_id,)).fetchall()
    return render_template("participants/detail.html", p=p, collections=collections, meanings=code_meaning_map(),
                           labels={c["collection_id"]: svc.collection_label(c) for c in collections})


@bp.route("/<participant_id>/edit", methods=("GET", "POST"))
@writer_required
def edit(participant_id):
    conn = get_db()
    p = conn.execute("SELECT * FROM participant WHERE participant_id=?", (participant_id,)).fetchone()
    if p is None:
        abort(404)
    locked = conn.execute("SELECT 1 FROM sample WHERE participant_id=?", (participant_id,)).fetchone() is not None
    if request.method == "POST":
        f = request.form
        new = {"cohort_code": f.get("cohort_code") or p["cohort_code"],
               "unc_number": (f.get("unc_number") or p["unc_number"] or "").strip().upper().removeprefix("UNC"),
               "notes": f.get("notes", "").strip() or None}
        try:
            if locked and (new["cohort_code"] != p["cohort_code"] or new["unc_number"] != p["unc_number"]):
                raise ValueError("Cohort and UNC number cannot change once tubes exist (they are part of every sample ID)")
            _check_unc(conn, new["unc_number"], own=participant_id)
        except ValueError as e:
            flash(str(e), "error")
            return _form(p, editing=True, locked=locked)
        conn.execute("UPDATE participant SET cohort_code=:cohort_code, unc_number=:unc_number, notes=:notes WHERE participant_id=:pid",
                     {**new, "pid": participant_id})
        audit.log(conn, "participant", participant_id, "update", before={k: p[k] for k in new}, after=new)
        conn.commit()
        flash("Participant updated", "ok")
        return redirect(url_for("participants.detail", participant_id=participant_id))
    return _form(p, editing=True, locked=locked)
