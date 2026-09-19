"""Three clickbait-direction thumbnails for the Hail Mary / Tau Ceti piece (IP / curiosity / benefit)."""
from PIL import Image, ImageFont, ImageDraw
import _clickbait_thumbs as T
D = "output/release/hailmary_tauceti"; SRC = f"{D}/still_window_planet_crop.png"
BLUE = (140, 200, 255)
def h1():
    im = T.crop(SRC, (0.05, 0.02, 0.95, 0.98)); im = T.scrim(im, "top", 200, 0.5); im = T.vignette(im, 80)
    T.text(im, "PROJECT HAIL MARY", 150, (T.TW//2, 190), track=4)
    T.text(im, "TAU CETI", 84, (T.TW//2, 300), fill=T.AMBER, stroke=7, track=10)
    return im, "H1 IP: PROJECT HAIL MARY / TAU CETI"
def h2():
    im = T.crop(SRC, (0.05, 0.02, 0.95, 0.98)); im = T.scrim(im, "top", 210, 0.5); im = T.vignette(im, 80)
    T.pill(im, "PROJECT HAIL MARY", (48, 640), size=44)
    T.text(im, "12 LIGHT YEARS", 190, (T.TW//2, 200), track=6)
    T.text(im, "FROM HOME", 96, (T.TW//2, 305), fill=T.AMBER, stroke=8, track=10)
    return im, "H2 curiosity: 12 LIGHT YEARS FROM HOME"
def h3():
    im = T.crop(SRC, (0.05, 0.02, 0.95, 0.98)); im = T.scrim(im, "top", 200, 0.5)
    T.pill(im, "PROJECT HAIL MARY", (48, 640), size=44)
    T.text(im, "1 HOUR", 210, (T.TW//2, 205), track=8)
    T.text(im, "OF DEEP FOCUS", 90, (T.TW//2, 308), fill=T.AMBER, stroke=8, track=8)
    return im, "H3 benefit: 1 HOUR OF DEEP FOCUS"
made = []
for fn in (h1, h2, h3):
    im, label = fn(); p = f"{D}/thumb_{fn.__name__}.png"; im.save(p, quality=95); made.append((p, label))
lf = ImageFont.truetype("fonts/Oswald.ttf", 20); pad = 24; row_h = 420
sheet = Image.new("RGB", (pad*4 + 640 + 336 + 168, pad + row_h*3), (245, 245, 245)); d = ImageDraw.Draw(sheet)
for i, (p, label) in enumerate(made):
    im = Image.open(p); y = pad + i*row_h; d.text((pad, y), label, fill=(0, 0, 0), font=lf); y += 30; x = pad
    for w in (640, 336, 168):
        sheet.paste(im.resize((w, w*9//16), Image.LANCZOS), (x, y)); x += w + pad
sheet.save(f"{D}/_thumbs_sheet.png"); print("ok")
