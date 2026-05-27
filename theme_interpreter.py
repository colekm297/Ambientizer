"""
theme_interpreter.py — Translates natural language prompts into SoundscapeConfig.

Uses Claude (or any LLM) to understand the emotional and physical semantics of a
scene description and map them to concrete audio parameters.
"""

import json
import random
import time
from pathlib import Path
from typing import Optional
from anthropic import Anthropic
from schemas import SoundscapeConfig, LayerConfig, LayerType, EffectsChain, EnergyCurve, GenerationMode
from retry_utils import retry_with_backoff, is_transient_api_error

INTERPRETER_LOG_DIR = Path("interpreter_logs")
INTERPRETER_LOG_DIR.mkdir(exist_ok=True)

MAJOR_KEYS = ["C major", "D major", "Eb major", "E major", "F major", "G major", "Ab major", "Bb major"]
MINOR_KEYS = ["C minor", "Eb minor", "F minor", "F# minor", "G minor", "Bb minor", "B minor"]


SYSTEM_PROMPT = """You are designing ambient SOUNDSCAPES for BACKGROUND LISTENING — audio that plays \
for hours on YouTube while people study, work, sleep, or relax.

THIS IS NOT A SONG. You are creating a soundscape — evolving textures and atmosphere, NOT tracks \
with verse/chorus/bridge structure. Think Brian Eno "Music for Airports", Stars of the Lid, \
Grouper, or field recordings blended with subtle tonal elements.

APPROACH — the user message specifies a "layer_plan" or a mode + approach:

A) LAYER PLAN PROVIDED:
   Follow the plan exactly. Each entry in the plan defines a layer you must output. \
   Use the plan's name, type, instruments, and prompt as your starting point. \
   Fill in all technical details (effects, volume, pan, etc.) and refine the prompt \
   to be maximally effective for the AI music generator. Do NOT add or remove layers.

B) NO PLAN — UNIFIED approach (musical mode):
   Create exactly 1 layer:
   MAIN MUSIC (type "musical"): One cohesive piece containing ALL instruments AND subtle \
   environmental atmosphere woven into the same generation. Do NOT add a separate atmosphere/SFX layer.

C) NO PLAN — MULTI-LAYER approach (musical mode):
   Create 3-4 musical layers. Each handles a different sonic role (harmonic bed, melodic lead, \
   textural pad). If you need environmental texture, use a quiet musical Background Pad layer — \
   NEVER type "base"/"mid"/"detail" (those produce choppy SFX loops). All layers share the same key.

D) NO PLAN — AMBIENT mode:
   2-3 SFX/environmental layers. You may include 1 subtle musical element (singing bowl, \
   soft pad) if it fits the scene.

SOUNDSCAPE PRINCIPLES (apply to ALL modes):
- Favor slow internal movement: elements enter and leave, density shifts, harmonic motion breathes
- Avoid catchy hooks, verse/chorus/bridge structure, beat drops, and pop song arcs
- Musical layers should stay beautiful and non-intrusive — background listening, not a performance
- Think "environment with gentle events" not "frozen wallpaper" or "radio single"

CRITICAL — KEY SELECTION:
The user message contains a REQUIRED KEY — you MUST use that exact key.

PROMPT QUALITY — most important part:
The "elevenlabs_prompt" drives the AI generator. \
If a LAYER PLAN or REFERENCE ANALYSIS provides elevenlabs_prompt values, use them VERBATIM. \
Do NOT rewrite, rephrase, merge, or "improve" prompts that are already provided. Copy them exactly. \
Only write NEW prompts when no prompt is provided for a layer. \
When writing new prompts: be rich and specific (250-500 chars), name instruments, tempo, key, mood. \
The music will be LOOPED — ending density must match the opening so it wraps cleanly. \
Do NOT ask for a fade-out, final cadence, or song ending.

For musical prompts, include a simple INTERNAL ARRANGEMENT across the full music length, e.g.: \
"0:00-1:30 core bed only; ~2:30 subtle shimmer enters for ~1 min; 3:00-4:00 slightly fuller harmonic motion; \
final 30-60s thin back toward opening texture for seamless loop." \
Scale the arc to the MUSIC LENGTH in the user message. 2-4 gentle events total — not a song structure.

Avoid stasis language: do NOT write "never-ending", "static", "stable sustained energy", \
"no discrete events", or "ambient wallpaper" in musical prompts.

BANNED WORDS in musical prompts: "drone", "freeform", "no tempo", "arrhythmic" \
(these produce formless noise).

EFFECTS:
  - Main music: no EQ filtering, moderate reverb
  - Background pad layers (if any): low_pass_hz 8000-10000, heavy reverb

VOLUME:
  Main music: -4 to -2 dB (foreground)
  Background pad layers: -18 to -14 dB (barely audible wash)

NEVER use layer_type "base", "mid", or "detail" in musical mode — they route to a short SFX \
generator that produces repetitive hits. Environmental texture belongs inside musical layers.

If a REFERENCE ANALYSIS is provided, blend its sonic character with the user's scene.

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
      "elevenlabs_prompt": "200-450 chars, rich and specific",
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
    "style": "slow_build|rise_and_fall|wave|steady",
    "peak_position": 0.55,
    "min_energy": 0.4,
    "max_energy": 1.0
  },
  "target_loudness_lufs": -16.0
}

Output ONLY valid JSON. No explanation, no markdown fences."""


_ATMOSPHERE_KEYWORDS = (
    "atmosphere", "ambient", "wind", "room tone", "environment", "space",
    "void", "hum", "drone bed", "background", "texture bed",
)

_DISCRETE_SFX_WORDS = (
    "occasional", "intermittent", "random", "creak", "crack",
    "drip", "drop", "hit", "tap", "knock", "footstep", "burst", "gust",
)


def _arrangement_hint(duration_sec: float) -> str:
    """Short arrangement guidance scaled to requested music length."""
    mins = max(0.5, duration_sec / 60)
    if mins >= 4:
        return (
            "Internal arc across the full length: establish core bed first; around one-third add a subtle "
            "new element or widen harmony for ~1 min; near two-thirds allow slightly fuller motion; "
            "final 30-60s return toward opening density for seamless loop. No verse/chorus, no drop, no fade-out."
        )
    if mins >= 2:
        return (
            "Gentle internal movement across the full length: core bed, one subtle added element mid-way, "
            "then return toward opening texture by the end for seamless loop. No verse/chorus, no fade-out."
        )
    return (
        "Mostly steady texture with one subtle internal shift mid-way, ending similar to the start for seamless loop."
    )


class ThemeInterpreter:
    """Converts natural language scene descriptions into SoundscapeConfig."""

    def __init__(self, anthropic_api_key: str, model: str = "claude-opus-4-7"):
        self.client = Anthropic(api_key=anthropic_api_key)
        self.model = model

    @staticmethod
    def _looks_like_atmosphere(layer: LayerConfig) -> bool:
        text = f"{layer.name} {layer.elevenlabs_prompt or ''}".lower()
        return any(k in text for k in _ATMOSPHERE_KEYWORDS)

    @staticmethod
    def _pad_prompt(prompt: str, root_key: str = "") -> str:
        key_bit = f" in {root_key}" if root_key else ""
        cleaned = prompt
        for word in _DISCRETE_SFX_WORDS:
            cleaned = cleaned.replace(word, "subtle")
        return (
            f"Soft sustained ambient pad{key_bit}: {cleaned}. "
            "Slowly evolving harmonic bed with subtle internal movement, seamless loop, no discrete hits."
        )[:450]

    def _convert_to_pad_layer(self, layer: LayerConfig, root_key: str = "") -> LayerConfig:
        return LayerConfig(
            name=layer.name,
            layer_type=LayerType.MUSICAL,
            sample_tags=layer.sample_tags or ["pad", "texture", "ambient"],
            volume_db=min(layer.volume_db, -14.0),
            pan=layer.pan,
            loop=True,
            fade_in_sec=max(layer.fade_in_sec, 4.0),
            fade_out_sec=0.0,
            independent_loop=True,
            effects=layer.effects or EffectsChain(reverb_amount=0.45, reverb_room_size=0.85, low_pass_hz=9000),
            elevenlabs_prompt=self._pad_prompt(layer.elevenlabs_prompt or layer.name, root_key),
        )

    def _finalize_layers(
        self,
        layers: list[LayerConfig],
        mode: GenerationMode,
        approach: str,
        root_key: str = "",
    ) -> list[LayerConfig]:
        """Merge choppy atmosphere SFX into music, or convert to sustained pads."""
        if not layers:
            return layers

        musical = [l for l in layers if l.layer_type == LayerType.MUSICAL]
        sfx_like = [l for l in layers if l.layer_type in (LayerType.BASE, LayerType.MID, LayerType.DETAIL)]

        if mode == GenerationMode.MUSICAL and approach == "unified" and musical and sfx_like:
            main = musical[0]
            atmo_bits = " ".join(
                (l.elevenlabs_prompt or l.name).strip(".") for l in sfx_like if (l.elevenlabs_prompt or l.name)
            )
            if atmo_bits:
                main.elevenlabs_prompt = (
                    f"{main.elevenlabs_prompt} "
                    f"Subtle integrated background atmosphere: {atmo_bits}. "
                    "Weave as a continuous environmental bed, not separate hits."
                )[:1000]
            return musical

        if mode == GenerationMode.MUSICAL and sfx_like:
            converted = []
            for layer in layers:
                if layer.layer_type in (LayerType.BASE, LayerType.MID, LayerType.DETAIL):
                    converted.append(self._convert_to_pad_layer(layer, root_key))
                else:
                    converted.append(layer)
            return converted

        for layer in layers:
            if layer.layer_type in (LayerType.BASE, LayerType.MID) and layer.loop:
                prompt = layer.elevenlabs_prompt or layer.name
                if not any(w in prompt.lower() for w in ("continuous", "steady", "seamless")):
                    layer.elevenlabs_prompt = (
                        f"{prompt}. Continuous steady environmental bed, no discrete hits or pulses, seamless loop."
                    )[:450]
                layer.independent_loop = True
        return layers

    def config_from_reference_direct(
        self,
        prompt: str,
        duration_sec: float,
        reference_analysis: dict,
        approach: str = "unified",
    ) -> SoundscapeConfig:
        """Build a config from Gemini reference prompts without Claude rewriting them."""
        mood_hint = "melancholic and contemplative"
        feel = reference_analysis.get("overall_feel") or ""
        if feel:
            mood_hint = feel[:120]

        recreate = reference_analysis.get("recreate_with", []) or []
        musical = [r for r in recreate if (r.get("layer_type") or "").lower() == "musical"]
        sfx = [r for r in recreate if (r.get("layer_type") or "").lower() != "musical"]

        layers: list[LayerConfig] = []
        if approach == "multilayer":
            selected_music = musical[:3]
        else:
            selected_music = musical

        if selected_music:
            direct_prompt = (reference_analysis.get("direct_elevenlabs_prompt") or "").strip()
            do_not = reference_analysis.get("do_not_include", []) or []
            if approach == "unified" and direct_prompt:
                avoid = f" Avoid: {', '.join(str(x) for x in do_not[:10])}." if do_not else ""
                music_prompt = (direct_prompt + avoid)[:900]
                music_name = "Complete Reference Arrangement"
            elif approach == "unified" and len(musical) > 1:
                prompts = [r.get("elevenlabs_prompt", "") for r in musical if r.get("elevenlabs_prompt")]
                music_prompt = (
                    "Complete ambient arrangement containing all of these clearly audible elements: "
                    + " ".join(prompts)
                )[:900]
                music_name = "Complete Reference Arrangement"
            else:
                music_prompt = selected_music[0].get("elevenlabs_prompt", "")
                music_name = selected_music[0].get("layer_name", "Complete Reference Arrangement")

            layers.append(LayerConfig(
                name=music_name,
                layer_type=LayerType.MUSICAL,
                sample_tags=["reference", "ambient", "music"],
                volume_db=-3.0,
                pan=0.0,
                loop=True,
                fade_in_sec=5.0,
                fade_out_sec=0.0,
                effects=EffectsChain(reverb_amount=0.35, reverb_room_size=0.75),
                elevenlabs_prompt=(
                    f"{music_prompt}. Layered instrumental ambient arrangement with gentle internal movement. "
                    f"{_arrangement_hint(duration_sec)} No vocals, no drums, no beat drop."
                )[:1000],
            ))

            if approach == "multilayer":
                for r in selected_music[1:]:
                    layers.append(LayerConfig(
                        name=r.get("layer_name", "Reference Musical Layer"),
                        layer_type=LayerType.MUSICAL,
                        sample_tags=["reference", "ambient", "music"],
                        volume_db=-9.0,
                        pan=0.0,
                        loop=True,
                        fade_in_sec=5.0,
                        fade_out_sec=0.0,
                        effects=EffectsChain(reverb_amount=0.3, reverb_room_size=0.7),
                        elevenlabs_prompt=(
                            f"{r.get('elevenlabs_prompt', '')}. Supporting ambient layer with subtle motion. "
                            "Loop-friendly ending, no fade-out."
                        )[:1000],
                    ))

        if sfx:
            r = sfx[0]
            if approach == "unified" and layers:
                atmo = r.get("elevenlabs_prompt", "")
                if atmo:
                    layers[0].elevenlabs_prompt = (
                        f"{layers[0].elevenlabs_prompt} "
                        f"Subtle integrated background atmosphere: {atmo}. "
                        "Weave as a continuous environmental bed, not separate hits."
                    )[:1000]
            else:
                pad = LayerConfig(
                    name=r.get("layer_name", "Reference Atmosphere"),
                    layer_type=LayerType.MUSICAL,
                    sample_tags=["reference", "atmosphere", "pad"],
                    volume_db=-16.0,
                    pan=0.0,
                    loop=True,
                    fade_in_sec=4.0,
                    fade_out_sec=0.0,
                    independent_loop=True,
                    effects=EffectsChain(reverb_amount=0.35, reverb_room_size=0.75, low_pass_hz=9000),
                    elevenlabs_prompt=self._pad_prompt(r.get("elevenlabs_prompt", r.get("layer_name", "Atmosphere"))),
                )
                layers.append(pad)

        if not layers:
            layers.append(LayerConfig(
                name="Reference-Inspired Music Bed",
                layer_type=LayerType.MUSICAL,
                sample_tags=["ambient", "music"],
                volume_db=-3.0,
                loop=True,
                fade_out_sec=0.0,
                effects=EffectsChain(reverb_amount=0.35, reverb_room_size=0.75),
                elevenlabs_prompt=(
                    f"{feel or prompt}. {_arrangement_hint(duration_sec)} "
                    "No vocals, no drums, no fade-out ending."
                )[:1000],
            ))

        return SoundscapeConfig(
            title="Reference Direct Soundscape",
            description=prompt,
            mood=mood_hint,
            setting="reference-inspired atmosphere",
            time_of_day="",
            root_key="",
            layers=layers,
            master_effects=EffectsChain(reverb_amount=0.2, reverb_room_size=0.5, high_pass_hz=30, low_pass_hz=16000),
            energy_curve=EnergyCurve(style="slow_build", peak_position=0.6, min_energy=0.45, max_energy=0.8),
            target_loudness_lufs=-16.0,
            duration_sec=duration_sec,
        )

    def build_user_message(
        self,
        prompt: str,
        mode: str,
        reference_analysis: Optional[dict],
        layer_plan: Optional[list] = None,
        approach: str = "unified",
        duration_sec: float = 300.0,
    ) -> str:
        msg = f"USER REQUEST: {prompt}\nMODE: {mode}\nAPPROACH: {approach}\n"
        msg += f"MUSIC LENGTH: {duration_sec / 60:.1f} minutes — musical prompts should include a gentle internal arc scaled to this length.\n"

        if layer_plan:
            msg += f"""
LAYER PLAN (user-approved — follow this exactly):
{json.dumps(layer_plan, indent=2)}

Use each entry as a layer in your output. Match the name, type, and instruments. \
Use the prompt_preview EXACTLY as the elevenlabs_prompt — do NOT rewrite or rephrase it. \
Copy it verbatim. Do NOT add or remove layers.
"""

        if reference_analysis:
            recreate = reference_analysis.get('recreate_with', [])
            msg += f"""
REFERENCE ANALYSIS (from a YouTube video the user likes):
Overall feel: {reference_analysis.get('overall_feel', 'N/A')}

Layer blueprints from the reference:
{json.dumps(recreate, indent=2)}

Mix character: {json.dumps(reference_analysis.get('mix_qualities', {}))}

BLENDING RULES:
- The reference tells you WHAT KINDS of sounds to use (instruments, textures, mix style).
- The user's prompt tells you the SCENE and SETTING.
- Use the elevenlabs_prompt values from the reference layer blueprints EXACTLY as written — do NOT rewrite or rephrase them. Copy them verbatim into your layers.
- If the reference has "musical" layers, keep them musical in your config.
"""

        mood_hint = prompt.lower()
        use_minor = any(w in mood_hint for w in [
            "melanchol", "dark", "tense", "lonely", "mysterious", "somber",
            "sad", "eerie", "haunting", "noir", "gloomy",
        ])
        suggested_key = random.choice(MINOR_KEYS if use_minor else MAJOR_KEYS)
        msg += f"\nREQUIRED KEY: {suggested_key}\nYou MUST set root_key to \"{suggested_key}\" and write all musical layer prompts in this key.\n"
        msg += "\nGenerate the SoundscapeConfig JSON."
        return msg

    @retry_with_backoff(max_retries=3, base_delay=2.0, retryable_check=is_transient_api_error)
    def _call_claude(self, user_message: str) -> str:
        """Call Claude with retry logic; returns raw response text."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text

    def interpret(
        self,
        prompt: str,
        duration_sec: float = 300.0,
        mode: GenerationMode = GenerationMode.AMBIENT,
        reference_analysis: Optional[dict] = None,
        layer_plan: Optional[list] = None,
        approach: str = "unified",
    ) -> SoundscapeConfig:
        """
        Take a user's natural language prompt and return a structured SoundscapeConfig.

        Args:
            prompt: Natural language description like "rainy Tokyo alley at 2am"
            duration_sec: Target duration for the soundscape
            mode: AMBIENT (pure environment) or MUSICAL (ambient music + environment)
            reference_analysis: Optional raw analysis dict from ReferenceAnalyzer
            layer_plan: Optional list of layer dicts from the Enhance & Plan step
            approach: 'unified' or 'multi-layer' (musical mode only)

        Returns:
            SoundscapeConfig ready to be rendered by the audio engine
        """
        user_message = self.build_user_message(
            prompt, mode.value, reference_analysis, layer_plan, approach, duration_sec
        )

        log_entry = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "prompt": prompt,
            "mode": mode.value,
            "approach": approach,
            "has_reference": reference_analysis is not None,
            "has_layer_plan": bool(layer_plan),
            "layer_plan_summary": [p.get("name", "?") for p in (layer_plan or [])],
            "reference_summary": reference_analysis.get("overall_feel", "") if reference_analysis else "",
            "reference_layers": [
                r.get("layer_name", "?") for r in (reference_analysis or {}).get("recreate_with", [])
            ],
            "full_message_to_claude": user_message,
        }

        raw_json = self._call_claude(user_message)
        log_entry["raw_claude_response"] = raw_json

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
            raw_json = self._call_claude(
                f"USER REQUEST: {prompt}\nMODE: {mode.value}\n\n"
                "IMPORTANT: Keep elevenlabs_prompt values under 100 characters each. "
                "Use 4 layers maximum. Output ONLY valid JSON, no markdown fences."
            )
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

        root_key = config_dict.get("root_key", "")
        layers = self._finalize_layers(layers, mode, approach, root_key)

        master_fx = EffectsChain(**config_dict.get("master_effects", {}))
        energy_data = config_dict.get("energy_curve", {})
        if mode == GenerationMode.MUSICAL and energy_data.get("style", "steady") == "steady":
            energy_data = {**energy_data, "style": "slow_build"}
        energy = EnergyCurve(**energy_data)

        config = SoundscapeConfig(
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

        log_entry["output_title"] = config.title
        log_entry["output_key"] = config.root_key
        log_entry["output_mood"] = config.mood
        log_entry["output_layers"] = [
            {
                "name": l.name,
                "type": l.layer_type.value,
                "volume_db": l.volume_db,
                "elevenlabs_prompt": l.elevenlabs_prompt or "",
            }
            for l in config.layers
        ]
        try:
            ts = time.strftime("%Y%m%d_%H%M%S")
            safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in config.title)[:40]
            log_path = INTERPRETER_LOG_DIR / f"{ts}_{safe_title}.json"
            log_path.write_text(json.dumps(log_entry, indent=2, ensure_ascii=False))
            print(f"   📋 Interpreter log saved: {log_path}")
        except Exception as e:
            print(f"   ⚠ Failed to save interpreter log: {e}")

        return config


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

    def __init__(self, anthropic_api_key: str, model: str = "claude-opus-4-7"):
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
