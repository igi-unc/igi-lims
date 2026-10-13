# IGI LIMS

Chain-of-custody database and web interface for IGI biological specimens.
SQLite + Flask, no external services. One row per tube; every tube records
the tube it was made from, so provenance from the collected specimen to the
sequencing file is a chain of parent links.

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
* **Two-person agreement.** Overrides, and (by default) every edit or delete of
  a sample record, go to the *Approvals* queue. The requester cannot approve
  their own request. The approver's decision applies the change and the audit
  log records the approval ID. `SAMPLE_EDIT_APPROVAL` in `config.py` relaxes
  this to `provenance` (only parent/ID/delete changes) or `none`.
* **Deletes are soft.** The record stays, the aliquot number stays reserved,
  and a tube with active children cannot be deleted.
* **Audit log** of every write (who, when, before, after).
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
  `docs/countess3_csv_columns.md`). QC imports are direct and audited; manual
  metadata edits go through the approval queue like other edits.

Roles: `admin` (everything), `user` (create, derive, edit, approve), `viewer`
(read only).

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

## Deployment on a GCP VM

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
library to the original fluid.

## Layout

```
config.py            ID format, approval policy, runtime settings
app.py               entry point (flask / gunicorn)
lims/schema.sql      tables
lims/seed.py         initial code lists and derivation rules
lims/ids.py          compose / parse / validate IDs, issue aliquots
lims/rules.py        derivation rule checks
lims/samples.py      create / update / delete / lineage (service layer)
lims/approvals.py    two-person approval queue
lims/attributes.py   per-fraction / per-material metadata (definitions + values)
lims/attachments.py  stored files
lims/qc_parsers.py   instrument export readers (Qubit, NanoDrop, TapeStation, Countess)
lims/seed_attributes.py  initial field definitions
lims/views/          Flask blueprints (samples, participants, approvals, admin, api)
lims/templates/      server-rendered pages
lims/static/tree.js  provenance tree drawing
NOTES.md             open questions and decisions to revisit
```
