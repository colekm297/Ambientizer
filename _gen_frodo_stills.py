"""Frodo Sails West stills via flux-pro v1.1-ultra (~$0.06 each). Scratch script like _gen_hm_stills.py."""
import sys, json, requests
sys.path.insert(0, "/Users/colemonroe/Projects/Ambientizer")
import fal_loop as fl
D = "/Users/colemonroe/Projects/Ambientizer/output/release/frodo_west"
fal = fl._fal()
BASE = "Cinematic film still, photoreal, 35mm anamorphic, quiet, no text, no watermark, no lettering. "
P = {
 "wide_haven": BASE + "Wide shot from a high grey stone quay at dawn: a slender white elven ship with a single tall swan-curved sail, "
    "small in frame, sailing away from the camera across a calm silver-grey sea toward the horizon. Far ahead the sea mist is parting "
    "like a grey curtain drawn back, and through the gap a distant green country with white shores lies under a swift golden sunrise. "
    "Soft haze, long gold light on the water, gulls absent, everything still and reverent. Locked-off, no people in the foreground.",
 "open_sea": BASE + "Open sea at dawn, seen from low over the water: a white elven ship with a tall curved sail, mid-distance, sailing "
    "away toward a horizon where a wall of soft grey mist has opened onto a far green coast with white beaches and low green hills, "
    "the first sun rising behind them and turning the sea from silver to gold in a long path toward the ship. Calm swell, no wake, "
    "no birds, vast and gentle. Locked-off, perfectly still.",
 "veil_close": BASE + "Medium-wide shot: a white elven ship with a swan-prowed bow and a tall pale sail, three small cloaked figures "
    "at the rail seen from behind, looking ahead. Before them the grey sea-mist is drawing aside like silver glass, revealing white "
    "shores and a far green country under a rising sun. The light on the sail turns from silver to warm gold. Calm water, no wake, "
    "quiet and hopeful. Locked-off, still.",
}
for name, prompt in P.items():
    res = fal.subscribe("fal-ai/flux-pro/v1.1-ultra", arguments={"prompt": prompt, "aspect_ratio": "16:9",
          "output_format": "png", "safety_tolerance": "2", "raw": False}, with_logs=False)
    url = res["images"][0]["url"]; out = f"{D}/still_{name}.png"
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status(); open(out, "wb").write(r.content)
    print(name, out, res["images"][0].get("width"), res["images"][0].get("height"), flush=True)
print("DONE", flush=True)
