"""How much a take changes across its length. Cole 2026-11-18 on 043a31ef: "Its boring there is nothing changing about
it its the same flat drone the whole way". Splits the take into 10 s windows and measures: loudness swing (dB std),
brightness swing (spectral centroid std, in semitones), and novelty (mean distance between consecutive windows'
16-band spectra, plus distance from each window to the take's average). Higher is more movement.
usage: .venv/bin/python tools/movement.py <job_id>..."""
import sys, json
from pathlib import Path
import numpy as np, soundfile as sf
H = Path(__file__).resolve().parent.parent

def audio_for(jid):
    j = json.load(open(H / "saved_jobs" / f"{jid}.json"))
    for p in ((((j.get("config") or {}).get("layers") or [{}])[0].get("generated_audio_path")), j.get("raw_output_path")):
        if p:
            p = Path(p) if Path(p).is_absolute() else H / p
            if p.exists():
                return p
    return None

def movement(path):
    a, sr = sf.read(str(path), dtype="float32", always_2d=True)
    a = a.mean(1)
    w = 10 * sr
    n = len(a) // w
    bands = np.geomspace(40, 16000, 17)
    db, cent, spec = [], [], []
    for i in range(n):
        x = a[i * w:(i + 1) * w]
        rms = np.sqrt((x ** 2).mean()) + 1e-9
        db.append(20 * np.log10(rms))
        X = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
        f = np.fft.rfftfreq(len(x), 1 / sr)
        cent.append(12 * np.log2(((f * X).sum() / (X.sum() + 1e-12)) / 440 + 1e-9))
        e = np.array([X[(f >= lo) & (f < hi)].sum() for lo, hi in zip(bands[:-1], bands[1:])]) + 1e-12
        spec.append(10 * np.log10(e / e.sum()))
    db, cent, spec = np.array(db), np.array(cent), np.array(spec)
    body = slice(1, n - 1)   # skip the first and last window (fade in/out)
    step = np.abs(np.diff(spec[body], axis=0)).mean()
    spread = np.abs(spec[body] - spec[body].mean(0)).mean()
    return {"loud_std_db": round(float(db[body].std()), 2), "bright_std_st": round(float(cent[body].std()), 2),
            "step_db": round(float(step), 2), "spread_db": round(float(spread), 2)}

if __name__ == "__main__":
    for jid in sys.argv[1:]:
        p = audio_for(jid)
        print(jid, movement(p) if p else "no audio", flush=True)
