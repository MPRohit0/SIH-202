"""`get_flood()` -- M5's answer to one flood query (`docs/m5_specs.md` §5),
in both modes:

- **scenario** (§5.1): the caller gives every input an exact value. One GP
  prediction, no Monte Carlo. Uncertainty is emulator uncertainty only --
  P10/P90 bands come from the GP's own per-cell Gaussian in transformed
  space, and `p_inundation` from that same Gaussian's analytic exceedance
  probability (`1 - Phi`), not from resampling.
- **unknown_breach** (§5.2): the caller fixes zero or more inputs; the rest
  are sampled from their ranges (`monte_carlo.sample_inputs`) and each
  sample draws its own GP realisation, so emulator and breach-parameter
  uncertainty are combined (`monte_carlo.run_monte_carlo`).

`get_flood()` returns a `FloodResult` (full-grid numpy arrays + POI/summary
numbers); `to_contract_response()` turns one into a dict that validates
against `contracts/schemas/flood_query_response.schema.json`
(`docs/handoff_contract.md` §5.4). Rendering those arrays to PNG and writing
them under `data/<site_id>/queries/<query_id>/` is M0's job
(`backend/m0_api/rendering.py`) -- `layers[].url` here is the contract's
well-formed path string, filled in without M0 having written that file yet.

Full-grid arrival time is available in both modes: scenario mode from the
GP's own per-cell Gaussian, unknown_breach mode from `monte_carlo`'s
per-cell arrival histogram (`mc.HISTOGRAM_OUTPUTS` includes `"arrival_time"`,
whose top bin is reserved for "never arrived within `t_end_s`" -- see
`monte_carlo.py`'s module docstring). In both modes, a cell's arrival at a
given band (median/P10/P90) is nodata unless that same band's depth actually
floods the cell -- see `_get_flood_scenario`/`_get_flood_unknown_breach`.

Not built here (later, M0/M2 sessions): resolving the request schema's
`{type: exact | slider}` input wrappers (needs a site config's
`emulator_inputs.slider.mapping`), pulling `m2_breach`'s dual-method ranges
directly (`ranges=` here defaults to the emulator's own trained design box --
see `monte_carlo.sample_inputs`), and `peak_discharge_m3s` (an M2 output, not
one this emulator predicts -- reported as an explicit placeholder, never
invented, per CLAUDE.md rule 3).
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from scipy.stats import norm

from backend.m5_emulator import confidence as conf
from backend.m5_emulator import monte_carlo as mc
from backend.m5_emulator.emulator import FloodEmulator, OUTPUT_KEYS, OUTPUT_SHORT_NAME, _corridor_indices
from backend.shared.grid import FLOAT_NODATA

CONTRACT_VERSION = "0.2.0"

#: docs/handoff_contract.md §1.5.
HIGH_P = 0.9
POSSIBLE_P = 0.1

#: docs/handoff_contract.md §3.3's fixed input-name list -> unit. Only the
#: three this emulator actually uses (`inputs.DEFAULT_SCALING`) have a known
#: unit here.
UNIT_BY_INPUT = {"water_volume_m3": "m3", "breach_width_m": "m", "failure_time_s": "s"}

#: z-scores for the two bands this module reports (both in transformed
#: space, back-transformed at the endpoints -- docs/m5_specs.md §5.1).
Z_P10_P90 = float(norm.ppf(0.9))

MODES = ("scenario", "unknown_breach")


def new_query_id() -> str:
    """`q_<YYYYMMDDTHHMMSSZ>_<6 hex>` (docs/handoff_contract.md §1.7)."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"q_{stamp}_{secrets.token_hex(3)}"


def _embed(emulator: FloodEmulator, corridor_values: np.ndarray, fill_value: float = 0.0) -> np.ndarray:
    """One output's corridor-cell array -> full-grid array, non-corridor
    cells filled with `fill_value` (mirrors `FloodEmulator._embed_and_clip`
    for arrays this module computes outside the emulator's own PCA/GP decode
    path, e.g. `p_inundation`)."""
    idx = _corridor_indices(emulator.corridor_mask)
    n_cells = emulator.grid.width * emulator.grid.height
    full = np.full(n_cells, fill_value, dtype=np.float32)
    full[idx] = corridor_values
    return full.reshape(emulator.grid.shape)


def _extent_class(p_inundation: np.ndarray, domain_mask: np.ndarray | None = None) -> np.ndarray:
    """uint8 0 dry / 1 POSSIBLE / 2 HIGH (docs/handoff_contract.md §1.5:
    `high_p`/`possible_p` thresholds on `p_inundation`)."""
    out = np.zeros(p_inundation.shape, dtype=np.uint8)
    out[p_inundation >= POSSIBLE_P] = 1
    out[p_inundation >= HIGH_P] = 2
    if domain_mask is not None:
        out[~domain_mask] = 0
    return out


# ============================================================================
# Per-output latent -> corridor decode helpers
# ============================================================================


def _corridor_p10_p90(emulator: FloodEmulator, latent_mean: dict, latent_std: dict) -> tuple[dict, dict]:
    """P10/P90 corridor-cell physical values per output, from one scenario's
    GP latent mean/std (docs/m5_specs.md §5.1's band, but at the P10/P90
    z-score the contract's `Estimate.interval` enum names, rather than the
    module-wide `EmulatorSettings.band_z` used internally for LOOCV/A2)."""
    p10, p90 = {}, {}
    for raw_name in OUTPUT_KEYS:
        oe = emulator.outputs[raw_name]
        mu_z = oe.pca.decode(latent_mean[raw_name].reshape(1, -1))[0]
        sigma_z = oe.pca.decode_std(latent_std[raw_name].reshape(1, -1))[0]
        lo = oe.transform.inverse(mu_z - Z_P10_P90 * sigma_z)
        hi = oe.transform.inverse(mu_z + Z_P10_P90 * sigma_z)
        p10[raw_name], p90[raw_name] = np.minimum(lo, hi), np.maximum(lo, hi)
    return p10, p90


def _p_inundation_scenario(emulator: FloodEmulator, latent_mean: dict, latent_std: dict) -> np.ndarray:
    """Analytic P(depth > extent_m) per corridor cell, from the GP's own
    Gaussian in transformed space -- exact, no resampling (scenario mode is
    "emulator uncertainty only", docs/m5_specs.md §5.1)."""
    oe = emulator.outputs["max_depth"]
    mu_z = oe.pca.decode(latent_mean["max_depth"].reshape(1, -1))[0]
    sigma_z = oe.pca.decode_std(latent_std["max_depth"].reshape(1, -1))[0]
    z_thresh = float(oe.transform.forward(np.array([emulator.settings.extent_m]))[0])
    sigma_safe = np.maximum(sigma_z, 1e-12)
    return 1.0 - norm.cdf((z_thresh - mu_z) / sigma_safe)


# ============================================================================
# Result
# ============================================================================


@dataclass
class FloodResult:
    """One `get_flood()` answer: full-grid arrays (raw_name/layer_id ->
    (height, width)) plus the scalar/POI numbers the contract's `summary`
    and `warning_table`-adjacent fields need."""

    site_id: str
    model: str
    mode: str
    resolved_inputs: dict[str, tuple[float, float, float]]  # name -> (value, low, high); low==high==value for fixed inputs
    p_inundation: np.ndarray
    extent_class: np.ndarray
    median: dict[str, np.ndarray]   # raw_name -> (height, width), max_depth/max_velocity/arrival_time
    p10: dict[str, np.ndarray]
    p90: dict[str, np.ndarray]
    poi_depth: dict[str, tuple[float, float, float]]     # name -> (median, p10, p90)
    poi_velocity: dict[str, tuple[float, float, float]]
    poi_arrival: dict[str, tuple[float, float, float] | None]  # None if the POI never arrived in-sample/in-scenario
    poi_p_inundation: dict[str, float]
    inundated_area_m2: tuple[float, float, float]
    max_depth_site: tuple[float, float, float]
    max_velocity_site: tuple[float, float, float]
    outside_trained_range: bool
    confidence: dict  # {"overall", "extent", "depth", "arrival", "velocity"}
    n_samples: int | None  # None in scenario mode


def get_flood(
    emulator: FloodEmulator,
    mode: str,
    inputs: dict[str, float],
    pois: dict[str, int],
    *,
    ranges: dict[str, tuple[float, float]] | None = None,
    n_samples: int = 2000,
    seed: int | None = 0,
    validation_skill: dict[str, str] | None = None,
    has_placeholder_inputs: bool = False,
) -> FloodResult:
    """`docs/m5_specs.md` §5. `inputs`: raw-unit values. In `scenario` mode
    every one of `emulator.input_scaler.specs`' names must be given (there is
    no per-site default table here -- that's a site-config concept, not
    built in M5). In `unknown_breach` mode, `inputs` instead *fixes* a subset
    (the request contract's "type: exact" inputs); anything not named is
    sampled (`monte_carlo.sample_inputs`). `pois`: name -> flattened
    full-grid cell index; every POI must be inside the trained corridor.
    `validation_skill`: optional real per-output LOOCV grade (GOOD/FAIR/POOR)
    from `loocv.build_report()`'s `summary.*.grade` -- omitted outputs (and
    the whole dict if not given) default to `"UNKNOWN"`
    (`docs/decisions.md`/`loocv.py`: depth and velocity have no defined LOOCV
    cut-off yet, so they are always `"UNKNOWN"`).
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    specs = emulator.input_scaler.specs
    input_names = [s.name for s in specs]
    validation_skill = validation_skill or {}
    skill_of = lambda output: validation_skill.get(output, "UNKNOWN")

    if mode == "scenario":
        missing = [n for n in input_names if n not in inputs]
        if missing:
            raise ValueError(f"scenario mode needs every input; missing {missing}")
        return _get_flood_scenario(emulator, inputs, pois, skill_of, has_placeholder_inputs)

    return _get_flood_unknown_breach(
        emulator, inputs, pois, ranges, n_samples, seed, skill_of, has_placeholder_inputs,
    )


def _get_flood_scenario(emulator, inputs, pois, skill_of, has_placeholder_inputs) -> FloodResult:
    specs = emulator.input_scaler.specs
    x_raw = np.array([inputs[s.name] for s in specs])
    predicted = emulator.predict(x_raw)

    p10, p90 = _corridor_p10_p90(emulator, predicted.latent_mean, predicted.latent_std)
    p_inund_corridor = _p_inundation_scenario(emulator, predicted.latent_mean, predicted.latent_std)
    p_inundation = _embed(emulator, p_inund_corridor, fill_value=0.0)
    extent_class = _extent_class(p_inundation)

    median = predicted.central
    p10_full = {name: _embed(emulator, p10[name], fill_value=(emulator.t_end_s if name == "arrival_time" else 0.0))
                for name in OUTPUT_KEYS}
    p90_full = {name: _embed(emulator, p90[name], fill_value=(emulator.t_end_s if name == "arrival_time" else 0.0))
                for name in OUTPUT_KEYS}
    # A cell's arrival time is only meaningful where that band's own depth
    # says the cell got wet -- median arrival is nodata where the median
    # never floods, P10 arrival (the fast/POSSIBLE tail) where the P90 depth
    # never floods, P90 arrival (the slow/HIGH tail) where the P10 depth
    # never floods (docs/handoff_contract.md §5.5: POSSIBLE cells outside the
    # median-flooded area still need an arrival estimate for the timeline).
    median["arrival_time"] = np.where(median["max_depth"] <= emulator.settings.arrival_m, FLOAT_NODATA, median["arrival_time"])
    p10_full["arrival_time"] = np.where(p90_full["max_depth"] <= emulator.settings.arrival_m, FLOAT_NODATA, p10_full["arrival_time"])
    p90_full["arrival_time"] = np.where(p10_full["max_depth"] <= emulator.settings.arrival_m, FLOAT_NODATA, p90_full["arrival_time"])

    corridor_idx = _corridor_indices(emulator.corridor_mask)
    flat_area = float((p_inund_corridor >= HIGH_P).sum() + ((p_inund_corridor >= POSSIBLE_P) & (p_inund_corridor < HIGH_P)).sum())
    area_m2 = flat_area * emulator.grid.cell_size_m ** 2
    # scenario mode has no sample distribution for area/site-max -- report the single deterministic value with interval "none"-like (low=high=value)
    inundated_area = (area_m2, area_m2, area_m2)
    max_depth_site = tuple([float(median["max_depth"].max())] * 3)
    max_velocity_site = tuple([float(median["max_velocity"].max())] * 3)

    poi_depth, poi_velocity, poi_arrival, poi_p = {}, {}, {}, {}
    for name, idx in pois.items():
        row, col = divmod(idx, emulator.grid.width)
        poi_depth[name] = (float(median["max_depth"][row, col]), float(p10_full["max_depth"][row, col]), float(p90_full["max_depth"][row, col]))
        poi_velocity[name] = (float(median["max_velocity"][row, col]), float(p10_full["max_velocity"][row, col]), float(p90_full["max_velocity"][row, col]))
        poi_p[name] = float(p_inundation[row, col])
        if median["arrival_time"][row, col] == FLOAT_NODATA:
            poi_arrival[name] = None
        else:
            poi_arrival[name] = (float(median["arrival_time"][row, col]), float(p10_full["arrival_time"][row, col]), float(p90_full["arrival_time"][row, col]))

    inside_box_all = all(predicted.inside_training_box.values())
    x_std = emulator.input_scaler.transform(x_raw)
    x_std_train = _training_points(emulator)
    coverage = conf.query_coverage_scenario(x_std, x_std_train, inside_box_all)

    extent_conf = conf.combine(skill_of("extent"), coverage, conf.spread_extent(_possible_fraction(p_inund_corridor)))
    depth_conf = conf.combine(skill_of("depth"), coverage, conf.spread_depth_or_velocity(*_lhc(poi_depth_or_site(poi_depth, max_depth_site))))
    velocity_conf = conf.combine(skill_of("velocity"), coverage, conf.spread_depth_or_velocity(*_lhc(poi_depth_or_site(poi_velocity, max_velocity_site))))
    arrival_conf = _arrival_confidence(skill_of, coverage, poi_arrival)
    for c in (extent_conf, depth_conf, arrival_conf, velocity_conf):
        if has_placeholder_inputs and c["level"] == "HIGH":
            c["level"], c["reason_key"] = "MODERATE", "conf_placeholder_inputs"
    per_output = {"extent": extent_conf, "depth": depth_conf, "arrival": arrival_conf, "velocity": velocity_conf}
    confidence = {"overall": conf.overall(per_output), **per_output}

    resolved = {s.name: (float(x_raw[i]), float(x_raw[i]), float(x_raw[i])) for i, s in enumerate(specs)}

    return FloodResult(
        site_id=emulator.site_id, model=emulator.model, mode="scenario", resolved_inputs=resolved,
        p_inundation=p_inundation, extent_class=extent_class,
        median=median, p10=p10_full, p90=p90_full,
        poi_depth=poi_depth, poi_velocity=poi_velocity, poi_arrival=poi_arrival, poi_p_inundation=poi_p,
        inundated_area_m2=inundated_area, max_depth_site=max_depth_site, max_velocity_site=max_velocity_site,
        outside_trained_range=not inside_box_all, confidence=confidence, n_samples=None,
    )


def _get_flood_unknown_breach(emulator, inputs, pois, ranges, n_samples, seed, skill_of, has_placeholder_inputs) -> FloodResult:
    result = mc.run_monte_carlo(emulator, n_samples, seed if seed is not None else 0, pois, ranges=ranges, fixed=inputs)

    p_inund_corridor = result.p_inundation()
    p_inundation = _embed(emulator, p_inund_corridor, fill_value=0.0)
    extent_class = _extent_class(p_inundation)

    median, p10_full, p90_full = {}, {}, {}
    for raw_name in mc.HISTOGRAM_OUTPUTS:
        hist = result.histograms[raw_name]
        fill = emulator.t_end_s if raw_name == "arrival_time" else 0.0
        median[raw_name] = _embed(emulator, hist.percentile(0.5), fill_value=fill)
        p10_full[raw_name] = _embed(emulator, hist.percentile(0.1), fill_value=fill)
        p90_full[raw_name] = _embed(emulator, hist.percentile(0.9), fill_value=fill)
    # The arrival histogram's top bin is reserved for "never arrived within
    # t_end_s" (monte_carlo.py); a percentile landing in roughly that bin's
    # range, or a cell whose matching depth band never floods, means nodata
    # -- not the arrival estimate implied by an arbitrary bin midpoint.
    # bin_width = t_end_s / (N_BINS - 1) (monte_carlo.py's arrival_bin_max); the
    # top bin is index N_BINS - 1, so its midpoint is (N_BINS - 0.5) * bin_width.
    never_arrived_from = (mc.N_BINS - 0.5) / (mc.N_BINS - 1) * emulator.t_end_s
    for full, depth_full in ((median, median), (p10_full, p90_full), (p90_full, p10_full)):
        never = (depth_full["max_depth"] <= emulator.settings.arrival_m) | (full["arrival_time"] >= never_arrived_from)
        full["arrival_time"] = np.where(never, FLOAT_NODATA, full["arrival_time"])

    def _pctl3(samples: np.ndarray) -> tuple[float, float, float]:
        if samples.size == 0:
            return (float("nan"),) * 3
        lo, med, hi = np.percentile(samples, [10, 50, 90])
        return float(med), float(lo), float(hi)

    inundated_area = _pctl3(result.inundated_area_m2_samples)
    max_depth_site = _pctl3(result.max_depth_samples)
    max_velocity_site = _pctl3(result.max_velocity_samples)

    poi_depth, poi_velocity, poi_arrival, poi_p = {}, {}, {}, {}
    for name, idx in pois.items():
        poi_depth[name] = _pctl3(result.poi_depth_samples[name])
        poi_velocity[name] = _pctl3(result.poi_velocity_samples[name])
        arr = result.poi_arrival_samples[name]
        poi_arrival[name] = _pctl3(arr) if arr.size else None
        row, col = divmod(idx, emulator.grid.width)
        poi_p[name] = float(p_inundation[row, col])

    coverage = conf.query_coverage_mc(result.fraction_inside_box())
    extent_conf = conf.combine(skill_of("extent"), coverage, conf.spread_extent(_possible_fraction(p_inund_corridor)))
    depth_conf = conf.combine(skill_of("depth"), coverage, conf.spread_depth_or_velocity(*_lhc(max_depth_site)))
    velocity_conf = conf.combine(skill_of("velocity"), coverage, conf.spread_depth_or_velocity(*_lhc(max_velocity_site)))
    arrival_conf = _arrival_confidence(skill_of, coverage, poi_arrival)
    for c in (extent_conf, depth_conf, arrival_conf, velocity_conf):
        if has_placeholder_inputs and c["level"] == "HIGH":
            c["level"], c["reason_key"] = "MODERATE", "conf_placeholder_inputs"
    per_output = {"extent": extent_conf, "depth": depth_conf, "arrival": arrival_conf, "velocity": velocity_conf}
    confidence = {"overall": conf.overall(per_output), **per_output}

    resolved = {}
    specs = emulator.input_scaler.specs
    for s in specs:
        if s.name in inputs:
            resolved[s.name] = (float(inputs[s.name]),) * 3
        else:
            lo, hi = (ranges or {}).get(s.name, (s.low, s.high))
            resolved[s.name] = ((lo + hi) / 2.0, lo, hi)

    return FloodResult(
        site_id=emulator.site_id, model=emulator.model, mode="unknown_breach", resolved_inputs=resolved,
        p_inundation=p_inundation, extent_class=extent_class,
        median=median, p10=p10_full, p90=p90_full,
        poi_depth=poi_depth, poi_velocity=poi_velocity, poi_arrival=poi_arrival, poi_p_inundation=poi_p,
        inundated_area_m2=inundated_area, max_depth_site=max_depth_site, max_velocity_site=max_velocity_site,
        outside_trained_range=result.fraction_inside_box() < 1.0, confidence=confidence, n_samples=n_samples,
    )


# ============================================================================
# Small shared helpers
# ============================================================================


def _training_points(emulator: FloodEmulator) -> np.ndarray:
    """The fitted GPs' own training inputs (standardised) -- `sklearn`
    stores them on the fitted estimator (`gp.X_train_`), so the design
    doesn't need to be persisted separately on `FloodEmulator` just for this."""
    any_output = next(iter(emulator.outputs.values()))
    return any_output.gps[0].gp.X_train_


def _possible_fraction(p_inundation_corridor: np.ndarray) -> float:
    flooded = p_inundation_corridor >= POSSIBLE_P
    if not flooded.any():
        return float("nan")
    possible = flooded & (p_inundation_corridor < HIGH_P)
    return float(possible.sum() / flooded.sum())


def poi_depth_or_site(poi_values: dict[str, tuple], site_value: tuple) -> tuple:
    """The headline (median, p10, p90) to grade spread on: the site-wide max
    if there are no POIs, else the POI with the largest median value (the
    one most likely to drive a warning)."""
    if not poi_values:
        return site_value
    return max(poi_values.values(), key=lambda t: t[0])


def _lhc(med_lo_hi: tuple) -> tuple:
    """(median, low, high) -> (low, central, high), the argument order
    `confidence.spread_*` takes."""
    med, lo, hi = med_lo_hi
    return (lo, med, hi)


def _arrival_confidence(skill_of, coverage: str, poi_arrival: dict) -> dict:
    arrived = [v for v in poi_arrival.values() if v is not None]
    if not arrived:
        spread = "WIDE"  # nothing arrived anywhere sampled -- can't call this a narrow answer
    else:
        med, lo, hi = min(arrived, key=lambda t: t[0])  # the earliest POI to arrive drives the warning
        spread = conf.spread_arrival(lo, med, hi)
    return conf.combine(skill_of("arrival"), coverage, spread)


# ============================================================================
# Contract response (docs/handoff_contract.md §5.4)
# ============================================================================


def _estimate(value: float, low: float, high: float, unit: str | None, *, kind: str = "predicted",
              interval: str = "P10-P90", confidence: str | None = None, basis: str | None = None) -> dict:
    d = {"value": value, "low": low, "high": high, "unit": unit, "interval": interval, "kind": kind}
    if confidence is not None:
        d["confidence"] = confidence
    if basis is not None:
        d["basis"] = basis
    return d


def _layer(layer_id: str, query_id: str, style_id: str, unit: str | None, bounds_latlng: list) -> dict:
    return {
        "layer_id": layer_id, "type": "raster_png",
        "url": f"/api/v1/flood/{query_id}/layers/{layer_id}.png",
        "bounds_latlng": bounds_latlng, "style_id": style_id, "unit": unit, "available": True,
    }


def to_contract_response(
    result: FloodResult, emulator: FloodEmulator, *,
    query_id: str | None = None, timing_ms: dict | None = None, caveats: list[dict] | None = None,
    demo_mode: bool = False, library_outdated: bool = False, has_placeholder_inputs: bool = False,
) -> dict:
    """`result` -> a dict matching `flood_query_response.schema.json`
    (docs/handoff_contract.md §5.4). `peak_discharge_m3s` is genuinely not
    computed here (see module docstring) -- reported as a null-valued
    Estimate and listed in `placeholder_fields`, never invented (CLAUDE.md
    rule 3)."""
    query_id = query_id or new_query_id()
    bounds = emulator.grid.bounds_latlng

    resolved_inputs = {
        name: _estimate(v, lo, hi, UNIT_BY_INPUT.get(name), kind="input",
                        interval="none" if lo == hi else "method_range")
        for name, (v, lo, hi) in result.resolved_inputs.items()
    }

    area_med, area_lo, area_hi = result.inundated_area_m2
    depth_med, depth_lo, depth_hi = result.max_depth_site
    vel_med, vel_lo, vel_hi = result.max_velocity_site

    if result.poi_arrival:
        first_name, first = min(
            ((n, v) for n, v in result.poi_arrival.items() if v is not None), default=(None, None), key=lambda nv: nv[1][0],
        )
    else:
        first_name, first = None, None

    summary = {
        "inundated_area_m2": _estimate(area_med, area_lo, area_hi, "m2", confidence=result.confidence["extent"]["level"]),
        "max_depth_m": _estimate(depth_med, depth_lo, depth_hi, "m", confidence=result.confidence["depth"]["level"]),
        "max_velocity_ms": _estimate(vel_med, vel_lo, vel_hi, "ms", confidence=result.confidence["velocity"]["level"]),
        "peak_discharge_m3s": _estimate(None, None, None, "m3s", interval="none",
                                         basis="not computed by M5 -- an M2 (backend.m2_breach) output"),
        "first_arrival": {
            "poi_id": f"{result.site_id}__poi__{first_name}" if first_name else None,
            "name": first_name,
            "arrival_s": (_estimate(first[0], first[1], first[2], "s", confidence=result.confidence["arrival"]["level"])
                          if first is not None else _estimate(None, None, None, "s", interval="none")),
        },
    }

    layers = [
        _layer("p_inundation", query_id, "p_inundation", None, bounds),
        _layer("extent_class", query_id, "extent_class", None, bounds),
    ]
    for raw_name in OUTPUT_KEYS:
        short = OUTPUT_SHORT_NAME[raw_name]
        unit = {"max_depth": "m", "max_velocity": "ms", "arrival_time": "s"}[raw_name]
        layers.append(_layer(f"{short}_p50", query_id, f"{short}_p50", unit, bounds))
        layers.append(_layer(f"{short}_p10", query_id, f"{short}_p50", unit, bounds))
        layers.append(_layer(f"{short}_p90", query_id, f"{short}_p50", unit, bounds))

    placeholder_fields = ["summary.peak_discharge_m3s"]
    if has_placeholder_inputs:
        placeholder_fields.append("resolved_inputs")

    caveats = list(caveats or [])
    caveats.append({"id": "clear_water", "severity": "warning", "text_key": "caveat_clear_water"})
    if result.outside_trained_range:
        caveats.append({"id": "outside_trained_range", "severity": "warning", "text_key": "caveat_outside_trained_range"})

    provenance = {
        "method": "gp_emulator", "contract_version": CONTRACT_VERSION,
        "parameters": {"mode": result.mode, "n_samples": result.n_samples},
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    return {
        "contract_version": CONTRACT_VERSION,
        "query_id": query_id, "site_id": result.site_id, "status": "complete", "method": "gp_emulator",
        "mode": result.mode, "resolved_inputs": resolved_inputs, "summary": summary,
        "confidence": result.confidence, "layers": layers,
        "vectors": {"extent_url": f"/api/v1/flood/{query_id}/extent.geojson"},
        "flags": {
            "outside_trained_range": result.outside_trained_range, "demo_mode": demo_mode,
            "library_outdated": library_outdated, "has_placeholders": True,
        },
        "placeholder_fields": placeholder_fields, "caveats": caveats, "provenance": provenance,
        "timing_ms": timing_ms or {"median_phase": 0, "full_phase": 0},
    }
