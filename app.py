"""Entry point. Dev: `flask --app app run --debug`. Prod: `gunicorn -w 4 -b 127.0.0.1:8000 app:app`."""
from lims import create_app

app = create_app()
