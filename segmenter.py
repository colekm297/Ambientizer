"""
segmenter.py — semantic sky/water masks from a still image, for region-aware motion.

Run with the SYSTEM python3.13 (where torch + transformers live), NOT the app
venv. The motion compositor shells out to this once per image and caches the
two masks; they're reused to confine effects (nebula drift → sky, shimmer →
water) to the right regions.

Uses Segformer fine-tuned on ADE20K (≈15M params, GPU via MPS). Outputs two
grayscale PNGs (white = region) softened at the edges.

    python3.13 segmenter.py <image_path> <out_sky_png> <out_water_png>
"""

import sys
import numpy as np
from PIL import Image


def segment(image_path: str, out_sky: str, out_water: str) -> None:
    import torch
    import torch.nn.functional as F
    from transformers import AutoImageProcessor, AutoModelForSemanticSegmentation
    from scipy.ndimage import gaussian_filter

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model_id = "nvidia/segformer-b0-finetuned-ade-512-512"
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

    sigma = max(W, H) / 220.0

    def mask_png(ids):
        m = np.isin(seg, ids).astype(np.float32) if ids else np.zeros((H, W), np.float32)
        if m.any():
            m = gaussian_filter(m, sigma=sigma)        # soften edges
            m = np.clip(m / max(m.max(), 1e-6), 0, 1)
        return Image.fromarray((m * 255).astype(np.uint8))

    mask_png(sky_ids).save(out_sky)
    mask_png(water_ids).save(out_water)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("usage: python3.13 segmenter.py <image> <out_sky.png> <out_water.png>")
        sys.exit(1)
    segment(sys.argv[1], sys.argv[2], sys.argv[3])
    print("SEG_OK", sys.argv[2], sys.argv[3])
