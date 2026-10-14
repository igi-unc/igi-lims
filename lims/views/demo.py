"""Demonstration-instance endpoints: a reset button for admins and a cron hook for Vercel."""
from flask import Blueprint, current_app, request, jsonify, abort, redirect, url_for, flash

from ..auth import admin_required
from ..db import get_db
from ..demo import reset_demo

bp = Blueprint("demo", __name__)


def _reset():
    return reset_demo(get_db(), current_app.config["DEMO_PASSWORD"])


@bp.route("/cron/demo-reset")
def cron_reset():
    """Vercel calls this on the schedule in vercel.json with `Authorization: Bearer $CRON_SECRET`."""
    secret = current_app.config.get("CRON_SECRET")
    if not current_app.config.get("DEMO_MODE") or not secret:
        abort(404)
    if request.headers.get("Authorization") != "Bearer " + secret:
        abort(401)
    info = _reset()
    return jsonify({"reset": True, "participant": info["participant"], "tubes": info["tubes"]})


@bp.route("/demo/reset", methods=("POST",))
@admin_required
def button_reset():
    if not current_app.config.get("DEMO_MODE"):
        abort(404)
    info = _reset()
    flash(f"Demo data rebuilt: participant {info['participant']} with {info['tubes']} tubes. You are still logged in as the demo admin.", "ok")
    return redirect(url_for("main.index"))
