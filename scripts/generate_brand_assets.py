"""
Generates Trovee's logo and favicon: a coin-ledger mark.

Concept: a circular coin (the "earnings" idea) containing a single ledger
tick-mark/T-bar built from two confident strokes -- echoes both the letter T
(Trovee) and a checkmark/ledger-tick (a completed, trustworthy transaction).
Rendered in the brand's ink navy and brass tokens, no gradients or cliché
dollar signs, so it doesn't read as a generic finance-app clip-art icon.
"""

from PIL import Image, ImageDraw

NAVY = (11, 18, 32, 255)        # #0B1220
BRASS = (201, 169, 97, 255)     # #C9A961
PAPER = (247, 248, 250, 255)    # #F7F8FA
TRANSPARENT = (0, 0, 0, 0)


def draw_mark(size: int, bg=None):
    """Draws the coin/ledger-tick mark at the given pixel size."""
    scale = size / 512
    img = Image.new("RGBA", (size, size), bg if bg else TRANSPARENT)
    draw = ImageDraw.Draw(img)

    cx, cy = size / 2, size / 2
    r = 248 * scale

    # Outer coin ring (brass), filled navy disc inside
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=BRASS)
    inner_r = r - (16 * scale)
    draw.ellipse([cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r], fill=NAVY)

    # Ledger-tick / T mark: a horizontal bar + a descending stroke, off-center
    # like a check-mark crossed with a T, in brass against the navy disc.
    bar_w = 190 * scale
    bar_h = 34 * scale
    bar_y = cy - 92 * scale
    draw.rounded_rectangle(
        [cx - bar_w / 2, bar_y, cx + bar_w / 2, bar_y + bar_h],
        radius=bar_h / 2, fill=BRASS,
    )

    stem_w = 34 * scale
    stem_top = bar_y
    stem_bottom = cy + 130 * scale
    draw.rounded_rectangle(
        [cx - stem_w / 2, stem_top, cx + stem_w / 2, stem_bottom],
        radius=stem_w / 2, fill=BRASS,
    )

    # Small accent dot (a "coin notch") top-right of the disc, like a minted detail
    dot_r = 14 * scale
    dot_x = cx + 150 * scale
    dot_y = cy - 150 * scale
    draw.ellipse([dot_x - dot_r, dot_y - dot_r, dot_x + dot_r, dot_y + dot_r], fill=PAPER)

    return img


def make_logo():
    """Square logo with mark + wordmark below, on transparent background,
    suitable for app headers (1024x1024 for high-res use)."""
    size = 1024
    img = Image.new("RGBA", (size, int(size * 1.0)), TRANSPARENT)
    mark = draw_mark(720)
    img.paste(mark, ((size - 720) // 2, 40), mark)
    img.save("/home/claude/trovee/frontend/static/img/logo.png")

    # Also save a compact horizontal lockup placeholder isn't needed since the
    # frontend will pair this mark with a CSS text wordmark "Trovee" for crisp
    # typography (web fonts render sharper than rasterized text in a logo file).


def make_favicon():
    sizes = [16, 32, 48, 64]
    imgs = [draw_mark(s) for s in sizes]
    imgs[0].save(
        "/home/claude/trovee/frontend/static/img/favicon.ico",
        format="ICO",
        sizes=[(s, s) for s in sizes],
    )


if __name__ == "__main__":
    make_logo()
    make_favicon()
    print("Logo and favicon generated.")
