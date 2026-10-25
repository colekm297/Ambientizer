"""Model upgrade test 2026-10-24: one Dune still from flux-pro v1.1-ultra (current) vs Nano Banana Pro vs GPT Image 2 on fal."""
import sys, json, requests
sys.path.insert(0, "/Users/colemonroe/Projects/Ambientizer")
import fal_loop as fl
O = "/Users/colemonroe/Projects/Ambientizer/output/_model_upgrade"; fal = fl._fal()
P = ("Cinematic film still, photoreal, 35mm anamorphic, quiet, no text, no watermark, no lettering. Dune, Arrakis at last light: "
     "a lone figure in a dark Fremen stillsuit cloak stands on a high dune crest, small in the frame, facing an immense desert "
     "of rolling dunes under a low amber sun; far off, the dark silhouette of a rock wall. Fine sand lifts off the crests in "
     "the wind. Warm amber and deep shadow, vast, still, reverent. Locked-off, wide.")
RUNS = {
 "flux11ultra": ("fal-ai/flux-pro/v1.1-ultra", {"prompt": P, "aspect_ratio": "16:9", "output_format": "png", "safety_tolerance": "2"}),
 "nanobananapro": ("fal-ai/nano-banana-pro", {"prompt": P, "aspect_ratio": "16:9", "resolution": "2K", "output_format": "png"}),
 "gptimage2": ("openai/gpt-image-2", {"prompt": P, "image_size": {"width": 2048, "height": 1152}, "quality": "high", "output_format": "png"}),
}
for name, (ep, args) in RUNS.items():
    try:
        res = fal.subscribe(ep, arguments=args, with_logs=False)
        im = res["images"][0]; out = f"{O}/still_{name}.png"
        open(out, "wb").write(requests.get(im["url"], timeout=300).content)
        print(name, ep, out, im.get("width"), im.get("height"), flush=True)
    except Exception as e:
        print(name, ep, "FAILED", str(e)[:300], flush=True)
print("DONE", flush=True)
