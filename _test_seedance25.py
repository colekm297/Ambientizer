# Model upgrade test 2026-10-24: Seedance 2.5 (bytedance/seedance-2.5/us/image-to-video) vs the shipped 1.5 Pro loop,
# same Last Light still as start+end, 12 s, 1080p high bitrate, no audio. seam_report on both.
import sys, json, requests
sys.path.insert(0, "/Users/colemonroe/Projects/Ambientizer")
import fal_loop as fl
D = "/Users/colemonroe/Projects/Ambientizer/output/release/dusk_arrakis"; O = "/Users/colemonroe/Projects/Ambientizer/output/_model_upgrade"
start = f"{D}/start.png"
fal = fl._fal(); url = fal.upload_file(start)
prompt = ("Static locked-off tripod shot. The camera does not move at all: no push in, no zoom, no pan, no drift. "
          "The framing is identical throughout. The figure stays motionless. The only motion is fine sand drifting off the "
          "dune crests in a slow wind, and the faint shimmer of heat in the last light. A living photograph, cinematic, no cuts.")
res = fal.subscribe("bytedance/seedance-2.5/us/image-to-video", arguments={
    "prompt": prompt, "image_url": url, "end_image_url": url, "resolution": "1080p", "duration": "12",
    "generate_audio": False, "bitrate_mode": "high"}, with_logs=True, on_queue_update=lambda u: None)
print("RESULT", json.dumps(res), flush=True)
out = f"{O}/seedance25_lastlight.mp4"
with requests.get(res["video"]["url"], stream=True, timeout=300) as r:
    r.raise_for_status()
    with open(out, "wb") as fh:
        for c in r.iter_content(1 << 20): fh.write(c)
print("SEAM 2.5", json.dumps(fl.seam_report(out, source_frame=start)), flush=True)
print("SEAM 1.5", json.dumps(fl.seam_report(f"{D}/loop_raw.mp4", source_frame=start)), flush=True)
print("DONE", flush=True)
