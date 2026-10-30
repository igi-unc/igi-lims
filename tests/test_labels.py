"""Label preview: three rows of at most 18 characters beside a Data Matrix of the full sample ID."""
import re
from lims.db import get_db
from conftest import sid, make_root, login


def test_label_svg(app, alice, client):
    make_root(alice, created_by="KEN")
    s = sid("PF", "PFM", "CPU", op="KEN")
    r = alice.get(f"/samples/{s}/label.svg")
    assert r.status_code == 200 and r.mimetype == "image/svg+xml"
    body = r.data.decode()
    assert body.startswith("<svg") and "<path" in body
    rows = re.findall(r"<text [^>]*>([^<]*)</text>", body)
    assert rows == ["IGI-MP-P101-UNC316", "26SEP29-PF-PFM-CPU", "01-KEN-26SEP29"]
    assert "-".join(rows) == s and all(len(x) <= 18 for x in rows)
    assert alice.get(f"/samples/{s}").data.count(b"label.svg") == 1
    assert alice.get("/samples/IGI-XX-NOPE/label.svg").status_code == 404
    login(client, "vic")
    assert client.get(f"/samples/{s}/label.svg").status_code == 200
    client.get("/logout")
    assert client.get(f"/samples/{s}/label.svg").status_code in (302, 401)


def test_barcode_matrix_is_square_and_sized_for_v21():
    from lims.labels import barcode_matrix
    m = barcode_matrix("IGI-MP-P101-UNC316-26SEP29-PF-TUM-HMD-01-KEN-26OCT06")
    assert len(m) == len(m[0]) and len(m) <= 32


def test_scan_page(app, client):
    """The camera scan page: behind the login, for every reading role, with the ID pattern and the pinned reader."""
    assert client.get("/scan").status_code == 302                         # not logged in
    login(client, "vic")
    page = client.get("/scan").data.decode()
    assert "sc-video" in page and "scan.js" in page and "barcode-detector@" in page
    assert '"pattern": "^(IGI)-' in page or "^(IGI)-" in page
    assert 'href="/scan"' in page                                          # in the menu
    js = client.get("/static/scan.js").data.decode()
    assert "data_matrix" in js and "not an IGI tube ID" in js
