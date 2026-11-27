"""Draws the Readhold logo from one geometry spec: an open book whose pages carry climbing holds, with a bookmark.

Each idea you grasp is a hold for the next; the bookmark keeps your place. Chosen on 2026-11-26 from the logo canvas
("Round 2"). Writes:
  assets/logo.svg (the full icon), web/static/logo.svg (the simple icon, for the menu and the browser tab),
  assets/logo-512.png and assets/readhold.ico (16 to 256 px: the simple icon up to 32 px, the full one above).
Run:  uv run python scripts/make_icon.py   (needs Pillow, installed with the dev dependencies)
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
V = 120  # design units (the SVG viewBox)
RADIUS = 30
BG_FROM, BG_TO = "#3D5AFE", "#8E2DE2"  # diagonal, top left to bottom right
PAGE, SPINE, LINK = "#FFFFFF", "#C9C2FF", "#3D5AFE"
BOOKMARK = "#FFB627"
# the open book: two pages joined at the spine (cubic curves)
BOOK = [((20, 40), (36, 33), (49, 35), (60, 44)), ((60, 44), (71, 35), (84, 33), (100, 40)), ((100, 40), (100, 40), (100, 90), (100, 90)),
        ((100, 90), (84, 84), (71, 86), (60, 95)), ((60, 95), (49, 86), (36, 84), (20, 90)), ((20, 90), (20, 90), (20, 40), (20, 40))]
HOLDS = [(36, 72, 5, "#FFB627"), (46, 58, 5, "#FF7A59"), (76, 66, 5, "#2EC4B6"), (86, 52, 5, "#FFB627")]
LINKS = [((36, 72), (46, 58)), ((76, 66), (86, 52))]
BOOKMARK_PTS = [(80, 22), (92, 22), (92, 48), (86, 43), (80, 48)]
SIMPLE_HOLDS = [(40, 66, 7, "#FFB627"), (80, 60, 7, "#2EC4B6")]  # the small icon: two bigger holds, no spine, links or bookmark


def _book_path() -> str:
    (start, *_), *_ = BOOK
    d = f"M{start[0]} {start[1]}"
    for _, c1, c2, end in BOOK:
        d += f" C{c1[0]} {c1[1]} {c2[0]} {c2[1]} {end[0]} {end[1]}"
    return d + " Z"


def svg(simple: bool = False) -> str:
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {V} {V}" role="img" aria-label="Readhold">',
        "<title>Readhold</title>",
        f'<defs><linearGradient id="rh" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{BG_FROM}"/>'
        f'<stop offset="1" stop-color="{BG_TO}"/></linearGradient></defs>',
        f'<rect width="{V}" height="{V}" rx="{RADIUS}" fill="url(#rh)"/>',
        f'<path d="{_book_path()}" fill="{PAGE}"/>',
    ]
    if simple:
        parts += [f'<circle cx="{x}" cy="{y}" r="{r}" fill="{c}"/>' for x, y, r, c in SIMPLE_HOLDS]
    else:
        parts.append(f'<path d="M60 44 V95" stroke="{SPINE}" stroke-width="3"/>')
        parts += [f'<circle cx="{x}" cy="{y}" r="{r}" fill="{c}"/>' for x, y, r, c in HOLDS]
        parts += [f'<path d="M{a[0]} {a[1]} L{b[0]} {b[1]}" stroke="{LINK}" stroke-width="2" stroke-dasharray="2 3"/>' for a, b in LINKS]
        pts = " ".join(f"{x},{y}" for x, y in BOOKMARK_PTS)
        parts.append(f'<polygon points="{pts}" fill="{BOOKMARK}"/>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def _bezier(p0, p1, p2, p3, steps: int = 40) -> list[tuple[float, float]]:
    out = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        out.append((u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                    u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1]))
    return out


def raster(size: int) -> Image.Image:
    """Supersampled drawing of the same geometry, then scaled down for crisp anti-aliasing. The simple icon up to 32 px."""
    simple = size <= 32
    k = 8 * size / V
    big = int(V * k)
    a, b = _rgb(BG_FROM), _rgb(BG_TO)
    grad = Image.new("RGBA", (big, big))
    px = grad.load()
    for y in range(big):
        for x in range(big):
            t = (x + y) / (2 * (big - 1))
            px[x, y] = tuple(round(p + (q - p) * t) for p, q in zip(a, b)) + (255,)
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, big - 1, big - 1), radius=int(RADIUS * k), fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img, "RGBA")
    outline = [pt for seg in BOOK for pt in _bezier(*seg)]
    d.polygon([(x * k, y * k) for x, y in outline], fill=PAGE)
    holds = SIMPLE_HOLDS if simple else HOLDS
    if not simple:
        d.line([(60 * k, 44 * k), (60 * k, 95 * k)], fill=SPINE, width=max(1, int(3 * k)))
        for (x0, y0), (x1, y1) in LINKS:  # dashed: short pieces along the line
            for j in range(0, 10, 2):
                t0, t1 = j / 10, (j + 1) / 10
                d.line([((x0 + (x1 - x0) * t0) * k, (y0 + (y1 - y0) * t0) * k), ((x0 + (x1 - x0) * t1) * k, (y0 + (y1 - y0) * t1) * k)],
                       fill=LINK, width=max(1, int(2 * k)))
        d.polygon([(x * k, y * k) for x, y in BOOKMARK_PTS], fill=BOOKMARK)
    for x, y, r, c in holds:
        d.ellipse(((x - r) * k, (y - r) * k, (x + r) * k, (y + r) * k), fill=c)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    (assets / "logo.svg").write_text(svg(), "utf-8")
    (ROOT / "web" / "static" / "logo.svg").write_text(svg(simple=True), "utf-8")
    raster(512).save(assets / "logo-512.png")
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    frames = [raster(s) for s in sizes]
    frames[-1].save(assets / "readhold.ico", format="ICO", sizes=[(s, s) for s in sizes], append_images=frames[:-1])
    print("Wrote assets/logo.svg, assets/logo-512.png, assets/readhold.ico, web/static/logo.svg")


if __name__ == "__main__":
    main()
