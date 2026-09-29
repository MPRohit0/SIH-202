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
import statistics
import struct
from pathlib import Path

import yaml
from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parents[1] / "public" / "preview"
DATA_OUT_DIR = Path(__file__).resolve().parents[1] / "src" / "data" / "preview" / "generated"
SITE_DETAIL_TEESTA = Path(__file__).resolve().parents[1] / "src" / "data" / "preview" / "site_detail.teesta.json"
IMPACT_OUTPUTS_DOC = REPO_ROOT / "docs" / "impact_outputs.md"
SIZE = 256
NODATA = -9999.0

# Shared near-field section NF-1 geometry (screens 4 and 5).
NF1_WIDTH, NF1_HEIGHT = 80, 60
NF1_CELL_M = 15.0
NF1_MIN_ELEV, NF1_MAX_ELEV = 1750.0, 1926.0
NF1_WET_THRESHOLD_M = 0.3  # docs/impact_outputs.md depth_classes_m[0]
NF1_SECTION_LENGTH_M = NF1_HEIGHT * NF1_CELL_M

# Screen 6 (scenario vs unknown-breach, confidence) far-field-like profile.
FAR_WIDTH, FAR_HEIGHT = 50, 80
FAR_TOTAL_LENGTH_M = 32000.0  # covers the furthest real teesta POI (mangan_district_hospital, 31000 m)
FAR_BOUNDS_LATLNG = [[27.5, 88.0], [28.2, 89.0]]  # same bbox as the teesta site fixture
N_TRAIN = 30
N_ENSEMBLE = 200
INPUT_ORDER = ["water_volume_m3", "breach_width_m", "failure_time_s"]


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


def _load_impact_thresholds() -> dict:
    """Reads zone_high_p/zone_possible_p etc. by parsing the fenced ```yaml```
    block in docs/impact_outputs.md (lines ~9-18), NOT from config/impact.yaml
    -- that file only holds M6 loss-estimation defaults (FX rate, price index,
    road width); it does not define these zone thresholds. The doc's own text
    says this block "should live in config... not in code" but it hasn't been
    migrated yet, so this is the one real, authoritative place these numbers
    exist in the repo. Parsed with PyYAML, not retyped."""
    text = IMPACT_OUTPUTS_DOC.read_text()
    start = text.index("```yaml") + len("```yaml")
    end = text.index("```", start)
    return yaml.safe_load(text[start:end])


def _teesta_emulator_input_ranges() -> dict[str, tuple[float, float]]:
    """Reads water_volume_m3/breach_width_m/failure_time_s low/high directly
    from site_detail.teesta.json's emulator_inputs, so the illustrative
    training design and ensemble below use the exact same bounds already
    shown on the site's inputs panel (screen 1), not independently invented
    ones."""
    site = json.loads(SITE_DETAIL_TEESTA.read_text())
    return {i["name"]: (float(i["low"]), float(i["high"])) for i in site["emulator_inputs"]}


def _teesta_pois() -> list[dict]:
    """Reads POI id/name/chainage_m directly from site_detail.teesta.json's
    real POI list, so the far-field profile's row mapping uses the same
    chainages already shown elsewhere, not invented distances."""
    site = json.loads(SITE_DETAIL_TEESTA.read_text())
    return [
        {"poi_id": f["properties"]["poi_id"], "name": f["properties"]["name"], "chainage_m": f["properties"]["chainage_m"]}
        for f in site["pois"]["features"]
    ]


def _weyl_points(n: int, dims: int, offset: int) -> list[list[float]]:
    """A deterministic low-discrepancy sequence (fractional parts of i*sqrt(prime)),
    used in place of a random LHS so this script has no random seed to manage and
    is exactly reproducible. Each dimension is in [0, 1]."""
    bases = [2.0, 3.0, 5.0, 7.0, 11.0][:dims]
    return [[((i + 1) * math.sqrt(b)) % 1.0 for b in bases] for i in range(offset, offset + n)]


def _to_real(unit_point: list[float], ranges: list[tuple[float, float]]) -> list[float]:
    return [lo + u * (hi - lo) for u, (lo, hi) in zip(unit_point, ranges)]


def _profile_depth_velocity(vw: float, bave: float, tf: float, chainage_m: float) -> tuple[float, float]:
    """The illustrative 'true' far-field profile a query point maps to: peak
    depth near the breach, decaying with chainage, scaled by water volume
    (cube root, larger lake -> deeper), breach width (wider -> deeper/faster
    flood) and failure time (faster failure -> higher peak). Purely
    illustrative constants -- not fitted to any real run."""
    along = min(chainage_m / FAR_TOTAL_LENGTH_M, 1.0)
    peak_depth = 2.2 * (vw / 1.0e7) ** (1 / 3) * (bave / 120.0) ** 0.5 * (3600.0 / tf) ** 0.25
    depth = max(peak_depth * (1 - along * 0.85), 0.0)
    velocity = 1.6 * math.sqrt(depth)
    return depth, velocity


def _channel_half_width_frac(bave: float, ranges: dict[str, tuple[float, float]]) -> float:
    lo, hi = ranges["breach_width_m"]
    t = (bave - lo) / (hi - lo) if hi > lo else 0.5
    return 0.12 + 0.10 * t


def _nearest_neighbour_distance(point: list[float], others: list[list[float]]) -> float:
    return min(math.dist(point, o) for o in others)


VALLEY_WIDTH_M = 300.0  # illustrative full valley width at the widest channel setting


def _single_run_depth_grid(vw: float, bave: float, tf: float, ranges: dict[str, tuple[float, float]]) -> list[float]:
    """One deterministic (non-ensemble) depth grid for a single scenario-mode
    Azmi member -- same profile/channel model as the ensemble, at one
    parameter point, used for the scenario-mode rasters/area/POI depths since
    m5_specs.md SS5.1 scenario mode is a single run per member, not Monte Carlo."""
    half_width = _channel_half_width_frac(bave, ranges)
    grid = []
    for row in range(FAR_HEIGHT):
        chainage_m = row / (FAR_HEIGHT - 1) * FAR_TOTAL_LENGTH_M
        depth_c, _ = _profile_depth_velocity(vw, bave, tf, chainage_m)
        for col in range(FAR_WIDTH):
            across = col / (FAR_WIDTH - 1)
            dist = abs(across - 0.5)
            grid.append(max(depth_c * (half_width - dist) / half_width, 0.0) if dist < half_width else 0.0)
    return grid


def _grid_area_m2(grid: list[float]) -> float:
    cell_area = (VALLEY_WIDTH_M / FAR_WIDTH) * (FAR_TOTAL_LENGTH_M / FAR_HEIGHT)
    return sum(1 for d in grid if d >= NF1_WET_THRESHOLD_M) * cell_area


def _peak_discharge_m3s(vw: float, bave: float, tf: float, ranges: dict[str, tuple[float, float]]) -> float:
    """A continuity estimate (Q = velocity x depth x width) at the breach
    (chainage 0), not a hand-typed number."""
    depth0, vel0 = _profile_depth_velocity(vw, bave, tf, 0.0)
    width0 = 2 * _channel_half_width_frac(bave, ranges) * VALLEY_WIDTH_M
    return vel0 * depth0 * width0


def gen_confidence_ensemble() -> dict:
    """Screen 6 (scenario vs unknown-breach mode, confidence). Builds:
    - an illustrative 30-point training design and 200-point Monte Carlo
      ensemble over Teesta's own emulator_inputs ranges (see
      _teesta_emulator_input_ranges), both from a deterministic low-discrepancy
      sequence, never hand-typed;
    - per-cell P(depth > 0.3 m), median and P5/P95 depth over a far-field-like
      profile whose POI row mapping uses the site's real POI chainages;
    - m5_specs.md SS6 confidence (S: LOOCV skill, C: query coverage, U: ensemble
      spread, weakest link wins), including the unknown-breach mode's
      in-training-box SAMPLE FRACTION rule (SS5.2) and the placeholder-inputs
      Medium cap;
    - one specific cell where a HIGH probability zone is downgraded to
      POSSIBLE for low local confidence, chosen as the HIGH cell whose wet/dry
      status is most sensitive to breach width (computed, not picked by hand).
    Every number below is computed; nothing is hand-typed into the fixtures
    that cite this function's JSON output.
    """
    thresholds = _load_impact_thresholds()
    zone_high_p = thresholds["zone_high_p"]
    zone_possible_p = thresholds["zone_possible_p"]
    ranges = _teesta_emulator_input_ranges()
    ranges_list = [ranges[k] for k in INPUT_ORDER]
    pois = _teesta_pois()

    # -- Training design (what the illustrative emulator was "trained" on) --
    training_unit = _weyl_points(N_TRAIN, 3, offset=1)
    training_real = [_to_real(p, ranges_list) for p in training_unit]
    nn_dists = [_nearest_neighbour_distance(p, training_unit[:i] + training_unit[i + 1:]) for i, p in enumerate(training_unit)]
    median_nn_dist = statistics.median(nn_dists)

    def coverage_grade(query_unit: list[float]) -> str:
        if any(u < 0.0 or u > 1.0 for u in query_unit):
            return "OUTSIDE"
        r = _nearest_neighbour_distance(query_unit, training_unit) / median_nn_dist
        if r <= 1.0:
            return "INSIDE"
        if r <= 2.0:
            return "EDGE"
        return "OUTSIDE"

    def to_unit(real_point: list[float]) -> list[float]:
        return [(v - lo) / (hi - lo) for v, (lo, hi) in zip(real_point, ranges_list)]

    # -- S: LOOCV skill at the farthest wet POI (mangan_district_hospital), 1-NN leave-one-out --
    ref_poi = max(pois, key=lambda p: p["chainage_m"])
    true_depths, pred_depths, true_arrivals, pred_arrivals = [], [], [], []
    for i, real_pt in enumerate(training_real):
        others_unit = training_unit[:i] + training_unit[i + 1:]
        others_real = training_real[:i] + training_real[i + 1:]
        nearest_idx = min(range(len(others_unit)), key=lambda j: math.dist(training_unit[i], others_unit[j]))
        true_d, true_v = _profile_depth_velocity(*real_pt, ref_poi["chainage_m"])
        pred_d, pred_v = _profile_depth_velocity(*others_real[nearest_idx], ref_poi["chainage_m"])
        true_depths.append(true_d)
        pred_depths.append(pred_d)
        true_arrivals.append(ref_poi["chainage_m"] / true_v if true_v > 0 else None)
        pred_arrivals.append(ref_poi["chainage_m"] / pred_v if pred_v > 0 else None)
    tp = sum(1 for t, p in zip(true_depths, pred_depths) if t >= NF1_WET_THRESHOLD_M and p >= NF1_WET_THRESHOLD_M)
    fp = sum(1 for t, p in zip(true_depths, pred_depths) if t < NF1_WET_THRESHOLD_M <= p)
    fn = sum(1 for t, p in zip(true_depths, pred_depths) if p < NF1_WET_THRESHOLD_M <= t)
    f1_skill = (2 * tp) / (2 * tp + fp + fn) if (2 * tp + fp + fn) else 1.0
    arrival_pairs = [(t, p) for t, p in zip(true_arrivals, pred_arrivals) if t is not None and p is not None]
    mean_true_arrival = sum(t for t, _ in arrival_pairs) / len(arrival_pairs)
    arrival_rmse = math.sqrt(sum((t - p) ** 2 for t, p in arrival_pairs) / len(arrival_pairs))
    arrival_rmse_pct = 100.0 * arrival_rmse / mean_true_arrival if mean_true_arrival else 100.0
    if f1_skill >= 0.85 and arrival_rmse_pct <= 10.0:
        s_grade, s_level = "GOOD", "High"
    elif f1_skill >= 0.70 and arrival_rmse_pct <= 20.0:
        s_grade, s_level = "FAIR", "Medium"
    else:
        s_grade, s_level = "POOR", "Low"

    # -- Far-field grid: per-cell P(depth>0.3m), median, P5/P95 across the 200-sample ensemble --
    ensemble_unit = _weyl_points(N_ENSEMBLE, 3, offset=5000)
    ensemble_real_inbox = [_to_real(p, ranges_list) for p in ensemble_unit]
    # Unknown-breach mode samples WIDENED ranges (m5_specs.md SS5.2: "+-20%" on
    # V_w, B_ave and T_f widened by 20%) -- implemented as +-10% of each range's
    # span per side (20% growth of span), which is why some ensemble members
    # legitimately fall outside the TRAINED box below.
    widened_ranges = [(lo - 0.1 * (hi - lo), hi + 0.1 * (hi - lo)) for lo, hi in ranges_list]
    ensemble_real = [_to_real(p, widened_ranges) for p in ensemble_unit]
    in_box_count = sum(
        1 for real_pt in ensemble_real
        if all(lo <= v <= hi for v, (lo, hi) in zip(real_pt, ranges_list))
    )
    in_box_fraction = in_box_count / N_ENSEMBLE

    n = FAR_WIDTH * FAR_HEIGHT
    depth_samples: list[list[float]] = [[] for _ in range(n)]
    # Track wet/dry split by breach-width tercile per cell, to find the cell whose
    # flooding status is most sensitive to breach width (the downgrade candidate).
    bave_median = statistics.median(pt[1] for pt in ensemble_real_inbox)
    wet_narrow = [0] * n
    wet_wide = [0] * n
    narrow_count = wide_count = 0
    for sample_idx, (vw, bave, tf) in enumerate(ensemble_real_inbox):
        half_width = _channel_half_width_frac(bave, ranges)
        is_narrow = bave < bave_median
        if is_narrow:
            narrow_count += 1
        else:
            wide_count += 1
        for row in range(FAR_HEIGHT):
            chainage_m = row / (FAR_HEIGHT - 1) * FAR_TOTAL_LENGTH_M
            depth_c, _ = _profile_depth_velocity(vw, bave, tf, chainage_m)
            for col in range(FAR_WIDTH):
                across = col / (FAR_WIDTH - 1)
                dist = abs(across - 0.5)
                cell = row * FAR_WIDTH + col
                if dist >= half_width:
                    depth_samples[cell].append(0.0)
                    continue
                d = depth_c * (half_width - dist) / half_width
                depth_samples[cell].append(d)
                if d >= NF1_WET_THRESHOLD_M:
                    if is_narrow:
                        wet_narrow[cell] += 1
                    else:
                        wet_wide[cell] += 1

    p_wet = [sum(1 for d in cell if d >= NF1_WET_THRESHOLD_M) / N_ENSEMBLE for cell in depth_samples]
    median_depth = [statistics.median(cell) for cell in depth_samples]
    p5_depth = [sorted(cell)[max(0, round(0.05 * (N_ENSEMBLE - 1)))] for cell in depth_samples]
    p95_depth = [sorted(cell)[min(N_ENSEMBLE - 1, round(0.95 * (N_ENSEMBLE - 1)))] for cell in depth_samples]

    zone = []
    for p in p_wet:
        if p >= zone_high_p:
            zone.append("HIGH")
        elif p >= zone_possible_p:
            zone.append("POSSIBLE")
        else:
            zone.append("DRY")

    # Downgrade candidate: among HIGH cells, the one most sensitive to breach width
    # (wet fraction among wide-breach samples minus wet fraction among narrow-breach
    # samples is largest) -- i.e. whether it floods depends heavily on which ensemble
    # member you draw, so its local confidence is treated as LOW even though its
    # overall P(depth>0.3m) clears the HIGH threshold.
    downgrade_idx, downgrade_gap = None, -1.0
    for i in range(n):
        if zone[i] != "HIGH" or narrow_count == 0 or wide_count == 0:
            continue
        gap = (wet_wide[i] / wide_count) - (wet_narrow[i] / narrow_count)
        if gap > downgrade_gap:
            downgrade_gap, downgrade_idx = gap, i
    downgraded_zone = list(zone)
    downgrade_info = None
    if downgrade_idx is not None:
        downgraded_zone[downgrade_idx] = "POSSIBLE"
        downgrade_info = {
            "row": downgrade_idx // FAR_WIDTH, "col": downgrade_idx % FAR_WIDTH,
            "chainage_m": round((downgrade_idx // FAR_WIDTH) / (FAR_HEIGHT - 1) * FAR_TOTAL_LENGTH_M, 0),
            "p_wet": round(p_wet[downgrade_idx], 3),
            "breach_width_sensitivity_gap": round(downgrade_gap, 3),
            "raw_zone": "HIGH", "shown_zone": "POSSIBLE",
        }

    # -- Per-POI P(floods) at each real POI's chainage-mapped row (channel centre) --
    poi_results = []
    for poi in pois:
        row = min(FAR_HEIGHT - 1, round(poi["chainage_m"] / FAR_TOTAL_LENGTH_M * (FAR_HEIGHT - 1)))
        col = FAR_WIDTH // 2
        cell = row * FAR_WIDTH + col
        poi_results.append({
            "poi_id": poi["poi_id"], "name": poi["name"], "chainage_m": poi["chainage_m"],
            "p_floods": round(p_wet[cell], 3), "median_depth_m": round(median_depth[cell], 3),
            "p5_depth_m": round(p5_depth[cell], 3), "p95_depth_m": round(p95_depth[cell], 3),
            "zone": downgraded_zone[cell],
        })

    # -- Breach-cell (row 0) percentiles, for the unknown-breach summary's peak
    # depth/velocity/discharge Estimates --
    breach_cell = 0 * FAR_WIDTH + FAR_WIDTH // 2
    breach_median, breach_p5, breach_p95 = median_depth[breach_cell], p5_depth[breach_cell], p95_depth[breach_cell]
    bave_median_inbox = statistics.median(pt[1] for pt in ensemble_real_inbox)
    breach_channel_width_m = 2 * _channel_half_width_frac(bave_median_inbox, ranges) * VALLEY_WIDTH_M

    def _velocity_of(depth_m: float) -> float:
        return 1.6 * math.sqrt(max(depth_m, 0.0))

    def _discharge_of(depth_m: float) -> float:
        return _velocity_of(depth_m) * depth_m * breach_channel_width_m

    # -- HIGH / HIGH+POSSIBLE extent areas (impact_outputs.md's population-style
    # zone_range convention: low = HIGH-zone area, high = HIGH+POSSIBLE-zone area) --
    cell_area_m2 = (VALLEY_WIDTH_M / FAR_WIDTH) * (FAR_TOTAL_LENGTH_M / FAR_HEIGHT)
    area_high_m2 = sum(1 for p in p_wet if p >= zone_high_p) * cell_area_m2
    area_high_possible_m2 = sum(1 for p in p_wet if p >= zone_possible_p) * cell_area_m2

    # -- U (spread) at the reference POI, from the unknown-breach ensemble --
    ref_row = min(FAR_HEIGHT - 1, round(ref_poi["chainage_m"] / FAR_TOTAL_LENGTH_M * (FAR_HEIGHT - 1)))
    ref_cell = ref_row * FAR_WIDTH + FAR_WIDTH // 2
    ref_median, ref_p5, ref_p95 = median_depth[ref_cell], p5_depth[ref_cell], p95_depth[ref_cell]
    ref_width = ref_p95 - ref_p5
    ref_width_pct = 100.0 * ref_width / ref_median if ref_median else 0.0
    if ref_width <= 0.5 or ref_width_pct <= 50.0:
        u_grade, u_level = "NARROW", "High"
    elif ref_width <= 1.0 or ref_width_pct <= 100.0:
        u_grade, u_level = "MEDIUM", "Medium"
    else:
        u_grade, u_level = "WIDE", "Low"

    # -- C for unknown-breach mode: in-training-box SAMPLE FRACTION (m5_specs.md SS5.2) --
    if in_box_fraction >= 0.95:
        c_grade_unknown, c_level_unknown = "INSIDE", "High"
    elif in_box_fraction >= 0.80:
        c_grade_unknown, c_level_unknown = "EDGE", "Medium"
    else:
        c_grade_unknown, c_level_unknown = "OUTSIDE", "Low"

    def weakest_link(*levels: str) -> str:
        """m5_specs.md SS6: 'weakest link' -- the lowest of S/C/U wins."""
        if "Low" in levels:
            return "Low"
        if "Medium" in levels:
            return "Medium"
        return "High"

    def build_confidence(c_level: str, c_grade: str, c_reason: str) -> dict:
        overall = weakest_link(s_level, c_level, u_level)
        weakest = min([("S", s_level), ("C", c_level), ("U", u_level)], key=lambda kv: {"Low": 0, "Medium": 1, "High": 2}[kv[1]])
        reason = None
        if overall == "Low":
            reason = {"letter": weakest[0], "text": c_reason if weakest[0] == "C" else f"{weakest[0]}: see components"}
        return {
            "level": overall.upper() if overall != "Medium" else "MODERATE",
            "components": {"validation_skill": s_grade, "query_coverage": c_grade, "spread": u_grade},
            "computed_weakest": weakest[0], "reason_detail": reason,
        }

    # -- Azmi pair scenario members: V_w fixed (a single sourced-style value), --
    # -- breach_width_m/failure_time_s at illustrative "low"/"high" method points --
    vw_fixed = ranges["water_volume_m3"][0] + 0.5 * (ranges["water_volume_m3"][1] - ranges["water_volume_m3"][0])
    azmi_low_real = [vw_fixed, 75.0, 1200.0]
    azmi_high_real = [vw_fixed, 165.0, 9000.0]
    azmi_low_c = coverage_grade(to_unit(azmi_low_real))
    azmi_high_c = coverage_grade(to_unit(azmi_high_real))
    c_level_map = {"INSIDE": "High", "EDGE": "Medium", "OUTSIDE": "Low"}

    azmi_low_conf = build_confidence(c_level_map[azmi_low_c], azmi_low_c, "azmi low member")
    azmi_high_conf = build_confidence(c_level_map[azmi_high_c], azmi_high_c, "azmi high member")
    unknown_breach_conf = build_confidence(
        c_level_unknown, c_grade_unknown,
        f"Low (C: only {in_box_fraction * 100:.0f}% of Monte Carlo samples fall inside the trained "
        f"V_w/B_ave/T_f design box)",
    )

    # -- Scenario mode: two single-run grids (no Monte Carlo). docs/impact_outputs.md
    # SS"Scenario mode" rule: HIGH = wet under the member with the SMALLER footprint
    # (the more conservative/"lower" estimate), HIGH+POSSIBLE = wet under the member
    # with the LARGER footprint ("upper" estimate). Which member is "lower" is decided
    # by comparing their computed inundated areas below, not assumed from input size.
    azmi_low_grid = _single_run_depth_grid(*azmi_low_real, ranges)
    azmi_high_grid = _single_run_depth_grid(*azmi_high_real, ranges)
    azmi_low_area = _grid_area_m2(azmi_low_grid)
    azmi_high_area = _grid_area_m2(azmi_high_grid)
    if azmi_low_area <= azmi_high_area:
        lower_grid, upper_grid, lower_name, upper_name = azmi_low_grid, azmi_high_grid, "azmi_low", "azmi_high"
    else:
        lower_grid, upper_grid, lower_name, upper_name = azmi_high_grid, azmi_low_grid, "azmi_high", "azmi_low"
    scenario_zone = []
    for lo_d, hi_d in zip(lower_grid, upper_grid):
        if lo_d >= NF1_WET_THRESHOLD_M:
            scenario_zone.append("HIGH")
        elif hi_d >= NF1_WET_THRESHOLD_M:
            scenario_zone.append("POSSIBLE")
        else:
            scenario_zone.append("DRY")

    def profile_summary(real_pt: list[float], grid: list[float]) -> dict:
        depth, vel = _profile_depth_velocity(*real_pt, ref_poi["chainage_m"])
        return {
            "max_depth_m": round(depth, 3), "max_velocity_ms": round(vel, 3),
            "arrival_s": round(ref_poi["chainage_m"] / vel, 1) if vel > 0 else None,
            "inundated_area_m2": round(_grid_area_m2(grid), 0),
            "peak_discharge_m3s": round(_peak_discharge_m3s(*real_pt, ranges), 1),
        }

    def scenario_poi_results(grid: list[float]) -> list[dict]:
        out = []
        for poi in pois:
            row = min(FAR_HEIGHT - 1, round(poi["chainage_m"] / FAR_TOTAL_LENGTH_M * (FAR_HEIGHT - 1)))
            cell = row * FAR_WIDTH + FAR_WIDTH // 2
            out.append({"poi_id": poi["poi_id"], "name": poi["name"], "chainage_m": poi["chainage_m"],
                        "depth_m": round(grid[cell], 3), "zone": scenario_zone[cell]})
        return out

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    gen_depth_raster(OUT_DIR / "far_depth_p50.png", "illustrative median depth (far-field)", FAR_WIDTH, FAR_HEIGHT, median_depth)
    _gen_probability_raster(OUT_DIR / "far_p_inundation.png", FAR_WIDTH, FAR_HEIGHT, p_wet)
    _gen_zone_raster(OUT_DIR / "far_zone.png", FAR_WIDTH, FAR_HEIGHT, downgraded_zone, downgrade_idx)
    gen_depth_raster(OUT_DIR / "far_depth_azmi_low.png", "illustrative Azmi-low depth (far-field)", FAR_WIDTH, FAR_HEIGHT, azmi_low_grid)
    gen_depth_raster(OUT_DIR / "far_depth_azmi_high.png", "illustrative Azmi-high depth (far-field)", FAR_WIDTH, FAR_HEIGHT, azmi_high_grid)
    _gen_zone_raster(OUT_DIR / "far_zone_scenario.png", FAR_WIDTH, FAR_HEIGHT, scenario_zone, None)

    result = {
        "_comment": "Computed by frontend/scripts/gen_preview_assets.py:gen_confidence_ensemble(). "
                    "Training design ranges are read from site_detail.teesta.json's emulator_inputs; "
                    "zone_high_p/zone_possible_p are parsed from docs/impact_outputs.md's config block "
                    "(config/impact.yaml does not define them -- see that function's docstring). "
                    "Nothing here is hand-typed; re-run the script and re-copy this file's numbers if "
                    "the ensemble/training design ever changes.",
        "training_design": {"n_train": N_TRAIN, "median_nn_distance_unit": round(median_nn_dist, 4),
                             "ranges": {k: list(ranges[k]) for k in INPUT_ORDER}},
        "ensemble": {"n": N_ENSEMBLE, "widened_ranges": {k: list(widened_ranges[i]) for i, k in enumerate(INPUT_ORDER)},
                     "in_box_fraction": round(in_box_fraction, 3)},
        "thresholds": {"zone_high_p": zone_high_p, "zone_possible_p": zone_possible_p, "wet_threshold_m": NF1_WET_THRESHOLD_M},
        "skill_s": {"f1": round(f1_skill, 3), "arrival_rmse_pct": round(arrival_rmse_pct, 1), "grade": s_grade, "level": s_level,
                    "reference_poi": ref_poi["poi_id"]},
        "spread_u": {"p5_depth_m": round(ref_p5, 3), "p95_depth_m": round(ref_p95, 3), "width_m": round(ref_width, 3),
                     "width_pct_of_median": round(ref_width_pct, 1), "grade": u_grade, "level": u_level},
        "azmi_low": {"inputs": {"water_volume_m3": azmi_low_real[0], "breach_width_m": azmi_low_real[1], "failure_time_s": azmi_low_real[2]},
                     "summary": profile_summary(azmi_low_real, azmi_low_grid), "confidence": azmi_low_conf,
                     "poi_results": scenario_poi_results(azmi_low_grid)},
        "azmi_high": {"inputs": {"water_volume_m3": azmi_high_real[0], "breach_width_m": azmi_high_real[1], "failure_time_s": azmi_high_real[2]},
                      "summary": profile_summary(azmi_high_real, azmi_high_grid), "confidence": azmi_high_conf,
                      "poi_results": scenario_poi_results(azmi_high_grid)},
        "scenario_zone_basis": {"lower_member": lower_name, "upper_member": upper_name,
                                 "lower_area_m2": round(min(azmi_low_area, azmi_high_area), 0),
                                 "upper_area_m2": round(max(azmi_low_area, azmi_high_area), 0)},
        "unknown_breach": {
            "confidence": unknown_breach_conf, "poi_results": poi_results,
            "reference_poi_summary": {
                "poi_id": ref_poi["poi_id"], "median_depth_m": round(ref_median, 3), "p5_depth_m": round(ref_p5, 3), "p95_depth_m": round(ref_p95, 3),
                "median_velocity_ms": round(_velocity_of(ref_median), 3), "p5_velocity_ms": round(_velocity_of(ref_p5), 3), "p95_velocity_ms": round(_velocity_of(ref_p95), 3),
                "median_arrival_s": round(ref_poi["chainage_m"] / _velocity_of(ref_median), 1) if ref_median > 0 else None,
                "fast_arrival_s_at_p95_depth": round(ref_poi["chainage_m"] / _velocity_of(ref_p95), 1) if ref_p95 > 0 else None,
                "slow_arrival_s_at_p5_depth": round(ref_poi["chainage_m"] / _velocity_of(ref_p5), 1) if ref_p5 > 0 else None,
            },
            "breach_cell_summary": {
                "median_depth_m": round(breach_median, 3), "p5_depth_m": round(breach_p5, 3), "p95_depth_m": round(breach_p95, 3),
                "median_discharge_m3s": round(_discharge_of(breach_median), 1), "p5_discharge_m3s": round(_discharge_of(breach_p5), 1), "p95_discharge_m3s": round(_discharge_of(breach_p95), 1),
            },
            "extent_area_m2": {"high_zone": round(area_high_m2, 0), "high_plus_possible_zone": round(area_high_possible_m2, 0)},
        },
        "downgrade_example": downgrade_info,
    }
    DATA_OUT_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_OUT_DIR / "teesta_confidence.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return result


def _gen_probability_raster(path: Path, width: int, height: int, p_wet: list[float]) -> None:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    px = img.load()
    for y in range(SIZE):
        row = min(height - 1, y * height // SIZE)
        for x in range(SIZE):
            col = min(width - 1, x * width // SIZE)
            p = p_wet[row * width + col]
            if p > 0.02:
                px[x, y] = (90, 150, 230, int(60 + p * 180))
    draw = ImageDraw.Draw(img, "RGBA")
    _stamp(draw, "illustrative P(depth > 0.3 m)", (SIZE, SIZE))
    img.save(path)


def _gen_zone_raster(path: Path, width: int, height: int, zone: list[str], downgrade_idx: int | None) -> None:
    """HIGH = red, POSSIBLE = amber (STYLE_GUIDE.md's existing badge colours),
    DRY = transparent. The downgraded cell (if any) gets a bright outline so
    the HIGH->POSSIBLE example is visible, not just documented in JSON."""
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    px = img.load()
    colors = {"HIGH": (229, 69, 63, 200), "POSSIBLE": (222, 183, 124, 170), "DRY": (0, 0, 0, 0)}
    dg_row, dg_col = (downgrade_idx // width, downgrade_idx % width) if downgrade_idx is not None else (-1, -1)
    for y in range(SIZE):
        row = min(height - 1, y * height // SIZE)
        for x in range(SIZE):
            col = min(width - 1, x * width // SIZE)
            px[x, y] = colors[zone[row * width + col]]
            if row == dg_row and col == dg_col:
                px[x, y] = (255, 240, 80, 255)
    draw = ImageDraw.Draw(img, "RGBA")
    _stamp(draw, "illustrative HIGH/POSSIBLE zones", (SIZE, SIZE))
    img.save(path)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    gen_dem_hillshade(OUT_DIR / "dem_hillshade_teesta.png")
    gen_domain_mask(OUT_DIR / "domain_mask_teesta.png")
    gen_nearfield_pair()
    gen_confidence_ensemble()
    print(f"Wrote preview rasters to {OUT_DIR}")


if __name__ == "__main__":
    main()
