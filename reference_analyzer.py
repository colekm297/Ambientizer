"""
reference_analyzer.py — Analyzes YouTube ambient/soundscape videos via Gemini.

Uses Gemini's native YouTube URL processing to extract what makes a reference
track work for background listening. The analysis feeds into the theme interpreter
and audio critic to ground generation in proven real-world examples.

No downloading needed — Gemini receives the YouTube URL directly.
"""

import json
from typing import Optional


REFERENCE_ANALYSIS_PROMPT = """Listen to the AUDIO in this YouTube video (ignore visuals). \
Identify every distinct sonic element you can hear.

Return a JSON object:

{
    "overall_feel": "What does it feel like to listen to this? Describe the sonic character.",

    "layers": [
        {
            "sound": "what this element is",
            "role": "what it contributes to the mix",
            "volume": "loudness relative to the mix",
            "character": "tonal quality"
        }
    ],

    "mix_qualities": {
        "volume": "overall loudness feel",
        "frequency_balance": "how lows/mids/highs are balanced",
        "spaciousness": "how reverberant or wide the mix is",
        "dynamics": "how much the volume varies"
    },

    "recreate_with": [
        {
            "layer_name": "descriptive name",
            "layer_type": "musical OR sfx",
            "elevenlabs_prompt": "Vivid description of this sound for an AI audio \
generator. Under 400 characters. Describe what you actually hear."
        }
    ]
}

Identify at least 5-8 distinct layers — don't lump related sounds together. \
For each layer, mark it as "musical" (tonal/harmonic) or "sfx" (environmental/textural). \
recreate_with must have one entry per layer.

Return ONLY valid JSON, no markdown fences."""


class ReferenceAnalyzer:
    """
    Analyzes YouTube ambient/soundscape videos to extract what makes them work.
    Uses Gemini's native YouTube URL processing — no download needed.
    """

    def __init__(self, gemini_api_key: str):
        from google import genai
        self.client = genai.Client(api_key=gemini_api_key)
        self.model_name = "gemini-2.5-pro"

    def analyze(self, youtube_url: str) -> Optional[dict]:
        """
        Analyze a YouTube video's audio. Returns structured dict or None on failure.

        IMPORTANT: This must never crash the pipeline. If anything fails
        (bad URL, rate limit, parse error), return None and log the error.
        """
        print(f"   🎧 Analyzing reference: {youtube_url}")

        try:
            from google.genai import types

            video_part = types.Part(
                file_data=types.FileData(
                    file_uri=youtube_url,
                    mime_type="video/mp4",
                ),
                video_metadata=types.VideoMetadata(
                    start_offset="0s",
                    end_offset="180s",
                ),
            )

            response = self.client.models.generate_content(
                model=self.model_name,
                contents=[video_part, REFERENCE_ANALYSIS_PROMPT],
            )

            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]

            data = json.loads(text.strip())

            if "layers" not in data or "mix_qualities" not in data:
                print("   ⚠ Reference analysis missing required fields, skipping")
                return None

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

        except Exception as e:
            print(f"   ⚠ Reference analysis failed ({type(e).__name__}): {e}")
            import traceback
            traceback.print_exc()
            print("     Continuing without reference — this is not fatal.")
            return None
