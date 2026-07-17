"""Generate the iHIM desktop icon — an arc-reactor mark, drawn in code.

iHIM has no raster logo (the UI's icons are inline lucide SVGs and its
identity is the arc-reactor energy background), so the icon is generated
rather than converted: concentric glowing rings + a hot core on a dark
rounded square, in the UI's palette (Catppuccin base #11111b, blue #89b4fa,
text #cdd6f4). Pillow-only, fully deterministic — re-run any time.

To swap in a real logo later: drop a >=1024px square PNG next to this file
as logo-src.png and rewrite this script to letterbox it (see
desktop-app/desktop/assets/make-icon.py for that pattern).

Usage:  python assets/make-icon.py   (from IHIM/desktop/, any Python w/ Pillow)
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
ICO = HERE / "icon.ico"
PNG = HERE / "icon.png"
SIZES = [16, 24, 32, 48, 64, 128, 256]

S = 1024  # master canvas, downsampled to each size

BG = (17, 17, 27, 255)        # #11111b Catppuccin crust — matches the UI body
RING = (137, 180, 250)        # #89b4fa Catppuccin blue — the UI accent
CORE = (205, 214, 244)        # #cdd6f4 near-white core


def rounded_square(draw: ImageDraw.ImageDraw) -> None:
    r = S * 0.22
    draw.rounded_rectangle([0, 0, S - 1, S - 1], radius=r, fill=BG)


def ring(draw, cx, cy, radius, width, color, alpha):
    box = [cx - radius, cy - radius, cx + radius, cy + radius]
    draw.ellipse(box, outline=(*color, alpha), width=width)


def make_master() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    rounded_square(draw)

    cx = cy = S / 2

    # Glow layer: soft halo behind the rings so small sizes still read "energy".
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([cx - S * 0.34, cy - S * 0.34, cx + S * 0.34, cy + S * 0.34],
               fill=(*RING, 90))
    glow = glow.filter(ImageFilter.GaussianBlur(S * 0.07))
    img.alpha_composite(glow)

    # Reactor rings, outer to inner.
    ring(draw, cx, cy, S * 0.360, int(S * 0.030), RING, 180)
    ring(draw, cx, cy, S * 0.270, int(S * 0.042), RING, 255)
    ring(draw, cx, cy, S * 0.180, int(S * 0.030), RING, 200)

    # Segment gaps on the middle ring (the reactor look): punch 8 notches.
    notch = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    nd = ImageDraw.Draw(notch)
    import math
    for i in range(8):
        a = math.radians(i * 45 + 22.5)
        x = cx + math.cos(a) * S * 0.270
        y = cy + math.sin(a) * S * 0.270
        w = S * 0.024
        nd.ellipse([x - w, y - w, x + w, y + w], fill=BG)
    img.alpha_composite(notch)

    # Hot core.
    core_glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    cgd = ImageDraw.Draw(core_glow)
    cgd.ellipse([cx - S * 0.11, cy - S * 0.11, cx + S * 0.11, cy + S * 0.11],
                fill=(*RING, 220))
    core_glow = core_glow.filter(ImageFilter.GaussianBlur(S * 0.02))
    img.alpha_composite(core_glow)
    draw = ImageDraw.Draw(img)
    draw.ellipse([cx - S * 0.075, cy - S * 0.075, cx + S * 0.075, cy + S * 0.075],
                 fill=(*CORE, 255))
    return img


def main() -> None:
    master = make_master()
    master.resize((256, 256), Image.LANCZOS).save(PNG)
    imgs = [master.resize((s, s), Image.LANCZOS) for s in SIZES]
    imgs[-1].save(ICO, sizes=[(s, s) for s in SIZES], append_images=imgs[:-1])
    print(f"wrote {ICO.name} ({', '.join(str(s) for s in SIZES)}) + {PNG.name}")


if __name__ == "__main__":
    main()
