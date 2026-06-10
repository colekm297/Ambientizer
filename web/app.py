"""
web/app.py — Flask web server for the Ambientizer soundscape generator.

Provides a REST API for generating soundscapes, applying human feedback
for iterative mix refinement, serving audio files, and generating visuals.

Endpoints:
    GET  /                          — Serves the single-page UI
    POST /api/generate              — Start a generation job (returns job_id)
    GET  /api/status/<job_id>       — Poll job progress
    POST /api/feedback/<job_id>     — Apply natural language feedback to refine mix
    POST /api/finalize/<job_id>     — Re-master current mix for download
    GET  /api/audio/<job_id>        — Serve the current audio (raw during feedback)
    GET  /api/audio/<job_id>/download — Download the mastered WAV
    GET  /api/history               — List recent generation jobs
    POST /api/visual/auto-prompt/<job_id> — AI-generate an image prompt
    POST /api/visual/image/<job_id>      — Generate a scene image with Grok
    GET  /api/visual/image/<job_id>/view  — Serve the generated image
    POST /api/visual/clip/<job_id>       — Generate a short animated clip
    GET  /api/visual/clip/<job_id>/view   — Serve the clip for preview
    POST /api/visual/export/<job_id>     — Loop clip + combine with audio
    GET  /api/visual/video/<job_id>/download — Download the final video
    GET  /api/youtube/status             — Check YouTube OAuth status
    POST /api/youtube/connect            — Start YouTube OAuth flow
    GET  /oauth/callback                 — Handle OAuth redirect
    POST /api/youtube/auto-metadata/<id> — AI-generate title/desc/tags
    POST /api/youtube/upload/<job_id>    — Upload video to YouTube
"""

import json
import os
import subprocess
import sys
import time
import uuid
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from flask import Flask, render_template, request, jsonify, send_file, abort
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import SoundscapeOrchestrator
from audio_engine import AudioEngine, SampleLibrary, detect_key, harmonize_layers, prepare_musical_loop, make_loopable
from mix_master import MixMasterAgent
from feedback_adjuster import FeedbackAdjuster
from sample_generator import ElevenLabsSampleGenerator
from pydub import AudioSegment
from schemas import GenerationMode, SoundscapeConfig, LayerConfig, LayerType, EffectsChain, PartSnapshot
from visual_generator import VisualGenerator
import thumbnail_maker
from motion_compositor import MotionCompositor, choose_layers, choose_layers_from_image
from youtube_publisher import YouTubePublisher, YouTubeAuthError, RECONNECT_MESSAGE, _is_invalid_grant
from retry_utils import retry_with_backoff, is_transient_api_error
from gemini_limiter import gemini_limiter
import distribute_shorts
import distribute_stream

load_dotenv()

app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0  # Never cache static files during dev.

# ── Optional password gate ────────────────────────────────────────────────────
# When AMBIENTIZER_PASSWORD is set (e.g. while exposed through a public
# Cloudflare tunnel), EVERY route requires a signed session cookie obtained by
# POSTing the password to /login. Unset = no gate (normal local/Tailscale use).
import hmac as _hmac
import secrets as _secrets

ACCESS_PASSWORD = os.environ.get("AMBIENTIZER_PASSWORD", "")
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or _secrets.token_hex(32)

_LOGIN_PAGE = """<!doctype html><html><head><title>Ambientizer</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{background:#0d0f14;color:#cfd6e4;font-family:-apple-system,sans-serif;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
form{background:#161a22;padding:2rem;border-radius:12px;text-align:center}
input{padding:.6rem .8rem;border-radius:8px;border:1px solid #2a3040;background:#0d0f14;
color:#cfd6e4;font-size:1rem;margin-bottom:.8rem;width:220px}
button{padding:.6rem 1.4rem;border-radius:8px;border:none;background:#4a7dff;color:#fff;
font-size:1rem;cursor:pointer}p.err{color:#ff7a7a;font-size:.85rem}</style></head>
<body><form method="post" action="/login"><h2>Ambientizer</h2>
{ERR}<input type="password" name="password" placeholder="Password" autofocus>
<br><button type="submit">Enter</button></form></body></html>"""


@app.before_request
def _password_gate():
    if not ACCESS_PASSWORD:
        return None
    from flask import session as _session
    if request.path == "/login":
        return None
    if _session.get("authed"):
        return None
    return _LOGIN_PAGE.replace("{ERR}", ""), 401


@app.route("/login", methods=["GET", "POST"])
def login():
    from flask import session as _session, redirect
    if not ACCESS_PASSWORD:
        return redirect("/")
    if request.method == "POST":
        supplied = request.form.get("password", "")
        if _hmac.compare_digest(supplied, ACCESS_PASSWORD):
            _session["authed"] = True
            _session.permanent = True
            return redirect("/")
        time.sleep(1.0)  # slow brute force
        return _LOGIN_PAGE.replace("{ERR}", '<p class="err">Wrong password</p>'), 401
    return _LOGIN_PAGE.replace("{ERR}", "")


jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
JOBS_DIR = PROJECT_ROOT / "saved_jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)

# When True, skip prepare_musical_loop entirely and serve the raw ElevenLabs
# audio. The "seamless loopable" prompt hint asks the model to produce audio
# that already starts and ends at compatible levels; Web Audio then loops the
# buffer natively. Set False to re-enable trim + crossfade prep.
BYPASS_LOOP_PREP = False


class GenerationCanceled(Exception):
    """Raised inside the generation worker when the user cancels a job."""


class LongTaskCanceled(Exception):
    """Raised when the user stops a background export/visual task."""


_long_tasks: dict[str, dict] = {}
_long_tasks_lock = threading.Lock()


def _long_task_snapshot(job_id: str) -> dict | None:
    with _long_tasks_lock:
        task = _long_tasks.get(job_id)
        return dict(task) if task else None


def _long_task_start(job_id: str, task_type: str, message: str = "Working..."):
    with _long_tasks_lock:
        existing = _long_tasks.get(job_id)
        if existing and existing.get("status") == "running":
            raise RuntimeError(
                f"A {existing.get('task_type', 'task')} is already running for this track"
            )
        _long_tasks[job_id] = {
            "task_type": task_type,
            "status": "running",
            "message": message,
            "cancel_requested": False,
            "subprocess": None,
            "result": {},
        }


def _long_task_update(job_id: str, **fields):
    with _long_tasks_lock:
        if job_id in _long_tasks:
            _long_tasks[job_id].update(fields)


def _long_task_check_cancel(job_id: str):
    with _long_tasks_lock:
        if _long_tasks.get(job_id, {}).get("cancel_requested"):
            raise LongTaskCanceled("Stopped by user")


def _long_task_set_subprocess(job_id: str, proc: subprocess.Popen):
    with _long_tasks_lock:
        if job_id in _long_tasks:
            _long_tasks[job_id]["subprocess"] = proc


def _long_task_finish(job_id: str, status: str, message: str = "", result: dict | None = None):
    with _long_tasks_lock:
        if job_id not in _long_tasks:
            return
        _long_tasks[job_id]["status"] = status
        _long_tasks[job_id]["message"] = message
        if result is not None:
            _long_tasks[job_id]["result"] = result
        _long_tasks[job_id]["subprocess"] = None
        _long_tasks[job_id]["cancel_requested"] = False


def _long_task_cancel(job_id: str) -> bool:
    proc = None
    with _long_tasks_lock:
        task = _long_tasks.get(job_id)
        if not task:
            return False
        task["cancel_requested"] = True
        if task.get("status") == "running":
            task["status"] = "canceled"
            task["message"] = "Stopped by user"
        proc = task.get("subprocess")
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return True


def _run_ffmpeg_cancellable(job_id: str, cmd: list[str], timeout: int = 3600,
                            total_sec: float = 0, label: str = "Processing"):
    """Run ffmpeg, checking for user cancellation while the process runs. When
    total_sec is given, parse ffmpeg's -progress output and report seconds
    done/total so the UI can show a real progress bar (the frontend reads N/M)."""
    use_progress = total_sec and total_sec > 0
    if use_progress and "-progress" not in cmd:
        cmd = [cmd[0], "-progress", "pipe:1", "-nostats"] + cmd[1:]
    proc = subprocess.Popen(
        cmd,
        stdout=(subprocess.PIPE if use_progress else subprocess.DEVNULL),
        stderr=subprocess.DEVNULL,
        text=True,
    )
    _long_task_set_subprocess(job_id, proc)

    if use_progress:
        def _reader():
            try:
                for line in proc.stdout:
                    line = line.strip()
                    if line.startswith("out_time="):
                        ts = line.split("=", 1)[1]
                        try:
                            h, m, s = ts.split(":")
                            done = int(int(h) * 3600 + int(m) * 60 + float(s))
                            done = max(0, min(int(total_sec), done))
                            _long_task_update(job_id, message=f"{label} — {done}/{int(total_sec)}s")
                        except Exception:
                            pass
            except Exception:
                pass
        threading.Thread(target=_reader, daemon=True).start()

    deadline = time.time() + timeout
    while proc.poll() is None:
        _long_task_check_cancel(job_id)
        if time.time() > deadline:
            proc.kill()
            raise RuntimeError("ffmpeg timed out")
        time.sleep(0.3)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (exit {proc.returncode})")


def _start_background_task(job_id: str, task_type: str, message: str, worker):
    try:
        _long_task_start(job_id, task_type, message)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 409

    def run():
        try:
            worker()
        except LongTaskCanceled:
            _long_task_finish(job_id, "canceled", "Stopped by user")
        except Exception as e:
            import traceback
            traceback.print_exc()
            _long_task_finish(job_id, "error", str(e))

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"status": "running", "task_type": task_type})


def _invalidate_flat_cache(job_id: str):
    """Delete cached flat mix so it gets re-rendered on next request."""
    flat_path = str(PROJECT_ROOT / "output" / f"{job_id}_flat.wav")
    export_loop_path = str(PROJECT_ROOT / "output" / f"{job_id}_export_loop.wav")
    for path in (flat_path, export_loop_path):
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


def _ensure_export_loop_audio(job_id: str, config) -> str:
    """Build or return cached seamless loop cell used for video export."""
    export_loop_path = str(PROJECT_ROOT / "output" / f"{job_id}_export_loop.wav")
    if os.path.exists(export_loop_path):
        return export_loop_path

    engine = _get_engine()
    loop_audio = engine.render_export_loop(config)
    loop_audio.export(export_loop_path, format="wav")
    print(f"  [export] Created export loop cell for {job_id}: {len(loop_audio)/1000:.1f}s")
    return export_loop_path


_save_lock = threading.Lock()

def _save_job(job_id: str):
    """Persist a job's state to disk as JSON.

    Serialised through _save_lock so concurrent autosaves (motion editor +
    brush mask painting + clip render all happening near-simultaneously) can't
    interleave their writes and corrupt the JSON file.
    """
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return

    serializable = {
        "job_id": job["job_id"],
        "prompt": job["prompt"],
        "duration": job["duration"],
        "mastering": job["mastering"],
        "mode": job.get("mode", "ambient"),
        "reference_url": job.get("reference_url"),
        "status": job["status"],
        "stage": job["stage"],
        "progress_message": job.get("progress_message", ""),
        "warnings": job.get("warnings", []),
        "audio_path": job.get("audio_path"),
        "output_path": job.get("output_path"),
        "raw_output_path": job.get("raw_output_path"),
        "mastered_path": job.get("mastered_path"),
        "feedback_history": job.get("feedback_history", []),
        "error": job.get("error"),
        "created_at": job.get("created_at"),
        "config": job["config"].to_dict() if job.get("config") else None,
        "visual_image_path": job.get("visual_image_path"),
        "visual_image_prompt": job.get("visual_image_prompt"),
        "visual_clip_path": job.get("visual_clip_path"),
        "visual_clip_mode": job.get("visual_clip_mode"),
        "visual_clips": job.get("visual_clips"),
        "visual_clip_sources": job.get("visual_clip_sources"),
        "visual_active_tab": job.get("visual_active_tab"),
        "brush_mask_path": job.get("brush_mask_path"),
        # Per-layer region masks for Living Still: { "0": "/path/to/mask.png", ... }
        # Index = position in motion_layers; reordering invalidates these.
        "layer_masks": job.get("layer_masks", {}),
        # Motion editor state — persisted so a refresh restores EXACTLY the
        # layers + dropdown values the user composed. Without this the editor
        # blanks out on every reload, which also strands the per-layer masks
        # (the brush-target dropdown can only list layers that exist).
        "motion_layers": job.get("motion_layers", []),
        "motion_director_style": job.get("motion_director_style"),
        "motion_intensity": job.get("motion_intensity"),
        "motion_loop_sec": job.get("motion_loop_sec"),
        "motion_prompt": job.get("motion_prompt"),
        "custom_thumbnail_path": job.get("custom_thumbnail_path"),
        "thumbnail_design": job.get("thumbnail_design"),
        "visual_video_path": job.get("visual_video_path"),
        "youtube_url": job.get("youtube_url"),
        "youtube_video_id": job.get("youtube_video_id"),
        "yt_title": job.get("yt_title"),
        "yt_description": job.get("yt_description"),
        "yt_tags": job.get("yt_tags"),
        "yt_privacy": job.get("yt_privacy"),
        "parts": [p.to_dict() for p in job.get("parts", [])],
        "alternate_pairs": job.get("alternate_pairs", []),
        "stems": job.get("stems"),
        "stem_files": job.get("stem_files"),
        "composition_plan": job.get("composition_plan"),
        "music_generation_mode": job.get("music_generation_mode"),
        "favorite": job.get("favorite", False),
        # Distribute-tab persistence
        "shorts": job.get("shorts", []),
        "ads_brief_md": job.get("ads_brief_md"),
        "community_drafts": job.get("community_drafts", {}),
        "reddit_drafts": job.get("reddit_drafts", {}),
        "seo_v2": job.get("seo_v2"),
        "last_promoted_at": job.get("last_promoted_at"),
        # Per-song saved Living Stills gallery
        "saved_living_stills": job.get("saved_living_stills", []),
    }

    path = JOBS_DIR / f"{job_id}.json"
    tmp = path.with_suffix(".json.tmp")
    try:
        # Atomic write under _save_lock so concurrent calls can't tear the JSON.
        with _save_lock:
            with open(tmp, "w") as f:
                json.dump(serializable, f, indent=2, default=str)
            os.replace(tmp, path)  # atomic rename on POSIX/macOS
    except Exception as e:
        print(f"  Warning: Could not save job {job_id}: {e}")
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def _load_saved_jobs():
    """Load all saved jobs from disk on startup."""
    loaded = 0
    for path in JOBS_DIR.glob("*.json"):
        try:
            with open(path) as f:
                data = json.load(f)

            job_id = data["job_id"]
            config = None
            if data.get("config"):
                config = SoundscapeConfig.from_dict(data["config"])

            jobs[job_id] = {
                "job_id": job_id,
                "prompt": data.get("prompt", ""),
                "duration": data.get("duration", 5.0),
                "mastering": data.get("mastering", True),
                "mode": data.get("mode", "ambient"),
                "reference_url": data.get("reference_url"),
                "status": data.get("status", "complete"),
                "stage": data.get("stage", "complete"),
                "progress_message": data.get("progress_message", ""),
                "warnings": data.get("warnings", []),
                "logs": [],
                "config": config,
                "audio_path": data.get("audio_path"),
                "output_path": data.get("output_path"),
                "raw_output_path": data.get("raw_output_path"),
                "mastered_path": data.get("mastered_path"),
                "adjuster": None,
                "feedback_history": data.get("feedback_history", []),
                "error": data.get("error"),
                "created_at": data.get("created_at", ""),
                "visual_image_path": data.get("visual_image_path"),
                "visual_image_prompt": data.get("visual_image_prompt"),
                "visual_clip_path": data.get("visual_clip_path"),
                "visual_clip_mode": data.get("visual_clip_mode"),
                "visual_clips": data.get("visual_clips"),
                "visual_clip_sources": data.get("visual_clip_sources"),
                "visual_active_tab": data.get("visual_active_tab"),
                "brush_mask_path": data.get("brush_mask_path"),
                "layer_masks": data.get("layer_masks", {}),
                "motion_layers": data.get("motion_layers", []),
                "motion_director_style": data.get("motion_director_style"),
                "motion_intensity": data.get("motion_intensity"),
                "motion_loop_sec": data.get("motion_loop_sec"),
                "motion_prompt": data.get("motion_prompt"),
                "custom_thumbnail_path": data.get("custom_thumbnail_path"),
                "thumbnail_design": data.get("thumbnail_design"),
                "visual_video_path": data.get("visual_video_path"),
                "youtube_url": data.get("youtube_url"),
                "youtube_video_id": data.get("youtube_video_id"),
                "yt_title": data.get("yt_title"),
                "yt_description": data.get("yt_description"),
                "yt_tags": data.get("yt_tags"),
                "yt_privacy": data.get("yt_privacy"),
                "parts": [PartSnapshot.from_dict(p) for p in data.get("parts", [])],
                "alternate_pairs": data.get("alternate_pairs", []),
                "stems": data.get("stems"),
                "stem_files": data.get("stem_files"),
                "composition_plan": data.get("composition_plan"),
                "music_generation_mode": data.get("music_generation_mode"),
                "favorite": data.get("favorite", False),
                "shorts": data.get("shorts", []),
                "ads_brief_md": data.get("ads_brief_md"),
                "community_drafts": data.get("community_drafts", {}),
                "reddit_drafts": data.get("reddit_drafts", {}),
                "seo_v2": data.get("seo_v2"),
                "last_promoted_at": data.get("last_promoted_at"),
                "saved_living_stills": data.get("saved_living_stills", []),
            }
            loaded += 1
        except Exception as e:
            print(f"  Warning: Could not load {path.name}: {e}")

    if loaded:
        print(f"  Loaded {loaded} saved job(s) from {JOBS_DIR}")


_load_saved_jobs()


def _get_engine() -> AudioEngine:
    """Get a shared AudioEngine instance for re-renders."""
    library = None
    samples_path = PROJECT_ROOT / "samples"
    if samples_path.is_dir():
        library = SampleLibrary(str(samples_path))
    return AudioEngine(library)


def _get_sample_generator():
    """Get an ElevenLabs sample generator, or None if no key."""
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        return None
    return ElevenLabsSampleGenerator(api_key=api_key)


def summarize_changes(old_config: SoundscapeConfig, new_config: SoundscapeConfig) -> str:
    """Compare two configs and return a human-readable summary of what changed."""
    changes = []

    old_layers = {l.name: l for l in old_config.layers}
    new_layers = {l.name: l for l in new_config.layers}

    for name, new_layer in new_layers.items():
        old_layer = old_layers.get(name)
        if not old_layer:
            continue

        if new_layer.volume_db != old_layer.volume_db:
            if new_layer.volume_db <= -55:
                changes.append(f"Removed: {name}")
            else:
                changes.append(f"{name} volume: {old_layer.volume_db:.0f}dB -> {new_layer.volume_db:.0f}dB")

        if new_layer.pan != old_layer.pan:
            changes.append(f"{name} pan: {old_layer.pan:.1f} -> {new_layer.pan:.1f}")

        if new_layer.density != old_layer.density:
            changes.append(f"{name} density: {old_layer.density:.1f} -> {new_layer.density:.1f}")

        old_fx = old_layer.effects
        new_fx = new_layer.effects
        if old_fx and new_fx:
            if new_fx.reverb_amount != old_fx.reverb_amount:
                changes.append(f"{name} reverb: {old_fx.reverb_amount:.2f} -> {new_fx.reverb_amount:.2f}")
            if new_fx.low_pass_hz != old_fx.low_pass_hz:
                changes.append(f"{name} low-pass: {old_fx.low_pass_hz} -> {new_fx.low_pass_hz}")
            if new_fx.high_pass_hz != old_fx.high_pass_hz:
                changes.append(f"{name} high-pass: {old_fx.high_pass_hz} -> {new_fx.high_pass_hz}")

    old_mfx = old_config.master_effects
    new_mfx = new_config.master_effects
    if old_mfx.reverb_amount != new_mfx.reverb_amount:
        changes.append(f"Master reverb: {old_mfx.reverb_amount:.2f} -> {new_mfx.reverb_amount:.2f}")
    if old_mfx.low_pass_hz != new_mfx.low_pass_hz:
        changes.append(f"Master low-pass: {old_mfx.low_pass_hz} -> {new_mfx.low_pass_hz}")

    return ", ".join(changes) if changes else "No visible changes"


def create_orchestrator(mastering: bool = True) -> SoundscapeOrchestrator:
    """Create a fresh orchestrator instance with environment API keys."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable required")

    return SoundscapeOrchestrator(
        anthropic_api_key=api_key,
        gemini_api_key=os.environ.get("GEMINI_API_KEY"),
        elevenlabs_api_key=os.environ.get("ELEVENLABS_API_KEY"),
        mastering=mastering,
    )





def _layer_has_audio(layer) -> bool:
    if not layer.generated_audio_path:
        return False
    path = _resolve_audio_path(layer.generated_audio_path)
    if not path or not os.path.exists(path):
        return False
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(path)
        return audio.max_dBFS != float("-inf") and audio.max_dBFS > -55
    except Exception:
        return True


def _serialize_layers(config: SoundscapeConfig) -> list[dict]:
    """Convert config layers to JSON-serializable dicts for the frontend."""
    result = []
    for layer in config.layers:
        result.append({
            "name": layer.name,
            "layer_type": layer.layer_type.value if hasattr(layer.layer_type, "value") else str(layer.layer_type),
            "volume_db": layer.volume_db,
            "pan": layer.pan,
            "pitch_shift_semitones": layer.pitch_shift_semitones,
            "swell_amount": layer.swell_amount,
            "swell_period_sec": layer.swell_period_sec,
            "start_sec": layer.start_sec,
            "end_sec": layer.end_sec,
            "repeat_every_sec": layer.repeat_every_sec,
            "elevenlabs_prompt": layer.elevenlabs_prompt or "",
            "loop": layer.loop,
            "independent_loop": layer.independent_loop,
            "has_audio": _layer_has_audio(layer),
            "effects": {
                "low_pass_hz": layer.effects.low_pass_hz if layer.effects else None,
                "high_pass_hz": layer.effects.high_pass_hz if layer.effects else None,
                "reverb_amount": layer.effects.reverb_amount if layer.effects else 0,
            } if layer.effects else {},
        })
    return result


def run_generation(
    job_id: str, prompt: str, duration: float,
    mastering: bool, mode: str = "ambient", reference_url: str = None,
    loopable: bool = True, music_length: float = 0,
    ref_start_sec: int = 0, ref_end_sec: int = 600,
    layer_plan: list = None, approach: str = "unified",
    stem_separation: str = "none", reference_analysis: dict = None,
    planner_mode: str = "claude", music_generation_mode: str = "text",
    composition_plan: dict = None,
):
    """
    Background worker: generates samples via ElevenLabs + renders a short
    preview for quick listening. Full-length render happens on finalize.
    """

    def on_status(stage: str, message: str, data: dict):
        with jobs_lock:
            job = jobs[job_id]
            if job.get("status") == "canceled" or job.get("cancel_requested"):
                raise GenerationCanceled("Generation stopped by user")
            job["stage"] = stage
            job["progress_message"] = message
            job["logs"].append({"time": datetime.now().isoformat(), "message": message})

            # Persist quality warnings (ToS rewrite, plan fallback, lossy MP3) so
            # the UI can show what silently changed even after generation finishes.
            if stage == "quality_warning" and data.get("warning"):
                job.setdefault("warnings", []).append(data["warning"])

            if stage == "complete" and "output_path" in data:
                job["output_path"] = data["output_path"]
                job["raw_output_path"] = data.get("raw_output_path")

    try:
        agent = create_orchestrator(mastering=mastering)
        gen_mode = GenerationMode(mode) if mode in ("ambient", "musical") else GenerationMode.AMBIENT
        result = agent.generate(
            prompt=prompt,
            duration_minutes=duration,
            on_status=on_status,
            mode=gen_mode,
            reference_url=reference_url or None,
            reference_analysis=reference_analysis,
            planner_mode=planner_mode,
            music_generation_mode=music_generation_mode,
            loopable=loopable,
            ref_start_sec=ref_start_sec,
            ref_end_sec=ref_end_sec,
            music_length_minutes=music_length,
            layer_plan=layer_plan,
            approach=approach,
            composition_plan=composition_plan,
        )

        with jobs_lock:
            if jobs[job_id].get("status") == "canceled" or jobs[job_id].get("cancel_requested"):
                raise GenerationCanceled("Generation stopped by user")
            jobs[job_id]["output_path"] = result.output_path
            jobs[job_id]["raw_output_path"] = result.raw_output_path
            jobs[job_id]["config"] = result.final_config
            jobs[job_id]["audio_path"] = result.raw_output_path

        # Mark complete.
        with jobs_lock:
            if jobs[job_id].get("status") == "canceled" or jobs[job_id].get("cancel_requested"):
                raise GenerationCanceled("Generation stopped by user")
            jobs[job_id]["status"] = "complete"
            jobs[job_id]["stage"] = "complete"
            jobs[job_id]["progress_message"] = "Generation complete"
        _save_job(job_id)

    except GenerationCanceled as e:
        with jobs_lock:
            jobs[job_id]["status"] = "canceled"
            jobs[job_id]["stage"] = "canceled"
            jobs[job_id]["progress_message"] = str(e)
            jobs[job_id]["logs"].append({
                "time": datetime.now().isoformat(),
                "message": str(e),
            })
        _save_job(job_id)

    except Exception as e:
        with jobs_lock:
            if jobs[job_id].get("status") == "canceled" or jobs[job_id].get("cancel_requested"):
                jobs[job_id]["status"] = "canceled"
                jobs[job_id]["stage"] = "canceled"
                jobs[job_id]["progress_message"] = "Generation stopped by user"
                _save_job(job_id)
                return
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = str(e)
            jobs[job_id]["logs"].append({
                "time": datetime.now().isoformat(),
                "message": f"Error: {e}",
            })
        _save_job(job_id)


# ────────────────────────────────────────────────────────
#  Routes
# ────────────────────────────────────────────────────────

@app.route("/")
def index():
    # Cache-bust static assets using file mtimes so the browser always picks
    # up the latest mixer.js / app.js immediately after they change on disk.
    try:
        mixer_v = int(os.path.getmtime(PROJECT_ROOT / "web" / "static" / "mixer.js"))
        app_v = int(os.path.getmtime(PROJECT_ROOT / "web" / "static" / "app.js"))
    except OSError:
        mixer_v = app_v = 0
    return render_template("index.html", mixer_v=mixer_v, app_v=app_v)


# ElevenLabs subscription tier → monthly USD price (for credit-to-dollar conversion).
# Source: https://elevenlabs.io/pricing (May 2026).
ELEVENLABS_TIER_PRICING = {
    "free": 0.0,
    "starter": 6.0,
    "creator": 22.0,
    "pro": 99.0,
    "scale": 299.0,
    "business": 990.0,
    "growing_business": 299.0,  # alternate API tier name for Scale
    "enterprise": None,         # custom pricing — fall back to per-tier rate
}


@app.route("/api/credits")
def get_credits():
    """Fetch real credit balance from ElevenLabs subscription API and include
    a credit→USD conversion so the UI can show dollar cost.
    """
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        return jsonify({"error": "No ElevenLabs API key configured"}), 500
    try:
        from elevenlabs.client import ElevenLabs as ELClient
        client = ELClient(api_key=api_key)
        sub = client.user.subscription.get()
        used = getattr(sub, "character_count", 0)
        limit = getattr(sub, "character_limit", 0)
        remaining = max(0, limit - used)
        reset_unix = getattr(sub, "next_character_count_reset_unix", None)
        tier = (getattr(sub, "tier", "") or "").lower()

        monthly_usd = ELEVENLABS_TIER_PRICING.get(tier)
        usd_per_credit = None
        if monthly_usd is not None and monthly_usd > 0 and limit > 0:
            usd_per_credit = monthly_usd / limit

        return jsonify({
            "used": used,
            "limit": limit,
            "remaining": remaining,
            "reset_unix": reset_unix,
            "tier": tier,
            "monthly_usd": monthly_usd,
            "usd_per_credit": usd_per_credit,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/gemini-usage")
def get_gemini_usage():
    """Return local Gemini rate-limit tracking."""
    return jsonify(gemini_limiter.get_usage())


@app.route("/api/gemini-limits", methods=["POST"])
def set_gemini_limits():
    """Let the user adjust RPM/RPD limits to match their AI Studio plan."""
    data = request.get_json(force=True, silent=True) or {}
    rpm = data.get("rpm")
    rpd = data.get("rpd")
    if rpm is not None:
        gemini_limiter.set_limits(rpm=int(rpm))
    if rpd is not None:
        gemini_limiter.set_limits(rpd=int(rpd))
    return jsonify(gemini_limiter.get_usage())


@app.route("/api/analyze-reference", methods=["POST"])
def analyze_reference():
    """
    Run the reference analyzer on a YouTube URL upfront so the user can see
    what Gemini found before generating.  Returns a human-readable summary
    and a suggested soundscape prompt derived from the analysis.
    """
    data = request.get_json(force=True, silent=True) or {}
    url = (data.get("url") or "").strip()
    start_sec = int(data.get("start_sec", 0))
    end_sec = int(data.get("end_sec", 600))

    if not url:
        return jsonify({"error": "No YouTube URL provided"}), 400

    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        return jsonify({"error": "GEMINI_API_KEY not set"}), 500

    usage = gemini_limiter.get_usage()
    if usage["rpd_used"] >= usage["rpd_limit"]:
        return jsonify({
            "error": f"Gemini daily limit reached ({usage['rpd_used']}/{usage['rpd_limit']} requests today). "
                     f"Upgrade your plan at https://aistudio.google.com or wait until tomorrow.",
            "gemini_usage": usage,
        }), 429

    from reference_analyzer import ReferenceAnalyzer
    analyzer = ReferenceAnalyzer(gemini_key)
    analysis = analyzer.analyze(url, start_sec=start_sec, end_sec=end_sec)

    if not analysis or "_error" in analysis:
        usage = gemini_limiter.get_usage()
        reason = (analysis or {}).get("_error", "Unknown failure")
        return jsonify({
            "error": reason,
            "gemini_usage": usage,
        }), 422

    # Build human-readable summary
    summary_parts = []
    feel = analysis.get("overall_feel", "")
    if feel:
        summary_parts.append(feel)
    if analysis.get("_model_used"):
        summary_parts.append(f"Gemini model: {analysis['_model_used']}")

    layers = analysis.get("layers", [])
    if layers:
        layer_names = [
            f"{l.get('sound', 'unknown')} ({l.get('confidence', '?')})"
            if l.get("confidence") else l.get("sound", "unknown")
            for l in layers
        ]
        summary_parts.append(f"Layers detected: {', '.join(layer_names)}")

    identity = analysis.get("track_identity", {})
    if identity:
        ident_parts = []
        if identity.get("primary_style"):
            ident_parts.append(f"Style: {identity['primary_style']}")
        if identity.get("movement"):
            ident_parts.append(f"Movement: {identity['movement']}")
        if identity.get("songlike_score"):
            ident_parts.append(f"Songlike: {identity['songlike_score']}/10")
        if ident_parts:
            summary_parts.append(" | ".join(ident_parts))

    timeline = analysis.get("timeline", [])
    if timeline:
        timeline_bits = [
            f"{t.get('time', '?')}: {t.get('what_changes', '')}"
            for t in timeline[:4]
            if t.get("what_changes")
        ]
        if timeline_bits:
            summary_parts.append("Timeline: " + " / ".join(timeline_bits))

    mix = analysis.get("mix_qualities", {})
    if mix:
        mix_desc = []
        if mix.get("spaciousness"):
            mix_desc.append(f"Space: {mix['spaciousness']}")
        if mix.get("frequency_balance"):
            mix_desc.append(f"Freq balance: {mix['frequency_balance']}")
        if mix_desc:
            summary_parts.append(" | ".join(mix_desc))

    # Prefer Gemini's direct music prompt so the visible prompt matches the
    # listening model's analysis. Claude is only a fallback for old responses.
    recreate = analysis.get("recreate_with", [])
    suggested_prompt = (analysis.get("direct_elevenlabs_prompt") or "").strip()
    do_not_include = analysis.get("do_not_include", [])
    if suggested_prompt and do_not_include:
        suggested_prompt += "\n\nAvoid: " + ", ".join(str(x) for x in do_not_include[:10])

    if not suggested_prompt and recreate:
        descriptions = [r.get("elevenlabs_prompt", "") for r in recreate if r.get("elevenlabs_prompt")]
        if descriptions:
            # Use Claude to synthesize into one coherent prompt
            anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
            if anthropic_key:
                try:
                    import anthropic
                    client = anthropic.Anthropic(api_key=anthropic_key)
                    layers_text = "\n".join(f"- {r.get('layer_name', 'Layer')}: {r.get('elevenlabs_prompt', '')}" for r in recreate)
                    @retry_with_backoff(max_retries=3, base_delay=2.0, retryable_check=is_transient_api_error)
                    def _call_summarize():
                        return client.messages.create(
                            model="claude-sonnet-4-6",
                            max_tokens=300,
                            messages=[{
                                "role": "user",
                                "content": f"""A YouTube reference track was analyzed. Here's what was found:

Overall feel: {feel}

Layers:
{layers_text}

Write a concise soundscape prompt (2-3 sentences) that captures the essence of this reference. \
Describe the sound world as if instructing a musician to recreate this atmosphere. \
Be specific about instruments, textures, spatial qualities, and mood. \
Output ONLY the prompt text, nothing else.""",
                            }],
                        )

                    msg = _call_summarize()
                    suggested_prompt = msg.content[0].text.strip().strip('"')
                except Exception as e:
                    print(f"  Claude summarize failed: {e}")
                    suggested_prompt = feel

    return jsonify({
        "summary": "\n\n".join(summary_parts),
        "suggested_prompt": suggested_prompt or feel,
        "analysis": analysis,
        "layers": [
            {"name": r.get("layer_name", "?"), "type": r.get("layer_type", "sfx"),
             "prompt": r.get("elevenlabs_prompt", "")}
            for r in recreate
        ],
        "overall_feel": feel,
    })


def favorite_prompt_exemplars(mode: str = "musical", max_n: int = 3) -> list:
    """Pull the actual elevenlabs_prompt text from FAVORITED jobs to use as
    few-shot examples — the user's own confirmed 'bangers'. We prefer prompts
    that exhibit the proven banger pattern (explicit key + tempo + named
    instruments), and pick diverse ones. Returns a list of prompt strings.

    This is what makes Enhance learn from what already works: as the user stars
    more good generations, the examples improve automatically. Cheap enough to
    read on demand (enhance is user-initiated, not a hot path)."""
    import re
    want_musical = (mode == "musical")
    scored = []
    for path in JOBS_DIR.glob("*.json"):
        try:
            with open(path) as f:
                d = json.load(f)
        except Exception:
            continue
        if not d.get("favorite"):
            continue
        cfg = d.get("config") or {}
        for layer in cfg.get("layers", []):
            if want_musical and layer.get("layer_type") != "musical":
                continue
            p = (layer.get("elevenlabs_prompt") or "").strip()
            if len(p) < 80:
                continue
            # Score by banger signals: has a key, a BPM/tempo, and named instruments.
            low = p.lower()
            score = 0
            if re.search(r"\b[a-g](b|#|\s|-)?\s?(major|minor|dorian|phrygian|lydian|aeolian|mixolydian)\b", low):
                score += 2
            if re.search(r"\b\d{2,3}\s?bpm\b", low) or "free-meter" in low or "no pulse" in low:
                score += 2
            if any(inst in low for inst in ("cello", "piano", "flute", "horn", "strings",
                                            "organ", "duduk", "synth", "pad", "choir", "harp")):
                score += 1
            scored.append((score, len(p), p))
    # Best score first; then prefer the more detailed (longer) prompt. De-dup.
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    out, seen = [], set()
    for _, _, p in scored:
        sig = p[:60].lower()
        if sig in seen:
            continue
        seen.add(sig)
        out.append(p)
        if len(out) >= max_n:
            break
    return out


@app.route("/api/enhance-prompt", methods=["POST"])
def enhance_prompt():
    """
    Research the user's rough idea via web search, then use Claude to craft
    a rich, detailed soundscape prompt AND a structured layer plan.
    """
    data = request.get_json(force=True, silent=True) or {}
    raw_prompt = data.get("prompt", "").strip()
    mode = data.get("mode", "ambient")
    approach = data.get("approach", "unified")
    # "world"  → describe the setting, atmosphere, lore, iconic visuals
    # "score"  → describe the soundtrack, composer, instrument palette, harmonic language
    enhance_style = (data.get("enhance_style") or "world").lower()
    if enhance_style not in ("world", "score"):
        enhance_style = "world"
    if not raw_prompt:
        return jsonify({"error": "No prompt provided"}), 400

    gemini_key = os.environ.get("GEMINI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not set"}), 500

    if enhance_style == "score":
        # "Score DNA" — harmony/tempo/instrument focused, NOT vague producer-brief.
        # We want concrete musical structure (key, mode, chord motion, BPM, named
        # instruments) because ElevenLabs Music v1 actually responds to those —
        # it does not respond to "in the style of [composer]" or production-aesthetic
        # adjectives. Force the analysis toward stuff the music model can emulate.
        search_query = (
            f'For "{raw_prompt}", give a music-theory analysis of the score / soundtrack. '
            f'Focus ONLY on harmonic and structural DNA — not lore, scenes, or feelings. '
            f'Specifically cover:\n'
            f'- KEY / MODE used (e.g. "D Phrygian dominant", "C minor with frequent '
            f'borrowed bVI", "modal — primarily Dorian over a drone")\n'
            f'- The recurring / iconic CHORD PROGRESSION described in plain language AND '
            f'in roman numerals if applicable (e.g. "i–VI–VII descending oscillation", '
            f'"tonic-pedal with parallel-5ths upper voice motion", "two-chord pendulum on '
            f'i and bII", "drone-based, no functional cadences")\n'
            f'- TEMPO range and time-feel (e.g. "60–70 BPM 4/4 with offbeat snare hits", '
            f'or "free-meter atmospheric beds with no pulse")\n'
            f'- 1–2 CHARACTERISTIC INSTRUMENTS that carry the harmony (e.g. "church organ '
            f'pedal tones", "processed female vocal pads", "Armenian duduk over synth '
            f'drones", "low brass swells", "ribbon-controlled analog synth")\n'
            f'- Harmonic DEVICES used (pedal tones, modal mixture, sus chords, drones, '
            f'cluster chords, parallel motion, microtonal bending)\n\n'
            f'Do NOT describe characters, locations, plot, creatures, weapons, vehicles, '
            f'or any world-specific imagery. Do NOT use vague producer language like "epic", '
            f'"hauntingly beautiful", "vast cinematic". Just the music theory. '
            f'2–3 paragraphs max. If the reference doesn\'t have a famous score, name 2–3 '
            f'real composers whose harmonic language fits the requested mood and describe '
            f'their typical chord/mode choices.'
        )
    else:
        search_query = (
            f'What is "{raw_prompt}"? Give a concise summary focusing on the setting, '
            f'atmosphere, visual aesthetic, emotional tone, and any iconic sounds or '
            f'music associated with it. If it\'s a book, movie, game, or place, describe '
            f'the world and mood in sensory detail. 3-4 paragraphs max.'
        )

    search_context = ""
    if gemini_key and gemini_limiter.wait_if_needed(timeout=30):
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=gemini_key)
            search_tool = types.Tool(google_search=types.GoogleSearch())
            gemini_limiter.record_call("enhance_search")
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=search_query,
                config=types.GenerateContentConfig(tools=[search_tool]),
            )
            search_context = response.text.strip()
        except Exception as e:
            print(f"  Gemini search failed (non-fatal): {e}")

    import anthropic
    client = anthropic.Anthropic(api_key=anthropic_key)

    ENHANCE_SYSTEM = """You are an expert ambient SOUNDSCAPE designer. You create immersive sonic environments \
for background listening — audio that plays for hours while people study, work, sleep, or relax.

CRITICAL: You are NOT writing pop songs. No verse/chorus/bridge, no beat drops, no hooks. \
But DO include gentle internal movement — elements entering, density shifts, harmonic breathing — \
then returning toward the opening texture for seamless looping.

For MUSICAL mode + Unified approach: 1 rich musical layer containing ALL instruments and environmental atmosphere in a single generation. Do NOT add a separate atmosphere/SFX layer.
For MUSICAL mode + Multi-Layer approach: 2-4 musical layers. Use a quiet Background Pad (type "musical") for texture — never type "base"/"mid"/"detail" (those produce choppy repetitive SFX).
For AMBIENT mode: 2-3 continuous environmental texture layers (type "base" or "mid"). Prompts must describe STEADY beds — no discrete hits.

OUTPUT FORMAT: Return a JSON object with:
{
  "enhanced_prompt": "the enhanced prompt text",
  "layers": [
    {
      "name": "short evocative name",
      "role": "Main Music" or "Atmosphere" or "Texture" etc.,
      "type": "musical" or "base" or "mid" or "detail",
      "instruments": ["instrument1", "instrument2"],
      "prompt_preview": "Detailed generation prompt (250-500 chars for musical, 50-150 for SFX)",
      "est_credits": 3600
    }
  ]
}

Credit estimation: musical layers cost ~30 credits/sec, SFX layers cost ~20 credits/sec × 5 seconds = 100 cr.

The enhanced_prompt should be vivid, production-ready (2-4 sentences). Name specific instruments, \
tempo, key, effects. The layer plan shows what Claude will generate — users can edit before committing.

MODEL GUIDANCE (from ElevenLabs Music v1 official prompting docs — follow these):
- ALWAYS state the musical KEY or MODE (e.g. "in A minor", "D Dorian over a drone"). \
The model reliably captures key — omitting it wastes the strongest lever you have.
- ALWAYS state TEMPO: a BPM number (e.g. "72 BPM") or, for beatless beds, an explicit time-feel \
(e.g. "free-meter, no pulse"). The model follows BPM accurately.
- These are INSTRUMENTAL soundscapes. Include the word "instrumental" and do NOT write lyrics, \
vocal lines, or vocal-entry cues. (Wordless vocal PADS/textures used as an instrument are fine — \
e.g. "wordless female vocal pad" — but never actual lyrics.)
- COPYRIGHT — HARD RULE: never name a real artist, band, or song in enhanced_prompt or prompt_preview \
(e.g. NOT "like Hans Zimmer", NOT "Beatles-esque", NOT a real track title). The API REJECTS prompts that \
name copyrighted material with a bad_prompt error. Describe what they DO musically instead \
(instruments, harmony, production), never who did it.

DESCRIBE INTERNAL MOTION QUALITATIVELY — NEVER WITH CLOCK TIMESTAMPS. \
The music model generates from a freeform prompt + a target length; it has NO mechanism to place an event "at 2:30", \
so written timestamps like "0:00-1:30" or "final 60s" are ignored and just waste prompt attention. \
(Precise timed structure is handled separately by the Composition Plan feature, not here.) \
Instead, describe the SHAPE of the movement in relative terms, e.g.: \
"opens sparse with the core bed, gradually adds a shimmer layer and thickens the harmony toward the middle, \
then thins back to the opening density so it loops seamlessly." \
Avoid stasis words like "never-ending", "static", "wallpaper", "no discrete events". \
Avoid: "verse", "chorus", "bridge", "drop", "beat", "hook", "fade-out ending". \
Do NOT write minute/second markers (no "0:00", "~2:30", "final 45s", "3:00-4:00", etc.) anywhere in enhanced_prompt or prompt_preview.

Output ONLY valid JSON, no markdown fences."""

    context_block = ""
    if search_context:
        label = "HARMONIC DNA ANALYSIS" if enhance_style == "score" else "RESEARCH CONTEXT"
        context_block = f"\n\n{label}:\n{search_context}"

    layer_structure = ""
    if mode == "musical" and approach == "unified":
        layer_structure = "\nLAYER STRUCTURE: 1 musical layer only — weave environmental atmosphere into the same generation. No separate SFX layer."
    elif mode == "musical":
        layer_structure = "\nLAYER STRUCTURE: 2-4 musical layers. Background texture = type 'musical' pad, never 'base'/'mid'/'detail'."
    else:
        layer_structure = "\nLAYER STRUCTURE: 2-3 continuous environmental texture layers. Steady beds only — no occasional/discrete sounds."

    style_addendum = ""
    if enhance_style == "score":
        # The previous "score" mode produced vague producer-brief language that the
        # music model couldn't actually emulate ("Hans Zimmer-esque swells in the
        # style of Loire Cotler"). Replace that with explicit, executable musical
        # structure that ElevenLabs Music v1 can actually pattern-match.
        style_addendum = (
            "\n\nHARMONIC-DNA INTERPRETATION (IMPORTANT):\n"
            "The user wants the prompt to capture the HARMONIC IDENTITY of the reference — "
            "the chord progression, key/mode, tempo, and characteristic instruments that "
            "make its score recognizable. Translate that into something the music model "
            "can directly emulate.\n\n"
            "REQUIRED in the enhanced prompt:\n"
            "- The KEY or MODE explicitly (e.g. 'D Phrygian dominant', 'C minor with "
            "frequent borrowed iv', 'modal — primarily Dorian over a tonic drone').\n"
            "- The CHORD PROGRESSION described as motion in plain language AND roman "
            "numerals when applicable (e.g. 'i–VI–VII descending oscillation', 'tonic "
            "pedal with parallel 5ths in upper voices, no functional cadences', "
            "'two-chord pendulum on i and bII').\n"
            "- The TEMPO and time-feel (BPM range + meter, or 'free-meter atmospheric').\n"
            "- 1–2 CHARACTERISTIC INSTRUMENTS that carry the harmony "
            "(e.g. 'church organ pedal tones', 'processed female vocal pads', "
            "'Armenian duduk over slow-evolving synth drones', 'distorted minimalist "
            "piano in the high register').\n"
            "- A short note on HARMONIC DEVICES (pedal tones, drones, modal mixture, "
            "sus chords, parallel 5ths, cluster chords) where relevant.\n\n"
            "FORBIDDEN:\n"
            "- No narrative or lore: no characters, locations, creatures, vehicles, "
            "weapons, vegetation, weather, spices, etc.\n"
            "- No naming the source material in the prompt itself — let the music carry "
            "the identity.\n"
            "- No vague producer adjectives ('epic', 'sweeping', 'hauntingly beautiful', "
            "'cathedral of sound'). Replace them with the concrete musical mechanic.\n"
            "- No composer name-drops as substitute for description "
            "('in the style of Zimmer' is forbidden — say what Zimmer DID musically).\n\n"
            "TARGET SHAPE — the enhanced prompt should read like a musician's lead sheet, "
            "not a film treatment. Example: 'D Phrygian dominant at ~60 BPM. Slow two-chord "
            "pendulum between i and bII over a sustained tonic drone. Solo Armenian duduk "
            "carries the upper melodic line above slow-evolving granular synth pads. No "
            "discrete events, no functional cadences — modal breathing only.'"
        )

    # Few-shot from the user's OWN favorited generations — show Claude the shape
    # of prompts that have actually produced bangers, so new prompts inherit that
    # specificity (explicit key, tempo, named instruments). Falls back silently
    # to none if there are no favorites yet.
    fewshot_block = ""
    try:
        exemplars = favorite_prompt_exemplars(mode=mode, max_n=3)
        if exemplars:
            examples = "\n\n".join(f'EXAMPLE {i+1} (proven excellent):\n"{p}"'
                                   for i, p in enumerate(exemplars))
            fewshot_block = (
                "\n\nLEARN FROM THESE PROVEN-EXCELLENT PROMPTS — these are real prompts that produced "
                "soundscapes the user marked as favorites. Match their LEVEL OF SPECIFICITY and STYLE: "
                "explicit musical key, explicit tempo (BPM or time-feel), concretely named instruments, "
                "and a clear sense of internal motion. Do NOT copy their content — write for the new idea — "
                "but hit the same quality bar.\n\n" + examples
            )
    except Exception as e:
        print(f"  [enhance] few-shot exemplars unavailable (non-fatal): {e}")

    @retry_with_backoff(max_retries=3, base_delay=2.0, retryable_check=is_transient_api_error)
    def _call_enhance():
        return client.messages.create(
            model="claude-opus-4-7",
            max_tokens=1200,
            system=ENHANCE_SYSTEM + style_addendum + fewshot_block,
            messages=[{
                "role": "user",
                "content": f"""Create a {mode} soundscape from this idea:
"{raw_prompt}"{context_block}{layer_structure}

Be specific about instruments, key, tempo, spatial qualities, and emotional character.
Remember: this is a SOUNDSCAPE, not a pop song. Gentle internal events and density shifts, loop-friendly ending.""",
            }],
        )

    message = _call_enhance()
    raw_response = message.content[0].text.strip()
    if raw_response.startswith("```"):
        raw_response = raw_response.split("\n", 1)[1]
    if raw_response.endswith("```"):
        raw_response = raw_response.rsplit("```", 1)[0]
    raw_response = raw_response.strip()

    try:
        result = json.loads(raw_response)
        enhanced = result.get("enhanced_prompt", raw_prompt)
        layers = result.get("layers", [])
    except (json.JSONDecodeError, KeyError):
        enhanced = raw_response.strip('"')
        layers = []

    return jsonify({
        "enhanced_prompt": enhanced,
        "research_summary": search_context[:300] + "..." if len(search_context) > 300 else search_context,
        "layers": layers,
    })


@app.route("/api/compose-plan", methods=["POST"])
def api_compose_plan():
    """Author an evolving composition plan (sections) for the UI to show/edit
    before generating. Returns the plan in ElevenLabs shape; the client computes
    minute ranges from each section's duration_ms."""
    data = request.get_json(force=True, silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "No prompt provided"}), 400
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not set"}), 500

    music_length_min = float(data.get("music_length", 0)) or 10.0
    duration_ms = int(min(music_length_min * 60, 600) * 1000)  # ElevenLabs caps music at 600s
    root_key = data.get("root_key", "") or ""
    mood = data.get("mood", "") or ""

    from composition_planner import author_composition_plan, clamp_plan_sections
    try:
        plan_examples = favorite_prompt_exemplars(mode="musical", max_n=3)
    except Exception:
        plan_examples = None
    plan = author_composition_plan(prompt, duration_ms, root_key=root_key, mood=mood,
                                   anthropic_key=anthropic_key, style_examples=plan_examples)
    # Clamp to ElevenLabs' 120s/section cap up front so the timeline the user
    # sees and edits is exactly what gets generated (what-you-see-is-what-generates).
    plan = clamp_plan_sections(plan)
    if not plan or not plan.get("sections"):
        return jsonify({"error": "Could not author a composition plan"}), 500
    return jsonify({"composition_plan": plan, "total_ms": duration_ms})


# ── Copyright pre-flight ──────────────────────────────────────────────────────
# ElevenLabs Music rejects prompts that name copyrighted MUSIC — real artists,
# bands, composers, or song/score titles — with a bad_prompt error. In RAW mode
# the prompt is sent verbatim, so these get rejected AFTER credits are reserved
# and the layer degrades to an 8s SFX. We scan for them BEFORE spending anything.
#
# We deliberately do NOT flag fictional worlds/franchises (Dune, Arrakis, Project
# Hail Mary) — those are trademarks, not copyrighted music, and appear to pass.
# Only real people/bands/songs are high-confidence triggers. Edit COPYRIGHT_NAMES
# to tune. Non-raw modes are unaffected: the interpreter rewords names itself.
COPYRIGHT_NAMES = frozenset({
    "hans zimmer", "john williams", "howard shore", "ennio morricone", "vangelis",
    "ludwig goransson", "ludwig göransson", "daniel pemberton", "trent reznor",
    "atticus ross", "johann johannsson", "jóhann jóhannsson", "max richter",
    "olafur arnalds", "ólafur arnalds", "nils frahm", "brian eno", "aphex twin",
    "boards of canada", "stars of the lid", "tim hecker", "grouper", "william basinski",
    "sigur ros", "sigur rós", "thomas newman", "james horner", "clint mansell",
    "ramin djawadi", "junkie xl", "tom holkenborg", "hildur gudnadottir",
    "hildur guðnadóttir", "jerry goldsmith", "bernard herrmann", "philip glass",
    "steve reich", "jon hopkins", "tycho", "bonobo", "hammock", "loscil", "biosphere",
    "ryuichi sakamoto", "joe hisaishi", "yann tiersen", "moby", "burial", "four tet",
})

# Phrases that almost always introduce an artist/style reference, whatever name
# follows. Catches names not in the curated list above.
_COPYRIGHT_PHRASES = ("in the style of", "in the vein of", "-esque", "esque",
                      "à la ", "a la ", "homage to", "tribute to")


def scan_copyright_risks(text: str) -> list:
    """Return a list of copyrighted-music references found in the text
    (real artists/bands/composers/song titles). Empty list = clean."""
    low = (text or "").lower()
    found = []
    for name in COPYRIGHT_NAMES:
        if name in low:
            found.append(name.title())
    for phrase in _COPYRIGHT_PHRASES:
        if phrase in low:
            found.append(phrase.strip())
    # De-dup, preserve order.
    seen, out = set(), []
    for f in found:
        if f.lower() not in seen:
            seen.add(f.lower())
            out.append(f)
    return out


@app.route("/api/generate", methods=["POST"])
def api_generate():
    """Start a new soundscape generation job."""
    data = request.get_json(force=True, silent=True) or {}
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400

    # RAW mode sends the prompt verbatim to ElevenLabs. Block before any spend if
    # it names copyrighted music, unless the user has explicitly chosen to proceed.
    is_raw = data.get("planner_mode") == "raw"
    if is_raw and not data.get("force_copyright"):
        risks = scan_copyright_risks(prompt)
        if risks:
            return jsonify({
                "preflight": "copyright",
                "terms": risks,
                "message": (
                    "Your raw prompt names copyrighted music ("
                    + ", ".join(risks) +
                    "). ElevenLabs will likely reject it. Remove the name(s), or "
                    "generate anyway and we'll auto-retry with a sanitized rewrite."
                ),
            }), 409

    duration = float(data.get("duration", 5.0))
    music_length = float(data.get("music_length", 0))
    mastering = data.get("mastering", True)
    mode = data.get("mode", "ambient")
    reference_url = data.get("reference_url", "").strip() or None
    ref_start_sec = int(data.get("ref_start_sec", 0))
    ref_end_sec = int(data.get("ref_end_sec", 600))
    loopable = data.get("loopable", True)
    layer_plan = data.get("layer_plan")
    reference_analysis = data.get("reference_analysis")
    approach = data.get("approach", "unified")
    stem_separation = data.get("stem_separation", "none")
    planner_mode = data.get("planner_mode", "claude")
    music_generation_mode = data.get("music_generation_mode", "text")
    composition_plan = data.get("composition_plan")  # optional, edited in the UI

    print(f"  [generate] mode={mode}, approach={approach}, stem_separation={stem_separation}, "
          f"layer_plan={'yes (' + str(len(layer_plan)) + ' layers)' if layer_plan else 'no'}, "
          f"reference_analysis={'yes' if reference_analysis else 'no'}, "
          f"planner_mode={planner_mode}, music_generation_mode={music_generation_mode}")

    job_id = str(uuid.uuid4())[:8]
    with jobs_lock:
        jobs[job_id] = {
            "job_id": job_id,
            "prompt": prompt,
            "duration": duration,
            "music_length": music_length,
            "mastering": mastering,
            "mode": mode,
            "approach": approach,
            "reference_url": reference_url,
            "status": "running",
            "stage": "starting",
            "progress_message": "Starting generation...",
            "logs": [],
            "config": None,
            "audio_path": None,
            "output_path": None,
            "raw_output_path": None,
            "mastered_path": None,
            "adjuster": None,
            "feedback_history": [],
            "error": None,
            "created_at": datetime.now().isoformat(),
            "stems": None,
            "stem_files": None,
            "composition_plan": composition_plan,
            "music_generation_mode": music_generation_mode,
        }

    thread = threading.Thread(
        target=run_generation,
        args=(job_id, prompt, duration, mastering, mode, reference_url, loopable,
              music_length, ref_start_sec, ref_end_sec, layer_plan, approach,
              stem_separation, reference_analysis, planner_mode, music_generation_mode,
              composition_plan),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/cancel/<job_id>", methods=["POST"])
def api_cancel_generation(job_id: str):
    """Best-effort cancellation for an active generation job."""
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        if job.get("status") not in ("running", "stitching"):
            return jsonify({"status": job.get("status"), "message": "Job is not running"})
        job["cancel_requested"] = True
        job["status"] = "canceled"
        job["stage"] = "canceled"
        job["progress_message"] = "Generation stop requested"
        job["logs"].append({
            "time": datetime.now().isoformat(),
            "message": "Generation stop requested by user",
        })
    _save_job(job_id)
    return jsonify({"status": "canceled"})


@app.route("/api/task-status/<job_id>")
def api_task_status(job_id: str):
    """Poll a background export/visual task."""
    task = _long_task_snapshot(job_id)
    if not task:
        return jsonify({"status": "idle"})
    payload = {
        "status": task.get("status", "idle"),
        "task_type": task.get("task_type"),
        "message": task.get("message", ""),
    }
    payload.update(task.get("result") or {})
    return jsonify(payload)


@app.route("/api/cancel-task/<job_id>", methods=["POST"])
def api_cancel_task(job_id: str):
    """Stop a background task or active generation for this job."""
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404

    canceled = _long_task_cancel(job_id)

    with jobs_lock:
        job = jobs.get(job_id)
        if job and job.get("status") in ("running", "stitching"):
            job["cancel_requested"] = True
            job["status"] = "canceled"
            job["stage"] = "canceled"
            job["progress_message"] = "Generation stop requested"
            job.setdefault("logs", []).append({
                "time": datetime.now().isoformat(),
                "message": "Generation stop requested by user",
            })
            canceled = True
    if canceled:
        _save_job(job_id)
        return jsonify({"status": "canceled"})
    return jsonify({"status": "idle", "message": "Nothing to cancel"})


@app.route("/api/status/<job_id>")
def api_status(job_id: str):
    """Poll the status of a generation job."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    config = job.get("config")
    layers_data = _serialize_layers(config) if config else []

    return jsonify({
        "job_id": job["job_id"],
        "prompt": job["prompt"],
        "duration": job.get("duration", 5),
        "mode": job.get("mode", "ambient"),
        "reference_url": job.get("reference_url", ""),
        "status": job["status"],
        "stage": job["stage"],
        "progress_message": job["progress_message"],
        "logs": job["logs"][-50:],
        "warnings": job.get("warnings", []),
        "output_path": job["output_path"],
        "raw_output_path": job["raw_output_path"],
        "feedback_history": job["feedback_history"],
        "error": job["error"],
        "created_at": job["created_at"],
        "layers": layers_data,
        "root_key": config.root_key if config else "",
        "visual_image_url": f"/api/visual/image/{job['job_id']}/view" if job.get("visual_image_path") else None,
        "visual_image_prompt": job.get("visual_image_prompt", ""),
        "visual_clip_url": f"/api/visual/clip/{job['job_id']}/view" if job.get("visual_clip_path") else None,
        "visual_clip_mode": job.get("visual_clip_mode"),
        "visual_active_tab": job.get("visual_active_tab"),
        "visual_clips": {
            m: f"/api/visual/clip/{job['job_id']}/view?mode={m}"
            for m, p in (job.get("visual_clips") or {}).items() if p
        },
        "brush_mask_url": f"/api/visual/brush-mask/{job['job_id']}/view" if job.get("brush_mask_path") else None,
        # Motion editor state for the Living Still tab. Restored verbatim into
        # the editor on track open so a page refresh doesn't blow away the user's
        # composition (and the per-layer masks that are keyed by layer index).
        "motion_layers": job.get("motion_layers", []) or [],
        "motion_director_style": job.get("motion_director_style") or "balanced",
        "motion_intensity": job.get("motion_intensity"),
        "motion_loop_sec": job.get("motion_loop_sec"),
        "motion_prompt": job.get("motion_prompt", ""),
        "custom_thumbnail_url": f"/api/thumbnail/{job['job_id']}/view" if job.get("custom_thumbnail_path") else None,
        "thumbnail_design": job.get("thumbnail_design"),
        "visual_video_url": f"/api/visual/video/{job['job_id']}/download" if job.get("visual_video_path") else None,
        "youtube_url": job.get("youtube_url"),
        "yt_title": job.get("yt_title", ""),
        "yt_description": job.get("yt_description", ""),
        "yt_tags": job.get("yt_tags", ""),
        "yt_privacy": job.get("yt_privacy", "unlisted"),
        "alternate_pairs": job.get("alternate_pairs", []),
        "stems": job.get("stems"),
        "stems_status": job.get("stems_status"),
        "stems_error": job.get("stems_error"),
        "shorts": job.get("shorts", []),
        "ads_brief_md": job.get("ads_brief_md"),
        "community_drafts": job.get("community_drafts", {}),
        "reddit_drafts": job.get("reddit_drafts", {}),
        "seo_v2": job.get("seo_v2"),
        # So reopening a track restores its ElevenLabs method + composition timeline.
        "music_generation_mode": job.get("music_generation_mode")
            or (getattr(config, "music_generation_mode", None) if config else None),
        "composition_plan": job.get("composition_plan")
            or (getattr(config, "composition_plan", None) if config else None),
    })


@app.route("/api/alternate-pairs/<job_id>", methods=["POST"])
def save_alternate_pairs(job_id: str):
    """Save or clear alternate layer pairs for a job."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    data = request.get_json(force=True)
    job["alternate_pairs"] = data.get("pairs", [])
    _save_job(job_id)
    return jsonify({"ok": True})


@app.route("/api/feedback/<job_id>", methods=["POST"])
def submit_feedback(job_id: str):
    """
    Apply natural language feedback to refine the current mix.

    POST body: {"feedback": "rain is too loud, more reverb please"}

    Re-renders with cached samples (fast), skips mastering for speed.
    """
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    if job["status"] != "complete":
        return jsonify({"error": "Generation not complete yet"}), 400

    config = job.get("config")
    if not config:
        return jsonify({"error": "No config available for this job"}), 400

    data = request.get_json(force=True, silent=True) or {}
    feedback = data.get("feedback", "").strip()
    if not feedback:
        return jsonify({"error": "feedback is required"}), 400

    # Get or create per-job adjuster
    adjuster = job.get("adjuster")
    if not adjuster:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        adjuster = FeedbackAdjuster(anthropic_api_key=api_key)
        with jobs_lock:
            jobs[job_id]["adjuster"] = adjuster

    old_config = config

    try:
        revised_config, reasoning, regenerations = adjuster.adjust(feedback, config)
    except Exception as e:
        return jsonify({"error": f"Adjustment failed: {e}"}), 500

    # Handle layer regeneration if any
    regen_summaries = []
    if regenerations:
        generator = _get_sample_generator()
        if not generator:
            return jsonify({"error": "ELEVENLABS_API_KEY required for sound regeneration"}), 500

        from schemas import LayerType

        for regen in regenerations:
            layer_name = regen["layer"]
            new_prompt = regen.get("new_prompt")
            new_layer_type = regen.get("layer_type")
            layer = next((l for l in revised_config.layers if l.name == layer_name), None)
            if not layer:
                continue

            if new_prompt:
                layer.elevenlabs_prompt = new_prompt

            if new_layer_type:
                try:
                    layer.layer_type = LayerType(new_layer_type)
                except ValueError:
                    pass

            layer.generated_audio_path = None

            reroll_counts = job.setdefault("reroll_counts", {})
            seed = reroll_counts.get(layer_name, 0) + 1
            reroll_counts[layer_name] = seed

            try:
                path = generator.generate_layer_audio(
                    layer=layer,
                    mood=revised_config.mood,
                    setting=revised_config.setting,
                    root_key=revised_config.root_key,
                    track_duration_sec=revised_config.duration_sec,
                    music_length_sec=revised_config.music_length_sec,
                    reroll_seed=seed,
                )
            except Exception as e:
                from sample_generator import QuotaExhaustedError, SpendingLimitError
                if isinstance(e, (QuotaExhaustedError, SpendingLimitError)):
                    return jsonify({"error": str(e)}), 402
                print(f"  [feedback regen] {layer_name} failed: {e}")
                regen_summaries.append(f"{layer_name} (regen failed: {e})")
                path = ""
            if path:
                layer.generated_audio_path = path
                api = "Music API" if layer.layer_type == LayerType.MUSICAL else "SFX API"
                action_label = "re-rolled" if not new_prompt else f"regenerated via {api}"
                regen_summaries.append(f"{layer_name} ({action_label})")

    # Re-render at full duration (fast — samples are cached)
    try:
        engine = _get_engine()
        new_audio = engine.render_flat(revised_config)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in revised_config.title)
        audio_filename = f"{safe_title}_feedback_{timestamp}.wav"
        audio_path = str(PROJECT_ROOT / "output" / audio_filename)
        new_audio.export(audio_path, format="wav")
    except Exception as e:
        return jsonify({"error": f"Re-render failed: {e}"}), 500

    changes_summary = summarize_changes(old_config, revised_config)
    if regen_summaries:
        changes_summary += ("; " if changes_summary != "No visible changes" else "") + \
            "Regenerated: " + ", ".join(regen_summaries)

    _invalidate_flat_cache(job_id)
    with jobs_lock:
        jobs[job_id]["config"] = revised_config
        jobs[job_id]["audio_path"] = audio_path
        jobs[job_id]["mastered_path"] = None
        jobs[job_id]["feedback_history"].append({
            "feedback": feedback,
            "changes": changes_summary,
            "reasoning": reasoning,
        })

    _save_job(job_id)

    return jsonify({
        "status": "updated",
        "changes": changes_summary,
        "reasoning": reasoning,
        "audio_url": f"/api/audio/{job_id}?t={time.time()}",
        "layers": _serialize_layers(revised_config),
    })


@app.route("/api/suggest-layers/<job_id>", methods=["POST"])
def suggest_layers(job_id: str):
    """Use Claude to suggest complementary layers for the current mix."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    config = job.get("config")
    if not config:
        return jsonify({"error": "No config available"}), 400

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not set"}), 500

    current_layers = [f"- {l.name} ({l.layer_type.value}): {l.elevenlabs_prompt or 'no prompt'}" for l in config.layers if l.volume_db > -55]
    mode = job.get("mode", "ambient")

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        messages=[{
            "role": "user",
            "content": f"""You're helping someone build a {mode} soundscape. Here's what they have so far:

Prompt: "{job.get('prompt', '')}"
Current layers:
{chr(10).join(current_layers) if current_layers else "(empty — starting fresh)"}

Suggest 3-4 layers that would complement the existing mix. For each:
- A short, descriptive name (2-4 words)
- Layer type: base, mid, detail, or musical
- An ElevenLabs sound generation prompt (1-2 sentences, vivid and specific — describe the actual sound, not the emotion)
- Brief reason why it fits

Reply in this exact JSON format:
[{{"name": "...", "type": "...", "prompt": "...", "reason": "..."}}]

Output ONLY the JSON array, nothing else.""",
        }],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    try:
        suggestions = json.loads(raw)
    except json.JSONDecodeError:
        return jsonify({"error": "Failed to parse suggestions"}), 500

    return jsonify({"suggestions": suggestions})


@app.route("/api/layer-action/<job_id>", methods=["POST"])
def layer_action(job_id: str):
    """
    Direct layer manipulation without going through Claude.

    POST body:
      {"action": "mute", "layer_name": "..."}
      {"action": "unmute", "layer_name": "...", "restore_volume": -12.0}
      {"action": "regenerate", "layer_name": "..."}
      {"action": "remove", "layer_name": "..."}
      {"action": "add", "name": "...", "layer_type": "base|mid|detail|musical", "prompt": "..."}
    """
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    if job["status"] != "complete":
        return jsonify({"error": "Generation not complete yet"}), 400

    config = job.get("config")
    if not config:
        return jsonify({"error": "No config available"}), 400

    import copy
    config = copy.deepcopy(config)

    data = request.get_json(force=True, silent=True) or {}
    action = data.get("action", "")
    layer_name = data.get("layer_name", "")
    change_desc = ""

    if action == "mute":
        layer = next((l for l in config.layers if l.name == layer_name), None)
        if not layer:
            return jsonify({"error": f"Layer '{layer_name}' not found"}), 404
        layer.volume_db = -60.0
        change_desc = f"Muted {layer_name}"

    elif action == "unmute":
        layer = next((l for l in config.layers if l.name == layer_name), None)
        if not layer:
            return jsonify({"error": f"Layer '{layer_name}' not found"}), 404
        restore = data.get("restore_volume", -12.0)
        layer.volume_db = float(restore)
        change_desc = f"Unmuted {layer_name} to {restore:.0f} dB"

    elif action == "remove":
        config.layers = [l for l in config.layers if l.name != layer_name]
        change_desc = f"Removed {layer_name}"

    elif action == "regenerate":
        layer = next((l for l in config.layers if l.name == layer_name), None)
        if not layer:
            return jsonify({"error": f"Layer '{layer_name}' not found"}), 404

        generator = _get_sample_generator()
        if not generator:
            return jsonify({"error": "ELEVENLABS_API_KEY required"}), 500

        reroll_counts = job.setdefault("reroll_counts", {})
        seed = reroll_counts.get(layer_name, 0) + 1
        reroll_counts[layer_name] = seed

        layer.generated_audio_path = None
        try:
            path = generator.generate_layer_audio(
                layer=layer,
                mood=config.mood,
                setting=config.setting,
                root_key=config.root_key,
                track_duration_sec=config.duration_sec,
                music_length_sec=config.music_length_sec,
                reroll_seed=seed,
            )
        except Exception as e:
            from sample_generator import QuotaExhaustedError, SpendingLimitError
            if isinstance(e, (QuotaExhaustedError, SpendingLimitError)):
                return jsonify({"error": str(e)}), 402
            return jsonify({"error": f"Regeneration failed for '{layer_name}': {e}"}), 500
        if path:
            layer.generated_audio_path = path
        api = "Music" if layer.layer_type == LayerType.MUSICAL else "SFX"
        change_desc = f"Regenerated {layer_name} via {api} API"

    elif action == "regenerate_with_prompt":
        layer = next((l for l in config.layers if l.name == layer_name), None)
        if not layer:
            return jsonify({"error": f"Layer '{layer_name}' not found"}), 404

        new_prompt = data.get("prompt", "").strip()
        new_layer_type = data.get("layer_type")

        if not new_prompt:
            return jsonify({"error": "prompt is required"}), 400

        layer.elevenlabs_prompt = new_prompt

        if new_layer_type:
            try:
                layer.layer_type = LayerType(new_layer_type)
            except ValueError:
                pass

        generator = _get_sample_generator()
        if not generator:
            return jsonify({"error": "ELEVENLABS_API_KEY required"}), 500

        layer.generated_audio_path = None
        try:
            path = generator.generate_layer_audio(
                layer=layer,
                mood=config.mood,
                setting=config.setting,
                root_key=config.root_key,
                track_duration_sec=config.duration_sec,
                music_length_sec=config.music_length_sec,
            )
        except Exception as e:
            from sample_generator import QuotaExhaustedError, SpendingLimitError
            if isinstance(e, (QuotaExhaustedError, SpendingLimitError)):
                return jsonify({"error": str(e)}), 402
            return jsonify({"error": f"Regeneration failed for '{layer_name}': {e}"}), 500
        if path:
            layer.generated_audio_path = path
        api = "Music" if layer.layer_type == LayerType.MUSICAL else "SFX"
        change_desc = f"Regenerated {layer_name} with new prompt via {api} API"

    elif action == "add":
        new_name = data.get("name", "").strip()
        new_type_str = data.get("layer_type", "mid").strip()
        new_prompt = data.get("prompt", "").strip()

        if not new_name or not new_prompt:
            return jsonify({"error": "name and prompt are required for add"}), 400

        try:
            new_type = LayerType(new_type_str)
        except ValueError:
            new_type = LayerType.MID

        is_musical = new_type == LayerType.MUSICAL
        if is_musical and not any(
            w in new_prompt.lower()
            for w in ("0:", "1:", "2:", "3:", "4:", "5:", "arc", "enter", "minute", "third")
        ):
            new_prompt = (
                f"{new_prompt}. Gentle internal movement across the loop: one subtle element mid-way, "
                "return toward opening density by the end for seamless wrap."
            )

        is_base = new_type == LayerType.BASE
        new_layer = LayerConfig(
            name=new_name,
            layer_type=new_type,
            sample_tags=[],
            volume_db=-8.0 if is_musical else (-14.0 if is_base else -16.0),
            pan=0.0,
            loop=is_base or is_musical,
            fade_in_sec=3.0,
            fade_out_sec=3.0,
            independent_loop=is_musical,
            effects=EffectsChain(
                reverb_amount=0.4,
                reverb_room_size=0.6,
                low_pass_hz=8000 if is_base else 12000,
                high_pass_hz=40,
            ),
            elevenlabs_prompt=new_prompt,
        )

        generator = _get_sample_generator()
        if not generator:
            return jsonify({"error": "ELEVENLABS_API_KEY required"}), 500

        try:
            path = generator.generate_layer_audio(
                layer=new_layer,
                mood=config.mood,
                setting=config.setting,
                use_cache=True,
                root_key=config.root_key,
                track_duration_sec=config.duration_sec,
                music_length_sec=config.music_length_sec,
                additive=True,
            )
        except Exception as e:
            from sample_generator import QuotaExhaustedError, SpendingLimitError
            if isinstance(e, (QuotaExhaustedError, SpendingLimitError)):
                return jsonify({"error": str(e)}), 402
            print(f"  [add-layer] Generation exception for '{new_name}': {e}")
            path = ""
        if path:
            new_layer.generated_audio_path = path
            print(f"  [add-layer] Generated audio for '{new_name}': {path}")
        else:
            print(f"  [add-layer] WARNING: No audio generated for '{new_name}'")

        config.layers.append(new_layer)
        api = "Music" if is_musical else "SFX"
        change_desc = f"Added {new_name} ({new_type_str}) via {api} API"
        if not path:
            change_desc += " (audio generation failed — try regenerating)"

    elif action == "update_params":
        layer = next((l for l in config.layers if l.name == layer_name), None)
        if not layer:
            return jsonify({"error": f"Layer '{layer_name}' not found"}), 404

        params = data.get("params", {})
        parts = []
        if "volume_db" in params:
            layer.volume_db = max(-60.0, min(0.0, float(params["volume_db"])))
            parts.append(f"vol={layer.volume_db:.0f}dB")
        if "pan" in params:
            layer.pan = max(-1.0, min(1.0, float(params["pan"])))
            parts.append(f"pan={layer.pan:.1f}")
        if "reverb_amount" in params:
            if not layer.effects:
                layer.effects = EffectsChain()
            layer.effects.reverb_amount = max(0.0, min(1.0, float(params["reverb_amount"])))
            parts.append(f"reverb={layer.effects.reverb_amount:.0%}")
        if "low_pass_hz" in params:
            if not layer.effects:
                layer.effects = EffectsChain()
            layer.effects.low_pass_hz = max(200, min(20000, int(params["low_pass_hz"])))
            parts.append(f"LP={layer.effects.low_pass_hz}Hz")
        if "high_pass_hz" in params:
            if not layer.effects:
                layer.effects = EffectsChain()
            layer.effects.high_pass_hz = max(20, min(5000, int(params["high_pass_hz"])))
            parts.append(f"HP={layer.effects.high_pass_hz}Hz")
        if "independent_loop" in params:
            layer.independent_loop = bool(params["independent_loop"])
            parts.append(f"independent_loop={'on' if layer.independent_loop else 'off'}")
        if "pitch_shift_semitones" in params:
            layer.pitch_shift_semitones = max(-12, min(12, int(params["pitch_shift_semitones"])))
            parts.append(f"pitch={layer.pitch_shift_semitones:+d}st")
        if "swell_amount" in params:
            layer.swell_amount = max(0.0, min(1.0, float(params["swell_amount"])))
            parts.append(f"swell={layer.swell_amount:.0%}")
        if "swell_period_sec" in params:
            layer.swell_period_sec = max(4.0, min(60.0, float(params["swell_period_sec"])))
            parts.append(f"swell_period={layer.swell_period_sec:.0f}s")
        if "start_sec" in params:
            layer.start_sec = max(0.0, float(params["start_sec"]))
            parts.append(f"start={layer.start_sec:.0f}s")
        if "end_sec" in params:
            layer.end_sec = max(0.0, float(params["end_sec"]))
            parts.append(f"end={layer.end_sec:.0f}s")
        if "repeat_every_sec" in params:
            layer.repeat_every_sec = max(0.0, float(params["repeat_every_sec"]))
            parts.append(f"repeat={layer.repeat_every_sec:.0f}s")

        change_desc = f"{layer_name}: {', '.join(parts)}" if parts else f"No changes to {layer_name}"

    else:
        return jsonify({"error": f"Unknown action: {action}"}), 400

    # Actions that only change config (not audio files) can skip the expensive
    # full re-render when the live mixer is handling playback client-side.
    skip_render = action in ("regenerate", "regenerate_with_prompt", "add",
                             "mute", "unmute", "update_params", "remove")

    audio_path = job.get("audio_path")
    if not skip_render:
        try:
            engine = _get_engine()
            new_audio = engine.render_flat(config)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in config.title)
            audio_filename = f"{safe_title}_action_{timestamp}.wav"
            audio_path = str(PROJECT_ROOT / "output" / audio_filename)
            new_audio.export(audio_path, format="wav")
        except Exception as e:
            return jsonify({"error": f"Re-render failed: {e}"}), 500

    _invalidate_flat_cache(job_id)
    with jobs_lock:
        jobs[job_id]["config"] = config
        if audio_path:
            jobs[job_id]["audio_path"] = audio_path
        jobs[job_id]["mastered_path"] = None

    _save_job(job_id)

    return jsonify({
        "status": "updated",
        "changes": change_desc,
        "audio_url": f"/api/audio/{job_id}?t={time.time()}",
        "layers": _serialize_layers(config),
    })


@app.route("/api/finalize/<job_id>", methods=["POST"])
def finalize(job_id: str):
    """
    Render at full requested duration, master, and serve for download.
    Also updates the audio player so the user can listen to the full track.
    """
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    config = job.get("config")
    if not config:
        return jsonify({"error": "No config to finalize"}), 400

    if job.get("mastered_path"):
        resolved = _resolve_audio_path(job["mastered_path"])
        if resolved:
            return jsonify({
                "status": "ready",
                "download_url": f"/api/audio/{job_id}/download",
            })

    try:
        import copy
        full_config = copy.deepcopy(config)
        full_config.duration_sec = job["duration"] * 60

        engine = _get_engine()
        full_audio = engine.render_flat(full_config)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in full_config.title)
        raw_filename = f"{safe_title}_full_{timestamp}.wav"
        raw_path = str(PROJECT_ROOT / "output" / raw_filename)
        full_audio.export(raw_path, format="wav")

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        master = MixMasterAgent(api_key)
        mastered_path = master.process(raw_path, full_config)

        with jobs_lock:
            jobs[job_id]["mastered_path"] = mastered_path
            jobs[job_id]["output_path"] = mastered_path
            jobs[job_id]["audio_path"] = mastered_path

        _save_job(job_id)

        return jsonify({
            "status": "ready",
            "download_url": f"/api/audio/{job_id}/download",
        })

    except Exception as e:
        return jsonify({"error": f"Finalization failed: {e}"}), 500


@app.route("/api/ai-feedback/<job_id>", methods=["POST"])
def ai_feedback(job_id: str):
    """
    Send the current audio to Gemini for critique and scoring.
    Returns text notes and a 1-10 overall quality score.
    """
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    audio_path = (
        _resolve_audio_path(job.get("audio_path"))
        or _resolve_audio_path(job.get("output_path"))
        or _resolve_audio_path(job.get("raw_output_path"))
    )
    if not audio_path:
        return jsonify({"error": "No audio available"}), 400

    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        return jsonify({"error": "GEMINI_API_KEY not set"}), 500

    try:
        import google.generativeai as genai
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel("gemini-2.5-flash")

        # Listen through (at least) the FIRST FULL LOOP — the generated source is
        # ~10 minutes and the rendered file just repeats it, so the first loop IS
        # the whole composition. Grading only the first 2 minutes made it
        # impossible to judge dynamics/evolution. Sent as 128kbps stereo MP3 to
        # stay under Gemini's inline-payload limit (10 min WAV would be ~100MB).
        LOOP_SEC = 11 * 60
        full = AudioSegment.from_file(audio_path)
        snippet = full[:LOOP_SEC * 1000]
        montage_note = ""
        if len(full) > LOOP_SEC * 1000:
            montage_note = (
                "\nNOTE ON THE AUDIO: you are hearing the FIRST FULL LOOP of a "
                "longer track (the rest is the same material repeating). Judge the "
                "complete arc — opening, development, and how it returns for the "
                "loop point."
            )
        import io
        buf = io.BytesIO()
        snippet.export(buf, format="mp3", bitrate="128k")
        audio_data = buf.getvalue()

        config = job.get("config")
        prompt_desc = config.title if config else job.get("prompt", "ambient soundscape")
        mode = job.get("mode", "ambient")

        critique_prompt = f"""You are an expert audio producer reviewing an AI-generated {mode} soundscape.
The intended description: "{prompt_desc}"
This is long-form ambient music for background listening (study/work/sleep) — people may leave it on for hours.{montage_note}

Listen to this audio and provide:

1. **Score** (1-10): Overall quality rating where:
   - 1-3: Poor (major issues like silence, noise, dissonance)
   - 4-5: Below average (noticeable issues)
   - 6-7: Good (minor issues, generally pleasant)
   - 8-9: Very good (professional quality, immersive)
   - 10: Exceptional

2. **Subscores** (each 1-10) — rate how a human listener would actually experience it:
   - "dynamics": Does the piece GO somewhere? Internal movement, rises and releases,
     density shifts, elements entering and leaving. 1-3 = static wallpaper that never
     changes; 8-10 = a clear arc you can feel even at low attention.
   - "instrumentation": Depth and variety of voices. 1-3 = one or two instruments
     droning the whole time; 8-10 = a rich, layered palette where distinct instruments
     share the space and trade focus.
   - "warmth": The emotional temperature AXIS — 1 = cold/dark/heavy/sorrowful,
     10 = warm/light/comforting/hopeful. This is a MEASUREMENT, not automatically a
     quality judgment — but if the piece reads notably darker or sadder than the
     intended description calls for, say so in the notes and reflect it in the
     overall score.
   - "ear_comfort": Fatigue over hours. Harsh 2-5kHz content, piercing sustained
     tones, abrasive textures, startling moments all lower this. 8-10 = could play
     all day without grating.
   - "texture_realism": Do environmental textures (rain, wind, crickets, water,
     machinery) sound organic and alive, or artificial/looped/synthetic?
     If there are no environmental textures, judge the naturalness of the
     instrument timbres instead.
   - "space": Stereo width and sense of place. Do the layers share one coherent
     acoustic space (cohesive reverb, good depth), or sound like separate files
     stacked together?

   Weighting guidance for the overall score: dynamics and ear_comfort matter most
   for long-form listening; a static piece caps around 6 overall no matter how
   pretty the sound is.

3. **Character**: one short phrase describing the emotional read of the piece
   (e.g. "warm dawn optimism", "vast lonely cold", "cozy melancholy").

4. **Notes**: 3-5 specific, actionable observations. Cover:
   - Does it match the intended mood/description?
   - Whether it evolves or stagnates (cite where you hear it: opening/middle/ending)
   - Layer balance and mixing quality
   - Any harsh, unpleasant, or out-of-place sounds
   - Suggestions for improvement

Respond in this exact JSON format:
{{"score": <number 1-10>,
  "subscores": {{"dynamics": <1-10>, "instrumentation": <1-10>, "warmth": <1-10>,
                "ear_comfort": <1-10>, "texture_realism": <1-10>, "space": <1-10>}},
  "character": "short phrase",
  "notes": ["note 1", "note 2", "note 3"]}}"""

        response = model.generate_content(
            [critique_prompt, {"mime_type": "audio/mp3", "data": audio_data}],
        )

        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        result = json.loads(text)
        score = max(1, min(10, int(result.get("score", 5))))
        notes = result.get("notes", [])
        raw_subs = result.get("subscores") or {}
        subscores = {}
        for k in ("dynamics", "instrumentation", "warmth", "ear_comfort",
                  "texture_realism", "space"):
            try:
                subscores[k] = max(1, min(10, int(raw_subs.get(k))))
            except (TypeError, ValueError):
                pass

        return jsonify({
            "score": score,
            "notes": notes,
            "subscores": subscores,
            "character": (result.get("character") or "").strip(),
        })

    except Exception as e:
        return jsonify({"error": f"AI feedback failed: {e}"}), 500


def _resolve_audio_path(relative_path: str) -> str | None:
    """Resolve an output path to an absolute path."""
    if not relative_path:
        return None
    p = Path(relative_path)
    if p.is_absolute():
        return str(p) if p.exists() else None
    resolved = PROJECT_ROOT / relative_path
    return str(resolved) if resolved.exists() else None


@app.route("/api/audio/<job_id>/layer/<layer_name>")
def api_layer_audio(job_id: str, layer_name: str):
    """Serve an individual layer's audio, crossfaded for seamless looping."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        print(f"  [layer-audio] 404: job {job_id} not found")
        abort(404)

    config = job.get("config")
    if not config:
        print(f"  [layer-audio] 404: job {job_id} has no config")
        abort(404)

    from urllib.parse import unquote
    layer_name = unquote(layer_name)
    layer = next((l for l in config.layers if l.name == layer_name), None)
    if not layer:
        available = [l.name for l in config.layers]
        print(f"  [layer-audio] 404: layer '{layer_name}' not in config. Available: {available}")
        abort(404)
    if not layer.generated_audio_path:
        print(f"  [layer-audio] 404: layer '{layer_name}' has no generated_audio_path")
        abort(404)

    path = _resolve_audio_path(layer.generated_audio_path)
    if not path:
        print(f"  [layer-audio] 404: file not found for '{layer_name}': {layer.generated_audio_path}")
        abort(404)

    if (not BYPASS_LOOP_PREP) and layer.layer_type == LayerType.MUSICAL and getattr(config, "loopable", True):
        safe_layer = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in layer_name)[:80]
        src_stamp = int(os.path.getmtime(path))
        safe_loop_path = PROJECT_ROOT / "output" / f"{job_id}_{safe_layer}_{src_stamp}_loop.wav"
        if not safe_loop_path.exists():
            try:
                src = AudioSegment.from_file(path)
                cf_ms = int(min(getattr(config, "crossfade_seconds", 15.0), 15.0) * 1000)
                looped = prepare_musical_loop(src, cf_ms)
                looped.export(safe_loop_path, format="wav")
                path = str(safe_loop_path)
            except Exception as e:
                print(f"  [layer-audio] loop prep failed for '{layer_name}', serving raw: {e}")
        else:
            path = str(safe_loop_path)

    return send_file(path, mimetype="audio/wav", as_attachment=False)




@app.route("/api/audio/<job_id>/reprep", methods=["POST"])
def api_reprep_loops(job_id: str):
    """Delete cached loop files for this job so they regenerate with current
    loop-prep code on next playback. Use to apply algorithm changes to a
    specific song without affecting any others.
    """
    import glob
    pattern = str(PROJECT_ROOT / "output" / f"{job_id}_*_loop.wav")
    files = glob.glob(pattern)
    deleted = 0
    for f in files:
        try:
            os.remove(f)
            deleted += 1
        except OSError as e:
            print(f"  [reprep] Could not delete {f}: {e}")
    print(f"  [reprep] Cleared {deleted} cached loop file(s) for job {job_id}")
    return jsonify({"deleted": deleted, "job_id": job_id})


@app.route("/api/audio/<job_id>")
def api_audio(job_id: str):
    """Serve a flat mix (volume+pan only, no baked-in effects) matching the LiveMixer."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        abort(404)

    config = job.get("config")
    if not config:
        path = (
            _resolve_audio_path(job.get("audio_path"))
            or _resolve_audio_path(job.get("output_path"))
            or _resolve_audio_path(job.get("raw_output_path"))
        )
        if not path:
            abort(404)
        return send_file(path, mimetype="audio/wav", as_attachment=False)

    has_layers = any(
        l.generated_audio_path and os.path.exists(l.generated_audio_path)
        for l in config.layers
    )
    if not has_layers:
        path = (
            _resolve_audio_path(job.get("audio_path"))
            or _resolve_audio_path(job.get("output_path"))
            or _resolve_audio_path(job.get("raw_output_path"))
        )
        if not path:
            abort(404)
        return send_file(path, mimetype="audio/wav", as_attachment=False)

    flat_path = str(PROJECT_ROOT / "output" / f"{job_id}_flat.wav")
    if not os.path.exists(flat_path):
        try:
            engine = _get_engine()
            flat_audio = engine.render_flat(config)
            flat_audio.export(flat_path, format="wav")
            print(f"  [api_audio] Created flat mix for {job_id}: {len(flat_audio)/1000:.0f}s")
        except Exception as e:
            print(f"  [api_audio] Flat render failed for {job_id}: {e}")
            import traceback; traceback.print_exc()
            abort(500, description=f"Failed to render flat mix: {e}")

    return send_file(flat_path, mimetype="audio/wav", as_attachment=False)


@app.route("/api/audio/<job_id>/download")
def api_audio_download(job_id: str):
    """Download the flat mix (same audio as LiveMixer playback)."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        abort(404)

    flat_path = str(PROJECT_ROOT / "output" / f"{job_id}_flat.wav")
    config = job.get("config")
    if config and not os.path.exists(flat_path):
        has_layers = any(
            l.generated_audio_path and os.path.exists(l.generated_audio_path)
            for l in config.layers
        )
        if has_layers:
            try:
                engine = _get_engine()
                flat_audio = engine.render_flat(config)
                flat_audio.export(flat_path, format="wav")
            except Exception:
                flat_path = None

    if flat_path and os.path.exists(flat_path):
        return send_file(flat_path, mimetype="audio/wav", as_attachment=True)

    path = (
        _resolve_audio_path(job.get("audio_path"))
        or _resolve_audio_path(job.get("output_path"))
        or _resolve_audio_path(job.get("raw_output_path"))
    )
    if not path:
        abort(404)
    return send_file(path, mimetype="audio/wav", as_attachment=True)


@app.route("/api/detect-keys/<job_id>", methods=["POST"])
def detect_keys(job_id: str):
    """Detect musical key for each tonal layer. Returns detected key + confidence."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    config = job.get("config")
    if not config:
        return jsonify({"error": "No config available"}), 400

    results = {}
    for layer in config.layers:
        if not layer.generated_audio_path or not os.path.exists(layer.generated_audio_path):
            results[layer.name] = {"key": "?", "confidence": 0.0, "tonal": False}
            continue
        try:
            _, key_name, confidence = detect_key(layer.generated_audio_path)
            results[layer.name] = {
                "key": key_name,
                "confidence": round(confidence, 2),
                "tonal": confidence > 0.3,
            }
        except Exception as e:
            results[layer.name] = {"key": "?", "confidence": 0.0, "tonal": False}

    return jsonify({
        "keys": results,
        "root_key": config.root_key,
    })


@app.route("/api/auto-harmonize/<job_id>", methods=["POST"])
def auto_harmonize(job_id: str):
    """Run auto-harmonization: detect keys, pitch-shift outliers to match root."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    config = job.get("config")
    if not config:
        return jsonify({"error": "No config available"}), 400

    import copy
    config = copy.deepcopy(config)

    target_key = request.get_json(force=True, silent=True) or {}
    if target_key.get("root_key"):
        config.root_key = target_key["root_key"]

    try:
        harmonize_layers(config)
    except Exception as e:
        return jsonify({"error": f"Harmonization failed: {e}"}), 500

    try:
        engine = _get_engine()
        new_audio = engine.render_flat(config)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in config.title)
        audio_filename = f"{safe_title}_harmonized_{timestamp}.wav"
        audio_path = str(PROJECT_ROOT / "output" / audio_filename)
        new_audio.export(audio_path, format="wav")
    except Exception as e:
        return jsonify({"error": f"Re-render failed: {e}"}), 500

    _invalidate_flat_cache(job_id)
    with jobs_lock:
        jobs[job_id]["config"] = config
        jobs[job_id]["audio_path"] = audio_path
        jobs[job_id]["mastered_path"] = None

    _save_job(job_id)

    return jsonify({
        "status": "harmonized",
        "root_key": config.root_key,
        "audio_url": f"/api/audio/{job_id}?t={time.time()}",
        "layers": _serialize_layers(config),
    })


@app.route("/api/export-extended/<job_id>", methods=["POST"])
def export_extended(job_id: str):
    """
    Tile the current loopable audio to a target duration (e.g. 1 hour).
    Uses the crossfade-looped output and repeats it seamlessly.
    """
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    audio_path = (
        _resolve_audio_path(job.get("audio_path"))
        or _resolve_audio_path(job.get("output_path"))
        or _resolve_audio_path(job.get("raw_output_path"))
    )
    if not audio_path:
        return jsonify({"error": "No audio available"}), 400

    data = request.get_json(force=True, silent=True) or {}
    target_minutes = float(data.get("target_minutes", 60))
    target_minutes = max(1, min(480, target_minutes))
    fade_in_sec = float(data.get("fade_in_sec", 5))
    fade_out_sec = float(data.get("fade_out_sec", 5))

    def worker():
        _long_task_update(job_id, message=f"Exporting {int(target_minutes)} minute looped audio...")
        source = AudioSegment.from_file(audio_path)
        source_ms = len(source)
        if source_ms == 0:
            raise RuntimeError("Source audio is empty")
        target_ms = int(target_minutes * 60 * 1000)

        # Make the source self-seamless BEFORE tiling: cross-blend its tail into
        # its head so every repeat boundary is click-free. Without this, plain
        # concatenation reproduces the raw end→start discontinuity every cycle
        # (measured 3–7× the normal sample delta = an audible click each loop).
        loop_cf_ms = int(min(4000, max(1000, source_ms // 20)))
        source = make_loopable(source, loop_cf_ms)
        source_ms = len(source)

        import math
        repeats = math.ceil(target_ms / source_ms)
        extended = AudioSegment.empty()
        for i in range(repeats):
            _long_task_check_cancel(job_id)
            extended += source
            if i % 4 == 3:
                _long_task_update(
                    job_id,
                    message=f"Tiling audio... {min(100, int(len(extended) / target_ms * 100))}%",
                )
        extended = extended[:target_ms]

        fade_in_ms = int(fade_in_sec * 1000)
        if fade_in_ms > 0:
            extended = extended.fade_in(min(fade_in_ms, len(extended) // 4))
        fade_out_ms = int(fade_out_sec * 1000)
        if fade_out_ms > 0:
            extended = extended.fade_out(min(fade_out_ms, len(extended) // 4))

        config = job.get("config")
        title = config.title if config else "Soundscape"
        safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in title)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{safe_title}_{int(target_minutes)}min_{timestamp}.wav"
        output_path = str(PROJECT_ROOT / "output" / filename)

        _long_task_update(job_id, message="Writing WAV file...")
        _long_task_check_cancel(job_id)
        extended.export(output_path, format="wav")

        with jobs_lock:
            jobs[job_id]["extended_path"] = output_path

        _long_task_finish(job_id, "done", "Export complete", {
            "download_url": f"/api/audio/{job_id}/extended",
            "duration_minutes": target_minutes,
        })

    return _start_background_task(
        job_id, "extended_audio", f"Exporting {int(target_minutes)} minute looped audio...", worker
    )


@app.route("/api/audio/<job_id>/extended")
def api_audio_extended(job_id: str):
    """Download the extended (tiled) version."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        abort(404)
    path = _resolve_audio_path(job.get("extended_path"))
    if not path:
        abort(404)
    return send_file(path, mimetype="audio/wav", as_attachment=True)


@app.route("/api/history")
def api_history():
    """Return recent generation jobs, always including favorites and exported videos."""
    with jobs_lock:
        history = sorted(jobs.values(), key=lambda j: j["created_at"], reverse=True)
        recent = history[:50]
        favorites = [j for j in history if j.get("favorite", False)]
        with_videos = [j for j in history if j.get("visual_video_path")]

    by_id = {j["job_id"]: j for j in recent}
    for j in favorites:
        by_id[j["job_id"]] = j
    for j in with_videos:
        by_id[j["job_id"]] = j
    visible_history = sorted(by_id.values(), key=lambda j: j["created_at"], reverse=True)

    return jsonify([
        {
            "job_id": j["job_id"],
            "prompt": j["prompt"],
            "title": (getattr(j.get("config"), "title", "") or "").strip(),
            "status": j["status"],
            "duration": j["duration"],
            "feedback_count": len(j.get("feedback_history", [])),
            "created_at": j["created_at"],
            "favorite": j.get("favorite", False),
            "visual_image_url": f"/api/visual/image/{j['job_id']}/view" if j.get("visual_image_path") else None,
            "visual_clip_url": f"/api/visual/clip/{j['job_id']}/view" if j.get("visual_clip_path") else None,
            "visual_video_url": f"/api/visual/video/{j['job_id']}/download" if j.get("visual_video_path") else None,
            "youtube_url": j.get("youtube_url"),
        }
        for j in visible_history
    ])


@app.route("/api/favorite/<job_id>", methods=["POST"])
def toggle_favorite(job_id: str):
    """Toggle the favorite flag on a job."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    new_val = not job.get("favorite", False)
    with jobs_lock:
        jobs[job_id]["favorite"] = new_val
    _save_job(job_id)
    return jsonify({"favorite": new_val})


# ────────────────────────────────────────────────────────
#  Visual Generation
# ────────────────────────────────────────────────────────

def _get_visual_generator() -> VisualGenerator | None:
    api_key = os.environ.get("XAI_API_KEY")
    if not api_key:
        return None
    return VisualGenerator(xai_api_key=api_key, output_dir=str(PROJECT_ROOT / "output"))


# Each video-mode tab (AI / Living Still / Ken Burns / Upload) keeps its OWN clip
# so switching tabs doesn't clobber what you made in another. `visual_clips` maps
# tab -> path; `visual_clip_path`/`visual_clip_mode` are the ACTIVE clip (what
# export/slow/boomerang operate on); `visual_active_tab` is the current tab slot.
TAB_MODES = {"ai", "motion", "kenburns", "upload"}


def _store_clip(job_id: str, mode: str, path: str) -> None:
    """Save a freshly-generated/uploaded clip into its tab slot and make it active.

    Also records it as the tab's immutable SOURCE — speed changes always derive
    from the source, so e.g. 1x reliably reverts to the original instead of
    re-processing an already-slowed clip."""
    with jobs_lock:
        j = jobs.get(job_id)
        if not j:
            return
        clips = dict(j.get("visual_clips") or {})
        sources = dict(j.get("visual_clip_sources") or {})
        if mode in TAB_MODES:
            clips[mode] = path
            sources[mode] = path
            j["visual_clips"] = clips
            j["visual_clip_sources"] = sources
            j["visual_active_tab"] = mode
        j["visual_clip_path"] = path
        j["visual_clip_mode"] = mode
        j["visual_video_path"] = None
    _save_job(job_id)


def _clip_source_path(job: dict) -> str | None:
    """The unmodified original clip for the active tab (falls back to active clip)."""
    tab = job.get("visual_active_tab")
    sources = job.get("visual_clip_sources") or {}
    if tab in TAB_MODES and sources.get(tab):
        return sources[tab]
    # Lazy migration / fallback for clips made before source-tracking existed.
    return job.get("visual_clip_path")


def _update_active_clip(job_id: str, path: str, label: str) -> None:
    """For derived transforms (slow/boomerang/extend): replace the active clip and
    keep it filed under whichever tab is currently active."""
    with jobs_lock:
        j = jobs.get(job_id)
        if not j:
            return
        tab = j.get("visual_active_tab")
        if tab in TAB_MODES:
            clips = dict(j.get("visual_clips") or {})
            clips[tab] = path
            j["visual_clips"] = clips
        j["visual_clip_path"] = path
        j["visual_clip_mode"] = label
        j["visual_video_path"] = None
    _save_job(job_id)


# ── Parts / Interactive Builder ──────────────────────────────────────────────

@app.route("/api/parts/<job_id>", methods=["GET"])
def get_parts(job_id: str):
    """Return the list of saved parts for a job."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    parts = job.get("parts", [])
    return jsonify({"parts": [p.to_dict() for p in parts]})


@app.route("/api/parts/<job_id>", methods=["POST"])
def save_parts(job_id: str):
    """Save a full list of parts (overwrite)."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    data = request.get_json(force=True, silent=True) or {}
    raw_parts = data.get("parts", [])
    parts = [PartSnapshot.from_dict(p) for p in raw_parts]

    with jobs_lock:
        jobs[job_id]["parts"] = parts
    _save_job(job_id)

    return jsonify({"status": "saved", "count": len(parts)})


@app.route("/api/parts/<job_id>/preview/<int:part_idx>", methods=["POST"])
def preview_part(job_id: str, part_idx: int):
    """Render a single part and return audio for preview."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    config = job.get("config")
    parts = job.get("parts", [])
    if not config or part_idx >= len(parts):
        return jsonify({"error": "Invalid part index or no config"}), 400

    try:
        engine = _get_engine()
        audio = engine.render_part(config, parts[part_idx])
        preview_path = str(PROJECT_ROOT / "output" / f"part_preview_{job_id}_{part_idx}.wav")
        audio.export(preview_path, format="wav")
        return jsonify({
            "status": "ready",
            "audio_url": f"/api/parts/{job_id}/preview-audio/{part_idx}",
            "duration_sec": len(audio) / 1000.0,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/parts/<job_id>/preview-audio/<int:part_idx>")
def serve_part_preview(job_id: str, part_idx: int):
    """Serve the preview audio for a single part."""
    preview_path = PROJECT_ROOT / "output" / f"part_preview_{job_id}_{part_idx}.wav"
    if not preview_path.exists():
        abort(404)
    return send_file(str(preview_path), mimetype="audio/wav")


@app.route("/api/parts/<job_id>/stitch", methods=["POST"])
def stitch_parts_endpoint(job_id: str):
    """Render all parts, crossfade-stitch them, and replace the job audio."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    config = job.get("config")
    parts = job.get("parts", [])
    if not config or len(parts) < 1:
        return jsonify({"error": "No config or parts"}), 400

    data = request.get_json(force=True, silent=True) or {}
    fade_in = float(data.get("global_fade_in_sec", 20.0))
    fade_out = float(data.get("global_fade_out_sec", 10.0))

    with jobs_lock:
        jobs[job_id]["status"] = "stitching"
        jobs[job_id]["progress_message"] = "Stitching parts..."

    def run_stitch():
        try:
            engine = _get_engine()
            result = engine.stitch_parts(config, parts, fade_in, fade_out)
            output_path = str(PROJECT_ROOT / "output" / f"stitched_{job_id}.wav")
            result.export(output_path, format="wav")

            _invalidate_flat_cache(job_id)
            with jobs_lock:
                jobs[job_id]["audio_path"] = output_path
                jobs[job_id]["raw_output_path"] = output_path
                jobs[job_id]["output_path"] = output_path
                jobs[job_id]["status"] = "complete"
                jobs[job_id]["progress_message"] = f"Stitched {len(parts)} parts ({len(result) / 1000.0 / 60:.1f} min)"
            _save_job(job_id)
        except Exception as e:
            with jobs_lock:
                jobs[job_id]["status"] = "error"
                jobs[job_id]["error"] = str(e)

    threading.Thread(target=run_stitch, daemon=True).start()
    return jsonify({"status": "stitching", "part_count": len(parts)})


# ── Visuals ──────────────────────────────────────────────────────────────────

@app.route("/api/visual/auto-prompt/<job_id>", methods=["POST"])
def auto_visual_prompt(job_id: str):
    """Use Claude to convert a soundscape prompt into a visual image prompt."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not configured"}), 500

    soundscape_prompt = job.get("prompt", "")
    config = job.get("config")
    mood = config.mood if config else ""
    setting = config.setting if config else ""
    title = config.title if config else ""

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        messages=[{
            "role": "user",
            "content": f"""Convert this ambient soundscape description into a visual image prompt for an AI image generator.

Soundscape: {soundscape_prompt}
Title: {title}
Mood: {mood}
Setting: {setting}

Rules:
- Output ONLY the image prompt, nothing else
- Focus purely on the visual scene — no musical terms, no sound references
- Make it cinematic: describe lighting, atmosphere, camera angle, time of day
- Keep it photorealistic and moody
- Include "cinematic wide-angle photograph" at the start
- 1-3 sentences max""",
        }],
    )

    image_prompt = message.content[0].text.strip()
    return jsonify({"image_prompt": image_prompt})


@app.route("/api/visual/image/<job_id>", methods=["POST"])
def generate_visual_image(job_id: str):
    """Generate a scene image using Grok Imagine for this soundscape."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    data = request.get_json(force=True, silent=True) or {}
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "Image prompt is required"}), 400

    gen = _get_visual_generator()
    if not gen:
        return jsonify({"error": "XAI_API_KEY not configured"}), 500

    config = job.get("config")
    safe_title = "ambientizer"
    if config:
        safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in config.title)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = str(PROJECT_ROOT / "output" / f"{safe_title}_visual_{timestamp}.png")

    def worker():
        _long_task_update(job_id, message="Generating scene image...")
        image_path = gen.generate_image(prompt, output_path=output_path)
        _long_task_check_cancel(job_id)

        with jobs_lock:
            jobs[job_id]["visual_image_path"] = image_path
            jobs[job_id]["visual_image_prompt"] = prompt
        _save_job(job_id)

        _long_task_finish(job_id, "done", "Image ready", {
            "image_url": f"/api/visual/image/{job_id}/view?t={time.time()}",
        })

    return _start_background_task(job_id, "image", "Generating scene image...", worker)


@app.route("/api/visual/upload-image/<job_id>", methods=["POST"])
def upload_custom_image(job_id: str):
    """Accept a user-uploaded image (or screenshot) to use as the scene, instead
    of AI-generating one. It then animates / exports exactly like a generated one."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400

    allowed = {".png", ".jpg", ".jpeg", ".webp"}
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in allowed:
        return jsonify({"error": f"Unsupported image ({ext}). Use PNG, JPG, or WebP "
                                 f"(iPhone screenshots are PNG)."}), 400

    out_path = str(PROJECT_ROOT / "output" / f"{job_id}_custom_image{ext}")
    f.save(out_path)

    with jobs_lock:
        jobs[job_id]["visual_image_path"] = out_path
        jobs[job_id]["visual_image_prompt"] = job.get("visual_image_prompt") or "(uploaded image)"
    _save_job(job_id)

    return jsonify({
        "status": "ready",
        "image_url": f"/api/visual/image/{job_id}/view?t={time.time()}",
    })


@app.route("/api/visual/brush-mask/<job_id>", methods=["POST"])
def upload_brush_mask(job_id: str):
    """Save a hand-painted motion-brush mask (WHITE=move, BLACK/transparent=freeze).
    The frontend paints over the scene image on a canvas and POSTs the result as a
    PNG. Living Still then confines motion to the painted region."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    if "file" not in request.files:
        return jsonify({"error": "No mask uploaded"}), 400
    f = request.files["file"]
    image_path = job.get("visual_image_path")
    if not image_path:
        return jsonify({"error": "Generate or upload a scene image first"}), 400

    mask_path = str(Path(image_path).with_name(Path(image_path).stem + "_brushmask.png"))
    f.save(mask_path)

    with jobs_lock:
        jobs[job_id]["brush_mask_path"] = mask_path
    _save_job(job_id)

    return jsonify({"status": "ready"})


@app.route("/api/visual/brush-mask/<job_id>", methods=["DELETE"])
def clear_brush_mask(job_id: str):
    """Forget the saved motion-brush mask (so the whole scene animates again)."""
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        mp = job.get("brush_mask_path")
        job["brush_mask_path"] = None
    if mp and os.path.exists(mp):
        try:
            os.remove(mp)
        except OSError:
            pass
    _save_job(job_id)
    return jsonify({"status": "cleared"})


@app.route("/api/visual/brush-mask/<job_id>/view")
def view_brush_mask(job_id: str):
    """Serve the saved brush mask so the canvas can restore it on reopen."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        abort(404)
    mp = job.get("brush_mask_path")
    if not mp or not os.path.exists(mp):
        abort(404)
    return send_file(mp, mimetype="image/png")


# ── Per-layer region masks (Living Still) ─────────────────────────────────
# Each motion layer can scope its effect to a painted region. Stored by the
# layer's INDEX in motion_layers (string keys for JSON safety). Reordering
# the layer list invalidates these masks; the UI repaints when that happens.
def _layer_mask_path_for(job: dict, layer_idx: int) -> str:
    """Where the file for this layer's region mask lives on disk."""
    image_path = job.get("visual_image_path")
    if not image_path:
        return ""
    p = Path(image_path)
    return str(p.with_name(f"{p.stem}_layermask_{layer_idx}.png"))


def _autopaint_region_masks(job: dict, layers: list) -> dict:
    """Materialize the region masks the renderer would otherwise compute silently
    (sky → cloud_drift, water → shimmer, content gas → nebula) and save them as
    VISIBLE per-layer brush masks, so after Auto-plan the editor shows a 🖌 badge
    on those layers and the user can repaint/clear them.

    These are the EXACT masks the renderer auto-targets with, just materialized so
    they're editable. Returns the new {str(layer_idx): mask_path} dict.
    """
    image_path = job.get("visual_image_path")
    out: dict = {}
    if not image_path or not os.path.exists(image_path):
        return out
    try:
        import numpy as _np
        from PIL import Image as _Image
        from motion_compositor import MotionCompositor
    except Exception as e:
        print(f"  [autopaint] unavailable: {e}", flush=True)
        return out

    mc = MotionCompositor()
    _seg_cache = {}

    def _seg():
        if "done" not in _seg_cache:
            _seg_cache["sky"], _seg_cache["water"] = mc._ensure_seg_masks(image_path)
            _seg_cache["done"] = True
        return _seg_cache["sky"], _seg_cache["water"]

    for i, l in enumerate(layers):
        t = l.get("type")
        kind = None
        if t == "cloud_drift" and str(l.get("region", "sky")) == "sky":
            kind = "sky"
        elif t == "shimmer" and str(l.get("region", "")) == "water":
            kind = "water"
        elif t == "nebula":
            kind = "nebula"
        if not kind:
            continue
        dst = _layer_mask_path_for(job, i)
        if not dst:
            continue
        try:
            if kind in ("sky", "water"):
                sky_p, water_p = _seg()
                src = sky_p if kind == "sky" else water_p
                if not src or not os.path.exists(src):
                    print(f"  [autopaint] layer {i}: no {kind} segment found — left unmasked", flush=True)
                    continue
                m = _Image.open(src).convert("L")
                if (_np.asarray(m, dtype=_np.float32) / 255.0).mean() < 0.01:
                    continue  # empty mask → don't bother (renderer falls back gracefully)
                m.save(dst)
            else:  # nebula content mask
                base = _Image.open(image_path).convert("RGB")
                W, H = base.size
                if max(W, H) > 1280:
                    base.thumbnail((1280, 1280))
                    W, H = base.size
                nmask = mc._nebula_mask(W, H, base)
                if float(nmask.mean()) < 0.01:
                    continue
                _Image.fromarray((_np.clip(nmask, 0, 1) * 255).astype("uint8")).save(dst)
            out[str(i)] = dst
            print(f"  [autopaint] layer {i} ({t}) ← {kind} mask → {dst}", flush=True)
        except Exception as e:
            print(f"  [autopaint] layer {i} ({kind}) failed: {e}", flush=True)
    return out


@app.route("/api/visual/layer-mask/<job_id>/<int:layer_idx>", methods=["POST"])
def upload_layer_mask(job_id: str, layer_idx: int):
    """Save a hand-painted region mask for ONE motion layer. The compositor uses
    it to scope that layer's effect (nebula drift, shimmer, twinkle, …) to the
    painted region while other layers stay full-frame."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    if "file" not in request.files:
        return jsonify({"error": "No mask uploaded"}), 400
    image_path = job.get("visual_image_path")
    if not image_path:
        return jsonify({"error": "Generate or upload a scene image first"}), 400
    if layer_idx < 0:
        return jsonify({"error": "Invalid layer index"}), 400

    mask_path = _layer_mask_path_for(job, layer_idx)
    request.files["file"].save(mask_path)

    with jobs_lock:
        lm = dict(jobs[job_id].get("layer_masks") or {})
        lm[str(layer_idx)] = mask_path
        jobs[job_id]["layer_masks"] = lm
    _save_job(job_id)
    return jsonify({"status": "ready", "layer_idx": layer_idx,
                    "mask_url": f"/api/visual/layer-mask/{job_id}/{layer_idx}/view?t={int(time.time())}"})


@app.route("/api/visual/layer-mask/<job_id>/<int:layer_idx>", methods=["DELETE"])
def clear_layer_mask(job_id: str, layer_idx: int):
    """Forget the saved region mask for ONE motion layer (revert to full-frame)."""
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        lm = dict(job.get("layer_masks") or {})
        mp = lm.pop(str(layer_idx), None)
        job["layer_masks"] = lm
    if mp and os.path.exists(mp):
        try:
            os.remove(mp)
        except OSError:
            pass
    _save_job(job_id)
    return jsonify({"status": "cleared", "layer_idx": layer_idx})


@app.route("/api/visual/layer-mask/<job_id>/<int:layer_idx>/view")
def view_layer_mask(job_id: str, layer_idx: int):
    """Serve a saved per-layer mask so the canvas can restore it when the user
    switches the brush target back to that layer."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        abort(404)
    lm = job.get("layer_masks") or {}
    mp = lm.get(str(layer_idx))
    if not mp or not os.path.exists(mp):
        abort(404)
    return send_file(mp, mimetype="image/png")


@app.route("/api/visual/layer-mask/<job_id>/_compact", methods=["POST"])
def compact_layer_masks(job_id: str):
    """Atomically shift per-layer masks when a layer is removed from the editor.

    Per-layer masks are keyed by INDEX. Deleting layer N in the middle of the
    editor shifts every later layer's index down by 1 — but without this
    endpoint, the saved masks stay put and silently re-attach to the wrong
    effect (e.g. the twinkle mask becomes the particles mask). Frontend calls
    this immediately after a delete so the on-disk state stays consistent.

    Body: { "removed_idx": <int> }
    Effect:
      • Deletes the mask file at removed_idx (if any)
      • Renames every mask at idx > removed_idx down by 1
      • Persists the updated layer_masks dict
    """
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    body = request.get_json(force=True, silent=True) or {}
    try:
        removed_idx = int(body.get("removed_idx"))
    except (TypeError, ValueError):
        return jsonify({"error": "removed_idx required (int)"}), 400
    if removed_idx < 0:
        return jsonify({"error": "removed_idx must be >= 0"}), 400

    with jobs_lock:
        lm = dict(job.get("layer_masks") or {})
    # Sort indices ASC so we shift K → K-1 in order (no clobbering).
    items = []
    for k, v in lm.items():
        try:
            items.append((int(k), v))
        except (TypeError, ValueError):
            continue
    items.sort(key=lambda x: x[0])

    new_lm: dict = {}
    actions = {"removed": False, "shifted": []}
    for old_idx, path in items:
        if old_idx < removed_idx:
            new_lm[str(old_idx)] = path
            continue
        if old_idx == removed_idx:
            # Delete the file behind the removed layer.
            if path and os.path.exists(path):
                try: os.remove(path)
                except OSError: pass
            actions["removed"] = True
            continue
        # old_idx > removed_idx → rename file from layermask_<old> → layermask_<new>
        new_idx = old_idx - 1
        new_path = _layer_mask_path_for(job, new_idx)
        if path and os.path.exists(path):
            try:
                if os.path.exists(new_path) and new_path != path:
                    os.remove(new_path)
                os.rename(path, new_path)
            except OSError:
                new_path = path  # fall back to leaving file in place
        new_lm[str(new_idx)] = new_path
        actions["shifted"].append({"from": old_idx, "to": new_idx})

    with jobs_lock:
        job["layer_masks"] = new_lm
    _save_job(job_id)
    return jsonify({"ok": True, "removed_idx": removed_idx, **actions,
                    "layer_masks": list(new_lm.keys())})


@app.route("/api/visual/layer-mask/<job_id>", methods=["GET"])
def list_layer_masks(job_id: str):
    """List which layer indices currently have a saved per-layer region mask."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    lm = job.get("layer_masks") or {}
    items = []
    for k, p in lm.items():
        if not p or not os.path.exists(p):
            continue
        items.append({"layer_idx": int(k),
                      "mask_url": f"/api/visual/layer-mask/{job_id}/{int(k)}/view?t={int(time.time())}"})
    return jsonify({"layer_masks": items})


@app.route("/api/visual/segment-point/<job_id>", methods=["POST"])
def segment_point(job_id: str):
    """AI-assisted motion brush: SAM segments the object the user clicked and returns
    a motion mask (white=moves). mode 'freeze' freezes the clicked object (moves the
    rest); 'move' does the opposite. The frontend paints the result onto the brush
    canvas for the user to refine, then Save persists it like a hand-painted mask."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    image_path = job.get("visual_image_path")
    if not image_path or not os.path.exists(image_path):
        return jsonify({"error": "Generate or upload a scene image first"}), 400

    data = request.get_json(force=True, silent=True) or {}
    try:
        x = float(data.get("x")); y = float(data.get("y"))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid click coordinates"}), 400
    mode = "move" if data.get("mode") == "move" else "freeze"

    preview_path = str(Path(image_path).with_name(Path(image_path).stem + "_sampreview.png"))
    script = str(PROJECT_ROOT / "sam_segmenter.py")
    py = "/opt/homebrew/bin/python3.13"
    if not os.path.exists(py):
        py = "python3.13"

    def worker():
        _long_task_update(job_id, message="Segmenting the region you clicked (SAM)…")
        proc = subprocess.run(
            [py, script, image_path, str(x), str(y), preview_path, mode],
            capture_output=True, text=True, timeout=600,
        )
        _long_task_check_cancel(job_id)
        if proc.returncode != 0 or not os.path.exists(preview_path):
            raise RuntimeError(
                "Segmentation failed: " + (proc.stderr or proc.stdout or "unknown")[-300:]
            )
        with jobs_lock:
            jobs[job_id]["sam_preview_path"] = preview_path
        _long_task_finish(job_id, "done", "Region segmented", {
            "mask_url": f"/api/visual/sam-mask/{job_id}/view?t={time.time()}",
            "mode": mode,
        })

    return _start_background_task(job_id, "segment", "Segmenting the region you clicked…", worker)


@app.route("/api/visual/sam-mask/<job_id>/view")
def view_sam_mask(job_id: str):
    """Serve the most recent SAM motion-mask preview for the brush canvas."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        abort(404)
    p = job.get("sam_preview_path")
    if not p or not os.path.exists(p):
        abort(404)
    return send_file(p, mimetype="image/png")


# ── Saved Living Stills (per-song gallery) ──────────────────────────


def _find_living_still(job: dict, still_id: str) -> Optional[dict]:
    for s in job.get("saved_living_stills", []) or []:
        if s.get("id") == still_id:
            return s
    return None


def _living_still_to_payload(job_id: str, s: dict) -> dict:
    """Serialize a saved Living Still for the frontend, swapping disk paths for URLs."""
    sid = s["id"]
    return {
        "id": sid,
        "name": s.get("name", ""),
        "created_at": s.get("created_at", ""),
        "favorite": bool(s.get("favorite", False)),
        "duration_sec": s.get("duration_sec"),
        "has_mask": bool(s.get("mask_path") and os.path.exists(s["mask_path"])),
        "video_url": f"/api/visual/saved-still/{job_id}/{sid}/video",
        "thumb_url": f"/api/visual/saved-still/{job_id}/{sid}/thumb",
    }


@app.route("/api/visual/living-still/<job_id>", methods=["POST"])
def save_living_still(job_id: str):
    """Snapshot the current visual_video_path + brush_mask_path into a new saved
    Living Still slot for this song. Generates a first-frame thumbnail via ffmpeg.

    Body: { "name": "optional display name" }
    """
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    src_video = job.get("visual_video_path")
    if not src_video or not os.path.exists(src_video):
        return jsonify({"error": "No exported video to save. Render one first."}), 400

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()

    still_id = uuid.uuid4().hex[:8]
    base = PROJECT_ROOT / "output" / f"{job_id}_livingstill_{still_id}"
    dst_video = str(base.with_suffix(".mp4"))
    dst_mask = None
    dst_thumb = str(base) + "_thumb.jpg"

    try:
        shutil.copy2(src_video, dst_video)
    except Exception as e:
        return jsonify({"error": f"Could not copy video: {e}"}), 500

    src_mask = job.get("brush_mask_path")
    if src_mask and os.path.exists(src_mask):
        dst_mask = str(base) + "_mask.png"
        try:
            shutil.copy2(src_mask, dst_mask)
        except Exception as e:
            print(f"  [living-still] mask copy failed (non-fatal): {e}")
            dst_mask = None

    # Thumbnail: first frame, scaled to 1280x720 contain, JPEG q=4.
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", "0", "-i", dst_video,
             "-frames:v", "1",
             "-vf", "scale='min(1280,iw)':'min(720,ih)':force_original_aspect_ratio=decrease",
             "-q:v", "4", dst_thumb],
            check=True, capture_output=True, timeout=30,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"  [living-still] thumbnail generation failed (non-fatal): {e}")
        dst_thumb = None

    # Probe duration for the gallery card.
    duration_sec = None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", dst_video],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        if out:
            duration_sec = float(out)
    except Exception:
        pass

    if not name:
        with jobs_lock:
            existing = len(job.get("saved_living_stills") or [])
        name = f"Living Still {existing + 1}"

    record = {
        "id": still_id,
        "name": name,
        "created_at": datetime.now().isoformat(),
        "video_path": dst_video,
        "mask_path": dst_mask,
        "thumbnail_path": dst_thumb,
        "favorite": False,
        "duration_sec": duration_sec,
    }
    with jobs_lock:
        lst = job.setdefault("saved_living_stills", [])
        lst.append(record)
    _save_job(job_id)

    return jsonify({"ok": True, "still": _living_still_to_payload(job_id, record)})


@app.route("/api/visual/living-still/<job_id>", methods=["GET"])
def list_living_stills(job_id: str):
    """List all saved Living Stills for a song, sorted favorites-first then newest-first."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    items = [_living_still_to_payload(job_id, s) for s in (job.get("saved_living_stills") or [])]
    items.sort(key=lambda x: (not x["favorite"], -1 * _safe_dt(x.get("created_at"))))
    return jsonify(items)


def _safe_dt(iso: str) -> float:
    try:
        return datetime.fromisoformat(iso).timestamp() if iso else 0.0
    except Exception:
        return 0.0


@app.route("/api/visual/living-still/<job_id>/<still_id>", methods=["PATCH"])
def update_living_still(job_id: str, still_id: str):
    """Rename and/or toggle favorite on a saved Living Still.
    Body: { "name": "...", "favorite": true|false }
    """
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        s = _find_living_still(job, still_id)
        if not s:
            return jsonify({"error": "Saved still not found"}), 404
        data = request.get_json(silent=True) or {}
        if "name" in data:
            s["name"] = (data["name"] or "").strip() or s.get("name", "")
        if "favorite" in data:
            s["favorite"] = bool(data["favorite"])
    _save_job(job_id)
    return jsonify({"ok": True, "still": _living_still_to_payload(job_id, s)})


@app.route("/api/visual/living-still/<job_id>/<still_id>", methods=["DELETE"])
def delete_living_still(job_id: str, still_id: str):
    """Remove a saved Living Still entry and its files."""
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        lst = job.get("saved_living_stills") or []
        match = next((s for s in lst if s.get("id") == still_id), None)
        if not match:
            return jsonify({"error": "Saved still not found"}), 404
        job["saved_living_stills"] = [s for s in lst if s.get("id") != still_id]
    for key in ("video_path", "mask_path", "thumbnail_path"):
        p = match.get(key)
        if p and os.path.exists(p):
            try:
                os.remove(p)
            except OSError as e:
                print(f"  [living-still] could not delete {p}: {e}")
    _save_job(job_id)
    return jsonify({"ok": True})


@app.route("/api/visual/living-still/<job_id>/<still_id>/restore-mask", methods=["POST"])
def restore_living_still_mask(job_id: str, still_id: str):
    """Adopt this saved Living Still's brush mask as the song's active brush mask
    (so the user can iterate on top of an old composition)."""
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        s = _find_living_still(job, still_id)
        if not s:
            return jsonify({"error": "Saved still not found"}), 404
        mask_path = s.get("mask_path")
        if not mask_path or not os.path.exists(mask_path):
            return jsonify({"error": "This saved still has no associated mask."}), 400
        image_path = job.get("visual_image_path")
        if not image_path:
            return jsonify({"error": "Song has no scene image to attach the mask to."}), 400
        active_mask = str(Path(image_path).with_name(Path(image_path).stem + "_brushmask.png"))
        try:
            shutil.copy2(mask_path, active_mask)
        except Exception as e:
            return jsonify({"error": f"Could not restore mask: {e}"}), 500
        job["brush_mask_path"] = active_mask
    _save_job(job_id)
    return jsonify({"ok": True, "brush_mask_url": f"/api/visual/brush-mask/{job_id}/view?t={int(time.time())}"})


@app.route("/api/visual/saved-still/<job_id>/<still_id>/video")
def view_saved_still_video(job_id: str, still_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        abort(404)
    s = _find_living_still(job, still_id)
    if not s or not s.get("video_path") or not os.path.exists(s["video_path"]):
        abort(404)
    return send_file(s["video_path"], mimetype="video/mp4")


@app.route("/api/visual/saved-still/<job_id>/<still_id>/thumb")
def view_saved_still_thumb(job_id: str, still_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        abort(404)
    s = _find_living_still(job, still_id)
    p = s.get("thumbnail_path") if s else None
    if not p or not os.path.exists(p):
        abort(404)
    return send_file(p, mimetype="image/jpeg")


def _thumb_duration_label(job: dict) -> str:
    """A friendly duration for the subtitle, from the final video if available."""
    p = job.get("visual_video_path")
    if p and os.path.exists(p):
        try:
            dur = float(subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "csv=p=0", p], capture_output=True, text=True, timeout=10).stdout.strip())
            mins = int(round(dur / 60))
            if mins >= 60:
                h = mins // 60
                return f"{h} Hour" + ("s" if h > 1 else "")
            return f"{mins} Min"
        except Exception:
            pass
    return "1 Hour"


_THUMB_DIR = PROJECT_ROOT / "web" / "static" / "_thumbs"


@app.route("/api/thumbnail/styles")
def api_thumbnail_styles():
    return jsonify([{"key": k, "label": v.get("label", k)}
                    for k, v in thumbnail_maker.STYLES.items()])


@app.route("/api/thumbnail/<job_id>/previews", methods=["POST"])
def api_thumbnail_previews(job_id: str):
    """Render the given text in EVERY style on the scene image → preview grid."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    image_path = job.get("visual_image_path")
    if not image_path or not os.path.exists(image_path):
        return jsonify({"error": "No scene image. Generate or upload one in Visuals first."}), 400

    data = request.get_json(force=True, silent=True) or {}
    config = job.get("config")
    default_hook = (config.title if config else (job.get("prompt", "")[:30] or "Ambient"))
    hook = (data.get("hook") or default_hook).strip()
    subtitle = (data.get("subtitle") or f"Ambient · {_thumb_duration_label(job)}").strip()
    accent = data.get("accent") or "#f5c97a"
    position = data.get("position") if data.get("position") in ("upper", "center", "lower") else "lower"
    # Clamp on the wire too — defensive, render_thumbnail also clamps.
    try: title_scale = max(0.5, min(2.0, float(data.get("title_scale", 1.0))))
    except (TypeError, ValueError): title_scale = 1.0
    try: sub_scale = max(0.5, min(2.0, float(data.get("sub_scale", 1.0))))
    except (TypeError, ValueError): sub_scale = 1.0
    try: scrim_opacity = max(0.0, min(1.5, float(data.get("scrim_opacity", 1.0))))
    except (TypeError, ValueError): scrim_opacity = 1.0

    _THUMB_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for style in thumbnail_maker.STYLES:
        fname = f"{job_id}_{style}.jpg"
        try:
            thumbnail_maker.render_thumbnail(
                image_path, str(_THUMB_DIR / fname), hook=hook, subtitle=subtitle,
                style=style, accent=accent, position=position,
                title_scale=title_scale, sub_scale=sub_scale,
                scrim_opacity=scrim_opacity)
            out.append({"style": style, "label": thumbnail_maker.STYLES[style].get("label", style),
                        "url": f"/static/_thumbs/{fname}?t={time.time()}"})
        except Exception as e:
            print(f"  [thumbnail] {style} failed: {e}", flush=True)
    return jsonify({"previews": out, "hook": hook, "subtitle": subtitle,
                    "accent": accent, "position": position,
                    "title_scale": title_scale, "sub_scale": sub_scale,
                    "scrim_opacity": scrim_opacity})


@app.route("/api/thumbnail/<job_id>/set", methods=["POST"])
def api_thumbnail_set(job_id: str):
    """Render the chosen style at full quality and make it THE thumbnail for upload."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    image_path = job.get("visual_image_path")
    if not image_path or not os.path.exists(image_path):
        return jsonify({"error": "No scene image."}), 400

    data = request.get_json(force=True, silent=True) or {}
    style = data.get("style")
    if style not in thumbnail_maker.STYLES:
        return jsonify({"error": "Unknown style"}), 400
    config = job.get("config")
    hook = (data.get("hook") or (config.title if config else "Ambient")).strip()
    subtitle = (data.get("subtitle") or f"Ambient · {_thumb_duration_label(job)}").strip()
    accent = data.get("accent") or "#f5c97a"
    position = data.get("position") if data.get("position") in ("upper", "center", "lower") else "lower"
    try: title_scale = max(0.5, min(2.0, float(data.get("title_scale", 1.0))))
    except (TypeError, ValueError): title_scale = 1.0
    try: sub_scale = max(0.5, min(2.0, float(data.get("sub_scale", 1.0))))
    except (TypeError, ValueError): sub_scale = 1.0
    try: scrim_opacity = max(0.0, min(1.5, float(data.get("scrim_opacity", 1.0))))
    except (TypeError, ValueError): scrim_opacity = 1.0

    out_path = str(PROJECT_ROOT / "output" / f"{job_id}_thumbnail.jpg")
    thumbnail_maker.render_thumbnail(image_path, out_path, hook=hook, subtitle=subtitle,
                                     style=style, accent=accent, position=position,
                                     title_scale=title_scale, sub_scale=sub_scale,
                                     scrim_opacity=scrim_opacity)
    with jobs_lock:
        jobs[job_id]["custom_thumbnail_path"] = out_path
        jobs[job_id]["thumbnail_design"] = {"style": style, "hook": hook, "subtitle": subtitle,
                                            "accent": accent, "position": position,
                                            "title_scale": title_scale, "sub_scale": sub_scale,
                                            "scrim_opacity": scrim_opacity}
    _save_job(job_id)
    return jsonify({"status": "set", "thumbnail_url": f"/api/thumbnail/{job_id}/view?t={time.time()}"})


@app.route("/api/thumbnail/<job_id>/view")
def api_thumbnail_view(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        abort(404)
    p = job.get("custom_thumbnail_path")
    if not p or not os.path.exists(p):
        abort(404)
    return send_file(p, mimetype="image/jpeg")


@app.route("/api/visual/motion-state/<job_id>", methods=["POST"])
def save_motion_state(job_id: str):
    """Persist the Living Still editor state for a song (layers + dropdowns).

    The frontend autosaves on every meaningful edit (layer add/remove, slider
    nudge, director-style change, preset load, auto-plan completion). Without
    persistence the editor blanks out on every page refresh — which is also
    what strands the per-layer brush masks (they're keyed by layer index, so
    the brush-target dropdown can only surface a layer-N mask if layer N is
    actually in the editor).
    """
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    data = request.get_json(force=True, silent=True) or {}
    fields = {}
    if "motion_layers" in data and isinstance(data["motion_layers"], list):
        fields["motion_layers"] = data["motion_layers"]
    if "motion_director_style" in data:
        s = (data.get("motion_director_style") or "").lower()
        if s in ("subtle", "balanced", "dynamic"):
            fields["motion_director_style"] = s
    if "motion_intensity" in data:
        try:
            fields["motion_intensity"] = float(data["motion_intensity"])
        except (TypeError, ValueError):
            pass
    if "motion_loop_sec" in data:
        try:
            fields["motion_loop_sec"] = float(data["motion_loop_sec"])
        except (TypeError, ValueError):
            pass
    if "motion_prompt" in data:
        fields["motion_prompt"] = str(data["motion_prompt"] or "")
    if not fields:
        return jsonify({"ok": True, "saved": []})
    with jobs_lock:
        for k, v in fields.items():
            job[k] = v
    _save_job(job_id)
    return jsonify({"ok": True, "saved": list(fields.keys())})


@app.route("/api/visual/motion-plan/<job_id>", methods=["POST"])
def api_motion_plan(job_id: str):
    """Vision director: Claude looks at the scene image and returns a motion layer
    plan for the editor to load (so the user can then tweak it). No render.

    Accepts an optional motion_director_style in the request body (subtle / balanced
    / dynamic) — same dropdown the render endpoint reads. Auto-plan from the UI
    now passes whatever the user has selected so the styles actually affect the
    layer list that lands in the editor.
    """
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    image_path = job.get("visual_image_path")
    if not image_path or not os.path.exists(image_path):
        return jsonify({"error": "No scene image yet — generate or upload one first."}), 400
    body = request.get_json(force=True, silent=True) or {}
    director_style = (body.get("motion_director_style") or "subtle").lower()
    if director_style not in ("subtle", "balanced", "dynamic"):
        director_style = "subtle"
    scene_text = job.get("prompt", "")
    config = job.get("config")
    if config:
        scene_text = f"{config.title}. {config.description}. {scene_text}"
    print(f"[motion-plan] job={job_id} style={director_style}", flush=True)
    layers, src = choose_layers_from_image(
        image_path, scene_text,
        anthropic_key=os.environ.get("ANTHROPIC_API_KEY"),
        director_style=director_style,
    )
    print(f"[motion-plan] result src={src} count={len(layers)} layers={layers}", flush=True)

    # Auto-paint: a fresh plan replaces the layer list, so any old per-layer
    # masks (keyed by index) are now stale — drop their files, then materialize
    # the region masks for the new plan so they're VISIBLE + editable in the
    # editor instead of invisibly applied at render time.
    for _p in (job.get("layer_masks") or {}).values():
        try:
            if _p and os.path.exists(_p):
                os.remove(_p)
        except OSError:
            pass
    auto_masks = _autopaint_region_masks(job, layers)
    print(f"[motion-plan] auto-painted masks for layers {list(auto_masks.keys())}", flush=True)

    # Persist the freshly-planned layers so a refresh keeps them — the frontend
    # also autosaves, but doing it here makes auto-plan immediately durable
    # even if the user navigates away before touching anything else.
    with jobs_lock:
        job["motion_layers"] = layers
        job["motion_director_style"] = director_style
        job["layer_masks"] = auto_masks
    _save_job(job_id)
    return jsonify({"layers": layers, "source": src, "director_style": director_style,
                    "auto_masked": list(auto_masks.keys())})


@app.route("/api/visual/image/<job_id>/view")
def view_visual_image(job_id: str):
    """Serve the generated scene image."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        abort(404)
    path = job.get("visual_image_path")
    if not path or not os.path.exists(path):
        abort(404)
    return send_file(path, mimetype="image/png")


@app.route("/api/visual/clip/<job_id>", methods=["POST"])
def generate_visual_clip(job_id: str):
    """
    Generate a short video clip (10s AI animation or 30s Ken Burns) for preview.
    This is step 2 — the clip you watch before committing to a full export.

    POST body:
      mode: "ai" (~$0.50) or "kenburns" (free)
      motion_prompt: motion description for AI mode
    """
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    image_path = job.get("visual_image_path")
    if not image_path or not os.path.exists(image_path):
        return jsonify({"error": "No image generated yet."}), 400

    data = request.get_json(force=True, silent=True) or {}
    mode = data.get("mode", "ai")
    motion_prompt = data.get("motion_prompt", "").strip()

    config = job.get("config")
    safe_title = "ambientizer"
    if config:
        safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in config.title)

    if mode == "ai" and not _get_visual_generator():
        return jsonify({"error": "XAI_API_KEY not configured"}), 500

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if mode == "ai":
        start_message = "Grok is animating your image (1-3 min)..."
    elif mode == "motion":
        start_message = "Compositing living-still motion loop (~30s)..."
    else:
        start_message = "Creating Ken Burns clip..."

    def worker():
        _long_task_update(job_id, message=start_message)
        if mode == "ai":
            gen = _get_visual_generator()
            if not gen:
                raise RuntimeError("XAI_API_KEY not configured")
            mp = motion_prompt or (
                "Slow, subtle ambient motion. Gentle atmospheric movement, drifting light, "
                "peaceful and dreamy. Cinematic, minimal camera movement."
            )
            clip_path = str(PROJECT_ROOT / "output" / f"{safe_title}_aiclip_{timestamp}.mp4")
            gen.animate_image(image_path, mp, duration=10, output_path=clip_path)
        elif mode == "motion":
            # "Living Still": procedural, seamlessly-looping motion over the still.
            # Free, loops perfectly for hour-long videos. Claude picks the motion
            # preset from the scene (keyword fallback if no API key).
            scene_text = job.get("prompt", "")
            if config:
                scene_text = f"{config.title}. {config.description}. {scene_text}"
            # The user's Motion Prompt box is the primary directive when filled —
            # it lets them steer the motion ("deep space, slow drift, faint red
            # glow, no clouds") instead of relying on the soundscape text alone.
            if motion_prompt:
                scene_text = f"{motion_prompt}\n(scene context: {scene_text})"
            # Motion settings from the UI: style (auto/drift/stargaze/parallax/calm),
            # intensity (calmer↔stronger), and loop length (longer = slower motion).
            from motion_compositor import motion_style_preset, scale_motion
            motion_style = (data.get("motion_style") or "auto").lower()
            intensity = max(0.3, min(2.5, float(data.get("motion_intensity", 1.0))))
            loop_sec = max(8, min(40, float(data.get("motion_loop_sec", 16))))
            draft_scale = max(0.25, min(1.0, float(data.get("motion_draft_scale", 1.0))))
            # Director style: "subtle" (today's premium-wallpaper restraint),
            # "balanced" (3-5 layers, visible motion), or "dynamic" (4-6 layers,
            # assertive cinema). Only consulted when auto-planning.
            director_style = (data.get("motion_director_style") or "subtle").lower()
            if director_style not in ("subtle", "balanced", "dynamic"):
                director_style = "subtle"
            # Motion brush: confine motion to a painted region, freeze the rest.
            # Triggered by the UI flag; layer SELECTION still comes from the editor/
            # preset/auto director below (the brush only says WHERE motion happens).
            use_brush = bool(data.get("use_brush"))
            brush_mask_path = job.get("brush_mask_path") if use_brush else None
            if brush_mask_path and not os.path.exists(brush_mask_path):
                brush_mask_path = None
            # Per-layer region masks: each painted mask scopes a single effect's
            # region. ADDITIVE to (and independent of) the global brush above —
            # you can paint shimmer-only-on-water without confining the camera.
            layer_masks_resolved: dict = {}
            for k, p in (job.get("layer_masks") or {}).items():
                if p and os.path.exists(p):
                    layer_masks_resolved[k] = p
            user_layers = data.get("motion_layers")
            # Persist whatever the render call brought along so the editor
            # survives refresh even if the user never hit the dedicated save.
            with jobs_lock:
                jobs[job_id]["motion_layers"] = user_layers if isinstance(user_layers, list) else []
                jobs[job_id]["motion_director_style"] = director_style
                jobs[job_id]["motion_intensity"] = intensity
                jobs[job_id]["motion_loop_sec"] = loop_sec
                jobs[job_id]["motion_prompt"] = motion_prompt
            _save_job(job_id)
            if isinstance(user_layers, list) and user_layers:
                # Editor-composed layers → render EXACTLY this (what-you-see-is-what-
                # renders). Bypass presets / director / bring-to-life toggles / intensity.
                # Per-layer "enabled" flag: a muted layer stays in the editor (so
                # the user can flip it back on later) but is dropped from the render.
                # Filtering shifts indices though — also re-map per-layer mask keys
                # so each surviving layer keeps its painted region.
                from motion_compositor import _validate_layers as _vl
                old_to_new: dict[int, int] = {}
                active_user_layers = []
                for old_idx, l in enumerate(user_layers):
                    if not isinstance(l, dict):
                        continue
                    if l.get("enabled", True) is False:
                        continue
                    old_to_new[old_idx] = len(active_user_layers)
                    active_user_layers.append(l)
                if layer_masks_resolved:
                    remapped: dict = {}
                    for k, p in layer_masks_resolved.items():
                        try:
                            old_i = int(k)
                        except (TypeError, ValueError):
                            continue
                        if old_i in old_to_new:
                            remapped[str(old_to_new[old_i])] = p
                    layer_masks_resolved = remapped
                layers, src = _vl(active_user_layers), "editor"
            elif motion_style != "auto":
                layers, src = motion_style_preset(motion_style), f"style:{motion_style}"
            else:
                # Auto = VISION director: Claude looks at the actual scene image and
                # composes motion matched to what's really there (sky/gas, water,
                # lights, composition) — not guessing from text.
                _long_task_update(job_id, message=f"Claude is studying the image to plan the motion ({director_style})...")
                layers, src = choose_layers_from_image(
                    image_path, scene_text,
                    anthropic_key=os.environ.get("ANTHROPIC_API_KEY"),
                    director_style=director_style,
                )
            # Bring-to-life toggles only apply to preset/auto modes (not the editor,
            # whose layers are taken verbatim).
            if src != "editor":
                fx = data.get("motion_effects") or {}
                if isinstance(fx, dict):
                    def _set_fx(lyrs, ltype, on, default):
                        lyrs = [l for l in lyrs if l.get("type") != ltype]
                        if on:
                            lyrs.append(default)
                        return lyrs
                    if "twinkle" in fx:
                        layers = _set_fx(layers, "twinkle", fx.get("twinkle"), {"type": "twinkle", "amount": 0.8})
                    if "nebula" in fx:
                        layers = _set_fx(layers, "nebula", fx.get("nebula"), {"type": "nebula", "amount": 0.5})
                    if "water" in fx:
                        layers = _set_fx(layers, "shimmer", fx.get("water"), {"type": "shimmer", "amount": 0.5, "region": "water"})
            # "Overall movement" is a GLOBAL multiplier applied in EVERY mode — incl.
            # Auto-planned / editor / brush layers — so "same look, just more motion"
            # is one slider nudge + regenerate. At 1.0 it's a no-op (true WYSIWYG).
            print(f"[clip] job={job_id} src={src} intensity={intensity:.2f} style={director_style} "
                  f"editor_layer_count={len(layers)} layer_masks={list(layer_masks_resolved.keys())} "
                  f"global_brush={'yes' if brush_mask_path else 'no'}", flush=True)
            print(f"[clip] layers_pre_scale={layers}", flush=True)
            if abs(intensity - 1.0) > 1e-3:
                layers = scale_motion(layers, intensity)
                print(f"[clip] layers_post_scale={layers}", flush=True)
            _long_task_update(job_id, message=f"Motion: {src}, movement ×{intensity:.1f}, {loop_sec:.0f}s loop; rendering...")
            clip_path = str(PROJECT_ROOT / "output" / f"{safe_title}_motion_{timestamp}.mp4")
            MotionCompositor().render(
                image_path, clip_path, layers=layers,
                loop_sec=loop_sec, fps=24, size=(1920, 1080),
                on_status=lambda m: _long_task_update(job_id, message=m),
                brush_mask_path=brush_mask_path,
                layer_masks=layer_masks_resolved or None,
                draft_scale=draft_scale,
            )
        else:
            gen = VisualGenerator(xai_api_key="", output_dir=str(PROJECT_ROOT / "output"))
            clip_path = str(PROJECT_ROOT / "output" / f"{safe_title}_kb_{timestamp}.mp4")
            gen.create_ken_burns_video(image_path, duration_sec=30, output_path=clip_path)

        _long_task_check_cancel(job_id)

        _store_clip(job_id, mode, clip_path)

        _long_task_finish(job_id, "done", "Clip ready", {
            "clip_url": f"/api/visual/clip/{job_id}/view?t={time.time()}",
            "mode": mode,
        })

    return _start_background_task(job_id, "clip", start_message, worker)


@app.route("/api/visual/upload-video/<job_id>", methods=["POST"])
def upload_custom_video(job_id: str):
    """Accept a user-uploaded video file to use as the visual clip."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "Empty filename"}), 400

    allowed = {".mp4", ".webm", ".mov", ".avi", ".mkv"}
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in allowed:
        return jsonify({"error": f"Unsupported format ({ext}). Use MP4, WebM, MOV, AVI, or MKV."}), 400

    out_path = str(PROJECT_ROOT / "output" / f"{job_id}_custom_video{ext}")
    f.save(out_path)

    _store_clip(job_id, "upload", out_path)

    return jsonify({
        "status": "ready",
        "clip_url": f"/api/visual/clip/{job_id}/view?t={time.time()}",
        "mode": "upload",
    })


@app.route("/api/visual/extend/<job_id>", methods=["POST"])
def extend_visual_clip(job_id: str):
    """Append one Grok-generated continuation segment to the current preview clip."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    clip_path = job.get("visual_clip_path")
    if not clip_path or not os.path.exists(clip_path):
        return jsonify({"error": "No clip generated yet. Create or upload a clip first."}), 400

    gen = _get_visual_generator()
    if not gen:
        return jsonify({"error": "XAI_API_KEY not configured"}), 500

    data = request.get_json(force=True, silent=True) or {}
    prompt = data.get("prompt", "").strip()
    duration = int(data.get("duration", 10) or 10)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = Path(clip_path).stem
    extended_path = str(PROJECT_ROOT / "output" / f"{stem}_extended_{timestamp}.mp4")

    def worker():
        _long_task_update(job_id, message="Grok is extending the current clip (+10s)...")
        gen.extend_video(clip_path, prompt, duration=duration, output_path=extended_path)
        _long_task_check_cancel(job_id)

        _update_active_clip(job_id, extended_path, "extended")

        _long_task_finish(job_id, "done", "Clip extended", {
            "clip_url": f"/api/visual/clip/{job_id}/view?t={time.time()}",
            "mode": "extended",
        })

    return _start_background_task(job_id, "extend", "Grok is extending the current clip (+10s)...", worker)


@app.route("/api/visual/slow/<job_id>", methods=["POST"])
def slow_visual_clip(job_id: str):
    """Create a slowed-down preview clip and make it the active export source."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    # Speed always derives from the tab's ORIGINAL clip, never the already-slowed
    # one — so e.g. 1x reliably reverts to the original instead of compounding.
    source_path = _clip_source_path(job)
    if not source_path or not os.path.exists(source_path):
        return jsonify({"error": "No clip generated yet. Create or upload a clip first."}), 400

    data = request.get_json(force=True, silent=True) or {}
    try:
        speed = float(data.get("speed", 0.5))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid speed value"}), 400

    if speed < 0.25 or speed > 1.0:
        return jsonify({"error": "Speed must be between 0.25x and 1x"}), 400

    smooth = bool(data.get("smooth", False))

    # 1x = revert to the original clip. No processing needed — just point back.
    if abs(speed - 1.0) < 1e-6:
        _update_active_clip(job_id, source_path, "ai")  # label irrelevant; tab slot reset
        with jobs_lock:
            j = jobs.get(job_id)
            tab = j.get("visual_active_tab") if j else None
            if j and tab in TAB_MODES:
                j["visual_clip_mode"] = tab
        _save_job(job_id)
        return jsonify({
            "status": "done",
            "clip_url": f"/api/visual/clip/{job_id}/view?t={time.time()}",
            "mode": "original",
            "speed": 1.0,
        })

    gen = VisualGenerator(xai_api_key="", output_dir=str(PROJECT_ROOT / "output"))

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = Path(source_path).stem
    speed_tag = str(speed).replace(".", "p")
    smooth_tag = "_smooth" if smooth else ""
    slowed_path = str(PROJECT_ROOT / "output" / f"{stem}_speed_{speed_tag}{smooth_tag}_{timestamp}.mp4")

    msg = f"Creating {speed}x {'smooth ' if smooth else ''}slowed clip..."

    def worker():
        _long_task_update(job_id, message=msg + (" (interpolating frames — slow)" if smooth else ""))
        gen.slow_video(source_path, speed, slowed_path, smooth=smooth)
        _long_task_check_cancel(job_id)

        _update_active_clip(job_id, slowed_path, "slowed")

        _long_task_finish(job_id, "done", "Speed applied", {
            "clip_url": f"/api/visual/clip/{job_id}/view?t={time.time()}",
            "mode": "slowed",
            "speed": speed,
        })

    return _start_background_task(job_id, "slow", msg, worker)


@app.route("/api/visual/boomerang/<job_id>", methods=["POST"])
def boomerang_visual_clip(job_id: str):
    """Create a ping-pong (forward+reverse) seamless loop and make it the active source."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    clip_path = job.get("visual_clip_path")
    if not clip_path or not os.path.exists(clip_path):
        return jsonify({"error": "No clip generated yet. Create or upload a clip first."}), 400

    gen = VisualGenerator(xai_api_key="", output_dir=str(PROJECT_ROOT / "output"))

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = Path(clip_path).stem
    boom_path = str(PROJECT_ROOT / "output" / f"{stem}_boomerang_{timestamp}.mp4")

    def worker():
        _long_task_update(job_id, message="Creating boomerang (ping-pong) loop...")
        gen.boomerang_video(clip_path, boom_path)
        _long_task_check_cancel(job_id)

        _update_active_clip(job_id, boom_path, "boomerang")

        _long_task_finish(job_id, "done", "Boomerang loop created", {
            "clip_url": f"/api/visual/clip/{job_id}/view?t={time.time()}",
            "mode": "boomerang",
        })

    return _start_background_task(job_id, "boomerang", "Creating boomerang (ping-pong) loop...", worker)


@app.route("/api/visual/clip/<job_id>/view")
def view_visual_clip(job_id: str):
    """Serve the short preview clip for inline playback.

    Optional ?mode=ai|motion|kenburns|upload serves that tab's stored clip;
    otherwise serves the active clip."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        abort(404)
    mode = request.args.get("mode")
    if mode:
        path = (job.get("visual_clips") or {}).get(mode)
    else:
        path = job.get("visual_clip_path")
    if not path or not os.path.exists(path):
        abort(404)
    return send_file(path, mimetype="video/mp4")


@app.route("/api/visual/select-clip/<job_id>", methods=["POST"])
def select_clip_mode(job_id: str):
    """Make a given tab's stored clip the active one (called when switching video-mode
    tabs) so export/slow/boomerang operate on the right clip. Returns whether that
    tab has a clip and its preview URL."""
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return jsonify({"error": "Job not found"}), 404
        data = request.get_json(force=True, silent=True) or {}
        mode = data.get("mode")
        clips = dict(job.get("visual_clips") or {})
        # Lazy-migrate older jobs that only have a single active clip.
        if not clips and job.get("visual_clip_path") and job.get("visual_clip_mode") in TAB_MODES:
            clips[job["visual_clip_mode"]] = job["visual_clip_path"]
            job["visual_clips"] = clips
        path = clips.get(mode)
        has = bool(path and os.path.exists(path))
        if has:
            job["visual_clip_path"] = path
            job["visual_clip_mode"] = mode
        if mode in TAB_MODES:
            job["visual_active_tab"] = mode
    _save_job(job_id)
    return jsonify({
        "has_clip": has,
        "clip_url": f"/api/visual/clip/{job_id}/view?mode={mode}&t={time.time()}" if has else None,
        "mode": mode,
    })


@app.route("/api/visual/export/<job_id>", methods=["POST"])
def export_visual_video(job_id: str):
    """
    Loop the preview clip to target duration + combine with audio for download.
    This is step 3 — only called after the user previews and likes the clip.

    POST body:
      duration_minutes: target length (0 = same as audio track)
    """
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    clip_path = job.get("visual_clip_path")
    if not clip_path or not os.path.exists(clip_path):
        return jsonify({"error": "No clip generated yet. Create a clip first."}), 400

    # Use the flat mix (matches LiveMixer output) for video export
    config = job.get("config")
    flat_path = str(PROJECT_ROOT / "output" / f"{job_id}_flat.wav")
    audio_path = flat_path if os.path.exists(flat_path) else (
        _resolve_audio_path(job.get("audio_path"))
        or _resolve_audio_path(job.get("output_path"))
        or _resolve_audio_path(job.get("raw_output_path"))
    )
    can_render_loop = bool(
        config and any(
            l.generated_audio_path and os.path.exists(l.generated_audio_path)
            for l in config.layers
        )
    )
    if not audio_path and not can_render_loop:
        return jsonify({"error": "No audio available"}), 400

    data = request.get_json(force=True, silent=True) or {}
    target_minutes = float(data.get("duration_minutes", 0))

    def worker():
        if config and can_render_loop:
            _long_task_update(job_id, message="Rendering seamless audio loop cell...")
            _long_task_check_cancel(job_id)
            resolved_audio = _ensure_export_loop_audio(job_id, config)
        else:
            resolved_audio = (
                _resolve_audio_path(job.get("audio_path"))
                or _resolve_audio_path(job.get("output_path"))
                or _resolve_audio_path(job.get("raw_output_path"))
            )
        if not resolved_audio:
            raise RuntimeError("No audio available")

        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", resolved_audio],
            capture_output=True, text=True, timeout=10,
        )
        loop_duration_sec = float(probe.stdout.strip())
        target_sec = target_minutes * 60 if target_minutes > 0 else loop_duration_sec

        safe_title = "ambientizer"
        if config:
            safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in config.title)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        final_path = str(PROJECT_ROOT / "output" / f"{safe_title}_final_{timestamp}.mp4")

        fade_in_sec = 5.0
        fade_out_sec = 5.0
        fade_out_start = max(0.0, target_sec - fade_out_sec)
        afade_chain = (
            f"afade=t=in:st=0:d={fade_in_sec},"
            f"afade=t=out:st={fade_out_start}:d={fade_out_sec}"
        )

        # Decide whether we can STREAM-COPY the video track instead of re-encoding
        # it. The short clip is already a finished H.264 file; tiling it to an hour
        # with -stream_loop and copying the packets avoids decoding+re-encoding
        # ~86k frames — near-instant and zero generational quality loss. Each loop
        # repetition restarts at the clip's leading keyframe, so the copy is clean.
        # Uploaded clips may not be H.264/yuv420p, so we probe and fall back to a
        # re-encode in that case.
        vcodec, vpix = "", ""
        try:
            vp = subprocess.run(
                ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
                 "-show_entries", "stream=codec_name,pix_fmt",
                 "-of", "csv=p=0", clip_path],
                capture_output=True, text=True, timeout=10,
            )
            parts = vp.stdout.strip().split(",")
            vcodec = (parts[0] if parts else "").strip()
            vpix = (parts[1] if len(parts) > 1 else "").strip()
        except Exception:
            pass

        can_copy_video = vcodec == "h264" and vpix in ("yuv420p", "yuvj420p")
        if can_copy_video:
            video_args = ["-c:v", "copy"]
            video_note = "video stream-copy (no re-encode)"
        else:
            video_args = ["-c:v", "libx264", "-preset", "fast", "-crf", "20",
                          "-pix_fmt", "yuv420p"]
            video_note = f"video re-encode (source codec: {vcodec or 'unknown'})"

        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", clip_path,
            "-stream_loop", "-1", "-i", resolved_audio,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-t", str(target_sec),
            *video_args,
            "-af", afade_chain,
            "-c:a", "aac", "-b:a", "320k", "-cutoff", "20000",
            final_path,
        ]

        _long_task_update(
            job_id,
            message=(
                f"Combining with audio ({target_sec / 60:.0f} min) — fast copy..."
                if can_copy_video
                else f"Looping clip + combining with audio ({target_sec / 60:.0f} min)..."
            ),
        )
        print(
            f"  [export] Single-pass export: {target_sec/60:.0f} min, "
            f"audio loop cell {loop_duration_sec:.1f}s, {video_note} → {final_path}"
        )
        _run_ffmpeg_cancellable(job_id, cmd, total_sec=target_sec,
                                label="Looping clip + combining audio")

        size_mb = os.path.getsize(final_path) / (1024 * 1024)
        print(f"  [export] Done: {size_mb:.0f} MB")

        with jobs_lock:
            jobs[job_id]["visual_video_path"] = final_path
        _save_job(job_id)

        _long_task_finish(job_id, "done", "Export complete", {
            "download_url": f"/api/visual/video/{job_id}/download",
            "duration_minutes": target_minutes if target_minutes > 0 else loop_duration_sec / 60,
        })

    return _start_background_task(
        job_id, "export", "Looping clip + combining with audio...", worker
    )


@app.route("/api/visual/video/<job_id>/download")
def download_visual_video(job_id: str):
    """Download the final video."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        abort(404)
    path = job.get("visual_video_path")
    if not path or not os.path.exists(path):
        abort(404)
    return send_file(path, mimetype="video/mp4", as_attachment=True)


@app.route("/api/visual/video/<job_id>/view")
def view_visual_video(job_id: str):
    """Serve the final exported video for inline playback."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        abort(404)
    path = job.get("visual_video_path")
    if not path or not os.path.exists(path):
        abort(404)
    return send_file(path, mimetype="video/mp4")


# ── YouTube Publishing ────────────────────────────────────
_yt_publisher = YouTubePublisher(
    client_secret_path=str(PROJECT_ROOT / "client_secret.json"),
    token_path=str(PROJECT_ROOT / "youtube_token.json"),
)
_pending_yt_flows: dict[str, object] = {}


@app.route("/api/youtube/status")
def youtube_status():
    """Check YouTube connection status."""
    if not _yt_publisher.has_client_secret:
        return jsonify({
            "connected": False,
            "has_client_secret": False,
            "message": "Place client_secret.json in the project root. Get it from Google Cloud Console → Credentials → OAuth 2.0 Client ID.",
        })

    if _yt_publisher.is_authenticated:
        try:
            channel = _yt_publisher.validate_connection()
        except YouTubeAuthError as e:
            return jsonify({
                "connected": False,
                "has_client_secret": True,
                "needs_reconnect": True,
                "message": str(e),
            })
        except Exception as e:
            if _is_invalid_grant(e):
                _yt_publisher.disconnect()
                return jsonify({
                    "connected": False,
                    "has_client_secret": True,
                    "needs_reconnect": True,
                    "message": RECONNECT_MESSAGE,
                })
            return jsonify({
                "connected": False,
                "has_client_secret": True,
                "message": f"Could not verify YouTube connection: {e}",
            })

        return jsonify({
            "connected": True,
            "has_client_secret": True,
            "channel": channel,
        })

    return jsonify({
        "connected": False,
        "has_client_secret": True,
        "message": "Click Connect to authorize YouTube uploads.",
    })


@app.route("/api/youtube/connect", methods=["POST"])
def youtube_connect():
    """Start OAuth flow — returns a URL for the user to visit."""
    try:
        auth_url, flow = _yt_publisher.get_auth_url(redirect_uri="http://localhost:5050/oauth/callback")
        flow_id = str(uuid.uuid4())
        _pending_yt_flows[flow_id] = flow
        return jsonify({"auth_url": auth_url, "flow_id": flow_id})
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"OAuth setup failed: {e}"}), 500


@app.route("/oauth/callback")
def oauth_callback():
    """Handle Google's OAuth redirect with the authorization code."""
    code = request.args.get("code")
    if not code:
        return "Authorization failed — no code received.", 400

    flow = None
    for fid, f in list(_pending_yt_flows.items()):
        flow = f
        del _pending_yt_flows[fid]
        break

    if not flow:
        return "OAuth session expired. Go back and try Connect again.", 400

    try:
        _yt_publisher.complete_auth(flow, authorization_response=request.url)
        return """
        <html><body style="font-family:system-ui;display:flex;align-items:center;justify-content:center;min-height:100vh;background:#0d1117;color:#c9d1d9">
        <div style="text-align:center">
            <h1 style="color:#58a6ff">Connected!</h1>
            <p>YouTube account linked. You can close this tab.</p>
            <script>window.opener && window.opener.postMessage('youtube-connected','*'); setTimeout(()=>window.close(),2000);</script>
        </div></body></html>
        """
    except Exception as e:
        return f"OAuth failed: {e}", 500


@app.route("/api/youtube/disconnect", methods=["POST"])
def youtube_disconnect():
    """Remove stored YouTube credentials."""
    _yt_publisher.disconnect()
    return jsonify({"status": "disconnected"})


@app.route("/api/youtube/auto-metadata/<job_id>", methods=["POST"])
def youtube_auto_metadata(job_id: str):
    """Use Claude to generate YouTube title, description, and tags from the soundscape."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not configured"}), 500

    soundscape_prompt = job.get("prompt", "")
    config = job.get("config")
    title = config.title if config else ""
    mood = config.mood if config else ""
    setting = config.setting if config else ""

    video_duration_sec = 0
    video_path = job.get("visual_video_path")
    if video_path and os.path.exists(video_path):
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "csv=p=0", video_path],
                capture_output=True, text=True, timeout=10,
            )
            video_duration_sec = int(float(probe.stdout.strip()))
        except Exception:
            pass
    if video_duration_sec == 0:
        video_duration_sec = 3600  # default to 1 hour — Cole publishes 1-hour videos

    hours = video_duration_sec // 3600
    if hours >= 1:
        duration_str = "1 Hour" if hours == 1 else f"{hours} Hours"
    else:
        duration_str = f"{video_duration_sec // 60} Minutes"

    layers_desc = ""
    if config and config.layers:
        layers_desc = ", ".join(
            f"{l.name} ({l.layer_type.value})" for l in config.layers
        )

    parts = job.get("parts", [])
    timestamps_hint = ""
    if parts and len(parts) > 1:
        elapsed = 0
        ts_lines = []
        for p in parts:
            h, m, s = int(elapsed // 3600), int((elapsed % 3600) // 60), int(elapsed % 60)
            ts = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
            ts_lines.append(f"{ts} {p.name}")
            elapsed += p.duration_sec
        timestamps_hint = "\nActual part timestamps (use these EXACTLY in the description):\n" + "\n".join(ts_lines)

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)

    no_timestamps_rule = (
        "Include these REAL chapter timestamps exactly as given above."
        if timestamps_hint else
        "Do NOT invent timestamps or chapter markers — this is one continuous "
        "seamless loop, so fake time points look amateur. Omit them entirely."
    )
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1300,
        messages=[{
            "role": "user",
            "content": f"""Write YouTube metadata for an ambient / cinematic music video, modeled on what performs for ambient, sci-fi, and study/focus channels. The DESCRIPTION is a short immersive story (no marketing copy); the TAGS carry the SEO.

SOURCE BRIEF: {soundscape_prompt}
Internal title: {title} | Mood: {mood} | Setting: {setting} | Duration: {duration_str}
Layers: {layers_desc}{timestamps_hint}

STEP 1 — Identify the SUBJECT HOOK: the single most recognizable thing this evokes (a book/film/universe, a real place, or a vivid concept — e.g. "Project Hail Mary", "Dune", "a cabin in a snowstorm"). The TITLE must lead with it verbatim. The story may reference it naturally but should not feel like an ad.

TITLE (keep it SHORT — aim <70 chars, hard max 90; no emoji, no clickbait):
- Pattern: "<Subject Hook> — <Short Evocative Descriptor> | {duration_str} <Genre>"
- Example: "Project Hail Mary — Adrift in the Silent Void | 1 Hour Space Ambient"
- Emotional/sensory words beat neutral ones. Must contain the subject hook verbatim. Must use the duration "{duration_str}".

DESCRIPTION — JUST THE STORY (sound HUMAN, not AI; specific and grounded, no purple filler):
- Open DIRECTLY with the story. NO opening hook/tagline like "X music for anyone who...", NO "Best for:" line, NO "subscribe/comment" CTA.
- 2-3 short paragraphs of immersive, atmospheric story set in the scene — sensory but restrained, like a person wrote it.
- {no_timestamps_rule}
- End with EXACTLY 3 relevant hashtags on their own line — the subject hook + two genre/use-case tags (e.g. #ProjectHailMary #SpaceAmbient #StudyMusic). This is the only non-story element.

TAGS (15-25) — this is where ALL the SEO lives: blend (a) SPECIFIC — the subject hook + closely related terms; (b) GENRE — space ambient, sci-fi ambient, cinematic ambient, etc.; (c) MOOD; (d) high-intent USE-CASE long-tails people actually search — study music, sleep music, focus music, reading music, 1 hour ambient. Favor long-tail phrases over single broad words.

Reply in EXACTLY this JSON format:
{{
  "title": "...",
  "description": "...",
  "tags": ["tag1", "tag2", ...]
}}

Output ONLY the JSON, nothing else.""",
        }],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]

    try:
        metadata = json.loads(raw)
    except json.JSONDecodeError:
        return jsonify({"error": "Failed to parse generated metadata", "raw": raw}), 500

    with jobs_lock:
        jobs[job_id]["yt_title"] = metadata.get("title", "")
        jobs[job_id]["yt_description"] = metadata.get("description", "")
        tags = metadata.get("tags", [])
        jobs[job_id]["yt_tags"] = ", ".join(tags) if isinstance(tags, list) else tags
    _save_job(job_id)

    return jsonify(metadata)


@app.route("/upload")
def upload_page():
    """Standalone upload progress window."""
    return render_template("upload.html")


@app.route("/api/youtube/upload/<job_id>", methods=["POST"])
def youtube_upload(job_id: str):
    """Start a YouTube upload in the background. Returns immediately."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    video_path = job.get("visual_video_path")
    if not video_path or not os.path.exists(video_path):
        return jsonify({"error": "No exported video found. Export a video first."}), 400

    if not _yt_publisher.is_authenticated:
        return jsonify({"error": "YouTube not connected. Click Connect first."}), 401

    try:
        _yt_publisher.validate_connection()
    except YouTubeAuthError as e:
        return jsonify({"error": str(e), "needs_reconnect": True}), 401
    except Exception as e:
        if _is_invalid_grant(e):
            _yt_publisher.disconnect()
            return jsonify({"error": RECONNECT_MESSAGE, "needs_reconnect": True}), 401
        return jsonify({"error": f"YouTube connection check failed: {e}"}), 500

    data = request.get_json(force=True, silent=True) or {}
    title = data.get("title", "").strip()
    description = data.get("description", "").strip()
    tags = data.get("tags", [])
    privacy = data.get("privacy", "unlisted")

    if not title:
        return jsonify({"error": "Title is required"}), 400

    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    # Prefer the branded text-overlay thumbnail if the user made one.
    thumbnail_path = job.get("custom_thumbnail_path")
    if not thumbnail_path or not os.path.exists(thumbnail_path):
        thumbnail_path = job.get("visual_image_path")

    with jobs_lock:
        jobs[job_id]["upload_status"] = "uploading"
        jobs[job_id]["upload_progress"] = 0
        jobs[job_id]["upload_message"] = "Starting upload..."
        jobs[job_id]["yt_title"] = title
        jobs[job_id]["yt_description"] = description
        jobs[job_id]["yt_tags"] = ", ".join(tags) if isinstance(tags, list) else tags
        jobs[job_id]["yt_privacy"] = privacy
    _save_job(job_id)

    # Spawn a fully independent subprocess so the upload survives server
    # restarts / auto-reloads.  Progress is written to a JSON file on disk
    # that the status endpoint reads.
    status_file = str(PROJECT_ROOT / "output" / f"{job_id}_upload_status.json")
    # Reset the status file BEFORE spawning so the /upload tab (which polls this
    # file immediately) can't read a stale "error" from a previous attempt and
    # show "Failed" while the new worker is actually succeeding.
    try:
        with open(status_file, "w") as _sf:
            json.dump({"status": "uploading", "progress": 0,
                       "message": "Starting upload..."}, _sf)
    except OSError:
        pass
    worker_params = json.dumps({
        "status_file": status_file,
        "video_path": video_path,
        "title": title,
        "description": description,
        "tags": tags,
        "privacy": privacy,
        "thumbnail_path": thumbnail_path,
        "client_secret": str(PROJECT_ROOT / "client_secret.json"),
        "token_path": str(PROJECT_ROOT / "youtube_token.json"),
    })
    worker_script = str(PROJECT_ROOT / "upload_worker.py")
    worker_log = str(PROJECT_ROOT / "output" / f"{job_id}_upload_worker.log")
    print(f"  [YT Upload {job_id[:8]}] Spawning upload worker subprocess → {worker_log}")
    log_fh = open(worker_log, "w")
    subprocess.Popen(
        [sys.executable, "-u", worker_script, worker_params],
        start_new_session=True,
        stdout=log_fh,
        stderr=log_fh,
    )
    return jsonify({"status": "uploading"})


@app.route("/api/youtube/upload-status/<job_id>")
def youtube_upload_status(job_id: str):
    """Poll upload progress from the worker's status file on disk."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    status_file = PROJECT_ROOT / "output" / f"{job_id}_upload_status.json"
    if status_file.exists():
        try:
            data = json.loads(status_file.read_text())
        except (json.JSONDecodeError, OSError):
            data = {}

        # When the worker finishes, persist the result into the job so it
        # survives in history / _save_job.
        if data.get("status") == "done" and data.get("youtube_url"):
            with jobs_lock:
                jobs[job_id]["youtube_url"] = data["youtube_url"]
                jobs[job_id]["youtube_video_id"] = data.get("video_id", "")
                jobs[job_id]["upload_status"] = "done"
                jobs[job_id]["upload_progress"] = 100
                jobs[job_id]["upload_message"] = data["youtube_url"]
            _save_job(job_id)

        elif data.get("status") == "error":
            with jobs_lock:
                jobs[job_id]["upload_status"] = "error"
                jobs[job_id]["upload_message"] = data.get("message", "Upload failed")

        return jsonify({
            "status": data.get("status", "uploading"),
            "progress": data.get("progress", 0),
            "message": data.get("message", ""),
            "youtube_url": data.get("youtube_url"),
        })

    # No status file — if the job still says "uploading" it means the worker
    # died (e.g. server was restarted before the subprocess fix was live).
    # Report it as failed so the user can retry instead of polling forever.
    mem_status = job.get("upload_status", "idle")
    if mem_status == "uploading":
        mem_status = "error"
        with jobs_lock:
            jobs[job_id]["upload_status"] = "error"
            jobs[job_id]["upload_message"] = "Upload was interrupted (server restarted). Please try again."

    return jsonify({
        "status": mem_status,
        "progress": job.get("upload_progress", 0),
        "message": job.get("upload_message", ""),
        "youtube_url": job.get("youtube_url"),
    })


# ═══════════════════════════════════════════════════════════════════
#  DISTRIBUTE TAB
#  Channel-wide growth automation: catalog, Shorts, SEO v2, Ads brief,
#  Community / Reddit / Discord drafts, 24/7 live stream.
# ═══════════════════════════════════════════════════════════════════


def _job_must_exist(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return None
    return job


def _yt_video_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    if "watch?v=" in url:
        return url.split("watch?v=", 1)[1].split("&", 1)[0]
    if "youtu.be/" in url:
        return url.split("youtu.be/", 1)[1].split("?", 1)[0]
    return None


# ── Catalog ─────────────────────────────────────────────────────────


@app.route("/api/distribute/attach-youtube/<job_id>", methods=["POST"])
def api_distribute_attach_youtube(job_id: str):
    """Attach an existing YouTube URL to a job whose upload didn't write back.

    Useful when the resumable upload completed but a later step (e.g. thumbnail)
    failed and the worker marked the upload as errored — the video exists on
    YouTube but the job lost the link. Optionally re-applies the job's
    thumbnail by hitting youtube.thumbnails().set() with the compressed image.
    """
    job = _job_must_exist(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    payload = request.get_json(silent=True) or {}
    url = (payload.get("youtube_url") or "").strip()
    apply_thumbnail = bool(payload.get("apply_thumbnail", True))
    video_id = _yt_video_id_from_url(url)
    if not video_id:
        return jsonify({"error": "Could not parse a video id from that URL."}), 400

    with jobs_lock:
        jobs[job_id]["youtube_url"] = url
        jobs[job_id]["youtube_video_id"] = video_id
    _save_job(job_id)

    thumb_msg = None
    if apply_thumbnail and job.get("visual_image_path") and os.path.exists(job["visual_image_path"]):
        try:
            from youtube_publisher import _prepare_thumbnail
            from googleapiclient.http import MediaFileUpload
            yt = _yt_publisher._get_youtube()
            prepared, mime, is_temp = _prepare_thumbnail(job["visual_image_path"])
            if prepared:
                try:
                    yt.thumbnails().set(
                        videoId=video_id,
                        media_body=MediaFileUpload(prepared, mimetype=mime),
                    ).execute()
                    thumb_msg = "Thumbnail applied."
                finally:
                    if is_temp:
                        try:
                            os.remove(prepared)
                        except OSError:
                            pass
            else:
                thumb_msg = "Thumbnail skipped (could not fit under 2 MB)."
        except Exception as e:
            thumb_msg = f"Thumbnail not applied: {e}"

    return jsonify({
        "ok": True,
        "youtube_url": url,
        "youtube_video_id": video_id,
        "thumbnail": thumb_msg,
    })


@app.route("/api/distribute/catalog")
def api_distribute_catalog():
    """All catalog rows the Distribute tab can operate on.

    Returns every job with an exported video, plus growth-state counters.
    """
    with jobs_lock:
        rows = []
        for j in jobs.values():
            if not j.get("visual_video_path"):
                continue
            shorts_list = j.get("shorts") or []
            shorts_published = sum(1 for s in shorts_list if s.get("youtube_url"))
            rows.append({
                "job_id": j["job_id"],
                "prompt": j.get("prompt", ""),
                "title": (j.get("config").title if j.get("config") else None) or j.get("prompt", "")[:60],
                "mood": j.get("config").mood if j.get("config") else "",
                "setting": j.get("config").setting if j.get("config") else "",
                "duration": j.get("duration", 0),
                "created_at": j.get("created_at", ""),
                "favorite": j.get("favorite", False),
                "youtube_url": j.get("youtube_url"),
                "visual_image_url": f"/api/visual/image/{j['job_id']}/view" if j.get("visual_image_path") else None,
                "visual_video_url": f"/api/visual/video/{j['job_id']}/download" if j.get("visual_video_path") else None,
                "shorts_total": len(shorts_list),
                "shorts_published": shorts_published,
                "has_ads_brief": bool(j.get("ads_brief_md")),
                "has_seo_v2": bool(j.get("seo_v2")),
                "last_promoted_at": j.get("last_promoted_at"),
            })
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    return jsonify(rows)


# ── Shorts factory ──────────────────────────────────────────────────


@app.route("/api/distribute/shorts/<job_id>")
def api_shorts_list(job_id: str):
    job = _job_must_exist(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    shorts = job.get("shorts") or []
    parent_url = job.get("youtube_url")
    out = []
    for s in shorts:
        out.append({
            **{k: v for k, v in s.items() if k != "video_path"},
            "preview_url": f"/api/distribute/shorts/{s['short_id']}/preview"
                           if s.get("video_path") and os.path.exists(s["video_path"]) else None,
            "parent_youtube_url": parent_url,
        })
    return jsonify(out)


def _find_short(short_id: str) -> tuple[Optional[dict], Optional[dict]]:
    """Return (job, short) for a given short_id, or (None, None)."""
    with jobs_lock:
        for j in jobs.values():
            for s in (j.get("shorts") or []):
                if s.get("short_id") == short_id:
                    return j, s
    return None, None


@app.route("/api/distribute/shorts/<short_id>/preview")
def api_short_preview(short_id: str):
    _, s = _find_short(short_id)
    if not s or not s.get("video_path") or not os.path.exists(s["video_path"]):
        abort(404)
    return send_file(s["video_path"], mimetype="video/mp4", conditional=True)


@app.route("/api/distribute/shorts/<short_id>", methods=["DELETE"])
def api_short_delete(short_id: str):
    job, s = _find_short(short_id)
    if not s:
        return jsonify({"error": "Short not found"}), 404
    try:
        if s.get("video_path") and os.path.exists(s["video_path"]):
            os.remove(s["video_path"])
    except OSError:
        pass
    with jobs_lock:
        job["shorts"] = [x for x in job.get("shorts", []) if x.get("short_id") != short_id]
    _save_job(job["job_id"])
    return jsonify({"deleted": short_id})


@app.route("/api/distribute/shorts/<job_id>/generate", methods=["POST"])
def api_shorts_generate(job_id: str):
    """Generate one or more vertical Shorts from a parent job.

    Body:
      {
        "count": 1-3,
        "mode": "auto" | "first" | "middle" | "last" | "manual",
        "manual_start_sec": float (only when mode == "manual"),
        "clip_sec": 30-60 (default 50),
        "visual_mode": "auto" | "crop" | "image"
      }
    """
    job = _job_must_exist(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    parent_video = job.get("visual_video_path")
    parent_image = job.get("visual_image_path")
    if not parent_video and not parent_image:
        return jsonify({"error": "No parent video or image. Generate a video first."}), 400

    audio_path = (
        _resolve_audio_path(job.get("audio_path"))
        or _resolve_audio_path(job.get("output_path"))
        or _resolve_audio_path(job.get("raw_output_path"))
    )
    if not audio_path or not os.path.exists(audio_path):
        # Fallback to the rendered final video's audio track.
        audio_path = parent_video
    if not audio_path:
        return jsonify({"error": "No audio source for short"}), 400

    data = request.get_json(force=True, silent=True) or {}
    count = max(1, min(3, int(data.get("count", 1))))
    mode = data.get("mode", "auto")
    manual_start = float(data.get("manual_start_sec", 0))
    clip_sec = float(data.get("clip_sec", 50))
    clip_sec = max(15.0, min(60.0, clip_sec))
    visual_mode = data.get("visual_mode", "auto")

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    gemini_key = os.environ.get("GEMINI_API_KEY", "")

    def worker():
        parent_dur = distribute_shorts._ffprobe_duration(parent_video or audio_path)
        # The segment window MUST stay within the AUDIO too: the parent video may be
        # the hour-long export while the audio is the shorter raw loop. Picking a
        # moment past the end of the audio seeks into silence → a soundless short.
        audio_dur = distribute_shorts._ffprobe_duration(audio_path) or parent_dur
        seg_dur = min(parent_dur, audio_dur) if audio_dur else parent_dur
        for i in range(count):
            _long_task_check_cancel(job_id)
            _long_task_update(job_id, message=f"Generating short {i + 1}/{count}: picking moment...")

            # Pick segment window (bounded by seg_dur so audio always exists).
            if mode == "manual":
                start_sec = max(0.0, min(seg_dur - clip_sec, manual_start))
                desc = "User-selected moment"
            elif mode in ("first", "middle", "last"):
                start_sec = distribute_shorts.preset_window(seg_dur, mode, clip_sec)
                desc = f"{mode.capitalize()} segment"
            else:
                # auto — offset each subsequent short so we don't pick the same moment.
                if i == 0:
                    start_sec, desc = distribute_shorts.pick_segment_auto(
                        audio_path, clip_sec=clip_sec, gemini_api_key=gemini_key,
                    )
                    start_sec = max(0.0, min(seg_dur - clip_sec, start_sec))
                else:
                    # Stagger across the track for variety
                    fraction = (i + 0.5) / count
                    start_sec = max(0.0, min(seg_dur - clip_sec, fraction * (seg_dur - clip_sec)))
                    desc = f"Atmospheric moment {i + 1}"

            short_id = distribute_shorts.new_short_id()
            out_path = str(distribute_shorts.shorts_dir(PROJECT_ROOT) / f"{job_id}_{short_id}.mp4")

            _long_task_update(job_id, message=f"Generating short {i + 1}/{count}: rendering video...")
            distribute_shorts.build_short_video(
                parent_video, parent_image, audio_path,
                start_sec, clip_sec, out_path,
                mode=visual_mode,
                on_log=lambda s: _long_task_update(job_id, message=s),
            )
            _long_task_check_cancel(job_id)

            # Never ship a silent Short: verify the render actually has an audio stream.
            acodec = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "a:0",
                 "-show_entries", "stream=codec_name", "-of", "csv=p=0", out_path],
                capture_output=True, text=True,
            ).stdout.strip()
            if not acodec:
                raise RuntimeError(
                    f"Short {i + 1} rendered with no audio (start {start_sec:.0f}s). Aborted "
                    "so it isn't published silent."
                )

            # Metadata.
            _long_task_update(job_id, message=f"Generating short {i + 1}/{count}: writing metadata...")
            try:
                meta = distribute_shorts.claude_short_metadata(
                    parent_title=(job.get("config").title if job.get("config") else job.get("prompt", "")[:60]),
                    parent_mood=(job.get("config").mood if job.get("config") else ""),
                    parent_setting=(job.get("config").setting if job.get("config") else ""),
                    moment_description=desc,
                    parent_youtube_url=job.get("youtube_url"),
                    anthropic_api_key=anthropic_key,
                ) if anthropic_key else {
                    "title": f"Ambient moment — {(job.get('config').title if job.get('config') else 'soundscape')} #Shorts",
                    "description": desc,
                    "tags": ["ambient", "shorts", "soundscape"],
                }
            except Exception as e:
                meta = {
                    "title": f"Ambient moment #Shorts",
                    "description": f"{desc}\n(metadata failed: {e})",
                    "tags": ["ambient", "shorts"],
                }

            record = distribute_shorts.short_record(
                short_id, job_id, out_path, start_sec, clip_sec, desc, meta,
                visual_mode=visual_mode,
            )

            with jobs_lock:
                if "shorts" not in jobs[job_id] or jobs[job_id]["shorts"] is None:
                    jobs[job_id]["shorts"] = []
                jobs[job_id]["shorts"].append(record)
            _save_job(job_id)

        _long_task_finish(job_id, "done", f"Generated {count} short(s)", {
            "shorts_count": count,
        })

    return _start_background_task(
        job_id, "shorts_generate", f"Generating {count} short(s)...", worker
    )


@app.route("/api/distribute/shorts/<short_id>/metadata", methods=["POST"])
def api_short_update_metadata(short_id: str):
    """Edit a Short's title/description/tags before publishing."""
    job, s = _find_short(short_id)
    if not s:
        return jsonify({"error": "Short not found"}), 404
    data = request.get_json(force=True, silent=True) or {}
    if "title" in data:
        s["yt_title"] = (data["title"] or "").strip()
    if "description" in data:
        s["yt_description"] = (data["description"] or "").strip()
    if "tags" in data:
        t = data["tags"]
        s["yt_tags"] = [x.strip() for x in t.split(",")] if isinstance(t, str) else list(t)
    _save_job(job["job_id"])
    return jsonify({"updated": short_id})


@app.route("/api/distribute/shorts/<short_id>/publish", methods=["POST"])
def api_short_publish(short_id: str):
    """Upload a Short to YouTube via the same upload_worker.py path."""
    job, s = _find_short(short_id)
    if not s:
        return jsonify({"error": "Short not found"}), 404

    video_path = s.get("video_path")
    if not video_path or not os.path.exists(video_path):
        return jsonify({"error": "Short video file not found"}), 400

    if not _yt_publisher.is_authenticated:
        return jsonify({"error": "YouTube not connected. Connect on the Publish tab first."}), 401

    try:
        _yt_publisher.validate_connection()
    except YouTubeAuthError as e:
        return jsonify({"error": str(e), "needs_reconnect": True}), 401
    except Exception as e:
        if _is_invalid_grant(e):
            _yt_publisher.disconnect()
            return jsonify({"error": RECONNECT_MESSAGE, "needs_reconnect": True}), 401
        return jsonify({"error": f"YouTube check failed: {e}"}), 500

    data = request.get_json(force=True, silent=True) or {}
    title = (data.get("title") or s.get("yt_title") or "Ambient moment #Shorts").strip()
    description = (data.get("description") or s.get("yt_description") or "").strip()
    tags = data.get("tags", s.get("yt_tags", []))
    privacy = data.get("privacy", "unlisted")

    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    # The upload_worker writes status to a file named after the "job_id" passed
    # in. Reuse the short_id slot in the same output dir.
    status_file = str(PROJECT_ROOT / "output" / f"{short_id}_upload_status.json")
    # Reset before spawning so the poller can't read a stale status from a prior
    # publish of this short (same fix as the main video upload).
    try:
        with open(status_file, "w") as _sf:
            json.dump({"status": "uploading", "progress": 0,
                       "message": "Starting upload..."}, _sf)
    except OSError:
        pass
    worker_params = json.dumps({
        "status_file": status_file,
        "video_path": video_path,
        "title": title,
        "description": description,
        "tags": tags,
        "privacy": privacy,
        "thumbnail_path": None,  # YT auto-generates for Shorts
        "client_secret": str(PROJECT_ROOT / "client_secret.json"),
        "token_path": str(PROJECT_ROOT / "youtube_token.json"),
    })
    worker_script = str(PROJECT_ROOT / "upload_worker.py")
    worker_log = str(PROJECT_ROOT / "output" / f"{short_id}_upload_worker.log")
    log_fh = open(worker_log, "w")
    subprocess.Popen(
        [sys.executable, "-u", worker_script, worker_params],
        start_new_session=True,
        stdout=log_fh, stderr=log_fh,
    )

    with jobs_lock:
        s["upload_status"] = "uploading"
        s["yt_title"] = title
        s["yt_description"] = description
        s["yt_tags"] = tags
    _save_job(job["job_id"])

    return jsonify({"status": "uploading", "short_id": short_id})


@app.route("/api/distribute/shorts/<short_id>/upload-status")
def api_short_upload_status(short_id: str):
    job, s = _find_short(short_id)
    if not s:
        return jsonify({"error": "Short not found"}), 404

    status_file = PROJECT_ROOT / "output" / f"{short_id}_upload_status.json"
    if status_file.exists():
        try:
            data = json.loads(status_file.read_text())
        except (json.JSONDecodeError, OSError):
            data = {}

        if data.get("status") == "done" and data.get("youtube_url"):
            with jobs_lock:
                s["youtube_url"] = data["youtube_url"]
                s["youtube_video_id"] = data.get("video_id", "")
                s["upload_status"] = "done"
            _save_job(job["job_id"])
        elif data.get("status") == "error":
            with jobs_lock:
                s["upload_status"] = "error"

        return jsonify({
            "status": data.get("status", "uploading"),
            "progress": data.get("progress", 0),
            "message": data.get("message", ""),
            "youtube_url": data.get("youtube_url"),
            "video_id": data.get("video_id") or s.get("youtube_video_id", ""),
            "parent_youtube_url": job.get("youtube_url"),
        })

    return jsonify({
        "status": s.get("upload_status", "idle"),
        "progress": 100 if s.get("youtube_url") else 0,
        "youtube_url": s.get("youtube_url"),
        "video_id": s.get("youtube_video_id", ""),
        "parent_youtube_url": job.get("youtube_url"),
    })


# ── SEO metadata v2 ────────────────────────────────────────────────


@app.route("/api/distribute/seo-v2/<job_id>", methods=["POST"])
def api_seo_v2(job_id: str):
    """Extended SEO metadata: 3 title variants + thumbnail prompt + optional
    comparable-channel exemplars.

    Body:
      {
        "comparable_channels": ["@TaosWinds", "@MyNoise"]   (optional, free text)
      }
    """
    job = _job_must_exist(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not configured"}), 500

    data = request.get_json(force=True, silent=True) or {}
    comparable_channels = [c.strip() for c in data.get("comparable_channels", []) if c and c.strip()]

    config = job.get("config")
    title = config.title if config else ""
    mood = config.mood if config else ""
    setting = config.setting if config else ""
    layers_desc = ", ".join(f"{l.name} ({l.layer_type.value})" for l in (config.layers if config else []))

    video_duration_sec = 0
    if job.get("visual_video_path") and os.path.exists(job["visual_video_path"]):
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "csv=p=0", job["visual_video_path"]],
                capture_output=True, text=True, timeout=10,
            )
            video_duration_sec = int(float(probe.stdout.strip()))
        except Exception:
            pass
    if video_duration_sec == 0:
        video_duration_sec = 3600  # default to 1 hour — Cole publishes 1-hour videos
    _h = video_duration_sec // 3600
    duration_str = (
        ("1 Hour" if _h == 1 else f"{_h} Hours") if _h >= 1
        else f"{video_duration_sec // 60} Minutes"
    )

    comparables_block = ""
    if comparable_channels:
        comparables_block = (
            "\nComparable channels to draw stylistic inspiration from "
            "(match their voice/cadence but don't copy):\n"
            + "\n".join(f"  - {c}" for c in comparable_channels)
        )

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1400,
        messages=[{
            "role": "user",
            "content": f"""Write YouTube metadata for an ambient / cinematic music video (v2: 3 title options + a thumbnail prompt), modeled on what performs for ambient, sci-fi, and study/focus channels. The DESCRIPTION is a short immersive story (no marketing copy); the TAGS carry the SEO.

SOURCE BRIEF: {job.get('prompt', '')}
Internal title: {title} | Mood: {mood} | Setting: {setting} | Duration: {duration_str}
Layers: {layers_desc}{comparables_block}

STEP 1 — Identify the SUBJECT HOOK: the single most recognizable thing this evokes (a book/film/universe, a real place, or a vivid concept — e.g. "Project Hail Mary", "Dune", "a cabin in a snowstorm"). Every title variant must lead with it verbatim.

TITLE VARIANTS (3, each SHORT — aim <70 chars, hard max 90; no emoji, no clickbait):
- Pattern: "<Subject Hook> — <Short Evocative Descriptor> | {duration_str} <Genre>"
- Give 3 genuinely different angles (e.g. emotional, place-focused, use-case-focused), all leading with the subject hook and all using the duration "{duration_str}".

DESCRIPTION — JUST THE STORY (human, not AI; specific and grounded, no purple filler):
- Open DIRECTLY with the story. NO opening hook/tagline, NO "About"/"Best for" sections, NO subscribe/comment CTA.
- 2-3 short paragraphs of immersive, atmospheric story set in the scene — sensory but restrained, like a person wrote it.
- This is one continuous seamless loop — do NOT invent timestamps or chapter markers.
- End with EXACTLY 3 relevant hashtags on their own line (subject hook + two genre/use-case tags). This is the only non-story element.

TAGS (15-25) — where ALL the SEO lives: blend (a) SPECIFIC — subject hook + closely related terms; (b) GENRE — space ambient, sci-fi ambient, cinematic ambient, etc.; (c) MOOD; (d) high-intent USE-CASE long-tails — study music, sleep music, focus music, reading music, 1 hour ambient. Favor long-tail phrases over single broad words.

Return STRICT JSON in this shape:
{{
  "title_variants": ["variant 1", "variant 2", "variant 3"],
  "description": "the story + 3 hashtags",
  "tags": ["15-25 keyword tags"],
  "thumbnail_prompt": "A single dense visual prompt for a text-to-image model. 16:9, 1280x720, click-stopping ambient cinema aesthetic. Describe scene, lighting, color palette, mood, camera framing. No text in the image."
}}

Output ONLY the JSON, nothing else."""
        }],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]

    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        return jsonify({"error": "Failed to parse SEO v2", "raw": raw}), 500

    with jobs_lock:
        jobs[job_id]["seo_v2"] = out
        if out.get("title_variants"):
            jobs[job_id]["yt_title"] = out["title_variants"][0]
        if out.get("description"):
            jobs[job_id]["yt_description"] = out["description"]
        if isinstance(out.get("tags"), list):
            jobs[job_id]["yt_tags"] = ", ".join(out["tags"])
    _save_job(job_id)

    return jsonify(out)


# ── Ads brief ──────────────────────────────────────────────────────


@app.route("/api/distribute/ads/brief/<job_id>", methods=["POST"])
def api_ads_brief(job_id: str):
    """Generate a paste-ready Google Ads campaign brief in Markdown.

    Body:
      {
        "comparable_channels": ["@Handle", ...],
        "budget_range": "5-20" | "20-50" | "50-150"  (USD/day, optional)
      }
    """
    job = _job_must_exist(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not configured"}), 500

    data = request.get_json(force=True, silent=True) or {}
    comparables = [c.strip() for c in data.get("comparable_channels", []) if c and c.strip()]
    budget = data.get("budget_range", "5-20")

    config = job.get("config")
    title = (config.title if config else job.get("prompt", "")[:60])
    mood = config.mood if config else ""
    setting = config.setting if config else ""

    comparables_block = (
        "\nComparable creators / placements supplied by the user:\n" +
        "\n".join(f"  - {c}" for c in comparables)
        if comparables else
        "\n(No comparable creators supplied — invent 6-10 plausible channels based on the vibe.)"
    )

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1800,
        messages=[{
            "role": "user",
            "content": f"""Write a YouTube Ads campaign brief I can paste straight into Google Ads.
This is for an ambient soundscape video on my channel.

Track: {title}
Mood: {mood}
Setting: {setting}
User prompt: {job.get('prompt', '')}
YouTube URL: {job.get('youtube_url') or '(not uploaded yet — leave a {{video_url}} placeholder)'}
Daily budget range (USD): {budget}{comparables_block}

Output FORMAT: pure Markdown, no preamble, no code fences. Use this exact structure:

# Ad Campaign — <name>

## Objective
<conversions / views / brand awareness, with reasoning>

## Target audience
- Demographics: <age, gender if relevant>
- Interests / affinities: <bulleted list>
- In-market segments: <bulleted list>
- Custom segment (URLs/keywords): <bulleted list, one keyword or URL per bullet>

## Placement targeting (channel handles)
- <list of 8-15 YouTube channels with @handle URLs to bid on>

## Ad creative
### Headline variants (use 2-3 in rotation)
1. <headline>
2. <headline>
3. <headline>

### Description variants
1. <description, <=70 chars>
2. <description, <=70 chars>

### Companion banner copy
<one-liner>

## Bid strategy
- Bid: <recommended CPV range>
- Daily budget: ${budget} USD
- Frequency cap: <recommended>

## Notes
<one or two strategic notes about why this targeting matches the vibe>"""
        }],
    )

    md = msg.content[0].text.strip()
    with jobs_lock:
        jobs[job_id]["ads_brief_md"] = md
        jobs[job_id]["last_promoted_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _save_job(job_id)

    return jsonify({"brief_md": md})


@app.route("/api/distribute/ads/brief/<job_id>")
def api_ads_brief_get(job_id: str):
    job = _job_must_exist(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({"brief_md": job.get("ads_brief_md")})


# ── Community / Reddit / Discord drafts ────────────────────────────


_COMMUNITY_STYLES = {
    "poll": (
        "Generate a YouTube Community-tab poll post. Format: a 1-2 sentence "
        "lead-in question, then exactly 4 short poll options (one per line, "
        "prefixed with '- '). Topic: 'which world should I soundscape next?'. "
        "Avoid duplicating the user's existing channel themes."
    ),
    "teaser": (
        "Generate a behind-the-scenes YouTube Community-tab teaser post for "
        "this track. 3-5 sentences, evocative voice, ends with a question to "
        "drive comments. Mention the track is up now."
    ),
    "world_request": (
        "Generate an open-ended YouTube Community-tab ask: 'what world / book / "
        "movie should I soundscape next?'. 2-4 sentences, conversational, fun."
    ),
}


@app.route("/api/distribute/community/draft/<job_id>", methods=["POST"])
def api_community_draft(job_id: str):
    job = _job_must_exist(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    style = (request.args.get("style") or "teaser").lower()
    if style not in _COMMUNITY_STYLES:
        return jsonify({"error": f"Unknown style '{style}'"}), 400

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not configured"}), 500

    # For poll style we also feed the catalog so Claude knows what worlds have
    # already been done.
    catalog_titles = []
    if style == "poll":
        with jobs_lock:
            for j in jobs.values():
                if j.get("config"):
                    catalog_titles.append(j["config"].title)
        catalog_titles = list(dict.fromkeys(catalog_titles))[:25]

    config = job.get("config")
    instructions = _COMMUNITY_STYLES[style]

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        messages=[{
            "role": "user",
            "content": f"""{instructions}

Track context:
  Title: {config.title if config else job.get('prompt', '')[:60]}
  Mood: {config.mood if config else ''}
  Setting: {config.setting if config else ''}
  YouTube URL: {job.get('youtube_url') or '(not uploaded yet)'}
  Already-done worlds on this channel: {', '.join(catalog_titles) if catalog_titles else '(unknown)'}

Output the post body ONLY, no preamble, no JSON, no explanations. Plain text."""
        }],
    )
    body = msg.content[0].text.strip()

    with jobs_lock:
        if "community_drafts" not in jobs[job_id] or not jobs[job_id]["community_drafts"]:
            jobs[job_id]["community_drafts"] = {}
        jobs[job_id]["community_drafts"][style] = {
            "body": body,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
    _save_job(job_id)

    return jsonify({
        "style": style,
        "body": body,
        "studio_url": "https://studio.youtube.com/channel/UC/community",
    })


@app.route("/api/distribute/reddit/draft/<job_id>", methods=["POST"])
def api_reddit_draft(job_id: str):
    """Generate a Reddit post draft tailored to a specific subreddit.

    Body: { "subreddit": "ambientmusic", "context_hint": "..." }
    Returns: { "title", "body", "submit_url" } — user pastes via the link.
    """
    job = _job_must_exist(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    data = request.get_json(force=True, silent=True) or {}
    subreddit = (data.get("subreddit") or "ambientmusic").removeprefix("r/").removeprefix("/")
    context_hint = data.get("context_hint", "")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not configured"}), 500

    config = job.get("config")
    yt_url = job.get("youtube_url") or "(upload pending)"

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=900,
        messages=[{
            "role": "user",
            "content": f"""Write a Reddit post for r/{subreddit} sharing this ambient soundscape.

Important rules:
  - Match r/{subreddit}'s culture. Read the room. For example r/dune is fandom-heavy and lore-aware,
    r/ambientmusic is gear/process-aware, r/space is awe-driven.
  - The OP should feel genuine, not promotional. Lead with a story or hook, not "check out my video".
  - Include the YouTube link inline, naturally.
  - Title <=120 chars, body 4-12 sentences.
  - {context_hint}

Track:
  Title: {config.title if config else job.get('prompt', '')[:60]}
  Mood: {config.mood if config else ''}
  Setting: {config.setting if config else ''}
  Description: {job.get('prompt', '')}
  YouTube link: {yt_url}

Reply ONLY with strict JSON:
{{"title": "...", "body": "..."}}"""
        }],
    )

    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        return jsonify({"error": "Failed to parse reddit draft", "raw": raw}), 500

    from urllib.parse import quote_plus
    submit_url = (
        f"https://www.reddit.com/r/{subreddit}/submit?"
        f"title={quote_plus(out.get('title', ''))}&"
        f"text={quote_plus(out.get('body', ''))}&kind=self"
    )

    with jobs_lock:
        if "reddit_drafts" not in jobs[job_id] or not jobs[job_id]["reddit_drafts"]:
            jobs[job_id]["reddit_drafts"] = {}
        jobs[job_id]["reddit_drafts"][subreddit] = {
            "title": out.get("title", ""),
            "body": out.get("body", ""),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
    _save_job(job_id)

    return jsonify({
        "subreddit": subreddit,
        "title": out.get("title", ""),
        "body": out.get("body", ""),
        "submit_url": submit_url,
    })


@app.route("/api/distribute/discord/post/<job_id>", methods=["POST"])
def api_discord_post(job_id: str):
    """Generate AND publish a Discord post via a stored webhook.

    Body: { "webhook_name": "main", "context_hint": "..." }
    The webhook URL must be saved first via /api/distribute/secrets.
    """
    job = _job_must_exist(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    data = request.get_json(force=True, silent=True) or {}
    webhook_name = data.get("webhook_name", "main")
    context_hint = data.get("context_hint", "")

    secrets = distribute_stream.read_secrets(JOBS_DIR)
    webhooks = secrets.get("discord_webhooks", {})
    webhook_url = webhooks.get(webhook_name)
    if not webhook_url:
        return jsonify({"error": f"No Discord webhook named '{webhook_name}'. Add it in Distribute → Secrets."}), 400

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not configured"}), 500

    config = job.get("config")
    yt_url = job.get("youtube_url") or ""

    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        messages=[{
            "role": "user",
            "content": f"""Write a Discord announcement message for a new ambient soundscape track.
2-4 short paragraphs, casual server voice, ends with the YouTube link if available.
Use line breaks; Discord renders standard Markdown.

Track:
  Title: {config.title if config else ''}
  Mood: {config.mood if config else ''}
  Setting: {config.setting if config else ''}
  Description: {job.get('prompt', '')}
  YouTube: {yt_url or '(uploading soon)'}
  Extra: {context_hint}

Output just the message text, no preamble."""
        }],
    )
    body = msg.content[0].text.strip()

    # Post to Discord webhook. Discord caps content at 2000 chars.
    payload = {"content": body[:1990]}
    try:
        import urllib.request
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            ok = 200 <= resp.status < 300
    except Exception as e:
        return jsonify({"error": f"Discord post failed: {e}", "body": body}), 502

    if not ok:
        return jsonify({"error": "Discord rejected the post", "body": body}), 502

    return jsonify({
        "posted": True,
        "webhook_name": webhook_name,
        "body": body,
    })


# ── Secrets storage ────────────────────────────────────────────────


@app.route("/api/distribute/secrets")
def api_secrets_get():
    """Return non-sensitive view of secrets (booleans + names only)."""
    s = distribute_stream.read_secrets(JOBS_DIR)
    webhooks = s.get("discord_webhooks", {}) or {}
    return jsonify({
        "discord_webhook_names": sorted(webhooks.keys()),
        "youtube_stream_url": s.get("youtube_stream_url", ""),
        "has_stream_key": bool(s.get("youtube_stream_key")),
    })


@app.route("/api/distribute/secrets", methods=["POST"])
def api_secrets_set():
    """Update secrets. Body:
      { "discord_webhooks": {"main": "https://...", ...},
        "youtube_stream_url": "rtmp://a.rtmp.youtube.com/live2",
        "youtube_stream_key": "xxxx-xxxx-xxxx" }
    Any omitted key is left unchanged. Pass empty string to clear.
    """
    data = request.get_json(force=True, silent=True) or {}
    current = distribute_stream.read_secrets(JOBS_DIR)

    if "discord_webhooks" in data and isinstance(data["discord_webhooks"], dict):
        # Merge — empty string means delete the entry.
        existing = current.get("discord_webhooks", {}) or {}
        for name, url in data["discord_webhooks"].items():
            if not name:
                continue
            if not url:
                existing.pop(name, None)
            else:
                existing[name] = url
        current["discord_webhooks"] = existing

    if "youtube_stream_url" in data:
        current["youtube_stream_url"] = (data["youtube_stream_url"] or "").strip()
    if "youtube_stream_key" in data:
        # Empty string clears it.
        if data["youtube_stream_key"] == "":
            current.pop("youtube_stream_key", None)
        else:
            current["youtube_stream_key"] = (data["youtube_stream_key"] or "").strip()

    distribute_stream.write_secrets(JOBS_DIR, current)
    return jsonify({"saved": True})


# ── Live stream ────────────────────────────────────────────────────


@app.route("/api/distribute/stream/status")
def api_stream_status():
    state = distribute_stream.reconcile_state(JOBS_DIR)
    playlist_path = distribute_stream._playlist_path(PROJECT_ROOT / "output")
    playlist_tracks = 0
    if playlist_path.exists():
        try:
            text = playlist_path.read_text()
            playlist_tracks = sum(1 for ln in text.splitlines() if ln.startswith("file "))
        except OSError:
            pass
    return jsonify({
        **state,
        "playlist_tracks": playlist_tracks,
    })


@app.route("/api/distribute/stream/playlist", methods=["POST"])
def api_stream_playlist():
    """Rebuild the concat playlist. Body: { job_ids: [..] | null }.
    If job_ids is null/missing, includes every job with an exported video."""
    data = request.get_json(force=True, silent=True) or {}
    job_ids = data.get("job_ids")
    if job_ids is not None and not isinstance(job_ids, list):
        return jsonify({"error": "job_ids must be a list or null"}), 400
    with jobs_lock:
        snapshot = dict(jobs)
    count = distribute_stream.build_playlist(JOBS_DIR, PROJECT_ROOT / "output", snapshot, job_ids)
    return jsonify({"tracks": count})


@app.route("/api/distribute/stream/start", methods=["POST"])
def api_stream_start():
    secrets = distribute_stream.read_secrets(JOBS_DIR)
    rtmp_url = secrets.get("youtube_stream_url") or "rtmp://a.rtmp.youtube.com/live2"
    stream_key = secrets.get("youtube_stream_key")
    if not stream_key:
        return jsonify({
            "error": "No YouTube stream key saved yet. Open “Stream settings” below, "
                     "paste your YouTube Live stream key, and click Save stream settings.",
            "needs_stream_key": True,
        }), 400

    log_path = str(PROJECT_ROOT / "output" / "_distribute_stream.log")
    try:
        state = distribute_stream.start_stream(
            JOBS_DIR, PROJECT_ROOT / "output", rtmp_url, stream_key, log_path,
        )
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(state)


@app.route("/api/distribute/stream/stop", methods=["POST"])
def api_stream_stop():
    state = distribute_stream.stop_stream(JOBS_DIR)
    return jsonify(state)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", "-p", type=int, default=5050)
    parser.add_argument("--host", default="0.0.0.0")
    cli_args = parser.parse_args()
    # Debug (Werkzeug debugger = remote code execution) only when explicitly
    # asked for AND the app is not password-gated for public exposure.
    _debug = os.environ.get("AMBIENTIZER_DEBUG", "0") == "1" and not ACCESS_PASSWORD
    app.run(debug=_debug, use_reloader=False, port=cli_args.port, host=cli_args.host, threaded=True)
