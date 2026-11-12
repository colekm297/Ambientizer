"""Turn cut_samples output into Music Director's samples.json: horn (>=G3) / cello (<G3) from the melody stem, pad, texture one-shots.
Short notes get a baked crossfade loop so a held key sustains."""
import sys, json
from pathlib import Path
import numpy as np, soundfile as sf
K = Path(sys.argv[1]); S = K / "samples"
rows = json.load(open(S / "samples.json")) if isinstance(json.load(open(S / "samples.json")), list) else json.load(open(S / "samples.json"))["_cuts"]
def loopify(name):
    a, sr = sf.read(S / name, dtype="float32", always_2d=True)
    n = len(a); ls, le = int(n * 0.30), int(n * 0.80); x = min(int(0.25 * sr), ls, (le - ls) // 3)
    if le - ls < sr * 0.5: return None, None, n / sr
    f = np.linspace(0, 1, x)[:, None]
    a[le - x:le] = a[le - x:le] * (1 - f) + a[ls - x:ls] * f
    sf.write(S / name, a, sr, subtype="PCM_24"); return ls, le, n / sr
def zones(rs):
    rs = sorted(rs, key=lambda r: r["midi"]); out = []
    for i, r in enumerate(rs):
        lo = max(21, r["midi"] - 6) if i == 0 else (rs[i-1]["midi"] + r["midi"]) // 2 + 1
        hi = min(108, r["midi"] + 6) if i == len(rs) - 1 else (r["midi"] + rs[i+1]["midi"]) // 2
        ls, le, _ = loopify(r["file"])
        out.append({"file": r["file"], "root": r["midi"], "lo": lo, "hi": hi, "loop_start": ls, "loop_end": le, "gain_db": 0, "tune_cents": 0})
    return out
mel = [r for r in rows if r["stem"] == "melody"]
inst = [
  {"name": "Horn", "id": "horn", "kind": "note", "sustain": True, "release_sec": 1.2, "zones": zones([r for r in mel if r["midi"] >= 55])},
  {"name": "Cello", "id": "cello", "kind": "note", "sustain": True, "release_sec": 1.2, "zones": zones([r for r in mel if r["midi"] < 55])},
  {"name": "Pad", "id": "pad", "kind": "note", "sustain": True, "release_sec": 2.0, "zones": zones([r for r in rows if r["stem"] == "pad"])},
]
# texture one-shots: the 6 loudest 8 s windows of texture.wav, 30 s apart
t, sr = sf.read(K / "stems" / "texture.wav", dtype="float32", always_2d=True)
w = 8 * sr; rms = [float(np.sqrt((t[i:i+w] ** 2).mean())) for i in range(0, len(t) - w, sr)]
picks = []
for i in np.argsort(rms)[::-1]:
    if all(abs(i - p) >= 30 for p in picks): picks.append(int(i))
    if len(picks) == 6: break
tz = []
for k, p in enumerate(sorted(picks)):
    c = t[p*sr:p*sr+w].copy(); fo = int(1.5*sr); c[:int(.05*sr)] *= np.linspace(0,1,int(.05*sr))[:,None]; c[-fo:] *= np.linspace(1,0,fo)[:,None]
    c *= 0.7 / (np.abs(c).max() or 1); name = f"texture_{k+1}.wav"; sf.write(S / name, c, sr, subtype="PCM_24")
    root = 60 + k; tz.append({"file": name, "root": root, "lo": root, "hi": root, "loop_start": None, "loop_end": None, "gain_db": 0, "tune_cents": 0})
inst.append({"name": "Texture", "id": "texture", "kind": "note", "sustain": False, "release_sec": 0.3, "zones": tz})
json.dump({"piece": "fc002c6a", "note": "Cut from demucs stems of a finished mix: horn and cello bleed into each other; detected pitch is the strongest note, others may sound under it. Texture one-shots sit on C4..F4.", "instruments": inst, "_cuts": rows}, open(S / "samples.json", "w"), indent=1, default=float)
for i in inst: print(i["id"], len(i["zones"]), [z["root"] for z in i["zones"]])
