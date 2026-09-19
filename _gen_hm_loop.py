"""Seedance 1.5 Pro 12 s loop from the chosen Hail Mary still. Usage: _gen_hm_loop.py <still.png> <tag>"""
import sys, json, requests
sys.path.insert(0, "/Users/colemonroe/Projects/Ambientizer")
import fal_loop as fl
D = "/Users/colemonroe/Projects/Ambientizer/output/release/hailmary_tauceti"
still, tag = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "a")
start = fl.prep_frame(still, f"{D}/start_{tag}.png", height=1080)
fal = fl._fal(); url = fal.upload_file(start); print("uploaded", url, flush=True)
prompt = ("Static locked-off tripod shot. The camera does not move at all: no push in, no zoom, no pan, no drift, no "
          "handheld sway. The framing is identical throughout. The figure stands completely still, only the faintest "
          "breathing. Within the fixed frame the only motion is very slow and gentle: the warm corona of the small star "
          "outside the window shimmers and breathes softly, a few tiny indicator lights on the panels glow steadily with "
          "the slightest flicker, faint dust motes drift in the warm light. Nothing else moves. Extremely slow continuous "
          "ambient motion, cinematic, no cuts, no flashes, no new objects.")
res = fal.subscribe("fal-ai/bytedance/seedance/v1.5/pro/image-to-video", arguments={
    "prompt": prompt, "image_url": url, "end_image_url": url, "resolution": "1080p", "duration": "12",
    "camera_fixed": True, "generate_audio": False, "aspect_ratio": "16:9"}, with_logs=True, on_queue_update=lambda u: None)
print("RESULT", json.dumps(res), flush=True)
out = f"{D}/loop_raw_{tag}.mp4"
with requests.get(res["video"]["url"], stream=True, timeout=300) as r:
    r.raise_for_status()
    with open(out, "wb") as fh:
        for c in r.iter_content(1 << 20): fh.write(c)
print("SEAM", json.dumps(fl.seam_report(out, source_frame=start)), flush=True)
print("DONE", flush=True)
