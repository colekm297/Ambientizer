"""
distribute_stream.py — 24/7 YouTube Live ambient stream (Path A: direct RTMP).

A long-running ffmpeg subprocess loops a concat playlist file and pushes to
the YouTube Live RTMP ingest. State is persisted to disk so a Flask restart
can resume the stream (or report that it died).

Path A is implemented here. A Path B (Gyre-hosted) adapter could be slotted in
behind the same start/stop interface later.
"""

import os
import json
import time
import signal
import subprocess
import threading
from pathlib import Path
from typing import Optional


STATE_FILE = "_distribute_stream.json"
PLAYLIST_FILE = "_distribute_playlist.txt"


def _state_path(saved_jobs_dir: Path) -> Path:
    return saved_jobs_dir / STATE_FILE


def _playlist_path(output_dir: Path) -> Path:
    return output_dir / PLAYLIST_FILE


def read_state(saved_jobs_dir: Path) -> dict:
    path = _state_path(saved_jobs_dir)
    if not path.exists():
        return {
            "status": "stopped",
            "pid": None,
            "started_at": None,
            "stream_key_set": False,
            "current_track_id": None,
            "current_track_started_at": None,
            "total_uptime_sec": 0,
            "last_error": None,
            "rtmp_url": None,
        }
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {"status": "stopped", "pid": None, "last_error": "Corrupt state file"}


def write_state(saved_jobs_dir: Path, state: dict) -> None:
    path = _state_path(saved_jobs_dir)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str))
    tmp.replace(path)


def _pid_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def reconcile_state(saved_jobs_dir: Path) -> dict:
    """Check the persisted PID against /proc — if dead, mark stopped."""
    state = read_state(saved_jobs_dir)
    if state.get("status") == "running" and not _pid_alive(state.get("pid")):
        state["status"] = "stopped"
        state["pid"] = None
        state["last_error"] = "ffmpeg subprocess died (not running anymore)"
        write_state(saved_jobs_dir, state)
    return state


def build_playlist(
    saved_jobs_dir: Path,
    output_dir: Path,
    jobs_dict: dict,
    job_ids: Optional[list[str]] = None,
) -> int:
    """Regenerate the concat playlist from current catalog.

    If job_ids is None, includes every job with a visual_video_path.
    Returns the number of tracks written.
    """
    if job_ids is None:
        eligible = [
            j for j in jobs_dict.values()
            if j.get("visual_video_path") and os.path.exists(j.get("visual_video_path", ""))
        ]
    else:
        eligible = [
            jobs_dict[j_id] for j_id in job_ids
            if j_id in jobs_dict
            and jobs_dict[j_id].get("visual_video_path")
            and os.path.exists(jobs_dict[j_id].get("visual_video_path", ""))
        ]

    lines = ["ffconcat version 1.0"]
    for j in eligible:
        # ffconcat requires escaping single quotes; safest is to use absolute
        # paths and wrap in single quotes after escaping.
        path = os.path.abspath(j["visual_video_path"]).replace("'", "'\\''")
        lines.append(f"file '{path}'")

    _playlist_path(output_dir).write_text("\n".join(lines) + "\n")
    return len(eligible)


def start_stream(
    saved_jobs_dir: Path,
    output_dir: Path,
    rtmp_url: str,
    stream_key: str,
    log_path: Optional[str] = None,
) -> dict:
    """Spawn detached ffmpeg pushing the playlist to RTMP. Returns state dict."""
    state = reconcile_state(saved_jobs_dir)
    if state.get("status") == "running":
        return state

    playlist = _playlist_path(output_dir)
    if not playlist.exists():
        raise RuntimeError("Playlist is empty. Build the playlist before starting the stream.")

    target = rtmp_url.rstrip("/") + "/" + stream_key.lstrip("/")

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "warning",
        "-re",
        "-stream_loop", "-1",
        "-f", "concat", "-safe", "0",
        "-i", str(playlist),
        # Video: re-encode to YT Live-compliant 1080p H.264, 4500k, 2s GOP.
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
        "-b:v", "4500k", "-maxrate", "4500k", "-bufsize", "9000k",
        "-pix_fmt", "yuv420p", "-g", "60", "-keyint_min", "60",
        "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2",
        "-r", "30",
        # Audio: AAC 160k stereo 44.1kHz (YT Live spec).
        "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2",
        "-f", "flv",
        target,
    ]

    log_handle = None
    if log_path:
        log_handle = open(log_path, "a", buffering=1)
        log_handle.write(f"\n--- distribute_stream start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        log_handle.flush()

    proc = subprocess.Popen(
        cmd,
        stdout=log_handle or subprocess.DEVNULL,
        stderr=log_handle or subprocess.DEVNULL,
        start_new_session=True,
    )
    state.update({
        "status": "running",
        "pid": proc.pid,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "stream_key_set": True,
        "last_error": None,
        # Don't persist the raw key — only the ingest URL prefix for reference.
        "rtmp_url": rtmp_url,
    })
    write_state(saved_jobs_dir, state)
    return state


def stop_stream(saved_jobs_dir: Path) -> dict:
    state = reconcile_state(saved_jobs_dir)
    pid = state.get("pid")
    if pid and _pid_alive(pid):
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
            # Give ffmpeg a moment, then SIGKILL if needed.
            for _ in range(20):
                if not _pid_alive(pid):
                    break
                time.sleep(0.25)
            if _pid_alive(pid):
                os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
    state.update({"status": "stopped", "pid": None})
    write_state(saved_jobs_dir, state)
    return state


# ── Secrets storage ────────────────────────────────────────────────

SECRETS_FILE = "_distribute_secrets.json"


def secrets_path(saved_jobs_dir: Path) -> Path:
    return saved_jobs_dir / SECRETS_FILE


def read_secrets(saved_jobs_dir: Path) -> dict:
    p = secrets_path(saved_jobs_dir)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def write_secrets(saved_jobs_dir: Path, secrets: dict) -> None:
    p = secrets_path(saved_jobs_dir)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(secrets, indent=2))
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(p)
