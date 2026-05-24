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
import time
import json
import random
from pathlib import Path

from pydub import AudioSegment
from elevenlabs.client import ElevenLabs

from schemas import LayerConfig, LayerType
from retry_utils import is_transient_api_error

ADDITIVE_MUSIC_SEC = 90.0   # loop cell length for layers added on top of a mix
STEM_SAMPLE_SEC = 120       # clip length sent to stem API (ambient is static throughout)
HARD_MAX_MUSIC_SEC = 600.0
HARD_MAX_SFX_SEC = 8.0
DAILY_CREDIT_LIMIT = int(os.environ.get("DAILY_CREDIT_LIMIT", "100000"))


class QuotaExhaustedError(Exception):
    """Raised when ElevenLabs credits are exhausted."""
    pass


class SpendingLimitError(Exception):
    """Raised when the daily self-imposed spending limit is reached."""
    pass


class ElevenLabsSampleGenerator:
    """Generates audio samples using ElevenLabs SFX v2 and Music v1 APIs."""

    MAX_SFX_PROMPT_LENGTH = 450

    def __init__(self, api_key: str, cache_dir: str = "generated_samples"):
        self.client = ElevenLabs(api_key=api_key)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._spend_log_path = self.cache_dir / "_daily_spend.json"

    def _call_with_retry(self, func, *args, max_retries=3, base_delay=2.0, **kwargs):
        """Call an ElevenLabs API function with exponential backoff on transient errors."""
        last_exc = None
        for attempt in range(1, max_retries + 1):
            try:
                return func(*args, **kwargs)
            except QuotaExhaustedError:
                raise
            except Exception as e:
                if self._is_quota_error(e):
                    raise QuotaExhaustedError(
                        "ElevenLabs credits exhausted (0 remaining). "
                        "Add credits at elevenlabs.io/subscription"
                    ) from e
                last_exc = e
                if attempt < max_retries and is_transient_api_error(e):
                    delay = min(base_delay * (2 ** (attempt - 1)), 30.0)
                    delay *= 0.5 + random.random()
                    print(f"  ↻ Retry {attempt}/{max_retries - 1} for ElevenLabs "
                          f"after {delay:.1f}s — {type(e).__name__}: {str(e)[:120]}")
                    time.sleep(delay)
                    continue
                raise
        raise last_exc

    def _get_daily_spend(self) -> dict:
        today = time.strftime("%Y-%m-%d")
        try:
            raw = json.loads(self._spend_log_path.read_text())
            if raw.get("date") == today:
                return raw
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass
        return {"date": today, "credits": 0, "calls": 0}

    def _record_spend(self, credits: float, label: str = ""):
        spend = self._get_daily_spend()
        spend["credits"] += credits
        spend["calls"] += 1
        try:
            self._spend_log_path.write_text(json.dumps(spend))
        except OSError:
            pass
        print(f"      💰 Spent ~{credits:.0f} cr ({label}) | Day total: ~{spend['credits']:.0f} / {DAILY_CREDIT_LIMIT:,}")

    def _refund_spend(self, credits: float, label: str = ""):
        spend = self._get_daily_spend()
        spend["credits"] = max(0, spend["credits"] - credits)
        try:
            self._spend_log_path.write_text(json.dumps(spend))
        except OSError:
            pass
        print(f"      ↩ Refund ~{credits:.0f} cr ({label}) | Day total: ~{spend['credits']:.0f} / {DAILY_CREDIT_LIMIT:,}")

    def _check_spend_limit(self, estimated_credits: float):
        spend = self._get_daily_spend()
        if spend["credits"] + estimated_credits > DAILY_CREDIT_LIMIT:
            raise SpendingLimitError(
                f"Daily spending limit reached (~{spend['credits']:.0f} / {DAILY_CREDIT_LIMIT:,} credits used today). "
                f"This action would cost ~{estimated_credits:.0f} more. "
                f"Limit resets tomorrow or set DAILY_CREDIT_LIMIT env var (currently {DAILY_CREDIT_LIMIT:,})."
            )

    def check_real_balance(self, estimated_credits: float):
        """Pre-flight check against the real ElevenLabs balance."""
        try:
            sub = self.client.user.subscription.get()
            remaining = max(0, sub.character_limit - sub.character_count)
            if remaining < estimated_credits:
                raise QuotaExhaustedError(
                    f"Not enough credits: ~{remaining:,.0f} remaining but this action costs ~{estimated_credits:,.0f}. "
                    f"Add credits at elevenlabs.io/subscription"
                )
        except QuotaExhaustedError:
            raise
        except Exception as e:
            print(f"  [credits] Balance check failed (non-fatal): {e}")

    def generate_layer_audio(
        self,
        layer: LayerConfig,
        mood: str = "",
        setting: str = "",
        use_cache: bool = True,
        root_key: str = "",
        track_duration_sec: float = 0,
        music_length_sec: float = 0,
        reroll_seed: int = 0,
        additive: bool = False,
    ) -> str:
        """
        Generate audio for a single layer via ElevenLabs.
        Routes musical layers through Music v1 API, everything else through SFX v2.
        Returns the path to the generated .wav file.

        reroll_seed: Incrementing this produces a new cache key so re-rolls
        get fresh audio but are still individually cacheable.
        """
        is_musical = layer.layer_type == LayerType.MUSICAL
        prompt = self._build_prompt(layer, mood, setting, root_key, additive=additive)
        if additive and is_musical:
            duration = min(ADDITIVE_MUSIC_SEC, music_length_sec or ADDITIVE_MUSIC_SEC, HARD_MAX_MUSIC_SEC)
        else:
            duration = self._get_duration(layer.layer_type, track_duration_sec, music_length_sec)
        should_loop = layer.loop or layer.layer_type in (LayerType.BASE, LayerType.MID)
        api_tag = "music" if is_musical else "sfx"
        seed_part = f"|seed={reroll_seed}" if reroll_seed else ""
        music_mode = getattr(layer, "music_generation_mode", "text") if is_musical else "text"
        cache_key = hashlib.sha256(f"{api_tag}|{music_mode}|{prompt}|{duration}{seed_part}".encode()).hexdigest()[:16]
        wav_path = str(self.cache_dir / f"{cache_key}.wav")

        if os.path.exists(wav_path):
            print(f"      ♻ Cached: {layer.name}")
            return wav_path

        cr_per_sec = 30 if is_musical else 20
        estimated_credits = duration * cr_per_sec
        self._check_spend_limit(estimated_credits)
        self.check_real_balance(estimated_credits)

        # Reserve credits BEFORE the API call so subsequent layers see the
        # updated total and won't pass the limit check while this one is
        # still in-flight.
        self._record_spend(estimated_credits, f"{api_tag} {layer.name} {duration:.0f}s (reserved)")

        if is_musical:
            if music_mode == "composition_plan":
                result = self._generate_music_composition_plan(layer.name, prompt, duration, wav_path, cache_key)
            else:
                result = self._generate_music(layer.name, prompt, duration, wav_path, cache_key)
        else:
            result = self._generate_sfx(layer.name, prompt, duration, wav_path, cache_key, loop=should_loop)

        if not result:
            # Generation failed — refund the reservation
            self._refund_spend(estimated_credits, f"{api_tag} {layer.name} (refund - generation failed)")
        else:
            self._ensure_audible(wav_path)

        return result

    def _ensure_audible(self, wav_path: str, target_peak_db: float = -8.0) -> None:
        """Boost pathologically quiet generations so added layers aren't inaudible."""
        if not os.path.exists(wav_path):
            return
        audio = AudioSegment.from_wav(wav_path)
        peak_db = audio.max_dBFS
        if peak_db == float("-inf"):
            print(f"      ⚠ Generated audio is completely silent: {wav_path}", flush=True)
            return
        if peak_db >= -20.0:
            return
        gain = min(36.0, target_peak_db - peak_db)
        boosted = audio.apply_gain(gain)
        boosted.export(wav_path, format="wav")
        print(
            f"      ↑ Boosted quiet layer by {gain:.1f} dB "
            f"(peak was {peak_db:.1f} dBFS → ~{target_peak_db:.0f} dBFS)",
            flush=True,
        )

    def _save_pcm_to_wav(self, audio_bytes: bytes, wav_path: str, sample_rate: int = 44100,
                          expected_duration: float = 0) -> AudioSegment:
        """Save raw PCM 16-bit LE bytes directly to WAV, auto-detecting channels."""
        import wave
        n_bytes = len(audio_bytes)
        channels = 1
        if expected_duration > 0:
            mono_dur = n_bytes / (sample_rate * 2)
            stereo_dur = n_bytes / (sample_rate * 4)
            if abs(stereo_dur - expected_duration) < abs(mono_dur - expected_duration):
                channels = 2
        elif n_bytes > 0:
            # No expected duration hint — assume stereo (ElevenLabs default)
            channels = 2

        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(audio_bytes)
        audio = AudioSegment.from_wav(wav_path)
        actual_dur = len(audio) / 1000
        print(f"         PCM: {n_bytes} bytes → {channels}ch, {actual_dur:.1f}s (expected ~{expected_duration:.0f}s)")
        return audio

    def _save_mp3_to_wav(self, audio_bytes: bytes, wav_path: str, cache_key: str) -> AudioSegment:
        """Decode MP3 bytes to WAV via pydub (lossy fallback)."""
        mp3_path = str(self.cache_dir / f"{cache_key}.mp3")
        with open(mp3_path, "wb") as f:
            f.write(audio_bytes)
        audio = AudioSegment.from_mp3(mp3_path)
        audio.export(wav_path, format="wav")
        os.unlink(mp3_path)
        return audio

    @staticmethod
    def _is_quota_error(e: Exception) -> bool:
        err = str(e).lower()
        return "quota_exceeded" in err or ("0 credits remaining" in err)

    def _generate_sfx(self, name: str, prompt: str, duration: float, wav_path: str, cache_key: str, loop: bool = False) -> str:
        """Generate via SFX v2 API (environmental sounds, textures)."""
        print(f"      🎵 Generating SFX: {name} ({duration:.0f}s, loop={loop})")
        print(f"         Prompt: {prompt[:80]}...")

        for fmt in ("pcm_44100", "mp3_44100_192"):
            try:
                result = self._call_with_retry(
                    self.client.text_to_sound_effects.convert,
                    text=prompt,
                    duration_seconds=duration,
                    prompt_influence=0.7,
                    output_format=fmt,
                    loop=loop,
                )
                audio_bytes = b"".join(result)

                if fmt.startswith("pcm"):
                    audio = self._save_pcm_to_wav(audio_bytes, wav_path,
                                                   expected_duration=duration)
                else:
                    audio = self._save_mp3_to_wav(audio_bytes, wav_path, cache_key)

                print(f"      ✓ Generated SFX: {name} ({len(audio)/1000:.1f}s, {fmt})")
                return wav_path

            except QuotaExhaustedError:
                raise
            except Exception as e:
                if fmt == "pcm_44100":
                    print(f"      ↓ PCM not available ({e}), trying MP3...")
                    continue
                print(f"      ⚠ ElevenLabs SFX error for '{name}': {e}")
                return ""

        return ""

    def _generate_music(self, name: str, prompt: str, duration: float, wav_path: str, cache_key: str) -> str:
        """Generate via Music v1 API (tonal/harmonic/melodic content)."""
        duration_ms = int(min(duration, HARD_MAX_MUSIC_SEC) * 1000)
        duration_ms = max(3000, min(int(HARD_MAX_MUSIC_SEC * 1000), duration_ms))

        print(f"      🎶 Generating Music: {name} ({duration_ms / 1000:.0f}s)")
        print(f"         Prompt: {prompt[:80]}...")

        for fmt in ("pcm_44100", "mp3_44100_192"):
            try:
                result = self._call_with_retry(
                    self.client.music.compose,
                    prompt=prompt,
                    model_id="music_v1",
                    music_length_ms=duration_ms,
                    force_instrumental=True,
                    output_format=fmt,
                )
                audio_bytes = b"".join(result)

                if fmt.startswith("pcm"):
                    audio = self._save_pcm_to_wav(audio_bytes, wav_path,
                                                   expected_duration=duration_ms / 1000)
                else:
                    audio = self._save_mp3_to_wav(audio_bytes, wav_path, cache_key)

                print(f"      ✓ Generated Music: {name} ({len(audio)/1000:.1f}s, {fmt})")
                return wav_path

            except QuotaExhaustedError:
                raise
            except Exception as e:
                if fmt == "pcm_44100":
                    print(f"      ↓ PCM not available ({e}), trying MP3...")
                    continue
                print(f"      ⚠ ElevenLabs Music error for '{name}': {e}")
                print(f"        Falling back to SFX API...")
                return self._generate_sfx(name, prompt, min(duration, HARD_MAX_SFX_SEC), wav_path, cache_key)

        return ""

    def _build_ambient_composition_plan(self, prompt: str, duration_ms: int) -> dict:
        """Build an ElevenLabs composition_plan optimized for complete ambient loops."""
        section_ms = max(3000, min(120000, duration_ms))
        sections = []
        remaining = duration_ms
        idx = 1
        while remaining > 0:
            dur = min(section_ms, remaining)
            if dur < 3000 and sections:
                sections[-1]["duration_ms"] += dur
                break
            sections.append({
                "section_name": "Complete Ambient Arrangement Loop" if len(sections) == 0 else f"Subtle Arrangement Evolution {idx}",
                "positive_local_styles": [
                    prompt,
                    "complete layered instrumental arrangement",
                    "all described instruments and textures clearly present",
                    "melodic lead or expressive top-line present when requested",
                    "supporting pads and low foundation underneath",
                    "slow evolving harmonic motion",
                    "seamless loopable soundscape",
                    "stable sustained energy",
                ],
                "negative_local_styles": [
                    "single drone only",
                    "static pad only",
                    "empty texture",
                    "one-note minimal drone",
                    "song ending",
                    "fade-out ending",
                    "final cadence",
                    "dramatic climax",
                    "verse chorus structure",
                    "beat drop",
                    "drums",
                    "vocals",
                    "synthwave",
                    "trailer music",
                    "sudden transition",
                ],
                "duration_ms": dur,
                "lines": [],
            })
            remaining -= dur
            idx += 1

        return {
            "positive_global_styles": [
                "instrumental ambient soundscape",
                "complete layered arrangement",
                "multiple complementary musical elements",
                "background listening",
                "continuous never-ending loop",
                "slow evolving sustained harmony",
                "soft spacious reverb",
                "subtle movement without song structure",
            ],
            "negative_global_styles": [
                "single drone only",
                "static pad only",
                "empty texture",
                "vocals",
                "lyrics",
                "drums",
                "EDM",
                "synthwave",
                "trailer music",
                "anthemic orchestration",
                "verse chorus bridge",
                "final cadence",
                "fade-out ending",
                "abrupt ending",
            ],
            "sections": sections,
        }

    def _generate_music_composition_plan(self, name: str, prompt: str, duration: float, wav_path: str, cache_key: str) -> str:
        """Generate via Music v1 API using a structured composition_plan."""
        duration_ms = int(min(duration, HARD_MAX_MUSIC_SEC) * 1000)
        duration_ms = max(3000, min(int(HARD_MAX_MUSIC_SEC * 1000), duration_ms))
        plan = self._build_ambient_composition_plan(prompt, duration_ms)

        print(f"      🎼 Generating Music Plan: {name} ({duration_ms / 1000:.0f}s, {len(plan['sections'])} section(s))")
        print(f"         Prompt: {prompt[:80]}...")

        for fmt in ("pcm_44100", "mp3_44100_192"):
            try:
                result = self._call_with_retry(
                    self.client.music.compose,
                    composition_plan=plan,
                    model_id="music_v1",
                    output_format=fmt,
                    respect_sections_durations=True,
                )
                audio_bytes = b"".join(result)

                if fmt.startswith("pcm"):
                    audio = self._save_pcm_to_wav(audio_bytes, wav_path,
                                                   expected_duration=duration_ms / 1000)
                else:
                    audio = self._save_mp3_to_wav(audio_bytes, wav_path, cache_key)

                print(f"      ✓ Generated Music Plan: {name} ({len(audio)/1000:.1f}s, {fmt})")
                return wav_path

            except QuotaExhaustedError:
                raise
            except Exception as e:
                if fmt == "pcm_44100":
                    print(f"      ↓ Composition plan PCM failed ({e}), trying MP3...")
                    continue
                print(f"      ⚠ ElevenLabs composition plan error for '{name}': {e}")
                print(f"        Falling back to text prompt Music API...")
                return self._generate_music(name, prompt, duration, wav_path, cache_key)

        return ""

    def separate_stems(self, audio_path: str, variation: str = "six_stems_v1") -> dict:
        """
        Separate a music file into individual instrument stems.

        Args:
            audio_path: Path to the audio file to separate
            variation: 'two_stems_v1' or 'six_stems_v1'

        Returns:
            Dict mapping stem name -> file path
        """
        import zipfile
        import io

        stems_dir = self.cache_dir / f"stems_{variation}"
        stems_dir.mkdir(parents=True, exist_ok=True)

        audio_hash = hashlib.sha256(f"{audio_path}|{variation}".encode()).hexdigest()[:12]
        marker_path = stems_dir / f"{audio_hash}_done"
        if marker_path.exists():
            result = {}
            for p in stems_dir.glob(f"{audio_hash}_*.mp3"):
                stem_name = p.stem.replace(f"{audio_hash}_", "")
                result[stem_name] = str(p)
            if result:
                print(f"      ♻ Cached stems: {list(result.keys())}")
                return result

        print(f"      🎛 Separating stems: {audio_path} ({variation})")

        # The stem separation API rejects audio >= 600s, and long uploads are slow.
        # Ambient mixes are static — a 2-minute middle clip is enough.
        STEM_MAX_SEC = 599
        from pydub import AudioSegment as _AS
        audio_seg = _AS.from_file(audio_path)
        total_sec = len(audio_seg) / 1000
        sample_sec = min(STEM_SAMPLE_SEC, STEM_MAX_SEC, total_sec)
        if total_sec > sample_sec + 5:
            start_ms = max(0, int(len(audio_seg) / 2 - (sample_sec * 500)))
            end_ms = start_ms + int(sample_sec * 1000)
            print(
                f"      ✂ Using {sample_sec:.0f}s middle clip for stem separation "
                f"(from {total_sec:.0f}s source)",
                flush=True,
            )
            audio_seg = audio_seg[start_ms:end_ms]
        elif total_sec >= STEM_MAX_SEC + 1:
            print(f"      ✂ Trimming {total_sec:.0f}s → {STEM_MAX_SEC}s for stem API limit")
            audio_seg = audio_seg[:STEM_MAX_SEC * 1000]
            trimmed_buf = io.BytesIO()
            audio_seg.export(trimmed_buf, format="wav")
            file_bytes = trimmed_buf.getvalue()
        else:
            file_bytes = Path(audio_path).read_bytes()

        response = self.client.music.separate_stems(
            file=io.BytesIO(file_bytes),
            stem_variation_id=variation,
        )
        zip_bytes = b"".join(response)
        print(f"      📦 Received {len(zip_bytes)} bytes ZIP")

        result = {}
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for name in zf.namelist():
                if name.endswith("/"):
                    continue
                stem_label = Path(name).stem.lower()
                out_path = stems_dir / f"{audio_hash}_{stem_label}.mp3"
                with zf.open(name) as src, open(out_path, "wb") as dst:
                    dst.write(src.read())
                result[stem_label] = str(out_path)
                print(f"         → {stem_label}: {out_path}")

        marker_path.write_text("ok")
        return result

    def _build_prompt(self, layer: LayerConfig, mood: str, setting: str, root_key: str = "",
                      additive: bool = False) -> str:
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

        if layer.layer_type == LayerType.MUSICAL:
            lower = prompt.lower()
            if not any(w in lower for w in ("continuous", "steady", "seamless", "never-ending", "sustained")):
                prompt = (
                    f"{prompt}. Continuous sustained instrumental texture throughout, "
                    "seamless loop, no long silent gaps."
                )
        elif layer.layer_type in (LayerType.BASE, LayerType.MID) and layer.loop:
            lower = prompt.lower()
            if not any(w in lower for w in ("continuous", "steady", "seamless", "never-ending")):
                prompt = (
                    f"{prompt}. Continuous steady environmental bed, no discrete hits or pulses, seamless loop."
                )

        return prompt

    def _get_duration(self, layer_type: LayerType, track_duration_sec: float = 0,
                       music_length_sec: float = 0) -> float:
        """Choose generation duration based on layer type.

        Hard caps: music ≤ 180s, SFX ≤ 8s. The audio engine crossfade-loops
        short clips to fill any track length.
        """
        if layer_type == LayerType.MUSICAL:
            if music_length_sec > 0:
                return min(music_length_sec, HARD_MAX_MUSIC_SEC)
            return 30.0

        durations = {
            LayerType.BASE: 8.0,
            LayerType.MID: 8.0,
            LayerType.DETAIL: 4.0,
        }
        return min(durations.get(layer_type, 5.0), HARD_MAX_SFX_SEC)
