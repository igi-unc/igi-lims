"""Label preview with a Data Matrix barcode of the sample ID."""
from lims.db import get_db
from conftest import make_root, login


def test_label_svg(app, alice, client):
    make_root(alice)
    with app.app_context():
        sid = get_db().execute("SELECT sample_id FROM sample").fetchone()[0]
    r = alice.get(f"/samples/{sid}/label.svg")
    assert r.status_code == 200 and r.mimetype == "image/svg+xml"
    body = r.data.decode()
    assert body.startswith("<svg") and "<path" in body
    for row in (sid.split("-")[0], "PF-BLK", "NAT-01", "AA"):
        assert row in body
    assert alice.get(f"/samples/{sid}").data.count(b"label.svg") == 1
    assert alice.get("/samples/IGI-XX-NOPE/label.svg").status_code == 404
    # viewers can see labels; anonymous users cannot
    login(client, "vic")
    assert client.get(f"/samples/{sid}/label.svg").status_code == 200
    client.get("/logout")
    assert client.get(f"/samples/{sid}/label.svg").status_code in (302, 401)


def test_barcode_matrix_is_square_and_sized_for_v21():
    from lims.labels import barcode_matrix
    m = barcode_matrix("IGI-MP-P101-UNC316-26SEP29-PF-TUM-HMD-01-KEN-26OCT06")
    assert len(m) == len(m[0]) and len(m) <= 32
