"""The Supabase Storage client, exercised against a fake HTTP layer (no network)."""
import io
import json
import urllib.request

import pytest

from lims import storage


class FakeResponse:
    def __init__(self, status, body=b""):
        self.status, self._body = status, body
    def read(self): return self._body
    def __enter__(self): return self
    def __exit__(self, *a): pass


def test_supabase_storage_put_get_and_cache(app, monkeypatch, tmp_path):
    calls = []
    objects = {}

    def fake_urlopen(req, timeout=0):
        calls.append((req.get_method(), req.full_url, dict(req.header_items())))
        assert req.get_header("Authorization") == "Bearer service-key"
        if req.full_url.endswith("/storage/v1/bucket"):
            assert json.loads(req.data)["public"] is False
            return FakeResponse(200, b'{"name":"b"}')
        if req.get_method() == "POST":
            objects[req.full_url] = req.data
            return FakeResponse(200, b"{}")
        return FakeResponse(200, objects[req.full_url])

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    app.config.update(SUPABASE_URL="https://ref.supabase.co/", SUPABASE_SERVICE_KEY="service-key", STORAGE_BUCKET="b")
    with app.app_context():
        be = storage.backend()
        assert isinstance(be, storage.SupabaseStorage)
        be.cache = str(tmp_path / "cache")
        size, md5 = be.put("IGI-X/1_trace.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")
        assert (size, md5) == (8, "e5ebd4c02cefbe7955977c67ada242b7")
        assert calls[0][1] == "https://ref.supabase.co/storage/v1/bucket"            # bucket ensured first
        assert calls[1][1] == "https://ref.supabase.co/storage/v1/object/b/IGI-X/1_trace.csv"
        assert calls[1][2]["X-upsert"] == "true" and calls[1][2]["Content-type"] == "text/csv"
        path = be.local_path("IGI-X/1_trace.csv")
        assert open(path, "rb").read() == b"a,b\n1,2\n"
        n = len(calls)
        assert be.local_path("IGI-X/1_trace.csv") == path and len(calls) == n   # cached, no second download


def test_local_storage_is_default(app, tmp_path):
    app.config.update(SUPABASE_URL=None, ATTACHMENT_DIR=str(tmp_path))
    with app.app_context():
        be = storage.backend()
        assert isinstance(be, storage.LocalStorage)
        size, md5 = be.put("shared/x.txt", io.BytesIO(b"hello"))
        assert size == 5 and open(be.local_path("shared/x.txt")).read() == "hello"
