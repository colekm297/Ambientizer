"""
sample_generator.py — Generates audio samples on-demand using ElevenLabs APIs.

Uses two ElevenLabs APIs:
  - SFX v2 (text_to_sound_effects) for environmental/texture layers (base, mid, detail)
  - Music v1 (music.compose) for musical/tonal layers that need harmonic content

Each layer gets cached to disk so the feedback loop can iterate on the mix
without regenerating samples.
"""

import os
import hashlib
from pathlib import Path

from pydub import AudioSegment
from elevenlabs.client import ElevenLabs

from schemas import LayerConfig, LayerType


class ElevenLabsSampleGenerator:
    """Generates audio samples using ElevenLabs SFX v2 and Music v1 APIs."""

    # SFX v2 API hard limit
    MAX_SFX_PROMPT_LENGTH = 450

    def __init__(self, api_key: str, cache_dir: str = "generated_samples"):
        self.client = ElevenLabs(api_key=api_key)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def generate_layer_audio(
        self,
        layer: LayerConfig,
        mood: str = "",
        setting: str = "",
        use_cache: bool = True,
        root_key: str = "",
        track_duration_sec: float = 0,
    ) -> str:
        """
        Generate audio for a single layer via ElevenLabs.
        Routes musical layers through Music v1 API, everything else through SFX v2.
        Returns the path to the generated .wav file.
        """
        is_musical = layer.layer_type == LayerType.MUSICAL
        prompt = self._build_prompt(layer, mood, setting, root_key)
        duration = self._get_duration(layer.layer_type, track_duration_sec)
        should_loop = layer.loop or layer.layer_type in (LayerType.BASE, LayerType.MID)
        api_tag = "music" if is_musical else "sfx"
        cache_key = hashlib.sha256(f"{api_tag}|{prompt}|{duration}".encode()).hexdigest()[:16]
        wav_path = str(self.cache_dir / f"{cache_key}.wav")

        if use_cache and os.path.exists(wav_path):
            print(f"      ♻ Cached: {layer.name}")
            return wav_path

        if is_musical:
            return self._generate_music(layer.name, prompt, duration, wav_path, cache_key)
        else:
            return self._generate_sfx(layer.name, prompt, duration, wav_path, cache_key, loop=should_loop)

    def _save_pcm_to_wav(self, audio_bytes: bytes, wav_path: str, sample_rate: int = 44100) -> AudioSegment:
        """Save raw PCM 16-bit LE bytes directly to WAV."""
        import struct, wave
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_bytes)
        return AudioSegment.from_wav(wav_path)

    def _save_mp3_to_wav(self, audio_bytes: bytes, wav_path: str, cache_key: str) -> AudioSegment:
        """Decode MP3 bytes to WAV via pydub (lossy fallback)."""
        mp3_path = str(self.cache_dir / f"{cache_key}.mp3")
        with open(mp3_path, "wb") as f:
            f.write(audio_bytes)
        audio = AudioSegment.from_mp3(mp3_path)
        audio.export(wav_path, format="wav")
        os.unlink(mp3_path)
        return audio

    def _generate_sfx(self, name: str, prompt: str, duration: float, wav_path: str, cache_key: str, loop: bool = False) -> str:
        """Generate via SFX v2 API (environmental sounds, textures)."""
        print(f"      🎵 Generating SFX: {name} ({duration:.0f}s, loop={loop})")
        print(f"         Prompt: {prompt[:80]}...")

        for fmt in ("pcm_44100", "mp3_44100_192"):
            try:
                result = self.client.text_to_sound_effects.convert(
                    text=prompt,
                    duration_seconds=duration,
                    prompt_influence=0.7,
                    output_format=fmt,
                    loop=loop,
                )
                audio_bytes = b"".join(result)

                if fmt.startswith("pcm"):
                    audio = self._save_pcm_to_wav(audio_bytes, wav_path)
                else:
                    audio = self._save_mp3_to_wav(audio_bytes, wav_path, cache_key)

                print(f"      ✓ Generated SFX: {name} ({len(audio)/1000:.1f}s, {fmt})")
                return wav_path

            except Exception as e:
                if fmt == "pcm_44100":
                    print(f"      ↓ PCM not available ({e}), trying MP3...")
                    continue
                print(f"      ⚠ ElevenLabs SFX error for '{name}': {e}")
                return ""

        return ""

    def _generate_music(self, name: str, prompt: str, duration: float, wav_path: str, cache_key: str) -> str:
        """Generate via Music v1 API (tonal/harmonic/melodic content)."""
        duration_ms = int(duration * 1000)
        duration_ms = max(3000, min(600000, duration_ms))

        print(f"      🎶 Generating Music: {name} ({duration_ms / 1000:.0f}s)")
        print(f"         Prompt: {prompt[:80]}...")

        for fmt in ("pcm_44100", "mp3_44100_192"):
            try:
                result = self.client.music.compose(
                    prompt=prompt,
                    model_id="music_v1",
                    music_length_ms=duration_ms,
                    force_instrumental=True,
                    output_format=fmt,
                )
                audio_bytes = b"".join(result)

                if fmt.startswith("pcm"):
                    audio = self._save_pcm_to_wav(audio_bytes, wav_path)
                else:
                    audio = self._save_mp3_to_wav(audio_bytes, wav_path, cache_key)

                print(f"      ✓ Generated Music: {name} ({len(audio)/1000:.1f}s, {fmt})")
                return wav_path

            except Exception as e:
                if fmt == "pcm_44100":
                    print(f"      ↓ PCM not available ({e}), trying MP3...")
                    continue
                print(f"      ⚠ ElevenLabs Music error for '{name}': {e}")
                print(f"        Falling back to SFX API...")
                return self._generate_sfx(name, prompt, min(duration, 22.0), wav_path, cache_key)

        return ""

    def _build_prompt(self, layer: LayerConfig, mood: str, setting: str, root_key: str = "") -> str:
        """
        Get the prompt for a layer. Injects root_key for tonal layers.
        For SFX layers, truncates to 450 chars.
        """
        if layer.elevenlabs_prompt:
            prompt = layer.elevenlabs_prompt
        else:
            prompt = f"{layer.name}, gentle ambient texture, warm, no sudden sounds"

        if root_key and root_key.lower() not in prompt.lower():
            is_tonal = layer.layer_type == LayerType.MUSICAL
            if is_tonal:
                prompt = f"{prompt}. In the key of {root_key}."

        if layer.layer_type != LayerType.MUSICAL and len(prompt) > self.MAX_SFX_PROMPT_LENGTH:
            prompt = prompt[:self.MAX_SFX_PROMPT_LENGTH - 3].rsplit(" ", 1)[0] + "..."

        return prompt

    def _get_duration(self, layer_type: LayerType, track_duration_sec: float = 0) -> float:
        """Choose generation duration based on layer type and track length.

        Musical layers match the track duration (capped at ElevenLabs' 600s max)
        so the music doesn't need to loop within shorter tracks. SFX layers stay
        short since ambient textures loop naturally.
        """
        if layer_type == LayerType.MUSICAL:
            if track_duration_sec > 0:
                return min(track_duration_sec, 600.0)
            return 300.0

        durations = {
            LayerType.BASE: 22.0,
            LayerType.MID: 22.0,
            LayerType.DETAIL: 10.0,
        }
        return durations.get(layer_type, 15.0)
