"""
audio_engine.py — Renders a SoundscapeConfig into actual audio.

Uses pydub for sample manipulation and layering, with pedalboard for
professional-quality effects processing. Implements the variation system
that makes soundscapes evolve over time rather than feeling like static loops.

Supports two sample sources:
  1. Generated audio paths (from ElevenLabs) — set on layer.generated_audio_path
  2. Static sample library (from samples/ folder) — fallback via sample_tags
"""

import os
import random
import math
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
from pydub import AudioSegment
from pydub.effects import low_pass_filter, high_pass_filter

from schemas import (
    SoundscapeConfig, LayerConfig, LayerType,
    EffectsChain, EnergyCurve, AudioFeatures, PartSnapshot,
)

# Optional: pedalboard for higher quality effects
try:
    import pedalboard as pb
    HAS_PEDALBOARD = True
except ImportError:
    HAS_PEDALBOARD = False

# Optional: librosa for audio feature extraction
try:
    import librosa
    HAS_LIBROSA = True
except ImportError:
    HAS_LIBROSA = False


SAMPLE_RATE = 44100


def make_loopable(audio: AudioSegment, crossfade_ms: int) -> AudioSegment:
    """
    Make an AudioSegment seamlessly loopable via equal-power crossfade.

    The audio must be LONGER than desired output by at least crossfade_ms.
    The tail is blended into the head, then trimmed to remove the extra.
    """
    if crossfade_ms <= 0 or len(audio) < crossfade_ms * 2:
        return audio

    samples = np.array(audio.get_array_of_samples(), dtype=np.float64)
    channels = audio.channels
    if channels == 2:
        samples = samples.reshape((-1, 2))

    crossfade_samples = int(crossfade_ms * audio.frame_rate / 1000)
    output_samples = len(samples) - crossfade_samples

    t = np.linspace(0, 1, crossfade_samples)
    fade_in = np.sqrt(t)
    fade_out = np.sqrt(1 - t)

    if channels == 2:
        fade_in = fade_in[:, np.newaxis]
        fade_out = fade_out[:, np.newaxis]

    head = samples[:crossfade_samples].copy()
    tail = samples[output_samples:].copy()

    blended = head * fade_in + tail * fade_out
    result = samples[:output_samples].copy()
    result[:crossfade_samples] = blended

    result = np.clip(result, -32768, 32767).astype(np.int16)
    if channels == 2:
        result = result.flatten()

    return audio._spawn(result.tobytes())[:int(output_samples / audio.frame_rate * 1000)]


class SampleLibrary:
    """
    Manages a folder of audio samples, indexed by tags.

    Expected folder structure:
        samples/
            base/
                rain_light.wav
                wind_low.wav
                pad_warm.wav
            mid/
                birds_morning.wav
                thunder_distant.wav
            detail/
                twig_snap.wav
                water_drip.wav
            musical/
                piano_gentle.wav

    Filenames (without extension) are used as tags.
    """

    def __init__(self, library_path: str):
        self.library_path = Path(library_path)
        self.samples: dict[str, AudioSegment] = {}
        self.tag_to_paths: dict[str, Path] = {}
        self._index()

    def _index(self):
        """Scan the library folder and build the tag index."""
        if not self.library_path.exists():
            return
        for category_dir in self.library_path.iterdir():
            if category_dir.is_dir():
                for audio_file in category_dir.iterdir():
                    if audio_file.suffix in ('.wav', '.mp3', '.ogg', '.flac'):
                        tag = audio_file.stem
                        self.tag_to_paths[tag] = audio_file

    def get(self, tag: str) -> Optional[AudioSegment]:
        """Load and cache a sample by tag."""
        if tag in self.samples:
            return self.samples[tag]
        if tag in self.tag_to_paths:
            self.samples[tag] = AudioSegment.from_file(str(self.tag_to_paths[tag]))
            return self.samples[tag]
        return None

    def find_best_match(self, tags: list[str]) -> Optional[AudioSegment]:
        """Return the first matching sample from a list of tag preferences."""
        for tag in tags:
            sample = self.get(tag)
            if sample is not None:
                return sample
        return None

    @property
    def available_tags(self) -> list[str]:
        return list(self.tag_to_paths.keys())


PITCH_CLASSES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

NOTE_TO_INDEX = {
    'C': 0, 'B#': 0,
    'C#': 1, 'Db': 1,
    'D': 2,
    'D#': 3, 'Eb': 3,
    'E': 4, 'Fb': 4,
    'F': 5, 'E#': 5,
    'F#': 6, 'Gb': 6,
    'G': 7,
    'G#': 8, 'Ab': 8,
    'A': 9,
    'A#': 10, 'Bb': 10,
    'B': 11, 'Cb': 11,
}

# Krumhansl-Kessler key profiles for major/minor detection
_MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
_MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def detect_key(audio_path: str, sample_rate: int = SAMPLE_RATE) -> tuple[int, str, float]:
    """
    Detect the musical key of an audio file using chroma analysis
    and Krumhansl-Kessler key profiles.

    Returns (pitch_class_index, key_name, confidence).
    confidence is the correlation coefficient (0-1); low values mean
    the audio is likely non-tonal (noise, texture).
    """
    if not HAS_LIBROSA:
        return 0, "C", 0.0

    y, sr = librosa.load(audio_path, sr=sample_rate, mono=True, duration=30.0)

    flatness = float(np.mean(librosa.feature.spectral_flatness(y=y)))
    if flatness > 0.4:
        return 0, "?", 0.0

    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    chroma_avg = np.mean(chroma, axis=1)

    best_corr = -1.0
    best_idx = 0
    best_mode = "major"

    for shift in range(12):
        rotated = np.roll(chroma_avg, -shift)
        maj_corr = float(np.corrcoef(rotated, _MAJOR_PROFILE)[0, 1])
        min_corr = float(np.corrcoef(rotated, _MINOR_PROFILE)[0, 1])

        if maj_corr > best_corr:
            best_corr = maj_corr
            best_idx = shift
            best_mode = "major"
        if min_corr > best_corr:
            best_corr = min_corr
            best_idx = shift
            best_mode = "minor"

    key_name = f"{PITCH_CLASSES[best_idx]} {best_mode}"
    return best_idx, key_name, best_corr


def harmonize_layers(config: SoundscapeConfig, cache_dir: str = "generated_samples"):
    """
    Detect keys of tonal layers and pitch-shift outliers to match the root key.

    If config.root_key is empty, auto-detects from the majority key of tonal layers.
    Only shifts layers with confident tonal detection (skips noise/texture layers).
    Saves shifted audio to separate files, preserving originals.
    """
    if not HAS_LIBROSA:
        print("  ⚠ librosa not installed, skipping harmonization")
        return

    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)

    layer_analysis = []

    for layer in config.layers:
        if not layer.generated_audio_path or not os.path.exists(layer.generated_audio_path):
            continue
        if layer.volume_db <= -55:
            continue

        key_idx, key_name, confidence = detect_key(layer.generated_audio_path)
        is_tonal = confidence > 0.3
        layer_analysis.append({
            "layer": layer,
            "key_idx": key_idx,
            "key_name": key_name,
            "confidence": confidence,
            "is_tonal": is_tonal,
        })
        status = f"🎵 {key_name} ({confidence:.2f})" if is_tonal else f"🌊 noise/texture ({confidence:.2f})"
        print(f"    Key detect: {layer.name} → {status}")

    tonal_layers = [a for a in layer_analysis if a["is_tonal"]]
    if not tonal_layers:
        print("    No tonal layers detected, skipping harmonization")
        return

    target_key_str = config.root_key.strip()
    if target_key_str:
        root_note = target_key_str.split()[0]
        target_idx = NOTE_TO_INDEX.get(root_note, None)
        if target_idx is None:
            print(f"    ⚠ Could not parse root_key '{target_key_str}', auto-detecting...")
            target_idx = None
    else:
        target_idx = None

    if target_idx is None:
        from collections import Counter
        key_counts = Counter(a["key_idx"] for a in tonal_layers)
        target_idx = key_counts.most_common(1)[0][0]
        detected_mode = "minor"
        for a in tonal_layers:
            if a["key_idx"] == target_idx and "major" in a["key_name"]:
                detected_mode = "major"
                break
        config.root_key = f"{PITCH_CLASSES[target_idx]} {detected_mode}"
        print(f"    Auto-detected root key: {config.root_key}")

    shifted_count = 0
    for analysis in tonal_layers:
        layer = analysis["layer"]
        detected_idx = analysis["key_idx"]

        semitone_diff = (target_idx - detected_idx) % 12
        if semitone_diff > 6:
            semitone_diff -= 12
        if semitone_diff == 0:
            print(f"    ✓ {layer.name} already in key ({analysis['key_name']})")
            continue

        direction = "up" if semitone_diff > 0 else "down"
        print(f"    ♻ Shifting {layer.name}: {analysis['key_name']} → {PITCH_CLASSES[target_idx]} "
              f"({semitone_diff:+d} semitones {direction})")

        try:
            y, sr = librosa.load(layer.generated_audio_path, sr=SAMPLE_RATE, mono=False)
            if y.ndim == 1:
                shifted = librosa.effects.pitch_shift(y=y, sr=sr, n_steps=semitone_diff)
            else:
                shifted = np.stack([
                    librosa.effects.pitch_shift(y=ch, sr=sr, n_steps=semitone_diff)
                    for ch in y
                ])

            harmonized_path = str(cache_path / f"{Path(layer.generated_audio_path).stem}_harm.wav")
            if shifted.ndim == 1:
                sf.write(harmonized_path, shifted, sr, subtype="PCM_16")
            else:
                sf.write(harmonized_path, shifted.T, sr, subtype="PCM_16")

            layer.generated_audio_path = harmonized_path
            shifted_count += 1

        except Exception as e:
            print(f"    ⚠ Pitch shift failed for {layer.name}: {e}")

    if shifted_count:
        print(f"    Harmonized {shifted_count} layer(s) to {config.root_key}")
    else:
        print(f"    All tonal layers already in {config.root_key}")


FREQ_SLOTS = {
    LayerType.BASE:    {"low_pass_hz": 10000, "high_pass_hz": 30},
    LayerType.MID:     {"low_pass_hz": 12000, "high_pass_hz": 80},
    LayerType.DETAIL:  {"low_pass_hz": 16000, "high_pass_hz": 400},
    # No automatic filtering on musical layers — let them use full spectrum
}

STEREO_POSITIONS = [0.0, -0.25, 0.25, -0.5, 0.5, -0.15, 0.15, -0.6, 0.6]


class AudioEngine:
    """
    Renders a SoundscapeConfig into a final audio file.

    The rendering pipeline:
    1. For each layer, load audio from generated_audio_path or sample library
    2. Build a timeline: where each sound plays, at what volume/pan
    3. Apply per-layer effects (with automatic frequency slotting)
    4. Mix all layers with gain staging
    5. Apply master effects
    6. Normalize to target loudness
    7. Export
    """

    def __init__(self, sample_library: Optional[SampleLibrary] = None):
        self.library = sample_library

    def _crossfade_ms_for_duration(self, config: SoundscapeConfig) -> int:
        """Pick crossfade length in ms, respecting config and duration constraints."""
        if not config.loopable:
            return 0
        cf = config.crossfade_seconds
        max_cf = config.duration_sec * 0.4
        return int(min(cf, max_cf) * 1000)

    def render(self, config: SoundscapeConfig) -> AudioSegment:
        """Render a complete soundscape from a config."""
        crossfade_ms = self._crossfade_ms_for_duration(config)
        render_ms = int(config.duration_sec * 1000) + crossfade_ms

        self._auto_stereo_spread(config)

        mix = AudioSegment.silent(duration=render_ms, frame_rate=SAMPLE_RATE)

        active_layers = [l for l in config.layers if l.volume_db > -55]
        gain_offset = self._gain_staging_offset(active_layers)

        layers_rendered = 0
        for layer_config in config.layers:
            layer_audio = self._render_layer(
                layer_config, render_ms, config.energy_curve,
                loopable=config.loopable, crossfade_ms=crossfade_ms,
                gain_offset=gain_offset,
            )
            if layer_audio is not None:
                layer_audio = self._apply_layer_timing(
                    layer_audio, layer_config, render_ms
                )
                mix = mix.overlay(layer_audio)
                layers_rendered += 1

        if layers_rendered == 0:
            print("  ⚠ WARNING: No layers produced audio! Output will be silent.")
            print(f"    Config has {len(config.layers)} layers:")
            for lc in config.layers:
                print(f"      - {lc.name}: path={lc.generated_audio_path}, tags={lc.sample_tags}")

        mix = self._apply_effects(mix, config.master_effects)
        mix = self._normalize(mix, config.target_loudness_lufs)

        if crossfade_ms > 0:
            mix = make_loopable(mix, crossfade_ms)

        return mix

    def _apply_layer_timing(
        self, audio: AudioSegment, layer: LayerConfig, total_ms: int
    ) -> AudioSegment:
        """If layer has start_sec/end_sec, silence the regions outside that window
        and apply 2-second fades at the entry/exit points."""
        start_ms = int(layer.start_sec * 1000)
        end_ms = int(layer.end_sec * 1000) if layer.end_sec > 0 else total_ms
        if start_ms <= 0 and end_ms >= total_ms:
            return audio
        FADE_MS = 2000
        active = audio[start_ms:end_ms]
        active = active.fade_in(min(FADE_MS, len(active) // 2))
        active = active.fade_out(min(FADE_MS, len(active) // 2))
        result = AudioSegment.silent(duration=start_ms, frame_rate=audio.frame_rate)
        result += active
        tail = total_ms - len(result)
        if tail > 0:
            result += AudioSegment.silent(duration=tail, frame_rate=audio.frame_rate)
        return result[:total_ms]

    def _auto_stereo_spread(self, config: SoundscapeConfig):
        """If all layers are centered (pan=0), auto-distribute across the stereo field."""
        active = [l for l in config.layers if l.volume_db > -55]
        if not active:
            return
        all_centered = all(abs(l.pan) < 0.05 for l in active)
        if not all_centered:
            return

        for i, layer in enumerate(active):
            if layer.layer_type == LayerType.BASE:
                layer.pan = 0.0
            else:
                pos_idx = (i % len(STEREO_POSITIONS))
                layer.pan = STEREO_POSITIONS[pos_idx]

    def _gain_staging_offset(self, active_layers: list) -> float:
        """Calculate gain reduction to prevent clipping when many layers sum together."""
        n = len(active_layers)
        if n <= 2:
            return 0.0
        if n <= 4:
            return -2.0
        if n <= 6:
            return -4.0
        return -6.0

    def render_preview(self, config: SoundscapeConfig, preview_sec: float = 30.0) -> AudioSegment:
        """
        Render a short preview segment.
        Inherits loopable setting from config so previews also loop-test cleanly.
        """
        preview_config = SoundscapeConfig(
            title=config.title,
            description=config.description,
            mood=config.mood,
            setting=config.setting,
            time_of_day=config.time_of_day,
            layers=config.layers,
            master_effects=config.master_effects,
            energy_curve=config.energy_curve,
            target_loudness_lufs=config.target_loudness_lufs,
            duration_sec=preview_sec,
            loopable=config.loopable,
            crossfade_seconds=min(config.crossfade_seconds, preview_sec * 0.3),
        )
        return self.render(preview_config)

    def _load_sample_for_layer(self, layer: LayerConfig) -> Optional[AudioSegment]:
        """Load audio for a layer — prefer generated path, fall back to library."""
        sample = None

        if layer.generated_audio_path and os.path.exists(layer.generated_audio_path):
            try:
                sample = AudioSegment.from_file(layer.generated_audio_path)
            except Exception as e:
                print(f"  ⚠ Failed to load generated audio for '{layer.name}': {e}")

        if sample is None and self.library:
            sample = self.library.find_best_match(layer.sample_tags)

        if sample is None:
            print(f"  ⚠ No audio found for layer '{layer.name}' "
                  f"(path: {layer.generated_audio_path}, tags: {layer.sample_tags})")
            return None

        if layer.pitch_shift_semitones != 0:
            sample = self._apply_pitch_shift(sample, layer.pitch_shift_semitones)

        return sample

    @staticmethod
    def _apply_pitch_shift(audio: AudioSegment, semitones: int) -> AudioSegment:
        """Fast pitch shift via resampling. Shifts pitch without changing duration noticeably
        for ambient content. Clamps to +/-12 semitones."""
        semitones = max(-12, min(12, semitones))
        if semitones == 0:
            return audio
        factor = 2 ** (semitones / 12.0)
        shifted = audio._spawn(
            audio.raw_data,
            overrides={"frame_rate": int(audio.frame_rate * factor)}
        ).set_frame_rate(audio.frame_rate)
        return shifted

    def _render_layer(
        self,
        layer: LayerConfig,
        duration_ms: int,
        energy_curve: EnergyCurve,
        loopable: bool = False,
        crossfade_ms: int = 0,
        gain_offset: float = 0.0,
    ) -> Optional[AudioSegment]:
        """Render a single layer across the full duration."""
        sample = self._load_sample_for_layer(layer)
        if sample is None:
            return None

        needs_tiling = len(sample) < duration_ms
        use_crossfaded_tiling = (
            loopable and needs_tiling and len(sample) > 2000
            and (layer.independent_loop or layer.layer_type == LayerType.MUSICAL)
        )

        if use_crossfaded_tiling:
            layer_audio = self._render_independent_loop_layer(
                sample, layer, duration_ms, energy_curve, crossfade_ms,
            )
        elif layer.loop or layer.layer_type in (LayerType.BASE, LayerType.MUSICAL):
            layer_audio = self._render_continuous_layer(
                sample, layer, duration_ms, energy_curve, skip_fades=loopable,
            )
        else:
            layer_audio = self._render_sparse_layer(sample, layer, duration_ms, energy_curve)

        layer_audio = self._apply_frequency_slot(layer_audio, layer)

        if layer.effects:
            layer_audio = self._apply_effects(layer_audio, layer.effects)

        if layer.swell_amount > 0.01:
            layer_audio = self._apply_swell(layer_audio, layer.swell_amount, layer.swell_period_sec)

        if gain_offset != 0.0:
            layer_audio = layer_audio + gain_offset

        return layer_audio

    def _apply_frequency_slot(self, audio: AudioSegment, layer: LayerConfig) -> AudioSegment:
        """Apply automatic frequency slotting based on layer type as a safety net.

        Only fills in missing EQ — won't override values explicitly set on the layer.
        """
        slot = FREQ_SLOTS.get(layer.layer_type)
        if not slot:
            return audio

        has_lp = layer.effects and layer.effects.low_pass_hz
        has_hp = layer.effects and layer.effects.high_pass_hz

        if not has_lp and slot.get("low_pass_hz"):
            audio = low_pass_filter(audio, int(slot["low_pass_hz"]))
        if not has_hp and slot.get("high_pass_hz"):
            audio = high_pass_filter(audio, int(slot["high_pass_hz"]))

        return audio

    def _render_continuous_layer(
        self,
        sample: AudioSegment,
        layer: LayerConfig,
        duration_ms: int,
        energy_curve: EnergyCurve,
        skip_fades: bool = False,
    ) -> AudioSegment:
        """Render a looping/continuous layer with volume drift and energy modulation."""
        loops_needed = math.ceil(duration_ms / len(sample)) + 1
        looped = sample * loops_needed
        looped = looped[:duration_ms]

        looped = looped + layer.volume_db

        if layer.volume_drift_db > 0:
            looped = self._apply_volume_drift(looped, layer.volume_drift_db)

        looped = self._apply_energy_curve(looped, energy_curve)

        pan_val = max(-1.0, min(1.0, layer.pan))
        if pan_val != 0.0:
            looped = looped.pan(pan_val)

        if not skip_fades:
            looped = looped.fade_in(int(layer.fade_in_sec * 1000))
            looped = looped.fade_out(int(layer.fade_out_sec * 1000))

        return looped

    def _render_independent_loop_layer(
        self,
        sample: AudioSegment,
        layer: LayerConfig,
        duration_ms: int,
        energy_curve: EnergyCurve,
        crossfade_ms: int,
    ) -> AudioSegment:
        """Render a layer that loops on its own cycle, already seamless."""
        sample_cf = min(crossfade_ms, int(len(sample) * 0.25))
        if sample_cf > 500:
            looped_sample = make_loopable(sample, sample_cf)
        else:
            looped_sample = sample

        loops_needed = math.ceil(duration_ms / len(looped_sample)) + 1
        tiled = looped_sample * loops_needed
        tiled = tiled[:duration_ms]

        tiled = tiled + layer.volume_db

        if layer.volume_drift_db > 0:
            tiled = self._apply_volume_drift(tiled, layer.volume_drift_db)

        tiled = self._apply_energy_curve(tiled, energy_curve)

        pan_val = max(-1.0, min(1.0, layer.pan))
        if pan_val != 0.0:
            tiled = tiled.pan(pan_val)

        return tiled

    def _render_sparse_layer(
        self,
        sample: AudioSegment,
        layer: LayerConfig,
        duration_ms: int,
        energy_curve: EnergyCurve,
    ) -> AudioSegment:
        """Render a layer with randomly-timed, sparse occurrences."""
        canvas = AudioSegment.silent(duration=duration_ms, frame_rate=SAMPLE_RATE)

        min_interval = layer.min_interval_sec * 1000
        max_interval = layer.max_interval_sec * 1000

        if max_interval <= 0:
            max_interval = 30000  # Default 30 sec max interval
        if min_interval <= 0:
            min_interval = 5000   # Default 5 sec min interval

        cursor_ms = int(random.uniform(min_interval * 0.5, max_interval * 0.5))

        while cursor_ms < duration_ms - len(sample):
            # Density check — skip some occurrences
            if random.random() > layer.density:
                cursor_ms += int(random.uniform(min_interval, max_interval))
                continue

            # Get energy at this point in time
            t_normalized = cursor_ms / duration_ms
            energy = self._get_energy_at(t_normalized, energy_curve)

            # Prepare this occurrence
            occurrence = sample + layer.volume_db

            # Volume variation
            if layer.volume_drift_db > 0:
                vol_offset = random.uniform(-layer.volume_drift_db, layer.volume_drift_db)
                occurrence = occurrence + vol_offset

            # Energy modulation (sparse sounds get quieter in low-energy sections)
            energy_mod = -12 * (1 - energy)  # Up to -12dB reduction
            occurrence = occurrence + energy_mod

            # Pitch variation (via speed change — rough but effective)
            if layer.pitch_drift_cents > 0:
                cents = random.uniform(-layer.pitch_drift_cents, layer.pitch_drift_cents)
                speed_factor = 2 ** (cents / 1200)
                occurrence = occurrence._spawn(
                    occurrence.raw_data,
                    overrides={"frame_rate": int(occurrence.frame_rate * speed_factor)}
                ).set_frame_rate(SAMPLE_RATE)

            # Panning
            if layer.pan_randomize:
                pan_val = random.uniform(-0.8, 0.8)
            else:
                pan_val = max(-1.0, min(1.0, layer.pan))
            if pan_val != 0:
                occurrence = occurrence.pan(pan_val)

            # Fade in/out
            fade_ms = min(int(layer.fade_in_sec * 1000), len(occurrence) // 3)
            occurrence = occurrence.fade_in(fade_ms).fade_out(fade_ms)

            # Place on canvas
            canvas = canvas.overlay(occurrence, position=cursor_ms)

            # Advance cursor
            cursor_ms += int(random.uniform(min_interval, max_interval))

        return canvas

    def _apply_volume_drift(self, audio: AudioSegment, drift_db: float) -> AudioSegment:
        """Apply slow, organic volume variation using chunked processing."""
        chunk_ms = 3000  # Modulate in 3-second chunks for smooth drift
        chunks = []
        drift_val = 0.0

        for i in range(0, len(audio), chunk_ms):
            chunk = audio[i:i + chunk_ms]
            # Random walk with mean reversion
            drift_val += random.gauss(0, drift_db * 0.3)
            drift_val *= 0.95  # Mean revert
            drift_val = max(-drift_db, min(drift_db, drift_val))
            chunk = chunk + drift_val
            chunks.append(chunk)

        return sum(chunks) if chunks else audio

    def _apply_energy_curve(self, audio: AudioSegment, curve: EnergyCurve) -> AudioSegment:
        """Modulate volume according to the energy curve over the full duration."""
        if curve.style == "steady":
            return audio

        chunk_ms = 5000
        chunks = []
        total_ms = len(audio)

        for i in range(0, total_ms, chunk_ms):
            chunk = audio[i:i + chunk_ms]
            t = i / total_ms
            energy = self._get_energy_at(t, curve)
            # Map energy to volume adjustment (-12dB to 0dB range)
            vol_adjust = -12 * (1 - energy)
            chunk = chunk + vol_adjust
            chunks.append(chunk)

        return sum(chunks) if chunks else audio

    def _get_energy_at(self, t: float, curve: EnergyCurve) -> float:
        """Get energy level (0.0-1.0) at normalized time position t."""
        if curve.style == "steady":
            return (curve.min_energy + curve.max_energy) / 2

        elif curve.style == "slow_build":
            raw = t ** 1.5
            return curve.min_energy + raw * (curve.max_energy - curve.min_energy)

        elif curve.style == "rise_and_fall":
            # Bell curve centered at peak_position
            raw = math.exp(-((t - curve.peak_position) ** 2) / 0.08)
            return curve.min_energy + raw * (curve.max_energy - curve.min_energy)

        elif curve.style == "wave":
            # Slow sine wave oscillation
            raw = (math.sin(t * 2 * math.pi * 2) + 1) / 2
            return curve.min_energy + raw * (curve.max_energy - curve.min_energy)

        return 0.7  # fallback

    def _apply_effects(self, audio: AudioSegment, effects: EffectsChain) -> AudioSegment:
        """Apply effects chain using pedalboard (preferred) or pydub fallbacks."""
        if HAS_PEDALBOARD:
            return self._apply_effects_pedalboard(audio, effects)
        else:
            return self._apply_effects_pydub(audio, effects)

    def _apply_effects_pedalboard(self, audio: AudioSegment, effects: EffectsChain) -> AudioSegment:
        """High-quality effects via Spotify's pedalboard library."""
        # Convert pydub → numpy
        samples = np.array(audio.get_array_of_samples(), dtype=np.float32)
        if audio.channels == 2:
            samples = samples.reshape((-1, 2)).T
        else:
            samples = samples.reshape((1, -1))
        samples = samples / (2**15)  # Normalize to -1.0 to 1.0

        # Build effects chain
        board = pb.Pedalboard()

        if effects.high_pass_hz:
            board.append(pb.HighpassFilter(cutoff_frequency_hz=effects.high_pass_hz))

        if effects.low_pass_hz:
            board.append(pb.LowpassFilter(cutoff_frequency_hz=effects.low_pass_hz))

        if effects.reverb_amount > 0:
            board.append(pb.Reverb(
                room_size=effects.reverb_room_size,
                wet_level=effects.reverb_amount,
                dry_level=1.0 - effects.reverb_amount * 0.5,
            ))

        if effects.compression_ratio > 1.0:
            board.append(pb.Compressor(
                threshold_db=effects.compression_threshold_db,
                ratio=effects.compression_ratio,
            ))

        # Process
        processed = board(samples, sample_rate=audio.frame_rate)

        # Convert back to pydub
        processed = (processed * (2**15)).astype(np.int16)
        if audio.channels == 2:
            processed = processed.T.flatten()
        else:
            processed = processed.flatten()

        return audio._spawn(processed.tobytes())

    def _apply_effects_pydub(self, audio: AudioSegment, effects: EffectsChain) -> AudioSegment:
        """Fallback effects using pydub (lower quality but no dependencies)."""
        if effects.low_pass_hz:
            audio = low_pass_filter(audio, effects.low_pass_hz)
        if effects.high_pass_hz:
            audio = high_pass_filter(audio, effects.high_pass_hz)
        return audio

    def _apply_swell(self, audio: AudioSegment, amount: float, period_sec: float) -> AudioSegment:
        """Apply slow sine-wave volume modulation for organic breathing movement.

        amount: 0.0 = no effect, 1.0 = full swell (up to -12 dB dip)
        period_sec: length of one full breathe cycle
        """
        amount = max(0.0, min(1.0, amount))
        period_sec = max(4.0, period_sec)
        max_dip_db = amount * 12.0

        samples = np.array(audio.get_array_of_samples(), dtype=np.float64)
        channels = audio.channels
        if channels > 1:
            samples = samples.reshape((-1, channels))
        num_frames = samples.shape[0] if channels > 1 else len(samples)

        t = np.linspace(0, num_frames / audio.frame_rate, num_frames, endpoint=False)
        phase_offset = np.random.uniform(0, 2 * np.pi)
        envelope_db = -max_dip_db * 0.5 * (1.0 - np.cos(2 * np.pi * t / period_sec + phase_offset))
        envelope_linear = 10.0 ** (envelope_db / 20.0)

        if channels > 1:
            envelope_linear = envelope_linear[:, np.newaxis]

        samples = samples * envelope_linear
        samples = np.clip(samples, -32768, 32767).astype(np.int16)

        return audio._spawn(samples.tobytes())

    def _normalize(self, audio: AudioSegment, target_lufs: float) -> AudioSegment:
        """Approximate loudness normalization. For true LUFS, use pyloudnorm."""
        current_dbfs = audio.dBFS
        adjustment = target_lufs - current_dbfs
        return audio + adjustment

    def render_part(self, base_config: SoundscapeConfig, part: PartSnapshot) -> AudioSegment:
        """
        Render a single Part by taking the base config and applying the part's
        layer state overrides (volume, pan, mute, effects). Uses cached samples.
        """
        import copy
        config = copy.deepcopy(base_config)
        config.duration_sec = part.duration_sec
        config.loopable = True

        for layer in config.layers:
            state = part.layer_states.get(layer.name)
            if state:
                if state.get("muted", False):
                    layer.volume_db = -60.0
                else:
                    layer.volume_db = state.get("volume_db", layer.volume_db)
                layer.pan = state.get("pan", layer.pan)
                layer.pitch_shift_semitones = state.get("pitch_shift_semitones", layer.pitch_shift_semitones)
                layer.swell_amount = state.get("swell_amount", layer.swell_amount)
                layer.swell_period_sec = state.get("swell_period_sec", layer.swell_period_sec)
                if layer.effects is None:
                    layer.effects = EffectsChain()
                layer.effects.reverb_amount = state.get("reverb_amount", layer.effects.reverb_amount)
                if state.get("low_pass_hz") is not None:
                    layer.effects.low_pass_hz = state["low_pass_hz"]

        for added in part.added_layers:
            config.layers.append(added)

        return self.render(config)

    def stitch_parts(
        self,
        base_config: SoundscapeConfig,
        parts: list[PartSnapshot],
        global_fade_in_sec: float = 20.0,
        global_fade_out_sec: float = 10.0,
    ) -> AudioSegment:
        """
        Render multiple Parts and crossfade-stitch them into one long track.
        Each part is rendered separately using cached samples, then joined.
        """
        if not parts:
            return AudioSegment.silent(duration=1000)

        rendered_parts = []
        for i, part in enumerate(parts):
            print(f"  Rendering part {i + 1}/{len(parts)}: '{part.name}' ({part.duration_sec / 60:.0f} min)...")
            rendered = self.render_part(base_config, part)
            rendered_parts.append(rendered)

        result = rendered_parts[0]
        for i in range(1, len(rendered_parts)):
            crossfade_ms = int(parts[i].fade_in_sec * 1000)
            crossfade_ms = min(crossfade_ms, len(result) // 4, len(rendered_parts[i]) // 4)
            crossfade_ms = max(crossfade_ms, 500)
            result = result.append(rendered_parts[i], crossfade=crossfade_ms)

        if global_fade_in_sec > 0:
            fade_ms = int(global_fade_in_sec * 1000)
            result = result.fade_in(min(fade_ms, len(result) // 4))

        if global_fade_out_sec > 0:
            fade_ms = int(global_fade_out_sec * 1000)
            result = result.fade_out(min(fade_ms, len(result) // 4))

        result = self._normalize(result, base_config.target_loudness_lufs)
        return result


def extract_features(audio_path: str) -> AudioFeatures:
    """
    Extract audio features from a rendered file for the critique loop.
    These features give the listening model concrete data to reason about.
    """
    if not HAS_LIBROSA:
        raise ImportError("librosa required for feature extraction: pip install librosa")

    y, sr = librosa.load(audio_path, sr=SAMPLE_RATE, mono=True)
    duration = librosa.get_duration(y=y, sr=sr)

    # Spectral centroid (brightness)
    centroid = librosa.feature.spectral_centroid(y=y, sr=sr)[0]

    # Frequency band energy distribution
    S = np.abs(librosa.stft(y))
    freqs = librosa.fft_frequencies(sr=sr)
    low_mask = freqs <= 250
    mid_mask = (freqs > 250) & (freqs <= 4000)
    high_mask = freqs > 4000
    total_energy = np.sum(S ** 2)
    low_ratio = np.sum(S[low_mask] ** 2) / total_energy if total_energy > 0 else 0
    mid_ratio = np.sum(S[mid_mask] ** 2) / total_energy if total_energy > 0 else 0
    high_ratio = np.sum(S[high_mask] ** 2) / total_energy if total_energy > 0 else 0

    # Dynamic range
    rms = librosa.feature.rms(y=y)[0]
    rms_db = librosa.amplitude_to_db(rms)
    dynamic_range = float(np.max(rms_db) - np.min(rms_db))

    # Silence ratio
    silence_threshold = np.percentile(rms, 10)
    silence_ratio = float(np.sum(rms < silence_threshold) / len(rms))

    # Onset density (busyness)
    onsets = librosa.onset.onset_detect(y=y, sr=sr)
    onset_density = len(onsets) / duration

    # Spectral flatness (noise-like vs tonal)
    flatness = librosa.feature.spectral_flatness(y=y)[0]

    # Loudness (approximate LUFS — use pyloudnorm for accurate)
    loudness_approx = float(20 * np.log10(np.sqrt(np.mean(y ** 2)) + 1e-10))

    return AudioFeatures(
        duration_sec=duration,
        loudness_lufs=loudness_approx,
        spectral_centroid_mean_hz=float(np.mean(centroid)),
        spectral_centroid_std_hz=float(np.std(centroid)),
        low_energy_ratio=float(low_ratio),
        mid_energy_ratio=float(mid_ratio),
        high_energy_ratio=float(high_ratio),
        dynamic_range_db=dynamic_range,
        silence_ratio=silence_ratio,
        onset_density_per_sec=onset_density,
        spectral_flatness_mean=float(np.mean(flatness)),
    )
