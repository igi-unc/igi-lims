"""Two-person agreement queue."""
import json
from flask import g

from . import samples, audit


def request(conn, action_type, payload, justification, target_id=None, violations=None):
    cur = conn.execute(
        "INSERT INTO approval_request(action_type, target_id, payload, violations, justification, requested_by) "
        "VALUES (?,?,?,?,?,?)",
        (action_type, target_id, json.dumps(payload, default=str),
         json.dumps(violations, default=str) if violations is not None else None,
         justification, g.user["username"]),
    )
    return cur.lastrowid


def get(conn, request_id):
    return conn.execute("SELECT * FROM approval_request WHERE id=?", (request_id,)).fetchone()


def pending(conn):
    return conn.execute("SELECT * FROM approval_request WHERE status='pending' ORDER BY requested_at").fetchall()


def apply(conn, req, note=None):
    """Apply an approved request. Raises ValueError if the approver is the requester."""
    if req["status"] != "pending":
        raise ValueError("Request is no longer pending")
    if req["requested_by"] == g.user["username"]:
        raise ValueError("A request cannot be approved by the person who made it")
    payload = json.loads(req["payload"])
    rid = req["id"]
    try:
        if req["action_type"] == "create_sample":
            created, _ = samples.create_samples(conn, payload, force=True, approval_id=rid)
            result = {"created": created}
        elif req["action_type"] == "update_sample":
            d = samples.update_sample(conn, req["target_id"], payload, approval_id=rid)
            result = {"changed": {k: [o, n] for k, (o, n) in d.items()}}
        elif req["action_type"] == "delete_sample":
            samples.delete_sample(conn, req["target_id"], approval_id=rid)
            result = {"deleted": req["target_id"]}
        elif req["action_type"] == "restore_sample":
            samples.restore_sample(conn, req["target_id"], approval_id=rid)
            result = {"restored": req["target_id"]}
        else:
            raise ValueError("Unknown action type " + req["action_type"])
        status = "approved"
    except ValueError as e:
        result = {"error": str(e)}
        status = "failed"
    conn.execute(
        "UPDATE approval_request SET status=?, decided_by=?, decided_at=strftime('%Y-%m-%dT%H:%M:%SZ','now'), "
        "decision_note=?, result=? WHERE id=?",
        (status, g.user["username"], note, json.dumps(result, default=str), rid),
    )
    audit.log(conn, "approval_request", rid, status, after=result, approval_id=rid)
    return status, result


def reject(conn, req, note=None):
    if req["status"] != "pending":
        raise ValueError("Request is no longer pending")
    conn.execute(
        "UPDATE approval_request SET status='rejected', decided_by=?, decided_at=strftime('%Y-%m-%dT%H:%M:%SZ','now'), "
        "decision_note=? WHERE id=?",
        (g.user["username"], note, req["id"]),
    )
    audit.log(conn, "approval_request", req["id"], "rejected", after={"note": note})
