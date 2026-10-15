"""The demo seed must pass the same rules and vocabularies as the forms."""
from lims.db import get_db
from lims.demo import seed_demo


def test_seed_demo_builds_a_full_tree(app, client):
    with app.app_context():
        conn = get_db()
        info = seed_demo(conn, "bob")      # bob seeds; alice (admin) makes the second edit
        conn.commit()
        pid = info["participant"]
        n = conn.execute("SELECT count(*) FROM sample WHERE participant_id=?", (pid,)).fetchone()[0]
        assert n == info["tubes"] >= 30
        assert len(info["roots"]) == 3
        # every non-root tube points at a tube of the same participant, and roots are consistent
        bad = conn.execute("SELECT count(*) FROM sample s JOIN sample p ON p.sample_id = s.parent_id "
                           "WHERE s.participant_id=? AND (p.participant_id <> s.participant_id OR p.root_id <> s.root_id)", (pid,)).fetchone()[0]
        assert bad == 0
        libs = conn.execute("SELECT sample_id FROM sample WHERE participant_id=? AND material_code='LIB'", (pid,)).fetchall()
        assert len(libs) == 6
        for (sid,) in libs:
            assert conn.execute("SELECT 1 FROM data_file WHERE sample_id=?", (sid,)).fetchone()
            assert conn.execute("SELECT value FROM sample_attribute WHERE sample_id=? AND key='assay'", (sid,)).fetchone()
        assert info["second"] == "alice" and len(info["edits"]) == 2
        who = [r[0] for r in conn.execute("SELECT username FROM audit_log WHERE action='update' AND reason IS NOT NULL ORDER BY id")]
        assert who == ["bob", "alice"]
        # re-running refuses rather than duplicating
        try:
            seed_demo(conn, "bob")
            assert False, "second seed should fail"
        except ValueError as e:
            assert "already exists" in str(e)
    # the tree renders for a viewer
    from conftest import login
    login(client, "vic")
    r = client.get(f"/browse?participant={pid}")
    assert r.status_code == 200 and info["roots"][0].encode() in r.data
    r = client.get(f"/api/samples/{info['roots'][0]}/lineage")
    assert r.status_code == 200 and len(r.get_json()["descendants"]) >= 15


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
        assert users == ["demo", "reviewer", "viewer"]          # the fixture's alice/bob/vic are gone
        assert conn.execute("SELECT count(*) FROM participant").fetchone()[0] == 4   # main + three smaller ones
        cohorts = sorted(r[0] for r in conn.execute("SELECT cohort_code FROM participant"))
        assert cohorts == ["AM", "MP", "NC", "TN"]
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
        extra = seed_extra_participants(conn, "bob")
        conn.commit()
        assert len(extra) == 3 and all(n >= 8 for n in extra.values())
        for pid in extra:
            bad = conn.execute("SELECT count(*) FROM sample s JOIN sample p ON p.sample_id = s.parent_id "
                               "WHERE s.participant_id=? AND p.participant_id <> s.participant_id", (pid,)).fetchone()[0]
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
