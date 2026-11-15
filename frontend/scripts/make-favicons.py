"""Builds the favicon set from the Fireproof logo (a red textured flame-and-match mark on white).

    python frontend/scripts/make-favicons.py [logo.webp]

Reads frontend/scripts/logo-source.webp unless a path is given, and writes into frontend/public:
favicon-16.png, favicon-32.png, icon-192.png and icon-512.png on a transparent background, and
apple-touch-icon.png (180 x 180) on white, because iOS fills transparency with black.
Needs Pillow and numpy (matplotlib pulls both in). Run it from anywhere; the paths come from this file's place.

The mark is never redrawn. The white page becomes transparent with a "colour to alpha" step: a pixel's
alpha is how far it is from white, and its colour is what it would be at full strength, so the red
texture and the soft edges survive and composite back onto white exactly as the logo looked. The
margin is trimmed, the mark is centred in a square, and each size is a LANCZOS resize. The two small
sizes get a little extra weight (the mark is thickened by a fraction of a pixel on white, then keyed
out again, and its alpha is lifted), so the thin arcs still read at 16 px.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

HERE = Path(__file__).resolve().parent
PUBLIC = HERE.parent / "public"
SOURCE = HERE / "logo-source.webp"

# Raw alpha under HAZE is the near-white noise of the source's background and becomes fully transparent; from FULL up it is fully
# opaque (the texture's lighter streaks keep their colour but not their see-through).
HAZE = 0.03
FULL = 0.85

# name, size, margin around the mark as a share of its longer side, background (None: transparent), extra weight (the MinFilter
# size on the 4x render; 0 for none)
OUTPUTS: list[tuple[str, int, float, tuple[int, int, int] | None, int]] = [
    ("favicon-16.png", 16, 0.03, None, 5),
    ("favicon-32.png", 32, 0.04, None, 3),
    ("apple-touch-icon.png", 180, 0.16, (255, 255, 255), 0),
    ("icon-192.png", 192, 0.10, None, 0),
    ("icon-512.png", 512, 0.10, None, 0),
]


def white_to_alpha(src: Image.Image) -> Image.Image:
    """RGBA with the white background transparent: GIMP's "Color to Alpha" for white."""
    a = np.asarray(src.convert("RGB"), dtype=np.float64) / 255.0
    raw = 1.0 - a.min(axis=2)  # how far from white
    rgb = np.clip((a - (1.0 - raw)[..., None]) / np.maximum(raw, 1e-6)[..., None], 0.0, 1.0)  # the colour at full strength
    alpha = np.clip((raw - HAZE) / (FULL - HAZE), 0.0, 1.0)
    out = np.dstack([rgb, alpha])
    return Image.fromarray(np.rint(out * 255.0).astype(np.uint8), "RGBA")


def trim(im: Image.Image) -> Image.Image:
    """Crops to the mark (everything with alpha above a faint threshold)."""
    box = im.getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox()
    if box is None:
        raise SystemExit("the logo has no mark: is the background not white?")
    return im.crop(box)


def square(im: Image.Image, margin: float) -> Image.Image:
    """The mark centred on a transparent square, `margin` of the longer side clear on every side."""
    w, h = im.size
    side = round(max(w, h) * (1.0 + 2.0 * margin))
    out = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    out.paste(im, ((side - w) // 2, (side - h) // 2))
    return out


def on_white(im: Image.Image) -> Image.Image:
    page = Image.new("RGBA", im.size, (255, 255, 255, 255))
    page.alpha_composite(im)
    return page.convert("RGB")


def weigh(im: Image.Image, size: int) -> Image.Image:
    """Extra weight for a tiny icon (`im` is 4x its size): thicken the mark on white (the darkest neighbour wins, so colours stay red),
    key the white out again, and lift the alpha a little."""
    heavy = white_to_alpha(on_white(im).filter(ImageFilter.MinFilter(size)))
    r, g, b, a = heavy.split()
    a = a.point(lambda v: min(255, round(255 * (v / 255.0) ** 0.8)))
    return Image.merge("RGBA", (r, g, b, a))


def render(master: Image.Image, size: int, margin: float, bg: tuple[int, int, int] | None, weight: int) -> Image.Image:
    sq = square(master, margin)
    if weight:
        sq = weigh(sq.resize((size * 4, size * 4), Image.LANCZOS), weight)
    out = sq.resize((size, size), Image.LANCZOS)
    return on_white(out) if bg is not None else out


def main() -> None:
    src_path = Path(sys.argv[1]) if len(sys.argv) > 1 else SOURCE
    master = trim(white_to_alpha(Image.open(src_path)))
    PUBLIC.mkdir(parents=True, exist_ok=True)
    for name, size, margin, bg, weight in OUTPUTS:
        render(master, size, margin, bg, weight).save(PUBLIC / name, optimize=True)
        print(f"wrote {PUBLIC / name} ({size} x {size})")


if __name__ == "__main__":
    main()
