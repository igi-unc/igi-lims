"""The demo seed must pass the same rules and vocabularies as the forms."""
from lims.db import get_db
from lims.demo import seed_demo


def _drop_fixture_participant(conn):
    conn.execute("DELETE FROM participant WHERE participant_id='P101'")   # the fixture's P101; the demo creates its own


def test_seed_demo_builds_the_worked_example(app, client):
    with app.app_context():
        conn = get_db()
        _drop_fixture_participant(conn)
        info = seed_demo(conn, "bob")      # bob seeds; alice (admin) makes the second edit
        conn.commit()
        assert info["participant"] == "P101" and info["unc_id"] == "UNC316"
        n = conn.execute("SELECT count(*) FROM sample WHERE participant_id='P101'").fetchone()[0]
        assert n == info["tubes"] >= 35 and len(info["collections"]) == 2
        # every tube's parent is in the same collection; first-generation tubes are their own root
        bad = conn.execute("SELECT count(*) FROM sample s JOIN sample p ON p.sample_id = s.parent_id "
                           "WHERE p.collection_id <> s.collection_id OR p.root_id <> s.root_id").fetchone()[0]
        assert bad == 0
        assert conn.execute("SELECT count(*) FROM sample WHERE parent_id IS NULL AND root_id <> sample_id").fetchone()[0] == 0
        # the document's back-tracking example
        hmd = "IGI-MP-P101-UNC316-26SEP29-PF-TUM-HMD-01-KEN-26OCT06"
        f = conn.execute("SELECT uri, assay_code, platform_code FROM data_file WHERE sample_id=?", (hmd,)).fetchone()
        assert f[0].endswith(hmd + "_tumor_DNA_WGS_ONT.bam") and (f[1], f[2]) == ("WGS", "ONT")
        assert info["second"] == "alice" and len(info["edits"]) == 2
        who = [r[0] for r in conn.execute("SELECT username FROM audit_log WHERE action='update' AND reason IS NOT NULL "
                                          "AND table_name='sample' ORDER BY id")]
        assert who == ["bob", "alice"]
        assert conn.execute("SELECT count(*) FROM sample_correction").fetchone()[0] == 1
        try:
            seed_demo(conn, "bob")
            assert False, "second seed should fail"
        except ValueError as e:
            assert "already exists" in str(e)
    from conftest import login
    login(client, "vic")
    r = client.get("/browse?participant=P101")
    assert r.status_code == 200 and hmd.encode() in r.data
    r = client.get(f"/api/samples/IGI-MP-P101-UNC316-26SEP29-PF-PFM-CPU-03-MF-26SEP29/lineage")
    assert r.status_code == 200 and len(r.get_json()["descendants"]) >= 10


def test_demo_reset_and_cron_endpoint(app, client):
    app.config.update(DEMO_MODE=True, DEMO_PASSWORD="pw-for-demo", CRON_SECRET="s3cret")
    # unauthenticated / wrong secret are refused; the right header rebuilds everything
    assert client.get("/cron/demo-reset").status_code == 401
    assert client.get("/cron/demo-reset", headers={"Authorization": "Bearer nope"}).status_code == 401
    r = client.get("/cron/demo-reset", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200 and r.get_json()["tubes"] >= 30
    with app.app_context():
        conn = get_db()
        users = sorted(r[0] for r in conn.execute("SELECT username FROM account"))
        assert users == ["demo", "ken", "mf", "reviewer", "station", "viewer"]     # the fixture's accounts are gone; operators MF and KEN added
        assert conn.execute("SELECT count(*) FROM participant").fetchone()[0] == 4   # main + three smaller ones
        cohorts = sorted(r[0] for r in conn.execute("SELECT cohort_code FROM participant"))
        assert cohorts == ["AM", "MP", "NC", "TN"]
        assert sorted(r[0] for r in conn.execute("SELECT participant_id FROM participant")) == ["P101", "P102", "P103", "P104"]
        # a collection with no tubes yet (P104's blood)
        assert conn.execute("SELECT count(*) FROM collection c WHERE NOT EXISTS (SELECT 1 FROM sample s WHERE s.collection_id=c.collection_id)").fetchone()[0] == 1
        statuses = {r[0] for r in conn.execute("SELECT DISTINCT status FROM sample")}
        assert {"Available", "Depleted", "In use", "Shipped", "Destroyed"} <= statuses
    # login page names the accounts but never shows the password; the demo admin can reset again from the dashboard
    r = client.get("/login")
    assert b"Demonstration instance" in r.data and b"viewer" in r.data
    assert b"pw-for-demo" not in r.data
    from conftest import login
    login(client, "demo", "pw-for-demo")
    r = client.post("/demo/reset", follow_redirects=True)
    assert r.status_code == 200 and b"Demo data rebuilt" in r.data
    # outside demo mode the endpoints do not exist
    app.config.update(DEMO_MODE=False)
    assert client.get("/cron/demo-reset", headers={"Authorization": "Bearer s3cret"}).status_code == 404
    assert client.post("/demo/reset").status_code == 404


def test_login_on_uninitialised_database_explains(app, client):
    """A fresh Postgres/SQLite with no tables gives a readable message instead of a 500."""
    from lims.db import get_db, ALL_TABLES, is_postgres
    with app.app_context():
        conn = get_db()
        cascade = " CASCADE" if is_postgres(conn) else ""
        for t in ALL_TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {t}{cascade}")
        conn.commit()
    r = client.post("/login", data={"username": "demo", "password": "x"})
    assert r.status_code == 200 and b"no tables yet" in r.data


def test_extra_participants_follow_the_rules(app, client):
    from lims.demo import seed_extra_participants
    with app.app_context():
        conn = get_db()
        _drop_fixture_participant(conn)
        extra = seed_extra_participants(conn, "bob")
        conn.commit()
        assert sorted(extra) == ["P102", "P103", "P104"] and all(n >= 4 for n in extra.values())
        for pid in extra:
            bad = conn.execute("SELECT count(*) FROM sample s JOIN sample p ON p.sample_id = s.parent_id "
                               "WHERE s.participant_id=? AND p.collection_id <> s.collection_id", (pid,)).fetchone()[0]
            assert bad == 0
        try:
            seed_extra_participants(conn, "bob")
            assert False, "second seed should fail"
        except ValueError as e:
            assert "already exists" in str(e)
    from conftest import login
    login(client, "vic")
    for pid in extra:
        assert client.get(f"/browse?participant={pid}").status_code == 200


def test_postgres_tables_are_locked_down(app):
    """On Supabase every public table is reachable through the REST API; init must turn RLS on for all of them."""
    import pytest
    from lims.db import get_db, is_postgres, ALL_TABLES
    with app.app_context():
        conn = get_db()
        if not is_postgres(conn):
            pytest.skip("Postgres only")
        off = [r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND NOT rowsecurity")]
        assert off == []
        assert conn.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public' AND rowsecurity").fetchone()[0] >= len(ALL_TABLES) - 1


def test_missing_table_is_created_on_first_request(app, alice):
    """A redeploy that adds a table must not 500 before the next reset."""
    from lims.db import get_db, is_postgres
    from conftest import make_root
    make_root(alice)
    with app.app_context():
        conn = get_db()
        sid = conn.execute("SELECT sample_id FROM sample").fetchone()[0]
        conn.execute("DROP TABLE sample_correction" + (" CASCADE" if is_postgres(conn) else ""))
        conn.commit()
    app.extensions.pop("igi_schema_ok", None)      # as on a fresh serverless instance
    r = alice.get(f"/samples/{sid}")
    assert r.status_code == 200
    with app.app_context():
        assert get_db().execute("SELECT count(*) FROM sample_correction").fetchone()[0] == 0
        assert get_db().execute("SELECT count(*) FROM sample").fetchone()[0] == 1   # nothing lost


def test_v2_database_is_rebuilt_in_demo_mode(app, client):
    """A demo database left over from nomenclature v2 (no collection_id column) is rebuilt on the first request."""
    from lims.db import get_db, is_postgres
    app.config.update(DEMO_MODE=True, DEMO_PASSWORD="pw-for-demo")
    with app.app_context():
        conn = get_db()
        conn.execute("DROP TABLE sample_correction" + (" CASCADE" if is_postgres(conn) else ""))
        conn.execute("DROP TABLE sample" + (" CASCADE" if is_postgres(conn) else ""))
        conn.execute("CREATE TABLE sample (sample_id TEXT PRIMARY KEY, collection_date TEXT)")
        conn.commit()
    app.extensions.pop("igi_schema_ok", None)
    assert client.get("/login").status_code == 200
    with app.app_context():
        assert get_db().execute("SELECT count(*) FROM participant").fetchone()[0] == 4
