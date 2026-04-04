"""
test_engine.py — Isolated test for the audio engine.

Hardcodes a minimal SoundscapeConfig (3 layers, 30 seconds),
renders it, and exports to verify the audio engine works.

Run:
    python test_engine.py
"""

import os
import sys

from schemas import SoundscapeConfig, LayerConfig, LayerType, EffectsChain, EnergyCurve
from audio_engine import AudioEngine, SampleLibrary


def main():
    sample_path = "./samples"
    if not os.path.isdir(sample_path):
        print("Error: ./samples directory not found. Run bootstrap_samples.py first.")
        sys.exit(1)

    print("Loading sample library...")
    library = SampleLibrary(sample_path)
    print(f"  Available tags: {library.available_tags}")

    if not library.available_tags:
        print("Error: No samples found. Run bootstrap_samples.py first.")
        sys.exit(1)

    engine = AudioEngine(library)

    config = SoundscapeConfig(
        title="Test Soundscape",
        description="Engine test: rain + birds + water drip",
        mood="calm",
        setting="forest",
        time_of_day="evening",
        layers=[
            LayerConfig(
                name="Rain Base",
                layer_type=LayerType.BASE,
                sample_tags=["rain_light", "noise_pink"],
                volume_db=-8.0,
                pan=-0.2,
                loop=True,
                fade_in_sec=2.0,
                fade_out_sec=2.0,
                volume_drift_db=2.0,
                effects=EffectsChain(
                    reverb_amount=0.4,
                    reverb_room_size=0.6,
                    low_pass_hz=8000,
                ),
            ),
            LayerConfig(
                name="Birds",
                layer_type=LayerType.MID,
                sample_tags=["birds_morning", "birds_evening"],
                volume_db=-10.0,
                pan=0.3,
                pan_randomize=True,
                loop=False,
                min_interval_sec=5.0,
                max_interval_sec=15.0,
                density=0.7,
                fade_in_sec=0.5,
                fade_out_sec=0.5,
                effects=EffectsChain(reverb_amount=0.3, reverb_room_size=0.5),
            ),
            LayerConfig(
                name="Water Drips",
                layer_type=LayerType.DETAIL,
                sample_tags=["water_drip", "splash_small"],
                volume_db=-14.0,
                pan=0.0,
                pan_randomize=True,
                loop=False,
                min_interval_sec=3.0,
                max_interval_sec=10.0,
                density=0.5,
                fade_in_sec=0.1,
                fade_out_sec=0.1,
            ),
        ],
        master_effects=EffectsChain(
            reverb_amount=0.2,
            reverb_room_size=0.4,
            compression_threshold_db=-18.0,
            compression_ratio=2.0,
        ),
        energy_curve=EnergyCurve(style="steady"),
        target_loudness_lufs=-18.0,
        duration_sec=30.0,
    )

    print(f"\nRendering: {config.title} ({config.duration_sec:.0f}s)...")
    audio = engine.render(config)

    os.makedirs("output", exist_ok=True)
    output_path = "output/test_engine_output.wav"
    audio.export(output_path, format="wav")

    duration_sec = len(audio) / 1000.0
    dbfs = audio.dBFS

    print(f"\n✅ Rendered successfully!")
    print(f"   Output: {output_path}")
    print(f"   Duration: {duration_sec:.1f}s")
    print(f"   Level: {dbfs:.1f} dBFS")
    print(f"   Channels: {audio.channels}")
    print(f"   Sample rate: {audio.frame_rate} Hz")

    if dbfs < -60:
        print("   ⚠ WARNING: Audio level very low — may be near-silent")
    elif dbfs > -1:
        print("   ⚠ WARNING: Audio level very high — may be clipping")
    else:
        print("   ✓ Audio level looks reasonable")


if __name__ == "__main__":
    main()
