"""Penelope at the Loom stills via flux-pro v1.1-ultra (~$0.06 each). Scratch script like _gen_hm_stills.py."""
import sys, json, requests
sys.path.insert(0, "/Users/colemonroe/Projects/Ambientizer")
import fal_loop as fl
D = "/Users/colemonroe/Projects/Ambientizer/output/release/penelope_loom"
fal = fl._fal()
BASE = "Cinematic film still, photoreal, 35mm anamorphic, quiet, no text, no watermark, no lettering. "
P = {
 "loom_wide": BASE + "Wide interior shot, a great stone hall in a Mycenaean palace on Ithaca at night: a tall wooden warp-weighted "
    "loom stands near a window, a woman in a long cream and saffron woolen gown seen from behind and to one side, seated, her hands "
    "at the half-woven cloth, hair bound. One bronze oil lamp on a low table throws warm gold light over the threads and the plaster "
    "wall; the rest of the hall falls into deep blue shadow. Through the open window behind the loom, a dark sea under a thin moon "
    "and a few stars, far and calm. Everything still, patient, lamplit. Locked-off, no text.",
 "loom_close": BASE + "Medium shot at a warp-weighted loom in a lamplit stone room at night: the half-finished weaving fills the left of "
    "the frame, cream wool with a thin red border pattern, clay loom weights hanging below. A woman in profile at the right, calm "
    "face lit from below by a single bronze oil lamp, her hand resting on the shuttle. Behind her a small window shows the night "
    "sea and a thin moon. Warm gold on the thread, deep blue in the shadows, quiet. Locked-off, still.",
 "window_sea": BASE + "A tall wooden loom with half-woven cream cloth in the left foreground, lit by one bronze oil lamp, in a dark "
    "stone room on Ithaca. Beyond it a wide window frames the night sea far below the palace: calm water under a thin crescent moon, "
    "a faint moon path on the water, no ships, the far horizon empty. A folded woolen shawl on the window ledge. The weaver is absent; "
    "only her stool and the lamp. Lonely, warm, patient. Locked-off, still.",
 "lamplight": BASE + "Low angle from the floor of a lamplit stone hall at night: a weaver in a long cream gown sits at a tall loom, "
    "seen from behind, her head slightly bowed, long dark hair bound, a thread drawn in one raised hand. The single oil lamp beside her "
    "makes a warm gold island in a vast cool dark; faint columns recede into shadow. A sliver of moonlit sea through a distant doorway. "
    "Vermeer-like light, tender, no faces. Locked-off, still.",
}
for name, prompt in P.items():
    res = fal.subscribe("fal-ai/flux-pro/v1.1-ultra", arguments={"prompt": prompt, "aspect_ratio": "16:9",
          "output_format": "png", "safety_tolerance": "2", "raw": False}, with_logs=False)
    url = res["images"][0]["url"]; out = f"{D}/still_{name}.png"
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status(); open(out, "wb").write(r.content)
    print(name, out, res["images"][0].get("width"), res["images"][0].get("height"), flush=True)
print("DONE", flush=True)
