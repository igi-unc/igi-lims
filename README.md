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
whose collections has no tubes yet), 63 tubes in all. Operator accounts MF and
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

## JSON API (read only)

Authenticate with a browser session or the `X-Api-Token` header matching
`LIMS_API_TOKEN` in the environment.

| Endpoint | Purpose |
|---|---|
| `/api/pattern` | anchored regex for IDs (length varies: 51 or 52) |
| `/api/validate/<id>` | parse an ID into components; says whether it exists |
| `/api/samples?participant=&collection=&root=&material=&status=&prefix=` | list tubes |
| `/api/samples/<id>` | tube with its collection, custody events, files and corrections |
| `/api/samples/<id>/lineage` | ancestors (first generation first) and all descendants |
| `/api/tree/<id>` | nested tree of the collection a tube belongs to |
| `/api/collections/<collection_id>` | collection record, its tree and corrections |
| `/api/files?assay=&participant=` | data files joined to tubes |

## Label printing (Brady M611)

Labels are printed through a queue, so nobody needs the printer on their own
computer:

1. Anyone who can register tubes clicks **Send ... to the printer**: on the
   page shown right after creating tubes (all the new tubes), on a tube page
   (one label), or on a collection page (tick boxes, "select Available only").
   The job joins the **Print queue** (menu), where it can be cancelled,
   requeued after a failure, or printed again. Each job also offers a CSV
   (barcode plus the three text rows) for Brady Express Labels or Workstation.
2. A **print station** prints the queue in order. It is any device next to the
   printer logged in as an account with role `printer` (create it on the Users
   page, or `flask create-user station --role printer --initials PRN ...`).
   That account sees only the station page and the label images it prints; it
   is redirected away from everything else, and its initials never appear as
   an operator.
3. On the station, open the LIMS (it lands on *Print station*), click
   **Connect printer** and pick the M611. From then on it checks every few
   seconds and prints each job: a header label ("PRINT JOB #12 / FOR JD /
   6 LABELS FOLLOW") and one label per tube, in aliquot order. Reconnect after
   a reload or a restart (Bluetooth needs one click per page load). *Test
   print* prints the nomenclature's example ID for checking alignment.

The station uses Brady's Web SDK (loaded from the jsDelivr CDN, version
pinned in `BRADY_SDK_URL`), which talks to the printer over Web Bluetooth.
That works in Chrome or Edge on a computer or Android tablet. **On an iPad,
Safari and Chrome cannot use Bluetooth from a web page; use the free Bluefy
browser.** The page must be served over HTTPS (Vercel is; `localhost` also
counts). Labels are drawn for the stock in `LABEL_STOCK` (default
M6-17-492, 1.0 x 0.5 in, 300 dpi; override with `LIMS_LABEL_PART`,
`LIMS_LABEL_WIDTH_IN`, `LIMS_LABEL_HEIGHT_IN`, `LIMS_LABEL_DPI`); the station
warns when the printer reports different labels loaded.

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
export LIMS_API_TOKEN="..."            # optional, for pipeline scripts
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
