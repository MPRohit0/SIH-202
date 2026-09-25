"""A synthetic training library for the M5 emulator's own tests
(`docs/m5_specs.md` §2: "maximin Latin hypercube over the 3 inputs").

This stands in for the real pipeline ("M5 -> M0, M3, M4",
`docs/handoff_contract.md` §4.3, `design/scenario_design.json`) that will
run the actual Delft3D/DualSPHysics campaign. It exists only so
`emulator.py` has something to fit and test against before real runs exist;
it does not write the contract's `scenario_design.json`, and its `run_id`s
and `model: "synthetic"` are outside the contract's ID/model patterns
(`docs/handoff_contract.md` §1.7) — never write them into `data/`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import qmc

from backend.m5_emulator import synthetic as sw
from backend.m5_emulator.inputs import DEFAULT_SCALING
from backend.shared.grid import CanonicalGrid, FLOAT_NODATA

INPUT_ORDER = ("water_volume_m3", "breach_width_m", "failure_time_s")


def maximin_lhs(n: int, d: int, seed: int, n_candidates: int = 200) -> np.ndarray:
    """`n` points in [0, 1)^d from the candidate (of `n_candidates`
    independent LHS draws) with the largest minimum pairwise distance
    (docs/m5_specs.md §2: "maximin avoids clumps that LHS alone can
    produce"). Deterministic given `seed`.
    """
    rng = np.random.default_rng(seed)
    best_sample = None
    best_min_dist = -np.inf
    for _ in range(n_candidates):
        sampler = qmc.LatinHypercube(d=d, seed=rng)
        sample = sampler.random(n)
        dists = np.linalg.norm(sample[:, None, :] - sample[None, :, :], axis=-1)
        np.fill_diagonal(dists, np.inf)
        min_dist = dists.min()
        if min_dist > best_min_dist:
            best_min_dist = min_dist
            best_sample = sample
    return best_sample


def _widen(low: float, high: float, scaling: str, fraction: float = 0.2) -> tuple[float, float]:
    """Widen [low, high] by `fraction` on each side (docs/m5_specs.md §2:
    "widened by 20% on each side"). For a log10-scaled input (`water_volume_m3`,
    which spans orders of magnitude) the widening is done in log space, so a
    plain 20% of the raw span can't push the lower bound negative or make
    the widening physically meaningless at the low end.

    For a linear-scaled input, spec §2 assumes M2's real (comparatively
    narrow) pair bounds. `synthetic.DEFAULT_INPUT_RANGES` spans nearly an
    order of magnitude for `failure_time_s`/`breach_width_m`, so a naive 20%
    of that wide a span can push the lower bound to or past zero (e.g.
    failure_time_s 300-10800 -> -1800). Clamp instead of letting a physical
    quantity go non-positive.
    """
    if scaling == "log10":
        log_lo, log_hi = np.log10(low), np.log10(high)
        span = log_hi - log_lo
        return 10 ** (log_lo - fraction * span), 10 ** (log_hi + fraction * span)
    span = high - low
    lo, hi = low - fraction * span, high + fraction * span
    if lo <= 0:
        lo = low * 0.5
    return lo, hi


@dataclass(frozen=True)
class SyntheticLibrary:
    """A trained-and-tested-against synthetic scenario library: raw inputs
    `X_raw` (N x 3, columns `INPUT_ORDER`), the three map stacks (each
    N x n_cells, flattened row-major to match `grid.shape`), `run_ids`,
    `grid` and `t_end_s`."""

    X_raw: np.ndarray
    max_depth: np.ndarray
    max_velocity: np.ndarray
    arrival_time: np.ndarray
    run_ids: list[str]
    grid: CanonicalGrid
    t_end_s: float


def build_synthetic_library(
    grid: CanonicalGrid,
    n: int = 30,
    seed: int = 42,
    ranges: dict[str, tuple[float, float]] | None = None,
    widen_fraction: float = 0.2,
    run_prefix: str = "m5synth",
) -> SyntheticLibrary:
    """Build an N-run synthetic training library: a maximin-LHS design over
    `ranges` (default `synthetic.DEFAULT_INPUT_RANGES`, widened by
    `widen_fraction` — docs/m5_specs.md §2), each point evaluated with
    `synthetic.synthetic_flood_maps`.

    `t_end_s` (the fill value for dry arrival cells, standing in for a real
    run's `run_meta.json.sim_duration_s`) is the library's maximum finite
    arrival time, rounded up to the next hour — long enough that every
    training run's flood has clearly passed.
    """
    ranges = ranges or sw.DEFAULT_INPUT_RANGES
    widened = {name: _widen(*ranges[name], DEFAULT_SCALING[name], widen_fraction) for name in INPUT_ORDER}

    unit = maximin_lhs(n, len(INPUT_ORDER), seed=seed)  # (n, 3) in [0, 1)
    X_raw = np.empty((n, len(INPUT_ORDER)))
    for i, name in enumerate(INPUT_ORDER):
        lo, hi = widened[name]
        if name == "water_volume_m3":
            X_raw[:, i] = 10 ** (np.log10(lo) + unit[:, i] * (np.log10(hi) - np.log10(lo)))
        else:
            X_raw[:, i] = lo + unit[:, i] * (hi - lo)

    n_cells = grid.width * grid.height
    depth_stack = np.empty((n, n_cells), dtype=np.float32)
    velocity_stack = np.empty((n, n_cells), dtype=np.float32)
    arrival_stack = np.empty((n, n_cells), dtype=np.float32)
    run_ids = []
    for i in range(n):
        maps = sw.synthetic_flood_maps(
            grid,
            water_volume_m3=float(X_raw[i, 0]),
            breach_width_m=float(X_raw[i, 1]),
            failure_time_s=float(X_raw[i, 2]),
        )
        depth_stack[i] = maps.max_depth_m.reshape(-1)
        velocity_stack[i] = maps.max_velocity_ms.reshape(-1)
        arrival_stack[i] = maps.arrival_time_s.reshape(-1)
        run_ids.append(f"{run_prefix}_s{i + 1:03d}__synthetic")

    finite_arrivals = arrival_stack[arrival_stack != FLOAT_NODATA]
    max_arrival = float(finite_arrivals.max()) if finite_arrivals.size else 3600.0
    t_end_s = float(np.ceil(max_arrival / 3600.0) * 3600.0)

    return SyntheticLibrary(
        X_raw=X_raw,
        max_depth=depth_stack,
        max_velocity=velocity_stack,
        arrival_time=arrival_stack,
        run_ids=run_ids,
        grid=grid,
        t_end_s=t_end_s,
    )
