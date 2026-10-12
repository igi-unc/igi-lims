import os
import sqlite3
import click
from flask import current_app, g

from . import seed as seed_module


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


def init_db(conn=None):
    conn = conn or get_db()
    with current_app.open_resource("schema.sql") as f:
        conn.executescript(f.read().decode("utf8"))
    seed_module.seed(conn)
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


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    app.cli.add_command(create_user_command)
