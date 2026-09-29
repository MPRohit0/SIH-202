#!/usr/bin/env python3
"""Generates the small, deterministic raster/binary assets used by
frontend/src/data/preview/*.json fixtures (design/target-state-preview).

These are NOT model output -- they are synthetic arrays and images, each
labelled "illustrative"/"PREVIEW", used only so the target-state screens have
something to render. Run this script again (deterministic, no random seed)
whenever a preview asset changes; commit what it writes under
frontend/public/preview/ since Vite serves that directory as-is and the
frontend has no Python runtime to generate assets at request time.

Screens 4 and 5 (near-field 3D / SPH result, and SPH vs D-Flow FM model
comparison) share ONE illustrative near-field section (NF-1) and ONE
illustrative scenario: gen_nearfield_pair() builds the FM and SPH depth/
velocity grids together, from the same bed and the same channel centreline,
so screen 5 is comparing two runs of the same thing, not two unrelated
fixtures. print_nearfield_comparison_metrics() then computes every agreement
statistic (IoU, F1 at 0.3 m, depth RMSE, velocity MAE, arrival) FROM those
two grids -- nothing in compare.teesta.json or the flood_query_response
fixtures is a hand-typed metric; each one is transcribed from this script's
printed output. Re-run this script and re-copy its printed numbers if the
grids below ever change.

Usage: conda run -n sih26 python frontend/scripts/gen_preview_assets.py
"""
from __future__ import annotations

import json
import math
import struct
from pathlib import Path

from PIL import Image, ImageDraw

OUT_DIR = Path(__file__).resolve().parents[1] / "public" / "preview"
DATA_OUT_DIR = Path(__file__).resolve().parents[1] / "src" / "data" / "preview" / "generated"
SIZE = 256
NODATA = -9999.0

# Shared near-field section NF-1 geometry (screens 4 and 5).
NF1_WIDTH, NF1_HEIGHT = 80, 60
NF1_CELL_M = 15.0
NF1_MIN_ELEV, NF1_MAX_ELEV = 1750.0, 1926.0
NF1_WET_THRESHOLD_M = 0.3  # docs/impact_outputs.md depth_classes_m[0]
NF1_SECTION_LENGTH_M = NF1_HEIGHT * NF1_CELL_M


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


def gen_depth_raster(path: Path, label: str, width: int, height: int, depth: list[float]) -> None:
    """A depth_p50-style 2D raster rendered from an actual generated depth grid
    (nearest-neighbour upscaled to SIZE x SIZE), not an independent drawing --
    so the 2D map fallback shows the same wet cells as the 3D scene / metrics."""
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    px = img.load()
    for y in range(SIZE):
        row = min(height - 1, y * height // SIZE)
        for x in range(SIZE):
            col = min(width - 1, x * width // SIZE)
            d = depth[row * width + col]
            if d >= NF1_WET_THRESHOLD_M:
                t = min(1.0, d / 4.0)
                px[x, y] = (int(60 + t * 40), int(120 + t * 60), int(200 + t * 40), int(140 + t * 100))
    draw = ImageDraw.Draw(img, "RGBA")
    _stamp(draw, label, (SIZE, SIZE))
    img.save(path)


def gen_depth_diff_raster(path: Path, width: int, height: int, diff: list[float]) -> None:
    """Diverging depth_diff raster (SPH minus FM), using the real project style
    (contracts/styles.json "depth_diff": range +-2.0 m, #2166ac/white/#b2182b)."""
    lo_color, mid_color, hi_color = (0x21, 0x66, 0xAC), (0xFF, 0xFF, 0xFF), (0xB2, 0x18, 0x2B)
    range_m = 2.0
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    px = img.load()
    for y in range(SIZE):
        row = min(height - 1, y * height // SIZE)
        for x in range(SIZE):
            col = min(width - 1, x * width // SIZE)
            d = diff[row * width + col]
            if d is None:
                continue
            t = max(-1.0, min(1.0, d / range_m))
            if t < 0:
                a = -t
                c = tuple(int(lo_color[i] * a + mid_color[i] * (1 - a)) for i in range(3))
            else:
                a = t
                c = tuple(int(hi_color[i] * a + mid_color[i] * (1 - a)) for i in range(3))
            px[x, y] = (*c, 210)
    draw = ImageDraw.Draw(img, "RGBA")
    _stamp(draw, "illustrative depth diff (SPH - FM)", (SIZE, SIZE))
    img.save(path)


def _nf1_bed() -> list[float]:
    """The shared bed for near-field section NF-1: a valley dropping from the
    upstream (row 0) to downstream (row height-1) edge, used by both engines'
    grids below so they represent the same terrain, not two different ones."""
    bed = []
    for row in range(NF1_HEIGHT):
        along = row / max(NF1_HEIGHT - 1, 1)
        for col in range(NF1_WIDTH):
            across = col / max(NF1_WIDTH - 1, 1)
            bed.append(NF1_MAX_ELEV - along * (NF1_MAX_ELEV - NF1_MIN_ELEV) + math.sin(across * math.pi) * 6.0)
    return bed


def _nf1_engine_grids(bed: list[float], *, half_width: float, peak_depth: float, decay: float,
                       front_delay: float, velocity_k: float) -> tuple[list[float], list[float]]:
    """One engine's depth (m) and velocity (m/s) grids for NF-1, over the shared
    channel centreline `0.5 + 0.18*sin(along*2.2*pi)`. Both engines see the same
    centreline (it is the same channel); only how each numerical method resolves
    it -- channel half-width, depth decay downstream, a startup delay before the
    front reaches a row, and a velocity/depth relationship -- differs, which is
    what a real SPH-vs-FM comparison would show (SPH: narrower, deeper, faster
    front and higher local velocity in a fixed-area near-field inlet; FM: wider,
    more numerically diffusive). All parameters are illustrative constants, not
    measured from any real run.
    """
    depth = []
    velocity = []
    for row in range(NF1_HEIGHT):
        along = row / max(NF1_HEIGHT - 1, 1)
        for col in range(NF1_WIDTH):
            across = col / max(NF1_WIDTH - 1, 1)
            channel_center = 0.5 + 0.18 * math.sin(along * math.pi * 2.2)
            dist = abs(across - channel_center)
            if along < front_delay or dist >= half_width:
                depth.append(0.0)
                velocity.append(0.0)
                continue
            d = (half_width - dist) / half_width * max(peak_depth - along * decay, 0.0)
            depth.append(max(d, 0.0))
            velocity.append(velocity_k * math.sqrt(max(d, 0.0)))
    return depth, velocity


def gen_nearfield_pair() -> dict:
    """Builds the shared NF-1 bed plus the FM and SPH depth/velocity grids,
    writes every binary/PNG asset both screens need, computes every screen-5
    agreement statistic from those grids, and returns them as a dict that is
    also written to frontend/src/data/preview/generated/nf1_comparison.json so
    the fixtures can cite it. Nothing here is a hand-typed metric."""
    bed = _nf1_bed()
    depth_fm, vel_fm = _nf1_engine_grids(
        bed, half_width=0.19, peak_depth=3.0, decay=1.1, front_delay=0.0, velocity_k=1.7,
    )
    depth_sph, vel_sph = _nf1_engine_grids(
        bed, half_width=0.14, peak_depth=3.6, decay=1.5, front_delay=0.05, velocity_k=2.0,
    )

    n = NF1_WIDTH * NF1_HEIGHT
    wet_fm = [d >= NF1_WET_THRESHOLD_M for d in depth_fm]
    wet_sph = [d >= NF1_WET_THRESHOLD_M for d in depth_sph]
    tp = sum(1 for i in range(n) if wet_fm[i] and wet_sph[i])
    fp = sum(1 for i in range(n) if wet_sph[i] and not wet_fm[i])
    fn = sum(1 for i in range(n) if wet_fm[i] and not wet_sph[i])
    union = tp + fp + fn
    iou = tp / union if union else 0.0
    f1 = (2 * tp) / (2 * tp + fp + fn) if (2 * tp + fp + fn) else 0.0

    both_wet_idx = [i for i in range(n) if wet_fm[i] and wet_sph[i]]
    depth_rmse = math.sqrt(sum((depth_fm[i] - depth_sph[i]) ** 2 for i in both_wet_idx) / len(both_wet_idx)) if both_wet_idx else None
    velocity_mae = sum(abs(vel_fm[i] - vel_sph[i]) for i in both_wet_idx) / len(both_wet_idx) if both_wet_idx else None

    mean_v_fm = sum(v for v, w in zip(vel_fm, wet_fm) if w) / max(sum(wet_fm), 1)
    mean_v_sph = sum(v for v, w in zip(vel_sph, wet_sph) if w) / max(sum(wet_sph), 1)
    # Illustrative arrival proxy: section length / mean wet-cell velocity. A
    # static max-depth grid has no time axis, so this is a distance/velocity
    # estimate derived from the generated grids, not an unsteady simulation --
    # documented as such in every fixture that cites it.
    arrival_fm_s = NF1_SECTION_LENGTH_M / mean_v_fm
    arrival_sph_s = NF1_SECTION_LENGTH_M / mean_v_sph

    max_depth_fm, max_depth_sph = max(depth_fm), max(depth_sph)
    max_vel_fm, max_vel_sph = max(vel_fm), max(vel_sph)
    area_fm = sum(wet_fm) * NF1_CELL_M * NF1_CELL_M
    area_sph = sum(wet_sph) * NF1_CELL_M * NF1_CELL_M

    diff = [
        (depth_sph[i] - depth_fm[i]) if (wet_fm[i] or wet_sph[i]) else None
        for i in range(n)
    ]

    flood_fm = [bed[i] + depth_fm[i] if wet_fm[i] else NODATA for i in range(n)]
    flood_sph = [bed[i] + depth_sph[i] if wet_sph[i] else NODATA for i in range(n)]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    Path(OUT_DIR / "nf1_terrain.bin").write_bytes(struct.pack(f"<{n}f", *bed))
    Path(OUT_DIR / "nf1_fm_flood.bin").write_bytes(struct.pack(f"<{n}f", *flood_fm))
    Path(OUT_DIR / "nf1_sph_flood.bin").write_bytes(struct.pack(f"<{n}f", *flood_sph))
    gen_depth_raster(OUT_DIR / "nf1_fm_depth_p50.png", "illustrative FM depth (NF-1)", NF1_WIDTH, NF1_HEIGHT, depth_fm)
    gen_depth_raster(OUT_DIR / "nf1_sph_depth_p50.png", "illustrative SPH depth (NF-1)", NF1_WIDTH, NF1_HEIGHT, depth_sph)
    gen_depth_diff_raster(OUT_DIR / "nf1_depth_diff.png", NF1_WIDTH, NF1_HEIGHT, diff)

    metrics = {
        "_comment": "Computed by frontend/scripts/gen_preview_assets.py:gen_nearfield_pair() "
                    "from the FM/SPH depth and velocity grids for near-field section NF-1. "
                    "Every number here is transcribed verbatim into flood_query_response.teesta.sph_direct.json "
                    "and compare.teesta.json -- do not hand-edit this file; re-run the script instead. "
                    "arrival_s is a travel-time PROXY (section_length_m / mean wet-cell velocity), not the "
                    "contract arrival definition (first time depth > 0.1 m, m5_specs.md SS4) -- a static "
                    "max-depth grid has no time axis to measure that from. arrival_diff_s is SPH minus FM: "
                    "negative means SPH arrives sooner.",
        "section": "NF-1", "wet_threshold_m": NF1_WET_THRESHOLD_M, "section_length_m": NF1_SECTION_LENGTH_M,
        "fm": {"max_depth_m": round(max_depth_fm, 3), "max_velocity_ms": round(max_vel_fm, 3),
               "inundated_area_m2": area_fm, "arrival_s": round(arrival_fm_s, 1)},
        "sph": {"max_depth_m": round(max_depth_sph, 3), "max_velocity_ms": round(max_vel_sph, 3),
                "inundated_area_m2": area_sph, "arrival_s": round(arrival_sph_s, 1)},
        "comparison": {
            "iou": round(iou, 3), "f1_0_3": round(f1, 3),
            "depth_rmse_wet_m": round(depth_rmse, 3) if depth_rmse is not None else None,
            "velocity_mae_ms": round(velocity_mae, 3) if velocity_mae is not None else None,
            "arrival_diff_s": round(arrival_sph_s - arrival_fm_s, 1),
            "arrival_diff_sign_convention": "sph_minus_fm",
        },
    }
    DATA_OUT_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_OUT_DIR / "nf1_comparison.json").write_text(json.dumps(metrics, indent=2) + "\n")
    print(json.dumps(metrics, indent=2))
    return metrics


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    gen_dem_hillshade(OUT_DIR / "dem_hillshade_teesta.png")
    gen_domain_mask(OUT_DIR / "domain_mask_teesta.png")
    gen_nearfield_pair()
    print(f"Wrote preview rasters to {OUT_DIR}")


if __name__ == "__main__":
    main()
