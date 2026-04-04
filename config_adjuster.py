"""
config_adjuster.py — Translates critique results into config modifications.

Uses a DIFF-BASED approach: instead of asking Claude to rewrite the entire config
(which causes drift, lost fields, and compounding errors), we ask for a small list
of specific parameter changes and apply them programmatically.

This guarantees:
- generated_audio_path is never lost
- Layers are never randomly added or removed
- Unchanged fields stay exactly as they were
- Claude focuses on a small number of high-impact changes
"""

import copy
import json
from anthropic import Anthropic
from schemas import SoundscapeConfig, CritiqueResult


ADJUSTER_SYSTEM = """You are a mix engineer adjusting an ambient soundscape for background listening.

You will receive the current mix config and a critique. Your job: output a small JSON \
list of specific parameter changes that address the critic's TOP concerns.

IMPORTANT CONSTRAINTS:
- Output 2-5 changes maximum. Less is more — one precise fix beats five scattered ones.
- You can ONLY adjust mix parameters. You cannot change the audio samples.
- Do NOT add or remove layers. Work with what exists.
- Focus on what the critic ACTUALLY complained about. Ignore issues about sample \
quality (looping, realism) — you can't fix those with mix adjustments.
- If the critic says something is "too loud": reduce volume_db by 4-6 dB.
- If something is "harsh": lower low_pass_hz by 2000-3000 Hz AND cut volume 2-3 dB.
- If layers "don't blend": increase reverb_amount on the drier layers.
- If something "sticks out": cut its volume and increase its reverb.

Output format — ONLY this JSON, nothing else:
{
  "reasoning": "One sentence explaining your approach",
  "changes": [
    {"layer": "Layer Name", "param": "volume_db", "value": -18.0},
    {"layer": "Layer Name", "param": "effects.low_pass_hz", "value": 7000},
    {"layer": "Layer Name", "param": "effects.reverb_amount", "value": 0.6},
    {"target": "master_effects", "param": "reverb_amount", "value": 0.5}
  ]
}

LAYER PARAMS you can change:
  volume_db, pan, fade_in_sec, fade_out_sec, density,
  effects.reverb_amount, effects.reverb_room_size,
  effects.low_pass_hz, effects.high_pass_hz,
  effects.compression_threshold_db, effects.compression_ratio

MASTER PARAMS (use "target": "master_effects"):
  reverb_amount, reverb_room_size, low_pass_hz, high_pass_hz,
  compression_threshold_db, compression_ratio

Output ONLY valid JSON."""


class ConfigAdjuster:
    """
    Takes a critique and current config, produces a revised config via targeted diffs.
    """

    def __init__(self, anthropic_api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.client = Anthropic(api_key=anthropic_api_key)
        self.model = model

    def adjust(
        self,
        config: SoundscapeConfig,
        critique: CritiqueResult,
        iteration: int = 0,
        score_trend: str = "",
    ) -> SoundscapeConfig:
        prompt = self._build_prompt(config, critique, iteration, score_trend)

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1000,
            system=ADJUSTER_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text
        return self._parse_and_apply(raw, config)

    def _build_prompt(
        self,
        config: SoundscapeConfig,
        critique: CritiqueResult,
        iteration: int,
        score_trend: str = "",
    ) -> str:
        layers_summary = []
        for layer in config.layers:
            fx = layer.effects
            layers_summary.append({
                "name": layer.name,
                "type": layer.layer_type.value,
                "volume_db": layer.volume_db,
                "pan": layer.pan,
                "density": layer.density,
                "effects": {
                    "reverb_amount": fx.reverb_amount if fx else 0.3,
                    "reverb_room_size": fx.reverb_room_size if fx else 0.5,
                    "low_pass_hz": fx.low_pass_hz if fx else None,
                    "high_pass_hz": fx.high_pass_hz if fx else None,
                } if fx else "none",
            })

        master_fx = config.master_effects
        master_summary = {
            "reverb_amount": master_fx.reverb_amount,
            "reverb_room_size": master_fx.reverb_room_size,
            "low_pass_hz": master_fx.low_pass_hz,
            "high_pass_hz": master_fx.high_pass_hz,
        }

        feature_summary = ""
        if critique.features:
            f = critique.features
            feature_summary = f"""
AUDIO MEASUREMENTS:
- Loudness: {f.loudness_lufs:.1f} LUFS
- Brightness: {f.spectral_centroid_mean_hz:.0f} Hz
- Frequency balance: {f.low_energy_ratio*100:.0f}% low / {f.mid_energy_ratio*100:.0f}% mid / {f.high_energy_ratio*100:.0f}% high
- Dynamic range: {f.dynamic_range_db:.1f} dB"""

        return f"""ITERATION {iteration + 1}

CURRENT MIX:
Layers: {json.dumps(layers_summary, indent=2)}
Master effects: {json.dumps(master_summary, indent=2)}

CRITIQUE (score: {critique.overall_score:.2f}):
Strengths: {'; '.join(str(s) for s in critique.strengths[:3])}
Issues: {'; '.join(str(s) for s in critique.issues[:3])}
Suggestions: {'; '.join(str(s) for s in critique.specific_suggestions[:3])}
{feature_summary}
{score_trend}
Output your changes as JSON. Remember: 2-5 targeted changes only, no layer additions."""

    def _parse_and_apply(self, raw: str, config: SoundscapeConfig) -> SoundscapeConfig:
        """Parse the diff JSON and apply changes to a deep copy of the config."""
        new_config = copy.deepcopy(config)

        try:
            clean = raw.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1]
            if clean.endswith("```"):
                clean = clean.rsplit("```", 1)[0]

            data = json.loads(clean.strip())
            changes = data.get("changes", [])

            if data.get("reasoning"):
                print(f"      Adjuster: {data['reasoning']}")

            applied = 0
            for change in changes:
                if self._apply_change(new_config, change):
                    applied += 1

            print(f"      Applied {applied}/{len(changes)} changes")
            return new_config

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            print(f"  ⚠ Failed to parse adjustment: {e}")
            return config

    def _apply_change(self, config: SoundscapeConfig, change: dict) -> bool:
        """Apply a single change to the config. Returns True if successful."""
        try:
            param = change.get("param", "")
            value = change.get("value")
            layer_name = change.get("layer")
            target = change.get("target")

            if target == "master_effects":
                if hasattr(config.master_effects, param):
                    old = getattr(config.master_effects, param)
                    setattr(config.master_effects, param, value)
                    print(f"      master_effects.{param}: {old} → {value}")
                    return True
                return False

            if layer_name:
                layer = next((l for l in config.layers if l.name == layer_name), None)
                if not layer:
                    print(f"      ⚠ Layer '{layer_name}' not found, skipping")
                    return False

                if "." in param:
                    obj_name, field = param.split(".", 1)
                    obj = getattr(layer, obj_name, None)
                    if obj is None and obj_name == "effects":
                        from schemas import EffectsChain
                        layer.effects = EffectsChain()
                        obj = layer.effects
                    if obj and hasattr(obj, field):
                        old = getattr(obj, field)
                        setattr(obj, field, value)
                        print(f"      {layer_name}.{param}: {old} → {value}")
                        return True
                else:
                    if hasattr(layer, param) and param not in (
                        "name", "layer_type", "sample_tags",
                        "elevenlabs_prompt", "generated_audio_path",
                    ):
                        old = getattr(layer, param)
                        setattr(layer, param, value)
                        print(f"      {layer_name}.{param}: {old} → {value}")
                        return True
                    else:
                        print(f"      ⚠ Cannot change '{param}' on layer")
                        return False

            return False

        except Exception as e:
            print(f"      ⚠ Change failed: {e}")
            return False
