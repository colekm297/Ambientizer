"""
segmenter.py — semantic sky/water/flora masks from a still image, for region-aware motion.

Run with the SYSTEM python3.13 (where torch + transformers live), NOT the app
venv. The motion compositor shells out to this once per image and caches the
masks; they're reused to confine effects (nebula drift → sky, shimmer →
water, wind sway → flora) to the right regions.

Uses Segformer fine-tuned on ADE20K (≈15M params, GPU via MPS). Outputs
grayscale PNGs (white = region) softened at the edges.

    python3.13 segmenter.py <image_path> <out_sky_png> <out_water_png> [<out_flora_png>]
"""

import sys
import numpy as np
from PIL import Image

# ADE20K vegetation classes. Everything here bends in wind; nothing here is
# architecture, terrain or water. Matched by NAME so the list survives a change
# of model variant, same as the sky/water resolution below.
FLORA_WORDS = ("tree", "grass", "plant", "flower", "palm", "field")


def segment(image_path: str, out_sky: str, out_water: str,
            out_flora: str | None = None) -> None:
    import torch
    import torch.nn.functional as F
    from transformers import AutoImageProcessor, AutoModelForSemanticSegmentation
    from scipy.ndimage import gaussian_filter

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model_id = "nvidia/segformer-b5-finetuned-ade-640-640"
    proc = AutoImageProcessor.from_pretrained(model_id)
    model = AutoModelForSemanticSegmentation.from_pretrained(model_id).to(device)
    model.eval()

    img = Image.open(image_path).convert("RGB")
    W, H = img.size
    inputs = proc(images=img, return_tensors="pt").to(device)
    with torch.no_grad():
        logits = model(**inputs).logits  # (1, C, h, w)
    up = F.interpolate(logits, size=(H, W), mode="bilinear", align_corners=False)
    seg = up.argmax(dim=1)[0].to("cpu").numpy()  # HxW class ids

    # Resolve class ids by NAME (robust to index changes across model variants).
    id2label = {int(k): v for k, v in model.config.id2label.items()}
    sky_ids = [i for i, l in id2label.items() if "sky" in l.lower()]
    water_words = ("water", "sea", "river", "lake", "ocean")
    water_ids = [i for i, l in id2label.items() if any(w in l.lower() for w in water_words)]
    flora_ids = [i for i, l in id2label.items()
                 if any(w in l.lower().split() or w in l.lower() for w in FLORA_WORDS)]

    sigma = max(W, H) / 220.0

    def mask_png(ids, blur=True):
        m = np.isin(seg, ids).astype(np.float32) if ids else np.zeros((H, W), np.float32)
        if m.any() and blur:
            m = gaussian_filter(m, sigma=sigma)        # soften edges
            m = np.clip(m / max(m.max(), 1e-6), 0, 1)
        return Image.fromarray((m * 255).astype(np.uint8))

    mask_png(sky_ids).save(out_sky)
    mask_png(water_ids).save(out_water)
    if out_flora:
        # Flora is NOT blurred like the others. Sky and water are broad areas
        # where a soft edge only helps; foliage is a lace of thin stems and leaf
        # gaps, and blurring at the same sigma bleeds the mask out over the
        # background the plants are silhouetted against — which then gets dragged
        # along by the sway. A tight edge keeps the motion on the plant.
        mask_png(flora_ids, blur=False).save(out_flora)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("usage: python3.13 segmenter.py <image> <out_sky.png> <out_water.png> "
              "[<out_flora.png>]")
        sys.exit(1)
    segment(sys.argv[1], sys.argv[2], sys.argv[3],
            sys.argv[4] if len(sys.argv) > 4 else None)
    print("SEG_OK", *sys.argv[2:])
