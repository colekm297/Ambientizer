"""Gemini motion critic — the automated visual judge for the Living Still engine.

Gemini *watches* a rendered loop (native video understanding) and returns a
structured verdict: is the loop seamless, is the motion natural, are there
artifacts, does it suit the scene, is it good enough to publish? This is the
feedback signal that lets the engine be hardened autonomously: render → judge →
rewrite motion_compositor.py → re-render → repeat until it locks in.

Reuses the project's existing Gemini setup (genai client + types.Part.from_bytes,
same as audio_critic.py / reference_analyzer.py).

CLI:  python motion_critic.py <loop.mp4> [source_image.png]   # judge an existing render
      python motion_critic.py --render <image.png>            # render + judge in one shot
Prints a JSON verdict to stdout.
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Optional

from google import genai
from google.genai import types

try:
    from gemini_limiter import gemini_limiter
except Exception:
    gemini_limiter = None

FALLBACK_MODELS = ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-3.5-flash"]

RUBRIC = """You are a strict QA judge for AMBIENT "living still" loops — a single
photo brought subtly to life (drifting clouds, shimmering water, twinkling lights,
gentle parallax) and tiled to play for an hour on YouTube. The motion must be
SEAMLESS (the last frame flows into the first with no visible jump/reset),
NATURAL (gentle, smooth — not shaky, not warping/melting), CLEAN (no tearing,
ghosting, smearing, or a hard colour seam sweeping across), and APPROPRIATE
(clouds drift, water shimmers — not fog on a spaceship; motion present, not dead-still).

Watch the whole clip, paying attention to the loop point and to any region that
moves. Then return ONLY a JSON object, no prose, with this exact shape:

{
  "good_enough": true|false,          // would you publish this as-is?
  "overall_score": 0-10,              // 10 = flawless, publishable
  "loop_seamless": true|false,
  "motion_natural": true|false,
  "artifact_free": true|false,
  "motion_appropriate": true|false,
  "issues": [
    {"severity": "blocker|major|minor", "what": "...", "where": "e.g. left edge / sky / the loop point"}
  ],
  "suggestions": ["concrete, engine-level fix, e.g. 'reduce warp amplitude near edges', 'the loop point shows a jump — the wrap blend is off'"],
  "summary": "one sentence"
}

Be specific and actionable in issues/suggestions — your output drives code changes
to the motion engine. If the clip is essentially static, say so (motion_appropriate=false)."""


def _client() -> genai.Client:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        # the app loads .env; mirror that for standalone CLI use
        try:
            from dotenv import load_dotenv
            load_dotenv()
            key = os.environ.get("GEMINI_API_KEY")
        except Exception:
            pass
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set (check .env)")
    return genai.Client(api_key=key)


def critique_loop(video_path: str, source_image: Optional[str] = None) -> dict:
    """Send a rendered loop mp4 to Gemini and return the structured verdict dict."""
    client = _client()
    with open(video_path, "rb") as f:
        video_bytes = f.read()
    parts = [types.Part.from_bytes(data=video_bytes, mime_type="video/mp4")]
    if source_image:
        with open(source_image, "rb") as f:
            parts.append(types.Part.from_bytes(data=f.read(), mime_type="image/png"))
        parts.append(types.Part(text="(The second image is the ORIGINAL still — judge whether the motion respects and suits it.)"))
    parts.append(types.Part(text=RUBRIC))

    last_error = None
    for model in FALLBACK_MODELS:
        for attempt in range(1, 4):
            if gemini_limiter and not gemini_limiter.wait_if_needed(timeout=90):
                raise RuntimeError("Gemini rate limit reached.")
            try:
                if gemini_limiter:
                    gemini_limiter.record_call(f"motion_critic:{model}")
                resp = client.models.generate_content(model=model, contents=parts)
                text = (resp.text or "").strip()
                # tolerate ```json fences
                if text.startswith("```"):
                    text = text.split("```", 2)[1].lstrip("json").strip("` \n")
                return json.loads(text)
            except json.JSONDecodeError as e:
                last_error = f"non-JSON from {model}: {text[:200]}"
            except Exception as e:
                err = str(e)
                last_error = f"{type(e).__name__}: {err[:150]}"
                if ("429" in err or "RESOURCE_EXHAUSTED" in err) and gemini_limiter and attempt < 3:
                    time.sleep(gemini_limiter.handle_429(attempt)); continue
                break  # try next model
    raise RuntimeError(f"Gemini motion critique failed: {last_error}")


def render_and_critique(image_path: str, loop_sec: float = 8.0,
                        size: tuple[int, int] = (1280, 720)) -> dict:
    """Auto-plan motion for an image, render a loop, and judge it. Returns
    {"video": path, "verdict": {...}, "layers": [...]}."""
    import motion_compositor as mc
    out = os.path.splitext(image_path)[0] + "_qcloop.mp4"
    layers = None
    try:
        # choose_layers_from_image returns (layers, source_label)
        result = mc.choose_layers_from_image(
            image_path, "", os.environ.get("ANTHROPIC_API_KEY"))
        layers = result[0] if isinstance(result, tuple) else result
        if not (isinstance(layers, list) and all(isinstance(l, dict) for l in layers)):
            layers = None
    except Exception:
        layers = None  # render() falls back to its own default/auto plan
    comp = mc.MotionCompositor()
    video = comp.render(image_path, output_path=out, layers=layers,
                        loop_sec=loop_sec, size=size)
    verdict = critique_loop(video, source_image=image_path)
    return {"video": video, "verdict": verdict, "layers": layers}


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--render":
        result = render_and_critique(args[1])
        print(json.dumps(result["verdict"], indent=2))
        print(f"\n[rendered: {result['video']}]", file=sys.stderr)
    else:
        video = args[0]
        src = args[1] if len(args) > 1 else None
        print(json.dumps(critique_loop(video, src), indent=2))
