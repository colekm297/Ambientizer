"""Project Hail Mary / Tau Ceti stills via flux-pro v1.1-ultra (~$0.06 each)."""
import sys, json, requests
sys.path.insert(0, "/Users/colemonroe/Projects/Ambientizer")
import fal_loop as fl
D = "/Users/colemonroe/Projects/Ambientizer/output/release/hailmary_tauceti"
fal = fl._fal()
BASE = ("Cinematic film still, photoreal, 35mm anamorphic, quiet, no text, no watermark. ")
P = {
 "exterior_wide": BASE + "Exterior wide shot: a long white cylindrical research spacecraft with a slowly rotating centrifuge ring, "
    "small in frame, drifting in silence near the star Tau Ceti. The star sits low and slightly right of centre, small, orange-white, "
    "its corona soft and warm, the only bright thing. A faint thin haze of dull red glowing motes hangs between the ship and the star. "
    "Deep black space, pin-sharp stars, warm rim light along the hull. Locked-off, perfectly still, vast and calm.",
 "window_figure": BASE + "Interior: the control room of a small research spacecraft, seen from behind. One figure stands alone at a wide "
    "curved window, silhouetted, looking out at the star Tau Ceti, which sits low through the glass, small, orange-white, warm, its light "
    "laid across the dim instrument panels and the floor. Everything else is dark and still. Wide shot, calm, reverent, no text.",
 "exterior_close": BASE + "Exterior medium shot: a white cylindrical research spacecraft with a rotating centrifuge ring fills the lower left "
    "third, hull lit warm orange on one side by the star Tau Ceti, which sits low right, small and bright with a soft corona. A dim red "
    "glow of drifting motes between them. Black space, sharp stars, no planet. Locked-off, still, quiet.",
}
for name, prompt in P.items():
    res = fal.subscribe("fal-ai/flux-pro/v1.1-ultra", arguments={"prompt": prompt, "aspect_ratio": "16:9",
          "output_format": "png", "safety_tolerance": "2", "raw": False}, with_logs=False)
    url = res["images"][0]["url"]; out = f"{D}/still_{name}.png"
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status(); open(out, "wb").write(r.content)
    print(name, out, res["images"][0].get("width"), res["images"][0].get("height"), flush=True)
print("DONE", flush=True)
