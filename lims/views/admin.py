from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort
from werkzeug.security import generate_password_hash

from ..auth import admin_required, login_required, create_user
from ..db import get_db
from .. import audit, rules
from .helpers import codes

bp = Blueprint("admin", __name__, url_prefix="/admin")

# Core vocabularies first; every other category in the table (the admin-extendable lists) follows.
CORE_CATEGORIES = ["cohort", "specimen", "fraction", "material", "status", "assay", "biobank_source", "site", "unit", "sop"]


def all_categories(conn):
    extra = [r[0] for r in conn.execute("SELECT DISTINCT category FROM code_list ORDER BY category") if r[0] not in CORE_CATEGORIES]
    return CORE_CATEGORIES + extra


@bp.route("/users")
@admin_required
def users():
    rows = get_db().execute("SELECT * FROM user ORDER BY username").fetchall()
    return render_template("admin/users.html", rows=rows)


@bp.route("/users/new", methods=("GET", "POST"))
@admin_required
def user_new():
    if request.method == "POST":
        conn = get_db()
        f = request.form
        if len(f["password"]) < 8:
            flash("Password must be at least 8 characters", "error")
        elif conn.execute("SELECT 1 FROM user WHERE username=?", (f["username"].strip(),)).fetchone():
            flash("Username already exists", "error")
        else:
            create_user(conn, f["username"].strip(), f["display_name"].strip(), f["initials"].strip().upper(),
                        f["password"], f["role"])
            audit.log(conn, "user", f["username"].strip(), "insert", after={"role": f["role"]})
            conn.commit()
            flash("User created", "ok")
            return redirect(url_for("admin.users"))
    return render_template("admin/user_form.html", u=request.form if request.method == "POST" else {})


@bp.route("/users/<username>", methods=("POST",))
@admin_required
def user_update(username):
    conn = get_db()
    u = conn.execute("SELECT * FROM user WHERE username=?", (username,)).fetchone()
    if u is None:
        abort(404)
    action = request.form.get("action")
    if action == "toggle_active":
        if username == g.user["username"]:
            flash("You cannot deactivate yourself", "error")
        else:
            conn.execute("UPDATE user SET active=? WHERE username=?", (0 if u["active"] else 1, username))
            audit.log(conn, "user", username, "update", before={"active": u["active"]}, after={"active": 0 if u["active"] else 1})
    elif action == "role":
        conn.execute("UPDATE user SET role=? WHERE username=?", (request.form["role"], username))
        audit.log(conn, "user", username, "update", before={"role": u["role"]}, after={"role": request.form["role"]})
    elif action == "reset_password":
        pw = request.form.get("password", "")
        if len(pw) < 8:
            flash("Password must be at least 8 characters", "error")
            return redirect(url_for("admin.users"))
        conn.execute("UPDATE user SET password_hash=? WHERE username=?", (generate_password_hash(pw), username))
        audit.log(conn, "user", username, "update", after={"password": "reset by admin"})
    conn.commit()
    return redirect(url_for("admin.users"))


@bp.route("/codes", methods=("GET", "POST"))
@admin_required
def code_lists():
    conn = get_db()
    if request.method == "POST":
        f = request.form
        action = f.get("action")
        if action == "new_category":
            cat = f["new_category"].strip().lower().replace(" ", "_")
            if not cat:
                flash("Category name is required", "error")
                return redirect(url_for("admin.code_lists"))
            conn.execute("INSERT OR IGNORE INTO code_list(category, code, meaning, sort_order) VALUES (?,?,?,0)", (cat, "NA", "Not applicable"))
            audit.log(conn, "code_list", f"{cat}:NA", "insert", after={"meaning": "new category"})
            conn.commit()
            return redirect(url_for("admin.code_lists", category=cat))
        if action == "add":
            cat, code, meaning = f["category"], f["code"].strip().upper(), f["meaning"].strip()
            if not code or not meaning:
                flash("Code and meaning are required", "error")
            elif conn.execute("SELECT 1 FROM code_list WHERE category=? AND code=?", (cat, code)).fetchone():
                flash("Code already exists (codes are never repurposed; retire it instead)", "error")
            else:
                n = conn.execute("SELECT COALESCE(MAX(sort_order),0)+1 FROM code_list WHERE category=?", (cat,)).fetchone()[0]
                conn.execute("INSERT INTO code_list(category, code, meaning, sort_order) VALUES (?,?,?,?)", (cat, code, meaning, n))
                audit.log(conn, "code_list", f"{cat}:{code}", "insert", after={"meaning": meaning})
                flash(f"Added {cat} code {code}", "ok")
        elif action == "toggle":
            cat, code = f["category"], f["code"]
            row = conn.execute("SELECT active FROM code_list WHERE category=? AND code=?", (cat, code)).fetchone()
            if row:
                conn.execute("UPDATE code_list SET active=? WHERE category=? AND code=?", (0 if row["active"] else 1, cat, code))
                audit.log(conn, "code_list", f"{cat}:{code}", "update", before={"active": row["active"]}, after={"active": 0 if row["active"] else 1})
        elif action == "rename":
            cat, code = f["category"], f["code"]
            conn.execute("UPDATE code_list SET meaning=? WHERE category=? AND code=?", (f["meaning"].strip(), cat, code))
            audit.log(conn, "code_list", f"{cat}:{code}", "update", after={"meaning": f["meaning"].strip()})
        conn.commit()
        return redirect(url_for("admin.code_lists", category=f.get("category")))
    cat = request.args.get("category", "specimen")
    rows = codes(cat, active_only=False)
    used_by = conn.execute("SELECT DISTINCT scope, code, label FROM attribute_definition WHERE type='list' AND choices=? AND active=1 ORDER BY 1,2",
                           (cat,)).fetchall()
    return render_template("admin/codes.html", categories=all_categories(conn), core=CORE_CATEGORIES, category=cat, rows=rows, used_by=used_by)


@bp.route("/rules", methods=("GET", "POST"))
@admin_required
def rule_table():
    conn = get_db()
    if request.method == "POST":
        f = request.form
        key = (f["rule_type"], f["from_code"].strip().upper(), f["to_code"].strip().upper())
        if f.get("action") == "delete":
            conn.execute("DELETE FROM derivation_rule WHERE rule_type=? AND from_code=? AND to_code=?", key)
            audit.log(conn, "derivation_rule", ":".join(key), "delete")
        else:
            if conn.execute("SELECT 1 FROM derivation_rule WHERE rule_type=? AND from_code=? AND to_code=?", key).fetchone():
                flash("Rule already exists", "error")
            else:
                conn.execute("INSERT INTO derivation_rule(rule_type, from_code, to_code, note) VALUES (?,?,?,?)",
                             key + (f.get("note", "").strip() or None,))
                audit.log(conn, "derivation_rule", ":".join(key), "insert")
                flash("Rule added", "ok")
        conn.commit()
        return redirect(url_for("admin.rule_table", rule_type=f["rule_type"]))
    rt = request.args.get("rule_type", "material_transition")
    rows = conn.execute("SELECT * FROM derivation_rule WHERE rule_type=? ORDER BY from_code, to_code", (rt,)).fetchall()
    grouped = {}
    for r in rows:
        grouped.setdefault(r["from_code"], []).append(r)
    return render_template("admin/rules.html", rule_types=rules.rule_types(), rule_type=rt, grouped=grouped,
                           fractions=codes("fraction"), materials=codes("material"), specimens=codes("specimen"))


@bp.route("/audit")
@login_required
def audit_log():
    conn = get_db()
    f = {k: (request.args.get(k) or "").strip() for k in ("table", "record", "user")}
    where, params = [], []
    if f["table"]:
        where.append("table_name=?"); params.append(f["table"])
    if f["record"]:
        where.append("record_id LIKE ?"); params.append(f"%{f['record']}%")
    if f["user"]:
        where.append("username=?"); params.append(f["user"])
    page = max(int(request.args.get("page", 1)), 1)
    sql = "SELECT * FROM audit_log" + (" WHERE " + " AND ".join(where) if where else "") + \
          f" ORDER BY id DESC LIMIT 101 OFFSET {(page - 1) * 100}"
    rows = conn.execute(sql, params).fetchall()
    tables = [r[0] for r in conn.execute("SELECT DISTINCT table_name FROM audit_log ORDER BY 1")]
    return render_template("admin/audit.html", rows=rows[:100], has_more=len(rows) > 100, page=page, f=f, tables=tables)


@bp.route("/fields", methods=("GET", "POST"))
@admin_required
def fields():
    """Per-fraction / per-material metadata field definitions."""
    conn = get_db()
    if request.method == "POST":
        f = request.form
        action = f.get("action")
        if action == "add":
            key = f["key"].strip().lower().replace(" ", "_")
            if not key or not f["label"].strip():
                flash("Key and label are required", "error")
            elif conn.execute("SELECT 1 FROM attribute_definition WHERE scope=? AND code=? AND key=?",
                              (f["scope"], f["code"].strip().upper() or "*", key)).fetchone():
                flash("That field already exists for this code", "error")
            else:
                n = conn.execute("SELECT COALESCE(MAX(sort_order),0)+1 FROM attribute_definition WHERE scope=? AND code=?",
                                 (f["scope"], f["code"].strip().upper() or "*")).fetchone()[0]
                choices = f.get("list_category", "").strip() if f["type"] == "list" else f.get("choices", "").strip()
                if f["type"] in ("list", "choice") and not choices:
                    flash("A list field needs a category and a choice field needs its choices", "error")
                    return redirect(url_for("admin.fields", scope=f.get("scope"), code=f.get("code")))
                conn.execute("INSERT INTO attribute_definition(scope, code, key, label, type, unit, choices, required, sort_order) VALUES (?,?,?,?,?,?,?,?,?)",
                             (f["scope"], f["code"].strip().upper() or "*", key, f["label"].strip(), f["type"],
                              f.get("unit", "").strip() or None, choices or None, 1 if f.get("required") else 0, n))
                audit.log(conn, "attribute_definition", f"{f['scope']}:{f['code']}:{key}", "insert", after={"label": f["label"]})
                flash("Field added", "ok")
        elif action == "toggle":
            row = conn.execute("SELECT * FROM attribute_definition WHERE id=?", (f["id"],)).fetchone()
            if row:
                conn.execute("UPDATE attribute_definition SET active=? WHERE id=?", (0 if row["active"] else 1, row["id"]))
                audit.log(conn, "attribute_definition", row["id"], "update", before={"active": row["active"]}, after={"active": 0 if row["active"] else 1})
        elif action == "required":
            row = conn.execute("SELECT * FROM attribute_definition WHERE id=?", (f["id"],)).fetchone()
            if row:
                conn.execute("UPDATE attribute_definition SET required=? WHERE id=?", (0 if row["required"] else 1, row["id"]))
                audit.log(conn, "attribute_definition", row["id"], "update", before={"required": row["required"]}, after={"required": 0 if row["required"] else 1})
        conn.commit()
        return redirect(url_for("admin.fields", scope=f.get("scope"), code=f.get("code")))
    scope = request.args.get("scope", "material")
    code = (request.args.get("code") or "").upper()
    codes_for = {"fraction": codes("fraction", active_only=False), "material": codes("material", active_only=False), "all": []}[scope]
    list_categories = all_categories(conn)
    if scope == "all":
        code = "*"
    elif not code and codes_for:
        code = codes_for[0]["code"]
    rows = conn.execute("SELECT * FROM attribute_definition WHERE scope=? AND code=? ORDER BY sort_order, id", (scope, code)).fetchall()
    return render_template("admin/fields.html", scope=scope, code=code, codes_for=codes_for, rows=rows, list_categories=list_categories)
