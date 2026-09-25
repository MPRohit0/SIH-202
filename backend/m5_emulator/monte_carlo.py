"""Unknown-breach-mode Monte Carlo (`docs/m5_specs.md` §5.2-§5.3): sample
breach parameters from their ranges, push each sample through the GP (which
adds its own `z_j ~ N(mu_j, sigma_j^2)` draw per component -- spec: "emulator
and breach uncertainty are combined"), and accumulate per-cell statistics in
fixed-size running structures so no `(n_samples, n_cells)` array is ever held
in memory at once (CLAUDE.md rule 13; spec §5.3: "process Monte Carlo samples
in chunks").

Two kinds of output need different accumulators:

- **Full-grid** depth/velocity/arrival (`p_inundation`, `depth_p10/p50/p90`,
  `velocity_p10/p50/p90`, `arrival_p10/p50/p90`): a fixed-count exceedance
  counter (for `p_inundation`) and a per-cell 64-bin histogram (for
  percentiles) -- spec §5.3's own design. Depth/velocity bin edges are fixed
  once, per cell, from `confidence.per_cell_upper_bound` (a GP-based bound
  over the whole trained box), not adapted per query -- a query near the
  middle of the trained box wastes some histogram resolution, but the bins
  never need to change size mid-run, which keeps the accumulator a single
  fixed-shape array. Arrival's bin edges instead run `[0, t_end_s * 64/63)`
  so the top bin is reserved for "never arrived within the run" (a sample
  whose depth never exceeds `settings.arrival_m` is recorded as exactly
  `t_end_s`, per docs/m5_specs.md §5.5's timeline semantics) -- this trades
  the last bin's resolution (`t_end_s/63`) for a histogram that can tell
  "arrives very late" from "doesn't arrive" without a second accumulator.
- **Scalars** (site-wide max depth/velocity, inundated area, and every
  point-of-interest's depth/velocity/arrival): spec §5.3 "store every
  sample" -- these are only `n_samples` floats each, cheap to keep exactly
  and give exact (not histogram-approximated) percentiles. POI arrival stays
  exact-sample (not histogram) because there are only ever a handful of POIs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from backend.m5_emulator import confidence as conf
from backend.m5_emulator.emulator import FloodEmulator, OUTPUT_KEYS, _corridor_indices
from backend.m5_emulator.gp import predict_components
from backend.m5_emulator.inputs import InputSpec

N_BINS = 64
# 2 GB, decimal (docs/m5_specs.md §5.3's own worked example -- "1M masked
# cells x 3 maps -> 166 samples per chunk" -- only comes out to 166 with a
# decimal, not binary (2*1024**3), 2 GB).
DEFAULT_CHUNK_BYTES_BUDGET = 2 * 10**9
CHUNK_SIZE_BOUNDS = (16, 500)  # spec §5.3
HISTOGRAM_OUTPUTS = ("max_depth", "max_velocity", "arrival_time")  # the full-grid histogram outputs


# ============================================================================
# Sampling (docs/m5_specs.md §5.2)
# ============================================================================


def sample_inputs(
    specs: list[InputSpec],
    n: int,
    rng: np.random.Generator,
    ranges: dict[str, tuple[float, float]] | None = None,
    fixed: dict[str, float] | None = None,
) -> np.ndarray:
    """`n` raw-unit samples (n x len(specs), columns in `specs` order).

    docs/m5_specs.md §5.2: "V_w: log-uniform over its sourced range ...
    B_ave, T_f: uniform between the low and high [range] values". `ranges`
    overrides a spec's own (`specs[i].low`, `specs[i].high`) bounds -- the
    default is the emulator's trained design box (widened M2 pair bounds,
    `docs/m5_specs.md` §2), used when the caller has no separate, unwidened
    M2 range to sample from. `fixed` pins one or more named inputs to an
    exact value instead of sampling them (request contract §5.4: "type:
    exact" inputs in `unknown_breach` mode).
    """
    ranges = ranges or {}
    fixed = fixed or {}
    X = np.empty((n, len(specs)))
    for i, s in enumerate(specs):
        if s.name in fixed:
            X[:, i] = fixed[s.name]
            continue
        lo, hi = ranges.get(s.name, (s.low, s.high))
        if s.scaling == "log10":
            X[:, i] = 10 ** rng.uniform(np.log10(lo), np.log10(hi), size=n)
        else:
            X[:, i] = rng.uniform(lo, hi, size=n)
    return X


def chunk_size_for(n_corridor_cells: int, n_maps: int = len(HISTOGRAM_OUTPUTS),
                    budget_bytes: int = DEFAULT_CHUNK_BYTES_BUDGET) -> int:
    """docs/m5_specs.md §5.3: `floor(budget / (n_cells * 4B * n_maps))`,
    clamped to [16, 500]. `n_cells` here is the corridor cell count (the only
    per-sample arrays ever held are corridor-sized, per this module's
    docstring), and `n_maps` defaults to the two full-grid histogram outputs
    (depth, velocity)."""
    if n_corridor_cells <= 0:
        return CHUNK_SIZE_BOUNDS[1]
    raw = budget_bytes // (n_corridor_cells * 4 * n_maps)
    return int(np.clip(raw, *CHUNK_SIZE_BOUNDS))


# ============================================================================
# Per-cell histogram accumulator (docs/m5_specs.md §5.3)
# ============================================================================


@dataclass
class CellHistogram:
    """A 64-bin histogram per corridor cell, bins `[0, bin_max[cell]]`
    (docs/m5_specs.md §5.3: "per-cell 64-bin histograms (percentiles)")."""

    bin_max: np.ndarray  # (n_corridor,) float64, > 0
    counts: np.ndarray = field(init=False)  # (n_corridor, N_BINS) uint32
    n: int = 0

    def __post_init__(self) -> None:
        n_corridor = self.bin_max.shape[0]
        self.counts = np.zeros((n_corridor, N_BINS), dtype=np.uint32)
        # int32 throughout (not the numpy default int64): halves the memory
        # traffic of the flattened (cell, bin) index below, which dominates
        # this class's cost at real corridor sizes (tens of thousands of
        # cells) -- n_corridor * N_BINS comfortably fits int32 for any grid
        # this project's canonical grids use.
        self._bin_width = (self.bin_max / N_BINS).astype(np.float32)
        self._cell_offset = (np.arange(n_corridor, dtype=np.int32) * N_BINS)[None, :]

    def add(self, values: np.ndarray) -> None:
        """`values`: (chunk, n_corridor) physical values >= 0. One
        `np.bincount` over a flattened (cell, bin) index, rather than a
        64-iteration loop over bins -- the loop was the dominant cost of a
        Monte Carlo run at real corridor sizes."""
        n_corridor = self.bin_max.shape[0]
        idx = np.clip((values / self._bin_width).astype(np.int32), 0, N_BINS - 1)  # (chunk, n_corridor)
        flat = (self._cell_offset + idx).ravel()
        counts_flat = np.bincount(flat, minlength=n_corridor * N_BINS)
        self.counts += counts_flat.reshape(n_corridor, N_BINS).astype(np.uint32)
        self.n += values.shape[0]

    def percentile(self, pct: float) -> np.ndarray:
        """Per-cell approximate percentile (0 < pct < 1), linearly
        interpolated within its bin."""
        if self.n == 0:
            return np.zeros(self.bin_max.shape[0])
        target = pct * self.n
        cum = np.cumsum(self.counts, axis=1)
        bin_idx = np.clip(np.sum(cum < target, axis=1), 0, N_BINS - 1)
        lower_cum = np.where(bin_idx > 0, np.take_along_axis(cum, np.clip(bin_idx - 1, 0, None)[:, None], axis=1)[:, 0], 0)
        count_in_bin = np.take_along_axis(self.counts, bin_idx[:, None], axis=1)[:, 0].astype(np.float64)
        frac = np.where(count_in_bin > 0, (target - lower_cum) / count_in_bin, 0.0)
        bin_width = self.bin_max / N_BINS
        return bin_idx * bin_width + frac * bin_width


# ============================================================================
# Full run
# ============================================================================


@dataclass
class MonteCarloResult:
    """Accumulated Monte Carlo output, all in corridor-cell space except the
    `poi_*`/`*_samples` scalars. `n_samples`, `n_inside_box` feed the C
    (query coverage) confidence check (`confidence.query_coverage_mc`)."""

    n_samples: int
    n_inside_box: int
    exceed_count: np.ndarray  # (n_corridor,) int -- samples with depth > extent_m
    histograms: dict[str, CellHistogram]  # raw_name -> histogram, for HISTOGRAM_OUTPUTS
    max_depth_samples: np.ndarray  # (n_samples,) site-wide max depth per sample
    max_velocity_samples: np.ndarray
    inundated_area_m2_samples: np.ndarray
    poi_depth_samples: dict[str, np.ndarray]  # poi name -> (n_samples,)
    poi_velocity_samples: dict[str, np.ndarray]
    poi_arrival_samples: dict[str, np.ndarray]  # only entries where the sample actually arrived (may be shorter than n_samples)

    def p_inundation(self) -> np.ndarray:
        """(n_corridor,) fraction of samples with depth > `extent_m`."""
        return self.exceed_count / self.n_samples

    def fraction_inside_box(self) -> float:
        return self.n_inside_box / self.n_samples


def run_monte_carlo(
    emulator: FloodEmulator,
    n_samples: int,
    seed: int,
    pois: dict[str, int],
    ranges: dict[str, tuple[float, float]] | None = None,
    fixed: dict[str, float] | None = None,
    cell_area_m2: float | None = None,
) -> MonteCarloResult:
    """Run `n_samples` unknown-breach draws in memory-bounded chunks
    (docs/m5_specs.md §5.2-§5.3). `pois`: name -> flattened *full-grid* cell
    index (e.g. `synthetic.poi_cell_index`); every POI must fall inside the
    emulator's corridor mask (raise `ValueError` otherwise -- a POI the
    training runs never wet can't be given an honest prediction)."""
    if n_samples <= 0:
        raise ValueError(f"n_samples must be > 0, got {n_samples!r}")
    cell_area_m2 = cell_area_m2 if cell_area_m2 is not None else emulator.grid.cell_size_m ** 2

    corridor_idx = _corridor_indices(emulator.corridor_mask)
    corridor_position = {int(full_idx): pos for pos, full_idx in enumerate(corridor_idx)}
    poi_pos: dict[str, int] = {}
    for name, full_idx in pois.items():
        if int(full_idx) not in corridor_position:
            raise ValueError(f"point of interest '{name}' (cell {full_idx}) is outside the trained corridor mask")
        poi_pos[name] = corridor_position[int(full_idx)]

    specs = emulator.input_scaler.specs
    rng = np.random.default_rng(seed)
    X_raw = sample_inputs(specs, n_samples, rng, ranges=ranges, fixed=fixed)
    inside = emulator.input_scaler.inside_training_box(X_raw)
    n_inside_box = int(inside.all(axis=1).sum())
    X_std = emulator.input_scaler.transform(X_raw)

    n_corridor = corridor_idx.shape[0]
    chunk = chunk_size_for(n_corridor)

    arrival_bin_max = np.full(n_corridor, emulator.t_end_s * N_BINS / (N_BINS - 1))
    histograms = {
        name: CellHistogram(bin_max=arrival_bin_max if name == "arrival_time" else conf.per_cell_upper_bound(emulator, name))
        for name in HISTOGRAM_OUTPUTS
    }
    exceed_count = np.zeros(n_corridor, dtype=np.int64)

    max_depth_samples = np.empty(n_samples)
    max_velocity_samples = np.empty(n_samples)
    inundated_area_samples = np.empty(n_samples)
    poi_depth_samples = {name: np.empty(n_samples) for name in pois}
    poi_velocity_samples = {name: np.empty(n_samples) for name in pois}
    poi_arrival_lists: dict[str, list[float]] = {name: [] for name in pois}

    rng_draw = np.random.default_rng(seed + 1)  # separate stream for the GP's own z_j draws

    for start in range(0, n_samples, chunk):
        end = min(start + chunk, n_samples)
        Xc = X_std[start:end]
        m = end - start

        physical: dict[str, np.ndarray] = {}
        for raw_name in OUTPUT_KEYS:
            oe = emulator.outputs[raw_name]
            mu, sigma = predict_components(oe.gps, Xc)  # (m, n_components)
            z = rng_draw.standard_normal(size=mu.shape)
            scores = mu + sigma * z  # spec §5.2: "z_j ~ N(mu_j, sigma_j^2)"
            Z = oe.pca.decode(scores)  # (m, n_corridor)
            phys = oe.transform.inverse(Z)
            if raw_name != "arrival_time":
                phys = np.clip(phys, 0.0, None)
            else:
                phys = np.clip(phys, 0.0, emulator.t_end_s)
            physical[raw_name] = phys

        depth_chunk = physical["max_depth"]
        velocity_chunk = physical["max_velocity"]
        arrival_chunk = physical["arrival_time"]

        exceed_count += (depth_chunk > emulator.settings.extent_m).sum(axis=0)
        histograms["max_depth"].add(depth_chunk)
        histograms["max_velocity"].add(velocity_chunk)
        arrived_mask = depth_chunk > emulator.settings.arrival_m
        histograms["arrival_time"].add(np.where(arrived_mask, arrival_chunk, emulator.t_end_s))

        max_depth_samples[start:end] = depth_chunk.max(axis=1)
        max_velocity_samples[start:end] = velocity_chunk.max(axis=1)
        inundated_area_samples[start:end] = (depth_chunk > emulator.settings.extent_m).sum(axis=1) * cell_area_m2

        for name, pos in poi_pos.items():
            poi_depth_samples[name][start:end] = depth_chunk[:, pos]
            poi_velocity_samples[name][start:end] = velocity_chunk[:, pos]
            arrived = depth_chunk[:, pos] > emulator.settings.arrival_m
            poi_arrival_lists[name].extend(arrival_chunk[arrived, pos].tolist())

    poi_arrival_samples = {name: np.asarray(vals) for name, vals in poi_arrival_lists.items()}

    return MonteCarloResult(
        n_samples=n_samples, n_inside_box=n_inside_box, exceed_count=exceed_count, histograms=histograms,
        max_depth_samples=max_depth_samples, max_velocity_samples=max_velocity_samples,
        inundated_area_m2_samples=inundated_area_samples,
        poi_depth_samples=poi_depth_samples, poi_velocity_samples=poi_velocity_samples,
        poi_arrival_samples=poi_arrival_samples,
    )
