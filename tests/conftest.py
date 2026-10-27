import os
import tempfile
import pytest

from lims import create_app
from lims.db import init_db, reset_db, get_db
from lims.auth import create_user

# Set LIMS_TEST_DATABASE_URL=postgresql://... to run the whole suite against PostgreSQL instead of SQLite.
PG_URL = os.environ.get("LIMS_TEST_DATABASE_URL")

# Participant P101 / UNC316 in cohort MP, as in the nomenclature's worked example.
P = "IGI-MP-P101-UNC316-26SEP29-"          # segments 1-5 of every tube from a collection received 2026-09-29


def sid(specimen, fraction, material, aliquot=1, op="AA", processed="26SEP29", received="26SEP29"):
    return f"IGI-MP-P101-UNC316-{received}-{specimen}-{fraction}-{material}-{aliquot:02d}-{op}-{processed}"


@pytest.fixture
def app():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app = create_app({"TESTING": True, "DATABASE": path, "DATABASE_URL": PG_URL, "SECRET_KEY": "test", "WTF_CSRF_ENABLED": False})
    with app.app_context():
        if PG_URL:
            reset_db()
        else:
            init_db()
        conn = get_db()
        create_user(conn, "alice", "Alice A", "AA", "password1", "admin")
        create_user(conn, "bob", "Bob B", "BB", "password1", "user")
        create_user(conn, "vic", "Vic V", "VV", "password1", "viewer")
        create_user(conn, "mf", "Misha F", "MF", "password1", "user")
        create_user(conn, "ken", "Ken K", "KEN", "password1", "user")
        conn.execute("INSERT INTO participant(participant_id, cohort_code, unc_number, site_code) VALUES ('P101','MP','316','UNC')")
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
              "freezer": "NA", "rack": "NA", "box": "NA", "position": "A1", "notes": "NA"}

COLL_FIELDS = {"participant_id": "P101", "received_date": "2026-09-29", "specimen_code": "PF", "site_code": "UNC",
               "biobank_source": "IH", "received_from": "PIRL", "received_by": "AA", "container_type": "BAG",
               "transport_temp": "ambient", "appearance": "turbid", "quantity": "400", "unit": "mL", "notes": "NA"}


def new_collection(client, **over):
    """Register a collection; returns its id (or the response if it was refused)."""
    r = client.post("/collections/new", data={**COLL_FIELDS, **over})
    if r.status_code == 302 and "/collections/" in r.headers["Location"]:
        return int(r.headers["Location"].split("/collections/")[1].split("/")[0])
    return r


def add_tubes(client, collection_id, **over):
    data = {"fraction": "PFM", "material": "CPU", "count": "1", "quantity": "1", "unit": "mL", "created_by": "AA", **ALL_FIELDS}
    data.update(over)
    return client.post(f"/collections/{collection_id}/tubes", data=data, follow_redirects=True)


def make_root(client, specimen="PF", received_date="2026-09-29", **over):
    """A collection plus one first-generation tube (PFM-CPU by default). Returns the tube-creation response."""
    cid = new_collection(client, specimen_code=specimen, received_date=received_date)
    assert isinstance(cid, int), cid.data[:500]
    return add_tubes(client, cid, **over)


def derive(client, parent, **over):
    data = {"fraction": "", "material": "", "count": "1", "quantity": "1", "unit": "NA", "created_by": "AA", **ALL_FIELDS}
    data.update(over)
    if data["material"] == "PEP":
        data.setdefault("attr_hla_class", "I")
    return client.post(f"/samples/{parent}/derive", data=data, follow_redirects=True)
