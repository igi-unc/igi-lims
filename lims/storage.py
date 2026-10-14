"""Where attachment bytes live.

* ``LocalStorage`` (default): files under ``ATTACHMENT_DIR``.
* ``SupabaseStorage``: a private bucket in Supabase Storage, used when the app runs on
  Vercel, whose filesystem does not persist between requests. Configured by
  LIMS_SUPABASE_URL, LIMS_SUPABASE_SERVICE_KEY and LIMS_STORAGE_BUCKET. The plain
  REST API is used so no SDK is needed; the service key never reaches the browser.

Both expose ``put(rel, stream, content_type) -> (size, md5)`` and
``local_path(rel) -> path`` (a readable file on local disk; for Supabase a cached
download under the system temp directory, which is what the QC parsers need).
"""
import hashlib
import json
import os
import tempfile
import urllib.request
import urllib.error

from flask import current_app


class LocalStorage:
    def __init__(self, root):
        self.root = root

    def put(self, rel, stream, content_type=None):
        full = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        h, size = hashlib.md5(), 0
        with open(full, "wb") as out:
            while True:
                chunk = stream.read(1 << 20)
                if not chunk:
                    break
                h.update(chunk); size += len(chunk); out.write(chunk)
        return size, h.hexdigest()

    def local_path(self, rel):
        return os.path.join(self.root, rel)


class SupabaseStorage:
    def __init__(self, url, service_key, bucket):
        self.url = url.rstrip("/")
        self.key = service_key
        self.bucket = bucket
        self._ensured = False
        self.cache = os.path.join(tempfile.gettempdir(), "igi-lims-attachments")

    def _req(self, method, path, data=None, content_type=None, ok=(200, 201)):
        req = urllib.request.Request(self.url + path, data=data, method=method)
        req.add_header("Authorization", "Bearer " + self.key)
        req.add_header("apikey", self.key)
        if content_type:
            req.add_header("Content-Type", content_type)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            if e.code in ok:
                return e.code, e.read()
            raise RuntimeError(f"Supabase Storage {method} {path}: HTTP {e.code} {e.read()[:200]!r}")

    def ensure_bucket(self):
        if self._ensured:
            return
        body = json.dumps({"id": self.bucket, "name": self.bucket, "public": False}).encode()
        self._req("POST", "/storage/v1/bucket", body, "application/json", ok=(200, 201, 409))   # 409: already exists
        self._ensured = True

    def put(self, rel, stream, content_type=None):
        self.ensure_bucket()
        data = stream.read()
        req = urllib.request.Request(f"{self.url}/storage/v1/object/{self.bucket}/{rel}", data=data, method="POST")
        req.add_header("Authorization", "Bearer " + self.key)
        req.add_header("apikey", self.key)
        req.add_header("Content-Type", content_type or "application/octet-stream")
        req.add_header("x-upsert", "true")
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                r.read()
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Supabase Storage upload failed: HTTP {e.code} {e.read()[:200]!r}")
        return len(data), hashlib.md5(data).hexdigest()

    def get(self, rel):
        _, data = self._req("GET", f"/storage/v1/object/{self.bucket}/{rel}")
        return data

    def local_path(self, rel):
        full = os.path.join(self.cache, rel)
        if not os.path.exists(full):
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb") as out:
                out.write(self.get(rel))
        return full


def backend():
    cfg = current_app.config
    if cfg.get("SUPABASE_URL") and cfg.get("SUPABASE_SERVICE_KEY"):
        return SupabaseStorage(cfg["SUPABASE_URL"], cfg["SUPABASE_SERVICE_KEY"], cfg.get("STORAGE_BUCKET") or "lims-attachments")
    return LocalStorage(cfg["ATTACHMENT_DIR"])
