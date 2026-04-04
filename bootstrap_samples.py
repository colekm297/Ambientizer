"""
bootstrap_samples.py — Generate synthetic placeholder audio samples.

Creates a library of 30+ synthetic .wav samples using numpy/scipy for testing
the soundscape pipeline. These are not production quality — they're placeholder
sounds that are distinguishable from each other and correctly tagged.

Run:
    python bootstrap_samples.py

Creates:
    samples/base/    — continuous drones, noise textures, ambient beds
    samples/mid/     — periodic elements (birds, thunder, crickets, etc.)
    samples/detail/  — short accent sounds (drips, clicks, rustles)
    samples/musical/ — melodic/harmonic fragments
"""

import os
import numpy as np
from scipy import signal
from scipy.io import wavfile

SAMPLE_RATE = 44100


def ensure_dirs():
    for d in ["samples/base", "samples/mid", "samples/detail", "samples/musical"]:
        os.makedirs(d, exist_ok=True)


def normalize(audio, peak_db=-3.0):
    """Normalize audio to a target peak level in dB."""
    peak = np.max(np.abs(audio))
    if peak > 0:
        target = 10 ** (peak_db / 20)
        audio = audio * (target / peak)
    return np.clip(audio, -1.0, 1.0)


def fade(audio, fade_in_ms=50, fade_out_ms=50):
    """Apply fade in/out to avoid clicks."""
    fade_in_samples = int(SAMPLE_RATE * fade_in_ms / 1000)
    fade_out_samples = int(SAMPLE_RATE * fade_out_ms / 1000)
    if fade_in_samples > 0 and fade_in_samples < len(audio):
        audio[:fade_in_samples] *= np.linspace(0, 1, fade_in_samples)
    if fade_out_samples > 0 and fade_out_samples < len(audio):
        audio[-fade_out_samples:] *= np.linspace(1, 0, fade_out_samples)
    return audio


def save_wav(filename, audio):
    """Save float audio as 16-bit WAV."""
    audio = np.clip(audio, -1.0, 1.0)
    int_audio = (audio * 32767).astype(np.int16)
    wavfile.write(filename, SAMPLE_RATE, int_audio)
    print(f"  ✓ {filename} ({len(audio)/SAMPLE_RATE:.1f}s)")


def pink_noise(duration_sec):
    """Generate pink noise (1/f) using spectral shaping."""
    n = int(SAMPLE_RATE * duration_sec)
    white = np.random.randn(n)
    fft = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n, 1.0 / SAMPLE_RATE)
    freqs[0] = 1  # avoid division by zero
    fft *= 1.0 / np.sqrt(freqs)
    return np.fft.irfft(fft, n=n)


def brown_noise(duration_sec):
    """Generate brown noise (1/f^2) via cumulative sum of white noise."""
    n = int(SAMPLE_RATE * duration_sec)
    white = np.random.randn(n) * 0.02
    brown = np.cumsum(white)
    brown -= np.mean(brown)
    return brown


def filtered_noise(duration_sec, low_hz, high_hz):
    """Generate bandpass-filtered white noise."""
    n = int(SAMPLE_RATE * duration_sec)
    white = np.random.randn(n)
    nyq = SAMPLE_RATE / 2
    low = max(low_hz / nyq, 0.001)
    high = min(high_hz / nyq, 0.999)
    b, a = signal.butter(4, [low, high], btype='band')
    return signal.filtfilt(b, a, white)


def sine_drone(duration_sec, freq_hz, vibrato_hz=0.1, vibrato_depth=2.0):
    """Generate a sine wave drone with slow vibrato."""
    t = np.linspace(0, duration_sec, int(SAMPLE_RATE * duration_sec), endpoint=False)
    vibrato = vibrato_depth * np.sin(2 * np.pi * vibrato_hz * t)
    return np.sin(2 * np.pi * (freq_hz + vibrato) * t)


def pad_tone(duration_sec, freq_hz, harmonics=5, attack_sec=1.5, release_sec=1.5):
    """Generate a pad-like tone with harmonics and slow attack/release."""
    n = int(SAMPLE_RATE * duration_sec)
    t = np.linspace(0, duration_sec, n, endpoint=False)
    audio = np.zeros(n)
    for h in range(1, harmonics + 1):
        amp = 1.0 / (h ** 1.5)
        audio += amp * np.sin(2 * np.pi * freq_hz * h * t)
    # Envelope
    env = np.ones(n)
    atk = int(SAMPLE_RATE * attack_sec)
    rel = int(SAMPLE_RATE * release_sec)
    if atk > 0:
        env[:atk] = np.linspace(0, 1, atk)
    if rel > 0:
        env[-rel:] = np.linspace(1, 0, rel)
    return audio * env


def envelope_burst(duration_sec, freq_hz=None, attack_ms=20, decay_ms=500):
    """Generate an enveloped noise burst (like a thud or pop)."""
    n = int(SAMPLE_RATE * duration_sec)
    if freq_hz:
        t = np.linspace(0, duration_sec, n, endpoint=False)
        audio = np.sin(2 * np.pi * freq_hz * t)
    else:
        audio = np.random.randn(n)
    atk = int(SAMPLE_RATE * attack_ms / 1000)
    dec = int(SAMPLE_RATE * decay_ms / 1000)
    env = np.zeros(n)
    if atk > 0:
        env[:atk] = np.linspace(0, 1, atk)
    if atk + dec < n:
        env[atk:atk + dec] = np.linspace(1, 0, dec)
    return audio * env


def chirp_sound(duration_sec, start_hz, end_hz):
    """Generate a frequency sweep (chirp)."""
    t = np.linspace(0, duration_sec, int(SAMPLE_RATE * duration_sec), endpoint=False)
    return signal.chirp(t, start_hz, duration_sec, end_hz, method='logarithmic')


# ──────────────────────────────────────────────────────────
#  BASE layer samples
# ──────────────────────────────────────────────────────────

def generate_base_samples():
    print("\n🔊 Generating BASE layer samples...")

    # Wind textures
    audio = normalize(filtered_noise(8, 80, 800))
    save_wav("samples/base/wind_low.wav", fade(audio, 500, 500))

    audio = normalize(filtered_noise(8, 500, 4000))
    save_wav("samples/base/wind_high.wav", fade(audio, 500, 500))

    audio = normalize(filtered_noise(8, 200, 1200))
    save_wav("samples/base/desert_wind.wav", fade(audio, 500, 500))

    # Rain textures
    audio = normalize(filtered_noise(10, 2000, 12000) * 0.3 + filtered_noise(10, 200, 800) * 0.15)
    save_wav("samples/base/rain_light.wav", fade(audio, 500, 500))

    audio = normalize(filtered_noise(10, 1000, 15000) * 0.5 + pink_noise(10) * 0.3)
    save_wav("samples/base/rain_heavy.wav", fade(audio, 500, 500))

    # Rain on window: high-frequency crackle
    n = int(SAMPLE_RATE * 10)
    drops = np.random.randn(n) * 0.1
    drops[np.random.random(n) > 0.97] *= 8  # sparse loud drops
    b, a = signal.butter(3, [3000 / (SAMPLE_RATE/2), 10000 / (SAMPLE_RATE/2)], btype='band')
    drops = signal.filtfilt(b, a, drops)
    audio = normalize(drops + filtered_noise(10, 200, 600) * 0.2)
    save_wav("samples/base/rain_on_window.wav", fade(audio, 500, 500))

    # Water textures
    audio = normalize(filtered_noise(10, 100, 2000) * 0.5 + brown_noise(10) * 0.3)
    save_wav("samples/base/river_gentle.wav", fade(audio, 500, 500))

    # Ocean
    n = int(SAMPLE_RATE * 12)
    t = np.linspace(0, 12, n, endpoint=False)
    wave_mod = 0.3 + 0.7 * (np.sin(2 * np.pi * 0.08 * t) * 0.5 + 0.5)
    audio = normalize(brown_noise(12) * wave_mod)
    save_wav("samples/base/ocean_waves.wav", fade(audio, 500, 500))

    audio = normalize(filtered_noise(10, 50, 400) * 0.5)
    save_wav("samples/base/ocean_distant.wav", fade(audio, 500, 500))

    # Forest ambience: layered pink noise + faint high detail
    audio = normalize(pink_noise(10) * 0.4 + filtered_noise(10, 3000, 8000) * 0.1)
    save_wav("samples/base/forest_ambience.wav", fade(audio, 500, 500))

    # Urban
    audio = normalize(brown_noise(8) * 0.5 + filtered_noise(8, 50, 300) * 0.3)
    save_wav("samples/base/traffic_distant.wav", fade(audio, 500, 500))

    audio = normalize(filtered_noise(8, 50, 200) * 0.4 + sine_drone(8, 60, 0.05, 1) * 0.1)
    save_wav("samples/base/city_hum.wav", fade(audio, 500, 500))

    audio = normalize(filtered_noise(8, 200, 3000) * 0.2 + pink_noise(8) * 0.15)
    save_wav("samples/base/cafe_murmur.wav", fade(audio, 500, 500))

    audio = normalize(filtered_noise(8, 80, 400) * 0.3 + sine_drone(8, 100, 0.02, 0.5) * 0.1)
    save_wav("samples/base/room_tone_warm.wav", fade(audio, 500, 500))

    audio = normalize(filtered_noise(8, 300, 2000) * 0.2)
    save_wav("samples/base/room_tone_cold.wav", fade(audio, 500, 500))

    audio = normalize(sine_drone(8, 60, 0.0, 0) * 0.3 + filtered_noise(8, 55, 65) * 0.5)
    save_wav("samples/base/hvac_hum.wav", fade(audio, 500, 500))

    audio = normalize(brown_noise(8) * 0.3 + filtered_noise(8, 30, 150) * 0.4)
    save_wav("samples/base/subway_distant.wav", fade(audio, 500, 500))

    # Synth pads and drones
    save_wav("samples/base/pad_warm.wav", fade(normalize(pad_tone(10, 130, 6, 2, 2)), 200, 200))
    save_wav("samples/base/pad_dark.wav", fade(normalize(pad_tone(10, 65, 4, 2, 2)), 200, 200))
    save_wav("samples/base/pad_ethereal.wav", fade(normalize(pad_tone(10, 330, 8, 2.5, 2.5)), 200, 200))
    save_wav("samples/base/pad_bright.wav", fade(normalize(pad_tone(10, 440, 6, 1.5, 1.5)), 200, 200))

    save_wav("samples/base/drone_low.wav", fade(normalize(sine_drone(10, 55, 0.1, 3)), 500, 500))
    save_wav("samples/base/drone_mid.wav", fade(normalize(sine_drone(10, 220, 0.15, 5)), 500, 500))

    # Evolving drone: slow frequency modulation
    t = np.linspace(0, 12, int(SAMPLE_RATE * 12), endpoint=False)
    freq_mod = 110 + 30 * np.sin(2 * np.pi * 0.05 * t)
    audio = np.sin(2 * np.pi * np.cumsum(freq_mod / SAMPLE_RATE))
    save_wav("samples/base/drone_evolving.wav", fade(normalize(audio), 500, 500))

    save_wav("samples/base/noise_pink.wav", fade(normalize(pink_noise(8)), 500, 500))
    save_wav("samples/base/noise_brown.wav", fade(normalize(brown_noise(8)), 500, 500))


# ──────────────────────────────────────────────────────────
#  MID layer samples
# ──────────────────────────────────────────────────────────

def generate_mid_samples():
    print("\n🔊 Generating MID layer samples...")

    # Birds — chirp patterns
    dur = 3.0
    n = int(SAMPLE_RATE * dur)
    audio = np.zeros(n)
    for _ in range(6):
        start = int(np.random.uniform(0.1, dur - 0.5) * SAMPLE_RATE)
        chirp_dur = np.random.uniform(0.1, 0.4)
        chirp_n = int(SAMPLE_RATE * chirp_dur)
        if start + chirp_n < n:
            f0 = np.random.uniform(2000, 4000)
            f1 = np.random.uniform(3000, 6000)
            t = np.linspace(0, chirp_dur, chirp_n, endpoint=False)
            c = np.sin(2 * np.pi * (f0 + (f1 - f0) * t / chirp_dur) * t)
            env = np.exp(-3 * t / chirp_dur)
            audio[start:start + chirp_n] += c * env * 0.5
    save_wav("samples/mid/birds_morning.wav", fade(normalize(audio), 50, 50))

    # Evening birds — lower, slower
    audio = np.zeros(n)
    for _ in range(3):
        start = int(np.random.uniform(0.2, dur - 0.6) * SAMPLE_RATE)
        chirp_dur = np.random.uniform(0.2, 0.6)
        chirp_n = int(SAMPLE_RATE * chirp_dur)
        if start + chirp_n < n:
            f0 = np.random.uniform(1500, 2500)
            f1 = np.random.uniform(1000, 2000)
            t = np.linspace(0, chirp_dur, chirp_n, endpoint=False)
            c = np.sin(2 * np.pi * (f0 + (f1 - f0) * t / chirp_dur) * t)
            env = np.exp(-2 * t / chirp_dur)
            audio[start:start + chirp_n] += c * env * 0.4
    save_wav("samples/mid/birds_evening.wav", fade(normalize(audio), 50, 50))

    # Owl call
    dur = 2.0
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    hoot1 = np.sin(2 * np.pi * 350 * t) * np.exp(-5 * (t - 0.3)**2)
    hoot2 = np.sin(2 * np.pi * 320 * t) * np.exp(-5 * (t - 1.0)**2)
    save_wav("samples/mid/owl_call.wav", fade(normalize(hoot1 + hoot2), 30, 30))

    # Crickets — rapid amplitude-modulated tone
    dur = 5.0
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    carrier = np.sin(2 * np.pi * 4500 * t)
    modulator = 0.5 + 0.5 * np.sign(np.sin(2 * np.pi * 15 * t))
    env_slow = 0.5 + 0.5 * np.sin(2 * np.pi * 0.3 * t)
    save_wav("samples/mid/crickets.wav", fade(normalize(carrier * modulator * env_slow * 0.3), 200, 200))

    # Frogs
    dur = 4.0
    n = int(SAMPLE_RATE * dur)
    audio = np.zeros(n)
    for _ in range(5):
        start = int(np.random.uniform(0.1, dur - 0.4) * SAMPLE_RATE)
        croak_n = int(SAMPLE_RATE * 0.2)
        if start + croak_n < n:
            t = np.linspace(0, 0.2, croak_n, endpoint=False)
            croak = np.sin(2 * np.pi * np.random.uniform(200, 500) * t)
            croak *= np.exp(-10 * t)
            audio[start:start + croak_n] += croak * 0.4
    save_wav("samples/mid/frogs.wav", fade(normalize(audio), 50, 50))

    # Thunder distant
    dur = 4.0
    audio = brown_noise(dur)
    n = len(audio)
    env = np.exp(-np.linspace(0, 5, n))
    b, a = signal.butter(3, 200 / (SAMPLE_RATE / 2), btype='low')
    audio = signal.filtfilt(b, a, audio * env)
    save_wav("samples/mid/thunder_distant.wav", fade(normalize(audio), 50, 200))

    # Thunder close
    dur = 3.0
    audio = np.random.randn(int(SAMPLE_RATE * dur))
    n = len(audio)
    env = np.exp(-np.linspace(0, 3, n))
    b, a = signal.butter(3, 500 / (SAMPLE_RATE / 2), btype='low')
    audio = signal.filtfilt(b, a, audio * env)
    save_wav("samples/mid/thunder_close.wav", fade(normalize(audio), 10, 200))

    # Café sounds
    dur = 2.0
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    clink = np.sin(2 * np.pi * 3200 * t) * np.exp(-30 * t)
    clink2 = np.sin(2 * np.pi * 4800 * t) * np.exp(-25 * (t - 0.15)) * (t > 0.15).astype(float)
    save_wav("samples/mid/cafe_clink.wav", fade(normalize(clink + clink2 * 0.5), 5, 50))

    # Clock tick
    dur = 2.0
    n = int(SAMPLE_RATE * dur)
    audio = np.zeros(n)
    for tick_time in [0.0, 1.0]:
        start = int(tick_time * SAMPLE_RATE)
        click_n = int(0.01 * SAMPLE_RATE)
        if start + click_n < n:
            t = np.linspace(0, 0.01, click_n, endpoint=False)
            audio[start:start + click_n] += np.sin(2 * np.pi * 2000 * t) * np.exp(-300 * t)
    save_wav("samples/mid/clock_tick.wav", fade(normalize(audio), 5, 5))

    # Vinyl crackle
    dur = 5.0
    n = int(SAMPLE_RATE * dur)
    crackle = np.zeros(n)
    pops = np.random.random(n) > 0.999
    crackle[pops] = np.random.randn(np.sum(pops)) * 0.5
    b, a = signal.butter(3, [500 / (SAMPLE_RATE/2), 8000 / (SAMPLE_RATE/2)], btype='band')
    crackle = signal.filtfilt(b, a, crackle)
    crackle += np.random.randn(n) * 0.005
    save_wav("samples/mid/vinyl_crackle.wav", fade(normalize(crackle), 100, 100))

    # Keyboard typing
    dur = 3.0
    n = int(SAMPLE_RATE * dur)
    audio = np.zeros(n)
    for _ in range(12):
        start = int(np.random.uniform(0.05, dur - 0.1) * SAMPLE_RATE)
        click_n = int(0.015 * SAMPLE_RATE)
        if start + click_n < n:
            t = np.linspace(0, 0.015, click_n, endpoint=False)
            click = np.random.randn(click_n) * np.exp(-200 * t)
            audio[start:start + click_n] += click * 0.3
    save_wav("samples/mid/keyboard_typing.wav", fade(normalize(audio), 20, 20))

    # Chimes
    dur = 4.0
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    freqs = [523, 659, 784, 880]  # C5, E5, G5, A5
    audio = np.zeros(n)
    for i, f in enumerate(freqs):
        onset = i * 0.6
        tone = np.sin(2 * np.pi * f * t) * np.exp(-2 * np.maximum(t - onset, 0)) * (t >= onset).astype(float)
        audio += tone * 0.3
    save_wav("samples/mid/chimes_wind.wav", fade(normalize(audio), 30, 200))

    # Singing bowl
    dur = 6.0
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    fundamental = 320
    audio = (np.sin(2 * np.pi * fundamental * t) * 0.5 +
             np.sin(2 * np.pi * fundamental * 2.71 * t) * 0.3 +
             np.sin(2 * np.pi * fundamental * 4.16 * t) * 0.15)
    audio *= np.exp(-0.4 * t)
    save_wav("samples/mid/singing_bowl.wav", fade(normalize(audio), 10, 100))

    # Bells distant
    dur = 3.0
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    bell = (np.sin(2 * np.pi * 800 * t) + 0.5 * np.sin(2 * np.pi * 1200 * t) +
            0.3 * np.sin(2 * np.pi * 1600 * t)) * np.exp(-1.5 * t)
    b, a = signal.butter(2, 2000 / (SAMPLE_RATE / 2), btype='low')
    bell = signal.filtfilt(b, a, bell)
    save_wav("samples/mid/bells_distant.wav", fade(normalize(bell), 10, 100))


# ──────────────────────────────────────────────────────────
#  DETAIL layer samples
# ──────────────────────────────────────────────────────────

def generate_detail_samples():
    print("\n🔊 Generating DETAIL layer samples...")

    # Twig snap
    dur = 0.3
    n = int(SAMPLE_RATE * dur)
    snap = np.random.randn(n) * np.exp(-50 * np.linspace(0, dur, n))
    b, a = signal.butter(3, [500 / (SAMPLE_RATE/2), 6000 / (SAMPLE_RATE/2)], btype='band')
    snap = signal.filtfilt(b, a, snap)
    save_wav("samples/detail/twig_snap.wav", normalize(snap))

    # Leaf rustle
    dur = 0.8
    n = int(SAMPLE_RATE * dur)
    rustle = filtered_noise(dur, 2000, 10000)
    env = np.exp(-4 * np.linspace(0, dur, n))
    save_wav("samples/detail/leaf_rustle.wav", normalize(rustle * env))

    # Water drip
    dur = 0.5
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    drip = np.sin(2 * np.pi * 1800 * t) * np.exp(-20 * t)
    drip += np.sin(2 * np.pi * 3600 * t) * np.exp(-25 * t) * 0.3
    save_wav("samples/detail/water_drip.wav", normalize(drip))

    # Single bird chirp
    dur = 0.4
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    chirp = signal.chirp(t, 3000, dur, 5000) * np.exp(-6 * t)
    save_wav("samples/detail/bird_single.wav", normalize(chirp))

    # Insect buzz
    dur = 1.0
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    buzz = np.sin(2 * np.pi * 200 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 50 * t))
    env = np.ones(n)
    env[:int(0.05 * SAMPLE_RATE)] = np.linspace(0, 1, int(0.05 * SAMPLE_RATE))
    env[-int(0.1 * SAMPLE_RATE):] = np.linspace(1, 0, int(0.1 * SAMPLE_RATE))
    save_wav("samples/detail/insect_buzz.wav", normalize(buzz * env))

    # Pine creak
    dur = 1.5
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    creak = signal.chirp(t, 150, dur, 80) * np.exp(-2 * t) * 0.5
    creak += filtered_noise(dur, 100, 600) * np.exp(-3 * t) * 0.3
    save_wav("samples/detail/pine_creak.wav", normalize(creak))

    # Small splash
    dur = 0.6
    n = int(SAMPLE_RATE * dur)
    splash = np.random.randn(n) * np.exp(-8 * np.linspace(0, dur, n))
    b, a = signal.butter(3, [300 / (SAMPLE_RATE/2), 5000 / (SAMPLE_RATE/2)], btype='band')
    splash = signal.filtfilt(b, a, splash)
    save_wav("samples/detail/splash_small.wav", normalize(splash))

    # Cup set down
    dur = 0.3
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    thud = (np.sin(2 * np.pi * 400 * t) + 0.5 * np.sin(2 * np.pi * 800 * t)) * np.exp(-30 * t)
    save_wav("samples/detail/cup_set_down.wav", normalize(thud))

    # Page turn
    dur = 0.5
    n = int(SAMPLE_RATE * dur)
    page = filtered_noise(dur, 3000, 12000) * np.exp(-6 * np.linspace(0, dur, n))
    save_wav("samples/detail/page_turn.wav", normalize(page))

    # Chair creak
    dur = 0.8
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    creak = signal.chirp(t, 200, dur, 400) * np.exp(-3 * t)
    save_wav("samples/detail/chair_creak.wav", normalize(creak))

    # Spoon stir
    dur = 1.5
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    stir = np.sin(2 * np.pi * 2500 * t) * (0.3 + 0.7 * np.abs(np.sin(2 * np.pi * 2 * t)))
    stir *= np.exp(-1 * t)
    save_wav("samples/detail/spoon_stir.wav", normalize(stir * 0.3))

    # Sparkle
    dur = 0.6
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    sparkle = (np.sin(2 * np.pi * 6000 * t) * 0.3 +
               np.sin(2 * np.pi * 8000 * t) * 0.2 +
               np.sin(2 * np.pi * 12000 * t) * 0.1) * np.exp(-5 * t)
    save_wav("samples/detail/sparkle.wav", normalize(sparkle))

    # Shimmer
    dur = 2.0
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    shimmer = np.zeros(n)
    for f in [4000, 5000, 6000, 7500]:
        shimmer += np.sin(2 * np.pi * f * t + np.random.uniform(0, 2*np.pi)) * np.exp(-1.5 * t) * 0.2
    save_wav("samples/detail/shimmer.wav", normalize(shimmer))

    # Echo distant
    dur = 2.0
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    click = np.zeros(n)
    click[:int(0.01*SAMPLE_RATE)] = np.sin(2 * np.pi * 1000 * t[:int(0.01*SAMPLE_RATE)])
    echoed = np.zeros(n)
    for delay_ms, amp in [(0, 0.6), (200, 0.3), (450, 0.15), (750, 0.07)]:
        d = int(delay_ms * SAMPLE_RATE / 1000)
        if d < n:
            echoed[d:] += click[:n - d] * amp
    b, a = signal.butter(2, 3000 / (SAMPLE_RATE / 2), btype='low')
    echoed = signal.filtfilt(b, a, echoed)
    save_wav("samples/detail/echo_distant.wav", normalize(echoed))

    # Whisper wind
    dur = 1.5
    n = int(SAMPLE_RATE * dur)
    wind = filtered_noise(dur, 1000, 6000)
    env = np.sin(np.pi * np.linspace(0, 1, n)) ** 2
    save_wav("samples/detail/whisper_wind.wav", normalize(wind * env * 0.5))


# ──────────────────────────────────────────────────────────
#  MUSICAL layer samples
# ──────────────────────────────────────────────────────────

def generate_musical_samples():
    print("\n🔊 Generating MUSICAL layer samples...")

    # Piano gentle — a few soft notes
    dur = 6.0
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    notes = [(262, 0.0), (330, 1.2), (392, 2.4), (330, 3.6)]  # C4, E4, G4, E4
    audio = np.zeros(n)
    for freq, onset in notes:
        mask = (t >= onset).astype(float)
        note = np.sin(2 * np.pi * freq * t) * np.exp(-1.5 * np.maximum(t - onset, 0)) * mask
        note += 0.3 * np.sin(2 * np.pi * freq * 2 * t) * np.exp(-2 * np.maximum(t - onset, 0)) * mask
        audio += note * 0.3
    save_wav("samples/musical/piano_gentle.wav", fade(normalize(audio), 30, 200))

    # Guitar ambient — harmonics
    dur = 5.0
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    audio = np.zeros(n)
    harmonics_freqs = [196, 294, 392, 494]  # G3, D4, G4, B4
    for i, freq in enumerate(harmonics_freqs):
        onset = i * 0.8
        mask = (t >= onset).astype(float)
        note = np.sin(2 * np.pi * freq * t) * np.exp(-0.8 * np.maximum(t - onset, 0)) * mask
        audio += note * 0.25
    save_wav("samples/musical/guitar_ambient.wav", fade(normalize(audio), 30, 200))

    # Music box
    dur = 5.0
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    notes = [(523, 0.0), (659, 0.4), (784, 0.8), (659, 1.2), (523, 1.6),
             (784, 2.4), (1047, 3.0), (784, 3.6)]
    audio = np.zeros(n)
    for freq, onset in notes:
        mask = (t >= onset).astype(float)
        note = np.sin(2 * np.pi * freq * t) * np.exp(-3 * np.maximum(t - onset, 0)) * mask
        audio += note * 0.25
    save_wav("samples/musical/music_box.wav", fade(normalize(audio), 10, 100))

    # Flute breathy
    dur = 4.0
    n = int(SAMPLE_RATE * dur)
    t = np.linspace(0, dur, n, endpoint=False)
    tone = np.sin(2 * np.pi * 587 * t) * 0.5  # D5
    breath = filtered_noise(dur, 1000, 5000) * 0.15
    env = np.sin(np.pi * t / dur) ** 0.5
    save_wav("samples/musical/flute_breathy.wav", fade(normalize((tone + breath) * env), 100, 200))


# ──────────────────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("🎛️ Bootstrapping synthetic sample library...")
    ensure_dirs()
    generate_base_samples()
    generate_mid_samples()
    generate_detail_samples()
    generate_musical_samples()

    # Count generated files
    count = 0
    for root, dirs, files in os.walk("samples"):
        count += sum(1 for f in files if f.endswith(".wav"))
    print(f"\n✅ Generated {count} synthetic samples in samples/")
