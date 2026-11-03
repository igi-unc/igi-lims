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


# ------------------------------------------------------------------ data-librarian (Slack bot) integration

def _resolve_tube(conn, key):
    """A tube by full sample ID or by LIMS number (the stable key across ID-format changes)."""
    key = (key or "").strip().upper()
    if key.isdigit() and len(key) <= current_app.config["LIMS_NUMBER_DIGITS"]:
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

QC_STATUSES = ("pass", "warn", "fail", "not_assessed")
QC_INT_METRICS = ("total_reads", "total_bases")
QC_PCT_METRICS = ("pct_q30", "pct_gc", "pct_duplication", "pct_adapter", "pct_mapped", "pct_target_20x")
QC_REAL_METRICS = ("mean_read_length", "read_n50", "mean_quality", "mean_coverage", "median_insert_size") + QC_PCT_METRICS
QC_METRICS = QC_INT_METRICS + QC_REAL_METRICS
_QC_TEXT = ("registry_id", "workflow_version", "scheduler_job_id")


def _qc_row(r):
    import json
    d = _row(r)
    d["metrics"] = json.loads(d.pop("metrics_json") or "{}")
    d.pop("lims_number", None)
    return d


@bp.route("/samples/<key>/qc")
@api_auth
def get_qc(key):
    """QC results for a tube, newest first, each with the file it is about (null = whole dataset)."""
    conn = get_db()
    s = _resolve_tube(conn, key)
    if s is None:
        return jsonify({"query": key, "exists": False}), 404
    rows = conn.execute("SELECT q.*, f.uri FROM seq_qc q LEFT JOIN data_file f ON f.id = q.data_file_id "
                        "WHERE q.sample_id=? ORDER BY q.recorded_at DESC, q.id DESC", (s["sample_id"],)).fetchall()
    from ..db import format_serial
    return jsonify({"sample_id": s["sample_id"], "lims_number": format_serial(s["serial"]), "results": [_qc_row(r) for r in rows]})


def _check_qc_result(conn, s, r, problems, i):
    """Validate one entry of `results`; returns the column values or None."""
    import json, math
    where = f"results[{i}]"
    if not isinstance(r, dict):
        problems.append(f"{where} must be an object"); return None
    status = str(r.get("qc_status") or "").strip().lower()
    if status not in QC_STATUSES:
        problems.append(f"{where}.qc_status must be one of {', '.join(QC_STATUSES)}")
    out = {"qc_status": status, "status_reason": (str(r["status_reason"])[:500] if r.get("status_reason") else None),
           "report_uri": (str(r["report_uri"])[:1000] if r.get("report_uri") else None), "data_file_id": None, "uri": None}
    md5 = str(r.get("md5") or "").strip().lower() or None
    if md5 and not re.fullmatch(r"[0-9a-f]{32}", md5):
        problems.append(f"{where}.md5 is not a 32-character hex md5")
    out["md5_observed"] = md5
    if r.get("path"):
        f = conn.execute("SELECT id, uri, checksum_md5 FROM data_file WHERE sample_id=? AND uri=? AND deleted_at IS NULL",
                         (s["sample_id"], str(r["path"]).strip())).fetchone()
        if f is None:
            problems.append(f"{where}.path is not a data file of tube {s['sample_id']} (link it first with POST .../files)")
        else:
            out["data_file_id"], out["uri"], out["recorded_md5"] = f["id"], f["uri"], f["checksum_md5"]
    elif md5:
        problems.append(f"{where}.md5 needs a path")
    metrics = r.get("metrics") or {}
    if not isinstance(metrics, dict):
        problems.append(f"{where}.metrics must be an object"); metrics = {}
    extra = {}
    for k, v in metrics.items():
        if k in QC_METRICS:
            if v is None:
                out[k] = None; continue
            if isinstance(v, bool) or not isinstance(v, (int, float)) or (isinstance(v, float) and not math.isfinite(v)) or v < 0:
                problems.append(f"{where}.metrics.{k} must be a non-negative number"); continue
            if k in QC_PCT_METRICS and v > 100:
                problems.append(f"{where}.metrics.{k} is a percentage (0-100)"); continue
            if k in QC_INT_METRICS and v != int(v):
                problems.append(f"{where}.metrics.{k} must be a whole number"); continue
            out[k] = int(v) if k in QC_INT_METRICS else float(v)
        elif re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", str(k)) and (v is None or isinstance(v, (str, int, float, bool))):
            extra[k] = v[:500] if isinstance(v, str) else v
        else:
            problems.append(f"{where}.metrics.{k}: extra metrics need a short name and a plain value")
    out["metrics_json"] = json.dumps(extra, sort_keys=True) if extra else None
    if len(out["metrics_json"] or "") > 20000:
        problems.append(f"{where}.metrics is too large")
    return out


@bp.route("/samples/<key>/qc", methods=("POST",))
@api_write_auth
def post_qc(key):
    """Record QC results from one workflow run for one tube. Write token. Re-posting the same
    (workflow_run_id, tube, path) replaces that result, so a scraper can safely run twice.
    JSON: {workflow_id, workflow_run_id, workflow_version?, scheduler_job_id?, registry_id?, instance?,
           results: [{path?, qc_status, status_reason?, metrics: {...}, md5?, report_uri?}, ...]}"""
    from .. import audit
    conn = get_db()
    s = _resolve_tube(conn, key)
    if s is None:
        return jsonify({"error": f"no tube {key}"}), 404
    d = request.get_json(silent=True) or {}
    problems = []
    wf, run = str(d.get("workflow_id") or "").strip(), str(d.get("workflow_run_id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", wf):
        problems.append("workflow_id is required (letters, digits, _ . : -)")
    if not run or len(run) > 200:
        problems.append("workflow_run_id is required (at most 200 characters)")
    inst = str(d.get("instance") or "igi").strip().lower()
    if not re.fullmatch(r"[a-z0-9_-]{1,32}", inst):
        problems.append("instance must look like 'igi'")
    common = {k: (str(d[k]).strip()[:200] if d.get(k) else None) for k in _QC_TEXT}
    results = d.get("results")
    if not isinstance(results, list) or not 1 <= len(results) <= 200:
        problems.append("results must be a list of 1 to 200 entries")
        results = []
    checked = [_check_qc_result(conn, s, r, problems, i) for i, r in enumerate(results)]
    keys = [c["data_file_id"] for c in checked if c]
    if len(keys) != len(set(keys)):
        problems.append("results repeats a path (or has two whole-dataset entries)")
    if problems:
        return jsonify({"error": "invalid request", "problems": problems}), 400
    user = f"bot:{inst}"
    cols = ["registry_id", "workflow_id", "workflow_version", "workflow_run_id", "scheduler_job_id", "qc_status", "status_reason",
            *QC_METRICS, "md5_observed", "report_uri", "metrics_json"]
    created = updated = 0
    mismatches = []
    for c in checked:
        vals = {**common, "workflow_id": wf, "workflow_run_id": run, **{k: c.get(k) for k in cols if k in c}}
        vals = {k: vals.get(k) for k in cols}
        old = conn.execute("SELECT * FROM seq_qc WHERE workflow_run_id=? AND sample_id=? AND "
                           + ("data_file_id=?" if c["data_file_id"] is not None else "data_file_id IS NULL"),
                           (run, s["sample_id"]) + ((c["data_file_id"],) if c["data_file_id"] is not None else ())).fetchone()
        if old:
            conn.execute(f"UPDATE seq_qc SET {', '.join(k + '=?' for k in cols)}, recorded_by=?, "
                         "recorded_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?", (*vals.values(), user, old["id"]))
            audit.log(conn, "seq_qc", old["id"], "update", username=user, before={k: old[k] for k in ("qc_status", "workflow_run_id")},
                      after={"qc_status": vals["qc_status"], "workflow_run_id": run}, reason="QC re-posted by the workflow")
            updated += 1
        else:
            cur = conn.execute(f"INSERT INTO seq_qc(sample_id, data_file_id, {', '.join(cols)}, recorded_by) "
                               f"VALUES (?, ?, {', '.join('?' for _ in cols)}, ?)", (s["sample_id"], c["data_file_id"], *vals.values(), user))
            audit.log(conn, "seq_qc", cur.lastrowid, "insert", username=user,
                      after={"sample_id": s["sample_id"], "uri": c["uri"], "workflow_id": wf, "workflow_run_id": run, "qc_status": vals["qc_status"]})
            created += 1
        md5 = c.get("md5_observed")
        if md5 and c["data_file_id"] is not None:
            if not c.get("recorded_md5"):
                conn.execute("UPDATE data_file SET checksum_md5=? WHERE id=?", (md5, c["data_file_id"]))
                audit.log(conn, "data_file", c["data_file_id"], "update", username=user, before={"checksum_md5": None},
                          after={"checksum_md5": md5}, reason=f"md5 computed by QC run {run}")
            elif c["recorded_md5"].lower() != md5:
                mismatches.append(c["uri"])
    conn.commit()
    from ..db import format_serial
    return jsonify({"sample_id": s["sample_id"], "lims_number": format_serial(s["serial"]), "workflow_run_id": run,
                    "created": created, "updated": updated, "md5_mismatches": mismatches}), (201 if created else 200)
