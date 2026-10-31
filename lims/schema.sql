PRAGMA foreign_keys = ON;

-- One mapping table for every controlled vocabulary (spec section 3).
CREATE TABLE IF NOT EXISTS code_list (
    category    TEXT NOT NULL,          -- cohort, specimen, fraction, material, status, assay, biobank_source, site, unit, sop
    code        TEXT NOT NULL,
    meaning     TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (category, code)
);

-- Allowed derivations. Checked when a sample is created; a violation needs a justified, audited override.
--   specimen_fraction   : from=specimen,  to=fraction   (fraction allowed for this specimen)
--   fraction_transition : from=fraction,  to=fraction   (child fraction reachable from parent fraction; same->same always ok)
--   material_transition : from=material,  to=material   (child material reachable from parent material)
--   material_fraction   : from=material,  to=fraction   (if any rows exist for a material, child fraction must be listed)
--   root_material       : from='*',       to=material   (materials a first-generation tube, made straight from a collection, may be)
CREATE TABLE IF NOT EXISTS derivation_rule (
    rule_type   TEXT NOT NULL,
    from_code   TEXT NOT NULL,
    to_code     TEXT NOT NULL,
    note        TEXT,
    PRIMARY KEY (rule_type, from_code, to_code)
);

CREATE TABLE IF NOT EXISTS account (   -- "user" is reserved in PostgreSQL
    username        TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    initials        TEXT NOT NULL,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin','user','viewer','printer')),   -- printer: print station only
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS participant (
    participant_id          TEXT PRIMARY KEY,     -- IGI patient ID (P + 3 digits), segment 3 of the sample ID
    cohort_code             TEXT NOT NULL,
    unc_number              TEXT UNIQUE,          -- 3 digits; "UNC" + this is segment 4 of the sample ID
    external_participant_id TEXT,                 -- any other site reference (not printed)
    site_code               TEXT,
    notes                   TEXT,
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    created_by              TEXT,
    deleted_at              TEXT
);

-- A collection is the set of tubes made from one specimen received on one day (the specimen itself is not
-- labelled or stored as a tube). Every tube carries its collection_id; first-generation tubes have no parent.
CREATE TABLE IF NOT EXISTS collection (
    collection_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    participant_id      TEXT NOT NULL REFERENCES participant(participant_id),
    specimen_code       TEXT NOT NULL,
    received_date       TEXT NOT NULL,            -- ISO yyyy-mm-dd; segment 5 of every tube ID from this collection
    site_code           TEXT,
    biobank_source      TEXT,
    received_from       TEXT,                     -- party (clinic, biobank)
    received_by         TEXT,                     -- staff initials
    time_collected      TEXT,                     -- ISO date-time
    time_received       TEXT,                     -- ISO date-time
    container_type      TEXT,
    transport_temp      TEXT,
    appearance          TEXT,
    quantity            REAL,                     -- as received (e.g. 400 mL of fluid)
    unit                TEXT,
    notes               TEXT,
    created_by          TEXT,                     -- username
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    deleted_at          TEXT
);
CREATE INDEX IF NOT EXISTS idx_collection_participant ON collection(participant_id, received_date);

-- Counters the LIMS issues numbers from. Allocation updates the row first, which takes the database's write lock,
-- so concurrent registrations queue up; a rolled-back registration gives its numbers back (no gaps, no duplicates).
CREATE TABLE IF NOT EXISTS id_counter (
    name    TEXT PRIMARY KEY,
    value   INTEGER NOT NULL                     -- last number issued (-1 = none yet)
);

CREATE TABLE IF NOT EXISTS sample (
    sample_id           TEXT PRIMARY KEY,         -- full ID, validated against the pattern in config.py
    serial              INTEGER,                  -- LIMS number (LIMS_NUMBER_DIGITS, default 9 digits), unique, under the 2D code
    -- parsed components (kept in sync with sample_id)
    project_code        TEXT NOT NULL,
    cohort_code         TEXT NOT NULL,
    participant_id      TEXT NOT NULL REFERENCES participant(participant_id),
    unc_id              TEXT NOT NULL,            -- UNC + 3 digits
    received_date       TEXT NOT NULL,            -- ISO yyyy-mm-dd, from the collection
    specimen_code       TEXT NOT NULL,
    fraction_code       TEXT NOT NULL,
    material_code       TEXT NOT NULL,
    aliquot             INTEGER NOT NULL,
    processing_date     TEXT NOT NULL,            -- ISO yyyy-mm-dd, the date part of created_datetime at creation
    -- provenance
    collection_id       INTEGER NOT NULL REFERENCES collection(collection_id),
    parent_id           TEXT REFERENCES sample(sample_id),   -- blank for first-generation tubes
    root_id             TEXT NOT NULL REFERENCES sample(sample_id),   -- the first-generation tube of this line
    -- processing
    created_datetime    TEXT,                     -- when the tube was made
    created_by          TEXT,                     -- operator initials (segment 10)
    sop_code            TEXT,
    biobank_source      TEXT,
    quantity            REAL,
    unit                TEXT,
    freezer             TEXT,
    rack                TEXT,
    box                 TEXT,
    position            TEXT,
    status              TEXT NOT NULL DEFAULT 'Available',
    notes               TEXT,
    -- record bookkeeping
    record_created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    record_created_by   TEXT,
    record_updated_at   TEXT,
    deleted_at          TEXT
);
CREATE INDEX IF NOT EXISTS idx_sample_parent ON sample(parent_id);
CREATE INDEX IF NOT EXISTS idx_sample_root ON sample(root_id);
CREATE INDEX IF NOT EXISTS idx_sample_participant ON sample(participant_id, received_date);
CREATE INDEX IF NOT EXISTS idx_sample_collection ON sample(collection_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sample_serial ON sample(serial);
CREATE INDEX IF NOT EXISTS idx_sample_status ON sample(status);

-- Append-only: one row per hand-off.
CREATE TABLE IF NOT EXISTS sample_correction (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id        TEXT REFERENCES sample(sample_id),            -- set for tube-level fields
    collection_id    INTEGER REFERENCES collection(collection_id),  -- set for collection-level fields (received date)
    field            TEXT NOT NULL,                                 -- a field from config.LABEL_FIELDS
    original_value   TEXT,                                          -- value in effect before this correction
    corrected_value  TEXT NOT NULL,
    reason           TEXT NOT NULL,
    recorded_by      TEXT NOT NULL,
    recorded_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_correction_sample ON sample_correction(sample_id);
CREATE INDEX IF NOT EXISTS idx_correction_collection ON sample_correction(collection_id);

CREATE TABLE IF NOT EXISTS custody_event (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id            TEXT NOT NULL REFERENCES sample(sample_id),
    event_datetime       TEXT NOT NULL,
    from_party           TEXT NOT NULL,            -- person or location
    to_party             TEXT NOT NULL,
    purpose              TEXT,
    condition_on_receipt TEXT,
    initials             TEXT,
    notes                TEXT,
    recorded_by          TEXT NOT NULL,
    recorded_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_custody_sample ON custody_event(sample_id);

CREATE TABLE IF NOT EXISTS data_file (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id        TEXT NOT NULL REFERENCES sample(sample_id),
    uri              TEXT NOT NULL,                -- gs://bucket/path
    assay_code       TEXT,
    platform_code    TEXT,
    run_id           TEXT,
    checksum_md5     TEXT,
    pipeline         TEXT,
    pipeline_version TEXT,
    notes            TEXT,
    recorded_by      TEXT NOT NULL,
    recorded_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    deleted_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_file_sample ON data_file(sample_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_file_uri ON data_file(uri) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS audit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    username      TEXT NOT NULL,
    table_name    TEXT NOT NULL,
    record_id     TEXT NOT NULL,
    action        TEXT NOT NULL,                   -- insert, update, delete, restore, login
    before_json   TEXT,
    after_json    TEXT,
    reason        TEXT                            -- operator's justification (edit, delete, rule override)
);
CREATE INDEX IF NOT EXISTS idx_audit_record ON audit_log(table_name, record_id);

-- ---------------------------------------------------------------- metadata (added 2026-10-13)

-- Which extra fields apply to a tube, by fraction code, material code, or all tubes ('all','*').
-- A key may be defined under several codes (e.g. cell_count for TUM and CPU); the form merges by key.
CREATE TABLE IF NOT EXISTS attribute_definition (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scope       TEXT NOT NULL CHECK (scope IN ('fraction','material','all')),
    code        TEXT NOT NULL,                     -- fraction/material code, or '*' for scope 'all'
    key         TEXT NOT NULL,                     -- snake_case identifier, stable across scopes
    label       TEXT NOT NULL,
    type        TEXT NOT NULL CHECK (type IN ('text','number','bool','choice','list','date','datetime')),
    unit        TEXT,
    choices     TEXT,                              -- '|'-separated for type 'choice'
    required    INTEGER NOT NULL DEFAULT 0,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    active      INTEGER NOT NULL DEFAULT 1,
    UNIQUE (scope, code, key)
);

-- Files kept with a tube (traces, images, reports) or shared QC exports (sample_id NULL, used by several tubes).
CREATE TABLE IF NOT EXISTS attachment (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id     TEXT REFERENCES sample(sample_id),
    filename      TEXT NOT NULL,
    stored_path   TEXT NOT NULL,                   -- relative to ATTACHMENT_DIR
    content_type  TEXT,
    size_bytes    INTEGER NOT NULL,
    md5           TEXT NOT NULL,
    kind          TEXT NOT NULL DEFAULT 'other',   -- qc_export, trace, image, report, other
    instrument    TEXT,                            -- qubit4, nanodrop_one, tapestation, countess3, ...
    notes         TEXT,
    uploaded_by   TEXT NOT NULL,
    uploaded_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    deleted_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_attachment_sample ON attachment(sample_id);

-- One value per (tube, key). Values written by a QC import point at the file they came from.
CREATE TABLE IF NOT EXISTS sample_attribute (
    sample_id             TEXT NOT NULL REFERENCES sample(sample_id),
    key                   TEXT NOT NULL,
    value                 TEXT,
    source_attachment_id  INTEGER REFERENCES attachment(id),
    updated_by            TEXT,
    updated_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    PRIMARY KEY (sample_id, key)
);

-- Label printing: users queue jobs from any browser; the print station (role 'printer', next to the Brady
-- printer) claims them in order and prints them.
CREATE TABLE IF NOT EXISTS print_job (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    requested_by        TEXT NOT NULL,                -- username
    requested_initials  TEXT,
    requested_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    sample_ids          TEXT NOT NULL,                -- JSON list, in print order
    n_labels            INTEGER NOT NULL,
    header              INTEGER NOT NULL DEFAULT 1,   -- print a job header label first
    status              TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','printing','printed','failed','cancelled')),
    station             TEXT,                         -- username of the station that claimed it
    claim_token         TEXT,
    claimed_at          TEXT,
    finished_at         TEXT,
    error               TEXT,
    reprint_reason      TEXT                          -- required when any tube in the job already has a printed label
);
CREATE INDEX IF NOT EXISTS idx_print_job_status ON print_job(status, id);

-- One row per label the station confirmed as printed. A tube's label is printed once; reprints need a reason.
CREATE TABLE IF NOT EXISTS label_print (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id       TEXT NOT NULL REFERENCES sample(sample_id),
    job_id          INTEGER REFERENCES print_job(id),
    printed_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    station         TEXT,
    reprint_reason  TEXT
);
CREATE INDEX IF NOT EXISTS idx_label_print_sample ON label_print(sample_id);
