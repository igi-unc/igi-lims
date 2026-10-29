"""Label printing through a print queue.

Anyone who can register tubes sends labels to the queue from any browser. One print station (a computer next to
the Brady M611, logged in as an account with role 'printer') claims jobs in order and prints them through Brady's
Web SDK. The station account can reach nothing but this page and the labels it prints.
"""
import json
import secrets
from datetime import datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort, jsonify, current_app

from ..auth import login_required, role_required, writer_required
from ..db import get_db
from .. import audit, samples as svc, labels

bp = Blueprint("printing", __name__, url_prefix="/print")
station_required = role_required("printer", "admin")


def _now():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def queue_job(conn, sample_ids, header=True):
    """Queue labels for these tubes (in this order). Returns the job id. Raises ValueError."""
    seen, ids = set(), []
    for sid in sample_ids:
        sid = (sid or "").strip().upper()
        if sid and sid not in seen:
            seen.add(sid)
            ids.append(sid)
    if not ids:
        raise ValueError("Choose at least one tube to print")
    if len(ids) > current_app.config["PRINT_JOB_MAX_LABELS"]:
        raise ValueError(f"At most {current_app.config['PRINT_JOB_MAX_LABELS']} labels per job")
    for sid in ids:
        s = svc.get_sample(conn, sid)
        if s is None or s["deleted_at"]:
            raise ValueError(f"No tube {sid}")
    cur = conn.execute("INSERT INTO print_job(requested_by, requested_initials, sample_ids, n_labels, header) VALUES (?,?,?,?,?)",
                       (g.user["username"], g.user["initials"], json.dumps(ids), len(ids), 1 if header else 0))
    jid = cur.lastrowid
    audit.log(conn, "print_job", jid, "insert", after={"labels": len(ids), "first": ids[0], "header": bool(header)})
    return jid


@bp.route("/jobs", methods=("POST",))
@writer_required
def create():
    conn = get_db()
    try:
        jid = queue_job(conn, request.form.getlist("sample_id"), header=request.form.get("header", "1") == "1")
        conn.commit()
        n = conn.execute("SELECT n_labels FROM print_job WHERE id=?", (jid,)).fetchone()[0]
        ahead = conn.execute("SELECT count(*) FROM print_job WHERE status IN ('queued','printing') AND id<?", (jid,)).fetchone()[0]
        flash(f"Sent {n} label(s) to the printer as job #{jid}" + (f"; {ahead} job(s) ahead of it." if ahead else ".")
              + " Collect them at the print station.", "ok")
    except ValueError as e:
        conn.rollback()
        flash(str(e), "error")
    nxt = request.form.get("next") or request.referrer or url_for("printing.jobs")
    return redirect(nxt if nxt.startswith("/") or nxt.startswith(request.host_url) else url_for("printing.jobs"))


@bp.route("/jobs")
@login_required
def jobs():
    conn = get_db()
    rows = conn.execute("SELECT * FROM print_job ORDER BY id DESC LIMIT 100").fetchall()
    stations = conn.execute("SELECT username, display_name FROM account WHERE role='printer' AND active=1").fetchall()
    last_seen = conn.execute("SELECT max(claimed_at) FROM print_job").fetchone()[0]
    return render_template("printing/jobs.html", rows=rows, ids={r["id"]: json.loads(r["sample_ids"]) for r in rows},
                           stations=stations, last_seen=last_seen, stock=current_app.config["LABEL_STOCK"])


@bp.route("/jobs/<int:job_id>/<action>", methods=("POST",))
@writer_required
def change(job_id, action):
    conn = get_db()
    job = conn.execute("SELECT * FROM print_job WHERE id=?", (job_id,)).fetchone()
    if job is None:
        abort(404)
    if action == "cancel" and job["status"] == "queued":
        conn.execute("UPDATE print_job SET status='cancelled', finished_at=? WHERE id=?", (_now(), job_id))
    elif action == "requeue" and job["status"] in ("failed", "printing", "printed", "cancelled"):
        conn.execute("UPDATE print_job SET status='queued', station=NULL, claim_token=NULL, claimed_at=NULL, finished_at=NULL, "
                     "error=NULL WHERE id=?", (job_id,))
    else:
        flash(f"Job #{job_id} is {job['status']}; cannot {action} it", "error")
        return redirect(url_for("printing.jobs"))
    audit.log(conn, "print_job", job_id, action, before={"status": job["status"]})
    conn.commit()
    flash(f"Job #{job_id}: {action} done", "ok")
    return redirect(url_for("printing.jobs"))


@bp.route("/jobs/<int:job_id>/header.svg")
@station_required
def header_svg(job_id):
    job = get_db().execute("SELECT * FROM print_job WHERE id=?", (job_id,)).fetchone()
    if job is None:
        abort(404)
    lines = [f"PRINT JOB #{job_id}", f"FOR {job['requested_initials'] or job['requested_by']}",
             f"{job['n_labels']} LABEL{'S' if job['n_labels'] != 1 else ''} FOLLOW"]
    return current_app.response_class(labels.header_print_svg(lines), mimetype="image/svg+xml")


@bp.route("/jobs/<int:job_id>.csv")
@login_required
def job_csv(job_id):
    """The job as a spreadsheet for Brady Express Labels or Brady Workstation: one row per label, the barcode
    value and the three printed text rows."""
    import csv, io
    conn = get_db()
    job = conn.execute("SELECT * FROM print_job WHERE id=?", (job_id,)).fetchone()
    if job is None:
        abort(404)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["barcode", "line1", "line2", "line3"])
    for sid in json.loads(job["sample_ids"]):
        w.writerow([sid] + svc.label_rows({"sample_id": sid}))
    resp = current_app.response_class(buf.getvalue(), mimetype="text/csv")
    resp.headers["Content-Disposition"] = f'attachment; filename="print_job_{job_id}.csv"'
    return resp


# ------------------------------------------------------------------ the station

TEST_ID = "IGI-MP-P101-UNC316-26SEP29-PF-TUM-HMD-01-KEN-26OCT06"   # the nomenclature's own example; not a real tube


@bp.route("/station/test.svg")
@station_required
def test_svg():
    """A calibration label for the example ID, so alignment can be checked without touching real tubes."""
    return current_app.response_class(labels.label_print_svg({"sample_id": TEST_ID}), mimetype="image/svg+xml")


@bp.route("/station")
@station_required
def station():
    st = current_app.config["LABEL_STOCK"]
    queued = get_db().execute("SELECT count(*) FROM print_job WHERE status='queued'").fetchone()[0]
    return render_template("printing/station.html", stock=st, queued=queued, sdk_url=current_app.config["BRADY_SDK_URL"])


@bp.route("/station/claim", methods=("POST",))
@station_required
def claim():
    """Give the station the oldest queued job (or nothing). Safe if two stations ask at once."""
    conn = get_db()
    row = conn.execute("SELECT id FROM print_job WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
    queued = conn.execute("SELECT count(*) FROM print_job WHERE status='queued'").fetchone()[0]
    if row is None:
        return jsonify({"job": None, "queued": 0})
    token = secrets.token_hex(8)
    conn.execute("UPDATE print_job SET status='printing', station=?, claim_token=?, claimed_at=? WHERE id=? AND status='queued'",
                 (g.user["username"], token, _now(), row["id"]))
    conn.commit()
    job = conn.execute("SELECT * FROM print_job WHERE id=? AND claim_token=?", (row["id"], token)).fetchone()
    if job is None:      # another station got it first
        return jsonify({"job": None, "queued": queued})
    ids = json.loads(job["sample_ids"])
    st = current_app.config["LABEL_STOCK"]
    images = ([{"kind": "header", "url": url_for("printing.header_svg", job_id=job["id"])}] if job["header"] else []) + \
             [{"kind": "label", "sample_id": sid, "url": url_for("samples.label_svg", sample_id=sid, print=1)} for sid in ids]
    return jsonify({"job": {"id": job["id"], "token": token, "requested_by": job["requested_by"],
                            "initials": job["requested_initials"], "n_labels": job["n_labels"], "images": images},
                    "queued": queued - 1, "stock": st})


@bp.route("/station/<int:job_id>/done", methods=("POST",))
@station_required
def done(job_id):
    conn = get_db()
    data = request.get_json(silent=True) or {}
    job = conn.execute("SELECT * FROM print_job WHERE id=?", (job_id,)).fetchone()
    if job is None or job["claim_token"] != data.get("token") or job["status"] != "printing":
        return jsonify({"ok": False, "error": "not your job"}), 409
    ok = bool(data.get("ok"))
    err = None if ok else (str(data.get("error") or "printer reported a failure")[:500])
    conn.execute("UPDATE print_job SET status=?, finished_at=?, error=? WHERE id=?",
                 ("printed" if ok else "failed", _now(), err, job_id))
    audit.log(conn, "print_job", job_id, "update", before={"status": "printing"},
              after={"status": "printed" if ok else "failed", **({"error": err} if err else {})})
    conn.commit()
    return jsonify({"ok": True})
