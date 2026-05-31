"""
depth_estimator.py — estimate a depth map from a still image for 2.5D parallax.

Run with the SYSTEM python3.13 (where torch + transformers live), NOT the app
venv. The motion compositor shells out to this once per image and caches the
result; the depth map is then reused for the parallax warp.

Uses Depth-Anything-V2-Small (≈100 MB, GPU-accelerated on Apple Silicon via MPS).
Output: a grayscale PNG where brighter = nearer the camera.

    python3.13 depth_estimator.py <image_path> <out_depth_png>
"""

import sys
import numpy as np
from PIL import Image


def estimate(image_path: str, out_path: str) -> str:
    import torch
    from transformers import pipeline

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    pipe = pipeline(
        "depth-estimation",
        model="depth-anything/Depth-Anything-V2-Small-hf",
        device=device,
    )
    img = Image.open(image_path).convert("RGB")
    result = pipe(img)

    # "predicted_depth" is relative inverse depth (larger = nearer). Normalize 0..255.
    depth = result["predicted_depth"]
    if hasattr(depth, "detach"):
        arr = depth.detach().to("cpu").float().numpy()
    else:
        arr = np.asarray(depth, dtype=np.float32)
    arr = np.squeeze(arr)
    arr -= arr.min()
    arr /= max(float(arr.max()), 1e-6)

    # Resize depth to the source image size (model may downscale internally).
    dimg = Image.fromarray((arr * 255).astype(np.uint8)).resize(img.size, Image.BILINEAR)
    dimg.save(out_path)
    return out_path


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: python3.13 depth_estimator.py <image> <out.png>")
        sys.exit(1)
    out = estimate(sys.argv[1], sys.argv[2])
    print("DEPTH_OK", out)
