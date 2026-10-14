"""The demo seed must pass the same rules and vocabularies as the forms."""
from lims.db import get_db
from lims.demo import seed_demo


def test_seed_demo_builds_a_full_tree(app, client):
    with app.app_context():
        conn = get_db()
        info = seed_demo(conn, "bob")      # bob requests, alice (admin) approves the first request
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
        assert conn.execute("SELECT status FROM approval_request WHERE id=?", (info["approved_request"],)).fetchone()[0] == "approved"
        assert conn.execute("SELECT status FROM approval_request WHERE id=?", (info["pending_request"],)).fetchone()[0] == "pending"
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
