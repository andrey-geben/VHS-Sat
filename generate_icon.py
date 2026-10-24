"""Generate all required icon formats from a source icon.ico.

Run after replacing icon.ico (project root), or when the design changes.
Requires Pillow: pip install pillow

Input:  icon.ico                      (source, project root)
Output: assets/vhs-sat.ico            (.exe icon for PyInstaller)
        static/favicon.ico            (browser fallback)
        static/favicon.svg            (modern browsers; PNG embedded)
        static/apple-touch-icon.png   (iOS home screen)
        static/icon-512.png           (PWA / social)
"""
from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image


FAVICON_ICO_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64)]
SVG_EMBED_SIZE = 32
APPLE_SIZE = 180
PWA_SIZE = 512


def load_source(path: Path) -> Image.Image:
    """Open icon.ico, prefer its largest bitmap if multi-size."""
    im = Image.open(path)
    sizes = list(im.info.get("sizes") or [])
    if sizes:
        largest = max(sizes, key=lambda s: s[0] * s[1])
        if im.size != largest:
            try:
                im2 = Image.open(path)
                im2.size = largest
                im2.load()
                im = im2
            except Exception:
                pass
    im.load()
    return im.convert("RGBA")


def save_ico(im: Image.Image, out: Path, sizes: list[tuple[int, int]]) -> None:
    im.save(out, format="ICO", sizes=sizes)


def save_png(im: Image.Image, out: Path, size: int) -> None:
    resized = im.resize((size, size), Image.LANCZOS)
    resized.save(out, format="PNG", optimize=True)


def save_svg_with_png(im: Image.Image, out: Path, size: int) -> None:
    """Embed a PNG (base64) inside an <svg> wrapper.

    Raster-to-vector conversion is not done here — this keeps the exact
    pixels the user provided while still giving browsers the small SVG
    favicon that modern Chrome/Firefox/Edge/Safari prefer.
    """
    buf = io.BytesIO()
    im.resize((size, size), Image.LANCZOS).save(buf, format="PNG", optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {size} {size}" width="{size}" height="{size}">\n'
        f'  <image width="{size}" height="{size}" '
        f'href="data:image/png;base64,{b64}"/>\n'
        f'</svg>\n'
    )
    out.write_text(svg, encoding="utf-8")


def main() -> None:
    root = Path(__file__).resolve().parent
    src = root / "icon.ico"

    if not src.exists():
        raise SystemExit(
            f"ERROR: {src} not found.\n"
            "Place your icon.ico in the project root and run again."
        )

    assets = root / "assets"
    static = root / "static"
    assets.mkdir(exist_ok=True)
    static.mkdir(exist_ok=True)

    im = load_source(src)
    print(f"Source: {src.name}  {im.size[0]}x{im.size[1]}")

    if im.size[0] < 256:
        print(f"WARN: source is {im.size[0]}x{im.size[1]} — .exe icon "
              f"will look blurry on high-DPI. Prefer 256x256 or larger.")

    # 1. .exe icon — copy source as-is (PyInstaller embeds multi-size directly)
    (assets / "vhs-sat.ico").write_bytes(src.read_bytes())
    print(f"OK  {assets / 'vhs-sat.ico'}")

    # 2. favicon.ico — multi-size, resized from source
    save_ico(im, static / "favicon.ico", FAVICON_ICO_SIZES)
    print(f"OK  {static / 'favicon.ico'}")

    # 3. favicon.svg — embedded PNG (works in all modern browsers)
    save_svg_with_png(im, static / "favicon.svg", SVG_EMBED_SIZE)
    print(f"OK  {static / 'favicon.svg'}")

    # 4. apple-touch-icon.png
    save_png(im, static / "apple-touch-icon.png", APPLE_SIZE)
    print(f"OK  {static / 'apple-touch-icon.png'}")

    # 5. icon-512.png (PWA / social preview)
    save_png(im, static / "icon-512.png", PWA_SIZE)
    print(f"OK  {static / 'icon-512.png'}")

    print("\nDone. Rebuild .exe:  .\\build-lite.ps1")


if __name__ == "__main__":
    main()