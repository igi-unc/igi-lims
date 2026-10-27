# NOTES – open questions and decisions to revisit

## Open questions (for Steven)

1. **Vocabulary oddities in the specimen list.** `NTC` (Normal T cell) and
   `NRM` (Normal tissue) sit in the *specimen* list but read like fractions or
   sources. Are these healthy-donor sources, patient-matched normals, or both?
   Should NTC be `PB` specimen + `TTC` fraction instead? Also: `IMM` says
   "e.g. CD45+ enriched, buffy coat" but buffy coat already has its own fraction
   code `BFC`. Which one wins for a buffy coat tube? Note that `NTC` and `NRM`
   are three characters while the ID format reserves two for specimen
   (`[A-Z]{2}`), so they currently cannot appear in an ID. Either shorten them
   or widen the segment in `config.py`.
2. **ID format is still in flight.** The build uses the 35-character validated
   pattern from the spec (`IGI-CC-PPPPPPP-YYMMDD-SS-FFF-MMM-AA`). The later
   field table hints at `P101-UNC316`, `26SEP29` dates, operator initials and a
   processing date inside the ID. Those are a `config.py` edit (plus a column
   if a new segment is added). Operator and processing date are stored in the
   database per the spec's own rule ("processing dates go in the database").
3. **Approval queue removed (2026-10-14).** After the demo Steven asked to
   drop two-person approval and rely on the audit log. Edits, deletes and rule
   overrides are now direct, carry an optional (override: required) reason,
   and are flagged in the audit log, on the tube page and in a changes-only
   audit view. Old databases keep their `approval_request` table unused.
4. **Participant code generation.** Generated codes use A–Z minus I and O
   (7 letters). Confirm this against the IRB/HIPAA review of label contents,
   and whether codes should instead be issued by a central IGI registry.
5. **Rule seed is a first guess.** The allowed transitions in `lims/seed.py`
   were inferred from the worked example; review them on the *Rules* page.
   Notably: `PEP` restricted to `TUM`/`BLK`/`IMM`; `CFD` only from `PLA`;
   root tubes may arrive as NAT, CPU, SNF, OCT, FFP.
6. **Pooling.** Single parent only, per decision. If hashtagged 10x pools or
   pooled libraries appear, a `sample_parent` link table is the change.
7. **HIPAA.** Collection dates are in every ID and label. The database also
   stores the site's external participant ID. Confirm who may be a `viewer`
   and whether the API token should be scoped.
8. **Barcodes.** The jump box on every page accepts a scanned ID. Label
   printing is not implemented; the 3-row layout is shown on each tube page.

9. **Required metadata.** Only two fields are required so far: library assay
   (LIB) and HLA class (PEP). Everything else is optional. Make more required
   on the *Fields* page once the lab agrees what must never be blank.
10. **QC import matching.** Rows auto-match only when the instrument sample
    name contains the full 35-character tube ID. Tell operators to name samples
    with the tube ID (or scan it) on the Qubit, NanoDrop, TapeStation and
    Countess. The Countess reader is built from the vendor column spec, not a
    real export; check it against the first real file.
11. **Attachments on GCP.** `ATTACHMENT_DIR` is a plain directory; mount the
    lab bucket with gcsfuse (or sync it) rather than storing files on the VM
    disk only.

12. **Remaining free text.** Only Notes fields are free text, plus three
    machine identifiers that cannot be dropdowns: data-file URI, run ID and
    md5 (copied from pipeline output; could move to API-only registration),
    and the participant's external site ID. Everything else is a number, a
    date/time, a fixed choice, or an entry from an admin-extendable list under
    Codes (kits, lots, buffers, freezers, racks, boxes, parties, SOPs, ...).
    Most lists start with just NA; fill them in before the first real tubes.
    Operators are chosen from active users, so every lab member needs an
    account before they appear on a form.

## Decisions made during the build

* Collection = (participant, collection date, specimen). No separate table;
  `root_id` groups a collection and the participant page lists them.
* Site/external ID live on the participant; biobank source on the tube.
* Status change to Depleted happens via the "all parent material used" box on
  the derive form.
* Status and location are one column in tables: an Available tube shows where
  it is; anything else shows its status (plus the location unless Depleted).
* GitHub issues #1-#3 (2026-10-27): location conflicts warn and ask for a
  second submit rather than block (a slot can legitimately hold several tubes,
  e.g. one box position for a bag); the combined base+derived form offers no
  rule override (use the two separate forms for exceptions); time-only inputs
  are client-side only, the server still receives and validates a full
  date-time, so API clients are unaffected.
* PostgreSQL support is a translation layer in `lims/db.py` (placeholders,
  strftime, INSERT OR IGNORE, lastrowid, LIKE→ILIKE, schema DDL). SQL in the
  code base stays in the SQLite dialect; the suite runs on both backends.
* Aliquot numbers are issued from `MAX(aliquot)` over all tubes with the same
  prefix, including deleted ones, so they are never reused.
* Metadata keys are shared across codes (`cell_count` on TUM and CPU is one
  value per tube). QC-imported values record the source attachment; manual
  edits and QC imports are both direct and audited.
* TapeStation is parsed from the XML directly rather than via allotropy,
  because allotropy's electrophoresis output buries RIN/DIN in calculated-data
  documents and drops region tables (cfDNA %, average size, molarity).
* Project now needs Python 3.10+ (allotropy). The cluster venv uses miniconda's
  3.10.
