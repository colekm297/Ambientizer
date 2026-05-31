"""
sam_segmenter.py — click-to-segment a region with SAM, for the motion brush.

Run with the SYSTEM python3.13 (where torch + transformers live), NOT the app
venv — same as segmenter.py / depth_estimator.py. Given an image and ONE click
point (normalized 0..1), SAM segments the object under the cursor. We then emit a
MOTION mask (white = "this moves") suitable as a brush mask:

  mode "freeze" → freeze the clicked object, move everything else  (mask = 1 - object)
  mode "move"   → move the clicked object, freeze everything else  (mask = object)

SAM is content-agnostic (no class vocabulary), so it works on stylized / space /
CGI art where ADE20K semantic segmentation ("sky", "water") fails.

    python3.13 sam_segmenter.py <image> <x_norm> <y_norm> <out_mask.png> <freeze|move>
"""

import sys
import numpy as np
from PIL import Image


def segment_point(image_path: str, x_norm: float, y_norm: float,
                  out_mask: str, mode: str = "freeze") -> None:
    import torch
    from transformers import SamModel, SamProcessor
    from scipy.ndimage import gaussian_filter

    # CPU: SAM's processor emits float64 tensors (image sizes) which MPS rejects,
    # and a single interactive click segments in a few seconds on CPU anyway.
    device = "cpu"
    model_id = "facebook/sam-vit-base"
    proc = SamProcessor.from_pretrained(model_id)
    model = SamModel.from_pretrained(model_id).to(device)
    model.eval()

    img = Image.open(image_path).convert("RGB")
    W, H = img.size
    px = int(round(min(max(x_norm, 0.0), 1.0) * (W - 1)))
    py = int(round(min(max(y_norm, 0.0), 1.0) * (H - 1)))

    inputs = proc(img, input_points=[[[px, py]]], return_tensors="pt").to(device)
    with torch.no_grad():
        out = model(**inputs)

    masks = proc.image_processor.post_process_masks(
        out.pred_masks.cpu(),
        inputs["original_sizes"].cpu(),
        inputs["reshaped_input_sizes"].cpu(),
    )
    # masks[0]: (1, num_masks, H, W) booleans. SAM returns 3 granularities; its
    # IoU scores sometimes rank a near-EMPTY mask highest, so we discard masks that
    # cover <2% of the frame and then take the highest-IoU survivor (falling back to
    # the largest-area mask). This reliably picks the actual clicked object.
    scores = out.iou_scores.cpu().numpy()[0, 0]
    cand = [(masks[0][0, i].numpy().astype(np.float32), float(scores[i]))
            for i in range(masks[0].shape[1])]
    fracs = [(m, s, m.mean()) for (m, s) in cand]
    substantial = [(m, s, f) for (m, s, f) in fracs if f >= 0.02]
    if substantial:
        obj = max(substantial, key=lambda x: x[1])[0]   # highest IoU among real masks
    else:
        obj = max(fracs, key=lambda x: x[2])[0]          # fallback: largest area

    # MOTION mask: white = moves.
    motion = (1.0 - obj) if mode == "freeze" else obj

    # Feather so the moving/frozen boundary isn't a hard cut (the compositor also
    # feathers, but softening here keeps the preview honest).
    sigma = max(W, H) / 240.0
    motion = gaussian_filter(motion, sigma=sigma)
    motion = np.clip(motion, 0.0, 1.0)

    Image.fromarray((motion * 255).astype(np.uint8)).save(out_mask)


if __name__ == "__main__":
    if len(sys.argv) < 6:
        print("usage: python3.13 sam_segmenter.py <image> <x_norm> <y_norm> <out_mask.png> <freeze|move>")
        sys.exit(1)
    segment_point(sys.argv[1], float(sys.argv[2]), float(sys.argv[3]),
                  sys.argv[4], sys.argv[5])
    print("SAM_OK", sys.argv[4])
