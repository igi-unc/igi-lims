import os
import sqlite3
import click
from flask import current_app, g

from . import seed as seed_module, seed_attributes


def get_db():
    if "db" not in g:
        path = current_app.config["DATABASE"]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        conn = sqlite3.connect(path, detect_types=0, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 10000")
        g.db = conn
    return g.db


def close_db(e=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def _migrate(conn):
    """Small in-place migrations for databases created by earlier versions."""
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='attribute_definition'").fetchone()
    if row and "'list'" not in row["sql"]:
        conn.executescript("""
            ALTER TABLE attribute_definition RENAME TO attribute_definition_old;
            CREATE TABLE attribute_definition (
                id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL CHECK (scope IN ('fraction','material','all')),
                code TEXT NOT NULL, key TEXT NOT NULL, label TEXT NOT NULL,
                type TEXT NOT NULL CHECK (type IN ('text','number','bool','choice','list','date','datetime')),
                unit TEXT, choices TEXT, required INTEGER NOT NULL DEFAULT 0, sort_order INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1, UNIQUE (scope, code, key));
            INSERT INTO attribute_definition SELECT * FROM attribute_definition_old;
            DROP TABLE attribute_definition_old;
        """)


def init_db(conn=None):
    conn = conn or get_db()
    _migrate(conn)
    with current_app.open_resource("schema.sql") as f:
        conn.executescript(f.read().decode("utf8"))
    seed_module.seed(conn)
    seed_attributes.seed(conn)
    conn.commit()


@click.command("init-db")
def init_db_command():
    """Create tables (if missing) and load the seed code lists and rules."""
    init_db()
    click.echo("Database initialised at " + current_app.config["DATABASE"])


@click.command("create-user")
@click.argument("username")
@click.option("--name", prompt="Display name")
@click.option("--initials", prompt="Initials")
@click.option("--role", type=click.Choice(["admin", "user", "viewer"]), default="user")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
def create_user_command(username, name, initials, role, password):
    """Create a login. The first user should be an admin."""
    from .auth import create_user
    create_user(get_db(), username, name, initials.upper(), password, role)
    get_db().commit()
    click.echo(f"Created {role} {username}")


@click.command("seed-demo")
@click.option("--user", "username", default=None, help="Account the demo records are attributed to (default: first active user)")
def seed_demo_command(username):
    """Add one demonstration participant with three collections processed through to data files."""
    from .demo import seed_demo
    conn = get_db()
    if username is None:
        row = conn.execute("SELECT username FROM user WHERE active=1 ORDER BY CASE role WHEN 'user' THEN 0 ELSE 1 END, username").fetchone()
        if row is None:
            raise click.ClickException("Create a user first (flask create-user)")
        username = row["username"]
    try:
        info = seed_demo(conn, username)
    except ValueError as e:
        conn.rollback()
        raise click.ClickException(str(e))
    conn.commit()
    click.echo(f"Demo participant {info['participant']} (site ID {info['external_id']}): {info['tubes']} tubes, "
               f"roots {', '.join(info['roots'])}")
    if info["pending_request"]:
        click.echo(f"Pending change request #{info['pending_request']} by {username}; approve it as another user "
                   f"({info['approver'] or 'create a second account'}) during the demo.")


@click.command("set-password")
@click.argument("username")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
def set_password_command(username, password):
    """Reset a user's password from the command line (e.g. when locked out)."""
    from .auth import hash_password
    conn = get_db()
    if conn.execute("SELECT 1 FROM user WHERE username=?", (username,)).fetchone() is None:
        raise click.ClickException(f"No user named {username}")
    conn.execute("UPDATE user SET password_hash=?, active=1 WHERE username=?", (hash_password(password), username))
    conn.commit()
    click.echo(f"Password updated for {username}")


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(create_user_command)
    app.cli.add_command(set_password_command)
    app.cli.add_command(seed_demo_command)
