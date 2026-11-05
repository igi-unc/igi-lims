"""Scanning kit / reagent boxes on the registration forms.

A scan is parsed as GS1 (GTIN, lot, expiry) when it is one; otherwise the raw text identifies the product. Which
code-list entry a product is (e.g. kit = EPCAM_MACS) is learned the first time someone scans it and confirms, and
stored in reagent_barcode. Lot numbers can be added to their lot list from the scan, so nobody retypes them.
"""
import datetime as dt
import re

from flask import Blueprint, jsonify, request, render_template, current_app, redirect, url_for, flash, g

from ..auth import writer_required, admin_required, login_required
from ..db import get_db
from .. import audit, gs1

bp = Blueprint("reagents", __name__, url_prefix="/reagents")
_LOT = re.compile(r"[A-Za-z0-9._/+-]{1,40}")


def _category(conn, field):
    """The code-list category behind a 'list' metadata field (e.g. kit -> kit)."""
    r = conn.execute("SELECT choices FROM attribute_definition WHERE key=? AND type='list' AND active=1 ORDER BY id LIMIT 1",
                     (field,)).fetchone()
    return r["choices"] if r else None


def _meaning(conn, category, code):
    r = conn.execute("SELECT meaning FROM code_list WHERE category=? AND code=? AND active=1", (category, code)).fetchone()
    return r["meaning"] if r else None


def describe(conn, text, fields=None):
    """What a scanned code means for the form: product key, lot, expiry, and the fields it fills."""
    raw = (text or "").strip()
    parsed = gs1.parse(raw)
    product = (parsed or {}).get("gtin") or (None if parsed else raw[:200]) or None
    lot = (parsed or {}).get("lot")
    expiry = (parsed or {}).get("expiry")
    fieldmap = current_app.config["REAGENT_FIELDS"]
    wanted = [f for f in (fields or fieldmap) if f in fieldmap]
    matches = []
    if product:
        for r in conn.execute("SELECT * FROM reagent_barcode WHERE product_key=? ORDER BY id", (product,)):
            if r["field_key"] in wanted:
                cat = _category(conn, r["field_key"])
                matches.append({"field": r["field_key"], "code": r["code"], "meaning": _meaning(conn, cat, r["code"]) if cat else None})
    lots = []
    if lot:
        for f in {fieldmap[m["field"]] for m in matches if fieldmap.get(m["field"])} or {fieldmap[f] for f in wanted if fieldmap.get(f)}:
            cat = _category(conn, f)
            if cat:
                lots.append({"field": f, "exists": _meaning(conn, cat, lot) is not None, "addable": bool(_LOT.fullmatch(lot))})
    return {"raw": raw, "gs1": parsed, "product_key": product, "gtin_valid": gs1.gtin_ok(product) if parsed and product else None,
            "lot": lot, "expiry": expiry, "expired": bool(expiry and expiry < dt.date.today().isoformat()),
            "matches": matches, "lots": lots}


@bp.route("/lookup", methods=("POST",))
@writer_required
def lookup():
    d = request.get_json(silent=True) or {}
    if not str(d.get("text") or "").strip():
        return jsonify({"error": "nothing scanned"}), 400
    return jsonify(describe(get_db(), str(d["text"])[:500], d.get("fields")))


@bp.route("/remember", methods=("POST",))
@writer_required
def remember():
    """This product is <code> in <field>. Replaces an earlier answer for the same product and field."""
    conn = get_db()
    d = request.get_json(silent=True) or {}
    product, field, code = str(d.get("product_key") or "").strip()[:200], str(d.get("field") or ""), str(d.get("code") or "")
    if not product or field not in current_app.config["REAGENT_FIELDS"]:
        return jsonify({"error": "unknown field or empty product"}), 400
    cat = _category(conn, field)
    if not cat or _meaning(conn, cat, code) is None:
        return jsonify({"error": f"{code!r} is not an entry of the {field} list"}), 400
    old = conn.execute("SELECT * FROM reagent_barcode WHERE product_key=? AND field_key=?", (product, field)).fetchone()
    if old:
        conn.execute("UPDATE reagent_barcode SET code=?, created_by=?, created_at=strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE id=?",
                     (code, g.user["username"], old["id"]))
        audit.log(conn, "reagent_barcode", old["id"], "update", before={"code": old["code"]}, after={"code": code},
                  reason="Scanned product re-assigned")
    else:
        cur = conn.execute("INSERT INTO reagent_barcode(product_key, field_key, code, created_by) VALUES (?,?,?,?)",
                           (product, field, code, g.user["username"]))
        audit.log(conn, "reagent_barcode", cur.lastrowid, "insert", after={"product_key": product, "field": field, "code": code})
    conn.commit()
    return jsonify({"ok": True, "field": field, "code": code, "meaning": _meaning(conn, cat, code)})


@bp.route("/lot", methods=("POST",))
@writer_required
def add_lot():
    """Add a scanned lot number to a lot list (only lot fields of REAGENT_FIELDS), so it can be selected."""
    conn = get_db()
    d = request.get_json(silent=True) or {}
    field, lot = str(d.get("field") or ""), str(d.get("lot") or "").strip()
    if field not in {v for v in current_app.config["REAGENT_FIELDS"].values() if v}:
        return jsonify({"error": "not a lot field"}), 400
    if not _LOT.fullmatch(lot):
        return jsonify({"error": "lot numbers are letters, digits and . _ / + - (at most 40)"}), 400
    cat = _category(conn, field)
    if not cat:
        return jsonify({"error": f"no list behind {field}"}), 400
    meaning = str(d.get("meaning") or "").strip()[:200] or f"Lot {lot}"
    if _meaning(conn, cat, lot) is None:
        n = conn.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM code_list WHERE category=?", (cat,)).fetchone()[0]
        conn.execute("INSERT INTO code_list(category, code, meaning, active, sort_order) VALUES (?,?,?,1,?)", (cat, lot, meaning, n))
        audit.log(conn, "code_list", f"{cat}:{lot}", "insert", after={"category": cat, "code": lot, "meaning": meaning},
                  reason="Added from a reagent scan")
        conn.commit()
    return jsonify({"ok": True, "field": field, "code": lot, "meaning": _meaning(conn, cat, lot)})


@bp.route("/")
@login_required
def index():
    conn = get_db()
    rows = conn.execute("SELECT * FROM reagent_barcode ORDER BY field_key, code").fetchall()
    shown = []
    for r in rows:
        cat = _category(conn, r["field_key"])
        shown.append({**{k: r[k] for k in r.keys()}, "meaning": _meaning(conn, cat, r["code"]) if cat else None})
    tests = []
    if current_app.config.get("DEMO_MODE"):
        from ..labels import barcode_matrix, _modules_path
        from ..demo import DEMO_REAGENTS
        for gtin, field, code, lot, exp, what in DEMO_REAGENTS:
            text = gs1.build(gtin, exp, lot)
            m = barcode_matrix(text); n = len(m); px = 6
            svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{(n + 4) * px}" height="{(n + 4) * px}" role="img" '
                   f'aria-label="test code"><rect width="100%" height="100%" fill="#fff"/>'
                   f'<path fill="#000" d="{_modules_path(m, 2 * px, 2 * px, px)}"/></svg>')
            tests.append({"what": what, "gtin": gtin, "lot": lot, "expiry": gs1.parse(text).get("expiry"), "svg": svg,
                          "human": f"(01){gtin}(17){exp}(10){lot}"})
    return render_template("reagents/index.html", rows=shown, tests=tests)


@bp.route("/<int:rid>/delete", methods=("POST",))
@admin_required
def delete(rid):
    conn = get_db()
    r = conn.execute("SELECT * FROM reagent_barcode WHERE id=?", (rid,)).fetchone()
    if r:
        conn.execute("DELETE FROM reagent_barcode WHERE id=?", (rid,))
        audit.log(conn, "reagent_barcode", rid, "delete", before={k: r[k] for k in ("product_key", "field_key", "code")},
                  reason="Removed on the reagent barcodes page")
        conn.commit()
        flash("Removed. The next scan of that product will ask again.", "ok")
    return redirect(url_for("reagents.index"))
