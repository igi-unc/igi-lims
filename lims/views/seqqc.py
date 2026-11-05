"""Sequencing QC overview: distributions, scatter plots and per-check verdicts across libraries."""
from flask import Blueprint, render_template, jsonify, request

from ..auth import login_required
from ..db import get_db
from .. import seqqc

bp = Blueprint("seqqc", __name__, url_prefix="/seq-qc")


@bp.route("/")
@login_required
def overview():
    n = get_db().execute("SELECT count(*) FROM seq_qc").fetchone()[0]
    return render_template("seqqc/overview.html", n_results=n, labels=seqqc.METRIC_LABELS,
                           participant=request.args.get("participant", ""))


@bp.route("/data.json")
@login_required
def data():
    return jsonify({"rows": seqqc.chart_rows(get_db()), "labels": seqqc.METRIC_LABELS})
