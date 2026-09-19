import sys, requests
sys.path.insert(0, "/Users/colemonroe/Projects/Ambientizer")
import fal_loop as fl
D = "/Users/colemonroe/Projects/Ambientizer/output/release/hailmary_tauceti"
fal = fl._fal()
BASE = "Cinematic film still, photoreal, 35mm anamorphic, quiet, no text, no lettering, no watermark, no lens flare streaks, no light lines. "
P = {
 "window_star": BASE + "Interior, from behind: the dim control room of a small spacecraft, a wide hexagonal panoramic window with soft "
    "white edge lighting. One figure stands alone at the window, silhouetted, hands at sides. Through the glass: deep black space with "
    "pin-sharp stars and, low and slightly left of the figure, the star Tau Ceti as a small round orange-white disc with a soft warm "
    "corona, no rays, no streaks. Its warm light lays across two chair backs and the instrument panels. Wide shot, still, calm.",
 "window_planet": BASE + "Interior, from behind: the dim control room of a small spacecraft, a wide hexagonal panoramic window. One figure "
    "stands alone at the window, silhouetted. Through the glass: a large hazy planet fills the lower half of the view, dusty amber and "
    "rust with a thin glowing atmosphere limb, and above it, small and low right, the star Tau Ceti as a round orange-white disc with a "
    "soft corona. Warm light on the panels and chairs. Wide shot, still, calm.",
}
for name, prompt in P.items():
    res = fal.subscribe("fal-ai/flux-pro/v1.1-ultra", arguments={"prompt": prompt, "aspect_ratio": "16:9",
          "output_format": "png", "safety_tolerance": "2", "raw": False}, with_logs=False)
    out = f"{D}/still_{name}.png"; open(out, "wb").write(requests.get(res["images"][0]["url"], timeout=300).content)
    print(name, out, flush=True)
print("DONE", flush=True)
