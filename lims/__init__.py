import os
from flask import Flask, render_template, g

from . import db, auth


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object("config")
    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    app.register_blueprint(auth.bp)

    from .views import main, samples, participants, approvals, admin, api
    for m in (main, samples, participants, approvals, admin, api):
        app.register_blueprint(m.bp)

    @app.context_processor
    def inject():
        from .db import get_db
        pending = 0
        if getattr(g, "user", None):
            pending = get_db().execute("SELECT COUNT(*) FROM approval_request WHERE status='pending'").fetchone()[0]
        return {"pending_count": pending}

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("error.html", code=403, message="You do not have permission to do that."), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", code=404, message="Not found."), 404

    return app
