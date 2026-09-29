#!/usr/bin/env python3
"""Generates the small, deterministic raster PNGs used by
frontend/src/data/preview/*.json fixtures (design/target-state-preview).

These are NOT model output -- they are synthetic images, each with "PREVIEW"
burned into the pixels, used only so the target-state screens have something
to render for a raster LayerRef. Run this script again (deterministic, no
random seed) whenever a new preview raster is needed; commit the PNGs it
writes under frontend/public/preview/ since Vite serves that directory as-is
and the frontend has no Python runtime to generate them at request time.

Usage: conda run -n sih26 python frontend/scripts/gen_preview_assets.py
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT_DIR = Path(__file__).resolve().parents[1] / "public" / "preview"
SIZE = 256


def _stamp(draw: ImageDraw.ImageDraw, text: str, size: tuple[int, int]) -> None:
    w, h = size
    draw.text((8, h - 18), "PREVIEW", fill=(255, 255, 255, 160))
    draw.text((8, 6), text, fill=(255, 255, 255, 200))


def gen_dem_hillshade(path: Path) -> None:
    """A synthetic hillshade: a diagonal ridge with simple directional shading,
    standing in for a real SRTM GL1 (src_033) hillshade until M1 produces one."""
    img = Image.new("RGB", (SIZE, SIZE))
    px = img.load()
    for y in range(SIZE):
        for x in range(SIZE):
            ridge = math.sin((x + y) / SIZE * math.pi) * 0.5 + 0.5
            shade = max(0.0, min(1.0, ridge - (x / SIZE) * 0.2))
            v = int(30 + shade * 180)
            px[x, y] = (v, int(v * 0.95), int(v * 0.85))
    draw = ImageDraw.Draw(img, "RGBA")
    _stamp(draw, "illustrative DEM hillshade", (SIZE, SIZE))
    img.save(path)


def gen_domain_mask(path: Path) -> None:
    """A synthetic domain mask: 1 (opaque) inside an illustrative catchment
    outline, 0 (transparent) outside -- stands in for M1's real domain_mask.tif
    until the terrain pipeline runs (CLAUDE.md rule 8)."""
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    points = [(40, 20), (200, 40), (230, 120), (180, 230), (60, 210), (20, 100)]
    draw.polygon(points, fill=(120, 200, 190, 110), outline=(120, 200, 190, 220))
    _stamp(draw, "illustrative domain mask", (SIZE, SIZE))
    img.save(path)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    gen_dem_hillshade(OUT_DIR / "dem_hillshade_teesta.png")
    gen_domain_mask(OUT_DIR / "domain_mask_teesta.png")
    print(f"Wrote preview rasters to {OUT_DIR}")


if __name__ == "__main__":
    main()
