"""
reference_analyzer.py — Analyzes YouTube ambient/soundscape videos via Gemini.

Uses Gemini's native YouTube URL processing to extract what makes a reference
track work for background listening. The analysis feeds into the theme interpreter
and audio critic to ground generation in proven real-world examples.

No downloading needed — Gemini receives the YouTube URL directly.
"""

import json
import os
import time
from typing import Optional
from gemini_limiter import gemini_limiter


REFERENCE_ANALYSIS_PROMPT = """Listen carefully to the AUDIO in this YouTube video segment (ignore visuals). \
Your job is to understand what the music/soundscape is actually doing, not to invent extra layers.

IMPORTANT:
- Do NOT force a minimum number of layers. If you only clearly hear 2-4 elements, return 2-4.
- Distinguish "actually audible" from "maybe present". Use confidence.
- Focus on musical identity, arrangement over time, mix character, and what should NOT be added.
- This is for recreating an ambient/soundscape reference with an AI music generator.
- For long clips (5+ minutes), provide timeline entries every 1-2 minutes — ambient tracks evolve slowly and a 30-second snapshot misses the arc.

Return a JSON object:

{
    "overall_feel": "What does it feel like to listen to this? Describe the sonic character.",

    "track_identity": {
        "primary_style": "ambient orchestral drone / sparse piano / etc",
        "energy_level": "very low / low / medium / high",
        "movement": "static drone / slow evolution / gradual build / waves",
        "songlike_score": "0-10 where 0 is pure soundscape and 10 is conventional song"
    },

    "timeline": [
        {
            "time": "0:00-0:30",
            "what_changes": "what enters, exits, swells, thins, or stays constant"
        }
    ],

    "layers": [
        {
            "sound": "what this element is",
            "role": "what it contributes to the mix",
            "volume": "loudness relative to the mix",
            "character": "tonal quality",
            "confidence": "high|medium|low"
        }
    ],

    "mix_qualities": {
        "volume": "overall loudness feel",
        "frequency_balance": "how lows/mids/highs are balanced",
        "spaciousness": "how reverberant or wide the mix is",
        "dynamics": "how much the volume varies"
    },

    "do_not_include": [
        "sounds, genres, instruments, or structures that would make the recreation wrong"
    ],

    "direct_elevenlabs_prompt": "A single complete prompt for ElevenLabs Music that recreates the whole reference as an instrumental ambient soundscape. Name only sounds you actually hear. Include spatial/mix qualities and a gentle internal arc across the clip (subtle entries, density shifts, return toward opening texture for loop). Avoid copyrighted names. Under 900 characters.",

    "recreate_with": [
        {
            "layer_name": "descriptive name",
            "layer_type": "musical OR sfx",
            "elevenlabs_prompt": "Vivid description of this sound for an AI audio \
generator. Under 400 characters. Describe what you actually hear."
        }
    ]
}

For each clearly audible layer, mark it as "musical" (tonal/harmonic/melodic) or "sfx" \
(environmental/textural). recreate_with should have one entry per clearly audible layer. \
If a sound is uncertain, include it with confidence "low" or omit it.

Return ONLY valid JSON, no markdown fences."""


class ReferenceAnalyzer:
    """
    Analyzes YouTube ambient/soundscape videos to extract what makes them work.
    Uses Gemini's native YouTube URL processing — no download needed.
    """

    # Prefer stable 3.5 Flash; fall back through preview/pro tiers if unavailable.
    FALLBACK_MODELS = [
        "gemini-3.5-flash",
        "gemini-3-flash-preview",
        "gemini-2.5-pro",
        "gemini-2.5-flash",
    ]

    def __init__(self, gemini_api_key: str):
        from google import genai
        self.client = genai.Client(api_key=gemini_api_key)
        self.last_model_used = None

    @property
    def max_analysis_sec(self) -> int:
        """Max clip length sent to Gemini (default 10 min; override via env)."""
        return int(os.environ.get("GEMINI_MAX_ANALYSIS_SEC", "600"))

    @staticmethod
    def _parse_youtube_timestamp(value: str) -> int:
        """Parse YouTube timestamps like 865s, 14m25s, 1h2m3s, or 14:25."""
        import re

        value = (value or "").strip().lower()
        if not value:
            return 0
        if value.isdigit():
            return int(value)
        if ":" in value:
            parts = [int(p) for p in value.split(":") if p.isdigit()]
            total = 0
            for p in parts:
                total = total * 60 + p
            return total

        total = 0
        for amount, unit in re.findall(r"(\d+)(h|m|s)", value):
            n = int(amount)
            if unit == "h":
                total += n * 3600
            elif unit == "m":
                total += n * 60
            else:
                total += n
        return total

    def _normalize_youtube_reference(
        self,
        youtube_url: str,
        start_sec: int,
        end_sec: int,
    ) -> tuple[str, int, int]:
        """Clean share URLs and convert timestamp query params into offsets."""
        from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

        parsed = urlparse(youtube_url.strip())
        qs = parse_qs(parsed.query)

        timestamp = 0
        for key in ("t", "start"):
            if key in qs and qs[key]:
                timestamp = self._parse_youtube_timestamp(qs[key][0])
                break
        if timestamp and start_sec <= 0:
            window = max(1, end_sec - start_sec)
            start_sec = timestamp
            end_sec = timestamp + window
            print(f"   Using YouTube timestamp as analysis start: {start_sec}s", flush=True)

        host = parsed.netloc.lower().replace("www.", "").replace("m.", "")
        video_id = None

        if host == "youtu.be":
            video_id = parsed.path.strip("/").split("/")[0]
        elif host.endswith("youtube.com"):
            if parsed.path == "/watch":
                video_id = qs.get("v", [None])[0]
            elif parsed.path.startswith("/shorts/") or parsed.path.startswith("/embed/"):
                video_id = parsed.path.strip("/").split("/")[1]

        if video_id:
            cleaned_url = f"https://www.youtube.com/watch?{urlencode({'v': video_id})}"
        else:
            cleaned_url = urlunparse(parsed._replace(query="", fragment=""))

        if cleaned_url != youtube_url:
            print(f"   Cleaned URL: {youtube_url} -> {cleaned_url}", flush=True)

        return cleaned_url, start_sec, end_sec

    def _call_gemini(self, youtube_url: str, start_sec: int = 0, end_sec: int = 600) -> str:
        """Try each model in the fallback chain until one succeeds."""
        from google.genai import types

        youtube_url, start_sec, end_sec = self._normalize_youtube_reference(
            youtube_url, start_sec, end_sec
        )

        clip_sec = end_sec - start_sec
        if clip_sec > self.max_analysis_sec:
            end_sec = start_sec + self.max_analysis_sec
            clip_sec = self.max_analysis_sec
            print(
                f"   Capping analysis to {self.max_analysis_sec}s "
                f"({start_sec}s-{end_sec}s)",
                flush=True,
            )

        # Long ambient clips: low FPS + low media resolution keeps token use sane.
        fps = 1.0
        if clip_sec > 300:
            fps = 0.25
        elif clip_sec > 120:
            fps = 0.5
        media_resolution = (
            types.MediaResolution.MEDIA_RESOLUTION_LOW
            if clip_sec > 120
            else None
        )

        video_part = types.Part(
            file_data=types.FileData(
                file_uri=youtube_url,
                mime_type="video/mp4",
            ),
            video_metadata=types.VideoMetadata(
                start_offset=f"{start_sec}s",
                end_offset=f"{end_sec}s",
                fps=fps,
            ),
        )
        gen_config = (
            types.GenerateContentConfig(media_resolution=media_resolution)
            if media_resolution
            else None
        )

        last_error = None
        print(f"   Models to try: {self.FALLBACK_MODELS}", flush=True)
        for model in self.FALLBACK_MODELS:
            for attempt in range(1, 4):
                if not gemini_limiter.wait_if_needed(timeout=90):
                    print(f"   ✗ Gemini rate limit — cannot proceed", flush=True)
                    raise RuntimeError("Gemini daily rate limit reached. Try again tomorrow or upgrade your plan at https://aistudio.google.com")

                try:
                    print(f"   Trying model: {model} (attempt {attempt})", flush=True)
                    gemini_limiter.record_call(f"ref_analysis:{model}")
                    response = self.client.models.generate_content(
                        model=model,
                        contents=[video_part, REFERENCE_ANALYSIS_PROMPT],
                        config=gen_config,
                    )
                    print(f"   ✓ Success with model: {model}", flush=True)
                    self.last_model_used = model
                    return response.text.strip()
                except Exception as e:
                    last_error = e
                    err_str = str(e)
                    print(f"   ✗ {model} failed: {type(e).__name__}: {err_str[:150]}", flush=True)
                    is_rate_limit = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
                    if is_rate_limit and attempt < 3:
                        delay = gemini_limiter.handle_429(attempt)
                        time.sleep(delay)
                        continue
                    break

        raise last_error

    def analyze(self, youtube_url: str, start_sec: int = 0, end_sec: int = 600) -> dict:
        """
        Analyze a YouTube video's audio. Returns structured dict on success.
        On failure, returns {"_error": "human-readable reason"}.

        IMPORTANT: This must never crash the pipeline. If anything fails
        (bad URL, rate limit, parse error), return error dict and log.
        """
        print(f"   Analyzing reference: {youtube_url} ({start_sec}s - {end_sec}s)")

        try:
            text = self._call_gemini(youtube_url, start_sec=start_sec, end_sec=end_sec)

            if text.startswith("```"):
                text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]

            data = json.loads(text.strip())
            if self.last_model_used:
                data["_model_used"] = self.last_model_used

            if "layers" not in data or "mix_qualities" not in data:
                print("   ⚠ Reference analysis missing required fields, skipping")
                return {"_error": "Gemini returned a response but it was missing expected fields. The video audio may be too unclear or short."}

            n_layers = len(data.get("layers", []))
            n_recreate = len(data.get("recreate_with", []))
            print(f"   ✓ Reference analyzed: {n_layers} layers identified, "
                  f"{n_recreate} recreate prompts")
            print(f"   Overall feel: {data.get('overall_feel', 'N/A')[:120]}...")
            for i, layer in enumerate(data.get("layers", [])):
                print(f"   Layer {i+1}: {layer.get('sound', '?')} "
                      f"({layer.get('character', '?')})")
            for r in data.get("recreate_with", []):
                print(f"   Recreate: {r.get('layer_name', '?')} -> "
                      f"{r.get('elevenlabs_prompt', '?')[:80]}...")
            return data

        except RuntimeError as e:
            # Raised by _call_gemini for rate limit exhaustion
            print(f"   ⚠ Reference analysis failed (RuntimeError): {e}")
            return {"_error": str(e)}

        except Exception as e:
            err_str = str(e)
            print(f"   ⚠ Reference analysis failed ({type(e).__name__}): {e}")
            import traceback
            traceback.print_exc()

            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                reason = f"Rate limited (429) — all Gemini models hit their quota. Wait a minute and try again, or check your limits at https://aistudio.google.com"
            elif "404" in err_str or "not found" in err_str.lower() or "no longer available" in err_str.lower():
                reason = f"Gemini model not found or deprecated. Models tried: {self.FALLBACK_MODELS}"
            elif "403" in err_str or "PERMISSION_DENIED" in err_str:
                reason = "Permission denied — check your Gemini API key is valid and has access enabled."
            elif "INVALID_ARGUMENT" in err_str or "invalid" in err_str.lower():
                reason = f"Gemini rejected the request — the YouTube URL may be private, age-restricted, or unavailable in Gemini's region. Error: {err_str[:200]}"
            elif "timeout" in err_str.lower() or "deadline" in err_str.lower():
                reason = "Request timed out — Gemini took too long to process the video. Try a shorter segment."
            elif "json" in type(e).__name__.lower() or "JSON" in err_str:
                reason = "Gemini returned a response but it wasn't valid JSON — the model may have been confused by the audio content. Try a different video."
            else:
                reason = f"{type(e).__name__}: {err_str[:250]}"

            return {"_error": reason}
            return None
