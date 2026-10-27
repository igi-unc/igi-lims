import functools
from flask import Blueprint, current_app, g, redirect, render_template, request, session, url_for, flash, abort
from werkzeug.security import check_password_hash
from werkzeug.security import generate_password_hash as _gph


def hash_password(password):
    # PBKDF2 rather than Werkzeug's scrypt default: scrypt needs an OpenSSL build that
    # some macOS / older Pythons lack (hashlib has no attribute 'scrypt').
    return _gph(password, method="pbkdf2:sha256")


from .db import get_db
from . import audit

bp = Blueprint("auth", __name__)


def check_initials(conn, initials, own_username=None):
    """Operator codes go into sample IDs: 2 or 3 uppercase letters, unique across accounts."""
    import re
    if not re.fullmatch(r"[A-Z]{2,3}", initials or ""):
        raise ValueError("Initials must be 2 or 3 uppercase letters (they are printed in sample IDs)")
    row = conn.execute("SELECT username FROM account WHERE initials=?", (initials,)).fetchone()
    if row and row["username"] != own_username:
        raise ValueError(f"Initials {initials} already belong to {row['username']}; operator codes must be unique")


def create_user(conn, username, display_name, initials, password, role="user"):
    initials = (initials or "").strip().upper()
    check_initials(conn, initials)
    conn.execute(
        "INSERT INTO account(username, display_name, initials, password_hash, role) VALUES (?,?,?,?,?)",
        (username, display_name, initials, hash_password(password), role),
    )


@bp.before_app_request
def load_user():
    username = session.get("username")
    g.user = None
    if username:
        row = get_db().execute("SELECT * FROM account WHERE username=? AND active=1", (username,)).fetchone()
        g.user = row


def login_required(view):
    @functools.wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.path))
        return view(**kwargs)
    return wrapped


def role_required(*roles):
    def deco(view):
        @functools.wraps(view)
        @login_required
        def wrapped(**kwargs):
            if g.user["role"] not in roles:
                abort(403)
            return view(**kwargs)
        return wrapped
    return deco


# Any write: user or admin. Viewers are read-only.
writer_required = role_required("admin", "user")
admin_required = role_required("admin")


@bp.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        conn = get_db()
        try:
            row = conn.execute("SELECT * FROM account WHERE username=?", (username,)).fetchone()
        except Exception as e:   # unreachable database, or a database that has never been initialised
            conn.rollback()
            current_app.logger.error("login failed before checking the password: %s", e)
            msg = str(e).lower()
            if "account" in msg and ("no such table" in msg or "does not exist" in msg):
                flash("The database has no tables yet. Run `flask init-db` (or, for a demo instance, "
                      "call /cron/demo-reset with the cron secret) and try again.", "error")
            else:
                flash("Cannot reach the database: " + str(e).strip().splitlines()[0], "error")
            return render_template("login.html")
        if row and row["active"] and check_password_hash(row["password_hash"], password):
            session.clear()
            session["username"] = row["username"]
            session.permanent = True
            audit.log(conn, "user", username, "login", username=username)
            conn.commit()
            nxt = request.args.get("next") or url_for("main.index")
            return redirect(nxt if nxt.startswith("/") else url_for("main.index"))
        flash("Invalid username or password", "error")
    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/password", methods=("GET", "POST"))
@login_required
def change_password():
    if request.method == "POST":
        conn = get_db()
        if not check_password_hash(g.user["password_hash"], request.form["current"]):
            flash("Current password is wrong", "error")
        elif request.form["new"] != request.form["confirm"] or len(request.form["new"]) < 8:
            flash("New passwords must match and be at least 8 characters", "error")
        else:
            conn.execute("UPDATE account SET password_hash=? WHERE username=?",
                         (hash_password(request.form["new"]), g.user["username"]))
            audit.log(conn, "user", g.user["username"], "update", after={"password": "changed"})
            conn.commit()
            flash("Password changed", "ok")
            return redirect(url_for("main.index"))
    return render_template("password.html")
