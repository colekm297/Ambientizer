"""Frodo Sails West thumbnail in the shipped IP-first style (big IP name, small subtitle)."""
from PIL import Image, ImageDraw, ImageFont, ImageFilter
D = "output/release/frodo_west"; TW, TH = 1280, 720
ANTON, ARCH = "fonts/Anton.ttf", "fonts/ArchivoBlack.ttf"
WHITE, DIM = (250, 248, 244), (236, 226, 206)
im = Image.open(f"{D}/start.png").convert("RGB").resize((TW, TH), Image.LANCZOS)
# soft bottom scrim so the type reads over the bright water
g = Image.new("L", (1, TH), 0); px = g.load()
for y in range(TH):
    t = max(0.0, (y/TH - 0.5)/0.5); px[0, y] = int(150 * (t**1.5))
im = Image.composite(Image.new("RGB", (TW, TH), (10, 8, 6)), im, g.resize((TW, TH)))
d = ImageDraw.Draw(im)
def tracked(s, font, y, track, fill, stroke):
    w = sum(d.textlength(c, font=font) for c in s) + track*(len(s)-1); x = (TW - w)/2
    for c in s:
        d.text((x+4, y+6), c, font=font, fill=(0,0,0), stroke_width=stroke, stroke_fill=(0,0,0), anchor="ls")
        d.text((x, y), c, font=font, fill=fill, stroke_width=stroke, stroke_fill=(0,0,0), anchor="ls")
        x += d.textlength(c, font=font) + track
tracked("THE LORD OF THE RINGS", ImageFont.truetype(ANTON, 112), 596, 10, WHITE, 5)
tracked("FRODO SAILS WEST  ·  1 HOUR", ImageFont.truetype(ARCH, 26), 650, 7, DIM, 2)
im.save(f"{D}/thumbnail.png", quality=95)
sheet = Image.new("RGB", (1280+336+168+40, 720), (30,30,30))
for i,(w,x) in enumerate(((1280,0),(336,1300),(168,1656))):
    sheet.paste(im.resize((w, int(w*9/16)), Image.LANCZOS), (x, 0))
sheet.save(f"{D}/_thumb_sizes.jpg", quality=85); print("thumb ok")
