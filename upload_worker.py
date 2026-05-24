"""
upload_worker.py — Standalone YouTube upload process.

Runs completely independent of the Flask server so that server restarts,
auto-reloads, or crashes cannot kill an in-progress upload.

Usage (called by app.py, not directly):
    python upload_worker.py '<json-params>'

Writes progress to a JSON status file that the Flask status endpoint reads.
"""

import sys
import json
import os
import traceback
from pathlib import Path

from youtube_publisher import YouTubePublisher, YouTubeAuthError, RECONNECT_MESSAGE


def write_status(status_file: Path, status: str, progress: float,
                 message: str, url: str = None, video_id: str = None):
    payload = {
        "status": status,
        "progress": progress,
        "message": message,
    }
    if url:
        payload["youtube_url"] = url
    if video_id:
        payload["video_id"] = video_id
    tmp = status_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload))
    tmp.replace(status_file)


def main():
    if len(sys.argv) < 2:
        print("upload_worker: missing params argument", file=sys.stderr)
        sys.exit(1)

    params = json.loads(sys.argv[1])
    status_file = Path(params["status_file"])

    write_status(status_file, "uploading", 0, "Starting upload...")

    publisher = YouTubePublisher(
        client_secret_path=params["client_secret"],
        token_path=params["token_path"],
    )

    try:
        file_mb = os.path.getsize(params["video_path"]) / (1024 * 1024)
        print(f"[upload_worker] Uploading {file_mb:.0f} MB: {params['video_path']}")

        result = publisher.upload_video(
            video_path=params["video_path"],
            title=params["title"],
            description=params["description"],
            tags=params.get("tags", []),
            privacy=params.get("privacy", "unlisted"),
            thumbnail_path=params.get("thumbnail_path"),
            on_progress=lambda pct, msg: write_status(
                status_file, "uploading", pct, msg
            ),
        )

        print(f"[upload_worker] Done! {result['url']}")
        write_status(
            status_file, "done", 100, result["url"],
            url=result["url"], video_id=result["video_id"],
        )

    except YouTubeAuthError as e:
        print(f"[upload_worker] AUTH FAILED: {e}", file=sys.stderr)
        write_status(status_file, "error", 0, str(e))
        sys.exit(1)
    except Exception as e:
        print(f"[upload_worker] FAILED: {e}", file=sys.stderr)
        traceback.print_exc()
        write_status(status_file, "error", 0, str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
