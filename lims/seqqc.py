"""Sequencing QC results (table seq_qc, checks in seq_qc_check), written by the QC workflow via the data librarian.

Nothing here knows a particular workflow's metric names: a handful of common metrics have columns, every other
numeric or text metric is kept in metrics_json, and the Sequencing QC page charts whatever numeric metrics exist.
quick-qc's per-library verdicts per check (PASS / WARN / FAIL / NA) go in seq_qc_check.
"""
import json
import math
import re

from . import audit

STATUSES = ("pass", "warn", "fail", "not_assessed")
_STATUS_ALIASES = {"na": "not_assessed", "n/a": "not_assessed", "not assessed": "not_assessed", "warning": "warn", "failed": "fail",
                   "passed": "pass", "ok": "pass"}
INT_METRICS = ("total_reads", "total_bases")
PCT_METRICS = ("pct_q30", "pct_gc", "pct_duplication", "pct_adapter", "pct_mapped", "pct_target_20x")
REAL_METRICS = ("mean_read_length", "read_n50", "mean_quality", "mean_coverage", "median_insert_size") + PCT_METRICS
METRICS = INT_METRICS + REAL_METRICS
METRIC_LABELS = {"total_reads": "Reads", "total_bases": "Bases", "mean_read_length": "Mean read length (bp)",
                 "read_n50": "Read N50 (bp)", "mean_quality": "Mean base quality", "pct_q30": "Q30 (%)", "pct_gc": "GC (%)",
                 "pct_duplication": "Duplication (%)", "pct_adapter": "Adapter (%)", "pct_mapped": "Mapped (%)",
                 "mean_coverage": "Mean coverage (x)", "pct_target_20x": "Target at 20x (%)", "median_insert_size": "Median insert (bp)"}
_TEXT = ("registry_id", "workflow_version", "scheduler_job_id")
_NAME = re.compile(r"[A-Za-z0-9_.:-]{1,80}")
COLS = ["registry_id", "workflow_id", "workflow_version", "workflow_run_id", "scheduler_job_id", "library_name", "qc_status",
        "status_reason", *METRICS, "md5_observed", "report_uri", "metrics_json"]


class Invalid(ValueError):
    def __init__(self, problems):
        super().__init__("; ".join(problems))
        self.problems = problems


def norm_status(v):
    v = str(v or "").strip().lower()
    return _STATUS_ALIASES.get(v, v)


def _short(v, n):
    return str(v).strip()[:n] if v not in (None, "") else None


def _check_result(conn, s, r, problems, i):
    where = f"results[{i}]"
    if not isinstance(r, dict):
        problems.append(f"{where} must be an object"); return None
    status = norm_status(r.get("qc_status"))
    if status not in STATUSES:
        problems.append(f"{where}.qc_status must be one of pass, warn, fail, not_assessed (PASS/WARN/FAIL/NA accepted)")
    out = {"qc_status": status, "status_reason": _short(r.get("status_reason"), 500), "report_uri": _short(r.get("report_uri"), 1000),
           "library_name": _short(r.get("library"), 200), "data_file_id": None, "uri": None}
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
        if k in METRICS:
            if v is None:
                out[k] = None; continue
            if isinstance(v, bool) or not isinstance(v, (int, float)) or (isinstance(v, float) and not math.isfinite(v)) or v < 0:
                problems.append(f"{where}.metrics.{k} must be a non-negative number"); continue
            if k in PCT_METRICS and v > 100:
                problems.append(f"{where}.metrics.{k} is a percentage (0-100)"); continue
            if k in INT_METRICS and v != int(v):
                problems.append(f"{where}.metrics.{k} must be a whole number"); continue
            out[k] = int(v) if k in INT_METRICS else float(v)
        elif re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", str(k)) and (v is None or isinstance(v, (str, int, float, bool))):
            if isinstance(v, float) and not math.isfinite(v):
                problems.append(f"{where}.metrics.{k} must be a finite number"); continue
            extra[k] = v[:500] if isinstance(v, str) else v
        else:
            problems.append(f"{where}.metrics.{k}: extra metrics need a short name and a plain value")
    out["metrics_json"] = json.dumps(extra, sort_keys=True) if extra else None
    if len(out["metrics_json"] or "") > 20000:
        problems.append(f"{where}.metrics is too large")
    checks = r.get("checks") or []
    if not isinstance(checks, list) or len(checks) > 100:
        problems.append(f"{where}.checks must be a list of at most 100 entries"); checks = []
    out["checks"], names = [], set()
    for j, c in enumerate(checks):
        cw = f"{where}.checks[{j}]"
        if not isinstance(c, dict) or not _NAME.fullmatch(str(c.get("check") or "")):
            problems.append(f"{cw}.check needs a name such as reads.coverage"); continue
        st = norm_status(c.get("status"))
        if st not in STATUSES:
            problems.append(f"{cw}.status must be PASS, WARN, FAIL or NA"); continue
        if c["check"] in names:
            problems.append(f"{cw}: {c['check']} appears twice"); continue
        names.add(c["check"])
        out["checks"].append({"check_name": c["check"], "status": st, "observed": _short(c.get("observed"), 300),
                              "expected": _short(c.get("expected"), 300), "reason": _short(c.get("reason"), 500)})
    return out


def store(conn, s, d, user):
    """Validate the whole request, then insert or replace one row per result (and its checks). Raises Invalid."""
    problems = []
    wf, run = str(d.get("workflow_id") or "").strip(), str(d.get("workflow_run_id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", wf):
        problems.append("workflow_id is required (letters, digits, _ . : -)")
    if not run or len(run) > 200:
        problems.append("workflow_run_id is required (at most 200 characters)")
    common = {k: _short(d.get(k), 200) for k in _TEXT}
    results = d.get("results")
    if not isinstance(results, list) or not 1 <= len(results) <= 200:
        problems.append("results must be a list of 1 to 200 entries")
        results = []
    checked = [_check_result(conn, s, r, problems, i) for i, r in enumerate(results)]
    keys = [(c["data_file_id"], c["library_name"]) for c in checked if c]
    if len(keys) != len(set(keys)):
        problems.append("results repeats a path/library pair (two entries would describe the same thing)")
    if problems:
        raise Invalid(problems)
    created = updated = 0
    mismatches = []
    for c in checked:
        vals = {k: c.get(k) for k in COLS}
        vals.update({**common, "workflow_id": wf, "workflow_run_id": run})
        vals = [vals[k] for k in COLS]
        where = ["workflow_run_id=?", "sample_id=?"]
        args = [run, s["sample_id"]]
        for col in ("data_file_id", "library_name"):
            if c[col] is None:
                where.append(f"{col} IS NULL")
            else:
                where.append(f"{col}=?"); args.append(c[col])
        old = conn.execute("SELECT * FROM seq_qc WHERE " + " AND ".join(where), args).fetchone()
        if old:
            qid = old["id"]
            conn.execute(f"UPDATE seq_qc SET {', '.join(k + '=?' for k in COLS)}, recorded_by=?, "
                         "recorded_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?", (*vals, user, qid))
            conn.execute("DELETE FROM seq_qc_check WHERE qc_id=?", (qid,))
            audit.log(conn, "seq_qc", qid, "update", username=user, before={"qc_status": old["qc_status"], "workflow_run_id": run},
                      after={"qc_status": c["qc_status"], "workflow_run_id": run}, reason="QC re-posted by the workflow")
            updated += 1
        else:
            cur = conn.execute(f"INSERT INTO seq_qc(sample_id, data_file_id, {', '.join(COLS)}, recorded_by) "
                               f"VALUES (?, ?, {', '.join('?' for _ in COLS)}, ?)", (s["sample_id"], c["data_file_id"], *vals, user))
            qid = cur.lastrowid
            audit.log(conn, "seq_qc", qid, "insert", username=user,
                      after={"sample_id": s["sample_id"], "uri": c["uri"], "library": c["library_name"], "workflow_id": wf,
                             "workflow_run_id": run, "qc_status": c["qc_status"], "checks": len(c["checks"])})
            created += 1
        for ch in c["checks"]:
            conn.execute("INSERT INTO seq_qc_check(qc_id, check_name, status, observed, expected, reason) VALUES (?,?,?,?,?,?)",
                         (qid, ch["check_name"], ch["status"], ch["observed"], ch["expected"], ch["reason"]))
        md5 = c.get("md5_observed")
        if md5 and c["data_file_id"] is not None:
            if not c.get("recorded_md5"):
                conn.execute("UPDATE data_file SET checksum_md5=? WHERE id=?", (md5, c["data_file_id"]))
                audit.log(conn, "data_file", c["data_file_id"], "update", username=user, before={"checksum_md5": None},
                          after={"checksum_md5": md5}, reason=f"md5 computed by QC run {run}")
            elif c["recorded_md5"].lower() != md5:
                mismatches.append(c["uri"])
    return {"workflow_run_id": run, "created": created, "updated": updated, "md5_mismatches": mismatches}


def _checks_by_qc(conn, ids):
    out = {}
    if not ids:
        return out
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        for r in conn.execute(f"SELECT * FROM seq_qc_check WHERE qc_id IN ({','.join('?' for _ in part)}) ORDER BY id", part):
            out.setdefault(r["qc_id"], []).append({"check": r["check_name"], "status": r["status"], "observed": r["observed"],
                                                    "expected": r["expected"], "reason": r["reason"]})
    return out


def _as_dict(r, checks):
    d = {k: r[k] for k in r.keys()}
    d["metrics"] = json.loads(d.pop("metrics_json") or "{}")
    d["checks"] = checks.get(r["id"], [])
    return d


def results_for_tube(conn, sample_id):
    rows = conn.execute("SELECT q.*, f.uri, f.checksum_md5 FROM seq_qc q LEFT JOIN data_file f ON f.id = q.data_file_id "
                        "WHERE q.sample_id=? ORDER BY q.recorded_at DESC, q.id DESC", (sample_id,)).fetchall()
    checks = _checks_by_qc(conn, [r["id"] for r in rows])
    return [_as_dict(r, checks) for r in rows]


def chart_rows(conn):
    """Every QC result with its tube's context, for the Sequencing QC page. Numeric metrics are flattened into one
    dict (columns + numeric extras); `latest` marks the newest run per (tube, file, library, workflow)."""
    rows = conn.execute(
        "SELECT q.*, f.uri, f.assay_code AS f_assay, f.platform_code AS f_platform, s.participant_id, s.cohort_code, "
        "s.material_code, s.fraction_code, s.specimen_code, s.serial FROM seq_qc q JOIN sample s ON s.sample_id = q.sample_id "
        "LEFT JOIN data_file f ON f.id = q.data_file_id WHERE s.deleted_at IS NULL ORDER BY q.recorded_at, q.id").fetchall()
    checks = _checks_by_qc(conn, [r["id"] for r in rows])
    # a whole-library row has no file: take assay/platform from the tube's files when they agree
    tube_ap = {}
    for t in conn.execute("SELECT sample_id, assay_code, platform_code FROM data_file WHERE deleted_at IS NULL"):
        tube_ap.setdefault(t["sample_id"], set()).add((t["assay_code"], t["platform_code"]))
    out, newest = [], {}
    from .db import format_serial
    for r in rows:
        m = {k: r[k] for k in METRICS if r[k] is not None}
        for k, v in json.loads(r["metrics_json"] or "{}").items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                m[k] = v
        assay, platform = r["f_assay"], r["f_platform"]
        if assay is None and platform is None and len(tube_ap.get(r["sample_id"], ())) == 1:
            assay, platform = next(iter(tube_ap[r["sample_id"]]))
        key = (r["sample_id"], r["data_file_id"], r["library_name"], r["workflow_id"])
        newest[key] = len(out)
        out.append({"id": r["id"], "sample_id": r["sample_id"], "lims_number": format_serial(r["serial"]),
                    "participant": r["participant_id"], "cohort": r["cohort_code"], "material": r["material_code"],
                    "assay": assay or "?", "platform": platform or "?", "library": r["library_name"] or "",
                    "file": (r["uri"] or "").rsplit("/", 1)[-1], "workflow": r["workflow_id"], "version": r["workflow_version"] or "",
                    "run": r["workflow_run_id"], "recorded_at": r["recorded_at"], "status": r["qc_status"],
                    "reason": r["status_reason"] or "", "metrics": m,
                    "checks": {c["check"]: c["status"] for c in checks.get(r["id"], [])}, "latest": False})
    for i in newest.values():
        out[i]["latest"] = True
    return out
