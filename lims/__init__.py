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

    from .views import main, samples, participants, admin, api, qcimport, demo, collections, printing
    for m in (main, samples, participants, admin, api, qcimport, demo, collections, printing):
        app.register_blueprint(m.bp)

    @app.template_filter("yymmmdd")
    def yymmmdd(value):
        """ISO date -> 26SEP29, as printed in sample IDs."""
        from .ids import format_yymmmdd
        try:
            return format_yymmmdd(value) if value else ""
        except (ValueError, TypeError):
            return value

    @app.template_filter("serial7")
    def serial7(n):
        """LIMS number as printed: seven digits, zero-padded."""
        return f"{int(n):07d}" if n is not None else ""

    @app.template_filter("short_id")
    def short_id(sample_id):
        """Fraction-material-aliquot part of a sample ID (what distinguishes tubes within a collection)."""
        from .ids import segment_names
        if not sample_id:
            return ""
        parts = dict(zip(segment_names(), sample_id.split(app.config["ID_SEPARATOR"])))
        return "-".join(parts.get(k, "") for k in ("fraction", "material", "aliquot"))

    @app.template_filter("kv")
    def kv(text):
        """Render a JSON object as 'key: value' lines for the audit views."""
        import json
        from markupsafe import Markup, escape
        if not text:
            return ""
        try:
            obj = json.loads(text)
        except (TypeError, ValueError):
            return text
        if not isinstance(obj, dict):
            return text
        rows = "".join(f"<div><span class='k'>{escape(k)}</span> {escape('' if v is None else v)}</div>"
                       for k, v in obj.items())
        return Markup(f"<div class='kv'>{rows}</div>")

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("error.html", code=403, message="You do not have permission to do that."), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", code=404, message="Not found."), 404

    return app
