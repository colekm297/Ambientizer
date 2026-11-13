"""Kit v2 for the Practice Room: notes chosen where the piano is quietest, with a bleed score on every cut.
Reads the 6-stem demucs split (htdemucs_6s) and writes <K>/samples-v2/ beside the old kit, which stays untouched.

  horn  55-77  from other.wav (melody notes at or above G3)
  cello 36-53  from other.wav (below G3)
  pad   24-43  from bass.wav
  texture      one-shots from guitar+vocals+drums, no piano, on C4..F4

bleed_db = level of everything else in the mix (piano weighted double) under the note, relative to the note's own stem,
in dB over the note's span. Lower is cleaner: -20 is clean, 0 means the leak is as loud as the note.
Also penalised: other notes sounding in the same stem at the same time (the note isn't alone).
Rerunnable: every file is cut fresh from the stems.
usage: tools/stems-venv/bin/python tools/cut_samples_v2.py output/keys/<job>"""
import sys, json
from pathlib import Path
import numpy as np, soundfile as sf
from scipy.signal import resample_poly
from basic_pitch.inference import predict
from basic_pitch import ICASSP_2022_MODEL_PATH

K = Path(sys.argv[1]); OUT = K / "samples-v2"; OUT.mkdir(exist_ok=True)
D = next((K / "_demucs" / "htdemucs_6s").iterdir())
SR = 48000
NAMES = "C C# D D# E F F# G G# A A# B".split()
def nn(p): return f"{NAMES[p % 12]}{p // 12 - 1}"

stems = {}
for name in ("other", "bass", "piano", "guitar", "vocals", "drums"):
    a, sr = sf.read(D / f"{name}.wav", dtype="float32", always_2d=True)
    if sr != SR:
        a = resample_poly(a, SR // 100, sr // 100, axis=0).astype("float32")
    stems[name] = a
n = min(len(a) for a in stems.values())
stems = {k: v[:n] for k, v in stems.items()}

def rms(a): return float(np.sqrt((a.astype("float64") ** 2).mean()) + 1e-9)

def bleed_db(stem, a, b):
    own = rms(stems[stem][a:b])
    rest = [k for k in stems if k != stem]
    # Piano counts double: it's the leak Cole hears under every note.
    leak = np.sqrt(sum((2 if k == "piano" else 1) * rms(stems[k][a:b]) ** 2 for k in rest))
    return round(20 * np.log10(leak / own), 1)

def candidates(stem, lo, hi):
    tmp = OUT / f"_{stem}.wav"; sf.write(tmp, stems[stem], SR)
    _, _, notes = predict(str(tmp), ICASSP_2022_MODEL_PATH, onset_threshold=0.5, frame_threshold=0.3,
                          minimum_note_length=1200)
    tmp.unlink()
    notes = [(float(s), float(e), int(p), float(amp)) for s, e, p, amp, _ in notes]
    best = {}
    for s, e, p, amp in notes:
        dur = e - s
        if dur < 1.5 or not lo <= p <= hi:
            continue
        a, b = int(s * SR), int(e * SR)
        bl = bleed_db(stem, a, b)
        overlap = sum(1 for s2, e2, p2, _ in notes if p2 != p and s2 < e - 0.3 and e2 > s + 0.3)
        score = bl + 3 * overlap - 4 * np.log2(min(dur, 6))   # lower is better
        if p not in best or score < best[p]["score"]:
            best[p] = {"score": round(float(score), 1), "s": s, "e": e, "bleed_db": bl, "overlap": overlap, "amp": round(amp, 2)}
    return best

def cut(stem, p, c, prefix):
    a, b = int(max(0, c["s"] - 0.03) * SR), int(min(c["e"] + 0.6, n / SR) * SR)
    clip = stems[stem][a:b].copy()
    fi, fo = int(0.01 * SR), int(0.5 * SR)
    clip[:fi] *= np.linspace(0, 1, fi)[:, None]; clip[-fo:] *= np.linspace(1, 0, fo)[:, None]
    clip *= 0.89 / (np.abs(clip).max() or 1)
    # Baked crossfade loop between 30% and 80% so a held key sustains.
    m = len(clip); ls, le = int(m * 0.30), int(m * 0.80); x = min(int(0.25 * SR), ls, (le - ls) // 3)
    if le - ls >= SR * 0.5:
        f = np.linspace(0, 1, x)[:, None]
        clip[le - x:le] = clip[le - x:le] * (1 - f) + clip[ls - x:ls] * f
    else:
        ls = le = None
    name = f"{prefix}_{nn(p)}.wav"; sf.write(OUT / name, clip, SR, subtype="PCM_24")
    return {"file": name, "root": p, "loop_start": ls, "loop_end": le, "gain_db": 0, "tune_cents": 0,
            "bleed_db": c["bleed_db"], "overlap": c["overlap"], "at_sec": round(c["s"], 2), "sec": round(m / SR, 2)}

def zones(stem, prefix, lo, hi):
    best = candidates(stem, lo, hi)
    zs = [cut(stem, p, best[p], prefix) for p in sorted(best)]
    for i, z in enumerate(zs):
        z["lo"] = lo if i == 0 else (zs[i - 1]["root"] + z["root"]) // 2 + 1
        z["hi"] = hi if i == len(zs) - 1 else (z["root"] + zs[i + 1]["root"]) // 2
    return zs

inst = [
    {"name": "Horn", "id": "horn", "kind": "note", "sustain": True, "release_sec": 1.2, "zones": zones("other", "horn", 55, 77)},
    {"name": "Cello", "id": "cello", "kind": "note", "sustain": True, "release_sec": 1.2, "zones": zones("other", "cello", 36, 53)},
    {"name": "Pad", "id": "pad", "kind": "note", "sustain": True, "release_sec": 2.0, "zones": zones("bass", "pad", 24, 43)},
]

# Texture: guitar + vocals + drums (no piano), the 6 8-second windows where the piano is quietest against it, 30 s apart.
t = stems["guitar"] + stems["vocals"] + stems["drums"]
w = 8 * SR; cands = []
for i in range(0, n - w, SR):
    own = rms(t[i:i + w])
    if own < 0.003:
        continue
    cands.append((20 * np.log10(rms(stems["piano"][i:i + w]) / own), i // SR))
picks = []
for bl, i in sorted(cands):
    if all(abs(i - p) >= 30 for _, p in picks): picks.append((bl, i))
    if len(picks) == 6: break
tz = []
for k, (bl, p) in enumerate(sorted(picks, key=lambda x: x[1])):
    c = t[p * SR:p * SR + w].copy(); fo = int(1.5 * SR)
    c[:int(.05 * SR)] *= np.linspace(0, 1, int(.05 * SR))[:, None]; c[-fo:] *= np.linspace(1, 0, fo)[:, None]
    c *= 0.7 / (np.abs(c).max() or 1); name = f"texture_{k + 1}.wav"; sf.write(OUT / name, c, SR, subtype="PCM_24")
    root = 60 + k
    tz.append({"file": name, "root": root, "lo": root, "hi": root, "loop_start": None, "loop_end": None, "gain_db": 0,
               "tune_cents": 0, "bleed_db": round(float(bl), 1), "at_sec": p, "sec": 8.0})
inst.append({"name": "Texture", "id": "texture", "kind": "note", "sustain": False, "release_sec": 0.3, "zones": tz})

json.dump({"piece": K.name, "version": 2, "sample_rate": SR,
           "note": "Cut from the 6-stem split with notes chosen where the piano is quietest. bleed_db per zone: everything "
                   "else under the note (piano weighted double) relative to the note, lower is cleaner, -20 clean, 0 as "
                   "loud as the note. overlap: other notes sounding in the same stem. Texture has no piano in it.",
           "instruments": inst}, open(OUT / "samples.json", "w"), indent=1, default=float)
for i in inst:
    print(f"{i['id']:8} {len(i['zones']):2} zones  " + " ".join(f"{nn(z['root'])}:{z['bleed_db']}" for z in i["zones"]))
