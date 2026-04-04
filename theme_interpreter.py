"""
theme_interpreter.py — Translates natural language prompts into SoundscapeConfig.

Uses Claude (or any LLM) to understand the emotional and physical semantics of a
scene description and map them to concrete audio parameters.
"""

import json
from typing import Optional
from anthropic import Anthropic
from schemas import SoundscapeConfig, LayerConfig, LayerType, EffectsChain, EnergyCurve, GenerationMode


SYSTEM_PROMPT = """You are designing ambient soundscapes for BACKGROUND LISTENING — audio that plays \
for hours on YouTube while people study, work, sleep, or relax.

LAYER APPROACH:
3-4 layers TOTAL. Each layer is generated independently by an AI music/sound API. \
They cannot hear each other. You coordinate them by locking ALL musical layers to \
the same key and style.

MODES:
- MUSICAL: 2-3 musical layers + 1 atmosphere SFX layer.
    1. MAIN MUSIC (required, type "musical"): A COMPLETE ambient music piece with \
       actual melody and chord progressions. This is the centerpiece — it should \
       sound like a beautiful, full song on its own. Think Nils Frahm, Brian Eno, \
       Ólafur Arnalds, lo-fi study beats. It should have enough musicality that \
       a listener can latch onto it. Include specific instrument(s), key, and style.
    2. HARMONY PAD (required, type "musical"): A warm sustained pad that fills out \
       the harmonic spectrum beneath the main music. Continuous, evolving slowly. \
       Synth pads, strings, or warm textures. Same key as the main music.
    3. ATMOSPHERE (required, type "base"): Environmental SFX to ground the scene — \
       rain, wind, room tone, nature sounds, vinyl crackle, etc.

- AMBIENT: 2-3 SFX layers for environmental soundscapes. You can include 1 musical \
  layer (e.g. soft drone, singing bowl) if it fits.

CRITICAL — KEY SELECTION:
You MUST vary the key. Pick based on mood, but ALWAYS use MAJOR keys unless the user \
explicitly asks for something dark, sad, or melancholy. \
Good ambient major keys: C major, D major, Eb major, F major, G major, Ab major, Bb major. \
NEVER use A minor or D minor — they are overused. If you must use minor, try Bb minor \
or Eb minor.

CRITICAL — MUSICAL LAYER COORDINATION:
ALL musical layers MUST share:
  - The SAME key
  - The SAME mood description
  - DIFFERENT instruments (never the same instrument in two layers)
Keep tempo very slow (around 50-65 BPM) for ambient music. At this tempo, slight \
rhythmic differences between layers are unnoticeable and create organic feel.

PROMPT QUALITY — this is the most important part:
The "elevenlabs_prompt" drives the AI music generator. Write rich, specific prompts. \
IMPORTANT: The music will be looped, so it must NOT wind down, resolve, or end. \
Always include "continuous, never-ending" in every musical layer prompt.

  GOOD main music: "Beautiful ambient piano piece in G major, gentle melodic phrases \
    with warm reverb, slow tempo around 55 BPM, contemplative and peaceful, soft \
    dynamics, continuous and never-ending, inspired by Nils Frahm and Ólafur Arnalds"
  GOOD pad: "Lush warm synthesizer pad in G major, slowly evolving sustained chords, \
    ambient and enveloping, continuous and never-ending, gentle and warm"
  BAD: "Freeform drifting drone, no tempo, ambient wash" (too vague, produces formless noise)

DO NOT USE these words in musical prompts: "drone", "freeform", "no tempo", "arrhythmic". \
These produce formless noise instead of actual music.

DO NOT apply heavy frequency filtering to musical layers. Let them use their full \
spectrum. Only use effects for subtle shaping:
  - Main music: no EQ filtering (let it breathe)
  - Pad: optional gentle low_pass_hz 8000-12000 to soften brightness
  - Atmosphere SFX: low_pass_hz 8000-10000 to sit behind the music

LOOPING CONTEXT:
Output will be looped for hours. Sounds should feel continuous — never fading to silence.

VOLUME:
  Main music: -6 to -4 dB (it's the star).
  Pad: -12 to -8 dB (supportive).
  Atmosphere SFX: -14 to -10 dB (background).

If the user provides a REFERENCE ANALYSIS, use its style and mood as inspiration.

Output a JSON object matching this schema:
{
  "title": "short evocative title",
  "description": "the original user prompt, preserved",
  "mood": "primary emotional quality",
  "setting": "physical environment",
  "time_of_day": "string",
  "root_key": "G major",
  "layers": [
    {
      "name": "descriptive name",
      "layer_type": "base|mid|detail|musical",
      "sample_tags": [],
      "elevenlabs_prompt": "200-400 chars, rich and specific, include key for musical layers",
      "volume_db": -6.0,
      "pan": 0.0,
      "loop": true,
      "fade_in_sec": 3.0,
      "fade_out_sec": 3.0,
      "effects": {
        "reverb_amount": 0.3,
        "reverb_room_size": 0.5,
        "low_pass_hz": null,
        "high_pass_hz": null,
        "compression_threshold_db": -20.0,
        "compression_ratio": 2.0
      }
    }
  ],
  "master_effects": { "reverb_amount": 0.2, "reverb_room_size": 0.4, "low_pass_hz": 16000, "high_pass_hz": 30, "compression_threshold_db": -18.0, "compression_ratio": 1.5 },
  "energy_curve": {
    "style": "steady|slow_build|rise_and_fall|wave",
    "peak_position": 0.5,
    "min_energy": 0.4,
    "max_energy": 1.0
  },
  "target_loudness_lufs": -16.0
}

Output ONLY valid JSON. No explanation, no markdown fences."""


class ThemeInterpreter:
    """Converts natural language scene descriptions into SoundscapeConfig."""

    def __init__(self, anthropic_api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.client = Anthropic(api_key=anthropic_api_key)
        self.model = model

    def build_user_message(
        self,
        prompt: str,
        mode: str,
        reference_analysis: Optional[dict],
    ) -> str:
        msg = f"USER REQUEST: {prompt}\nMODE: {mode}\n"

        if reference_analysis:
            recreate = reference_analysis.get('recreate_with', [])
            msg += f"""
REFERENCE ANALYSIS (from a YouTube video the user likes):
Overall feel: {reference_analysis.get('overall_feel', 'N/A')}

Layer blueprints — use these as your layers:
{json.dumps(recreate, indent=2)}

Mix character: {json.dumps(reference_analysis.get('mix_qualities', {}))}

Use these blueprints as your starting point. Copy the elevenlabs_prompt values. \
If a layer has "layer_type": "musical", set it as musical in your config.
"""

        msg += "\nGenerate the SoundscapeConfig JSON."
        return msg

    def interpret(
        self,
        prompt: str,
        duration_sec: float = 300.0,
        mode: GenerationMode = GenerationMode.AMBIENT,
        reference_analysis: Optional[dict] = None,
    ) -> SoundscapeConfig:
        """
        Take a user's natural language prompt and return a structured SoundscapeConfig.

        Args:
            prompt: Natural language description like "rainy Tokyo alley at 2am"
            duration_sec: Target duration for the soundscape
            mode: AMBIENT (pure environment) or MUSICAL (ambient music + environment)
            reference_analysis: Optional raw analysis dict from ReferenceAnalyzer

        Returns:
            SoundscapeConfig ready to be rendered by the audio engine
        """
        user_message = self.build_user_message(prompt, mode.value, reference_analysis)

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        raw_json = response.content[0].text

        clean = raw_json.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1]
        if clean.endswith("```"):
            clean = clean.rsplit("```", 1)[0]
        clean = clean.strip()

        try:
            config_dict = json.loads(clean)
        except json.JSONDecodeError as e:
            print(f"   ⚠ JSON parse failed ({e}), retrying with shorter prompt...")
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"USER REQUEST: {prompt}\nMODE: {mode.value}\n\n"
                            "IMPORTANT: Keep elevenlabs_prompt values under 100 characters each. "
                            "Use 4 layers maximum. Output ONLY valid JSON, no markdown fences."
                        ),
                    }
                ],
            )
            raw_json = response.content[0].text
            clean = raw_json.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1]
            if clean.endswith("```"):
                clean = clean.rsplit("```", 1)[0]
            config_dict = json.loads(clean.strip())

        layers = []
        for layer_dict in config_dict.get("layers", []):
            effects = None
            if layer_dict.get("effects"):
                effects = EffectsChain(**layer_dict["effects"])

            layers.append(LayerConfig(
                name=layer_dict["name"],
                layer_type=LayerType(layer_dict["layer_type"]),
                sample_tags=layer_dict.get("sample_tags", []),
                volume_db=layer_dict.get("volume_db", -6.0),
                pan=layer_dict.get("pan", 0.0),
                pan_randomize=layer_dict.get("pan_randomize", False),
                loop=layer_dict.get("loop", True),
                fade_in_sec=layer_dict.get("fade_in_sec", 2.0),
                fade_out_sec=layer_dict.get("fade_out_sec", 2.0),
                min_interval_sec=layer_dict.get("min_interval_sec", 0.0),
                max_interval_sec=layer_dict.get("max_interval_sec", 0.0),
                density=layer_dict.get("density", 1.0),
                volume_drift_db=layer_dict.get("volume_drift_db", 0.0),
                pitch_drift_cents=layer_dict.get("pitch_drift_cents", 0.0),
                effects=effects,
                elevenlabs_prompt=layer_dict.get("elevenlabs_prompt"),
            ))

        master_fx = EffectsChain(**config_dict.get("master_effects", {}))
        energy = EnergyCurve(**config_dict.get("energy_curve", {}))

        return SoundscapeConfig(
            title=config_dict["title"],
            description=prompt,
            mood=config_dict["mood"],
            setting=config_dict["setting"],
            time_of_day=config_dict["time_of_day"],
            layers=layers,
            master_effects=master_fx,
            energy_curve=energy,
            target_loudness_lufs=config_dict.get("target_loudness_lufs", -18.0),
            duration_sec=duration_sec,
            root_key=config_dict.get("root_key", ""),
        )


class DiscoveryConversation:
    """
    Interactive conversation that refines a vague idea into a rich prompt.
    This is the Level 3 "discovery" phase — the LLM asks evocative questions
    to build a detailed intent before generating any audio.
    """

    DISCOVERY_SYSTEM = """You are a creative audio director helping someone design an
ambient soundscape. Your goal is to understand their vision deeply through 3-5 focused
questions. Ask about:

1. The physical space (indoor/outdoor, large/small, natural/urban)
2. The emotional quality (what feeling should dominate? what should it evoke?)
3. The listener's use case (sleep, focus, meditation, background for video?)
4. Temporal qualities (does it evolve? is there a narrative arc? time of day?)
5. Any specific sounds they love or hate

After gathering enough info, synthesize their answers into a single rich prompt paragraph
that captures the full vision. Prefix your final synthesis with "SYNTHESIS:" on its own line.

Be warm and collaborative. Use sensory language. Keep questions concise — one at a time."""

    def __init__(self, anthropic_api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.client = Anthropic(api_key=anthropic_api_key)
        self.model = model
        self.messages: list[dict] = []

    def start(self) -> str:
        """Begin the discovery conversation."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=300,
            system=self.DISCOVERY_SYSTEM,
            messages=[{"role": "user", "content": "I want to create a soundscape."}],
        )
        assistant_msg = response.content[0].text
        self.messages.append({"role": "user", "content": "I want to create a soundscape."})
        self.messages.append({"role": "assistant", "content": assistant_msg})
        return assistant_msg

    def respond(self, user_input: str) -> tuple[str, bool]:
        """
        Continue the conversation. Returns (response_text, is_complete).
        is_complete is True when the LLM has produced a final synthesis.
        """
        self.messages.append({"role": "user", "content": user_input})

        response = self.client.messages.create(
            model=self.model,
            max_tokens=500,
            system=self.DISCOVERY_SYSTEM,
            messages=self.messages,
        )

        assistant_msg = response.content[0].text
        self.messages.append({"role": "assistant", "content": assistant_msg})

        is_complete = "SYNTHESIS:" in assistant_msg
        return assistant_msg, is_complete

    def get_synthesis(self) -> str:
        """Extract the final synthesized prompt from the conversation."""
        for msg in reversed(self.messages):
            if msg["role"] == "assistant" and "SYNTHESIS:" in msg["content"]:
                return msg["content"].split("SYNTHESIS:")[-1].strip()
        raise ValueError("No synthesis found — conversation not complete")
