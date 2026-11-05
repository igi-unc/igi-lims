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
    elif q.isdigit() and len(q.lstrip("0")) <= digits:
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


# ------------------------------------------------------------------ data-librarian (Slack bot) integration

def _resolve_tube(conn, key):
    """A tube by full sample ID or by LIMS number (the stable key across ID-format changes)."""
    key = (key or "").strip().upper()
    if key.isdigit() and len(key.lstrip("0")) <= current_app.config["LIMS_NUMBER_DIGITS"]:
        return conn.execute("SELECT * FROM sample WHERE serial=?", (int(key),)).fetchone()
    return conn.execute("SELECT * FROM sample WHERE sample_id=?", (key,)).fetchone()


# The registry's vocabulary (igi-data-librarian registry/service.py). Anything without a clean mapping is null.
_ANALYTE = {"DNA": "dna", "HMD": "dna", "CFD": "dna", "RNA": "rna", "HMR": "rna"}
_PLATFORM = {"ILM": "illumina", "ONT": "ont", "PAC": "pacbio"}   # 10X here means a 10x library read on Illumina: no registry term
_LIBRARY = {"WGS": "wgs", "WES": "wes"}                  # RSQ: poly-A vs rRNA depletion is not recorded, so no guess
_NORMAL_SPECIMEN = {"PB": "normal-blood", "NM": "normal-tissue"}


def registry_fields_for(conn, s):
    """Prefill values for a registry accession from one tube, in the registry's own terms (null = no clean mapping),
    with a short reason for every null."""
    from ..db import format_serial
    part = conn.execute("SELECT * FROM participant WHERE participant_id=?", (s["participant_id"],)).fetchone()
    why = {}
    tumor_specimens = set(current_app.config["TUMOR_SPECIMENS"])
    if s["specimen_code"] in tumor_specimens:
        sample_type = "tumor"
    elif s["specimen_code"] == "PB" and s["cohort_code"] == "AM":
        sample_type, why["sample_type"] = None, "blood from a leukemia cohort may be tumour"
    elif s["specimen_code"] in _NORMAL_SPECIMEN:
        sample_type = _NORMAL_SPECIMEN[s["specimen_code"]]
    else:
        sample_type, why["sample_type"] = None, f"no registry term for specimen {s['specimen_code']}"
    analyte = _ANALYTE.get(s["material_code"])
    if analyte is None:
        why["analyte"] = f"material {s['material_code']} is not DNA or RNA"
    files = conn.execute("SELECT DISTINCT assay_code, platform_code FROM data_file WHERE sample_id=? AND deleted_at IS NULL",
                         (s["sample_id"],)).fetchall()
    platforms = {r["platform_code"] for r in files if r["platform_code"]}
    assays = {r["assay_code"] for r in files if r["assay_code"]}
    platform = _PLATFORM.get(next(iter(platforms))) if len(platforms) == 1 else None
    if platform == "ont" and assays == {"SCR"}:
        platform = "10x-ont"                              # single-cell on nanopore = a 10x library read long
    if platform is None:
        why["platform"] = ("no data file with a platform yet" if not platforms else
                           "several platforms on this tube" if len(platforms) > 1 else f"no registry term for {next(iter(platforms))}")
    library_type = _LIBRARY.get(next(iter(assays))) if len(assays) == 1 else None
    if library_type is None:
        why["library_type"] = ("no data file with an assay yet" if not assays else
                               "several assays on this tube" if len(assays) > 1 else f"no registry term for assay {next(iter(assays))}")
    species = "human" if s["cohort_code"] != "DG" else None
    if species is None:
        why["species"] = "canine cohort; the registry has human and mouse only"
    return {"sample_id": s["sample_id"], "lims_number": format_serial(s["serial"]), "participant_id": s["participant_id"],
            "exists": True, "deleted": bool(s["deleted_at"]), "status": s["status"],
            "fields": {"sample_type": sample_type, "analyte": analyte, "platform": platform,
                       "library_type": library_type, "species": species},
            "unmapped_reasons": why}


@bp.route("/samples/<key>/registry-fields")
@api_auth
def registry_fields(key):
    """GET prefill values for the data-librarian accession form. key = sample ID or LIMS number."""
    conn = get_db()
    s = _resolve_tube(conn, key)
    if s is None:
        return jsonify({"query": key, "exists": False}), 404
    return jsonify(registry_fields_for(conn, s))


def api_write_auth(view):
    """Writes need LIMS_API_WRITE_TOKEN (a separate secret from the read token). No token set = writes disabled."""
    @functools.wraps(view)
    def wrapped(**kw):
        token = os.environ.get("LIMS_API_WRITE_TOKEN")
        given = request.headers.get("X-Api-Token") or ""
        if not token:
            return jsonify({"error": "API writes are disabled on this LIMS (no write token configured)"}), 403
        if not hmac.compare_digest(given.encode(), token.encode()):
            return jsonify({"error": "unauthorised"}), 401
        return view(**kw)
    return wrapped


@bp.route("/samples/<key>/files", methods=("POST",))
@api_write_auth
def post_files(key):
    """Record that a registry dataset holds this tube's data. Idempotent on (tube, registry_id, path).
    JSON: {registry_id, instance, paths: [...], accessioned_by, approved_by, assay_code?, platform_code?, notes?}"""
    from .. import audit
    conn = get_db()
    s = _resolve_tube(conn, key)
    if s is None:
        return jsonify({"error": f"no tube {key}"}), 404
    if s["deleted_at"]:
        return jsonify({"error": f"tube {s['sample_id']} is deleted"}), 409
    d = request.get_json(silent=True) or {}
    reg, inst = str(d.get("registry_id") or "").strip(), str(d.get("instance") or "").strip().lower()
    paths = d.get("paths")
    acc, appr = str(d.get("accessioned_by") or "").strip(), str(d.get("approved_by") or "").strip()
    problems = []
    if not reg or len(reg) > 200:
        problems.append("registry_id is required (at most 200 characters)")
    if not re.fullmatch(r"[a-z0-9_-]{1,32}", inst or ""):
        problems.append("instance is required, e.g. 'igi'")
    if not isinstance(paths, list) or not paths or not all(isinstance(x, str) and x.strip() for x in paths) or len(paths) > 100:
        problems.append("paths must be a list of 1 to 100 non-empty strings")
    if not acc or not appr:
        problems.append("accessioned_by and approved_by are required (Slack user IDs)")
    codes = {}
    for field, cat in (("assay_code", "assay"), ("platform_code", "platform")):
        v = str(d.get(field) or "").strip().upper() or None
        if v and not conn.execute("SELECT 1 FROM code_list WHERE category=? AND code=? AND active=1", (cat, v)).fetchone():
            problems.append(f"{field} {v!r} is not in the LIMS {cat} list")
        codes[field] = v
    if problems:
        return jsonify({"error": "invalid request", "problems": problems}), 400
    user = f"bot:{inst}"
    note = f"Registered by the {inst} data librarian; accessioned by {acc}, approved by {appr}."
    if d.get("notes"):
        note += " " + str(d["notes"])[:500]
    created, existing = [], []
    for path in dict.fromkeys(x.strip() for x in paths):
        same = conn.execute("SELECT id FROM data_file WHERE sample_id=? AND registry_id=? AND uri=? AND deleted_at IS NULL",
                            (s["sample_id"], reg, path)).fetchone()
        if same:
            existing.append(same["id"]); continue
        other = conn.execute("SELECT sample_id FROM data_file WHERE uri=? AND deleted_at IS NULL", (path,)).fetchone()
        if other:
            conn.rollback()
            return jsonify({"error": f"{path} is already linked to tube {other['sample_id']}"}), 409
        cur = conn.execute(
            "INSERT INTO data_file(sample_id, uri, assay_code, platform_code, notes, registry_id, registry_instance, recorded_by) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (s["sample_id"], path, codes["assay_code"], codes["platform_code"], note, reg, inst, user))
        created.append(cur.lastrowid)
        audit.log(conn, "data_file", cur.lastrowid, "insert", username=user,
                  after={"sample_id": s["sample_id"], "uri": path, "registry_id": reg, "instance": inst,
                         "accessioned_by": acc, "approved_by": appr})
    conn.commit()
    from ..db import format_serial
    return jsonify({"sample_id": s["sample_id"], "lims_number": format_serial(s["serial"]), "registry_id": reg,
                    "created": len(created), "already_linked": len(existing), "file_ids": created + existing}), \
        (201 if created else 200)


# ------------------------------------------------------------------ sequencing QC (written by the QC workflow)
# Validation and storage live in lims/seqqc.py (shared with the demo seed and the Sequencing QC page).


@bp.route("/samples/<key>/qc")
@api_auth
def get_qc(key):
    """QC results for a tube, newest first, each with the file it is about (null = whole library) and its checks."""
    from .. import seqqc
    conn = get_db()
    s = _resolve_tube(conn, key)
    if s is None:
        return jsonify({"query": key, "exists": False}), 404
    from ..db import format_serial
    return jsonify({"sample_id": s["sample_id"], "lims_number": format_serial(s["serial"]),
                    "results": seqqc.results_for_tube(conn, s["sample_id"])})


@bp.route("/samples/<key>/qc", methods=("POST",))
@api_write_auth
def post_qc(key):
    """Record QC results from one workflow run for one tube. Write token. Re-posting the same
    (workflow_run_id, tube, path, library) replaces that result, so a scraper can safely run twice.
    JSON: {workflow_id, workflow_run_id, workflow_version?, scheduler_job_id?, registry_id?, instance?,
           results: [{path?, library?, qc_status, status_reason?, metrics: {...}, checks: [...]?, md5?, report_uri?}]}"""
    from .. import seqqc
    conn = get_db()
    s = _resolve_tube(conn, key)
    if s is None:
        return jsonify({"error": f"no tube {key}"}), 404
    d = request.get_json(silent=True) or {}
    inst = str(d.get("instance") or "igi").strip().lower()
    if not re.fullmatch(r"[a-z0-9_-]{1,32}", inst):
        return jsonify({"error": "invalid request", "problems": ["instance must look like 'igi'"]}), 400
    try:
        out = seqqc.store(conn, s, d, user=f"bot:{inst}")
    except seqqc.Invalid as e:
        return jsonify({"error": "invalid request", "problems": e.problems}), 400
    conn.commit()
    from ..db import format_serial
    return jsonify({"sample_id": s["sample_id"], "lims_number": format_serial(s["serial"]), **out}), (201 if out["created"] else 200)
