"""
mix_master.py — Professional mixing and mastering for assembled soundscapes.

After the AudioEngine assembles all layers into a raw mix and the critique loop
settles on a good config, the MixMasterAgent analyzes the audio and applies
professional DSP processing to create a polished final output.

Pipeline:
  1. librosa + pyloudnorm analyze the raw mix
  2. Claude (as a mastering engineer) prescribes a processing chain
  3. pedalboard applies the chain (EQ, compression, limiting)
  4. pyloudnorm normalizes to target LUFS
"""

import json
import os
from pathlib import Path

import numpy as np
import soundfile as sf
import pyloudnorm as pyln

import pedalboard as pb

from anthropic import Anthropic
from schemas import SoundscapeConfig

try:
    import librosa
    HAS_LIBROSA = True
except ImportError:
    HAS_LIBROSA = False


MASTERING_SYSTEM = """You are a professional mastering engineer specializing in ambient music and
soundscapes designed for extended listening (study, sleep, work, relaxation).

Your priorities for this genre:
1. WARMTH: Gentle roll-off above 10kHz, slight low-shelf boost around 60-80Hz
2. NON-FATIGUING: No harsh frequencies in the 2-5kHz presence region. If anything,
   gently scoop this area. Listeners will have this on for hours.
3. CONSISTENT DYNAMICS: Gentle compression to keep the level steady. No sudden
   loud moments. Target a narrow dynamic range (6-10dB) for background listening.
4. STEREO DEPTH: Wide but not exaggerated. Bass should be mono below 120Hz.
5. LOUDNESS: Target -14 LUFS for YouTube/Spotify. Use limiting gently —
   never more than 2dB of gain reduction on the limiter.
6. CLEAN LOW END: High-pass everything below 30Hz (subsonic rumble removal).
   Keep the bass warm but controlled.

Given the audio analysis data and intended mood/setting, prescribe specific processing
parameters. Be conservative — it's better to under-process than over-process ambient music.

Output ONLY valid JSON matching this schema:
{
    "eq_bands": [
        {"freq_hz": 80, "gain_db": 2.0, "q": 0.7, "type": "low_shelf"},
        {"freq_hz": 250, "gain_db": -1.5, "q": 1.4, "type": "peak"},
        {"freq_hz": 3000, "gain_db": -1.0, "q": 0.8, "type": "peak"},
        {"freq_hz": 10000, "gain_db": -1.5, "q": 0.7, "type": "high_shelf"}
    ],
    "highpass_hz": 30,
    "compression": {
        "threshold_db": -18,
        "ratio": 2.0
    },
    "limiter_threshold_db": -1.0,
    "target_lufs": -14.0
}

eq_bands type must be one of: "low_shelf", "high_shelf", "peak".
Keep gain_db values between -6 and +6. Keep q values between 0.3 and 3.0.
Use 3-6 EQ bands total. Output ONLY valid JSON, no explanation."""


class MixMasterAgent:
    """
    Professional mixing and mastering for assembled soundscapes.

    Uses librosa analysis + Claude reasoning to determine processing parameters,
    then applies DSP via pedalboard + pyloudnorm.
    """

    def __init__(self, anthropic_api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.client = Anthropic(api_key=anthropic_api_key)
        self.model = model

    def process(self, raw_mix_path: str, config: SoundscapeConfig) -> str:
        """
        Analyze and process the raw mix into a mastered output.

        Args:
            raw_mix_path: Path to the raw rendered .wav file
            config: The SoundscapeConfig used to generate the audio

        Returns:
            Path to the mastered .wav file
        """
        print("   🎛️ Analyzing raw mix...")
        analysis = self._analyze(raw_mix_path)

        print("   🧠 Claude prescribing mastering chain...")
        chain = self._get_processing_chain(analysis, config)

        print("   🔊 Applying mastering DSP...")
        mastered_path = self._apply_processing(raw_mix_path, chain)

        print(f"   ✅ Mastered: {mastered_path}")
        return mastered_path

    def _analyze(self, audio_path: str) -> dict:
        """
        Deep analysis of the raw mix for mastering decisions.

        Returns a dict with spectral, dynamic, and loudness measurements.
        """
        if not HAS_LIBROSA:
            raise ImportError("librosa required for mix analysis")

        y, sr = librosa.load(audio_path, sr=44100, mono=False)

        # Handle mono/stereo
        if y.ndim == 1:
            y_mono = y
            is_stereo = False
        else:
            y_mono = librosa.to_mono(y)
            is_stereo = True

        duration = librosa.get_duration(y=y_mono, sr=sr)

        # 5-band energy breakdown
        S = np.abs(librosa.stft(y_mono))
        freqs = librosa.fft_frequencies(sr=sr)
        total_energy = np.sum(S ** 2)
        if total_energy == 0:
            total_energy = 1e-10

        bands = {
            "sub_bass_pct": float(np.sum(S[freqs <= 60] ** 2) / total_energy * 100),
            "bass_pct": float(np.sum(S[(freqs > 60) & (freqs <= 250)] ** 2) / total_energy * 100),
            "mid_pct": float(np.sum(S[(freqs > 250) & (freqs <= 2000)] ** 2) / total_energy * 100),
            "presence_pct": float(np.sum(S[(freqs > 2000) & (freqs <= 6000)] ** 2) / total_energy * 100),
            "air_pct": float(np.sum(S[freqs > 6000] ** 2) / total_energy * 100),
        }

        # Spectral centroid (brightness)
        centroid = librosa.feature.spectral_centroid(y=y_mono, sr=sr)[0]

        # RMS and dynamic range
        rms = librosa.feature.rms(y=y_mono)[0]
        rms_db = librosa.amplitude_to_db(rms + 1e-10)
        dynamic_range = float(np.max(rms_db) - np.min(rms_db))

        # Crest factor (peak-to-RMS)
        peak = float(np.max(np.abs(y_mono)))
        rms_val = float(np.sqrt(np.mean(y_mono ** 2)))
        crest_factor_db = float(20 * np.log10(peak / (rms_val + 1e-10)))

        # LUFS via pyloudnorm
        meter = pyln.Meter(sr)
        if is_stereo:
            lufs = meter.integrated_loudness(y.T)
        else:
            lufs = meter.integrated_loudness(y_mono.reshape(-1, 1))

        # Stereo width (correlation coefficient)
        stereo_correlation = 1.0
        if is_stereo and y.shape[0] >= 2:
            corr = np.corrcoef(y[0], y[1])
            stereo_correlation = float(corr[0, 1]) if not np.isnan(corr[0, 1]) else 1.0

        # Spectral flatness
        flatness = librosa.feature.spectral_flatness(y=y_mono)[0]

        return {
            "duration_sec": duration,
            "sample_rate": sr,
            "is_stereo": is_stereo,
            "integrated_lufs": float(lufs) if not np.isinf(lufs) else -60.0,
            "peak_dbfs": float(20 * np.log10(peak + 1e-10)),
            "rms_dbfs": float(20 * np.log10(rms_val + 1e-10)),
            "crest_factor_db": crest_factor_db,
            "dynamic_range_db": dynamic_range,
            "spectral_centroid_hz": float(np.mean(centroid)),
            "spectral_flatness": float(np.mean(flatness)),
            "stereo_correlation": stereo_correlation,
            "bands": bands,
        }

    def _get_processing_chain(self, analysis: dict, config: SoundscapeConfig) -> dict:
        """
        Ask Claude to prescribe a mastering processing chain based on analysis data.
        """
        prompt = f"""Prescribe a mastering chain for this ambient soundscape:

INTENT:
- Title: {config.title}
- Mood: {config.mood}
- Setting: {config.setting}
- Layers: {len(config.layers)} ({', '.join(l.name for l in config.layers)})

AUDIO ANALYSIS:
- Duration: {analysis['duration_sec']:.1f}s
- Stereo: {analysis['is_stereo']}
- Integrated loudness: {analysis['integrated_lufs']:.1f} LUFS
- Peak: {analysis['peak_dbfs']:.1f} dBFS
- RMS: {analysis['rms_dbfs']:.1f} dBFS
- Crest factor: {analysis['crest_factor_db']:.1f} dB
- Dynamic range: {analysis['dynamic_range_db']:.1f} dB
- Spectral centroid: {analysis['spectral_centroid_hz']:.0f} Hz
- Spectral flatness: {analysis['spectral_flatness']:.3f}
- Stereo correlation: {analysis['stereo_correlation']:.2f}

FREQUENCY BANDS:
- Sub-bass (<60Hz): {analysis['bands']['sub_bass_pct']:.1f}%
- Bass (60-250Hz): {analysis['bands']['bass_pct']:.1f}%
- Mids (250-2kHz): {analysis['bands']['mid_pct']:.1f}%
- Presence (2-6kHz): {analysis['bands']['presence_pct']:.1f}%
- Air (>6kHz): {analysis['bands']['air_pct']:.1f}%

Prescribe the mastering chain as JSON."""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1000,
            system=MASTERING_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text

        try:
            clean = raw.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1]
            if clean.endswith("```"):
                clean = clean.rsplit("```", 1)[0]
            chain = json.loads(clean.strip())
        except (json.JSONDecodeError, KeyError) as e:
            print(f"      ⚠ Failed to parse mastering chain: {e}")
            chain = self._default_chain()

        # Log the chain
        n_eq = len(chain.get("eq_bands", []))
        comp = chain.get("compression", {})
        print(f"      Chain: {n_eq} EQ bands, "
              f"comp {comp.get('threshold_db', 'N/A')}dB @ {comp.get('ratio', 'N/A')}:1, "
              f"limiter {chain.get('limiter_threshold_db', -1.0)}dB, "
              f"target {chain.get('target_lufs', -14.0)} LUFS")

        return chain

    def _default_chain(self) -> dict:
        """Conservative default mastering chain if Claude fails."""
        return {
            "eq_bands": [
                {"freq_hz": 80, "gain_db": 1.5, "q": 0.7, "type": "low_shelf"},
                {"freq_hz": 3500, "gain_db": -1.0, "q": 0.8, "type": "peak"},
                {"freq_hz": 10000, "gain_db": -1.5, "q": 0.7, "type": "high_shelf"},
            ],
            "highpass_hz": 30,
            "compression": {"threshold_db": -20, "ratio": 1.5},
            "limiter_threshold_db": -1.0,
            "target_lufs": -14.0,
        }

    def _apply_processing(self, raw_mix_path: str, chain: dict) -> str:
        """
        Apply the mastering chain using pedalboard + pyloudnorm.

        Returns path to the mastered file.
        """
        # Load audio
        data, sr = sf.read(raw_mix_path)

        # Ensure float32 for pedalboard
        if data.dtype != np.float32:
            data = data.astype(np.float32)

        # Handle mono vs stereo for pedalboard (expects [channels, samples])
        if data.ndim == 1:
            audio = data.reshape(1, -1)
        else:
            audio = data.T  # [samples, channels] -> [channels, samples]

        # Build pedalboard chain
        board = pb.Pedalboard()

        # 1. Subsonic high-pass filter
        hp_hz = chain.get("highpass_hz", 30)
        if hp_hz and hp_hz > 0:
            board.append(pb.HighpassFilter(cutoff_frequency_hz=hp_hz))

        # 2. EQ bands
        for band in chain.get("eq_bands", []):
            freq = band.get("freq_hz", 1000)
            gain = band.get("gain_db", 0)
            q = band.get("q", 0.7)
            band_type = band.get("type", "peak")

            if abs(gain) < 0.1:
                continue

            if band_type == "low_shelf":
                board.append(pb.LowShelfFilter(
                    cutoff_frequency_hz=freq, gain_db=gain, q=q
                ))
            elif band_type == "high_shelf":
                board.append(pb.HighShelfFilter(
                    cutoff_frequency_hz=freq, gain_db=gain, q=q
                ))
            elif band_type == "peak":
                board.append(pb.PeakFilter(
                    cutoff_frequency_hz=freq, gain_db=gain, q=q
                ))

        # 3. Compression
        comp = chain.get("compression", {})
        if comp:
            board.append(pb.Compressor(
                threshold_db=comp.get("threshold_db", -20),
                ratio=comp.get("ratio", 2.0),
            ))

        # 4. Limiter
        limiter_thresh = chain.get("limiter_threshold_db", -1.0)
        board.append(pb.Limiter(threshold_db=limiter_thresh))

        # Process through pedalboard
        processed = board(audio, sample_rate=sr)

        # Convert back to [samples, channels]
        if processed.shape[0] <= 2:
            processed = processed.T
        else:
            processed = processed.reshape(-1, 1)

        # 5. LUFS normalization via pyloudnorm
        target_lufs = chain.get("target_lufs", -14.0)
        meter = pyln.Meter(sr)
        current_lufs = meter.integrated_loudness(processed)

        if not np.isinf(current_lufs) and not np.isnan(current_lufs):
            processed = pyln.normalize.loudness(processed, current_lufs, target_lufs)

        # Clip to prevent any overs
        processed = np.clip(processed, -1.0, 1.0)

        # Save mastered file as PCM_16 for universal compatibility
        raw_path = Path(raw_mix_path)
        mastered_path = str(raw_path.parent / f"{raw_path.stem}_mastered{raw_path.suffix}")
        sf.write(mastered_path, processed, sr, subtype="PCM_16")

        # Log result
        final_lufs = meter.integrated_loudness(processed)
        final_peak = float(20 * np.log10(np.max(np.abs(processed)) + 1e-10))
        print(f"      Result: {final_lufs:.1f} LUFS, peak {final_peak:.1f} dBFS")

        return mastered_path
