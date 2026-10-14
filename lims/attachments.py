"""Files stored with tubes or as shared QC exports. Bytes go to lims.storage (local directory or Supabase bucket)."""
import re

from flask import g
from werkzeug.utils import secure_filename

from . import audit, storage


def abs_path(row):
    """A readable local path for the stored file (downloaded to a cache first when the bytes live in a bucket)."""
    return storage.backend().local_path(row["stored_path"])


def save(conn, file_storage, sample_id=None, kind="other", instrument=None, notes=None):
    """Store an uploaded file and insert its row. Returns the new attachment row."""
    name = secure_filename(file_storage.filename or "upload") or "upload"
    cur = conn.execute("INSERT INTO attachment(sample_id, filename, stored_path, content_type, size_bytes, md5, kind, instrument, notes, uploaded_by) "
                       "VALUES (?,?,?,?,0,'',?,?,?,?)",
                       (sample_id, name, "", file_storage.mimetype, kind, instrument, notes, g.user["username"]))
    aid = cur.lastrowid
    sub = re.sub(r"[^A-Z0-9-]", "_", sample_id) if sample_id else "shared"
    rel = f"{sub}/{aid}_{name}"
    size, md5 = storage.backend().put(rel, file_storage.stream, file_storage.mimetype)
    conn.execute("UPDATE attachment SET stored_path=?, size_bytes=?, md5=? WHERE id=?", (rel, size, md5, aid))
    row = get(conn, aid)
    audit.log(conn, "attachment", aid, "insert", after={"sample_id": sample_id, "filename": name, "md5": row["md5"], "kind": kind, "instrument": instrument})
    return row


def get(conn, attachment_id):
    return conn.execute("SELECT * FROM attachment WHERE id=?", (attachment_id,)).fetchone()


def for_sample(conn, sample_id):
    """Files attached to this tube, plus shared QC exports that produced one of its attribute values."""
    return conn.execute(
        "SELECT a.*, (a.sample_id IS NULL) AS shared FROM attachment a WHERE a.deleted_at IS NULL AND "
        "(a.sample_id=? OR a.id IN (SELECT source_attachment_id FROM sample_attribute WHERE sample_id=? AND source_attachment_id IS NOT NULL)) "
        "ORDER BY a.uploaded_at DESC", (sample_id, sample_id)).fetchall()


def soft_delete(conn, row):
    conn.execute("UPDATE attachment SET deleted_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?", (row["id"],))
    audit.log(conn, "attachment", row["id"], "delete", before=row)
