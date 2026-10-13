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

-- Allowed derivations. Checked when a sample is created; violations need a second user to approve.
--   specimen_fraction   : from=specimen,  to=fraction   (fraction allowed for this specimen)
--   fraction_transition : from=fraction,  to=fraction   (child fraction reachable from parent fraction; same->same always ok)
--   material_transition : from=material,  to=material   (child material reachable from parent material)
--   material_fraction   : from=material,  to=fraction   (if any rows exist for a material, child fraction must be listed)
--   root_material       : from='*',       to=material   (materials a root specimen may arrive as)
CREATE TABLE IF NOT EXISTS derivation_rule (
    rule_type   TEXT NOT NULL,
    from_code   TEXT NOT NULL,
    to_code     TEXT NOT NULL,
    note        TEXT,
    PRIMARY KEY (rule_type, from_code, to_code)
);

CREATE TABLE IF NOT EXISTS user (
    username        TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    initials        TEXT NOT NULL,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin','user','viewer')),
    active          INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS participant (
    participant_id          TEXT PRIMARY KEY,     -- IGI-assigned code used in the sample ID
    cohort_code             TEXT NOT NULL,
    external_participant_id TEXT,                 -- the collection site's own ID; never on a label
    site_code               TEXT,
    notes                   TEXT,
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    created_by              TEXT,
    deleted_at              TEXT
);

CREATE TABLE IF NOT EXISTS sample (
    sample_id           TEXT PRIMARY KEY,         -- full ID, validated against the pattern in config.py
    -- parsed components (kept in sync with sample_id)
    project_code        TEXT NOT NULL,
    cohort_code         TEXT NOT NULL,
    participant_id      TEXT NOT NULL REFERENCES participant(participant_id),
    collection_date     TEXT NOT NULL,            -- ISO yyyy-mm-dd
    specimen_code       TEXT NOT NULL,
    fraction_code       TEXT NOT NULL,
    material_code       TEXT NOT NULL,
    aliquot             INTEGER NOT NULL,
    -- provenance
    parent_id           TEXT REFERENCES sample(sample_id),
    root_id             TEXT NOT NULL REFERENCES sample(sample_id),
    -- processing
    created_datetime    TEXT,                     -- when the tube was made
    created_by          TEXT,                     -- operator initials
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
CREATE INDEX IF NOT EXISTS idx_sample_participant ON sample(participant_id, collection_date);
CREATE INDEX IF NOT EXISTS idx_sample_status ON sample(status);

-- Append-only: one row per hand-off.
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

-- Two-person agreement queue. A request holds the full intended action; a
-- different user approves it, and the action is applied at approval time.
CREATE TABLE IF NOT EXISTS approval_request (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    action_type    TEXT NOT NULL,                  -- create_sample, update_sample, delete_sample, restore_sample
    target_id      TEXT,                           -- sample_id for updates/deletes
    payload        TEXT NOT NULL,                  -- JSON
    violations     TEXT,                           -- JSON list of rule violations (create) or field diff (update)
    justification  TEXT NOT NULL,
    requested_by   TEXT NOT NULL,
    requested_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    status         TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','failed')),
    decided_by     TEXT,
    decided_at     TEXT,
    decision_note  TEXT,
    result         TEXT                            -- JSON: ids created, or error text
);

CREATE TABLE IF NOT EXISTS audit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    username      TEXT NOT NULL,
    table_name    TEXT NOT NULL,
    record_id     TEXT NOT NULL,
    action        TEXT NOT NULL,                   -- insert, update, delete, restore, login
    before_json   TEXT,
    after_json    TEXT,
    approval_id   INTEGER REFERENCES approval_request(id)
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
    type        TEXT NOT NULL CHECK (type IN ('text','number','bool','choice','date')),
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
