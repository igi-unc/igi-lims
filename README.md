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

Log in, add participants, register a collected specimen (root tube), then use
**Derive** on any tube to create children (cryo tubes, pellets, DNA, libraries).

### Demonstration data

```bash
.venv/bin/flask seed-demo --user <username>     # records are attributed to this account
```

Adds one malignant-pleural-effusion participant (site ID MPE-021) with three
collections processed through to libraries, a peptide eluate and data files:
43 tubes, custody events and two audited edits (one by a second account) so
the flagged history has something to show. It also fills the empty lists (SOPs,
freezers, racks, boxes, lots, indexes, submissions, instruments) with a few
plausible entries. Three smaller participants follow in the other cohorts
(AML-007: marrow and blood, with a vial shipped and one destroyed; TNBC-103:
core biopsy as FFPE and OCT blocks plus blood; NUT-002: snap-frozen lymph node
through to a nanopore library, blood not yet processed), 75 tubes in all.
Re-running skips the participants that already exist. The data is built with
the same service functions as the forms, so it obeys the rules.

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

* **Sample IDs** follow `config.py` (`ID_SEGMENTS`), currently the 35-character
  `IGI-CC-PPPPPPP-YYMMDD-SS-FFF-MMM-AA`. IDs are composed by the database, never
  typed. The aliquot number is issued per prefix and never reused, even after a
  tube is deleted. `GET /api/pattern` returns the anchored regex for pipelines.
* **Code lists** (cohort, specimen, fraction, material, status, assay, biobank
  source, site, unit, SOP) live in one table and are edited under *Codes*.
  Codes are retired, never deleted or repurposed.
* **Derivation rules** (*Rules* page) decide which fractions a specimen may
  have, which fraction/material transitions are allowed, and what a root tube
  may arrive as. A violation blocks creation and offers *Request override*.
* **Changes are flagged, not queued.** Edits, deletes, restores and rule
  overrides apply immediately with the operator's stated reason. The audit log
  and the tube's history flag every row that is not a plain creation; a
  *changes only* filter lists them system-wide, and tubes carry *edited* and
  *rule override* tags. (An earlier two-person approval queue was removed.)
* **Deletes are soft.** The record stays, the aliquot number stays reserved,
  and a tube with active children cannot be deleted.
* **Audit log** of every write (who, when, before, after).
* **Label values are read-only.** Fields printed on the tube label (today the
  collection date and the operator; `LABEL_FIELDS` in `config.py`) cannot be
  edited once the tube exists. A mistake is fixed with *Correct a value printed
  on the label* on the tube page: the right value and a required reason are
  recorded beside the original and flagged in the audit log, while the label,
  the ID and the stored value stay as printed. A collection-date correction
  applies to every tube of that collection. The API returns both values.
* **Occupied slots are flagged.** Registering or moving a tube into a
  freezer/rack/box/position that already holds an Available or In-use tube
  shows a warning naming the occupant; submitting again confirms that the slot
  is shared. Depleted, shipped and destroyed tubes do not occupy their slot.
* **Base and derived tubes in one step.** When a base specimen was processed
  the moment it arrived (blood straight into PBMCs), the derived-specimen
  picker offers a combined form: collection date, specimen and quantity for
  the base tube, everything else for the derived tubes. The base tube takes
  its time, operator, SOP and biobank source from the derived tubes, is marked
  Depleted by default, and its creation is flagged in the audit log.
* **Times follow the collection date.** On the base-specimen form the
  "time collected" and "time received" fields take only a time; the date is
  the collection date above. An "other date" link switches to a full
  date-and-time input for a specimen received on a later day.
* **Custody events** are append-only. **Data files** are linked to the tube
  that was sequenced or run (usually LIB or PEP) by URI, with assay, run ID,
  checksum and pipeline version.
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
| `/api/pattern` | anchored regex and fixed length for IDs |
| `/api/validate/<id>` | parse an ID into components; says whether it exists |
| `/api/samples?participant=&root=&material=&status=&prefix=` | list tubes |
| `/api/samples/<id>` | tube with custody events and files |
| `/api/samples/<id>/lineage` | ancestors (root first) and all descendants |
| `/api/tree/<root_id>` | nested tree for a collection |
| `/api/files?assay=&participant=` | data files joined to tubes |

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

`docs/IGI_LIMS_feature_overview.pdf` is an illustrated walkthrough. To rebuild
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
