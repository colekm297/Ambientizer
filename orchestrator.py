"""
orchestrator.py — The main pipeline that ties everything together.

Single-pass generation:
1. (Optional) Analyze YouTube reference via Gemini
2. Theme interpretation (prompt -> config with elevenlabs_prompts)
3. Audio generation (ElevenLabs SFX v2 for each layer)
4. Audio rendering (config + generated samples -> .wav)
5. Mix/master the final output (EQ, compression, limiting, LUFS normalization)

The critique loop is gone. Users refine the mix via the web UI's
feedback chat, which calls FeedbackAdjuster directly.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Callable

from dotenv import load_dotenv

from schemas import SoundscapeConfig, GenerationMode, LayerType, LayerConfig, EffectsChain
from theme_interpreter import ThemeInterpreter, DiscoveryConversation
from audio_engine import AudioEngine, SampleLibrary
from sample_generator import ElevenLabsSampleGenerator
from mix_master import MixMasterAgent
from reference_analyzer import ReferenceAnalyzer


StatusCallback = Callable[[str, str, dict], None]


@dataclass
class GenerationResult:
    """Complete record of a soundscape generation run."""
    prompt: str
    final_config: SoundscapeConfig
    output_path: str
    raw_output_path: str
    timestamp: str


class SoundscapeOrchestrator:
    """
    Main orchestrator for LLM-driven soundscape generation.

    Usage:
        agent = SoundscapeOrchestrator(
            anthropic_api_key="sk-...",
            gemini_api_key="...",
            elevenlabs_api_key="...",
        )
        result = agent.generate("cozy rainy cafe at midnight", duration_minutes=5)
    """

    def __init__(
        self,
        anthropic_api_key: str,
        gemini_api_key: Optional[str] = None,
        elevenlabs_api_key: Optional[str] = None,
        sample_library_path: str = "./samples",
        output_dir: str = "./output",
        use_cache: bool = True,
        mastering: bool = True,
    ):
        self.anthropic_key = anthropic_api_key
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.use_cache = use_cache
        self.mastering = mastering
        self._on_status: Optional[StatusCallback] = None

        self.interpreter = ThemeInterpreter(anthropic_api_key)
        self.mix_master = MixMasterAgent(anthropic_api_key) if mastering else None

        library = None
        if os.path.isdir(sample_library_path):
            library = SampleLibrary(sample_library_path)
        self.engine = AudioEngine(library)

        if not elevenlabs_api_key:
            elevenlabs_api_key = os.environ.get("ELEVENLABS_API_KEY")
        if elevenlabs_api_key:
            self.generator = ElevenLabsSampleGenerator(api_key=elevenlabs_api_key)
        else:
            print("Warning: No ELEVENLABS_API_KEY provided. Will fall back to static sample library.")
            self.generator = None

        if not gemini_api_key:
            gemini_api_key = os.environ.get("GEMINI_API_KEY")
        self.reference_analyzer = ReferenceAnalyzer(gemini_api_key) if gemini_api_key else None

    def _status(self, stage: str, message: str, data: dict = None):
        """Print a status message and forward to the callback if set."""
        print(message)
        if self._on_status:
            self._on_status(stage, message, data or {})

    def _generate_layer_audio(self, config: SoundscapeConfig):
        """Generate audio for layers that don't have a cached file yet."""
        if not self.generator:
            return

        for layer in config.layers:
            if layer.layer_type == LayerType.MUSICAL:
                setattr(layer, "music_generation_mode", getattr(config, "music_generation_mode", "text"))
                setattr(layer, "composition_plan", getattr(config, "composition_plan", None))

        layers_to_generate = [
            layer for layer in config.layers
            if not layer.generated_audio_path or not os.path.exists(layer.generated_audio_path)
        ]

        if not layers_to_generate:
            return

        # Clear any warnings from a prior generation so we only surface this run's.
        if self.generator:
            self.generator.warnings = []

        # Pre-flight: estimate total cost for ALL layers and check once upfront
        # so we don't burn real credits on early layers only to fail on later ones.
        if self.generator:
            total_est = 0
            for layer in layers_to_generate:
                dur = self.generator._get_duration(
                    layer.layer_type, config.duration_sec, config.music_length_sec
                )
                cr = 30 if layer.layer_type == LayerType.MUSICAL else 20
                total_est += dur * cr
            self.generator._check_spend_limit(total_est)
            self.generator.check_real_balance(total_est)

        self._status("generating_samples",
                      f"\n   Generating {len(layers_to_generate)} layer(s) via ElevenLabs...",
                      {"count": len(layers_to_generate)})

        for layer in layers_to_generate:
            path = self.generator.generate_layer_audio(
                layer=layer,
                mood=config.mood,
                setting=config.setting,
                use_cache=self.use_cache,
                root_key=config.root_key,
                track_duration_sec=config.duration_sec,
                music_length_sec=config.music_length_sec,
            )
            if path:
                layer.generated_audio_path = path

        # Surface quality warnings (ToS rewrite, composition-plan fallback, lossy
        # MP3) so the UI shows what silently changed instead of burying it in logs.
        warnings = list(getattr(self.generator, "warnings", []) or [])
        if warnings:
            for w in warnings:
                self._status("quality_warning", f"   ⚠ {w}", {"warning": w})
            self._status("quality_warning",
                         f"   ⚠ {len(warnings)} quality warning(s) — see above.",
                         {"warnings": warnings})

    def _passthrough_config(self, prompt: str, duration_sec: float) -> SoundscapeConfig:
        """Build a minimal config that sends the user's prompt to ElevenLabs VERBATIM
        — no LLM interpretation, no arrangement authoring, no rewriting. One musical
        layer carrying the raw prompt; downstream key-detection/harmonize/loop still
        apply (those are not part of the interpreter)."""
        title = (prompt.strip().split("\n")[0][:48] or "Raw soundscape").strip()
        layer = LayerConfig(
            name="Raw prompt",
            layer_type=LayerType.MUSICAL,
            sample_tags=[],
            volume_db=-3.0,
            pan=0.0,
            loop=True,
            fade_in_sec=4.0,
            fade_out_sec=0.0,
            elevenlabs_prompt=prompt,              # ← verbatim, untouched
            effects=EffectsChain(reverb_amount=0.3, reverb_room_size=0.5),
        )
        return SoundscapeConfig(
            title=title,
            description=prompt,
            mood="", setting="", time_of_day="",
            layers=[layer],
            duration_sec=duration_sec,
            root_key="",                            # no forced key
        )

    def generate(
        self,
        prompt: str,
        duration_minutes: float = 5.0,
        on_status: Optional[StatusCallback] = None,
        mode: GenerationMode = GenerationMode.AMBIENT,
        reference_url: Optional[str] = None,
        reference_analysis: Optional[dict] = None,
        planner_mode: str = "claude",
        music_generation_mode: str = "text",
        loopable: bool = True,
        layer_plan: Optional[list] = None,
        approach: str = "unified",
        ref_start_sec: int = 0,
        ref_end_sec: int = 600,
        music_length_minutes: float = 0,
        composition_plan: Optional[dict] = None,
    ) -> GenerationResult:
        """
        Generate a soundscape from a natural language prompt.

        Single-pass pipeline: interpret -> generate samples -> render -> master -> done.
        """
        self._on_status = on_status
        duration_sec = duration_minutes * 60

        self._status("interpreting", f"\n{'='*60}")
        self._status("interpreting", f"Generating: {prompt}")
        self._status("interpreting", f"   Duration: {duration_minutes:.1f} min | Mode: {mode.value}")
        self._status("interpreting",
                      f"   Audio: {'ElevenLabs SFX v2' if self.generator else 'Static sample library'}")
        self._status("interpreting",
                      f"   Mastering: {'Enabled' if self.mastering else 'Disabled'}")
        if reference_url:
            self._status("interpreting", f"   Reference: {reference_url}")
        self._status("interpreting", f"{'='*60}\n")

        # Step 0: Analyze reference (if provided). If the UI already ran the
        # preview analysis, reuse it so generation is consistent and cheaper.
        if reference_analysis and "_error" not in reference_analysis:
            n_layers = len(reference_analysis.get("layers", []))
            self._status("analyzing_reference",
                         f"Using reviewed reference analysis ({n_layers} layers)",
                         {"layers": n_layers, "cached": True})
        elif reference_url and self.reference_analyzer:
            self._status("analyzing_reference",
                         f"Analyzing YouTube reference ({ref_start_sec}s - {ref_end_sec}s)...")
            reference_analysis = self.reference_analyzer.analyze(
                reference_url, start_sec=ref_start_sec, end_sec=ref_end_sec)
            if reference_analysis and "_error" not in reference_analysis:
                n_layers = len(reference_analysis.get("layers", []))
                self._status("analyzing_reference",
                             f"   Reference analyzed: {n_layers} layers identified",
                             {"layers": n_layers})
            else:
                err_reason = (reference_analysis or {}).get("_error", "unknown")
                self._status("analyzing_reference",
                             f"   Reference analysis failed: {err_reason}. Continuing without it.")
                reference_analysis = None

        # Step 1: Interpret the prompt
        self._status("interpreting", "Step 1: Interpreting prompt...")
        if planner_mode == "raw":
            # RAW passthrough: NO interpretation. The typed prompt is sent to
            # ElevenLabs verbatim as a single musical layer. Lets you A/B exactly
            # what the model does with your words vs. the interpreted version.
            self._status("interpreting",
                         "   RAW MODE — prompt sent verbatim, theme interpreter bypassed")
            config = self._passthrough_config(prompt, duration_sec)
        elif planner_mode == "reference_direct":
            if not reference_analysis:
                raise ValueError("Reference Direct planner requires a successful reference analysis")
            config = self.interpreter.config_from_reference_direct(
                prompt=prompt,
                duration_sec=duration_sec,
                reference_analysis=reference_analysis,
                approach=approach,
            )
        else:
            config = self.interpreter.interpret(
                prompt,
                duration_sec=duration_sec,
                mode=mode,
                reference_analysis=reference_analysis,
                layer_plan=layer_plan,
                approach=approach,
            )
        self._status("interpreting",
                      f"   -> {config.title} ({len(config.layers)} layers, mood: {config.mood})",
                      {"title": config.title, "layers": len(config.layers), "mood": config.mood})

        if music_length_minutes > 0:
            config.music_length_sec = music_length_minutes * 60

        config.music_generation_mode = music_generation_mode
        config.composition_plan = composition_plan
        config.loopable = loopable
        if loopable:
            if duration_minutes < 2:
                config.crossfade_seconds = 8.0
            elif duration_minutes <= 10:
                config.crossfade_seconds = 15.0
            else:
                config.crossfade_seconds = 25.0

        # Step 2: Generate audio for all layers
        self._status("generating_samples", "\nStep 2: Generating layer audio...")
        self._generate_layer_audio(config)

        # Step 3: Render (flat mix — matches LiveMixer output)
        self._status("rendering", f"\nStep 3: Rendering ({duration_minutes:.1f} min)...")
        final_audio = self.engine.render_flat(config)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = "".join(c if c.isalnum() or c in " -_" else "" for c in config.title)
        raw_filename = f"{timestamp}_{safe_title}_raw.wav"
        raw_output_path = str(self.output_dir / raw_filename)
        final_audio.export(raw_output_path, format="wav")
        self._status("rendering", f"   Raw mix saved: {raw_output_path}")

        # Step 4: Mix/Master
        mastered_path = None
        if self.mix_master:
            self._status("mastering", "\nStep 4: Mastering...")
            try:
                mastered_path = self.mix_master.process(raw_output_path, config)
                self._status("mastering", f"   Mastered output: {mastered_path}")
            except Exception as e:
                self._status("error", f"   Mastering failed: {e}. Using raw mix.")

        output_path = mastered_path or raw_output_path

        self._status("complete",
                      f"\nDone! Saved to: {output_path}",
                      {"output_path": output_path, "raw_output_path": raw_output_path})

        self._on_status = None

        return GenerationResult(
            prompt=prompt,
            final_config=config,
            output_path=output_path,
            raw_output_path=raw_output_path,
            timestamp=timestamp,
        )

    def generate_interactive(self, duration_minutes: float = 5.0) -> GenerationResult:
        """Run discovery conversation first, then generate."""
        print("\nStarting discovery conversation...\n")
        discovery = DiscoveryConversation(self.anthropic_key)

        opening = discovery.start()
        print(f"Claude: {opening}\n")

        while True:
            user_input = input("You: ").strip()
            if not user_input:
                continue
            response, is_complete = discovery.respond(user_input)
            print(f"\nClaude: {response}\n")
            if is_complete:
                break

        synthesis = discovery.get_synthesis()
        print(f"\nSynthesized intent: {synthesis}\n")
        return self.generate(synthesis, duration_minutes=duration_minutes)


def main():
    """CLI entry point for the soundscape agent."""
    import argparse

    load_dotenv()

    parser = argparse.ArgumentParser(description="LLM-powered ambient soundscape generator")
    parser.add_argument("prompt", nargs="?", help="Soundscape description")
    parser.add_argument("--interactive", "-i", action="store_true", help="Use discovery conversation")
    parser.add_argument("--duration", "-d", type=float, default=5.0, help="Duration in minutes")
    parser.add_argument("--samples", "-s", default="./samples", help="Path to sample library (fallback)")
    parser.add_argument("--no-cache", action="store_true", help="Force regeneration of ElevenLabs samples")
    parser.add_argument("--no-master", action="store_true", help="Skip mix/mastering step")
    parser.add_argument("--mode", "-m", default="ambient", choices=["ambient", "musical"],
                        help="Mode: ambient (default) or musical")
    parser.add_argument("--reference", "-r", default=None, help="YouTube reference URL for style guidance")
    parser.add_argument("--output", "-o", default="./output", help="Output directory")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable required")
        return

    agent = SoundscapeOrchestrator(
        anthropic_api_key=api_key,
        gemini_api_key=os.environ.get("GEMINI_API_KEY"),
        elevenlabs_api_key=os.environ.get("ELEVENLABS_API_KEY"),
        sample_library_path=args.samples,
        output_dir=args.output,
        use_cache=not args.no_cache,
        mastering=not args.no_master,
    )

    if args.interactive:
        result = agent.generate_interactive(duration_minutes=args.duration)
    else:
        if not args.prompt:
            print("Error: provide a prompt or use --interactive")
            return
        gen_mode = GenerationMode(args.mode)
        result = agent.generate(
            args.prompt,
            duration_minutes=args.duration,
            mode=gen_mode,
            reference_url=args.reference,
        )


if __name__ == "__main__":
    main()
