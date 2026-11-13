"""A kit from the solo takes (one instrument per take, nothing else in the mix, so no piano to bleed).
Same samples.json format and zone ranges as samples-v2. bleed_db here is other notes ringing in the take under the
chosen note (reverb tails, a second voice), relative to the note: lower is cleaner.
usage: tools/stems-venv/bin/python tools/cut_samples_solo.py output/keys/<job> horn=<wav> cello=<wav> pad=<wav>"""
import sys, json
from pathlib import Path
import numpy as np, soundfile as sf
from scipy.signal import resample_poly
from basic_pitch.inference import predict
from basic_pitch import ICASSP_2022_MODEL_PATH

K = Path(sys.argv[1]); OUT = K / "samples-solo"; OUT.mkdir(exist_ok=True)
SRC = dict(a.split("=", 1) for a in sys.argv[2:])
SR = 48000
RANGES = {"horn": (55, 77), "cello": (36, 53), "pad": (24, 43)}
NAMES = "C C# D D# E F F# G G# A A# B".split()
def nn(p): return f"{NAMES[p % 12]}{p // 12 - 1}"
def rms(a): return float(np.sqrt((a.astype("float64") ** 2).mean()) + 1e-9)

def kit(inst, wav):
    lo, hi = RANGES[inst]
    a, sr = sf.read(wav, dtype="float32", always_2d=True)
    if sr != SR:
        a = resample_poly(a, SR // 100, sr // 100, axis=0).astype("float32")
    tmp = OUT / f"_{inst}.wav"; sf.write(tmp, a, SR)
    _, _, notes = predict(str(tmp), ICASSP_2022_MODEL_PATH, onset_threshold=0.5, frame_threshold=0.3, minimum_note_length=1200)
    tmp.unlink()
    notes = [(float(s), float(e), int(p), float(amp)) for s, e, p, amp, _ in notes]
    best = {}
    for s, e, p, amp in notes:
        dur = e - s
        # Fold octaves into range: a pad note an octave out still roots a zone once transposed by the player.
        if dur < 1.5 or not lo <= p <= hi:
            continue
        others = [(s2, e2, a2) for s2, e2, p2, a2 in notes if p2 != p and s2 < e - 0.3 and e2 > s + 0.3]
        under = sum(a2 for *_, a2 in others) / (amp or 1)
        bl = round(20 * np.log10(under + 1e-3), 1)
        score = bl + 3 * len(others) - 4 * np.log2(min(dur, 6))
        if p not in best or score < best[p]["score"]:
            best[p] = {"score": score, "s": s, "e": e, "bleed_db": bl, "overlap": len(others)}
    zs = []
    for p in sorted(best):
        c = best[p]
        x0, x1 = int(max(0, c["s"] - 0.03) * SR), int(min(c["e"] + 0.6, len(a) / SR) * SR)
        clip = a[x0:x1].copy()
        fi, fo = int(0.01 * SR), int(0.5 * SR)
        clip[:fi] *= np.linspace(0, 1, fi)[:, None]; clip[-fo:] *= np.linspace(1, 0, fo)[:, None]
        clip *= 0.89 / (np.abs(clip).max() or 1)
        m = len(clip); ls, le = int(m * 0.30), int(m * 0.80); x = min(int(0.25 * SR), ls, (le - ls) // 3)
        if le - ls >= SR * 0.5:
            f = np.linspace(0, 1, x)[:, None]
            clip[le - x:le] = clip[le - x:le] * (1 - f) + clip[ls - x:ls] * f
        else:
            ls = le = None
        name = f"{inst}_{nn(p)}.wav"; sf.write(OUT / name, clip, SR, subtype="PCM_24")
        zs.append({"file": name, "root": p, "loop_start": ls, "loop_end": le, "gain_db": 0, "tune_cents": 0,
                   "bleed_db": c["bleed_db"], "overlap": c["overlap"], "at_sec": round(c["s"], 2), "sec": round(m / SR, 2)})
    for i, z in enumerate(zs):
        z["lo"] = lo if i == 0 else (zs[i - 1]["root"] + z["root"]) // 2 + 1
        z["hi"] = hi if i == len(zs) - 1 else (z["root"] + zs[i + 1]["root"]) // 2
    return zs

inst = []
for key, name, rel in (("horn", "Horn", 1.2), ("cello", "Cello", 1.2), ("pad", "Pad", 2.0)):
    if key in SRC:
        inst.append({"name": name, "id": key, "kind": "note", "sustain": True, "release_sec": rel, "zones": kit(key, SRC[key])})
# Texture, and any instrument the solo takes gave no notes for (the solo pad sat above 43), come from v2, copied so
# this folder stands alone.
v2 = K / "samples-v2" / "samples.json"
if v2.exists():
    have = {i["id"] for i in inst if i["zones"]}
    inst = [i for i in inst if i["zones"]]
    for t in json.load(open(v2))["instruments"]:
        if t["id"] in have:
            continue
        for z in t["zones"]:
            (OUT / z["file"]).write_bytes((K / "samples-v2" / z["file"]).read_bytes())
        t["from"] = "samples-v2"
        inst.append(t)
json.dump({"piece": K.name, "version": "solo", "sample_rate": SR,
           "sources": SRC,
           "note": "Horn, cello and pad from solo takes, each generated with one instrument and nothing else, so no piano. "
                   "bleed_db: other notes ringing under the chosen one, relative to it, lower is cleaner. Texture is v2's.",
           "instruments": inst}, open(OUT / "samples.json", "w"), indent=1, default=float)
for i in inst:
    print(f"{i['id']:8} {len(i['zones']):2} zones  " + " ".join(f"{nn(z['root'])}:{z['bleed_db']}" for z in i["zones"]))
