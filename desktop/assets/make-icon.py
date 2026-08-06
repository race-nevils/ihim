"""Generate the iHIM desktop icon — a Mark-I arc-reactor mark, drawn in code.

iHIM has no raster logo (the UI's icons are inline lucide SVGs), so the icon
is generated rather than converted: a gunmetal housing ring, ten gold coil
segments, a crimson tick ring and a hot crimson core with the Y-strut, on a
dark rounded square — the UI's red/gold HUD palette (bg #0a0a0a, gunmetal
#4A5568, gold #DAA520/#FFD700, crimson #DC143C). Matches the in-app
<ihim-arc-menu> reactor mark. Pillow-only, fully deterministic — re-run any
time.

To swap in a real logo later: drop a >=1024px square PNG next to this file
as logo-src.png and rewrite this script to letterbox it.

Usage:  python assets/make-icon.py   (from desktop/, any Python w/ Pillow)
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
ICO = HERE / "icon.ico"
PNG = HERE / "icon.png"
SIZES = [16, 24, 32, 48, 64, 128, 256]

S = 1024  # master canvas, downsampled to each size

BG = (10, 10, 10, 255)         # #0a0a0a — the UI body surface
FACE = (11, 11, 13, 255)       # #0b0b0d — reactor face
METAL = (74, 85, 104)          # #4A5568 gunmetal housing
METAL_DARK = (26, 29, 36)      # struts / hub
GOLD = (218, 165, 32)          # #DAA520 coil segments
GOLD_BRIGHT = (255, 215, 0)    # #FFD700 coil edge highlight
RED = (220, 20, 60)            # #DC143C crimson
RED_HOT = (255, 93, 120)       # core mid
RED_WHITE = (255, 224, 230)    # core center


def rounded_square(draw: ImageDraw.ImageDraw) -> None:
    r = S * 0.22
    draw.rounded_rectangle([0, 0, S - 1, S - 1], radius=r, fill=BG)


def ring(draw, cx, cy, radius, width, color, alpha=255):
    box = [cx - radius, cy - radius, cx + radius, cy + radius]
    draw.ellipse(box, outline=(*color, alpha), width=int(width))


def seg_ring(draw, cx, cy, radius, width, color, alpha, count, gap_deg):
    """Segmented ring — `count` arcs with `gap_deg` between them."""
    box = [cx - radius, cy - radius, cx + radius, cy + radius]
    step = 360 / count
    for i in range(count):
        a0 = i * step + gap_deg / 2 - 90
        a1 = (i + 1) * step - gap_deg / 2 - 90
        draw.arc(box, a0, a1, fill=(*color, alpha), width=int(width))


def make_master() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    rounded_square(draw)

    cx = cy = S / 2

    # Soft crimson halo behind the device so small sizes still read "energy".
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([cx - S * 0.28, cy - S * 0.28, cx + S * 0.28, cy + S * 0.28],
               fill=(*RED, 55))
    glow = glow.filter(ImageFilter.GaussianBlur(S * 0.07))
    img.alpha_composite(glow)

    # Reactor face + gunmetal housing (double ring so the rim reads metallic).
    draw.ellipse([cx - S * 0.385, cy - S * 0.385, cx + S * 0.385, cy + S * 0.385],
                 fill=FACE)
    ring(draw, cx, cy, S * 0.372, S * 0.026, METAL)
    ring(draw, cx, cy, S * 0.340, S * 0.008, (110, 124, 148), 200)

    # Ten gold coil segments + a subtle bright edge just outside them.
    seg_ring(draw, cx, cy, S * 0.272, S * 0.072, GOLD, 255, 10, 10)
    seg_ring(draw, cx, cy, S * 0.318, S * 0.012, GOLD_BRIGHT, 150, 10, 10)

    # Crimson tick ring between the coils and the core.
    seg_ring(draw, cx, cy, S * 0.190, S * 0.014, RED, 185, 20, 12)

    # Hot core: blurred crimson bloom, then concentric hot centers.
    core_glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    cgd = ImageDraw.Draw(core_glow)
    cgd.ellipse([cx - S * 0.155, cy - S * 0.155, cx + S * 0.155, cy + S * 0.155],
                fill=(*RED, 235))
    core_glow = core_glow.filter(ImageFilter.GaussianBlur(S * 0.022))
    img.alpha_composite(core_glow)

    core = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    cd = ImageDraw.Draw(core)
    for r, color in [(0.125, RED), (0.085, RED_HOT), (0.048, RED_WHITE)]:
        cd.ellipse([cx - S * r, cy - S * r, cx + S * r, cy + S * r],
                   fill=(*color, 255))
    core = core.filter(ImageFilter.GaussianBlur(S * 0.010))
    img.alpha_composite(core)

    # Y-strut over the core + center hub (the Mark-I signature).
    draw = ImageDraw.Draw(img)
    for ang in (90, 210, 330):
        a = math.radians(ang)
        x = cx + math.cos(a) * S * 0.125
        y = cy - math.sin(a) * S * 0.125
        draw.line([cx, cy, x, y], fill=(*METAL_DARK, 255), width=int(S * 0.022))
    hub = S * 0.030
    draw.ellipse([cx - hub, cy - hub, cx + hub, cy + hub],
                 fill=(*METAL_DARK, 255), outline=(*METAL, 255),
                 width=int(S * 0.008))
    return img


def main() -> None:
    master = make_master()
    master.resize((256, 256), Image.LANCZOS).save(PNG)
    imgs = [master.resize((s, s), Image.LANCZOS) for s in SIZES]
    imgs[-1].save(ICO, sizes=[(s, s) for s in SIZES], append_images=imgs[:-1])
    print(f"wrote {ICO.name} ({', '.join(str(s) for s in SIZES)}) + {PNG.name}")


if __name__ == "__main__":
    main()
