import os
import tempfile
import pytest

from lims import create_app
from lims.db import init_db, get_db
from lims.auth import create_user


@pytest.fixture
def app():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app({"TESTING": True, "DATABASE": path, "SECRET_KEY": "test", "WTF_CSRF_ENABLED": False})
    with app.app_context():
        init_db()
        conn = get_db()
        create_user(conn, "alice", "Alice A", "AA", "password1", "admin")
        create_user(conn, "bob", "Bob B", "BB", "password1", "user")
        create_user(conn, "vic", "Vic V", "VV", "password1", "viewer")
        conn.execute("INSERT INTO participant(participant_id, cohort_code, external_participant_id, site_code) VALUES ('KXRTQVA','MP','UNC316','UNC')")
        conn.commit()
    yield app
    for suffix in ("", "-wal", "-shm"):
        try:
            os.unlink(path + suffix)
        except FileNotFoundError:
            pass


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, username, password="password1"):
    return client.post("/login", data={"username": username, "password": password}, follow_redirects=True)


@pytest.fixture
def alice(client):
    login(client, "alice")
    return client


ALL_FIELDS = {"created_datetime": "2026-09-29T10:00", "sop_code": "NA", "biobank_source": "IH", "status": "Available",
              "freezer": "F1", "rack": "R1", "box": "B1", "position": "A1", "notes": "NA"}


def make_root(client, **over):
    data = {"participant": "KXRTQVA", "collection_date": "2026-09-29", "specimen": "PF", "fraction": "BLK",
            "material": "NAT", "count": "1", "quantity": "500", "unit": "mL", "created_by": "MF", **ALL_FIELDS}
    data.update(over)
    return client.post("/samples/new", data=data, follow_redirects=True)


def derive(client, parent, **over):
    data = {"fraction": "", "material": "", "count": "1", "quantity": "1", "unit": "NA", "created_by": "MF", **ALL_FIELDS}
    data.update(over)
    # required metadata for some materials (see lims/seed_attributes.py)
    if data["material"] == "LIB":
        data.setdefault("attr_assay", "ONT")
    if data["material"] == "PEP":
        data.setdefault("attr_hla_class", "I")
    return client.post(f"/samples/{parent}/derive", data=data, follow_redirects=True)
