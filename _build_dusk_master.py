# Dusk Over Arrakis: 1-hour master from loop_raw.mp4 + one mastered audio take.
# Usage: .venv/bin/python _build_dusk_master.py "<mastered wav>"
# Same construction as Fair Wind (2026-09-07) with both lessons baked in:
#   * the seamless audio cell is the acrossfade output's middle segment [cell:2*cell]
#   * the cell must never open the video; the track's natural head plays first
import math, os, subprocess, sys
import numpy as np
import soundfile as sf

HERE = "/Users/colemonroe/Projects/Ambientizer"
D = f"{HERE}/output/release/dusk_arrakis"
SRC_AUDIO = sys.argv[1]
SRC_VIDEO = f"{D}/loop_raw_c.mp4"
STING = f"{HERE}/brand/out/sting_bronze.mp4"
XFADE, TOTAL = 40, 3600.0

def sh(a): subprocess.run(a, check=True, capture_output=True)
def dur(p): return float(subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
                        "-of","csv=p=0",p],check=True,capture_output=True,text=True).stdout.strip())

# 1. audio cell + natural-head timeline
info = sf.info(SRC_AUDIO); src_dur = info.frames / info.samplerate; cell_dur = src_dur - XFADE
big = f"{D}/_xfade_big.wav"; cell = f"{D}/audio_cell.wav"; head = f"{D}/_head.wav"
sh(["ffmpeg","-y","-v","error","-i",SRC_AUDIO,"-i",SRC_AUDIO,
    "-filter_complex",f"[0:a][1:a]acrossfade=d={XFADE}:c1=tri:c2=tri[a]","-map","[a]","-c:a","pcm_s16le",big])
sh(["ffmpeg","-y","-v","error","-ss",str(cell_dur),"-t",str(cell_dur),"-i",big,"-c:a","pcm_s16le",cell])
sh(["ffmpeg","-y","-v","error","-t",str(cell_dur),"-i",SRC_AUDIO,"-c:a","pcm_s16le",head])
data, sr = sf.read(cell); mono = data.mean(axis=1) if data.ndim > 1 else data
edge = abs(mono[0]-mono[-1]); p999 = np.percentile(np.abs(np.diff(mono)), 99.9)
print(f"1. cell {cell_dur:.1f}s edge {edge:.5f} vs p99.9 {p999:.5f} -> {'CLEAN' if edge < p999 else 'FAIL'}", flush=True)
if edge >= p999: sys.exit("audio cell seam FAILED")
n_cells = math.ceil((TOTAL - cell_dur) / cell_dur)
alst = f"{D}/_audio.txt"
with open(alst,"w") as fh:
    fh.write(f"file '{head}'\n"); [fh.write(f"file '{cell}'\n") for _ in range(n_cells)]
audio = f"{D}/_audio_final.wav"
sh(["ffmpeg","-y","-v","error","-f","concat","-safe","0","-i",alst,"-af","afade=t=in:st=0:d=3",
    "-t",str(TOTAL),"-c:a","pcm_s16le",audio])

# 2. video: encode cell + sting once with identical params, concat-copy
ENC = ["-c:v","libx264","-crf","16","-preset","slow","-pix_fmt","yuv420p","-r","24",
       "-video_track_timescale","24000","-an"]
cell_v, sting_v = f"{D}/_cell_enc.mp4", f"{D}/_sting_enc.mp4"
sh(["ffmpeg","-y","-v","error","-i",SRC_VIDEO]+ENC+[cell_v])
sh(["ffmpeg","-y","-v","error","-i",STING,"-vf","fps=24,scale=1920:1080"]+ENC[:-1]+[sting_v])
sting_dur, cv = dur(sting_v), dur(cell_v); n_tiles = math.ceil((TOTAL - sting_dur)/cv)
print(f"2. sting {sting_dur:.2f}s, cell {cv:.4f}s, {n_tiles} tiles", flush=True)
vlst = f"{D}/_video.txt"
with open(vlst,"w") as fh:
    fh.write(f"file '{sting_v}'\n"); [fh.write(f"file '{cell_v}'\n") for _ in range(n_tiles)]
vfull = f"{D}/_video_full.mp4"
sh(["ffmpeg","-y","-v","error","-f","concat","-safe","0","-i",vlst,"-c","copy",vfull])

# 3. mux
master = f"{D}/dusk_arrakis_1h.mp4"
sh(["ffmpeg","-y","-v","error","-i",vfull,"-i",audio,"-map","0:v","-map","1:a","-t",str(TOTAL),
    "-c:v","copy","-c:a","aac","-b:a","384k",master])

# 4. verify: duration, deep frame, joins vs controls, loudness
print(f"3. duration {dur(master):.3f}s", flush=True)
sh(["ffmpeg","-y","-v","error","-ss","1800","-i",master,"-frames:v","1","-q:v","2",f"{D}/_check_30m.jpg"])
def mj(t):
    o = subprocess.run(["ffmpeg","-v","error","-ss",str(t-1),"-t","2","-i",master,"-vn","-f","f32le","-ac","1","-"],capture_output=True)
    a = np.frombuffer(o.stdout, dtype=np.float32); return float(np.abs(np.diff(a)).max())
joins = [cell_dur*k for k in range(1, n_cells+1) if cell_dur*k < TOTAL-2]
jv = [mj(t) for t in joins]; cvv = [mj(t) for t in (400, 800, 1600, 2000, 2800)]
print(f"4. joins {np.mean(jv):.5f} vs controls {np.mean(cvv):.5f} -> {'CLEAN' if np.mean(jv) <= np.mean(cvv)*1.3 else 'SUSPECT'}", flush=True)
lo = subprocess.run(["ffmpeg","-v","info","-i",master,"-vn","-af","ebur128=peak=true","-f","null","-"],
                    capture_output=True, text=True).stderr
tail = lo[lo.rfind("Integrated loudness"):] if "Integrated loudness" in lo else lo[-600:]
print("5. LOUDNESS", " ".join(tail.split())[:300], flush=True)
for f in (big, head, audio, cell_v, sting_v, vfull, alst, vlst): os.path.exists(f) and os.remove(f)
print("DONE", flush=True)
