"""Cut a playable sample set from a take's stems: long held notes found by basic-pitch, named by pitch, plus an SFZ map.
usage: tools/stems-venv/bin/python tools/cut_samples.py output/keys/<job>"""
import sys, json
from pathlib import Path
import numpy as np, soundfile as sf
from basic_pitch.inference import predict
from basic_pitch import ICASSP_2022_MODEL_PATH
K = Path(sys.argv[1]); OUT = K / "samples"; OUT.mkdir(exist_ok=True)
NAMES = "C C# D D# E F F# G G# A A# B".split()
def nn(p): return f"{NAMES[p%12]}{p//12-1}"
rows = []
for stem in ("melody", "pad"):
    wav = K / "stems" / f"{stem}.wav"
    audio, sr = sf.read(wav, dtype="float32")
    _, _, notes = predict(str(wav), ICASSP_2022_MODEL_PATH, onset_threshold=0.5, frame_threshold=0.3, minimum_note_length=1500)
    best = {}
    for s, e, p, amp, _ in notes:
        dur = e - s
        if dur < 1.8: continue
        score = dur * amp
        if p not in best or score > best[p][0]: best[p] = (score, s, e, amp)
    for p, (score, s, e, amp) in sorted(best.items()):
        a, b = int(max(0, s - 0.03) * sr), int(min(e + 0.6, len(audio) / sr) * sr)
        clip = audio[a:b].copy(); n = len(clip)
        fi, fo = int(0.01 * sr), int(0.5 * sr)
        clip[:fi] *= np.linspace(0, 1, fi)[:, None]; clip[-fo:] *= np.linspace(1, 0, fo)[:, None]
        peak = np.abs(clip).max() or 1; clip *= 0.89 / peak
        name = f"{stem}_{nn(p)}.wav"; sf.write(OUT / name, clip, sr, subtype="PCM_24")
        rows.append({"file": name, "stem": stem, "midi": int(p), "note": nn(p), "sec": round(n / sr, 2), "at": round(s, 2), "amp": round(float(amp), 2)})
json.dump(rows, open(OUT / "samples.json", "w"), indent=1)
# SFZ: one group per stem, each sample covers keys up to halfway to its neighbours
sfz = []
for stem in ("melody", "pad"):
    rs = sorted([r for r in rows if r["stem"] == stem], key=lambda r: r["midi"])
    if not rs: continue
    sfz.append(f"// {stem}\n<group> ampeg_release=1.2 loop_mode=no_loop")
    for i, r in enumerate(rs):
        lo = 21 if i == 0 else (rs[i-1]["midi"] + r["midi"]) // 2 + 1
        hi = 108 if i == len(rs) - 1 else (r["midi"] + rs[i+1]["midi"]) // 2
        sfz.append(f"<region> sample={r['file']} pitch_keycenter={r['midi']} lokey={lo} hikey={hi}")
    (OUT / f"folding_city_{stem}.sfz").write_text("\n".join(sfz[-(len(rs)+1):]) + "\n")
print(len(rows), "samples"); [print(r) for r in rows]
