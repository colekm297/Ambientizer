"""Loop quality test harness.

Runs candidate loop-prep strategies against existing raw ElevenLabs files
in `generated_samples/` and scores how clean the wrap point is. No new
generations needed.

Scores (lower = better, except spectral_sim which is higher = better):
  level_dB        : abs dBFS diff between last 1s and first 1s of loop
  click_pct       : abs(last_sample - first_sample) / int16 max, in %
  body_dip_dB     : how much quieter the last 5s + first 5s are vs body
  spectral_sim    : cosine similarity of MFCC of last 3s and first 3s
                    (0..1, higher = more similar content at seam)

Usage:
  python loop_lab.py                  # run all strategies on all raw files
  python loop_lab.py --strategy v3    # run a single strategy
  python loop_lab.py --file <name>    # run on a single file
  python loop_lab.py --export <dir>   # also export prepped wavs for listening
"""

from __future__ import annotations

import argparse
import glob
import os
import sys
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
from pydub import AudioSegment

import librosa

import audio_engine


SAMPLES_DIR = "generated_samples"


# -----------------------------------------------------------------------------
# Metrics
# -----------------------------------------------------------------------------


def _samples_float(audio: AudioSegment) -> np.ndarray:
    arr = np.array(audio.get_array_of_samples(), dtype=np.float64)
    if audio.channels == 2:
        arr = arr.reshape((-1, 2)).mean(axis=1)
    return arr / 32768.0


def _dbfs(seg: AudioSegment) -> float:
    return float("-inf") if len(seg) == 0 else seg.dBFS


def _mfcc(audio: AudioSegment, start_ms: int, dur_ms: int) -> np.ndarray:
    seg = audio[start_ms:start_ms + dur_ms]
    if len(seg) == 0:
        return np.zeros((13,))
    sr = seg.frame_rate
    sig = _samples_float(seg)
    if len(sig) < sr // 10:
        return np.zeros((13,))
    mfcc = librosa.feature.mfcc(y=sig.astype(np.float32), sr=sr, n_mfcc=13)
    return mfcc.mean(axis=1)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    if np.linalg.norm(a) < 1e-9 or np.linalg.norm(b) < 1e-9:
        return 0.0
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


@dataclass
class SeamScore:
    level_dB: float          # |last 1s dBFS - first 1s dBFS|, lower=better
    click_pct: float         # sample discontinuity at exact wrap, %
    body_dip_dB: float       # avg of (last5s, first5s) - body, signed; near 0=good
    spectral_sim: float      # MFCC cosine sim of last 3s vs first 3s
    duration_s: float

    def __str__(self) -> str:
        return (
            f"dur={self.duration_s:6.1f}s  "
            f"level={self.level_dB:5.2f}dB  "
            f"click={self.click_pct:5.2f}%  "
            f"dip={self.body_dip_dB:+5.2f}dB  "
            f"specSim={self.spectral_sim:0.3f}"
        )


def score_seam(audio: AudioSegment) -> SeamScore:
    dur = len(audio)
    head1 = audio[:1000]
    tail1 = audio[-1000:]
    head5 = audio[:5000]
    tail5 = audio[-5000:]
    body = audio[dur // 4 : 3 * dur // 4]

    level_dB = abs(_dbfs(tail1) - _dbfs(head1))

    h_samples = np.array(audio[-1:].get_array_of_samples(), dtype=np.float64)
    f_samples = np.array(audio[:1].get_array_of_samples(), dtype=np.float64)
    last_val = h_samples[-1] if len(h_samples) else 0.0
    first_val = f_samples[0] if len(f_samples) else 0.0
    click_pct = abs(last_val - first_val) / 32768.0 * 100

    seam_avg_dbfs = (_dbfs(head5) + _dbfs(tail5)) / 2
    body_dbfs = _dbfs(body)
    body_dip = seam_avg_dbfs - body_dbfs

    mh = _mfcc(audio, 0, 3000)
    mt = _mfcc(audio, dur - 3000, 3000)
    spec_sim = _cosine(mh, mt)

    return SeamScore(
        level_dB=level_dB,
        click_pct=click_pct,
        body_dip_dB=body_dip,
        spectral_sim=spec_sim,
        duration_s=dur / 1000,
    )


# -----------------------------------------------------------------------------
# Strategies
# -----------------------------------------------------------------------------


def strat_passthrough(audio: AudioSegment) -> AudioSegment:
    """No processing at all. Baseline."""
    return audio


def strat_v3_current(audio: AudioSegment) -> AudioSegment:
    """Current production loop prep: trim fades, rotate, 15s crossfade."""
    return audio_engine.prepare_musical_loop(audio, crossfade_ms=15_000)


def strat_short_xfade(audio: AudioSegment) -> AudioSegment:
    """Trim fades + rotate, then SHORT 100ms crossfade (industry standard)."""
    prepared = audio_engine._trim_generated_fade_out(audio)
    prepared = audio_engine._trim_generated_fade_in(prepared)
    rot = audio_engine._find_loop_rotation_ms(prepared)
    prepared = audio_engine._rotate_audio(prepared, rot)
    return audio_engine.make_loopable(prepared, 100)


def strat_aggressive_trim(audio: AudioSegment) -> AudioSegment:
    """Aggressively trim until level is within 1dB of body on both ends,
    then short crossfade. No rotation."""
    a = audio
    dur = len(a)
    body = a[dur // 4 : 3 * dur // 4]
    body_db = body.dBFS

    # Trim head until within 1dB of body
    step = 250
    head_trim = 0
    for t in range(0, dur // 3, step):
        if _dbfs(a[t:t + 1000]) >= body_db - 1.0:
            head_trim = t
            break
    a = a[head_trim:]

    # Trim tail until within 1dB of body (search from end backwards)
    dur2 = len(a)
    tail_trim = 0
    for t in range(0, dur2 // 3, step):
        if _dbfs(a[dur2 - t - 1000:dur2 - t]) >= body_db - 1.0:
            tail_trim = t
            break
    if tail_trim:
        a = a[:-tail_trim] if tail_trim else a

    return audio_engine.make_loopable(a, 100)


def strat_mfcc_loop_point(audio: AudioSegment) -> AudioSegment:
    """Content-aware: find the loop point inside the audio that best matches
    the (post-fade-trim) start, using MFCC cosine similarity. Then trim the
    audio to that loop length. Short crossfade.
    """
    a = audio_engine._trim_generated_fade_out(audio)
    a = audio_engine._trim_generated_fade_in(a)

    dur = len(a)
    if dur < 60_000:
        return audio_engine.make_loopable(a, 100)

    sr = a.frame_rate
    sig = _samples_float(a).astype(np.float32)

    win_ms = 3000
    win_samples = int(win_ms * sr / 1000)
    head_sig = sig[:win_samples]
    head_mfcc = librosa.feature.mfcc(y=head_sig, sr=sr, n_mfcc=13).mean(axis=1)

    # Search the back half for the best match
    search_start_ms = int(dur * 0.5)
    search_end_ms = dur - win_ms
    step_ms = 500

    best_offset = dur
    best_sim = -1.0
    for t_ms in range(search_start_ms, search_end_ms, step_ms):
        t_samp = int(t_ms * sr / 1000)
        chunk = sig[t_samp:t_samp + win_samples]
        if len(chunk) < win_samples:
            break
        m = librosa.feature.mfcc(y=chunk, sr=sr, n_mfcc=13).mean(axis=1)
        sim = _cosine(head_mfcc, m)
        if sim > best_sim:
            best_sim = sim
            best_offset = t_ms

    a = a[:best_offset + win_ms]
    return audio_engine.make_loopable(a, 100)


def _find_zero_cross_match(sig: np.ndarray, target_pos: int, search_radius: int) -> int:
    """Within +/- search_radius of target_pos, find sample index whose value is
    closest to sig[0] AND whose slope (sample-to-sample diff) sign matches.
    Returns absolute sample index.
    """
    n = len(sig)
    lo = max(1, target_pos - search_radius)
    hi = min(n - 2, target_pos + search_radius)
    target_val = sig[0]
    target_slope = sig[1] - sig[0]

    best_idx = target_pos
    best_score = float("inf")
    for i in range(lo, hi):
        val_diff = abs(sig[i] - target_val)
        slope_diff = abs((sig[i + 1] - sig[i]) - target_slope) * 0.5
        score = val_diff + slope_diff
        if score < best_score:
            best_score = score
            best_idx = i
    return best_idx


def strat_smart_loop(audio: AudioSegment) -> AudioSegment:
    """Production candidate: aggressive level trim + content-aware loop length +
    zero-crossing snap + tiny crossfade.

    Steps:
      1. Trim fade-out conservatively (only obvious silent tail)
      2. Trim fade-in until level is within 2 dB of body
      3. Find loop length L in back half where MFCC of audio[L-3s:L] is most
         similar to audio[0:3s] AND level matches within ~3 dB
      4. Snap L to a sample where audio[L] best matches audio[0] (zero-cross +
         slope match) to prevent micro-click
      5. Apply 50ms equal-power crossfade as final click insurance
    """
    a = audio_engine._trim_generated_fade_out(audio)

    # Step 2: aggressive head trim (within 2 dB of body)
    dur = len(a)
    body = a[dur // 4 : 3 * dur // 4]
    body_db = body.dBFS
    step = 250
    head_trim = 0
    for t in range(0, dur // 3, step):
        if _dbfs(a[t:t + 1000]) >= body_db - 2.0:
            head_trim = t
            break
    a = a[head_trim:]

    dur = len(a)
    if dur < 30_000:
        return audio_engine.make_loopable(a, 50)

    sr = a.frame_rate
    sig = _samples_float(a).astype(np.float32)

    # Step 3: content + level search in back 30-95% range
    win_ms = 3000
    win_samples = int(win_ms * sr / 1000)
    head_sig = sig[:win_samples]
    head_mfcc = librosa.feature.mfcc(y=head_sig, sr=sr, n_mfcc=13).mean(axis=1)
    head_rms = float(np.sqrt(np.mean(head_sig ** 2)) + 1e-9)

    search_start_ms = int(dur * 0.30)
    search_end_ms = dur - win_ms - 1
    step_ms = 500

    best_L_ms = dur
    best_score = -1.0
    for t_ms in range(search_start_ms, search_end_ms, step_ms):
        t_samp = int(t_ms * sr / 1000)
        chunk = sig[t_samp:t_samp + win_samples]
        if len(chunk) < win_samples:
            break
        chunk_rms = float(np.sqrt(np.mean(chunk ** 2)) + 1e-9)
        level_db_diff = abs(20 * np.log10(chunk_rms / head_rms))
        if level_db_diff > 3.0:
            continue
        m = librosa.feature.mfcc(y=chunk, sr=sr, n_mfcc=13).mean(axis=1)
        sim = _cosine(head_mfcc, m)
        # Combined: content similarity with light level penalty
        score = sim - level_db_diff * 0.01
        if score > best_score:
            best_score = score
            best_L_ms = t_ms + win_ms

    if best_score < 0:
        # No qualifying match. Fall back to aggressive level-match trim.
        tail_trim = 0
        for t in range(0, dur // 3, step):
            if _dbfs(a[dur - t - 1000:dur - t]) >= body_db - 2.0:
                tail_trim = t
                break
        if tail_trim:
            a = a[:dur - tail_trim]
    else:
        a = a[:best_L_ms]

    # Step 4: snap end to a sample whose value matches sig[0]
    sig2 = _samples_float(a).astype(np.float32)
    if len(sig2) > 200:
        snap_idx = _find_zero_cross_match(sig2, len(sig2) - 1, search_radius=min(2000, len(sig2) // 20))
        snap_ms = int(snap_idx * 1000 / sr)
        if snap_ms < len(a) - 5 and snap_ms > len(a) - 200:
            a = a[:snap_ms + 1]

    # Step 5: tiny final crossfade (50ms)
    return audio_engine.make_loopable(a, 50)


def strat_pymusiclooper(audio: AudioSegment, _path: Optional[str] = None) -> AudioSegment:
    """Use PyMusicLooper to find a musically clean loop pair (any length).
    Returns the trimmed loop body with a tiny click-safe crossfade.
    """
    from pymusiclooper.core import MusicLooper

    if _path is None:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp = f.name
        audio.export(tmp, format="wav")
        _path = tmp

    looper = MusicLooper(_path)
    try:
        pairs = looper.find_loop_pairs(min_loop_duration=30, max_loop_duration=300)
    except Exception:
        pairs = []
    if not pairs:
        return strat_aggressive_trim(audio)

    best = pairs[0]
    sr = audio.frame_rate
    start_ms = int(best.loop_start * 1000 / sr)
    end_ms = int(best.loop_end * 1000 / sr)
    looped = audio[start_ms:end_ms]
    return audio_engine.make_loopable(looped, 50)


def strat_long_loop_keep_fades(audio: AudioSegment, _path: Optional[str] = None) -> AudioSegment:
    """KEEP the music's natural fade-in and fade-out. Trim only dead-silent
    edges, then use PyMusicLooper hinted near both ends to find the exact best
    long-loop pair. Result preserves ~95% of the original audio length and
    loops cleanly in the naturally-quiet fade regions.
    """
    from pymusiclooper.core import MusicLooper

    if _path is None:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp = f.name
        audio.export(tmp, format="wav")
        _path = tmp

    # 1. Strip only dead silence (< -50 dBFS) from both ends
    a = audio
    step = 250
    n = len(a)
    head_silent_ms = 0
    for t in range(0, n // 4, step):
        if _dbfs(a[t:t + 1000]) >= -50.0:
            head_silent_ms = t
            break
    tail_silent_ms = 0
    for t in range(0, n // 4, step):
        if _dbfs(a[n - t - 1000:n - t]) >= -50.0:
            tail_silent_ms = t
            break
    a = a[head_silent_ms:n - tail_silent_ms] if tail_silent_ms else a[head_silent_ms:]
    trimmed_dur_s = len(a) / 1000

    # 2. Hint PyMusicLooper to look near the trimmed start and end
    if trimmed_dur_s < 60:
        return audio_engine.make_loopable(a, 50)

    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_trim = f.name
    a.export(tmp_trim, format="wav")

    looper = MusicLooper(tmp_trim)
    try:
        pairs = looper.find_loop_pairs(
            approx_loop_start=5.0,
            approx_loop_end=trimmed_dur_s - 5.0,
        )
    except Exception:
        pairs = []

    if not pairs:
        # Fall back to just-trimmed-silence + small crossfade
        return audio_engine.make_loopable(a, 50)

    best = pairs[0]
    sr = a.frame_rate
    start_ms = int(best.loop_start * 1000 / sr)
    end_ms = int(best.loop_end * 1000 / sr)
    looped = a[start_ms:end_ms]
    return audio_engine.make_loopable(looped, 50)


STRATEGIES: dict[str, Callable[[AudioSegment], AudioSegment]] = {
    "passthrough": strat_passthrough,
    "v3_current": strat_v3_current,
    "short_xfade": strat_short_xfade,
    "aggressive_trim": strat_aggressive_trim,
    "mfcc_loop_point": strat_mfcc_loop_point,
    "smart_loop": strat_smart_loop,
    "pymusiclooper": strat_pymusiclooper,
    "long_loop_keep_fades": strat_long_loop_keep_fades,
}


def _export_seam_demo(prepped: AudioSegment, raw_path: Optional[AudioSegment], out_path: str) -> None:
    """Write a listenable demo that puts the loop boundary at center.

    Format: [last 20s of prepped][first 20s of prepped] = 40s file, wrap at 0:20.
    Listener hears how the loop sounds when it wraps.
    """
    pre_seam_ms = min(20_000, len(prepped) // 2)
    post_seam_ms = min(20_000, len(prepped) // 2)
    demo = prepped[-pre_seam_ms:] + prepped[:post_seam_ms]
    demo.export(out_path, format="wav")


# -----------------------------------------------------------------------------
# Runner
# -----------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--strategy", choices=list(STRATEGIES.keys()), default=None,
                   help="Run a single strategy (default: all)")
    p.add_argument("--file", default=None, help="Specific raw file name (in generated_samples)")
    p.add_argument("--limit", type=int, default=8, help="Max files to test (default 8)")
    p.add_argument("--export", default=None, help="Directory to write prepped wavs for listening")
    p.add_argument("--min-size", type=int, default=10_000_000, help="Skip files smaller than this (bytes)")
    args = p.parse_args(argv)

    files = sorted(glob.glob(f"{SAMPLES_DIR}/*.wav"), key=os.path.getmtime, reverse=True)
    files = [f for f in files if os.path.getsize(f) >= args.min_size]

    if args.file:
        files = [f for f in files if args.file in f]
    files = files[: args.limit]

    if not files:
        print("No matching files found.")
        return 1

    strategies = [args.strategy] if args.strategy else list(STRATEGIES.keys())

    if args.export:
        os.makedirs(args.export, exist_ok=True)
        os.makedirs(os.path.join(args.export, "seam_demos"), exist_ok=True)
        os.makedirs(os.path.join(args.export, "full_prepped"), exist_ok=True)

    print(f"Testing {len(files)} files x {len(strategies)} strategies\n")

    summary: dict[str, list[SeamScore]] = {s: [] for s in strategies}

    for f in files:
        print(f"=== {os.path.basename(f)} ({os.path.getsize(f) / 1e6:.1f} MB) ===")
        try:
            raw = AudioSegment.from_file(f)
        except Exception as e:
            print(f"  FAIL load: {e}")
            continue
        print(f"  raw: dur={len(raw)/1000:.1f}s  body dBFS={raw[len(raw)//4:3*len(raw)//4].dBFS:.1f}")
        for sname in strategies:
            try:
                fn = STRATEGIES[sname]
                if sname in ("pymusiclooper", "long_loop_keep_fades"):
                    prepped = fn(raw, f)
                else:
                    prepped = fn(raw)
                score = score_seam(prepped)
                summary[sname].append(score)
                print(f"  {sname:>16}: {score}")
                if args.export:
                    base = os.path.splitext(os.path.basename(f))[0]
                    full_path = os.path.join(args.export, "full_prepped", f"{base}__{sname}.wav")
                    demo_path = os.path.join(args.export, "seam_demos", f"{base}__{sname}__SEAM.wav")
                    prepped.export(full_path, format="wav")
                    _export_seam_demo(prepped, raw, demo_path)
            except Exception as e:
                print(f"  {sname:>16}: ERROR {e}")
        print()

    # Aggregate
    print("=" * 80)
    print("AGGREGATE (mean across files)")
    print("=" * 80)
    print(f"{'strategy':<20} {'dur':>7} {'level':>8} {'click':>7} {'dip':>7} {'specSim':>8}")
    for sname, scores in summary.items():
        if not scores:
            continue
        dur = np.mean([s.duration_s for s in scores])
        level = np.mean([s.level_dB for s in scores])
        click = np.mean([s.click_pct for s in scores])
        dip = np.mean([s.body_dip_dB for s in scores])
        sim = np.mean([s.spectral_sim for s in scores])
        print(f"{sname:<20} {dur:>6.1f}s {level:>7.2f}dB {click:>5.2f}% {dip:>+6.2f}dB {sim:>7.3f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
