#!/usr/bin/env python3
"""beat_check.py: does a take have a beat? Free, local, no Gemini.

Cole, 2026-11-03, on the first private draft (Rain Over Arrakis): "the beat in it is just bad." His keepers
are beatless (see the screen list in stock_campaign.SCREEN). Two numbers from librosa over the first 4
minutes: perc = share of energy in the percussive half of a harmonic/percussive split, and pulse = how
strongly the onset curve repeats at one tempo (peak of the normalized onset autocorrelation between
40 and 180 BPM). A take with a steady beat scores high on both.
Usage: .venv/bin/python beat_check.py <wav> [<wav> ...]
"""
from __future__ import annotations

import sys

import numpy as np


def beat_scores(path: str, seconds: float = 240.0) -> dict:
    import librosa
    y, sr = librosa.load(path, sr=22050, mono=True, duration=seconds)
    h, p = librosa.effects.hpss(y)
    perc = float(np.sum(p ** 2) / (np.sum(h ** 2) + np.sum(p ** 2) + 1e-12))
    env = librosa.onset.onset_strength(y=y, sr=sr)
    env = env - env.mean()
    ac = np.correlate(env, env, mode="full")[len(env) - 1:]
    ac /= ac[0] + 1e-12
    fps = sr / 512
    lo, hi = int(fps * 60 / 180), int(fps * 60 / 40)
    pulse = float(ac[lo:hi].max())
    return {"perc": round(perc, 3), "pulse": round(pulse, 3)}


if __name__ == "__main__":
    for f in sys.argv[1:]:
        print(beat_scores(f), f)
