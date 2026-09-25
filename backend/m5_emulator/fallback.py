"""The empirical fallback for sites without a trained emulator
(CLAUDE.md module table: "M5 ... Monte Carlo, confidence, fallback";
`docs/handoff_contract.md` §4.6: "For a site without a trained emulator,
returns the empirical fallback with `method: empirical_fallback`, confidence
LOW").

Method (no PCA, no GP, no Monte Carlo -- this is the low-data path):

1. Take M2's peak discharge for the scenario (`Hydrograph.peak_q_m3s`,
   `docs/handoff_contract.md` §4.2) and route it along the centreline
   (`route_discharge`) -- no attenuation, so downstream depths are, if
   anything, slightly over- rather than under-estimated (CLAUDE.md's "honest
   uncertainty matters more than accuracy").
2. At each chainage station, estimate the active channel's top width from
   the HAND raster (`channel_top_width_m`) and normal flow depth from
   Manning's equation for a wide rectangular channel (`manning_normal_depth`),
   using the roughness raster and the bed slope from `chainage_samples.csv`.
3. Flood every cell whose HAND value is below that station's depth
   (`flood_depth_m` = station depth minus cell HAND), with velocity from
   Manning's equation at the same station.
4. Estimate arrival time from a kinematic-wave celerity built on that same
   Manning velocity (`kinematic_wave_celerity`, `cumulative_arrival_time_s`).

Every simplification here is a caveat (`FALLBACK_CAVEATS`), not a hidden
assumption: no downstream attenuation, one flow depth per cross-section (no
lateral routing, so flooded cells in one column all get the same arrival
time), and the wide-channel Manning approximation (invalid where the top
width is not much larger than the flow depth, e.g. a narrow gorge at high
discharge).

Needs M1 terrain outputs that do not exist yet -- `hand.tif`, `roughness.tif`,
`chainage_samples.csv` (`docs/handoff_contract.md` §4.1). Per CLAUDE.md rule
2 ("every module runs end-to-end on synthetic data ... before real data
exists"), `FallbackTerrain.from_rasters` is the real-data loader this module
will use once M1 exists, and `synthetic_fallback_terrain` below is the
stand-in used by this module's own tests, built from the same valley
geometry as `synthetic.py` (`docs/m5_specs.md` §7.1) but *not* through
`synthetic_flood_maps` -- the fallback must be tested against terrain alone,
never given the emulator's own "true" answer to fit against.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

from backend.m5_emulator import confidence as conf
from backend.m5_emulator import synthetic as sw
from backend.shared.grid import CanonicalGrid, FLOAT_NODATA

CONTRACT_VERSION = "0.2.0"

#: docs/m5_specs.md §4 defaults (also emulator.EmulatorSettings' defaults).
EXTENT_THRESHOLD_M = 0.3
ARRIVAL_THRESHOLD_M = 0.1

#: HAND value (m) below which a cell counts as "in the active channel" when
#: measuring a cross-section's top width off the HAND raster -- a fallback-only
#: convention (no contract file gives channel width directly), not a sourced
#: site fact (CLAUDE.md rule 3 doesn't apply -- it's a method parameter, not a
#: fact about a dam or lake).
CHANNEL_REF_HAND_M = 2.0
MIN_CHANNEL_WIDTH_CELLS = 1

#: Bed-slope floor (dimensionless), avoiding a singular Manning solution on a
#: numerically flat reach.
MIN_SLOPE = 1e-4

#: Kinematic-wave celerity for a wide channel obeying Manning's equation is
#: (5/3) x the mean velocity (standard open-channel hydraulics result, e.g.
#: Chow, "Open-Channel Hydraulics", 1959 -- not one of docs/Equations.md's
#: breach equations, which is why it isn't cited from there).
KINEMATIC_CELERITY_FACTOR = 5.0 / 3.0
CELERITY_MIN_MS = 0.1  # m/s floor, avoids division by ~0 before flow ramps up

FALLBACK_CAVEATS = [
    {"id": "empirical_fallback", "severity": "warning", "text_key": "caveat_empirical_fallback"},
    {"id": "clear_water", "severity": "warning", "text_key": "caveat_clear_water"},
]


# ============================================================================
# Manning / kinematic-wave equations (one function per equation, per
# CLAUDE.md rule 4 -- these are standard open-channel hydraulics, not
# docs/Equations.md breach equations, so they're documented here instead)
# ============================================================================


def route_discharge(chainage_m: np.ndarray, peak_discharge_m3s: float) -> np.ndarray:
    """M2's peak discharge, routed along the centreline (module docstring
    step 1): constant with chainage. `peak_discharge_m3s` must be > 0 (a
    zero or negative discharge means M2 didn't produce a usable breach
    outflow -- callers should not reach this fallback with one)."""
    if peak_discharge_m3s <= 0:
        raise ValueError(f"peak_discharge_m3s must be > 0, got {peak_discharge_m3s!r}")
    return np.full_like(np.asarray(chainage_m, dtype=np.float64), float(peak_discharge_m3s))


def channel_top_width_m(
    hand_m: np.ndarray, domain_mask: np.ndarray, cell_size_m: float, ref_hand_m: float = CHANNEL_REF_HAND_M,
) -> np.ndarray:
    """Per-column (chainage station) active-channel top width [m]: cell size
    times the count of domain cells with HAND at or below `ref_hand_m`, in
    that column. Floored at `MIN_CHANNEL_WIDTH_CELLS` cell so a column with no
    cell that low (e.g. a coarse HAND raster on a very narrow gorge) still
    gives a finite, if narrow, channel rather than dividing by zero."""
    active = domain_mask & (hand_m <= ref_hand_m)
    counts = active.sum(axis=0)
    counts = np.maximum(counts, MIN_CHANNEL_WIDTH_CELLS)
    return counts.astype(np.float64) * cell_size_m


def channel_roughness(
    roughness_n: np.ndarray, domain_mask: np.ndarray, hand_m: np.ndarray, ref_hand_m: float = CHANNEL_REF_HAND_M,
) -> np.ndarray:
    """Per-column Manning's n: mean roughness of that column's active-channel
    cells (HAND <= `ref_hand_m`), falling back to the mean of all domain
    cells in the column if none qualifies."""
    active = domain_mask & (hand_m <= ref_hand_m)
    width = roughness_n.shape[1]
    n = np.empty(width, dtype=np.float64)
    for col in range(width):
        col_active = active[:, col]
        if col_active.any():
            n[col] = float(roughness_n[col_active, col].mean())
        else:
            col_domain = domain_mask[:, col]
            n[col] = float(roughness_n[col_domain, col].mean()) if col_domain.any() else np.nan
    return n


def bed_slope(bed_elev_m: np.ndarray, chainage_m: np.ndarray, min_slope: float = MIN_SLOPE) -> np.ndarray:
    """Bed-slope magnitude along the centreline (central difference of
    `chainage_samples.csv`'s `bed_elev_m` over `chainage_m`), floored at
    `min_slope` -- Manning's equation is singular at zero slope."""
    slope = np.abs(np.gradient(np.asarray(bed_elev_m, dtype=np.float64), np.asarray(chainage_m, dtype=np.float64)))
    return np.maximum(slope, min_slope)


def manning_normal_depth(q_unit_m2s: np.ndarray, manning_n: np.ndarray, slope: np.ndarray) -> np.ndarray:
    """Manning's equation, solved for normal depth in a wide rectangular
    channel (hydraulic radius ~= depth -- standard open-channel hydraulics,
    e.g. Chow 1959): `q = (1/n) d^(5/3) sqrt(S)` => `d = (q n / sqrt(S))^(3/5)`.

    q_unit_m2s: discharge per unit top width [m^2/s], > 0. manning_n:
    Manning's roughness [s/m^(1/3)], > 0. slope: dimensionless bed slope,
    > 0. Valid only where the channel top width is much larger than the flow
    depth -- not valid in a narrow, deep gorge at high discharge (flagged by
    the `empirical_fallback` caveat, not checked numerically here)."""
    q = np.maximum(np.asarray(q_unit_m2s, dtype=np.float64), 0.0)
    return np.power(q * np.asarray(manning_n, dtype=np.float64) / np.sqrt(np.asarray(slope, dtype=np.float64)), 3.0 / 5.0)


def manning_velocity(depth_m: np.ndarray, manning_n: np.ndarray, slope: np.ndarray) -> np.ndarray:
    """Manning's equation for mean velocity in the same wide-channel
    approximation: `v = (1/n) d^(2/3) sqrt(S)`."""
    d = np.maximum(np.asarray(depth_m, dtype=np.float64), 0.0)
    return (1.0 / np.asarray(manning_n, dtype=np.float64)) * np.power(d, 2.0 / 3.0) * np.sqrt(np.asarray(slope, dtype=np.float64))


def kinematic_wave_celerity(
    velocity_ms: np.ndarray, factor: float = KINEMATIC_CELERITY_FACTOR, min_ms: float = CELERITY_MIN_MS,
) -> np.ndarray:
    """Kinematic-wave celerity for a wide Manning channel: `c = (5/3) v`
    (module-level docstring), floored at `min_ms` so arrival time stays
    finite where the station is effectively dry."""
    return np.maximum(factor * np.asarray(velocity_ms, dtype=np.float64), min_ms)


def cumulative_arrival_time_s(chainage_m: np.ndarray, celerity_ms: np.ndarray, t_offset_s: float = 0.0) -> np.ndarray:
    """Cumulative travel time to each chainage station: the running integral
    of `1/celerity` over chainage (module docstring step 4's "simple
    wave-celerity assumption"), from the breach (chainage 0) at `t_offset_s`
    (> 0 for a downstream dam in a cascade, `docs/handoff_contract.md`
    §4.2's hydrograph `t_offset_s`)."""
    chainage_m = np.asarray(chainage_m, dtype=np.float64)
    ds = np.diff(chainage_m, prepend=0.0)
    return t_offset_s + np.cumsum(ds / np.asarray(celerity_ms, dtype=np.float64))


# ============================================================================
# Terrain input
# ============================================================================


@dataclass(frozen=True)
class FallbackTerrain:
    """The M1 terrain outputs this fallback needs (`docs/handoff_contract.md`
    §4.1), reduced to what the routing/Manning/HAND steps read: per-cell HAND
    and roughness, the domain mask, and the centreline's chainage/bed-elevation
    profile (one value per grid column -- valid once M1's real centreline runs
    straight down a column of the far-field grid, true for every site's
    `centreline.gpkg` today; a meandering centreline would need chainage
    resampled onto the grid first, not handled here)."""

    grid: CanonicalGrid
    hand_m: np.ndarray        # (height, width) float, m
    roughness_n: np.ndarray   # (height, width) float, Manning's n
    domain_mask: np.ndarray   # (height, width) bool
    chainage_m: np.ndarray    # (width,) float, m downstream from the breach
    bed_elev_m: np.ndarray    # (width,) float, m


# ============================================================================
# Synthetic terrain (for this module's own tests -- module docstring)
# ============================================================================


def synthetic_fallback_terrain(
    grid: CanonicalGrid, *, dam_elev_m: float = 2_000.0, manning_n: float = sw.MANNING_N, wall_slope: float = 0.15,
) -> FallbackTerrain:
    """HAND/roughness/bed-elevation stand-in for `synthetic.py`'s valley
    (`docs/m5_specs.md` §7.1), used only by this module's tests -- built
    independently of `synthetic_flood_maps` (see module docstring). HAND is
    0 across the (unconstricted) floor half-width and rises linearly with
    lateral distance beyond it at `wall_slope` [m HAND per m offset], a
    reasonable valley-wall stand-in, not a sourced elevation. Roughness is
    uniform at `manning_n` (matches `synthetic.MANNING_N`, for a fair
    A1-style comparison against the emulator on the same synthetic valley).
    Bed elevation integrates the valley's longitudinal slope profile
    downstream from `dam_elev_m` at chainage 0."""
    chainage, offset = sw._chainage_and_offset(grid)
    s = chainage.reshape(1, -1)
    y = offset.reshape(-1, 1)

    floor_half_width = sw._floor_half_width(s).ravel()
    slope = sw._slope(s).ravel()
    ds = grid.cell_size_m
    bed_elev = dam_elev_m - np.concatenate(([0.0], np.cumsum(slope[:-1] * ds)))

    lateral_excess = np.maximum(np.abs(y) - floor_half_width.reshape(1, -1), 0.0)
    hand = (lateral_excess * wall_slope).astype(np.float32)
    hand = np.broadcast_to(hand, grid.shape).copy()

    roughness = np.full(grid.shape, manning_n, dtype=np.float32)
    domain_mask = np.ones(grid.shape, dtype=bool)

    return FallbackTerrain(
        grid=grid, hand_m=hand, roughness_n=roughness, domain_mask=domain_mask,
        chainage_m=chainage.astype(np.float64), bed_elev_m=bed_elev.astype(np.float64),
    )


# ============================================================================
# Result
# ============================================================================


@dataclass(frozen=True)
class FallbackResult:
    """One empirical-fallback answer -- full-grid arrays in the same units as
    `query.FloodResult` (max depth [m], max velocity [m/s], arrival [s since
    t0, `FLOAT_NODATA` where never wet]), plus the deterministic extent class
    and the always-LOW confidence (module docstring; contract §4.6)."""

    site_id: str
    peak_discharge_m3s: float
    max_depth_m: np.ndarray
    max_velocity_ms: np.ndarray
    arrival_time_s: np.ndarray
    extent_class: np.ndarray  # uint8: 0 dry, 2 HIGH -- no POSSIBLE band (this method gives one deterministic estimate, not a probability)
    confidence: dict          # {"overall", "extent", "depth", "arrival", "velocity"}, all level "LOW"


def _fallback_confidence() -> dict:
    """Always LOW (contract §4.6, module docstring) -- `combine`'s
    `empirical_fallback=True` forces LOW regardless of the S/C/U components,
    which don't apply here (no LOOCV skill, no training design to be near,
    no probability band to measure the spread of). `query_coverage="INSIDE"`
    is a dummy placeholder, not a real check: `combine` reads a literal
    `"OUTSIDE"` there as extrapolation and reports `conf_extrapolation`
    instead, which would misstate *why* this is LOW."""
    per_output = {
        name: conf.combine("UNKNOWN", "INSIDE", "WIDE", empirical_fallback=True)
        for name in ("extent", "depth", "arrival", "velocity")
    }
    return {"overall": conf.overall(per_output), **per_output}


def run_empirical_fallback(
    terrain: FallbackTerrain,
    peak_discharge_m3s: float,
    *,
    t_offset_s: float = 0.0,
    extent_m: float = EXTENT_THRESHOLD_M,
    arrival_m: float = ARRIVAL_THRESHOLD_M,
    ref_hand_m: float = CHANNEL_REF_HAND_M,
) -> FallbackResult:
    """Run the empirical fallback (module docstring steps 1-4) over
    `terrain`, for one scenario's peak discharge."""
    grid = terrain.grid
    q_col = route_discharge(terrain.chainage_m, peak_discharge_m3s)
    width_col = channel_top_width_m(terrain.hand_m, terrain.domain_mask, grid.cell_size_m, ref_hand_m)
    n_col = channel_roughness(terrain.roughness_n, terrain.domain_mask, terrain.hand_m, ref_hand_m)
    slope_col = bed_slope(terrain.bed_elev_m, terrain.chainage_m)

    q_unit = q_col / width_col
    depth_col = manning_normal_depth(q_unit, n_col, slope_col)
    velocity_col = manning_velocity(depth_col, n_col, slope_col)
    celerity_col = kinematic_wave_celerity(velocity_col)
    arrival_col = cumulative_arrival_time_s(terrain.chainage_m, celerity_col, t_offset_s)

    depth_full = np.where(terrain.domain_mask, depth_col.reshape(1, -1) - terrain.hand_m, 0.0)
    depth_full = np.maximum(depth_full, 0.0).astype(np.float32)

    wet = depth_full > arrival_m
    velocity_full = np.where(wet, np.broadcast_to(velocity_col.reshape(1, -1), grid.shape), 0.0).astype(np.float32)
    arrival_full = np.where(wet, np.broadcast_to(arrival_col.reshape(1, -1), grid.shape), FLOAT_NODATA).astype(np.float32)

    extent_class = np.where(depth_full > extent_m, np.uint8(2), np.uint8(0))
    extent_class[~terrain.domain_mask] = 0

    return FallbackResult(
        site_id=grid.site_id, peak_discharge_m3s=float(peak_discharge_m3s),
        max_depth_m=depth_full, max_velocity_ms=velocity_full, arrival_time_s=arrival_full,
        extent_class=extent_class, confidence=_fallback_confidence(),
    )


# ============================================================================
# Contract response (docs/handoff_contract.md §5.4) -- mirrors
# query.to_contract_response's shape, method "empirical_fallback"
# ============================================================================


def _estimate(value, low, high, unit, *, kind="predicted", interval="none", confidence=None, basis=None) -> dict:
    d = {"value": value, "low": low, "high": high, "unit": unit, "interval": interval, "kind": kind}
    if confidence is not None:
        d["confidence"] = confidence
    if basis is not None:
        d["basis"] = basis
    return d


def to_contract_response(
    result: FallbackResult, grid: CanonicalGrid, *, query_id: str, mode: str = "scenario",
    pois: dict[str, int] | None = None, resolved_inputs: dict | None = None, timing_ms: dict | None = None,
) -> dict:
    """`result` -> a dict matching `flood_query_response.schema.json`
    (docs/handoff_contract.md §5.4), `method: "empirical_fallback"`. `layers`
    only lists the three deterministic maps this method actually produces
    (no P10/P90 band, no `p_inundation` -- there's no probability
    distribution here) plus `extent_class`. `pois`: name -> flattened
    full-grid cell index (same convention as `query.get_flood`), used to name
    `summary.first_arrival` -- the schema's `poi_id`/`name` are non-nullable
    strings, so at least one POI is needed for a wet result to validate."""
    bounds = grid.bounds_latlng
    area_m2 = float((result.extent_class == 2).sum()) * grid.cell_size_m ** 2
    depth_max = float(result.max_depth_m.max())
    velocity_max = float(result.max_velocity_ms.max())

    first_name, first_s = None, None
    for name, idx in (pois or {}).items():
        row, col = divmod(idx, grid.width)
        val = float(result.arrival_time_s[row, col])
        if val != FLOAT_NODATA and (first_s is None or val < first_s):
            first_name, first_s = name, val

    summary = {
        "inundated_area_m2": _estimate(area_m2, area_m2, area_m2, "m2", confidence=result.confidence["extent"]["level"]),
        "max_depth_m": _estimate(depth_max, depth_max, depth_max, "m", confidence=result.confidence["depth"]["level"]),
        "max_velocity_ms": _estimate(velocity_max, velocity_max, velocity_max, "ms", confidence=result.confidence["velocity"]["level"]),
        "peak_discharge_m3s": _estimate(
            result.peak_discharge_m3s, result.peak_discharge_m3s, result.peak_discharge_m3s, "m3s",
            basis="M2 breach outflow, routed with no attenuation (empirical_fallback)",
        ),
        "first_arrival": {
            "poi_id": f"{result.site_id}__poi__{first_name}" if first_name else None,
            "name": first_name,
            "arrival_s": (_estimate(first_s, first_s, first_s, "s", confidence=result.confidence["arrival"]["level"])
                          if first_s is not None else _estimate(None, None, None, "s")),
        },
    }

    layers = [
        {"layer_id": "extent_class", "type": "raster_png", "url": f"/api/v1/flood/{query_id}/layers/extent_class.png",
         "bounds_latlng": bounds, "style_id": "extent_class", "unit": None, "available": True},
        {"layer_id": "depth_p50", "type": "raster_png", "url": f"/api/v1/flood/{query_id}/layers/depth_p50.png",
         "bounds_latlng": bounds, "style_id": "depth_p50", "unit": "m", "available": True},
        {"layer_id": "velocity_p50", "type": "raster_png", "url": f"/api/v1/flood/{query_id}/layers/velocity_p50.png",
         "bounds_latlng": bounds, "style_id": "depth_p50", "unit": "ms", "available": True},
    ]

    resolved = resolved_inputs or {}

    return {
        "contract_version": CONTRACT_VERSION,
        "query_id": query_id, "site_id": result.site_id, "status": "complete", "method": "empirical_fallback",
        "mode": mode, "resolved_inputs": resolved, "summary": summary,
        "confidence": result.confidence, "layers": layers,
        "vectors": {"extent_url": f"/api/v1/flood/{query_id}/extent.geojson"},
        "flags": {"outside_trained_range": False, "demo_mode": False, "library_outdated": False, "has_placeholders": False},
        "placeholder_fields": [],
        "caveats": list(FALLBACK_CAVEATS),
        "provenance": {
            "method": "empirical_fallback", "contract_version": CONTRACT_VERSION,
            "parameters": {"mode": mode},
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "timing_ms": timing_ms or {"median_phase": 0, "full_phase": 0},
    }
