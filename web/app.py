"""
web/app.py — Flask web server for the Ambientizer soundscape generator.

Provides a REST API for generating soundscapes, applying human feedback
for iterative mix refinement, and serving audio files.

Endpoints:
    GET  /                          — Serves the single-page UI
    POST /api/generate              — Start a generation job (returns job_id)
    GET  /api/status/<job_id>       — Poll job progress
    POST /api/feedback/<job_id>     — Apply natural language feedback to refine mix
    POST /api/finalize/<job_id>     — Re-master current mix for download
    GET  /api/audio/<job_id>        — Serve the current audio (raw during feedback)
    GET  /api/audio/<job_id>/download — Download the mastered WAV
    GET  /api/history               — List recent generation jobs
"""

import json
import os
import sys
import time
import uuid
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_file, abort
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import SoundscapeOrchestrator
from audio_engine import AudioEngine, SampleLibrary, detect_key, harmonize_layers
from mix_master import MixMasterAgent
from feedback_adjuster import FeedbackAdjuster
from sample_generator import ElevenLabsSampleGenerator
from schemas import GenerationMode, SoundscapeConfig, LayerConfig, LayerType, EffectsChain

load_dotenv()

app = Flask(__name__)

jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
JOBS_DIR = PROJECT_ROOT / "saved_jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)


def _save_job(job_id: str):
    """Persist a job's state to disk as JSON."""
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
        "audio_path": job.get("audio_path"),
        "output_path": job.get("output_path"),
        "raw_output_path": job.get("raw_output_path"),
        "mastered_path": job.get("mastered_path"),
        "feedback_history": job.get("feedback_history", []),
        "error": job.get("error"),
        "created_at": job.get("created_at"),
        "config": job["config"].to_dict() if job.get("config") else None,
    }

    path = JOBS_DIR / f"{job_id}.json"
    try:
        with open(path, "w") as f:
            json.dump(serializable, f, indent=2, default=str)
    except Exception as e:
        print(f"  Warning: Could not save job {job_id}: {e}")


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


PREVIEW_SECONDS = 30


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
            "elevenlabs_prompt": layer.elevenlabs_prompt or "",
            "loop": layer.loop,
            "independent_loop": layer.independent_loop,
            "has_audio": bool(layer.generated_audio_path),
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
    loopable: bool = True,
):
    """
    Background worker: generates samples + renders a short preview for listening.
    The full-length render only happens when the user clicks Download (finalize).
    """

    def on_status(stage: str, message: str, data: dict):
        with jobs_lock:
            job = jobs[job_id]
            job["stage"] = stage
            job["progress_message"] = message
            job["logs"].append({"time": datetime.now().isoformat(), "message": message})

            if stage == "complete" and "output_path" in data:
                job["output_path"] = data["output_path"]
                job["raw_output_path"] = data.get("raw_output_path")

    try:
        preview_duration = PREVIEW_SECONDS / 60.0
        agent = create_orchestrator(mastering=mastering)
        gen_mode = GenerationMode(mode) if mode in ("ambient", "musical") else GenerationMode.AMBIENT
        result = agent.generate(
            prompt=prompt,
            duration_minutes=preview_duration,
            on_status=on_status,
            mode=gen_mode,
            reference_url=reference_url or None,
            loopable=loopable,
        )

        with jobs_lock:
            jobs[job_id]["status"] = "complete"
            jobs[job_id]["output_path"] = result.output_path
            jobs[job_id]["raw_output_path"] = result.raw_output_path
            jobs[job_id]["config"] = result.final_config
            jobs[job_id]["audio_path"] = result.raw_output_path

        _save_job(job_id)

    except Exception as e:
        with jobs_lock:
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
    return render_template("index.html")


@app.route("/api/generate", methods=["POST"])
def api_generate():
    """Start a new soundscape generation job."""
    data = request.get_json(force=True, silent=True) or {}
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400

    duration = float(data.get("duration", 5.0))
    mastering = data.get("mastering", True)
    mode = data.get("mode", "ambient")
    reference_url = data.get("reference_url", "").strip() or None
    loopable = data.get("loopable", True)

    job_id = str(uuid.uuid4())[:8]
    with jobs_lock:
        jobs[job_id] = {
            "job_id": job_id,
            "prompt": prompt,
            "duration": duration,
            "mastering": mastering,
            "mode": mode,
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
        }

    thread = threading.Thread(
        target=run_generation,
        args=(job_id, prompt, duration, mastering, mode, reference_url, loopable),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id})


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
        "status": job["status"],
        "stage": job["stage"],
        "progress_message": job["progress_message"],
        "logs": job["logs"][-50:],
        "output_path": job["output_path"],
        "raw_output_path": job["raw_output_path"],
        "feedback_history": job["feedback_history"],
        "error": job["error"],
        "created_at": job["created_at"],
        "layers": layers_data,
        "root_key": config.root_key if config else "",
    })


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

            path = generator.generate_layer_audio(
                layer=layer,
                mood=revised_config.mood,
                setting=revised_config.setting,
                use_cache=False,
                root_key=revised_config.root_key,
            )
            if path:
                layer.generated_audio_path = path
                api = "Music API" if layer.layer_type == LayerType.MUSICAL else "SFX API"
                action = "re-rolled" if not new_prompt else f"regenerated via {api}"
                regen_summaries.append(f"{layer_name} ({action})")

    # Re-render a short preview (fast — samples are cached)
    try:
        engine = _get_engine()
        new_audio = engine.render_preview(revised_config, preview_sec=PREVIEW_SECONDS)

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

        layer.generated_audio_path = None
        path = generator.generate_layer_audio(
            layer=layer,
            mood=config.mood,
            setting=config.setting,
            use_cache=False,
            root_key=config.root_key,
        )
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
        path = generator.generate_layer_audio(
            layer=layer,
            mood=config.mood,
            setting=config.setting,
            use_cache=False,
            root_key=config.root_key,
        )
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
        is_base = new_type == LayerType.BASE
        new_layer = LayerConfig(
            name=new_name,
            layer_type=new_type,
            sample_tags=[],
            volume_db=-14.0 if is_base else -16.0,
            pan=0.0,
            loop=is_base or is_musical,
            fade_in_sec=3.0,
            fade_out_sec=3.0,
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

        path = generator.generate_layer_audio(
            layer=new_layer,
            mood=config.mood,
            setting=config.setting,
            use_cache=True,
            root_key=config.root_key,
        )
        if path:
            new_layer.generated_audio_path = path

        config.layers.append(new_layer)
        api = "Music" if is_musical else "SFX"
        change_desc = f"Added {new_name} ({new_type_str}) via {api} API"

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

        change_desc = f"{layer_name}: {', '.join(parts)}" if parts else f"No changes to {layer_name}"

    else:
        return jsonify({"error": f"Unknown action: {action}"}), 400

    # Re-render preview
    try:
        engine = _get_engine()
        new_audio = engine.render_preview(config, preview_sec=PREVIEW_SECONDS)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in config.title)
        audio_filename = f"{safe_title}_action_{timestamp}.wav"
        audio_path = str(PROJECT_ROOT / "output" / audio_filename)
        new_audio.export(audio_path, format="wav")
    except Exception as e:
        return jsonify({"error": f"Re-render failed: {e}"}), 500

    with jobs_lock:
        jobs[job_id]["config"] = config
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
    Previews are 30s; this renders the real thing.
    """
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    config = job.get("config")
    if not config:
        return jsonify({"error": "No config to finalize"}), 400

    # If we already have a mastered full-length version, use it
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
        full_audio = engine.render(full_config)

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

        return jsonify({
            "status": "ready",
            "download_url": f"/api/audio/{job_id}/download",
        })

    except Exception as e:
        return jsonify({"error": f"Finalization failed: {e}"}), 500


def _resolve_audio_path(relative_path: str) -> str | None:
    """Resolve an output path to an absolute path."""
    if not relative_path:
        return None
    p = Path(relative_path)
    if p.is_absolute():
        return str(p) if p.exists() else None
    resolved = PROJECT_ROOT / relative_path
    return str(resolved) if resolved.exists() else None


@app.route("/api/audio/<job_id>")
def api_audio(job_id: str):
    """Serve the current audio file (raw during feedback, mastered initially)."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        abort(404)

    # Prefer feedback-adjusted audio, then mastered, then raw
    path = (
        _resolve_audio_path(job.get("audio_path"))
        or _resolve_audio_path(job.get("output_path"))
        or _resolve_audio_path(job.get("raw_output_path"))
    )
    if not path:
        abort(404)

    return send_file(path, mimetype="audio/wav", as_attachment=False)


@app.route("/api/audio/<job_id>/download")
def api_audio_download(job_id: str):
    """Download the best available audio (mastered if finalized)."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        abort(404)

    path = (
        _resolve_audio_path(job.get("mastered_path"))
        or _resolve_audio_path(job.get("output_path"))
        or _resolve_audio_path(job.get("audio_path"))
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
        new_audio = engine.render_preview(config, preview_sec=PREVIEW_SECONDS)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in config.title)
        audio_filename = f"{safe_title}_harmonized_{timestamp}.wav"
        audio_path = str(PROJECT_ROOT / "output" / audio_filename)
        new_audio.export(audio_path, format="wav")
    except Exception as e:
        return jsonify({"error": f"Re-render failed: {e}"}), 500

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


@app.route("/api/history")
def api_history():
    """Return a list of recent generation jobs."""
    with jobs_lock:
        history = sorted(jobs.values(), key=lambda j: j["created_at"], reverse=True)

    return jsonify([
        {
            "job_id": j["job_id"],
            "prompt": j["prompt"],
            "status": j["status"],
            "duration": j["duration"],
            "feedback_count": len(j.get("feedback_history", [])),
            "created_at": j["created_at"],
        }
        for j in history[:20]
    ])


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", "-p", type=int, default=5050)
    parser.add_argument("--host", default="0.0.0.0")
    cli_args = parser.parse_args()
    app.run(debug=True, port=cli_args.port, host=cli_args.host)
