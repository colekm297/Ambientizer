"""Lock a generated loop to its source still: removes whole-frame shake/drift a video model adds.
Each frame is aligned (affine, ECC) to the still and warped back, so only local motion (smoke, light, water) remains.
Usage: .venv-omni/bin/python lock_frame.py <in.mp4> <still.png> <out.mp4>"""
import sys, subprocess, numpy as np, cv2
src, still, out = sys.argv[1:4]
cap = cv2.VideoCapture(src); fps = cap.get(cv2.CAP_PROP_FPS)
w, h = int(cap.get(3)), int(cap.get(4))
ref = cv2.cvtColor(cv2.resize(cv2.imread(still), (w, h), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
s = 0.25; refs = cv2.GaussianBlur(cv2.resize(ref, None, fx=s, fy=s), (5, 5), 0).astype(np.float32)
p = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
                      "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", out], stdin=subprocess.PIPE)
M = np.eye(2, 3, dtype=np.float32); shifts = []
crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-5)
while True:
    ok, f = cap.read()
    if not ok: break
    g = cv2.GaussianBlur(cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), None, fx=s, fy=s), (5, 5), 0).astype(np.float32)
    try: _, M = cv2.findTransformECC(refs, g, M, cv2.MOTION_AFFINE, crit, None, 5)
    except cv2.error: pass
    Mf = M.copy(); Mf[:, 2] /= s
    shifts.append(float(np.hypot(Mf[0, 2], Mf[1, 2])))
    fixed = cv2.warpAffine(f, Mf, (w, h), flags=cv2.INTER_LANCZOS4 + cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REFLECT)
    p.stdin.write(fixed.tobytes())
p.stdin.close(); p.wait()
print(f"frames {len(shifts)}  shift px mean {np.mean(shifts):.2f} max {np.max(shifts):.2f}")
