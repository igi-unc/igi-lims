#!/usr/bin/env python3
"""Upload one quick-qc run's results to the IGI LIMS (POST /api/samples/<LIMS number>/qc).

Standard library only, so the Slack data librarian (or anyone) can run or import it as is.

    IGI_LIMS_WRITE_TOKEN=... python3 post_quick_qc.py \\
        --report-dir <raft outputs>/qc/qc_report --run-id <librarian run ID> --map runs.tsv [--dry-run]

runs.tsv (tab-separated, header row): Run_Name, lims_number, path
  - lims_number: the tube the library came from (the registry stores it per dataset)
  - path: any one of that library's files, already linked to the tube with POST /api/samples/<n>/files
Libraries in the report that are not in runs.tsv are skipped (not IGI tubes, or not accessioned).
runs.tsv holds PHI (file names start with the full sample ID): keep it with the bot or in a temp directory, never in
a git repository. Load the token from the bot's .env rather than typing it on a command line (shell history).

quick-qc's column names are taken from its documentation (~/quick-qc-outputs.md); the candidates below cover
the likely spellings. Re-running is safe: the LIMS replaces a result posted for the same run, tube and library.
The LIMS's responses contain no PHI (tubes are named by LIMS number), so they may be logged.
"""
import argparse
import csv
import glob
import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict

LIMS_URL = os.environ.get("IGI_LIMS_URL", "https://igi-lims.vercel.app")
RUN = ("Run_Name", "run_name", "Run")
STATUS = ("status", "Status", "overall_status", "Overall_Status", "verdict")
CHECK = ("check", "Check", "check_name")
OBSERVED, EXPECTED, REASON = ("observed", "Observed"), ("expected", "Expected"), ("reason", "Reason")


def _get(row, names):
    for n in names:
        if n in row and row[n] not in (None, ""):
            return row[n]
    return None


def _tsv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _metrics(report_dir, run):
    """The library's flat metrics.json (about 60 fields); plain values only."""
    for p in sorted(glob.glob(os.path.join(report_dir, "*", "*", run, "qc", "*.metrics.json"))):
        with open(p) as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if v is None or isinstance(v, (int, float, str, bool))}
    return {}


def build_requests(report_dir, run_id, mapping, version=None):
    """[(lims_number, body)], one POST per tube with one result per library on it."""
    checks = defaultdict(list)
    checks_file = os.path.join(report_dir, "qc_checks.tsv")
    if os.path.exists(checks_file):
        for r in _tsv(checks_file):
            run, name = _get(r, RUN), _get(r, CHECK)
            if run and name:
                checks[run].append({"check": name, "status": _get(r, STATUS) or "NA", "observed": _get(r, OBSERVED),
                                    "expected": _get(r, EXPECTED), "reason": _get(r, REASON)})
    by_tube = defaultdict(list)
    for r in _tsv(os.path.join(report_dir, "qc_samples.tsv")):
        run = _get(r, RUN)
        if run not in mapping:
            continue
        tube, path = mapping[run]
        by_tube[tube].append({"library": run, "path": path, "qc_status": _get(r, STATUS) or "NA",
                              "metrics": _metrics(report_dir, run), "checks": checks.get(run, [])})
    body = {"workflow_id": "quick-qc", "workflow_run_id": run_id, "instance": "igi"}
    if version:
        body["workflow_version"] = version
    return [(tube, {**body, "results": results}) for tube, results in by_tube.items()]


def post(lims_number, body, token, base=LIMS_URL):
    req = urllib.request.Request(f"{base}/api/samples/{lims_number}/qc", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Api-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def read_map(path):
    return {r["Run_Name"]: (r["lims_number"], r["path"]) for r in _tsv(path)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--report-dir", required=True)
    ap.add_argument("--run-id", required=True, help="the librarian's workflow run ID")
    ap.add_argument("--map", required=True, help="TSV: Run_Name, lims_number, path")
    ap.add_argument("--version", default=None, help="quick-qc version, e.g. 1.0.0-dev")
    ap.add_argument("--dry-run", action="store_true", help="print the requests, send nothing")
    a = ap.parse_args(argv)
    reqs = build_requests(a.report_dir, a.run_id, read_map(a.map), a.version)
    if a.dry_run:
        for tube, body in reqs:
            print(tube, json.dumps(body)[:300])
        return 0
    token = os.environ.get("IGI_LIMS_WRITE_TOKEN")
    if not token:
        sys.exit("IGI_LIMS_WRITE_TOKEN is not set")
    failed = 0
    for tube, body in reqs:
        status, resp = post(tube, body, token)
        ok = status in (200, 201)
        failed += not ok
        print(f"{tube}: {status} " + (f"created {resp.get('created')}, updated {resp.get('updated')}" if ok else json.dumps(resp)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
