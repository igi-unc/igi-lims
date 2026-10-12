import json
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort

from ..auth import login_required, writer_required
from ..db import get_db
from .. import approvals as svc

bp = Blueprint("approvals", __name__, url_prefix="/approvals")


@bp.route("/")
@login_required
def list_requests():
    conn = get_db()
    status = request.args.get("status", "pending")
    rows = conn.execute("SELECT * FROM approval_request WHERE status=? ORDER BY id DESC LIMIT 200", (status,)).fetchall()
    return render_template("approvals/list.html", rows=rows, status=status, json=json)


@bp.route("/<int:request_id>")
@login_required
def detail(request_id):
    req = svc.get(get_db(), request_id)
    if req is None:
        abort(404)
    return render_template("approvals/detail.html", r=req, payload=json.loads(req["payload"]),
                           violations=json.loads(req["violations"]) if req["violations"] else None,
                           result=json.loads(req["result"]) if req["result"] else None,
                           can_decide=req["status"] == "pending" and req["requested_by"] != g.user["username"]
                           and g.user["role"] in ("admin", "user"))


@bp.route("/<int:request_id>/decide", methods=("POST",))
@writer_required
def decide(request_id):
    conn = get_db()
    req = svc.get(conn, request_id)
    if req is None:
        abort(404)
    note = request.form.get("note", "").strip() or None
    try:
        if request.form.get("decision") == "approve":
            status, result = svc.apply(conn, req, note)
            conn.commit()
            if status == "approved":
                flash("Approved and applied: " + json.dumps(result), "ok")
            else:
                flash("Approved but the action failed: " + result.get("error", ""), "error")
        else:
            svc.reject(conn, req, note)
            conn.commit()
            flash("Request rejected", "ok")
    except ValueError as e:
        conn.rollback()
        flash(str(e), "error")
    return redirect(url_for("approvals.detail", request_id=request_id))
