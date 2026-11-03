"""Read-only JSON API for pipeline scripts. Authenticate with a login session or
the X-Api-Token header (set LIMS_API_TOKEN in the environment)."""
import os
import re
import hmac
import functools
from flask import Blueprint, jsonify, request, g, abort, current_app

from ..db import get_db
from .. import ids, samples as svc

bp = Blueprint("api", __name__, url_prefix="/api")


def api_auth(view):
    @functools.wraps(view)
    def wrapped(**kw):
        token = os.environ.get("LIMS_API_TOKEN")
        given = request.headers.get("X-Api-Token") or ""
        if g.user is None and not (token and hmac.compare_digest(given.encode(), token.encode())):
            return jsonify({"error": "unauthorised"}), 401
        return view(**kw)
    return wrapped


def _row(r):
    if r is None:
        return None
    d = {k: r[k] for k in r.keys()}
    if "serial" in d:                       # the LIMS number as printed, zero-padded
        from ..db import format_serial
        d["lims_number"] = format_serial(d["serial"]) if d["serial"] is not None else None
    return d


@bp.route("/pattern")
def pattern():
    """The anchored regex every pipeline script should use."""
    return jsonify({"pattern": ids.full_pattern(), "length": current_app.config.get("ID_LENGTH")})


@bp.route("/validate/<sample_id>")
def validate(sample_id):
    try:
        comp = ids.parse(sample_id)
    except ids.IdError as e:
        return jsonify({"valid": False, "error": str(e)}), 400
    exists = get_db().execute("SELECT 1 FROM sample WHERE sample_id=?", (sample_id,)).fetchone() is not None
    return jsonify({"valid": True, "components": comp, "exists": exists})


@bp.route("/samples")
@api_auth
def list_samples():
    conn = get_db()
    where, params = ["deleted_at IS NULL"], []
    for key, col in (("participant", "participant_id"), ("root", "root_id"), ("collection", "collection_id"), ("material", "material_code"),
                     ("fraction", "fraction_code"), ("specimen", "specimen_code"), ("status", "status"),
                     ("cohort", "cohort_code")):
        if request.args.get(key):
            where.append(f"{col}=?"); params.append(request.args[key])
    if request.args.get("prefix"):
        where.append("sample_id LIKE ?"); params.append(request.args["prefix"] + "%")
    rows = conn.execute("SELECT * FROM sample WHERE " + " AND ".join(where) + " ORDER BY sample_id LIMIT 5000", params)
    return jsonify([_row(r) for r in rows])


@bp.route("/samples/<sample_id>")
@api_auth
def sample(sample_id):
    conn = get_db()
    s = svc.get_sample(conn, sample_id)
    if s is None:
        abort(404)
    files = conn.execute("SELECT * FROM data_file WHERE sample_id=? AND deleted_at IS NULL", (sample_id,)).fetchall()
    custody = conn.execute("SELECT * FROM custody_event WHERE sample_id=? ORDER BY event_datetime", (sample_id,)).fetchall()
    corrections = svc.corrections_for(conn, s)
    return jsonify({"sample": _row(s), "collection": _row(svc.get_collection(conn, s["collection_id"])),
                    "files": [_row(f) for f in files], "custody": [_row(c) for c in custody],
                    "corrections": [_row(c) for c in corrections], "corrected_values": svc.effective_values(corrections)})


@bp.route("/samples/<sample_id>/lineage")
@api_auth
def lineage(sample_id):
    conn = get_db()
    s = svc.get_sample(conn, sample_id)
    if s is None:
        abort(404)
    return jsonify({
        "sample": _row(s),
        "ancestors": [_row(a) for a in svc.ancestors(conn, sample_id)],
        "descendants": [_row(d) for d in svc.descendants(conn, sample_id)],
    })


@bp.route("/tree/<root_id>")
@api_auth
def tree(root_id):
    """Tree of the collection this tube belongs to."""
    conn = get_db()
    s = svc.get_sample(conn, root_id)
    if s is None:
        abort(404)
    return jsonify(svc.collection_tree(conn, s["collection_id"]))


@bp.route("/collections/<int:collection_id>")
@api_auth
def collection(collection_id):
    conn = get_db()
    c = svc.get_collection(conn, collection_id)
    if c is None:
        abort(404)
    return jsonify({"collection": _row(c), "tree": svc.collection_tree(conn, collection_id),
                    "corrections": [_row(x) for x in svc.corrections_for_collection(conn, collection_id)]})


@bp.route("/files")
@api_auth
def files():
    conn = get_db()
    where, params = ["f.deleted_at IS NULL"], []
    if request.args.get("assay"):
        where.append("f.assay_code=?"); params.append(request.args["assay"])
    if request.args.get("participant"):
        where.append("s.participant_id=?"); params.append(request.args["participant"])
    rows = conn.execute("SELECT f.*, s.participant_id, s.collection_id, s.root_id FROM data_file f JOIN sample s USING(sample_id) WHERE "
                        + " AND ".join(where) + " ORDER BY f.uri", params)
    return jsonify([_row(r) for r in rows])


def _tube_hit(r):
    from ..db import format_serial
    return {"type": "tube", "sample_id": r["sample_id"], "lims_number": format_serial(r["serial"]),
            "participant_id": r["participant_id"], "fraction": r["fraction_code"], "material": r["material_code"],
            "status": r["status"], "deleted": bool(r["deleted_at"]),
            "url": request.url_root.rstrip("/") + f"/samples/{r['sample_id']}"}


def _participant_hit(conn, p):
    n_tubes = conn.execute("SELECT count(*) FROM sample WHERE participant_id=? AND deleted_at IS NULL",
                           (p["participant_id"],)).fetchone()[0]
    n_coll = conn.execute("SELECT count(*) FROM collection WHERE participant_id=? AND deleted_at IS NULL",
                          (p["participant_id"],)).fetchone()[0]
    return {"type": "participant", "participant_id": p["participant_id"], "unc_id": f"UNC{p['unc_number']}" if p["unc_number"] else None,
            "cohort": p["cohort_code"], "collections": n_coll, "tubes": n_tubes,
            "url": request.url_root.rstrip("/") + f"/participants/{p['participant_id']}"}


@bp.route("/search")
@api_auth
def search():
    """One lookup for chat tools and scripts. q may be a full sample ID, a LIMS number (with or without leading
    zeros), an IGI patient ID (P101), a UNC ID (UNC316), or part of a sample ID (up to 20 tube matches)."""
    conn = get_db()
    q = (request.args.get("q") or "").strip().upper()
    if not q:
        return jsonify({"error": "q is required"}), 400
    digits = current_app.config["LIMS_NUMBER_DIGITS"]
    kind, hits = "none", []
    row = conn.execute("SELECT * FROM sample WHERE sample_id=?", (q,)).fetchone()
    if row:
        kind, hits = "sample_id", [_tube_hit(row)]
    elif q.isdigit() and len(q) <= digits:
        row = conn.execute("SELECT * FROM sample WHERE serial=?", (int(q),)).fetchone()
        kind, hits = "lims_number", [_tube_hit(row)] if row else []
    elif re.fullmatch(r"P\d{3}", q) or re.fullmatch(r"UNC\d{3}", q):
        col, val = ("participant_id", q) if q.startswith("P") else ("unc_number", q[3:])
        p = conn.execute(f"SELECT * FROM participant WHERE {col}=? AND deleted_at IS NULL", (val,)).fetchone()
        kind, hits = ("participant" if q.startswith("P") else "unc_id"), [_participant_hit(conn, p)] if p else []
    else:
        rows = conn.execute("SELECT * FROM sample WHERE sample_id LIKE ? AND deleted_at IS NULL ORDER BY sample_id LIMIT 21",
                            (f"%{q}%",)).fetchall()
        kind, hits = "partial", [_tube_hit(r) for r in rows[:20]]
        return jsonify({"query": q, "kind": kind, "results": hits, "truncated": len(rows) > 20})
    return jsonify({"query": q, "kind": kind, "results": hits, "truncated": False})
