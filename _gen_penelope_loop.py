# Penelope at the Loom loop: Seedance 1.5 Pro, same still start+end, camera fixed, 12 s, raw ships untreated.
import sys, json, requests
sys.path.insert(0, "/Users/colemonroe/Projects/Ambientizer")
import fal_loop as fl
D = "/Users/colemonroe/Projects/Ambientizer/output/release/penelope_loom"
start = f"{D}/start.png"
tag = sys.argv[1] if len(sys.argv) > 1 else ""
fal = fl._fal()
url = fal.upload_file(start)
prompt = ("Static locked-off tripod shot. The camera does not move at all: no push in, no zoom, no pan, no drift. "
          "The framing is identical throughout. The seated woman stays motionless, her head and hands exactly where they are; "
          "the loom, the threads and the cloth do not move. The only motion is the soft flicker and slow breathing of the two "
          "oil-lamp flames and their warm light trembling faintly on the wall and threads, and the faintest glitter on the "
          "moonlit sea through the window. The moon, the stars and the room hold exactly as they are. "
          "A living photograph, night, cinematic, no cuts.")
res = fal.subscribe("fal-ai/bytedance/seedance/v1.5/pro/image-to-video", arguments={
    "prompt": prompt, "image_url": url, "end_image_url": url,
    "resolution": "1080p", "duration": "12", "camera_fixed": True,
    "generate_audio": False, "aspect_ratio": "16:9"}, with_logs=True, on_queue_update=lambda u: None)
print("RESULT", json.dumps(res), flush=True)
out = f"{D}/loop_raw{tag}.mp4"
with requests.get(res["video"]["url"], stream=True, timeout=300) as r:
    r.raise_for_status()
    with open(out, "wb") as fh:
        for c in r.iter_content(1<<20): fh.write(c)
print("SEAM", json.dumps(fl.seam_report(out, source_frame=start)), flush=True)
print("DONE", flush=True)
