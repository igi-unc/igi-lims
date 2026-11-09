# IGI LIMS

Chain-of-custody database and web interface for IGI biological specimens.
Flask with SQLite (local) or PostgreSQL (hosted). One row per tube; every tube
records the tube it was made from, so provenance from the collected specimen to
the sequencing file is a chain of parent links.

## Quick start (development)

```bash
cd ~/dev/igi-lims
python3.10 -m venv .venv && .venv/bin/pip install -r requirements.txt   # Python 3.10+ (allotropy)
export FLASK_APP=app
.venv/bin/flask init-db                                  # creates instance/lims.db and loads code lists + rules
.venv/bin/flask create-user admin --name "Your Name" --initials YN --role admin
.venv/bin/flask run --debug                              # http://127.0.0.1:5000
```

Log in, add a participant, register a collection (the specimen as received,
which is not itself a tube) and the tubes made straight from it, then use
**Derive** on any tube to create children (enriched fractions, pellets, cultures,
DNA, RNA, peptide eluates).

### Demonstration data

```bash
.venv/bin/flask seed-demo --user <username>     # records are attributed to this account
```

Adds participant P101 / UNC316, which is the worked example of the nomenclature
document (section 5) tube for tube: the pleural fluid received 29 Sep 2026 and
processed by MF into supernatant, PFMC vials, tumour, immune and CD8 fractions,
pellets, Ken's HMW DNA and RNA, a culture and a peptide eluate, plus the matched
blood collection. It has data files named the way section 6 asks, custody
events, two audited edits (one by a second account) and one correction. Three
smaller participants follow (P102 AML, P103 TNBC, P104 NUT carcinoma, one of
whose collections has no tubes yet), 63 tubes in all. Two synthetic patients
in cohort SY follow: P105 = IGI-SYN-SEQ-01 and P106 = IGI-SYN-SEQ-02 (the
external ID). Each has a tumour and a matched blood collection, 8 tubes, and
the 22 files of its LENS manifest (WES, WGS, bulk RNA, 10x GEX/TCR, ONT, PacBio
HiFi and Kinnex) linked to the extract each library came from. The paths are
the real simulated reads under `raft/inputs` on the cluster; the tube history is
invented. Operator accounts MF and
KEN are created if missing. Re-running skips participants that already exist.
The data is built with the same service functions as the forms, so it obeys the
rules.

### Running on your own laptop

```bash
git clone git@github.com:igi-unc/igi-lims.git && cd igi-lims
python3 --version                                 # 3.9 works; 3.10+ also enables Qubit/NanoDrop import
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export FLASK_APP=app
.venv/bin/flask init-db
.venv/bin/flask create-user you --name "Your Name" --initials YN --role admin
.venv/bin/flask create-user second --name "Second Person" --initials SP --role user
.venv/bin/flask seed-demo --user second
.venv/bin/flask run                               # then open http://127.0.0.1:5000
```

On Windows use `.venv\Scripts\` in place of `.venv/bin/` and `set FLASK_APP=app`.
On Python 3.9 pip skips allotropy, so Import QC accepts TapeStation and Countess
files but not Qubit or NanoDrop until a newer Python is used.
To reuse a database from another machine, copy its `instance/lims.db` (and the
`instance/attachments` folder) into the clone before starting; the server must
not be running while the file is copied.

Alternatively leave the server running on a workstation and tunnel to it:
`ssh -L 5000:127.0.0.1:5000 user@workstation`, then open
http://127.0.0.1:5000 on the laptop.

## What is enforced

* **Sample IDs** follow IGI Sample Nomenclature v2.1 (`ID_SEGMENTS` in
  `config.py`): `IGI-CC-PNNN-UNCNNN-YYMMMDD-SS-FFF-MMM-AA-OO(O)-YYMMMDD`, 51 or 52
  characters, e.g. `IGI-MP-P101-UNC316-26SEP29-PF-TUM-HMD-01-KEN-26OCT06`. IDs
  are composed by the database, never typed. Segments 1-6 come from the
  participant and the collection (received date) and are inherited by every
  derived tube; fraction, material, operator and processing date belong to the
  tube. The aliquot is counted within segments 1-8 and never reused, even after
  a tube is deleted. `GET /api/pattern` returns the anchored regex for pipelines.
  The v2 format (35 characters) is kept at git tag `v2-final`; see *Falling
  back to nomenclature v2* below.
* **Participants** get the next IGI patient ID (P001, P002, ...; never reused;
  admins may enter an existing number) and a required, unique 3-digit UNC
  number. Cohort and UNC number lock once tubes exist.
* **Collections.** The specimen as received (fluid, blood, tissue) is a
  collection record, not a tube: received date, specimen, quantity, container,
  times collected and received, who received it. Tubes made straight from it
  are first-generation tubes with no parent; every tube carries its
  collection_id, so "all tubes from this collection" is one query. A collection
  with no tubes can be deleted.
* **Operators** are account initials: 2 or 3 uppercase letters, unique.
* **LIMS numbers.** Every tube also gets a six-digit number, 000000 to
  999999 (`LIMS_NUMBER_DIGITS`), issued by the LIMS when it is registered and printed under the 2D
  code on its label (the code itself still holds only the sample ID). Numbers
  come from a counter in the database: assigning them updates the counter
  first, which takes the database's write lock, so simultaneous registrations
  queue up and can never share a number; a refused or failed registration
  gives its numbers back, so there are no gaps. A unique index on the column is
  the second safeguard, and the LIMS refuses to go past 999999. Lookups ignore
  extra leading zeros, so labels printed while numbers had nine digits still scan. Tubes that
  existed before numbering were numbered in the order they were created. Type
  a number (with or without leading zeros) in the search box to open its tube.
* **Code lists** (cohort, specimen, fraction, material, status, assay, biobank
  source, site, unit, SOP) live in one table and are edited under *Codes*.
  Codes are retired, never deleted or repurposed.
* **Derivation rules** (*Rules* page) decide which fractions a specimen may
  have, which fraction/material transitions are allowed, and which materials
  can be made straight from a specimen. A processing date before the received
  date (or before the parent's) is also flagged. A violation blocks creation
  and offers an override with a required justification.
* **Changes are flagged, not queued.** Edits, deletes, restores and rule
  overrides apply immediately with the operator's stated reason. The audit log
  and the tube's history flag every row that is not a plain creation; a
  *changes only* filter lists them system-wide, and tubes carry *edited* and
  *rule override* tags. (An earlier two-person approval queue was removed.)
* **Deletes are soft.** The record stays, the aliquot number stays reserved,
  and a tube with active children cannot be deleted.
* **Audit log** of every write (who, when, before, after).
* **Label preview with a 2D barcode.** Every tube page, and the panel that
  opens when you click a tube in the Samples & Participants tree, shows the
  label as it should print: three rows of at most 18 characters broken at
  hyphens (`LABEL_ROWS` in `config.py`) beside a Data Matrix code that encodes
  exactly the sample ID. It is a preview only; printing is not
  wired to a label printer yet.
* **Label values are read-only.** The received date, operator and processing
  date are printed on the label (`LABEL_FIELDS` in `config.py`) and cannot be
  edited once the tube exists. A mistake is fixed with a correction on the tube
  or collection page: the right value and a required reason are recorded
  beside the original and flagged in the audit log, while the label, the ID and
  the stored value stay as printed. A received-date correction is made once on
  the collection and shows on all its tubes. The API returns both values.
* **Occupied slots are flagged.** Registering or moving a tube into a
  freezer/rack/box/position that already holds an Available or In-use tube
  shows a warning naming the occupant; submitting again confirms that the slot
  is shared. Depleted, shipped and destroyed tubes do not occupy their slot.
* **Times follow the received date.** On the collection form the "time
  collected" and "time received" fields take only a time; the date is the
  received date above. An "other date" link switches to a full date-and-time
  input.
* **Custody events** are append-only. **Data files** are linked to the tube
  handed to the facility (usually DNA, HMD, RNA, HMR or PEP) by URI, with a
  required assay and platform, run ID, checksum and pipeline version. The form
  suggests the file name `<sample ID>_<source>_<assay>_<platform>` (for example
  `…-HMD-01-KEN-26OCT06_tumor_DNA_WGS_ONT`); the labels are `ASSAY_LABELS` and
  `PLATFORM_LABELS` in `config.py`.
* **No free text** except Notes. Operator, SOP, freezer, rack, box, position,
  custody parties and purposes, and every metadata vocabulary (kits, lots,
  buffers, media, antibodies, ...) are dropdowns backed by admin-extendable
  lists on the *Codes* page. Server-side checks reject values not in a list.
* **Metadata fields** depend on the tube's fraction and material (kit, purity,
  cell count, concentration, RIN/DIN, capture kit, HLA class, ...). They are
  defined in one table (*Fields* page), appear on the create and edit forms,
  and show on the tube page and in the tree hover panel. A few are required
  (library assay, peptide HLA class).
* **Attachments** (traces, images, reports) are stored under `ATTACHMENT_DIR`
  with an md5, per tube.
* **Import QC** takes one instrument export, shows each row with a suggested
  tube ID (auto-matched when the instrument sample name contains the tube ID),
  and writes the chosen values into the metadata fields with a link back to the
  stored file. Readers: Qubit 4 and NanoDrop One via
  [allotropy](https://github.com/Benchling-Open-Source/allotropy), TapeStation
  XML, Countess 3 CSV (columns from the vendor guide, see
  `docs/countess3_csv_columns.md`). QC imports and manual metadata edits are
  both direct and audited.

Roles: `admin` (everything), `user` (create, derive, edit), `viewer` (read only).

## JSON API

Reads: authenticate with a browser session or the `X-Api-Token` header matching
`LIMS_API_TOKEN` in the environment. `/api/pattern` is public (it holds no data).
Wherever `<key>` appears, it may be a sample ID or a LIMS number (`42` or `000042`).

| Endpoint | Purpose |
|---|---|
| `/api/pattern` | anchored regex for IDs (length varies: 51 or 52) |
| `/api/validate/<id>` | parse an ID into components; says whether it exists |
| `/api/samples?participant=&collection=&root=&material=&status=&prefix=` | list tubes |
| `/api/samples/<id>` | tube with its collection, custody events, files and corrections |
| `/api/samples/<id>/lineage` | ancestors (first generation first) and all descendants |
| `/api/tree/<id>` | nested tree of the collection a tube belongs to |
| `/api/collections/<collection_id>` | collection record, its tree and corrections |
| `/api/search?q=` | one lookup: sample ID, LIMS number, P number, UNC ID or part of an ID; compact results with page links |
| `/api/files?assay=&participant=` | data files joined to tubes |
| `/api/samples/<key>/registry-fields` | prefill for the Slack data librarian: `{found, lims_number, safe: {participant_id, sample_type, analyte, platform, library_type, species}, phi: {sample_id, unc_id, dates, operator}}`. `safe` uses the bot's vocabulary, `null` plus a reason where there is no clean mapping; everything outside `phi` may appear in a Slack channel; unknown tube = 404 `{found: false}` |

### Write-back from the data librarian

`POST /api/samples/<key>/files` records that a registry dataset holds this tube's data, so the
tube page lists it under Data files. It takes a **separate** token, `LIMS_API_WRITE_TOKEN`
(header `X-Api-Token`); while that variable is unset, writes are switched off (403). Neither
the read token nor a browser session can write.

```json
{"registry_id": "igi_p101_...", "instance": "igi", "paths": ["/proj/.../a.bam"],
 "accessioned_by": "U0123", "approved_by": "U0456", "assay_code": "WGS", "platform_code": "ONT"}
```

`assay_code`, `platform_code` and `notes` are optional (codes must be in the LIMS lists). A
retry is harmless: a path already linked to the same tube and registry ID is reported as
`already_linked`, not added again (201 `status: created` if anything was added, 200 `status: exists` if not).
Write responses and their errors never contain a sample ID or a path (both carry PHI): tubes are named by LIMS number. A path already
linked to a different tube is refused (409). Rows are recorded and audited as `bot:<instance>`,
with the Slack user IDs in the notes and the audit entry.

### Sequencing QC

`seq_qc` holds the results of the QC workflow: the data librarian runs it on each accessioned
dataset and posts the scraped outputs to `POST /api/samples/<key>/qc` (write token). One
row per workflow run, tube and file; an entry without `path` is a whole-dataset result (e.g.
MultiQC general statistics). Re-posting the same `workflow_run_id`, tube and path replaces
that row, so a scraper can safely run twice; a new run adds rows beside the old ones.

```json
{"workflow_id": "igi_qc", "workflow_version": "0.1.0", "workflow_run_id": "<librarian run id>",
 "scheduler_job_id": "12345", "registry_id": "igi_...",
 "results": [
   {"path": "/proj/.../x_R1.fastq.gz", "qc_status": "pass", "md5": "<32 hex>",
    "metrics": {"total_reads": 1000000, "total_bases": 150000000, "pct_q30": 93.2, "my_tool_metric": 4}},
   {"qc_status": "warn", "status_reason": "duplication 31% > 25%",
    "metrics": {"mean_coverage": 31.5, "pct_duplication": 31.0}, "report_uri": "/proj/.../multiqc_report.html"}]}
```

* `qc_status`: `pass`, `warn`, `fail` or `not_assessed`. The workflow decides it (thresholds
  live in the workflow, not the LIMS); `status_reason` says why.
* Metrics with their own column: `total_reads`, `total_bases`, `mean_read_length`, `read_n50`,
  `mean_quality`, `pct_q30`, `pct_gc`, `pct_duplication`, `pct_adapter`, `pct_mapped`,
  `mean_coverage`, `pct_target_20x`, `median_insert_size` (percentages are 0-100). Any
  other key is kept as-is in `metrics_json`, so new tools need no schema change.
* `path` must already be a data file of that tube (`POST .../files` first). An `md5` fills an
  empty checksum on the file; one that differs from the recorded checksum is reported in
  `md5_mismatch_file_ids` and flagged on the tube page, and the recorded value is kept.
* The whole request is checked first; any problem returns 400 with a list and writes nothing.
* `GET /api/samples/<key>/qc` (read token) returns the results, newest first. The tube page
  shows them under **Sequencing QC**.
* **quick-qc libraries and checks.** Give each result a `library` (quick-qc's `Run_Name`) and a
  `path` (any one of that library's files, so the result inherits its assay and platform);
  several libraries per tube are fine. `checks` is a list of
  `{"check": "reads.coverage", "status": "PASS|WARN|FAIL|NA", "observed", "expected", "reason"}`,
  one per quick-qc check; `qc_status` also accepts PASS/WARN/FAIL/NA. Put every field of the
  library's `*.metrics.json` in `metrics`: unknown names are kept and can be charted.

**Sequencing QC** (menu) charts the results across libraries: verdicts per check, the
distribution of any numeric metric by assay / platform / participant / cohort, a scatter of
any two metrics, and a worst-first table. Filters narrow by participant, cohort, assay,
platform and workflow; points link to the tube. The page draws plain SVG (no chart library)
and reads `/seq-qc/data.json`. The demo has fictional quick-qc results ("demo values").

## Scanning kit and reagent boxes

On the registration forms (**Add tubes**, **Derive**), **Scan kit / reagent** reads a kit or
reagent box with the camera, a USB scanner or typed text, and fills the metadata below:
the kit (`kit`, `extraction_kit`, `ip_antibody`, `dissociation_method`; set in
`REAGENT_FIELDS`) and its lot. GS1 codes, the usual Data Matrix on reagent boxes, give the
product number (GTIN), lot and expiry; an expired box is flagged. The first scan of a
product asks which list entry it is and remembers it (**Codes › Reagent barcodes**,
`/reagents/`); a lot that is not in its list yet can be added from the scan. Nothing is
saved until the tubes are registered. The demo has four fictional test codes on
`/reagents/`.

## Scanning labels with a camera

**Scan** (menu) opens the device's camera. Point it at the 2D code on a tube
label and the tube's page opens; tick *stay on this page* to scan several
tubes into a list instead. The code holds only the sample ID, never a web
address, so a phone camera on its own shows nothing more than the ID, and the
page it leads to needs a LIMS login. Codes that are not IGI tube IDs (reagent
lots, catalogue numbers) are shown but not followed. USB/Bluetooth barcode
scanners keep working in the search box at the top of every page.

It works in Chrome on Android, Safari on iPad and iPhone, and Chrome or Edge
with a webcam, over https. Browsers without a built-in Data Matrix reader load
a WebAssembly reader (`barcode-detector`, MIT licence, version pinned in
`BARCODE_READER_URL`) from the jsDelivr CDN.

## Label printing (Brady M611)

Labels are printed through a queue, so nobody needs the printer on their own
computer:

1. Anyone who can register tubes clicks **Send ... to the printer**: on the
   page shown right after creating tubes (all the new tubes), on a tube page
   (one label), or on a collection page (tick boxes, "select Available only").
   The job joins the **Print queue** (menu), where it can be cancelled or
   requeued after a failure. Each job also offers a CSV (barcode plus the three
   text rows) for Brady Express Labels or Workstation.
   **Each tube's label is printed once.** When the station confirms a job, its
   labels are recorded as printed (the tube page shows the history). A printed
   tube cannot be queued again, and a tube already waiting cannot be queued
   twice; collection pages grey them out. A deliberate reprint (lost, smudged
   or misprinted label) is done from the tube page with a required reason,
   which is recorded and appears in the audit log's changes-only view.
   Requeueing a job the station took but never confirmed also needs a reason,
   since its labels may already have come out.
2. A **print station** prints the queue in order. It is a browser next to the
   printer, logged in as an account with role `printer` (create it on the
   Users page, or `flask create-user station --role printer --initials PRN ...`).
   That account sees only the station page and the label images it prints; it
   is redirected away from everything else, and its initials never appear as
   an operator.
3. The station reaches the printer in one of two ways (tabs on the page):
   * **Windows printer (USB), the lab setup.** Brady's M611 driver is
     installed, the printer is plugged in by USB and set as the Windows
     default printer, with the M6-17-492 label size and no margins. Chrome is
     started from a shortcut with silent printing switched on:
     `chrome.exe --kiosk-printing --app=https://<lims>/print/station`
     (the station page shows the exact line; put the shortcut in
     `shell:startup`). Leave the driver's orientation and size settings alone
     (Chrome decides them). The station prints an upright 0.5 x 1 in page with
     the label turned a quarter turn left, which is what Brady's M611 driver
     needs (calibration layout C, confirmed on the printer; `LABEL_PRINT_LAYOUT`).
     For another printer or driver, **Calibrate** prints the alignment label in
     all four layouts (A to D) as one four-page print; choose the letter that
     comes out on one label, complete and upright, under *Page layout*.
     **Fine position** (mm, shift right / down) corrects the printer's own
     placement; the default (0.6 mm right, 0.1 mm down, `LABEL_PRINT_OFFSET_MM`)
     comes from an alignment print on the lab's M611. Printed tube labels keep
     a ~0.9 mm white edge so a small remaining offset cannot clip the barcode.
     If a print dialog ever appears (Chrome was not started with the switch),
     the station stops and marks the job failed rather than claiming it
     printed. "Printed" means Windows accepted the job for the printer.
   * **Bluetooth.** Brady's Web SDK (loaded from the jsDelivr CDN, version
     pinned in `BRADY_SDK_URL`) over Web Bluetooth, in Chrome or Edge on a
     computer or Android tablet. Click **Connect printer** once per page load.
     iPads cannot do this in Safari or Chrome.
   Each job prints one label per tube, in aliquot order. A header label before
   each job ("PRINT JOB #12 / FOR JD / 6 LABELS FOLLOW") is off by default;
   set `LIMS_PRINT_JOB_HEADER=1` to bring it back (it can then be skipped per
   job from the tube page). *Test print* prints the nomenclature's example ID.

Labels are drawn for the stock in `LABEL_STOCK` (default M6-17-492,
1.0 x 0.5 in, 300 dpi; override with `LIMS_LABEL_PART`, `LIMS_LABEL_WIDTH_IN`,
`LIMS_LABEL_HEIGHT_IN`, `LIMS_LABEL_DPI`).

## Falling back to nomenclature v2

The v2 code (35-character IDs, 7-letter participant codes, root tubes) is tagged
`v2-final` and kept on the branch `nomenclature-v2`. The two formats use
different database layouts, so a fallback is a code rollback plus a database
rebuild; data entered under v2.1 does not carry over.

* **Vercel demo:** Deployments, open the deployment of commit `4d07295`
  ("Create missing tables on the first request after a deploy"), then
  **Instant Rollback** (or **Promote**). Then run the reset once
  (`curl -H "Authorization: Bearer $CRON_SECRET" https://<app>/cron/demo-reset`).
  To make it permanent, push the branch: `git push origin nomenclature-v2:main --force`
  after agreeing it with whoever else pushes to `main`.
* **Workstation or laptop:** `git checkout v2-final`, then put back the v2
  database backup (`instance/lims.db.bak-…-v2`) or build a fresh one with
  `flask init-db`.

Going forward again is `git checkout main`, then a reset (demo) or the v2.1
database backup.

## Hosting

### Public demo on Vercel + Supabase

See `docs/DEPLOY_VERCEL_SUPABASE.md`. In short: a free Supabase project holds
the Postgres database and a private storage bucket; Vercel runs the Flask app
from this repository; one authenticated request to `/cron/demo-reset` (sent
nightly by Vercel's cron, or by hand) creates the tables and rebuilds the demo
accounts and data, so nothing has to run on a laptop. Secrets live only in the
Vercel dashboard. Set `LIMS_DATABASE_URL` to a `postgresql://` URL and the app
uses Postgres instead of SQLite; nothing else changes.

### On a GCP VM (SQLite)

```bash
export LIMS_SECRET_KEY="$(python3 -c 'import secrets;print(secrets.token_hex(32))')"
export LIMS_DATABASE=/var/lib/igi-lims/lims.db
export LIMS_API_TOKEN="..."            # optional, for pipeline scripts and the Slack bot (read)
export LIMS_API_WRITE_TOKEN="..."      # optional, lets the Slack bot link datasets to tubes
export LIMS_ATTACHMENT_DIR=/mnt/igi-lims-files   # e.g. a gcsfuse mount of the lab bucket
.venv/bin/flask --app app init-db
.venv/bin/gunicorn -w 4 -b 127.0.0.1:8000 app:app
```

Put nginx or the GCP HTTPS load balancer in front; do not expose port 8000
directly. SQLite runs in WAL mode and copes with a couple of dozen users.
Back up by copying `lims.db` while the app is idle, or use `sqlite3 lims.db
".backup /path/backup.db"`.

## Tests

```bash
.venv/bin/python -m pytest -q
```

`tests/test_workflow.py` walks the spec's worked MPE collection (section 5)
through the web interface and checks the back-tracking chain from the ONT
library to the original fluid. `tests/test_demo.py` checks that the demo seed
obeys the rules and vocabularies and that the demo reset works. Set
`LIMS_TEST_DATABASE_URL=postgresql://...` to run the same suite against
PostgreSQL.

## Documentation

`docs/IGI_LIMS_feature_overview.pdf` is an illustrated walkthrough of the v2.1 build. To rebuild
it after UI changes (needs `pip install -r requirements-docs.txt` and a one-time
`playwright install chromium`):

```bash
.venv/bin/python docs/walkthrough_capture.py     # demo DB + annotated screenshots (~2 min)
.venv/bin/python docs/make_feature_overview.py   # lays them out as the PDF
```

## Layout

```
config.py            ID format, runtime settings (database, storage, demo mode)
app.py               entry point (flask / gunicorn)
lims/schema.sql      tables
lims/seed.py         initial code lists and derivation rules
lims/demo.py         `flask seed-demo` / `flask demo-reset`: demonstration data and accounts
lims/db.py           SQLite or PostgreSQL connection; CLI commands
lims/storage.py      attachment bytes: local directory or Supabase Storage bucket
lims/ids.py          compose / parse / validate IDs, issue aliquots
lims/rules.py        derivation rule checks
lims/samples.py      create / update / delete / lineage (service layer)
lims/attributes.py   per-fraction / per-material metadata (definitions + values)
lims/attachments.py  stored files
lims/qc_parsers.py   instrument export readers (Qubit, NanoDrop, TapeStation, Countess)
lims/seed_attributes.py  initial field definitions
lims/views/          Flask blueprints (samples, participants, admin, api, qcimport, demo)
lims/templates/      server-rendered pages
lims/static/tree.js  provenance tree drawing
NOTES.md             open questions and decisions to revisit
```
