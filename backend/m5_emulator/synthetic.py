"""Synthetic test world for M5 (`docs/m5_specs.md` §7).

A cheap stand-in for the 2D hydraulic model, used to test the M5 pipeline
end to end before real Delft3D/DualSPHysics runs exist. `synthetic_flood_maps`
is a function, not a simulation: given a canonical grid and one breach
scenario (`water_volume_m3`, `breach_width_m`, `failure_time_s` — the
contract's emulator-input names, §3.3), it returns max depth, max velocity
and arrival-time maps in milliseconds, deterministically. Its qualitative
behaviour is known by construction (§7.2), so tests can check that a trained
emulator recovers it (§8 acceptance tests).

Valley (§7.1): a single 40 km valley, dam at chainage 0, open plain at
40 km — steep 15 km gorge (~50 m floor, 2% slope), a 500 m constriction
at 10 km, a 15 km trapezoidal middle reach (~300 m floor, 0.8% slope) with
a raised terrace ("the town") at 22 km that is dry until overtopped, then
a 10 km fan/plain (0.3% slope, floor widening to 2 km).

Deviation from §7.1's illustrative grid: the spec sketches non-square cells
(e.g. "100 m x 50 m") sized to resolve a ~50 m gorge floor across a valley
whose fan is ~2 km wide. `backend.shared.grid.CanonicalGrid` — the grid every
raster in this project must align to (`docs/handoff_contract.md` §1.4) —
only supports square cells, and no single square cell size both resolves the
narrowest feature (the 12.5 m constriction half-width) and keeps the total
cell count near the spec's illustrative "40k" at this valley's full cross
width. `small_grid`/`large_grid` below keep the spec's 40 km length and the
same 3.2 km cross-valley domain (wide enough for the fan plus its lateral
decay), sized instead by "small enough to resolve the constriction, small
enough total cells to be a quick test": small = 16 m, 2500x200 (500k cells);
large = 8 m, 5000x400 (2M cells, same order of magnitude as the "about 1M"
target and as the real far-field grids in `docs/handoff_contract.md` §1.4's
own example).

All numeric constants below (valley dimensions aside, which come from §7.1)
are illustrative shape constants for this fake world, not sourced facts —
CLAUDE.md rule 3 does not apply here, this is declared synthetic test data.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from backend.shared.grid import CanonicalGrid, FLOAT_NODATA, write_grid_raster

CONTRACT_VERSION = "0.1.0"

# =============================================================================
# Thresholds (docs/handoff_contract.md §1.5 defaults)
# =============================================================================

EXTENT_THRESHOLD_M = 0.3
ARRIVAL_THRESHOLD_M = 0.1

# =============================================================================
# Valley geometry (docs/m5_specs.md §7.1)
# =============================================================================

VALLEY_LENGTH_M = 40_000.0
GORGE_END_M = 15_000.0
MIDDLE_END_M = 30_000.0
PLAIN_END_M = VALLEY_LENGTH_M
TRANSITION_BLEND_M = 600.0  # width of the smoothed jump between named zones

GORGE_HALF_WIDTH_M = 25.0    # half of the ~50 m gorge floor
MIDDLE_HALF_WIDTH_M = 150.0  # half of the ~300 m middle floor
PLAIN_HALF_WIDTH_M = 1_000.0  # half of the ~2 km fan floor at the valley mouth

GORGE_SLOPE = 0.02
MIDDLE_SLOPE = 0.008
PLAIN_SLOPE = 0.003

CONSTRICTION_CENTER_M = 10_000.0
CONSTRICTION_HALF_LENGTH_M = 250.0       # the floor is at half width for 500 m
CONSTRICTION_BLEND_UPSTREAM_M = 700.0    # longer shoulder: water backs up upstream
CONSTRICTION_BLEND_DOWNSTREAM_M = 250.0  # sharper relaxation downstream

TERRACE_CENTER_M = 22_000.0
TERRACE_HALF_LENGTH_M = 500.0  # ~1 km bench along the valley
TERRACE_BLEND_M = 150.0
TERRACE_HEIGHT_M = 3.0  # above the local valley floor
TERRACE_SIGMOID_WIDTH_M = 0.5  # steepness of the overtopping threshold, in m of channel stage
TERRACE_SATURATE_M = 2.0  # extra stage above the threshold needed to reach the max terrace depth
TERRACE_MIN_DEPTH_M = 0.5
TERRACE_MAX_DEPTH_M = 1.5
TERRACE_INNER_OFFSET_M = 170.0  # just past the middle-reach floor edge (150 m)
TERRACE_OUTER_OFFSET_M = 420.0
TERRACE_EDGE_BLEND_M = 60.0
TERRACE_OVERTOP_DELAY_S = 300.0  # extra time to top the bench, once overtopped

LATERAL_DECAY_FRACTION = 0.6  # lateral wet-to-dry decay width, as a fraction of the local floor half-width
LATERAL_DELAY_S_PER_M = 2.0   # extra arrival delay for cells off the channel centreline

DEPTH_K = 0.9        # depth_channel = DEPTH_K * sqrt(unit discharge)
MANNING_N = 0.04      # uniform synthetic roughness for the velocity ~ Manning relation
CELERITY_FACTOR = 1.5  # wave celerity as a multiple of channel velocity
CELERITY_MIN = 0.1     # m/s floor, avoids division by ~0 near the dam before flow ramps up

DELAY_FRACTION = 0.05  # near the dam, arrival is shifted by this fraction of failure_time_s
DELAY_FADE_LENGTH_M = 25_000.0  # e-folding distance over which that delay fades — long enough that
# its decay never outpaces the travel-time increase with distance, so arrival stays monotonic in s
# across the full DEFAULT_INPUT_RANGES design space

ATTEN_K = 1.2e-7  # 1/m^2 — attenuation rate per metre of local floor half-width

Q0_M3S = 2_000.0
V_REF_M3 = 1.0e7
B_REF_M = 50.0
T_F_REF_S = 1_800.0
V_EXP = 0.55  # V_w usually dominates (docs/m5_specs.md §3, ARD kernel note)
B_EXP = 0.25
T_EXP = 0.35

#: Plausible synthetic ranges spanning "terrace dry" to "terrace overtopped"
#: at reference breach_width_m/failure_time_s — for building a synthetic-world
#: LHS scenario design in tests, not a real site's M2 range.
DEFAULT_INPUT_RANGES: dict[str, tuple[float, float]] = {
    "water_volume_m3": (1.0e5, 1.0e8),
    "breach_width_m": (20.0, 150.0),
    "failure_time_s": (300.0, 10_800.0),
}


# =============================================================================
# Grid presets (docs/m5_specs.md §7.1: "a small version ... for quick tests,
# and a large version of about 1M cells for the memory and runtime tests")
# =============================================================================


def small_grid(site_id: str = "m5synth") -> CanonicalGrid:
    """2500x200 cells at 16 m -> 40 km x 3.2 km domain, 500,000 cells."""
    return CanonicalGrid(site_id=site_id, grid_id="farfield", crs_epsg=32645,
                          origin_x=500_000.0, origin_y=3_100_000.0,
                          cell_size_m=16.0, width=2500, height=200)


def large_grid(site_id: str = "m5synth") -> CanonicalGrid:
    """5000x400 cells at 8 m -> the same 40 km x 3.2 km domain, 2,000,000 cells."""
    return CanonicalGrid(site_id=site_id, grid_id="farfield", crs_epsg=32645,
                          origin_x=500_000.0, origin_y=3_100_000.0,
                          cell_size_m=8.0, width=5000, height=400)


# =============================================================================
# Small numeric helpers
# =============================================================================


def _check_positive(**kwargs: float) -> None:
    for name, v in kwargs.items():
        if v is None or v <= 0:
            raise ValueError(f"{name} must be > 0, got {v!r}")


def _smoothstep(t: np.ndarray) -> np.ndarray:
    """Cubic smoothstep, clamped: 0 for t<=0, 1 for t>=1, C1-smooth between."""
    tc = np.clip(t, 0.0, 1.0)
    return tc * tc * (3.0 - 2.0 * tc)


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _smooth_piecewise(s: np.ndarray, breakpoints: list[float], values: list[float], blend: float) -> np.ndarray:
    """`values[0]` for s well below `breakpoints[0]`, ..., `values[-1]` for s well
    above `breakpoints[-1]`, each transition smoothstep-blended over `blend`
    metres centred on its breakpoint. Breakpoints must be well separated
    relative to `blend` (true for the valley's named zones)."""
    result = np.full_like(s, values[0], dtype=float)
    for x0, v1 in zip(breakpoints, values[1:]):
        t = _smoothstep((s - x0) / blend + 0.5)
        result = result * (1.0 - t) + v1 * t
    return result


def _chainage_and_offset(grid: CanonicalGrid) -> tuple[np.ndarray, np.ndarray]:
    """Chainage (m downstream from the dam at column 0) per column, and signed
    cross-valley offset from the centreline (m; >0 = the bank the terrace sits
    on) per row."""
    col = np.arange(grid.width, dtype=float)
    row = np.arange(grid.height, dtype=float)
    chainage = (col + 0.5) * grid.cell_size_m
    centre_row = grid.height / 2.0
    offset = (row - centre_row + 0.5) * grid.cell_size_m
    return chainage, offset


# =============================================================================
# Valley cross-section / longitudinal profile (functions of chainage `s`, a
# (1, width) array; broadcast against offset `y`, a (height, 1) array)
# =============================================================================


def _slope(s: np.ndarray) -> np.ndarray:
    return _smooth_piecewise(s, [GORGE_END_M, MIDDLE_END_M], [GORGE_SLOPE, MIDDLE_SLOPE, PLAIN_SLOPE], TRANSITION_BLEND_M)


def _floor_half_width_base(s: np.ndarray) -> np.ndarray:
    """Unconstricted floor half-width: gorge -> middle jump, then a smooth
    widening ramp across the fan (15 km, 15 km, then widening to 2 km)."""
    base = _smooth_piecewise(s, [GORGE_END_M], [GORGE_HALF_WIDTH_M, MIDDLE_HALF_WIDTH_M], TRANSITION_BLEND_M)
    fan_t = _smoothstep((s - MIDDLE_END_M) / (PLAIN_END_M - MIDDLE_END_M))
    fan_extra = np.where(s > MIDDLE_END_M, (PLAIN_HALF_WIDTH_M - MIDDLE_HALF_WIDTH_M) * fan_t, 0.0)
    return base + fan_extra


def _constriction_bump(s: np.ndarray) -> np.ndarray:
    """1 inside the 500 m narrow band at 10 km, decaying to 0 over an
    asymmetric shoulder (longer upstream: backwater from the constriction)."""
    dist = np.abs(s - CONSTRICTION_CENTER_M)
    blend = np.where(s < CONSTRICTION_CENTER_M, CONSTRICTION_BLEND_UPSTREAM_M, CONSTRICTION_BLEND_DOWNSTREAM_M)
    t = (dist - CONSTRICTION_HALF_LENGTH_M) / blend
    return 1.0 - _smoothstep(t)


def _floor_half_width(s: np.ndarray) -> np.ndarray:
    return _floor_half_width_base(s) * (1.0 - 0.5 * _constriction_bump(s))


def _terrace_window(s: np.ndarray) -> np.ndarray:
    """1 within the terrace's along-valley footprint, 0 elsewhere."""
    t = (np.abs(s - TERRACE_CENTER_M) - TERRACE_HALF_LENGTH_M) / TERRACE_BLEND_M
    return 1.0 - _smoothstep(t)


def _terrace_lateral_window(y: np.ndarray) -> np.ndarray:
    """1 within the terrace's cross-valley band on the positive-offset bank."""
    inner = _smoothstep((y - TERRACE_INNER_OFFSET_M) / TERRACE_EDGE_BLEND_M)
    outer = 1.0 - _smoothstep((y - TERRACE_OUTER_OFFSET_M) / TERRACE_EDGE_BLEND_M)
    return inner * outer * (y > 0)


def _lateral_factor(y: np.ndarray, fh: np.ndarray) -> np.ndarray:
    """1 within the wet floor, smoothstep decay to 0 over a band that scales
    with the local floor half-width (narrow in the gorge -> walls cap the
    extent; wide on the plain -> water spreads)."""
    decay = np.maximum(LATERAL_DECAY_FRACTION * fh, 1e-6)
    excess = (np.abs(y) - fh) / decay
    return 1.0 - _smoothstep(excess)


def _peak_flow_proxy(water_volume_m3: float, breach_width_m: float, failure_time_s: float) -> float:
    """Peak-flow proxy: grows with volume and breach width, shrinks as
    failure time lengthens (docs/m5_specs.md §7.2)."""
    return (Q0_M3S * (water_volume_m3 / V_REF_M3) ** V_EXP
            * (breach_width_m / B_REF_M) ** B_EXP
            * (T_F_REF_S / failure_time_s) ** T_EXP)


def _attenuation(s: np.ndarray, fh_base: np.ndarray, cell_size_m: float) -> np.ndarray:
    """Cumulative downstream attenuation of the peak-flow proxy: a rectangle-rule
    integral of a decay rate proportional to the local unconstricted floor
    half-width (faster attenuation where the valley is wide)."""
    rate = ATTEN_K * fh_base
    return np.exp(-np.cumsum(rate * cell_size_m, axis=1))


# =============================================================================
# Public API
# =============================================================================


@dataclass(frozen=True)
class SyntheticFloodMaps:
    """One scenario's synthetic max-depth / max-velocity / arrival-time maps,
    on `grid`, in the M3/M4 run-result units (`docs/handoff_contract.md` §4.4):
    depth [m], velocity [m/s], arrival [s since t0]. Dry cells: depth/velocity
    0.0; arrival `FLOAT_NODATA` (never exceeds the arrival threshold)."""

    max_depth_m: np.ndarray
    max_velocity_ms: np.ndarray
    arrival_time_s: np.ndarray
    grid: CanonicalGrid

    def extent_mask(self, threshold_m: float = EXTENT_THRESHOLD_M) -> np.ndarray:
        """Boolean flooded mask, derived from depth (contract: extent is not
        stored separately, docs/m5_specs.md §1)."""
        return self.max_depth_m > threshold_m


def synthetic_flood_maps(
    grid: CanonicalGrid,
    water_volume_m3: float,
    breach_width_m: float,
    failure_time_s: float,
    *,
    extent_threshold_m: float = EXTENT_THRESHOLD_M,
    arrival_threshold_m: float = ARRIVAL_THRESHOLD_M,
    noise_std_m: float = 0.0,
    seed: int = 0,
) -> SyntheticFloodMaps:
    """The synthetic world's fake "physics": one breach scenario -> max depth,
    max velocity and arrival-time maps on `grid`.

    Deterministic given `seed` (only consulted when `noise_std_m > 0`, per
    docs/m5_specs.md §7.3's "optional small noise switch"). All responses are
    monotonic in the directions listed in §7.2, so callers can check both
    direction and size (acceptance test A3).
    """
    _check_positive(water_volume_m3=water_volume_m3, breach_width_m=breach_width_m, failure_time_s=failure_time_s)

    chainage, offset = _chainage_and_offset(grid)
    s = chainage.reshape(1, -1)
    y = offset.reshape(-1, 1)

    fh_base = _floor_half_width_base(s)
    fh = _floor_half_width(s)
    slope = _slope(s)

    q_peak = _peak_flow_proxy(water_volume_m3, breach_width_m, failure_time_s)
    q_s = q_peak * _attenuation(s, fh_base, grid.cell_size_m)
    unit_q = q_s / (2.0 * fh)
    depth_channel = DEPTH_K * np.sqrt(np.maximum(unit_q, 0.0))  # (1, width)

    depth = depth_channel * _lateral_factor(y, fh)  # (height, width)

    terrace_mask = _terrace_window(s) * _terrace_lateral_window(y)  # (height, width)
    overtop = _sigmoid((depth_channel - TERRACE_HEIGHT_M) / TERRACE_SIGMOID_WIDTH_M)
    fill = np.clip((depth_channel - TERRACE_HEIGHT_M) / TERRACE_SATURATE_M, 0.0, 1.0)
    terrace_depth = overtop * (TERRACE_MIN_DEPTH_M + (TERRACE_MAX_DEPTH_M - TERRACE_MIN_DEPTH_M) * fill)
    depth = depth * (1.0 - terrace_mask) + terrace_depth * terrace_mask

    velocity = (1.0 / MANNING_N) * np.power(np.maximum(depth, 0.0), 2.0 / 3.0) * np.sqrt(slope)

    v_channel = (1.0 / MANNING_N) * np.power(np.maximum(depth_channel, 0.0), 2.0 / 3.0) * np.sqrt(slope)
    celerity = np.maximum(CELERITY_FACTOR * v_channel, CELERITY_MIN)
    ds = grid.cell_size_m
    travel = np.cumsum(ds / celerity, axis=1) - 0.5 * ds / celerity  # integral up to each cell's centre
    delay = DELAY_FRACTION * failure_time_s * np.exp(-s / DELAY_FADE_LENGTH_M)
    arrival_channel = travel + delay  # (1, width)

    lateral_delay = LATERAL_DELAY_S_PER_M * np.clip(np.abs(y) - fh, 0.0, None)
    arrival = arrival_channel + lateral_delay
    terrace_arrival = np.broadcast_to(arrival_channel + TERRACE_OVERTOP_DELAY_S, depth.shape)
    arrival = np.where(terrace_mask > 0.5, terrace_arrival, arrival)

    if noise_std_m > 0:
        rng = np.random.default_rng(seed)
        depth = np.maximum(depth + rng.normal(0.0, noise_std_m, size=depth.shape), 0.0)
        velocity = np.maximum(velocity + rng.normal(0.0, noise_std_m, size=velocity.shape), 0.0)

    wet = depth > arrival_threshold_m
    arrival = np.where(wet, arrival, FLOAT_NODATA)

    return SyntheticFloodMaps(
        max_depth_m=depth.astype(np.float32),
        max_velocity_ms=velocity.astype(np.float32),
        arrival_time_s=arrival.astype(np.float32),
        grid=grid,
    )


def terrace_cells(grid: CanonicalGrid) -> np.ndarray:
    """Boolean (height, width) mask of the terrace ("the town", §7.1): cells
    where `_terrace_window * _terrace_lateral_window > 0.5` — i.e. inside the
    along-valley and cross-valley terrace footprint, not the smoothstep
    shoulders. Used by LOOCV's A4 terrace test (`metrics.terrace_correct`)."""
    chainage, offset = _chainage_and_offset(grid)
    s = chainage.reshape(1, -1)
    y = offset.reshape(-1, 1)
    window = _terrace_window(s) * _terrace_lateral_window(y)
    return np.broadcast_to(window > 0.5, (grid.height, grid.width))


#: Five points of interest spanning the synthetic valley's named zones
#: (§7.1), declared purely for this test world — NOT a real site's POIs
#: (`docs/handoff_contract.md` `poi_id` pattern). Used by LOOCV's A2 (POI
#: coverage) and A3 (paired-query monotonicity at points).
SYNTHETIC_POIS: dict[str, float] = {
    "gorge_5km": 5_000.0,
    "upstream_of_constriction_9_5km": 9_500.0,
    "terrace_22km": TERRACE_CENTER_M,
    "middle_27km": 27_000.0,
    "plain_36km": 36_000.0,
}


def poi_cell_index(grid: CanonicalGrid, chainage_m: float) -> int:
    """Flattened (row-major) cell index of the channel-centreline cell
    nearest `chainage_m`, for reading a POI's value out of a flattened map
    stack column."""
    col = int(np.clip(round(chainage_m / grid.cell_size_m - 0.5), 0, grid.width - 1))
    row = grid.height // 2
    return row * grid.width + col


def write_synthetic_run(
    run_dir: str | Path,
    grid: CanonicalGrid,
    water_volume_m3: float,
    breach_width_m: float,
    failure_time_s: float,
    **kwargs,
) -> dict[str, Path]:
    """Compute `synthetic_flood_maps` and write it as `summary/max_depth.tif`,
    `summary/max_velocity.tif`, `summary/arrival_time.tif` under `run_dir`,
    in the M3/M4 run-result schema (`docs/handoff_contract.md` §4.4). Returns
    the paths written, keyed by layer name."""
    maps = synthetic_flood_maps(grid, water_volume_m3, breach_width_m, failure_time_s, **kwargs)
    summary_dir = Path(run_dir) / "summary"
    summary_dir.mkdir(parents=True, exist_ok=True)
    return {
        "max_depth": write_grid_raster(summary_dir / "max_depth.tif", maps.max_depth_m, grid),
        "max_velocity": write_grid_raster(summary_dir / "max_velocity.tif", maps.max_velocity_ms, grid),
        "arrival_time": write_grid_raster(summary_dir / "arrival_time.tif", maps.arrival_time_s, grid),
    }
