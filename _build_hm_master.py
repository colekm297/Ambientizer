# Hail Mary / Tau Ceti: 1-hour master from a Seedance loop + one mastered audio take, with the
# plain-wording subscribe/like cards baked in (intro 7-19 s after the 6 s sting, end card last 25 s).
# Usage: .venv/bin/python _build_hm_master.py "<mastered wav>" [loop_raw.mp4]
# Construction is _build_dusk_master.py's (natural head, acrossfade cell, concat-copy tiles) plus an
# overlay pass on the final video: the cards are RGBA PNGs faded in/out with ffmpeg overlay.
import math, os, subprocess, sys
import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = "/Users/colemonroe/Projects/Ambientizer"
D = f"{HERE}/output/release/hailmary_tauceti"
SRC_AUDIO = sys.argv[1]
SRC_VIDEO = sys.argv[2] if len(sys.argv) > 2 else f"{D}/loop_raw.mp4"
STING = f"{HERE}/brand/out/sting_bronze.mp4"
XFADE, TOTAL = 40, 3600.0
INTRO_IN, INTRO_OUT, END_LEN = 7.0, 19.0, 25.0
CTA1 = "If you liked this track, please consider liking and subscribing."
CTA2 = "I'll be putting out new music weekly."
NEXT_TITLE, NEXT_THUMB = "A Small Light in the Dark", f"{HERE}/brand/ref/small_light_frJb60y4d5M.jpg"

def sh(a): subprocess.run(a, check=True, capture_output=True)
def dur(p): return float(subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
                        "-of","csv=p=0",p],check=True,capture_output=True,text=True).stdout.strip())

# 0. card overlays (RGBA, 1920x1080, transparent outside the plates)
W, H = 1920, 1080
OSW, ARCH = f"{HERE}/fonts/Oswald.ttf", f"{HERE}/fonts/ArchivoBlack.ttf"
CREAM, DIM = (245, 240, 230), (215, 205, 190)
def mark(size, color=CREAM):
    a = Image.open(f"{HERE}/brand/out/avatar_aperture_bold_v2.png").convert("L")
    m = a.point(lambda v: 255 if v > 140 else 0).resize((size, size), Image.LANCZOS)
    out = Image.new("RGBA", (size, size), color + (0,)); out.putalpha(m); return out
def stext(d, xy, s, f, fill, anchor="la"):
    d.text((xy[0]+2, xy[1]+3), s, font=f, fill=(0, 0, 0, 160), anchor=anchor); d.text(xy, s, font=f, fill=fill, anchor=anchor)
def intro_overlay(path):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d0 = ImageDraw.Draw(im)
    f1, f2, f3 = ImageFont.truetype(OSW, 46), ImageFont.truetype(OSW, 32), ImageFont.truetype(OSW, 26)
    tx = 260; wt = max(d0.textlength(CTA1, font=f1), d0.textlength(CTA2, font=f2), 250 + d0.textlength("a like helps a lot too", font=f3))
    d0.rounded_rectangle((72, 790, int(tx + wt + 48), 1010), radius=22, fill=(10, 8, 12, 165))
    im = im.filter(ImageFilter.GaussianBlur(1.5)); im.alpha_composite(mark(120), (100, 840)); d = ImageDraw.Draw(im)
    stext(d, (tx, 822), CTA1, f1, CREAM); stext(d, (tx, 886), CTA2, f2, DIM)
    d.rounded_rectangle((tx, 940, tx + 220, 988), radius=8, fill=(204, 0, 0))
    d.text((tx + 110, 964), "SUBSCRIBE", font=ImageFont.truetype(ARCH, 22), fill=(255, 255, 255), anchor="mm")
    d.text((tx + 250, 964), "a like helps a lot too", font=f3, fill=DIM, anchor="lm"); im.save(path)
def end_overlay(path):
    im = Image.new("RGBA", (W, H), (6, 5, 8, 115)); im.alpha_composite(mark(150), (W//2 - 75, 110)); d = ImageDraw.Draw(im)
    stext(d, (W//2, 300), "THE SPACE OF SOUND", ImageFont.truetype(ARCH, 40), CREAM, "mm")
    stext(d, (W//2, 356), CTA2.rstrip("."), ImageFont.truetype(OSW, 32), DIM, "mm")
    d.rounded_rectangle((300, 470, 820, 820), radius=24, fill=(14, 12, 16, 200)); d.ellipse((470, 500, 650, 680), fill=(0, 0, 0, 255))
    im.alpha_composite(mark(140), (490, 520)); d = ImageDraw.Draw(im)
    d.rounded_rectangle((420, 710, 700, 768), radius=10, fill=(204, 0, 0, 255))
    d.text((560, 739), "SUBSCRIBE", font=ImageFont.truetype(ARCH, 26), fill=(255, 255, 255), anchor="mm")
    stext(d, (560, 800), "like and subscribe", ImageFont.truetype(OSW, 26), DIM, "mm")
    d.rounded_rectangle((1090, 470, 1680, 820), radius=24, fill=(14, 12, 16, 200))
    im.paste(Image.open(NEXT_THUMB).convert("RGB").resize((560, 315), Image.LANCZOS), (1105, 485)); d = ImageDraw.Draw(im)
    stext(d, (1385, 830), "MORE LIKE THIS", ImageFont.truetype(ARCH, 22), (232, 176, 96), "mm")
    stext(d, (1385, 866), NEXT_TITLE, ImageFont.truetype(OSW, 26), CREAM, "mm"); im.save(path)
intro_png, end_png = f"{D}/_card_intro.png", f"{D}/_card_end.png"
intro_overlay(intro_png); end_overlay(end_png)

# 1. audio cell + natural-head timeline
info = sf.info(SRC_AUDIO); src_dur = info.frames / info.samplerate; cell_dur = src_dur - XFADE
big, cell, head = f"{D}/_xfade_big.wav", f"{D}/audio_cell.wav", f"{D}/_head.wav"
sh(["ffmpeg","-y","-v","error","-i",SRC_AUDIO,"-i",SRC_AUDIO,
    "-filter_complex",f"[0:a][1:a]acrossfade=d={XFADE}:c1=tri:c2=tri[a]","-map","[a]","-c:a","pcm_s16le",big])
sh(["ffmpeg","-y","-v","error","-ss",str(cell_dur),"-t",str(cell_dur),"-i",big,"-c:a","pcm_s16le",cell])
sh(["ffmpeg","-y","-v","error","-t",str(cell_dur),"-i",SRC_AUDIO,"-c:a","pcm_s16le",head])
data, sr = sf.read(cell); mono = data.mean(axis=1) if data.ndim > 1 else data
edge = abs(mono[0]-mono[-1]); p999 = np.percentile(np.abs(np.diff(mono)), 99.9)
print(f"1. src {src_dur:.1f}s cell {cell_dur:.1f}s edge {edge:.5f} vs p99.9 {p999:.5f} -> {'CLEAN' if edge < p999 else 'FAIL'}", flush=True)
if edge >= p999: sys.exit("audio cell seam FAILED")
n_cells = math.ceil((TOTAL - cell_dur) / cell_dur)
alst = f"{D}/_audio.txt"
with open(alst,"w") as fh:
    fh.write(f"file '{head}'\n"); [fh.write(f"file '{cell}'\n") for _ in range(n_cells)]
audio = f"{D}/_audio_final.wav"
sh(["ffmpeg","-y","-v","error","-f","concat","-safe","0","-i",alst,"-af",f"afade=t=in:st=0:d=3,afade=t=out:st={TOTAL-6}:d=6",
    "-t",str(TOTAL),"-c:a","pcm_s16le",audio])

# 2. video. Re-encoding the whole hour for two overlays took >1 h, so only the segments that carry a
# card are re-encoded: seg1 = sting + 2 tiles (intro card), mid = 294 tiles concat-copied, tail = 3 tiles
# (end card). All three use the same ENC params so the final concat is a stream copy.
ENC = ["-c:v","libx264","-crf","16","-preset","slow","-pix_fmt","yuv420p","-r","24","-video_track_timescale","24000","-an"]
cell_v, sting_v = f"{D}/_cell_enc.mp4", f"{D}/_sting_enc.mp4"
sh(["ffmpeg","-y","-v","error","-i",SRC_VIDEO]+ENC+[cell_v])
sh(["ffmpeg","-y","-v","error","-i",STING,"-vf","fps=24,scale=1920:1080"]+ENC[:-1]+[sting_v])
sting_dur, cv = dur(sting_v), dur(cell_v)
N_SEG1, N_TAIL = 2, 3
n_mid = math.ceil((TOTAL - sting_dur - (N_SEG1 + N_TAIL) * cv) / cv)
print(f"2. sting {sting_dur:.2f}s, cell {cv:.4f}s, tiles {N_SEG1}+{n_mid}+{N_TAIL}", flush=True)
def concat_list(path, files):
    with open(path, "w") as fh: [fh.write(f"file '{f}'\n") for f in files]
seg1_src, mid_v, tail_src = f"{D}/_seg1_src.mp4", f"{D}/_mid.mp4", f"{D}/_tail_src.mp4"
concat_list(f"{D}/_l1.txt", [sting_v] + [cell_v]*N_SEG1); sh(["ffmpeg","-y","-v","error","-f","concat","-safe","0","-i",f"{D}/_l1.txt","-c","copy",seg1_src])
concat_list(f"{D}/_l2.txt", [cell_v]*n_mid);            sh(["ffmpeg","-y","-v","error","-f","concat","-safe","0","-i",f"{D}/_l2.txt","-c","copy",mid_v])
concat_list(f"{D}/_l3.txt", [cell_v]*N_TAIL);           sh(["ffmpeg","-y","-v","error","-f","concat","-safe","0","-i",f"{D}/_l3.txt","-c","copy",tail_src])
seg1_dur, mid_dur = dur(seg1_src), dur(mid_v); tail_start = seg1_dur + mid_dur
t0, t1 = INTRO_IN, INTRO_OUT; te_rel = (TOTAL - END_LEN) - tail_start
assert t1 < seg1_dur and te_rel > 2, (seg1_dur, te_rel)
seg1_v, tail_v = f"{D}/_seg1.mp4", f"{D}/_tail.mp4"
sh(["ffmpeg","-y","-v","error","-i",seg1_src,"-loop","1","-i",intro_png,"-filter_complex",
    f"[1:v]format=rgba,fade=t=in:st={t0}:d=1:alpha=1,fade=t=out:st={t1-1}:d=1:alpha=1[i];[0:v][i]overlay=0:0:enable='between(t,{t0},{t1})'[v]",
    "-map","[v]","-t",str(seg1_dur)]+ENC+[seg1_v])
sh(["ffmpeg","-y","-v","error","-i",tail_src,"-loop","1","-i",end_png,"-filter_complex",
    f"[1:v]format=rgba,fade=t=in:st={te_rel}:d=2:alpha=1[e];[0:v][e]overlay=0:0:enable='gte(t,{te_rel})'[v]",
    "-map","[v]","-t",str(TOTAL - tail_start)]+ENC+[tail_v])
concat_list(f"{D}/_l4.txt", [seg1_v, mid_v, tail_v])
vcards = f"{D}/_video_cards.mp4"
sh(["ffmpeg","-y","-v","error","-f","concat","-safe","0","-i",f"{D}/_l4.txt","-c","copy",vcards])
print(f"2b. cards overlaid: seg1 {seg1_dur:.3f}s, mid {mid_dur:.3f}s, tail from {tail_start:.3f}s, end card at {tail_start+te_rel:.3f}s", flush=True)

# 3. mux
master = f"{D}/hailmary_tauceti_1h.mp4"
sh(["ffmpeg","-y","-v","error","-i",vcards,"-i",audio,"-map","0:v","-map","1:a","-t",str(TOTAL),"-c:v","copy","-c:a","aac","-b:a","384k",master])

# 4. verify
print(f"3. duration {dur(master):.3f}s", flush=True)
for t, n in ((12, "intro"), (1800, "30m"), (3590, "end")):
    sh(["ffmpeg","-y","-v","error","-ss",str(t),"-i",master,"-frames:v","1","-q:v","2",f"{D}/_check_{n}.jpg"])
def mj(t):
    o = subprocess.run(["ffmpeg","-v","error","-ss",str(t-1),"-t","2","-i",master,"-vn","-f","f32le","-ac","1","-"],capture_output=True)
    a = np.frombuffer(o.stdout, dtype=np.float32); return float(np.abs(np.diff(a)).max())
joins = [cell_dur*k for k in range(1, n_cells+1) if cell_dur*k < TOTAL-2]
jv = [mj(t) for t in joins]; cvv = [mj(t) for t in (400, 800, 1600, 2000, 2800)]
print(f"4. joins {np.mean(jv):.5f} vs controls {np.mean(cvv):.5f} -> {'CLEAN' if np.mean(jv) <= np.mean(cvv)*1.3 else 'SUSPECT'}", flush=True)
lo = subprocess.run(["ffmpeg","-v","info","-i",master,"-vn","-af","ebur128=peak=true","-f","null","-"],capture_output=True,text=True).stderr
tail = lo[lo.rfind("Integrated loudness"):] if "Integrated loudness" in lo else lo[-600:]
print("5. LOUDNESS", " ".join(tail.split())[:300], flush=True)
import glob
for f in [big, head, audio, cell_v, sting_v, vcards, alst, seg1_src, mid_v, tail_src, seg1_v, tail_v] + glob.glob(f"{D}/_l?.txt"): os.path.exists(f) and os.remove(f)
print("DONE", flush=True)
