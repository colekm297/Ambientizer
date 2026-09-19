import sys, requests
sys.path.insert(0, "/Users/colemonroe/Projects/Ambientizer")
import fal_loop as fl
D = "/Users/colemonroe/Projects/Ambientizer/output/release/hailmary_tauceti"
fal = fl._fal()
BASE = "Cinematic film still, photoreal, 35mm anamorphic, quiet, no text, no watermark, no lens flare streaks. "
P = {
 "window_warm": BASE + "Interior, from behind: the dim control room of a small spacecraft. One figure stands alone at a wide "
    "panoramic window, silhouetted. Through the glass: the star Tau Ceti low and slightly left, small, orange-white, with a soft warm "
    "corona, and beside it a faint crescent of a hazy planet; a thin band of dull red glowing dust crosses the black between them. "
    "The warm starlight lays across the instrument panels, the chair backs and the floor so the room reads clearly, low key but not black. "
    "Wide shot, still, calm.",
 "hull_side": BASE + "Exterior, three-quarter side view: a white cylindrical research spacecraft, long hull with a wide rotating crew ring "
    "near the front and radiator fins at the back, hanging motionless in deep space, lower left of frame, hull lit warm orange on the "
    "sunward side. The star Tau Ceti sits low right, small and bright, orange-white, soft corona, no streaks. Dull red glowing dust band "
    "far behind. Pin-sharp stars. Vast, calm, still.",
}
for name, prompt in P.items():
    res = fal.subscribe("fal-ai/flux-pro/v1.1-ultra", arguments={"prompt": prompt, "aspect_ratio": "16:9",
          "output_format": "png", "safety_tolerance": "2", "raw": False}, with_logs=False)
    out = f"{D}/still_{name}.png"; open(out, "wb").write(requests.get(res["images"][0]["url"], timeout=300).content)
    print(name, out, flush=True)
print("DONE", flush=True)
