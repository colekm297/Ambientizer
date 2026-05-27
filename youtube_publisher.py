"""
youtube_publisher.py — YouTube Data API v3 integration for uploading videos.

Handles OAuth 2.0 authentication flow and resumable video uploads.
Requires a client_secret.json file from Google Cloud Console with
YouTube Data API v3 enabled.

Setup:
  1. Go to https://console.cloud.google.com/
  2. Create a project (or use existing)
  3. Enable "YouTube Data API v3"
  4. Go to Credentials → Create OAuth 2.0 Client ID (Desktop app)
  5. Download JSON → save as client_secret.json in project root
"""

import os
import json
import time
import fcntl
import tempfile
import subprocess
import httplib2
from pathlib import Path
from typing import Optional, Callable

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError, MediaUploadSizeError

# YouTube hard caps custom thumbnails at 2 MB.
YT_THUMB_MAX_BYTES = 2 * 1024 * 1024


def _prepare_thumbnail(src_path: str) -> tuple[str, str, bool]:
    """Return (path, mimetype, is_temp) for a YouTube-acceptable thumbnail.

    If the source is already <= 2 MB, returns it as-is with a sniffed mimetype.
    Otherwise re-encodes to a JPEG sized to 1280x720, stepping quality down
    until it fits under the 2 MB cap. The returned path may be a tempfile that
    the caller is responsible for deleting (is_temp=True).
    """
    if not src_path or not os.path.exists(src_path):
        return src_path, "image/png", False

    size = os.path.getsize(src_path)
    ext = Path(src_path).suffix.lower()
    if size <= YT_THUMB_MAX_BYTES:
        mimetype = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
        return src_path, mimetype, False

    # Re-encode via ffmpeg. Scale down to 1280x720 (YT recommended), then walk
    # JPEG quality down until the file fits.
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    tmp.close()
    out_path = tmp.name

    # ffmpeg's -q:v range is 2..31 (lower = better). Start at 4 and step up.
    last_size = size
    for q in (4, 6, 9, 12, 16, 22, 28):
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", src_path,
            "-vf", "scale='min(1280,iw)':'min(720,ih)':force_original_aspect_ratio=decrease",
            "-q:v", str(q),
            out_path,
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=60)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            print(f"[youtube_publisher] thumbnail re-encode at q={q} failed: {e}")
            continue
        last_size = os.path.getsize(out_path)
        if last_size <= YT_THUMB_MAX_BYTES:
            print(
                f"[youtube_publisher] thumbnail compressed "
                f"{size/1024:.0f}KB -> {last_size/1024:.0f}KB (q={q})"
            )
            return out_path, "image/jpeg", True

    print(
        f"[youtube_publisher] thumbnail still {last_size/1024:.0f}KB after max "
        f"compression — skipping thumbnail."
    )
    try:
        os.remove(out_path)
    except OSError:
        pass
    return "", "image/jpeg", False

if os.environ.get("FLASK_ENV") == "development" or not os.environ.get("FLASK_ENV"):
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

YOUTUBE_CATEGORIES = {
    "10": "Music",
    "22": "People & Blogs",
    "24": "Entertainment",
    "26": "Howto & Style",
}

DEFAULT_CATEGORY = "10"

RETRIABLE_STATUS_CODES = [500, 502, 503, 504]
MAX_RETRIES = 5

RECONNECT_MESSAGE = (
    "YouTube authorization expired. Go to Publish → Connect YouTube to sign in again. "
    "If this keeps happening every ~7 days, your Google Cloud OAuth app is likely in "
    "Testing mode — publish it to Production or reconnect weekly."
)


class YouTubeAuthError(RuntimeError):
    """Raised when stored OAuth credentials can no longer be refreshed."""


def _is_invalid_grant(exc: BaseException) -> bool:
    return "invalid_grant" in str(exc).lower()


class YouTubePublisher:
    """Manages YouTube OAuth and video uploads."""

    def __init__(
        self,
        client_secret_path: str = "client_secret.json",
        token_path: str = "youtube_token.json",
    ):
        self.client_secret_path = Path(client_secret_path)
        self.token_path = Path(token_path)
        self._token_lock_path = self.token_path.with_suffix(".lock")
        self._youtube = None

    def _token_lock(self):
        self._token_lock_path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self._token_lock_path, "w")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        return fh

    @staticmethod
    def _token_unlock(lock_fh):
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
        lock_fh.close()

    @property
    def has_client_secret(self) -> bool:
        return self.client_secret_path.exists()

    @property
    def is_authenticated(self) -> bool:
        if not self.token_path.exists():
            return False
        try:
            creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)
            return creds.valid or (creds.expired and creds.refresh_token)
        except Exception:
            return False

    def get_auth_url(self, redirect_uri: str = "http://localhost:5050/oauth/callback") -> tuple[str, object]:
        """Start OAuth flow and return (auth_url, flow) for the user to visit."""
        if not self.has_client_secret:
            raise FileNotFoundError(
                "client_secret.json not found. Download it from Google Cloud Console."
            )

        flow = Flow.from_client_secrets_file(
            str(self.client_secret_path),
            scopes=SCOPES,
            redirect_uri=redirect_uri,
        )
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        return auth_url, flow

    def complete_auth(self, flow, authorization_response: str = None, code: str = None):
        """Exchange authorization code for tokens and save them."""
        if authorization_response:
            flow.fetch_token(authorization_response=authorization_response)
        else:
            flow.fetch_token(code=code)
        creds = flow.credentials
        lock_fh = self._token_lock()
        try:
            self.token_path.write_text(creds.to_json())
        finally:
            self._token_unlock(lock_fh)
        self._youtube = None
        return True

    def _get_credentials(self) -> Credentials:
        lock_fh = self._token_lock()
        try:
            if not self.token_path.exists():
                raise RuntimeError("Not authenticated. Complete OAuth flow first.")

            creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)

            if creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    self.token_path.write_text(creds.to_json())
                except RefreshError as e:
                    self.disconnect()
                    raise YouTubeAuthError(RECONNECT_MESSAGE) from e

            return creds
        finally:
            self._token_unlock(lock_fh)

    def validate_connection(self) -> dict:
        """Refresh credentials if needed and verify the channel is reachable."""
        self._youtube = None
        return self.get_channel_info()

    def _get_youtube(self):
        if self._youtube is None:
            creds = self._get_credentials()
            self._youtube = build("youtube", "v3", credentials=creds)
        return self._youtube

    def get_channel_info(self) -> dict:
        """Return basic info about the authenticated channel."""
        yt = self._get_youtube()
        resp = yt.channels().list(part="snippet,statistics", mine=True).execute()
        if not resp.get("items"):
            return {"name": "Unknown", "subscribers": 0}
        ch = resp["items"][0]
        return {
            "name": ch["snippet"]["title"],
            "thumbnail": ch["snippet"]["thumbnails"]["default"]["url"],
            "subscribers": int(ch["statistics"].get("subscriberCount", 0)),
            "channel_id": ch["id"],
        }

    def upload_video(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list[str] | None = None,
        category_id: str = DEFAULT_CATEGORY,
        privacy: str = "unlisted",
        thumbnail_path: str | None = None,
        on_progress: Callable[[float, str], None] | None = None,
    ) -> dict:
        """
        Upload a video to YouTube with resumable upload.

        Returns dict with video_id, url, and status.
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        yt = self._get_youtube()

        body = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "tags": (tags or [])[:500],
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False,
            },
        }

        file_size = os.path.getsize(video_path)
        media = MediaFileUpload(
            video_path,
            mimetype="video/mp4",
            resumable=True,
            chunksize=10 * 1024 * 1024,  # 10MB chunks
        )

        insert_request = yt.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        def status(pct, msg):
            if on_progress:
                on_progress(pct, msg)

        status(0, "Starting upload...")

        response = None
        retry = 0
        while response is None:
            try:
                upload_status, response = insert_request.next_chunk()
                if upload_status:
                    pct = upload_status.progress() * 100
                    uploaded_mb = (upload_status.resumable_progress) / (1024 * 1024)
                    total_mb = file_size / (1024 * 1024)
                    status(pct, f"Uploading... {uploaded_mb:.0f}/{total_mb:.0f} MB ({pct:.0f}%)")
            except HttpError as e:
                if e.resp.status in RETRIABLE_STATUS_CODES:
                    retry += 1
                    if retry > MAX_RETRIES:
                        raise
                    wait = 2 ** retry
                    status(0, f"Retrying in {wait}s (attempt {retry}/{MAX_RETRIES})...")
                    time.sleep(wait)
                else:
                    raise

        video_id = response["id"]
        status(95, "Upload complete. Setting thumbnail...")

        if thumbnail_path and os.path.exists(thumbnail_path):
            prepared_path, prepared_mime, is_temp = _prepare_thumbnail(thumbnail_path)
            if prepared_path:
                try:
                    yt.thumbnails().set(
                        videoId=video_id,
                        media_body=MediaFileUpload(prepared_path, mimetype=prepared_mime),
                    ).execute()
                except (HttpError, MediaUploadSizeError) as e:
                    # Video is already published; a thumbnail failure must
                    # never roll back the upload.
                    print(f"[youtube_publisher] thumbnail upload failed (non-fatal): {e}")
                except Exception as e:
                    print(f"[youtube_publisher] thumbnail upload error (non-fatal): {e}")
                finally:
                    if is_temp:
                        try:
                            os.remove(prepared_path)
                        except OSError:
                            pass

        video_url = f"https://www.youtube.com/watch?v={video_id}"
        status(100, f"Published! {video_url}")

        return {
            "video_id": video_id,
            "url": video_url,
            "privacy": privacy,
            "title": title,
        }

    def disconnect(self):
        """Remove stored credentials."""
        lock_fh = self._token_lock()
        try:
            if self.token_path.exists():
                self.token_path.unlink()
        finally:
            self._token_unlock(lock_fh)
        self._youtube = None
