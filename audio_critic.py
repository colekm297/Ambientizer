"""
audio_critic.py — The "ears" of the system.

Uses Gemini (via Google's API) to actually listen to rendered soundscapes and
produce structured critiques. Augments perceptual judgment with extracted audio
features from librosa.

Two critic implementations:
  - GeminiAudioCritic: sends audio to Gemini 2.5 Flash/Pro for real listening
  - FeatureOnlyCritic: uses Claude + librosa features only (no audio listening)
"""

import json
import os
from pathlib import Path

from google import genai
from google.genai import types

from schemas import SoundscapeConfig, CritiqueResult, AudioFeatures
from audio_engine import extract_features


def _to_str_list(val) -> list[str]:
    """Coerce a list of possibly-dict items to clean strings.
    Gemini sometimes returns structured objects like {"problem": "...", "suggested_fix": "..."}
    instead of plain strings."""
    if not isinstance(val, list):
        return []
    result = []
    for item in val:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            problem = item.get("problem", item.get("issue", ""))
            fix = item.get("suggested_fix", item.get("fix", ""))
            if problem and fix:
                result.append(f"{problem} (Suggested fix: {fix})")
            elif problem:
                result.append(problem)
            else:
                result.append(str(item))
        else:
            result.append(str(item))
    return result


CRITIQUE_PROMPT_TEMPLATE = """You are evaluating ambient audio designed for BACKGROUND LISTENING on YouTube.
Someone will play this for 1-8 hours while studying, working, or relaxing.

THE AUDIO WAS DESIGNED WITH THIS INTENT:
Original prompt: {intent}
Target mood: {mood}
Target setting: {setting}

MEASURED AUDIO FEATURES:
- Brightness (spectral centroid): {centroid_hz:.0f} Hz mean
- Frequency balance: {low_pct:.0f}% low, {mid_pct:.0f}% mid, {high_pct:.0f}% high
- Dynamic range: {dynamic_range:.1f} dB
- Onset density: {onset_density:.2f} events/sec
- Spectral flatness: {flatness:.3f}
- Loudness: {loudness:.1f} LUFS

EVALUATE AGAINST THESE CRITERIA (in priority order):

1. LISTENABILITY: Could someone have this on for 3 hours while working?
   - Anything harsh, piercing, or tiring in the 2-5kHz range?
   - Any sudden volume spikes or startling moments?
   - Is the overall energy level appropriate for background use?
   - Note: "appropriate" can range from whisper-quiet to moderately present, \
depending on the intent. A "cozy fireplace" should feel present and warm, \
not barely audible.

2. COHESION: Do the layers sound like one unified environment?
   - Or do they sound like separate audio files stacked on top of each other?
   - Does any single element stick out and demand attention?
   - Do the layers share a consistent sense of space/reverb?

3. MOOD AND CHARACTER: Does it evoke what was intended?
   - Does it feel like the place/atmosphere described?
   - Is it emotionally resonant or generic?

4. PRODUCTION QUALITY: Does it sound polished?
   - Clean frequency balance or muddy/thin?
   - Appropriate stereo width?
   - Any artifacts, clicks, or unnatural transitions?

SCORING:
- 0.0-0.3: Uncomfortable or distracting — would turn this off quickly
- 0.3-0.5: Recognizable intent but significant issues for background use
- 0.5-0.7: Pleasant, would leave on, but noticeably amateur
- 0.7-0.85: Professional quality — competitive with YouTube ambient channels
- 0.85-1.0: Exceptional — would bookmark this

Be specific and actionable in your critique. For each issue, suggest a concrete fix.

Respond with JSON:
{{
    "perceived_mood": "what this actually feels like",
    "perceived_setting": "what environment this evokes",
    "perceived_quality": "professional|amateur|mixed",
    "strengths": ["what works well"],
    "issues": ["specific problems, each with a suggested fix"],
    "specific_suggestions": ["concrete adjustments to improve it"],
    "mood_match": 0.0-1.0,
    "density_match": 0.0-1.0,
    "frequency_balance_score": 0.0-1.0,
    "overall_score": 0.0-1.0
}}

Output ONLY valid JSON."""


class GeminiAudioCritic:
    """
    Listens to rendered audio using Gemini and produces structured critiques.

    The critique combines:
    1. Perceptual judgment from Gemini (it actually "hears" the audio)
    2. Quantitative features extracted via librosa
    3. Comparison against the original intent/config
    """

    def __init__(
        self,
        gemini_api_key: str,
        model: str = "gemini-2.5-flash",
    ):
        self.client = genai.Client(api_key=gemini_api_key)
        self.model = model

    def critique(
        self,
        audio_path: str,
        config: SoundscapeConfig,
        reference_analysis: dict = None,
    ) -> CritiqueResult:
        """
        Listen to a rendered soundscape and produce a structured critique.

        Args:
            audio_path: Path to the rendered audio file (.wav)
            config: The SoundscapeConfig that produced this audio
            reference_analysis: Optional raw reference analysis dict

        Returns:
            CritiqueResult with perceptual assessment and feature data
        """
        features = extract_features(audio_path)

        prompt_text = CRITIQUE_PROMPT_TEMPLATE.format(
            intent=config.description,
            mood=config.mood,
            setting=config.setting,
            centroid_hz=features.spectral_centroid_mean_hz,
            low_pct=features.low_energy_ratio * 100,
            mid_pct=features.mid_energy_ratio * 100,
            high_pct=features.high_energy_ratio * 100,
            dynamic_range=features.dynamic_range_db,
            onset_density=features.onset_density_per_sec,
            flatness=features.spectral_flatness_mean,
            loudness=features.loudness_lufs,
        )

        if reference_analysis:
            prompt_text += f"""

REFERENCE COMPARISON:
The user provided a YouTube reference they like. It has these qualities:
{json.dumps(reference_analysis.get('mix_qualities', {}), indent=2)}

It works because: {reference_analysis.get('why_it_works', [])}

Compare our generated audio against the reference's character.
Are we achieving a similar feel? What's different?
"""

        with open(audio_path, "rb") as f:
            audio_bytes = f.read()

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=[
                    types.Part.from_bytes(
                        data=audio_bytes,
                        mime_type="audio/wav",
                    ),
                    prompt_text,
                ],
            )
            response_text = response.text
        except Exception as e:
            print(f"  ⚠ Gemini API error: {e}")
            print("  Falling back to feature-only assessment")
            return self._fallback_critique(features, config)

        critique = self._parse_critique(response_text, features)
        return critique

    def quick_listen(self, audio_path: str) -> str:
        """
        Quick, unstructured listen — just ask Gemini to describe what it hears.
        Useful for debugging and sanity checks.
        """
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=[
                    types.Part.from_bytes(
                        data=audio_bytes,
                        mime_type="audio/wav",
                    ),
                    (
                        "Describe this audio in detail. What sounds do you hear? "
                        "What mood does it evoke? What environment does it suggest? "
                        "How would you rate its quality as an ambient soundscape?"
                    ),
                ],
            )
            return response.text
        except Exception as e:
            return f"Gemini API error: {e}"

    def _parse_critique(self, response_text: str, features: AudioFeatures) -> CritiqueResult:
        """Parse the model's JSON response into a structured CritiqueResult."""
        try:
            clean = response_text.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1]
            if clean.endswith("```"):
                clean = clean.rsplit("```", 1)[0]
            clean = clean.strip()

            data = json.loads(clean)

            return CritiqueResult(
                perceived_mood=data.get("perceived_mood", "unknown"),
                perceived_setting=data.get("perceived_setting", "unknown"),
                perceived_quality=data.get("perceived_quality", "mixed"),
                strengths=_to_str_list(data.get("strengths", [])),
                issues=_to_str_list(data.get("issues", [])),
                specific_suggestions=_to_str_list(data.get("specific_suggestions", [])),
                mood_match=float(data.get("mood_match", 0.5)),
                density_match=float(data.get("density_match", 0.5)),
                frequency_balance_score=float(data.get("frequency_balance_score", 0.5)),
                overall_score=float(data.get("overall_score", 0.5)),
                features=features,
            )

        except (json.JSONDecodeError, KeyError) as e:
            print(f"  ⚠ Failed to parse critique JSON: {e}")
            print(f"  Raw response: {response_text[:500]}")
            return CritiqueResult(
                perceived_mood="parse_error",
                perceived_setting="parse_error",
                perceived_quality="unknown",
                strengths=[],
                issues=["Could not parse audio critique — retrying recommended"],
                specific_suggestions=[],
                mood_match=0.5,
                density_match=0.5,
                frequency_balance_score=0.5,
                overall_score=0.4,
                features=features,
            )

    def _fallback_critique(self, features: AudioFeatures, config: SoundscapeConfig) -> CritiqueResult:
        """Return a conservative default critique when the API call fails."""
        return CritiqueResult(
            perceived_mood="api_error",
            perceived_setting="api_error",
            perceived_quality="unknown",
            strengths=[],
            issues=["Gemini API call failed — using fallback assessment"],
            specific_suggestions=["Retry with working API connection"],
            mood_match=0.5,
            density_match=0.5,
            frequency_balance_score=0.5,
            overall_score=0.4,
            features=features,
        )


class FeatureOnlyCritic:
    """
    Fallback critic that uses only extracted audio features + an LLM (no audio listening).
    Useful when you want to test without burning Gemini credits.
    """

    def __init__(self, anthropic_api_key: str, model: str = "claude-sonnet-4-6"):
        from anthropic import Anthropic
        self.client = Anthropic(api_key=anthropic_api_key)
        self.model = model

    def critique(self, audio_path: str, config: SoundscapeConfig, reference_analysis: dict = None) -> CritiqueResult:
        """Critique based on features only — no actual listening."""
        features = extract_features(audio_path)

        prompt = f"""You are an expert audio engineer. A soundscape was generated with this intent:

INTENT: {config.description}
MOOD: {config.mood}
SETTING: {config.setting}

The rendered audio has these measured features:
- Brightness: {features.spectral_centroid_mean_hz:.0f} Hz mean ({features.spectral_centroid_std_hz:.0f} Hz std)
- Frequency balance: {features.low_energy_ratio*100:.0f}% low, {features.mid_energy_ratio*100:.0f}% mid, {features.high_energy_ratio*100:.0f}% high
- Dynamic range: {features.dynamic_range_db:.1f} dB
- Onset density: {features.onset_density_per_sec:.2f} events/sec
- Spectral flatness: {features.spectral_flatness_mean:.3f}
- Loudness: {features.loudness_lufs:.1f} LUFS

The config has {len(config.layers)} layers: {[l.name for l in config.layers]}

Based on the features and your expertise, assess whether this likely achieves the intent.
Respond with JSON matching this schema:
{{"perceived_mood": "...", "perceived_setting": "...", "perceived_quality": "...",
  "strengths": [...], "issues": [...], "specific_suggestions": [...],
  "mood_match": 0.0-1.0, "density_match": 0.0-1.0,
  "frequency_balance_score": 0.0-1.0, "overall_score": 0.0-1.0}}

Output ONLY valid JSON."""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )

        try:
            data = json.loads(response.content[0].text)
            return CritiqueResult(
                perceived_mood=data.get("perceived_mood", "unknown"),
                perceived_setting=data.get("perceived_setting", "unknown"),
                perceived_quality=data.get("perceived_quality", "mixed"),
                strengths=_to_str_list(data.get("strengths", [])),
                issues=_to_str_list(data.get("issues", [])),
                specific_suggestions=_to_str_list(data.get("specific_suggestions", [])),
                mood_match=float(data.get("mood_match", 0.5)),
                density_match=float(data.get("density_match", 0.5)),
                frequency_balance_score=float(data.get("frequency_balance_score", 0.5)),
                overall_score=float(data.get("overall_score", 0.5)),
                features=features,
            )
        except (json.JSONDecodeError, KeyError):
            return CritiqueResult(
                perceived_mood="parse_error", perceived_setting="parse_error",
                perceived_quality="unknown", strengths=[], issues=["Parse error"],
                specific_suggestions=[], mood_match=0.5, density_match=0.5,
                frequency_balance_score=0.5, overall_score=0.4, features=features,
            )
