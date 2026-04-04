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
from pydub import AudioSegment
from schemas import GenerationMode, SoundscapeConfig, LayerConfig, LayerType, EffectsChain, PartSnapshot
from visual_generator import VisualGenerator
from youtube_publisher import YouTubePublisher

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
        "visual_image_path": job.get("visual_image_path"),
        "visual_image_prompt": job.get("visual_image_prompt"),
        "visual_clip_path": job.get("visual_clip_path"),
        "visual_clip_mode": job.get("visual_clip_mode"),
        "visual_video_path": job.get("visual_video_path"),
        "youtube_url": job.get("youtube_url"),
        "youtube_video_id": job.get("youtube_video_id"),
        "yt_title": job.get("yt_title"),
        "yt_description": job.get("yt_description"),
        "yt_tags": job.get("yt_tags"),
        "yt_privacy": job.get("yt_privacy"),
        "parts": [p.to_dict() for p in job.get("parts", [])],
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
                "visual_image_path": data.get("visual_image_path"),
                "visual_image_prompt": data.get("visual_image_prompt"),
                "visual_clip_path": data.get("visual_clip_path"),
                "visual_clip_mode": data.get("visual_clip_mode"),
                "visual_video_path": data.get("visual_video_path"),
                "youtube_url": data.get("youtube_url"),
                "youtube_video_id": data.get("youtube_video_id"),
                "yt_title": data.get("yt_title"),
                "yt_description": data.get("yt_description"),
                "yt_tags": data.get("yt_tags"),
                "yt_privacy": data.get("yt_privacy"),
                "parts": [PartSnapshot.from_dict(p) for p in data.get("parts", [])],
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


PREVIEW_SECONDS = None  # None = render at full requested duration


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
    loopable: bool = True, music_length: float = 0,
):
    """
    Background worker: generates samples via ElevenLabs + renders a short
    preview for quick listening. Full-length render happens on finalize.
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
        agent = create_orchestrator(mastering=mastering)
        gen_mode = GenerationMode(mode) if mode in ("ambient", "musical") else GenerationMode.AMBIENT
        result = agent.generate(
            prompt=prompt,
            duration_minutes=duration,
            on_status=on_status,
            mode=gen_mode,
            reference_url=reference_url or None,
            loopable=loopable,
        )

        if music_length > 0:
            result.final_config.music_length_sec = music_length * 60

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


@app.route("/api/enhance-prompt", methods=["POST"])
def enhance_prompt():
    """
    Research the user's rough idea via web search, then use Claude to craft
    a rich, detailed soundscape prompt from the context.
    """
    data = request.get_json(force=True, silent=True) or {}
    raw_prompt = data.get("prompt", "").strip()
    mode = data.get("mode", "ambient")
    if not raw_prompt:
        return jsonify({"error": "No prompt provided"}), 400

    gemini_key = os.environ.get("GEMINI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not set"}), 500

    # Step 1: Web search via Gemini for context about the reference
    search_context = ""
    if gemini_key:
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=gemini_key)
            search_tool = types.Tool(google_search=types.GoogleSearch())
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=f'What is "{raw_prompt}"? Give a concise summary focusing on the setting, '
                         f"atmosphere, visual aesthetic, emotional tone, and any iconic sounds or "
                         f"music associated with it. If it's a book, movie, game, or place, describe "
                         f"the world and mood in sensory detail. 3-4 paragraphs max.",
                config=types.GenerateContentConfig(tools=[search_tool]),
            )
            search_context = response.text.strip()
        except Exception as e:
            print(f"  Gemini search failed (non-fatal): {e}")

    # Step 2: Claude crafts the enhanced prompt
    import anthropic
    client = anthropic.Anthropic(api_key=anthropic_key)

    context_block = ""
    if search_context:
        context_block = f"\n\nHere is research context about this topic:\n{search_context}"

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=400,
        messages=[{
            "role": "user",
            "content": f"""The user wants to create a {mode} soundscape inspired by this idea:
"{raw_prompt}"{context_block}

Write a vivid, detailed soundscape prompt (2-4 sentences) that captures the essence of this idea.
Be specific about:
- The setting/environment (where are we?)
- The mood and emotional quality
- Specific sounds, textures, or musical qualities to include
- Time of day, weather, or atmosphere if relevant

Write it as a direct description of what the soundscape should sound like, as if describing
a scene the listener will be immersed in. Don't explain what you're doing — just write the prompt.

Output ONLY the enhanced prompt text, nothing else.""",
        }],
    )

    enhanced = message.content[0].text.strip()
    enhanced = enhanced.strip('"')

    return jsonify({
        "enhanced_prompt": enhanced,
        "research_summary": search_context[:300] + "..." if len(search_context) > 300 else search_context,
    })


@app.route("/api/generate", methods=["POST"])
def api_generate():
    """Start a new soundscape generation job."""
    data = request.get_json(force=True, silent=True) or {}
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400

    duration = float(data.get("duration", 5.0))
    music_length = float(data.get("music_length", 0))
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
            "music_length": music_length,
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
        args=(job_id, prompt, duration, mastering, mode, reference_url, loopable, music_length),
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
        "duration": job.get("duration", 5),
        "mode": job.get("mode", "ambient"),
        "reference_url": job.get("reference_url", ""),
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
        "visual_image_url": f"/api/visual/image/{job['job_id']}/view" if job.get("visual_image_path") else None,
        "visual_image_prompt": job.get("visual_image_prompt", ""),
        "visual_clip_url": f"/api/visual/clip/{job['job_id']}/view" if job.get("visual_clip_path") else None,
        "visual_video_url": f"/api/visual/video/{job['job_id']}/download" if job.get("visual_video_path") else None,
        "youtube_url": job.get("youtube_url"),
        "yt_title": job.get("yt_title", ""),
        "yt_description": job.get("yt_description", ""),
        "yt_tags": job.get("yt_tags", ""),
        "yt_privacy": job.get("yt_privacy", "unlisted"),
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
                track_duration_sec=revised_config.duration_sec,
                music_length_sec=revised_config.music_length_sec,
            )
            if path:
                layer.generated_audio_path = path
                api = "Music API" if layer.layer_type == LayerType.MUSICAL else "SFX API"
                action = "re-rolled" if not new_prompt else f"regenerated via {api}"
                regen_summaries.append(f"{layer_name} ({action})")

    # Re-render at full duration (fast — samples are cached)
    try:
        engine = _get_engine()
        new_audio = engine.render(revised_config)

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
        model="claude-sonnet-4-20250514",
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

        layer.generated_audio_path = None
        path = generator.generate_layer_audio(
            layer=layer,
            mood=config.mood,
            setting=config.setting,
            use_cache=False,
            root_key=config.root_key,
            track_duration_sec=config.duration_sec,
            music_length_sec=config.music_length_sec,
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
            track_duration_sec=config.duration_sec,
            music_length_sec=config.music_length_sec,
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
            track_duration_sec=config.duration_sec,
            music_length_sec=config.music_length_sec,
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

        change_desc = f"{layer_name}: {', '.join(parts)}" if parts else f"No changes to {layer_name}"

    else:
        return jsonify({"error": f"Unknown action: {action}"}), 400

    # Re-render at full duration (fast — samples are cached)
    try:
        engine = _get_engine()
        new_audio = engine.render(config)
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

        with open(audio_path, "rb") as f:
            audio_data = f.read()

        config = job.get("config")
        prompt_desc = config.title if config else job.get("prompt", "ambient soundscape")
        mode = job.get("mode", "ambient")

        critique_prompt = f"""You are an expert audio producer reviewing an AI-generated {mode} soundscape.
The intended description: "{prompt_desc}"

Listen to this audio and provide:

1. **Score** (1-10): Overall quality rating where:
   - 1-3: Poor (major issues like silence, noise, dissonance)
   - 4-5: Below average (noticeable issues)
   - 6-7: Good (minor issues, generally pleasant)
   - 8-9: Very good (professional quality, immersive)
   - 10: Exceptional

2. **Notes**: 3-5 specific, actionable observations. Cover:
   - Does it match the intended mood/description?
   - Layer balance and mixing quality
   - Any harsh, unpleasant, or out-of-place sounds
   - Suggestions for improvement

Respond in this exact JSON format:
{{"score": <number 1-10>, "notes": ["note 1", "note 2", "note 3"]}}"""

        response = model.generate_content(
            [critique_prompt, {"mime_type": "audio/wav", "data": audio_data}],
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

        return jsonify({"score": score, "notes": notes})

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
        abort(404)

    config = job.get("config")
    if not config:
        abort(404)

    from urllib.parse import unquote
    layer_name = unquote(layer_name)
    layer = next((l for l in config.layers if l.name == layer_name), None)
    if not layer or not layer.generated_audio_path:
        abort(404)

    path = _resolve_audio_path(layer.generated_audio_path)
    if not path:
        abort(404)

    # Serve a crossfaded version so the mixer's loop point is seamless.
    # Without this, ElevenLabs music (which fades out naturally at the end)
    # causes an audible dip every time the buffer loops.
    loopable_path = path.replace(".wav", "_loop.wav")
    if not os.path.exists(loopable_path):
        try:
            from pydub import AudioSegment as AS
            from audio_engine import make_loopable
            audio = AS.from_wav(path)
            if len(audio) > 10000:  # only crossfade files longer than 10s
                crossfade_ms = min(5000, len(audio) // 4)
                audio = make_loopable(audio, crossfade_ms)
                audio.export(loopable_path, format="wav")
            else:
                loopable_path = path
        except Exception as e:
            print(f"  Crossfade failed for {layer_name}: {e}")
            loopable_path = path

    return send_file(loopable_path, mimetype="audio/wav", as_attachment=False)


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
        new_audio = engine.render(config)
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

    try:
        source = AudioSegment.from_file(audio_path)
        source_ms = len(source)
        target_ms = int(target_minutes * 60 * 1000)

        import math
        repeats = math.ceil(target_ms / source_ms)
        extended = source * repeats
        extended = extended[:target_ms]

        fade_in_ms = int(float(data.get("fade_in_sec", 20)) * 1000)
        if fade_in_ms > 0:
            extended = extended.fade_in(min(fade_in_ms, len(extended) // 4))
        extended = extended.fade_out(5000)

        config = job.get("config")
        title = config.title if config else "Soundscape"
        safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in title)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{safe_title}_{int(target_minutes)}min_{timestamp}.wav"
        output_path = str(PROJECT_ROOT / "output" / filename)
        extended.export(output_path, format="wav")

        with jobs_lock:
            jobs[job_id]["extended_path"] = output_path

        return jsonify({
            "status": "ready",
            "download_url": f"/api/audio/{job_id}/extended",
            "duration_minutes": target_minutes,
        })

    except Exception as e:
        return jsonify({"error": f"Export failed: {e}"}), 500


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


# ────────────────────────────────────────────────────────
#  Visual Generation
# ────────────────────────────────────────────────────────

def _get_visual_generator() -> VisualGenerator | None:
    api_key = os.environ.get("XAI_API_KEY")
    if not api_key:
        return None
    return VisualGenerator(xai_api_key=api_key, output_dir=str(PROJECT_ROOT / "output"))


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
        model="claude-sonnet-4-20250514",
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

    try:
        config = job.get("config")
        safe_title = "ambientizer"
        if config:
            safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in config.title)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = str(PROJECT_ROOT / "output" / f"{safe_title}_visual_{timestamp}.png")

        image_path = gen.generate_image(prompt, output_path=output_path)

        with jobs_lock:
            jobs[job_id]["visual_image_path"] = image_path
            jobs[job_id]["visual_image_prompt"] = prompt

        _save_job(job_id)

        return jsonify({
            "status": "ready",
            "image_url": f"/api/visual/image/{job_id}/view?t={time.time()}",
        })

    except Exception as e:
        return jsonify({"error": f"Image generation failed: {e}"}), 500


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

    gen = _get_visual_generator()
    if not gen:
        return jsonify({"error": "XAI_API_KEY not configured"}), 500

    config = job.get("config")
    safe_title = "ambientizer"
    if config:
        safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in config.title)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        if mode == "ai":
            if not motion_prompt:
                motion_prompt = "Slow, subtle ambient motion. Gentle atmospheric movement, drifting light, peaceful and dreamy. Cinematic, minimal camera movement."

            clip_path = str(PROJECT_ROOT / "output" / f"{safe_title}_aiclip_{timestamp}.mp4")
            gen.animate_image(image_path, motion_prompt, duration=10, output_path=clip_path)
        else:
            clip_path = str(PROJECT_ROOT / "output" / f"{safe_title}_kb_{timestamp}.mp4")
            gen.create_ken_burns_video(image_path, duration_sec=30, output_path=clip_path)

        with jobs_lock:
            jobs[job_id]["visual_clip_path"] = clip_path
            jobs[job_id]["visual_clip_mode"] = mode

        _save_job(job_id)

        return jsonify({
            "status": "ready",
            "clip_url": f"/api/visual/clip/{job_id}/view?t={time.time()}",
            "mode": mode,
        })

    except Exception as e:
        return jsonify({"error": f"Clip generation failed: {e}"}), 500


@app.route("/api/visual/clip/<job_id>/view")
def view_visual_clip(job_id: str):
    """Serve the short preview clip for inline playback."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        abort(404)
    path = job.get("visual_clip_path")
    if not path or not os.path.exists(path):
        abort(404)
    return send_file(path, mimetype="video/mp4")


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

    audio_path = (
        _resolve_audio_path(job.get("mastered_path"))
        or _resolve_audio_path(job.get("audio_path"))
        or _resolve_audio_path(job.get("output_path"))
        or _resolve_audio_path(job.get("raw_output_path"))
    )
    if not audio_path:
        return jsonify({"error": "No audio available"}), 400

    data = request.get_json(force=True, silent=True) or {}
    target_minutes = float(data.get("duration_minutes", 0))

    gen = _get_visual_generator()
    if not gen:
        return jsonify({"error": "XAI_API_KEY not configured"}), 500

    try:
        source_audio = AudioSegment.from_file(audio_path)
        audio_duration_sec = len(source_audio) / 1000.0

        target_sec = target_minutes * 60 if target_minutes > 0 else audio_duration_sec
        if target_sec > audio_duration_sec + 5:
            import math
            crossfade_ms = 3000
            repeats = math.ceil(target_sec / audio_duration_sec)
            extended = source_audio
            for _ in range(repeats - 1):
                extended = extended.append(source_audio, crossfade=crossfade_ms)
            extended = extended[:int(target_sec * 1000)]
            extended = extended.fade_in(20000)
            extended = extended.fade_out(5000)
            ext_path = audio_path.replace(".wav", f"_{int(target_minutes)}min_video.wav")
            extended.export(ext_path, format="wav")
            audio_path = ext_path
            audio_duration_sec = target_sec

        config = job.get("config")
        safe_title = "ambientizer"
        if config:
            safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in config.title)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        looped_path = str(PROJECT_ROOT / "output" / f"{safe_title}_looped_{timestamp}.mp4")
        gen.loop_video(clip_path, audio_duration_sec, output_path=looped_path)

        final_path = str(PROJECT_ROOT / "output" / f"{safe_title}_final_{timestamp}.mp4")
        gen.combine_audio_video(looped_path, audio_path, output_path=final_path)

        with jobs_lock:
            jobs[job_id]["visual_video_path"] = final_path

        _save_job(job_id)

        return jsonify({
            "status": "ready",
            "download_url": f"/api/visual/video/{job_id}/download",
            "duration_minutes": target_minutes if target_minutes > 0 else audio_duration_sec / 60,
        })

    except Exception as e:
        return jsonify({"error": f"Video export failed: {e}"}), 500


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
        channel = None
        try:
            channel = _yt_publisher.get_channel_info()
        except Exception:
            pass

        return jsonify({
            "connected": True,
            "has_client_secret": True,
            "channel": channel or {"name": "YouTube Account", "thumbnail": "", "subscribers": 0},
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
        video_duration_sec = config.duration_sec if config else 300

    if video_duration_sec >= 3600:
        duration_str = f"{video_duration_sec // 3600} hour(s)"
    else:
        duration_str = f"{video_duration_sec // 60} minutes"

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

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        messages=[{
            "role": "user",
            "content": f"""Create YouTube metadata for an ambient soundscape video.

Soundscape: {soundscape_prompt}
Title: {title}
Mood: {mood}
Setting: {setting}
Duration: {duration_str}
Layers: {layers_desc}{timestamps_hint}

Generate:
1. A YouTube title (catchy, searchable, includes mood/vibe, under 80 chars). Think like popular ambient YouTube channels — evocative, slightly poetic, includes the setting.
2. A YouTube description that includes:
   - An immersive 2-3 paragraph story/narrative set in the scene of this soundscape. Write it like you're placing the listener inside the moment — sensory details, atmosphere, emotion. Make it beautiful and evocative.
   - A short "About this track" section explaining what it is
   - {"Use the EXACT timestamps provided above in the description." if timestamps_hint else "Timestamps (if duration > 5min, suggest a few atmospheric moments)"}
   - Relevant hashtags (5-8)
3. Tags for YouTube search optimization (15-25 tags)

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

    data = request.get_json(force=True, silent=True) or {}
    title = data.get("title", "").strip()
    description = data.get("description", "").strip()
    tags = data.get("tags", [])
    privacy = data.get("privacy", "unlisted")

    if not title:
        return jsonify({"error": "Title is required"}), 400

    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

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

    def do_upload():
        def on_progress(pct, msg):
            with jobs_lock:
                jobs[job_id]["upload_progress"] = pct
                jobs[job_id]["upload_message"] = msg

        try:
            result = _yt_publisher.upload_video(
                video_path=video_path,
                title=title,
                description=description,
                tags=tags,
                privacy=privacy,
                thumbnail_path=thumbnail_path,
                on_progress=on_progress,
            )
            with jobs_lock:
                jobs[job_id]["youtube_url"] = result["url"]
                jobs[job_id]["youtube_video_id"] = result["video_id"]
                jobs[job_id]["upload_status"] = "done"
                jobs[job_id]["upload_progress"] = 100
                jobs[job_id]["upload_message"] = result["url"]
            _save_job(job_id)
        except Exception as e:
            with jobs_lock:
                jobs[job_id]["upload_status"] = "error"
                jobs[job_id]["upload_message"] = str(e)

    threading.Thread(target=do_upload, daemon=True).start()
    return jsonify({"status": "uploading"})


@app.route("/api/youtube/upload-status/<job_id>")
def youtube_upload_status(job_id: str):
    """Poll upload progress."""
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "status": job.get("upload_status", "idle"),
        "progress": job.get("upload_progress", 0),
        "message": job.get("upload_message", ""),
        "youtube_url": job.get("youtube_url"),
    })


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", "-p", type=int, default=5050)
    parser.add_argument("--host", default="0.0.0.0")
    cli_args = parser.parse_args()
    app.run(debug=True, port=cli_args.port, host=cli_args.host)
