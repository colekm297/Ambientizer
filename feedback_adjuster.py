"""
feedback_adjuster.py — Translates natural language user feedback into config changes.

Replaces the automated critique loop with human-in-the-loop refinement.
The user listens and says things like "rain too loud" or "more reverb" and
this module translates that into specific mix parameter changes.

Uses a hybrid approach:
  1. Primary: diff-based — Claude outputs targeted changes, applied to a deepcopy
  2. Fallback: full config parse with generated_audio_path safeguards
"""

import copy
import json
from anthropic import Anthropic
from schemas import SoundscapeConfig, EffectsChain


FEEDBACK_SYSTEM = """You are helping a user refine an ambient soundscape mix. The user listens \
and gives natural language feedback. You can make two types of changes:

1. MIX CHANGES — adjust volume, effects, panning (instant re-render)
2. REGENERATE — replace a layer's sound via AI audio generation (slower)

PARAMETER REFERENCE:
- volume_db: layer loudness (range: -40 to 0, -60 = muted)
- pan: stereo position (-1.0 left to 1.0 right)
- effects.reverb_amount: reverb wet level (0.0 to 1.0)
- effects.low_pass_hz: cuts frequencies above this (lower = warmer/darker)
- effects.high_pass_hz: cuts frequencies below this (higher = thinner)

AUDIO GENERATION:
When regenerating, set layer_type to "musical" for tonal/harmonic content (pads, \
drones, piano, synths) or "base"/"mid"/"detail" for environmental sounds. \
Write vivid prompts under 400 characters.

Be decisive — make noticeable changes. The user will tell you if you overshot.

OUTPUT FORMAT — ONLY this JSON, nothing else:
{
  "reasoning": "One sentence explaining what you're doing and why",
  "changes": [
    {"layer": "Layer Name", "param": "volume_db", "value": -18.0},
    {"layer": "Layer Name", "param": "effects.reverb_amount", "value": 0.6},
    {"target": "master_effects", "param": "reverb_amount", "value": 0.5}
  ],
  "regenerate": [
    {"layer": "Layer Name", "new_prompt": "detailed sound description", "layer_type": "musical"},
    {"layer": "Layer Name", "new_prompt": null}
  ]
}

The "regenerate" array is OPTIONAL — omit it or leave it empty [] if no layers need
new audio. Only include it when the user specifically wants a DIFFERENT SOUND, not
just a volume/effects tweak. When new_prompt is null, the existing sound description
is re-rolled (same prompt, different random result).

The "layer_type" field in regenerate is OPTIONAL. Use it when switching a layer between
sound effect and music generation:
- "musical" → uses Music API (for pads, drones, piano, strings, evolving tones)
- "base"/"mid"/"detail" → uses SFX API (for rain, wind, fire, birds, textures)

LAYER PARAMS for mix changes:
  volume_db, pan, pan_randomize, fade_in_sec, fade_out_sec, density,
  effects.reverb_amount, effects.reverb_room_size,
  effects.low_pass_hz, effects.high_pass_hz,
  effects.compression_threshold_db, effects.compression_ratio

MASTER PARAMS (use "target": "master_effects"):
  reverb_amount, reverb_room_size, low_pass_hz, high_pass_hz,
  compression_threshold_db, compression_ratio

Output ONLY valid JSON. No explanation outside the JSON."""


class FeedbackAdjuster:
    """
    Takes natural language feedback from the user and adjusts the SoundscapeConfig.

    Maintains conversation history so multi-turn feedback works:
    "make rain quieter" then "actually a bit louder than that".
    """

    def __init__(self, anthropic_api_key: str, model: str = "claude-sonnet-4-6"):
        self.client = Anthropic(api_key=anthropic_api_key)
        self.model = model
        self.history: list[dict] = []

    def adjust(self, feedback: str, current_config: SoundscapeConfig) -> tuple[SoundscapeConfig, str, list[dict]]:
        """
        Apply user feedback to the current config.

        Returns:
            (revised_config, reasoning_string, regenerations)
            regenerations is a list of {"layer": name, "new_prompt": str|None}
        """
        layers_summary = []
        for layer in current_config.layers:
            fx = layer.effects
            entry = {
                "name": layer.name,
                "type": layer.layer_type.value,
                "volume_db": layer.volume_db,
                "pan": layer.pan,
                "density": layer.density,
            }
            if fx:
                entry["effects"] = {
                    "reverb_amount": fx.reverb_amount,
                    "reverb_room_size": fx.reverb_room_size,
                    "low_pass_hz": fx.low_pass_hz,
                    "high_pass_hz": fx.high_pass_hz,
                }
            layers_summary.append(entry)

        master_fx = current_config.master_effects
        master_summary = {
            "reverb_amount": master_fx.reverb_amount,
            "reverb_room_size": master_fx.reverb_room_size,
            "low_pass_hz": master_fx.low_pass_hz,
            "high_pass_hz": master_fx.high_pass_hz,
        }

        user_message = (
            f"CURRENT MIX:\n"
            f"Layers: {json.dumps(layers_summary, indent=2)}\n"
            f"Master effects: {json.dumps(master_summary, indent=2)}\n\n"
            f"USER FEEDBACK: {feedback}\n\n"
            f"Apply the feedback. Output ONLY the JSON with reasoning + changes."
        )

        self.history.append({"role": "user", "content": user_message})

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1000,
            system=FEEDBACK_SYSTEM,
            messages=self.history,
        )

        assistant_text = response.content[0].text
        self.history.append({"role": "assistant", "content": assistant_text})

        return self._parse_and_apply(assistant_text, current_config)

    def reset(self):
        """Clear conversation history for a new generation."""
        self.history = []

    def _parse_and_apply(
        self, raw: str, config: SoundscapeConfig
    ) -> tuple[SoundscapeConfig, str, list[dict]]:
        """Parse diff JSON and apply to a deep copy. Returns (new_config, reasoning, regenerations)."""
        new_config = copy.deepcopy(config)

        try:
            clean = raw.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1]
            if clean.endswith("```"):
                clean = clean.rsplit("```", 1)[0]

            data = json.loads(clean.strip())
            changes = data.get("changes", [])
            reasoning = data.get("reasoning", "")
            regenerations = data.get("regenerate", [])

            applied = 0
            for change in changes:
                if self._apply_change(new_config, change):
                    applied += 1

            valid_layer_names = {l.name for l in config.layers}
            valid_regens = []
            for regen in regenerations:
                layer_name = regen.get("layer", "")
                if layer_name in valid_layer_names:
                    valid_regens.append({
                        "layer": layer_name,
                        "new_prompt": regen.get("new_prompt"),
                        "layer_type": regen.get("layer_type"),
                    })
                    print(f"      Regenerate: {layer_name}"
                          f"{' (new prompt)' if regen.get('new_prompt') else ' (re-roll)'}")
                else:
                    print(f"      Regenerate skipped: layer '{layer_name}' not found")

            print(f"   FeedbackAdjuster: {reasoning}")
            print(f"   Applied {applied}/{len(changes)} mix changes, "
                  f"{len(valid_regens)} regeneration(s)")
            return new_config, reasoning, valid_regens

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            print(f"   FeedbackAdjuster parse error: {e}, attempting full-config fallback")
            config_result, reason = self._full_config_fallback(raw, config)
            return config_result, reason, []

    def _full_config_fallback(
        self, raw: str, original: SoundscapeConfig
    ) -> tuple[SoundscapeConfig, str]:
        """
        Fallback: if Claude output a full config instead of diffs,
        parse it but preserve generated_audio_path from original.
        """
        try:
            clean = raw.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1]
            if clean.endswith("```"):
                clean = clean.rsplit("```", 1)[0]

            data = json.loads(clean.strip())

            if "layers" not in data:
                return original, "Could not parse feedback response"

            from schemas import LayerConfig, LayerType, EnergyCurve

            new_config = copy.deepcopy(original)

            path_map = {l.name: l.generated_audio_path for l in original.layers}

            layers = []
            for ld in data["layers"]:
                effects = None
                if ld.get("effects"):
                    effects = EffectsChain(**ld["effects"])

                layer = LayerConfig(
                    name=ld["name"],
                    layer_type=LayerType(ld["layer_type"]),
                    sample_tags=ld.get("sample_tags", []),
                    volume_db=ld.get("volume_db", -12.0),
                    pan=ld.get("pan", 0.0),
                    pan_randomize=ld.get("pan_randomize", False),
                    loop=ld.get("loop", True),
                    fade_in_sec=ld.get("fade_in_sec", 2.0),
                    fade_out_sec=ld.get("fade_out_sec", 2.0),
                    min_interval_sec=ld.get("min_interval_sec", 0.0),
                    max_interval_sec=ld.get("max_interval_sec", 0.0),
                    density=ld.get("density", 1.0),
                    effects=effects,
                    elevenlabs_prompt=ld.get("elevenlabs_prompt"),
                    generated_audio_path=path_map.get(ld["name"]),
                )
                layers.append(layer)

            new_config.layers = layers

            if data.get("master_effects"):
                new_config.master_effects = EffectsChain(**data["master_effects"])

            return new_config, "Applied full config (fallback mode)"

        except Exception as e:
            print(f"   Full-config fallback also failed: {e}")
            return original, "Could not parse feedback response"

    def _apply_change(self, config: SoundscapeConfig, change: dict) -> bool:
        """Apply a single targeted change. Returns True if successful."""
        try:
            param = change.get("param", "")
            value = change.get("value")
            layer_name = change.get("layer")
            target = change.get("target")

            if target == "master_effects":
                if hasattr(config.master_effects, param):
                    old = getattr(config.master_effects, param)
                    setattr(config.master_effects, param, value)
                    print(f"      master_effects.{param}: {old} -> {value}")
                    return True
                return False

            if layer_name:
                layer = next((l for l in config.layers if l.name == layer_name), None)
                if not layer:
                    print(f"      Layer '{layer_name}' not found, skipping")
                    return False

                if "." in param:
                    obj_name, field = param.split(".", 1)
                    obj = getattr(layer, obj_name, None)
                    if obj is None and obj_name == "effects":
                        layer.effects = EffectsChain()
                        obj = layer.effects
                    if obj and hasattr(obj, field):
                        old = getattr(obj, field)
                        setattr(obj, field, value)
                        print(f"      {layer_name}.{param}: {old} -> {value}")
                        return True
                else:
                    immutable = (
                        "name", "layer_type", "sample_tags",
                        "elevenlabs_prompt", "generated_audio_path",
                    )
                    if hasattr(layer, param) and param not in immutable:
                        old = getattr(layer, param)
                        setattr(layer, param, value)
                        print(f"      {layer_name}.{param}: {old} -> {value}")
                        return True
                    else:
                        print(f"      Cannot change '{param}' on layer")
                        return False

            return False

        except Exception as e:
            print(f"      Change failed: {e}")
            return False
