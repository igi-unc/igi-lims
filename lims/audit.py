import json
from flask import g


def _row_to_dict(row):
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def log(conn, table, record_id, action, before=None, after=None, reason=None, username=None):
    """One row per write. `reason` is the operator's stated justification (edits, deletes, rule overrides);
    the audit views flag rows that carry one, and every non-insert action, so changes stand out."""
    user = username or (g.user["username"] if getattr(g, "user", None) else "system")
    conn.execute(
        "INSERT INTO audit_log(username, table_name, record_id, action, before_json, after_json, reason) "
        "VALUES (?,?,?,?,?,?,?)",
        (user, table, str(record_id), action,
         json.dumps(_row_to_dict(before) if not isinstance(before, dict) else before, default=str) if before is not None else None,
         json.dumps(_row_to_dict(after) if not isinstance(after, dict) else after, default=str) if after is not None else None,
         reason),
    )
