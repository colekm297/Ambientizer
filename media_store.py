"""media_store.py — cloud offload for Ambientizer's media files (R2/S3-compatible).

The problem: output/ holds ~100 GB of audio and video the app still needs to
serve, and the Mac keeps running out of disk. The fix is NOT moving the app's
source of truth — job JSONs keep their local paths untouched. Instead:

  * A MANIFEST (output/cloud_manifest.json) maps each offloaded local path to
    its object key, size, and sha256. The manifest is the only new state.
  * upload() streams a file to the bucket and verifies the stored object's
    sha256 against the local file before the manifest records it.
  * evict() deletes the local copy ONLY for files the manifest shows verified.
  * resolve()/presign_for_path() let the app serve an offloaded file via a
    time-limited signed URL — R2 supports HTTP Range on signed GETs, so
    seeking in hour-long videos and audio scrubbing keep working.

Config comes from .env (same convention as every other credential here):
    R2_ACCOUNT_ID=...       # Cloudflare account id (the hex in the dashboard URL)
    R2_ACCESS_KEY_ID=...    # R2 API token -> access key
    R2_SECRET_ACCESS_KEY=...
    R2_BUCKET=ambientizer-media

If unset, MediaStore.enabled is False and the app behaves exactly as before —
this module is inert until credentials exist.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = PROJECT_ROOT / "output" / "cloud_manifest.json"
_CHUNK = 8 * 1024 * 1024


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(_CHUNK), b""):
            h.update(b)
    return h.hexdigest()


def etag_of(path: str) -> str:
    """The ETag R2 gives this file: the md5 of its 8 MiB part md5s. A match proves the stored bytes without a
    download. The sha256 in an object's metadata doesn't, since it's computed before the upload."""
    parts = []
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(_CHUNK), b""):
            parts.append(hashlib.md5(b).digest())
    if len(parts) == 1:
        return parts[0].hex()
    return f"{hashlib.md5(b''.join(parts)).hexdigest()}-{len(parts)}"


class MediaStore:
    def __init__(self):
        self.account = os.environ.get("R2_ACCOUNT_ID", "")
        self.key_id = os.environ.get("R2_ACCESS_KEY_ID", "")
        self.secret = os.environ.get("R2_SECRET_ACCESS_KEY", "")
        self.bucket = os.environ.get("R2_BUCKET", "ambientizer-media")
        self._client = None
        self._lock = threading.Lock()
        self._manifest = None

    @property
    def enabled(self) -> bool:
        return bool(self.account and self.key_id and self.secret)

    @property
    def client(self):
        if self._client is None:
            import boto3
            from botocore.config import Config
            self._client = boto3.client(
                "s3",
                endpoint_url=f"https://{self.account}.r2.cloudflarestorage.com",
                aws_access_key_id=self.key_id,
                aws_secret_access_key=self.secret,
                region_name="auto",
                config=Config(retries={"max_attempts": 4, "mode": "adaptive"}),
            )
        return self._client

    # ── manifest ──────────────────────────────────────────────────────────
    def manifest(self) -> dict:
        # Reload when another process (offload_release.py, stock_campaign.py) has rewritten the file,
        # or the app keeps 404ing files evicted after it started.
        with self._lock:
            try:
                mtime = os.path.getmtime(MANIFEST_PATH)
            except OSError:
                mtime = None
            if self._manifest is None or mtime != getattr(self, "_manifest_mtime", None):
                try:
                    self._manifest = json.load(open(MANIFEST_PATH))
                except Exception:
                    self._manifest = self._manifest or {}
                self._manifest_mtime = mtime
            return self._manifest

    def _commit(self, key: str, entry: dict) -> None:
        """Write one entry on top of what's on disk now, under a lock shared with other processes. Each process
        caches the manifest, so saving its whole copy would drop what the others wrote since."""
        with self._lock, open(str(MANIFEST_PATH) + ".lock", "w") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            fresh = json.load(open(MANIFEST_PATH)) if MANIFEST_PATH.exists() else {}   # unreadable raises: never wipe it
            fresh[key] = entry
            tmp = f"{MANIFEST_PATH}.{os.getpid()}.tmp"
            with open(tmp, "w") as fh:
                json.dump(fresh, fh, indent=1)
            os.replace(tmp, MANIFEST_PATH)
            self._manifest, self._manifest_mtime = fresh, os.path.getmtime(MANIFEST_PATH)

    # ── operations ────────────────────────────────────────────────────────
    def upload(self, path: str, verify: bool = True) -> Optional[str]:
        """Upload one file; verify round-trip hash; record in manifest.
        Returns the object key, or None on any failure (manifest untouched)."""
        if not self.enabled or not os.path.exists(path):
            return None
        key = self.relkey(path)
        digest = _sha256(path)
        size = os.path.getsize(path)
        extra = {"Metadata": {"sha256": digest}}
        from boto3.s3.transfer import TransferConfig
        self.client.upload_file(path, self.bucket, key, ExtraArgs=extra,
                                Config=TransferConfig(multipart_threshold=_CHUNK, multipart_chunksize=_CHUNK))
        if verify:
            head = self.client.head_object(Bucket=self.bucket, Key=key)
            if head["ContentLength"] != size or head["ETag"].strip('"') != etag_of(path):
                # wrong object landed — do not record it as safe
                return None
        self._commit(key, {"size": size, "sha256": digest,
                           "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                           "local_path": str(Path(path).resolve()), "evicted": False})
        return key

    def adopt(self, path: str) -> Optional[str]:
        """Record an object that is ALREADY in the bucket, without re-uploading.

        Files pushed by hand (the Aug 23 2026 Sirens recovery) exist remotely
        but the manifest never learns of them, so every later check reports
        them missing and every offload re-sends gigabytes. Adopt only when the
        remote sha256 metadata matches the local file; otherwise return None
        and let the caller upload for real."""
        if not self.enabled or not os.path.exists(path):
            return None
        key = self.relkey(path)
        try:
            head = self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception:
            return None
        digest = _sha256(path)
        size = os.path.getsize(path)
        if head["ContentLength"] != size or head.get("Metadata", {}).get("sha256") != digest:
            return None
        self._commit(key, {"size": size, "sha256": digest,
                           "uploaded_at": head["LastModified"].strftime("%Y-%m-%dT%H:%M:%S"),
                           "local_path": str(Path(path).resolve()), "evicted": False,
                           "adopted": True})
        return key

    def evict(self, path: str) -> bool:
        """Delete the LOCAL copy of a file the manifest shows verified-uploaded."""
        key = self.relkey(path)
        m = self.manifest()
        ent = m.get(key)
        if not ent or ent.get("evicted"):
            return False
        # paranoia: re-check the local file still matches what we uploaded —
        # if it changed since upload, evicting would lose the newer version.
        if not os.path.exists(path) or _sha256(path) != ent["sha256"]:
            return False
        # and that the bucket really holds these bytes, right before the only local copy goes
        head = self.client.head_object(Bucket=self.bucket, Key=key)
        if head["ContentLength"] != ent["size"] or head["ETag"].strip('"') != etag_of(path):
            return False
        os.unlink(path)
        self._commit(key, {**ent, "evicted": True})
        return True

    def lookup(self, path: str) -> Optional[dict]:
        """Manifest entry for a local path (whether or not still on disk)."""
        return self.manifest().get(self.relkey(path))

    def presign_for_path(self, path: str, expires: int = 3600) -> Optional[str]:
        ent = self.lookup(path)
        if not ent:
            return None
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": self.relkey(path)},
            ExpiresIn=expires)

    def restore(self, path: str) -> bool:
        """Download an evicted file back to its original local path."""
        ent = self.lookup(path)
        if not ent:
            return False
        key = self.relkey(path)
        tmp = path + ".restore-tmp"
        self.client.download_file(self.bucket, key, tmp)
        if _sha256(tmp) != ent["sha256"]:
            os.unlink(tmp)
            return False
        os.replace(tmp, path)
        self._commit(key, {**ent, "evicted": False})
        return True


_store: Optional[MediaStore] = None


def get_store() -> MediaStore:
    global _store
    if _store is None:
        _store = MediaStore()
    return _store
