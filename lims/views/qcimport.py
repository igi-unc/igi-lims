"""Import QC: upload one instrument export, match its rows to tubes, write the values as attributes."""
import re
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort

from ..auth import writer_required, login_required
from ..db import get_db
from .. import attachments, attributes, qc_parsers, ids, samples as svc

bp = Blueprint("qc", __name__, url_prefix="/qc")


def _suggest(conn, name):
    """Find a tube ID inside an instrument sample name (full ID, or a unique suffix like TUM-HMD-01)."""
    if not name:
        return ""
    m = re.search(ids.full_pattern().strip("^$"), name.upper())
    if m and svc.get_sample(conn, m.group(0)):
        return m.group(0)
    return ""


@bp.route("/import", methods=("GET", "POST"))
@writer_required
def upload():
    conn = get_db()
    if request.method == "POST":
        f = request.files.get("file")
        if not f or not f.filename:
            flash("Choose an instrument export file", "error")
            return redirect(url_for("qc.upload"))
        inst = request.form.get("instrument") or None
        row = attachments.save(conn, f, sample_id=None, kind="qc_export", instrument=inst,
                               notes=request.form.get("notes", "").strip() or None)
        try:
            inst, ms = qc_parsers.parse(attachments.abs_path(row), inst, row["filename"])
        except qc_parsers.ParseError as e:
            conn.rollback()
            flash(str(e), "error")
            return redirect(url_for("qc.upload"))
        if inst != row["instrument"]:
            conn.execute("UPDATE attachment SET instrument=? WHERE id=?", (inst, row["id"]))
        conn.commit()
        return redirect(url_for("qc.confirm", attachment_id=row["id"]))
    return render_template("qc/import.html", instruments=qc_parsers.INSTRUMENTS)


@bp.route("/import/<int:attachment_id>", methods=("GET", "POST"))
@writer_required
def confirm(attachment_id):
    conn = get_db()
    att = attachments.get(conn, attachment_id)
    if att is None or att["kind"] != "qc_export" or att["deleted_at"]:
        abort(404)
    try:
        inst, ms = qc_parsers.parse(attachments.abs_path(att), att["instrument"], att["filename"])
    except qc_parsers.ParseError as e:
        flash(str(e), "error")
        return redirect(url_for("qc.upload"))
    labels = attributes.labels(conn)
    if request.method == "POST":
        written, skipped, errors = [], 0, []
        for i, m in enumerate(ms):
            sid = (request.form.get(f"tube_{i}") or "").strip().upper()
            if not sid:
                skipped += 1
                continue
            s = svc.get_sample(conn, sid)
            if s is None or s["deleted_at"]:
                errors.append(f"row {i + 1}: no tube {sid}")
                continue
            chosen = {k: v for k, (v, _u) in m.values.items() if request.form.get(f"use_{i}_{k}")}
            if not chosen:
                skipped += 1
                continue
            vals = attributes.validate_dict(conn, {k: str(v) for k, v in chosen.items()}, s["fraction_code"], s["material_code"])
            attributes.set_values(conn, sid, vals, source_attachment_id=att["id"])
            written.append(sid)
        conn.commit()
        if errors:
            flash("; ".join(errors), "error")
        flash(f"Wrote values to {len(written)} tube(s); {skipped} row(s) skipped", "ok")
        if len(written) == 1:
            return redirect(url_for("samples.detail", sample_id=written[0]))
        return redirect(url_for("qc.upload"))
    rows = []
    for i, m in enumerate(ms):
        rows.append({"i": i, "m": m, "suggest": _suggest(conn, m.sample_name),
                     "vals": [(k, v, u, labels.get(k, (k, None))[0]) for k, (v, u) in m.values.items()]})
    return render_template("qc/confirm.html", att=att, instrument=qc_parsers.INSTRUMENTS.get(inst, inst), rows=rows)
