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
# Daily self-imposed credit cap. 0 (or negative) = DISABLED (no limit). Set the
# DAILY_CREDIT_LIMIT env var to a positive number to re-enable the guardrail.
DAILY_CREDIT_LIMIT = int(os.environ.get("DAILY_CREDIT_LIMIT", "0"))


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
        # Quality warnings collected during a generation (e.g. ToS rewrite,
        # composition-plan fallback, lossy MP3 fallback). The orchestrator reads
        # and clears this so the UI can surface what silently changed.
        self.warnings: list[str] = []

    def _warn(self, message: str) -> None:
        """Record a user-facing quality warning AND print it to the log."""
        self.warnings.append(message)
        print(f"      ⚠ {message}", flush=True)

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
        if DAILY_CREDIT_LIMIT <= 0:
            return  # guardrail disabled
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
        # A provided/edited composition plan must change the cache key so edits
        # produce fresh audio instead of returning a stale cached render.
        provided_plan = getattr(layer, "composition_plan", None) if is_musical else None
        plan_part = ""
        if music_mode == "composition_plan" and provided_plan:
            plan_part = "|plan=" + hashlib.sha256(json.dumps(provided_plan, sort_keys=True).encode()).hexdigest()[:10]
        cache_key = hashlib.sha256(f"{api_tag}|{music_mode}|{prompt}|{duration}{seed_part}{plan_part}".encode()).hexdigest()[:16]
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
                result = self._generate_music_composition_plan(
                    layer.name, prompt, duration, wav_path, cache_key,
                    provided_plan=provided_plan, root_key=root_key, mood=mood,
                )
            else:
                result = self._generate_music(layer.name, prompt, duration, wav_path, cache_key)
        else:
            result = self._generate_sfx(layer.name, prompt, duration, wav_path, cache_key, loop=should_loop)

        if not result:
            # Generation failed — refund the reservation
            self._refund_spend(estimated_credits, f"{api_tag} {layer.name} (refund - generation failed)")
            return result

        self._ensure_audible(wav_path)
        # HONEST FAILURE: never save a silent file as a successful track. A
        # rejected composition plan used to fall through to silence while the
        # job still reported "complete" — the worst possible outcome. After
        # _ensure_audible (which boosts merely-quiet layers), the only way a file
        # is still silent is a genuine generation failure, so raise → job error.
        if self._is_silent_file(wav_path):
            self._refund_spend(estimated_credits, f"{api_tag} {layer.name} (refund - silent output)")
            raise RuntimeError(
                f"Generation for '{layer.name}' produced SILENT audio — ElevenLabs likely rejected "
                f"the request (e.g. an invalid composition plan). The track was NOT saved as complete. "
                f"Try the Text prompt engine, or simplify the prompt/plan."
            )
        return result

    def _is_silent_file(self, wav_path: str, floor_dbfs: float = -70.0) -> bool:
        """True if the rendered file is effectively silent (pure digital silence
        or below an inaudible floor). Used to fail loudly instead of shipping a
        silent 'completed' track."""
        if not os.path.exists(wav_path):
            return False
        try:
            peak = AudioSegment.from_wav(wav_path).max_dBFS
        except Exception:
            return False
        return peak == float("-inf") or peak < floor_dbfs

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
        self._warn("Lossless PCM was unavailable from ElevenLabs — used 192kbps MP3 instead "
                   "(slightly lower audio fidelity). Usually transient; re-rolling often gets PCM.")
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

    @staticmethod
    def _extract_prompt_suggestion(exc: Exception) -> str:
        """If ElevenLabs rejected the prompt for Terms-of-Service reasons
        (status 'bad_prompt' — usually IP/artist references like composer
        names), the error body includes their own sanitized rewrite in
        data.prompt_suggestion. Pull it out so we can retry with it instead
        of destroying the layer with an 8s SFX fallback."""
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            detail = body.get("detail")
            if isinstance(detail, dict) and detail.get("status") == "bad_prompt":
                suggestion = (detail.get("data") or {}).get("prompt_suggestion")
                if isinstance(suggestion, str) and suggestion.strip():
                    return suggestion.strip()
        return ""

    def _generate_music(self, name: str, prompt: str, duration: float, wav_path: str, cache_key: str,
                        _sanitized_retry: bool = False) -> str:
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
                # ToS rejection ("bad_prompt", e.g. composer/IP names): retry ONCE
                # with ElevenLabs' own sanitized rewrite. Check this BEFORE the PCM
                # fallback — a rejected prompt fails identically on every format.
                suggestion = self._extract_prompt_suggestion(e)
                if suggestion and not _sanitized_retry:
                    self._warn("ElevenLabs rejected the prompt (Terms of Service — likely "
                               "artist/composer/IP names). Retried with their sanitized rewrite. "
                               "Tip: avoid real artist names (e.g. 'Hans Zimmer') and trademarked "
                               "titles for a cleaner result.")
                    print(f"      ↻ Sanitized rewrite: {suggestion[:120]}...", flush=True)
                    return self._generate_music(name, suggestion, duration, wav_path, cache_key,
                                                _sanitized_retry=True)
                if fmt == "pcm_44100":
                    print(f"      ↓ PCM not available ({e}), trying MP3...")
                    continue
                self._warn(f"Music generation failed for '{name}' — fell back to a short SFX "
                           f"texture (NOT a full musical track). Error: {str(e)[:160]}")
                return self._generate_sfx(name, prompt, min(duration, HARD_MAX_SFX_SEC), wav_path, cache_key)

        return ""

    def _build_ambient_composition_plan(self, prompt: str, duration_ms: int,
                                         root_key: str = "", mood: str = "",
                                         provided_plan: dict = None) -> dict:
        """Build an ElevenLabs composition_plan for a complete ambient loop.

        Priority: (1) a PROVIDED plan (authored/edited in the UI — what-you-see-
        is-what-generates), (2) a fresh Claude-authored arrangement, (3) the
        generic time-chunked fallback below.
        """
        try:
            from composition_planner import author_composition_plan, finalize_plan, clamp_plan_sections
            if provided_plan and provided_plan.get("sections"):
                final = clamp_plan_sections(finalize_plan(provided_plan, duration_ms))
                if final:
                    print(f"      [plan] Using PROVIDED plan ({len(final['sections'])} sections after clamp)", flush=True)
                    return final
            authored = clamp_plan_sections(author_composition_plan(prompt, duration_ms, root_key=root_key, mood=mood))
            if authored and authored.get("sections"):
                print(f"      [plan] Using Claude-authored arrangement "
                      f"({len(authored['sections'])} sections after clamp)", flush=True)
                return authored
        except Exception as e:
            print(f"      [plan] authoring unavailable ({e}); generic plan", flush=True)

        # Reaching here means neither a provided nor a Claude-authored plan
        # materialized — we're using the generic time-chunked fallback, which is
        # far blander than a real arrangement. Surface it instead of hiding it.
        self._warn("Could not author a custom composition arrangement — used a generic "
                   "time-chunked plan (much less musically evolving). Re-roll, or design "
                   "the plan in the composition editor for full control.")
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

    # Words that nudge the music model into synthesizing voice — which, without
    # force_instrumental (REJECTED alongside composition_plan), degrades into
    # garbled robotic vocal artifacts mid-track. Stripped from every plan style
    # right before the API call, and hard negatives are always merged in.
    _VOCALISH_WORDS = ("breathy", "breath", "sighing", "sigh", "whisper", "humming",
                       "hum", "throat", "chant", "moan", "wordless", "choir",
                       "vocal-like", "voice-like")
    _FORCED_NEGATIVES = ("vocals", "spoken word", "singing", "robotic vocal artifacts")

    def _sanitize_plan_vocals(self, plan: dict) -> dict:
        """Scrub voice-suggesting adjectives from plan styles and force no-vocal
        negatives — the composition-plan path's substitute for force_instrumental."""
        import re as _re
        scrubbed = 0

        def clean_list(styles):
            nonlocal scrubbed
            out = []
            for s in styles or []:
                orig = s
                for w in self._VOCALISH_WORDS:
                    s = _re.sub(rf"\b{w}\b", "soft", s, flags=_re.IGNORECASE)
                if s != orig:
                    scrubbed += 1
                out.append(s)
            return out

        plan["positive_global_styles"] = clean_list(plan.get("positive_global_styles"))
        for sec in plan.get("sections", []):
            sec["positive_local_styles"] = clean_list(sec.get("positive_local_styles"))

        negs = [n.lower() for n in (plan.get("negative_global_styles") or [])]
        for needed in self._FORCED_NEGATIVES:
            if needed not in negs:
                plan.setdefault("negative_global_styles", []).append(needed)
        if scrubbed:
            self._warn(f"Softened {scrubbed} voice-suggesting term(s) in the composition plan "
                       "(e.g. 'breathy') — these cause robotic vocal artifacts mid-track.")
        return plan

    def _generate_music_composition_plan(self, name: str, prompt: str, duration: float, wav_path: str, cache_key: str,
                                          provided_plan: dict = None, root_key: str = "", mood: str = "") -> str:
        """Generate via Music v1 API using a structured composition_plan."""
        duration_ms = int(min(duration, HARD_MAX_MUSIC_SEC) * 1000)
        duration_ms = max(3000, min(int(HARD_MAX_MUSIC_SEC * 1000), duration_ms))
        plan = self._build_ambient_composition_plan(
            prompt, duration_ms, root_key=root_key, mood=mood, provided_plan=provided_plan
        )
        plan = self._sanitize_plan_vocals(plan)

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
                    # NOTE: force_instrumental is REJECTED with composition_plan
                    # ("can only be used with prompt"). Instrumental is enforced via
                    # the plan's negative_global_styles ("vocals", "lyrics") instead.
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
                self._warn(f"Composition plan was REJECTED for '{name}' — fell back to a flat text "
                           f"prompt, so the track does NOT have the evolving arrangement you designed. "
                           f"Error: {str(e)[:160]}")
                return self._generate_music(name, prompt, duration, wav_path, cache_key)

        return ""


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
            if additive and not any(
                w in prompt.lower() for w in ("0:", "arc", "enter", "mid-way", "seamless")
            ):
                prompt = (
                    f"{prompt}. Dense sustained texture with one subtle mid-way shift, "
                    "ending similar to the start for seamless loop, no long silent gaps."
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
            # No explicit length → generate a full 10-min source instead of a 30s
            # clip looped 40×. Long-source = far less repetition; matches what the
            # favorited "banger" tracks use (600s) and what the UI now defaults to.
            return HARD_MAX_MUSIC_SEC

        durations = {
            LayerType.BASE: 8.0,
            LayerType.MID: 8.0,
            LayerType.DETAIL: 4.0,
        }
        return min(durations.get(layer_type, 5.0), HARD_MAX_SFX_SEC)
