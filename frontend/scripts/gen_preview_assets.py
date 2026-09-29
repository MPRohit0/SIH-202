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
import struct
from pathlib import Path

from PIL import Image, ImageDraw

OUT_DIR = Path(__file__).resolve().parents[1] / "public" / "preview"
SIZE = 256
NODATA = -9999.0


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


def gen_depth_raster(path: Path, label: str) -> None:
    """A small illustrative depth_p50-style raster (blue ramp with a wet channel
    band), used as the 2D-map fallback layer for screens whose primary view is
    the 3D scene (screen 4's SPH near-field query)."""
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    px = img.load()
    for y in range(SIZE):
        for x in range(SIZE):
            channel_center = SIZE * (0.5 + 0.18 * math.sin(y / SIZE * math.pi * 2.2))
            dist = abs(x - channel_center)
            if dist < SIZE * 0.16:
                t = 1 - dist / (SIZE * 0.16)
                px[x, y] = (int(60 + t * 40), int(120 + t * 60), int(200 + t * 40), int(140 + t * 100))
    draw = ImageDraw.Draw(img, "RGBA")
    _stamp(draw, label, (SIZE, SIZE))
    img.save(path)


def gen_nearfield_scene(terrain_path: Path, flood_path: Path, width: int, height: int) -> None:
    """A synthetic near-field terrain + flood_surface pair, in the exact
    contracts/scene3d.md format (headerless float32_le_row_major, upper-left
    origin, `-9999.0` nodata). Screen 4 (near-field 3D) needs geometry to
    render; there is no usable real Teesta SPH near-field run in this repo to
    reuse (the real a02 attempt is flagged anomalous -- see
    ui_text.json onboarding.noPairedSph), so this is illustrative terrain: a
    valley dropping from the upper-left corner to the lower-right, with a
    meandering wet channel down the middle carrying illustrative depth.
    """
    terrain: list[float] = []
    flood: list[float] = []
    min_elev, max_elev = 1750.0, 1920.0
    for row in range(height):
        for col in range(width):
            along = row / max(height - 1, 1)  # 0 upstream -> 1 downstream
            across = col / max(width - 1, 1)
            bed = max_elev - along * (max_elev - min_elev) + math.sin(across * math.pi) * 6.0
            terrain.append(bed)
            channel_center = 0.5 + 0.18 * math.sin(along * math.pi * 2.2)
            dist_from_channel = abs(across - channel_center)
            if dist_from_channel < 0.16:
                depth = (0.16 - dist_from_channel) / 0.16 * (3.5 - along * 1.5)
                flood.append(bed + max(depth, 0.05))
            else:
                flood.append(NODATA)
    terrain_path.write_bytes(struct.pack(f"<{len(terrain)}f", *terrain))
    flood_path.write_bytes(struct.pack(f"<{len(flood)}f", *flood))
    print(f"  terrain min/max: {min(terrain):.1f}/{max(terrain):.1f} m, {len(terrain) * 4} bytes")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    gen_dem_hillshade(OUT_DIR / "dem_hillshade_teesta.png")
    gen_domain_mask(OUT_DIR / "domain_mask_teesta.png")
    gen_nearfield_scene(
        OUT_DIR / "sph_nearfield_terrain.bin",
        OUT_DIR / "sph_nearfield_flood.bin",
        width=80, height=60,
    )
    gen_depth_raster(OUT_DIR / "sph_nearfield_depth_p50.png", "illustrative SPH depth (near-field)")
    print(f"Wrote preview rasters to {OUT_DIR}")


if __name__ == "__main__":
    main()
