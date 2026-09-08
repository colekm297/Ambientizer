import sys, json, requests
sys.path.insert(0, "/Users/colemonroe/Projects/Ambientizer")
import fal_loop as fl
D = "/Users/colemonroe/Projects/Ambientizer/output/release/dusk_arrakis"
start = f"{D}/start.png"
fal = fl._fal()
url = fal.upload_file(start)
prompt = ("Static locked-off tripod shot. The camera does not move at all: no push in, no zoom, no pan, "
          "no drift. The framing is identical throughout. Within that fixed frame almost nothing moves: "
          "no sand blows, no dust rises, the dunes are utterly still and their ripples do not change. "
          "The only motion is a faint, slow heat shimmer over the far dunes near the horizon and the "
          "softest drift in the haze. The sky and the setting sun hold exactly as they are. The distant "
          "figure stands motionless. A living photograph, dusk, cinematic, no cuts.")
res = fal.subscribe("fal-ai/bytedance/seedance/v1.5/pro/image-to-video", arguments={
    "prompt": prompt, "image_url": url, "end_image_url": url,
    "resolution": "1080p", "duration": "12", "camera_fixed": True,
    "generate_audio": False, "aspect_ratio": "16:9"}, with_logs=True, on_queue_update=lambda u: None)
print("RESULT", json.dumps(res), flush=True)
with requests.get(res["video"]["url"], stream=True, timeout=300) as r:
    r.raise_for_status()
    with open(f"{D}/loop_raw_c.mp4", "wb") as fh:
        for c in r.iter_content(1<<20): fh.write(c)
print("SEAM_C", json.dumps(fl.seam_report(f"{D}/loop_raw_c.mp4", source_frame=start)), flush=True)
print("DONE", flush=True)
