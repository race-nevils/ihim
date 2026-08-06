"""Generate the iHIM desktop icon — a Mark-I arc-reactor mark, drawn in code.

iHIM has no raster logo (the UI's icons are inline lucide SVGs), so the icon
is generated rather than converted: the bare reactor device on a transparent
canvas — no plate or rounded square behind it, the symbol IS the icon. A
gunmetal housing ring, ten dark-copper coil segments, a crimson tick ring and
a hot crimson core with the Y-strut, in the UI's HUD palette (gunmetal
#4A5568, dark copper #6B3A1F/#8E4F2E, crimson #DC143C).
Sized edge-to-edge at FILL 1.00, the same knob
and value the EdgeFlow icon uses, so the two sit at equal weight in the
taskbar. Pillow-only, fully deterministic — re-run any time.

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

# Device diameter as a fraction of the square, matching the EdgeFlow icon's
# knob of the same name: 1.00 = edge-to-edge, no transparent margin. Every
# radius below is a fraction of RAD (the device's own radius), so this one
# number scales the whole mark.
FILL = 1.00

FACE = (11, 11, 13, 255)       # #0b0b0d — reactor face
METAL = (74, 85, 104)          # #4A5568 gunmetal housing
METAL_DARK = (26, 29, 36)      # struts / hub
COPPER = (107, 58, 31)         # #6B3A1F dark-copper coil segments
COPPER_BRIGHT = (142, 79, 46)  # #8E4F2E coil edge highlight
RED = (220, 20, 60)            # #DC143C crimson
RED_HOT = (255, 93, 120)       # core mid
RED_WHITE = (255, 224, 230)    # core center


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

    # Centre on the pixel grid's true middle so the device is symmetric and the
    # rightmost/bottom column isn't clipped when FILL reaches 1.00.
    cx = cy = (S - 1) / 2
    R = (S - 1) / 2 * FILL  # device radius — every fraction below is of this

    # The device IS the icon: no plate, no margin. Everything stays inside the
    # face circle, so nothing bleeds onto whatever the icon sits over.
    draw.ellipse([cx - R, cy - R, cx + R, cy + R], fill=FACE)
    ring(draw, cx, cy, R * 0.964, R * 0.067, METAL)
    ring(draw, cx, cy, R * 0.883, R * 0.021, (110, 124, 148), 200)

    # Ten dark-copper coil segments + a subtle bright edge just outside them.
    seg_ring(draw, cx, cy, R * 0.705, R * 0.186, COPPER, 255, 10, 10)
    seg_ring(draw, cx, cy, R * 0.824, R * 0.031, COPPER_BRIGHT, 100, 10, 10)

    # Crimson tick ring between the coils and the core.
    seg_ring(draw, cx, cy, R * 0.494, R * 0.036, RED, 185, 20, 12)

    # Hot core: blurred crimson bloom, then concentric hot centers.
    core_glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    cgd = ImageDraw.Draw(core_glow)
    cgd.ellipse([cx - R * 0.402, cy - R * 0.402, cx + R * 0.402, cy + R * 0.402],
                fill=(*RED, 235))
    core_glow = core_glow.filter(ImageFilter.GaussianBlur(R * 0.056))
    img.alpha_composite(core_glow)

    core = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    cd = ImageDraw.Draw(core)
    for f, color in [(0.324, RED), (0.220, RED_HOT), (0.126, RED_WHITE)]:
        cd.ellipse([cx - R * f, cy - R * f, cx + R * f, cy + R * f],
                   fill=(*color, 255))
    core = core.filter(ImageFilter.GaussianBlur(R * 0.025))
    img.alpha_composite(core)

    # The blurred bloom spills a little past the face — clip everything back
    # to the device circle so the transparent canvas stays truly transparent.
    mask = Image.new("L", (S, S), 0)
    md = ImageDraw.Draw(mask)
    md.ellipse([cx - R, cy - R, cx + R, cy + R], fill=255)
    img.putalpha(Image.composite(img.getchannel("A"), mask.point(lambda _: 0), mask))

    # Y-strut over the core + center hub (the Mark-I signature).
    draw = ImageDraw.Draw(img)
    for ang in (90, 210, 330):
        a = math.radians(ang)
        x = cx + math.cos(a) * R * 0.324
        y = cy - math.sin(a) * R * 0.324
        draw.line([cx, cy, x, y], fill=(*METAL_DARK, 255), width=int(R * 0.056))
    hub = R * 0.077
    draw.ellipse([cx - hub, cy - hub, cx + hub, cy + hub],
                 fill=(*METAL_DARK, 255), outline=(*METAL, 255),
                 width=int(R * 0.021))
    return img


def main() -> None:
    master = make_master()
    master.resize((256, 256), Image.LANCZOS).save(PNG)
    imgs = [master.resize((s, s), Image.LANCZOS) for s in SIZES]
    imgs[-1].save(ICO, sizes=[(s, s) for s in SIZES], append_images=imgs[:-1])
    print(f"wrote {ICO.name} ({', '.join(str(s) for s in SIZES)}) + {PNG.name}")


if __name__ == "__main__":
    main()
