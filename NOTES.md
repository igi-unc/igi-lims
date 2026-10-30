# NOTES – open questions and decisions to revisit

## Open questions (for Steven)

1. **Nomenclature v2.1 applied (2026-10-27), document still under review.**
   The ID, code lists and rules follow the 2026-10-19 v2.1 text, read the
   "sane" way where the pasted copy disagreed with itself: PF is a specimen and
   PFS a fraction. NTC and NRM are retired (normal T cells are specimen +
   TTC; normal tissue is NM). BLK, NA (fraction), NAT, CPL, CPC and LIB are
   gone. v2 is preserved at tag `v2-final` / branch `nomenclature-v2`.
   Choices the document left open, made here and easy to change:
   * Assay list keeps bulk `TCR` beside the new single-cell `VDJ`; platform
     list adds `MS` so immunopeptidomics files can be linked. File-name labels
     for those two (`bulkTCR`, `immunopeptidome`, `MS`) are placeholders in
     `config.py`. The 10XGEX/10XVDJ question is still open.
   * Source in file names: `tumor` for PF, TU, LN, BM; `normal` otherwise;
     `_Tcell` added for TTC, CD4, CD8 (`TUMOR_SPECIMENS`, `TCELL_FRACTIONS`).
   * First-generation tubes may be FRZ, CPU, SNF, SCS, CFD, DNA, RNA, HMD,
     HMR, OCT or FFP. FRZ requires PFS, PLA, SER or BFC. SNF follows the v2.1
     meaning (cell pellet); there is no code for snap-frozen tissue pieces.
   * A processing date earlier than the received date, or than the parent's,
     is a rule violation (overridable with a reason).
   * Biobank source codes are unchanged (C, H, IH, NA); the document mentions
     C and H only.
2. **Same-day collections.** Two collections of one specimen type received the
   same day (two taps) share segments 1-6. Aliquots stay unique, and the
   collection record keeps them apart in the LIMS, but the ID alone cannot.
3. **Approval queue removed (2026-10-14).** After the demo Steven asked to
   drop two-person approval and rely on the audit log. Edits, deletes and rule
   overrides are now direct, carry an optional (override: required) reason,
   and are flagged in the audit log, on the tube page and in a changes-only
   audit view. Old databases keep their `approval_request` table unused.
4. **Participant numbers.** IGI patient IDs are issued in sequence (P001...)
   and never reused; admins can enter an existing number. Three digits cap
   both the P number and the UNC number at 999. Only UNC participants are
   supported. The label now carries the patient ID, the UNC ID and two dates:
   the document asks for an IRB/HIPAA check of that.
5. **Rule seed is a first guess.** The allowed transitions in `lims/seed.py`
   reproduce the v2.1 worked example; review them on the *Rules* page.
   Notably: `PEP` only in `TUM`/`IMM`/`NAP` and only from SNF; `CFD` only
   from `PLA`; CUL may go to SNF, SCS or CPU.
6. **Pooling.** Single parent only, per decision. If hashtagged 10x pools or
   pooled libraries appear, a `sample_parent` link table is the change.
7. **HIPAA.** Received and processing dates are in every ID and label. The database also
   stores the site's external participant ID. Confirm who may be a `viewer`
   and whether the API token should be scoped.
8. **Barcodes.** The jump box on every page accepts a scanned ID or a UNC ID.
   Label printing is not implemented; each tube page shows the 3-row layout
   with a Data Matrix of the full ID.

9. **Required metadata.** Only one field is required so far: HLA class (PEP).
   (Library assay went with LIB; assay and platform are now required on data
   files.) Everything else is optional. Make more required
   on the *Fields* page once the lab agrees what must never be blank.
10. **QC import matching.** Rows auto-match only when the instrument sample
    name contains the full 51-52 character tube ID. Tell operators to name samples
    with the tube ID (or scan it) on the Qubit, NanoDrop, TapeStation and
    Countess. The Countess reader is built from the vendor column spec, not a
    real export; check it against the first real file.
11. **Attachments on GCP.** `ATTACHMENT_DIR` is a plain directory; mount the
    lab bucket with gcsfuse (or sync it) rather than storing files on the VM
    disk only.

12. **Remaining free text.** Only Notes fields are free text, plus three
    machine identifiers that cannot be dropdowns: data-file URI, run ID and
    md5 (copied from pipeline output; could move to API-only registration). Everything else is a number, a
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
* Label fields are read-only with corrections (Steven, 2026-10-27). Locked now:
  collection date (always was, it is in the ID) and operator (printed on the
  label). Add `created_datetime` to `LABEL_FIELDS` when v2.1 puts the
  processing date in the ID. Corrections never rewrite the stored value, so
  lists, searches and trees still show what was printed; the tube page and the
  API show the corrected value beside it.
* Camera scanning (2026-10-30): /scan reads the Data Matrix (sample ID only;
  Steven chose to keep the code an ID rather than a URL) with the native
  BarcodeDetector where it reads Data Matrix, else the barcode-detector
  ponyfill (ZXing-C++ WASM) from jsDelivr. Tested in headless Chromium with a
  fake camera (no native reader, so the ponyfill path): a tube code opens the
  tube, a non-IGI code is shown and not followed. Not yet tried on an iPad or
  phone against a real printed label.
* Label layout confirmed (2026-10-30): on the lab's Windows computer the M611
  driver prints M6-17-492 correctly with calibration LAYOUT C (upright
  0.5 x 1 in page, label image turned a quarter turn left). Earlier guesses
  (as-drawn page; driver label-size or orientation settings) did not work:
  Chrome overrides the driver's orientation. C is now the default
  (`LABEL_PRINT_LAYOUT`).
* Windows/USB printing (2026-10-30): the lab chose a Windows computer with
  the M611 on USB. The station page's "Windows printer" mode prints label-sized
  pages with window.print(); Chrome started with --kiosk-printing sends them
  silently to the default printer (the Brady driver). Verified in headless
  Chromium (pages, 1.0 x 0.5 in size, barcode, dialog detection), **not yet on
  the lab computer**: check that the driver maps the 1 x 0.5 in page onto the
  label without scaling or offset, and that Chrome prints unattended after a
  reload. Bluetooth mode remains for tablets.
* Label printing (2026-10-29): print queue + one print station (role
  `printer`) using Brady's Web SDK 3.3.3 from the CDN. Tested end to end in
  Chromium with a stand-in for the SDK (jobs claimed in order, 300 x 150 dot
  bitmaps, barcode decodes); **not yet tested on a real M611 or in Bluefy on
  the iPad**. Unknowns to settle at the first real print: whether
  `printBitmaps` scales our 2:1 image exactly onto M6-17-492, whether the
  text is legible at that size (rows are condensed to fit 18 characters in
  about 15 mm), and whether Bluefy runs Brady's WebAssembly. Fallbacks: the
  per-job CSV into Brady Express Labels on the iPad; an Android tablet or any
  laptop with Chrome as the station; a native iPad app with Brady's iOS SDK
  (needs a Mac with Xcode and an Apple developer account).
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
