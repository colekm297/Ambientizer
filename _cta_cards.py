"""Subscribe + like card mockups (intro card after the sting, end card) and the
channel watermark asset. Mockups only; no re-render of live videos."""
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
import os
OUT = "brand/out/cta"; os.makedirs(OUT, exist_ok=True)
W, H = 1920, 1080
OSW = "fonts/Oswald.ttf"; ARCH = "fonts/ArchivoBlack.ttf"
CREAM = (245, 240, 230); AMBER = (232, 176, 96); DIM = (215, 205, 190)

def mark(size, color=CREAM):
    """Bold aperture mark from the avatar, recolored, transparent background."""
    a = Image.open("brand/out/avatar_aperture_bold_v2.png").convert("L")
    # the avatar is a white mark on a black disc: threshold the white
    m = a.point(lambda v: 255 if v > 140 else 0).resize((size, size), Image.LANCZOS)
    out = Image.new("RGBA", (size, size), color + (0,)); out.putalpha(m)
    return out

def shadow_text(d, xy, s, font, fill, anchor="la"):
    x, y = xy
    d.text((x+2, y+3), s, font=font, fill=(0, 0, 0, 160), anchor=anchor)
    d.text((x, y), s, font=font, fill=fill, anchor=anchor)

def intro_card(frame, out, headline, line2):
    """Lower-left card, 10 s after the sting: small mark, two lines, subscribe chip. Plate is sized to the text."""
    im = Image.open(frame).convert("RGBA")
    f1, f2, f3 = ImageFont.truetype(OSW, 46), ImageFont.truetype(OSW, 32), ImageFont.truetype(OSW, 26)
    d0 = ImageDraw.Draw(im)
    tx = 100 + 120 + 40                      # plate left + mark + gap
    w_text = max(d0.textlength(headline, font=f1), d0.textlength(line2, font=f2), 220 + 30 + d0.textlength("a like helps a lot too", font=f3))
    x0, y0 = 72, 790; x1 = int(tx + w_text + 48); y1 = 1010
    plate = Image.new("RGBA", (W, H), (0, 0, 0, 0)); pd = ImageDraw.Draw(plate)
    pd.rounded_rectangle((x0, y0, x1, y1), radius=22, fill=(10, 8, 12, 165))
    im = Image.alpha_composite(im, plate.filter(ImageFilter.GaussianBlur(1.5)))
    im.alpha_composite(mark(120), (100, 840))
    d = ImageDraw.Draw(im)
    shadow_text(d, (tx, 822), headline, f1, CREAM)
    shadow_text(d, (tx, 886), line2, f2, DIM)
    d.rounded_rectangle((tx, 940, tx + 220, 988), radius=8, fill=(204, 0, 0))
    d.text((tx + 110, 964), "SUBSCRIBE", font=ImageFont.truetype(ARCH, 22), fill=(255, 255, 255), anchor="mm")
    d.text((tx + 250, 964), "a like helps a lot too", font=f3, fill=DIM, anchor="lm")
    im.convert("RGB").save(out, quality=94)

def end_card(frame, out, next_title, next_thumb):
    """Last 25 s: frame darkens 40%, mark + channel name centre-top, 'more like this' tile right, subscribe/like left."""
    im = Image.open(frame).convert("RGB")
    im = Image.blend(im, Image.new("RGB", (W, H), (6, 5, 8)), 0.45).convert("RGBA")
    mk = mark(150); im.alpha_composite(mk, (W//2 - 75, 110))
    d = ImageDraw.Draw(im)
    shadow_text(d, (W//2, 300), "THE SPACE OF SOUND", ImageFont.truetype(ARCH, 40), CREAM, anchor="mm")
    shadow_text(d, (W//2, 356), "new music every week", ImageFont.truetype(OSW, 32), DIM, anchor="mm")
    # left: subscribe + like block (YouTube's end-screen subscribe element sits here; this is the painted version)
    d.rounded_rectangle((300, 470, 820, 820), radius=24, fill=(14, 12, 16, 170))
    d.ellipse((470, 500, 650, 680), fill=(0, 0, 0)); im.alpha_composite(mark(140), (490, 520)); d = ImageDraw.Draw(im)
    d.rounded_rectangle((420, 710, 700, 768), radius=10, fill=(204, 0, 0))
    d.text((560, 739), "SUBSCRIBE", font=ImageFont.truetype(ARCH, 26), fill=(255, 255, 255), anchor="mm")
    shadow_text(d, (560, 800), "like and subscribe", ImageFont.truetype(OSW, 26), DIM, anchor="mm")
    # right: more-like-this tile (YouTube's video element goes here; painted placeholder under it)
    tile = Image.open(next_thumb).convert("RGB").resize((560, 315), Image.LANCZOS)
    d.rounded_rectangle((1090, 470, 1680, 820), radius=24, fill=(14, 12, 16, 170))
    im.paste(tile, (1105, 485)); d = ImageDraw.Draw(im)
    shadow_text(d, (1385, 830), "MORE LIKE THIS", ImageFont.truetype(ARCH, 22), AMBER, anchor="mm")
    shadow_text(d, (1385, 866), next_title, ImageFont.truetype(OSW, 26), CREAM, anchor="mm")
    im.convert("RGB").save(out, quality=94)

if __name__ == "__main__":
    intro_card("brand/ref/frames/dusk_8.png", f"{OUT}/intro_dusk.png",
               "If you liked this track, please like and subscribe.", "New music every week.")
    intro_card("brand/ref/frames/fw_8.png", f"{OUT}/intro_fairwind.png",
               "If you liked this track, please like and subscribe.", "New music every week.")
    end_card("brand/ref/frames/dusk_end.png", f"{OUT}/end_dusk.png", "Dawn Over Arrakis", "brand/ref/dawn_kg-RRBuGsuQ.jpg")
    # watermark asset: YouTube wants square, transparent PNG, 150x150 min, 1 MB max
    wm = mark(400, (255, 255, 255)); wm.save(f"{OUT}/watermark_aperture_400.png")
    # contact sheet
    sheet = Image.new("RGB", (1920//2*2 + 60, 1080//2*2 + 90), (245, 245, 245)); d = ImageDraw.Draw(sheet); f = ImageFont.truetype(OSW, 20)
    for i, (p, l) in enumerate([("intro_dusk", "intro card, Dusk, t=8s"), ("intro_fairwind", "intro card, Fair Wind, t=8s"), ("end_dusk", "end card, Dusk, last 25 s")]):
        x = 20 + (i % 2) * (960 + 20); y = 20 + (i // 2) * (540 + 30)
        sheet.paste(Image.open(f"{OUT}/{p}.png").resize((960, 540), Image.LANCZOS), (x, y + 24)); d.text((x, y), l, fill=(0, 0, 0), font=f)
    wmv = Image.new("RGB", (960, 540), (40, 40, 44)); wmv.paste(Image.open(f"{OUT}/watermark_aperture_400.png").resize((150, 150)), (780, 360), Image.open(f"{OUT}/watermark_aperture_400.png").resize((150, 150)))
    sheet.paste(wmv, (20 + 980, 20 + 570 + 24)); d.text((20 + 980, 20 + 570), "watermark asset at 150 px, lower-right, as YouTube places it", fill=(0, 0, 0), font=f)
    sheet.save(f"{OUT}/_sheet.png"); print("ok")
