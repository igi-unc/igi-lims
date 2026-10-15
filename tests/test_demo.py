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
        assert conn.execute("SELECT count(*) FROM participant").fetchone()[0] == 1
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
