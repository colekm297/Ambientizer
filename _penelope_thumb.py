"""Penelope at the Loom thumbnails: A IP-first (shipped style), B scene only, C gold moment line."""
from PIL import Image, ImageDraw, ImageFont
D = "output/release/penelope_loom"; TW, TH = 1280, 720
ANTON, ARCH = "fonts/Anton.ttf", "fonts/ArchivoBlack.ttf"
WHITE, DIM, GOLD = (250, 248, 244), (236, 226, 206), (232, 190, 110)
base = Image.open(f"{D}/start.png").convert("RGB").resize((TW, TH), Image.LANCZOS)
def scrim(im, strength=120):
    g = Image.new("L", (1, TH), 0); px = g.load()
    for y in range(TH):
        t = max(0.0, (y/TH - 0.5)/0.5); px[0, y] = int(strength * (t**1.5))
    return Image.composite(Image.new("RGB", (TW, TH), (8, 6, 4)), im, g.resize((TW, TH)))
def tracked(d, s, font, y, track, fill, stroke):
    w = sum(d.textlength(c, font=font) for c in s) + track*(len(s)-1); x = (TW - w)/2
    for c in s:
        d.text((x+4, y+6), c, font=font, fill=(0,0,0), stroke_width=stroke, stroke_fill=(0,0,0), anchor="ls")
        d.text((x, y), c, font=font, fill=fill, stroke_width=stroke, stroke_fill=(0,0,0), anchor="ls")
        x += d.textlength(c, font=font) + track
# A: IP-first
im = scrim(base.copy()); d = ImageDraw.Draw(im)
tracked(d, "THE ODYSSEY", ImageFont.truetype(ANTON, 128), 600, 12, WHITE, 5)
tracked(d, "PENELOPE AT THE LOOM  ·  1 HOUR", ImageFont.truetype(ARCH, 26), 654, 7, DIM, 2)
im.save(f"{D}/thumbnail.png", quality=95)
# B: scene only
base.save(f"{D}/thumbnail_b_scene.png", quality=95)
# C: gold moment line
im = scrim(base.copy(), 100); d = ImageDraw.Draw(im)
tracked(d, "TWENTY YEARS", ImageFont.truetype(ANTON, 118), 606, 14, GOLD, 5)
tracked(d, "THE ODYSSEY  ·  1 HOUR AMBIENT", ImageFont.truetype(ARCH, 24), 656, 7, DIM, 2)
im.save(f"{D}/thumbnail_c_moment.png", quality=95)
sheet = Image.new("RGB", (1280+336+168+40, 720), (30,30,30)); A = Image.open(f"{D}/thumbnail.png")
for w, x in ((1280,0),(336,1300),(168,1656)):
    sheet.paste(A.resize((w, int(w*9/16)), Image.LANCZOS), (x, 0))
sheet.save(f"{D}/_thumb_sizes.jpg", quality=85); print("thumbs ok")
