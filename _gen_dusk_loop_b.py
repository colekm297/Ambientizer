import sys, json, requests
sys.path.insert(0, "/Users/colemonroe/Projects/Ambientizer")
import fal_loop as fl
D = "/Users/colemonroe/Projects/Ambientizer/output/release/dusk_arrakis"
start = fl.prep_frame(f"{D}/still_dunes_dusk.png", f"{D}/start.png", height=1080)
fal = fl._fal()
url = fal.upload_file(start)
print("uploaded", url, flush=True)
prompt = ("Static locked-off tripod shot. The camera does not move at all: no push in, no zoom, no pan, "
          "no drift. The framing is identical throughout. Within that fixed frame the motion is very slow "
          "and gentle: a light steady wind lifts thin veils of sand off the dune crests and carries them "
          "sideways at constant speed, never gusting, never stopping. A faint heat haze shimmers over the "
          "far dunes. The sky and the setting sun hold exactly as they are. The distant figure stands "
          "still. Extremely slow continuous ambient motion, dusk, cinematic, no cuts.")
res = fal.subscribe("fal-ai/bytedance/seedance/v1.5/pro/image-to-video", arguments={
    "prompt": prompt, "image_url": url, "end_image_url": url,
    "resolution": "1080p", "duration": "12", "camera_fixed": True,
    "generate_audio": False, "aspect_ratio": "16:9"},
    with_logs=True, on_queue_update=lambda u: None)
print("RESULT", json.dumps(res), flush=True)
with requests.get(res["video"]["url"], stream=True, timeout=300) as r:
    r.raise_for_status()
    with open(f"{D}/loop_raw_b.mp4", "wb") as fh:
        for c in r.iter_content(1<<20): fh.write(c)
rep = fl.seam_report(f"{D}/loop_raw_b.mp4", source_frame=start)
print("SEAM_B", json.dumps(rep), flush=True)
print("DONE", flush=True)
