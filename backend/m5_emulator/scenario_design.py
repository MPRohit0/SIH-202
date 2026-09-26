"""Real `design/scenario_design.json` generator (docs/handoff_contract.md §4.3,
M5 -> M0, M3, M4). Unlike `library.py` (a synthetic-only stand-in for
`emulator.py`'s own tests), this builds the actual maximin-LHS training design
from a site's real M2 breach-parameter ranges (docs/m5_specs.md §2).

Only `breach_width_m` and `failure_time_s` vary across the design: M2 computes
a low/high pair range for these (`backend/m2_breach/ranges.py`'s `PAIRS`), but
not for `water_volume_m3` -- that's a physical *input* to M2's equations
(`dam.breach_inputs.water_volume_above_invert`), not one of its ranged
outputs, so there is no "M2 pair" to widen. `water_volume_m3` is instead held
fixed at the site config's own value for every scenario in the design (team
decision, this session -- docs/m5_specs.md §1 loosely calls all three
emulator inputs "breach outputs M2 produces", which is imprecise for V_w).

If a required range is blocked (e.g. `breach_width_m`'s pair needs XZ9, which
is itself blocked pending `h_r` -- docs/Equations.md §1.2/§2.3), this module
raises `ScenarioDesignBlockedError` rather than inventing a range (CLAUDE.md
rule 3; `docs/decisions.md` "never guess").
"""

from __future__ import annotations

import json
from dataclasses import dataclass, fields, replace
from pathlib import Path

import numpy as np
import yaml

from backend.m2_breach.breach_params import compute_dam
from backend.m5_emulator.inputs import DEFAULT_SCALING
from backend.m5_emulator.library import maximin_lhs, _widen
from backend.shared.site_config import Dam, SiteConfig

DEFAULT_SETTINGS_PATH = Path(__file__).resolve().parents[2] / "config" / "m5_scenario_design.yaml"
CONTRACT_VERSION = "0.2.0"

#: Emulator inputs with an M2-computed range (`backend.m2_breach.ranges.PAIRS`
#: minus `peak_discharge_m3s`, which isn't one of the emulator's 3 inputs,
#: docs/m5_specs.md §1 / backend/m5_emulator/inputs.py).
RANGED_INPUTS = ("breach_width_m", "failure_time_s")

_UNIT = {"breach_width_m": "m", "failure_time_s": "s"}


class ScenarioDesignBlockedError(Exception):
    """A required M2 breach-parameter range (or the fixed water_volume_m3
    input) is blocked or missing. Raised instead of guessing a value."""

    def __init__(self, dam_id: str, param: str, reason: str):
        super().__init__(f"dam '{dam_id}': {param} is blocked: {reason}")
        self.dam_id = dam_id
        self.param = param
        self.reason = reason


@dataclass(frozen=True)
class ScenarioDesignSettings:
    n: int = 30
    n_holdout: int = 5
    seed: int = 42
    input_widen_fraction: float = 0.20
    method: str = "maximin_lhs"

    def __post_init__(self) -> None:
        if self.n < 1:
            raise ValueError(f"n must be >= 1, got {self.n}")
        if self.n_holdout < 0:
            raise ValueError(f"n_holdout must be >= 0, got {self.n_holdout}")
        if not 0.0 <= self.input_widen_fraction < 1.0:
            raise ValueError(f"input_widen_fraction must be in [0, 1), got {self.input_widen_fraction}")
        if self.method != "maximin_lhs":
            raise ValueError(f"unknown method {self.method!r}")


def load_scenario_design_settings(path: str | Path | None = None, **overrides) -> ScenarioDesignSettings:
    """Load `config/m5_scenario_design.yaml` (or `path`), applying any keyword overrides on top."""
    path = Path(path) if path is not None else DEFAULT_SETTINGS_PATH
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    known = {f.name for f in fields(ScenarioDesignSettings)}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"{path}: unknown setting(s): {', '.join(sorted(unknown))}")
    settings = ScenarioDesignSettings(**raw)
    return replace(settings, **overrides) if overrides else settings


def _m2_ranges(dam: Dam) -> dict[str, tuple[float, float]]:
    """M2's computed low/high pair range for each of `RANGED_INPUTS`.

    Raises `ScenarioDesignBlockedError` naming the first blocked input rather
    than a generic KeyError, so a caller (or a human reading the traceback)
    sees exactly which M2 output is blocked and why.
    """
    entry = compute_dam(dam)
    ranges: dict[str, tuple[float, float]] = {}
    for name in RANGED_INPUTS:
        param = entry["parameters"][name]
        if param.get("status") == "blocked":
            raise ScenarioDesignBlockedError(dam.id, name, param["reason"])
        ranges[name] = (param["low"], param["high"])
    return ranges


def _scenario_id(site_id: str, kind: str, index: int) -> str:
    """docs/decisions.md "ID naming scheme". `held_out` isn't one of the four
    documented kinds (design | demo | historical | named extra) -- it's
    written using the `__n_<slug>` named-extra shape, `kind: "held_out"`
    distinguishing it in the payload (this module's own choice)."""
    if kind == "design":
        return f"{site_id}__s{index:03d}"
    if kind == "held_out":
        return f"{site_id}__n_holdout{index:03d}"
    raise ValueError(f"unknown kind {kind!r}")


def _lhs_params(unit_row: np.ndarray, widened: dict[str, tuple[float, float]],
                 water_volume_m3: float) -> dict[str, float]:
    params = {"water_volume_m3": water_volume_m3}
    for j, name in enumerate(RANGED_INPUTS):
        lo, hi = widened[name]
        if DEFAULT_SCALING[name] == "log10":
            value = 10 ** (np.log10(lo) + unit_row[j] * (np.log10(hi) - np.log10(lo)))
        else:
            value = lo + unit_row[j] * (hi - lo)
        params[name] = float(value)
    return params


def design_from_ranges(site_id: str, dam_id: str, water_volume_m3: float,
                        ranges: dict[str, tuple[float, float]], caveats: list[str],
                        settings: ScenarioDesignSettings) -> dict:
    """Build the contract's `design/scenario_design.json` payload (§4.3) from
    already-resolved `ranges` (`{"breach_width_m": (low, high), "failure_time_s": (low, high)}`,
    M2's raw pair range, not yet widened). Pure function, independent of
    `SiteConfig`/M2, so the LHS/writing logic is testable without going
    through M2's equations (`breach_width_m`'s M2 range is blocked for every
    real site today -- XZ9 pending `h_r`, docs/Equations.md §1.2/§2.3 -- so
    `build_scenario_design` below can never reach a happy path yet)."""
    widened = {
        name: _widen(*ranges[name], DEFAULT_SCALING[name], settings.input_widen_fraction)
        for name in RANGED_INPUTS
    }

    def _make(n: int, kind: str, seed: int) -> list[dict]:
        if n == 0:
            return []
        unit = maximin_lhs(n, len(RANGED_INPUTS), seed=seed)
        return [
            {
                "scenario_id": _scenario_id(site_id, kind, i + 1),
                "kind": kind,
                "params": _lhs_params(unit[i], widened, water_volume_m3),
            }
            for i in range(n)
        ]

    scenarios = _make(settings.n, "design", settings.seed)
    extra = _make(settings.n_holdout, "held_out", settings.seed + 1)

    return {
        "contract_version": CONTRACT_VERSION,
        "site_id": site_id,
        "model": "delft3d",
        "method": settings.method,
        "seed": settings.seed,
        "n": settings.n,
        "inputs": [
            {"name": name, "dam_id": dam_id, "low": widened[name][0], "high": widened[name][1],
             "unit": _UNIT[name]}
            for name in RANGED_INPUTS
        ],
        "scenarios": scenarios,
        "extra": extra,
        "has_placeholders": True,
        "caveats": caveats,
    }


def build_scenario_design(cfg: SiteConfig, dam_id: str,
                           settings: ScenarioDesignSettings | None = None) -> dict:
    """Build the contract's `design/scenario_design.json` payload (§4.3) for
    `dam_id` (normally the site's most-upstream dam, CLAUDE.md rule 6).

    Raises `ScenarioDesignBlockedError` if `water_volume_m3` is itself a
    placeholder, or if either ranged input's M2 pair is blocked.
    """
    settings = settings or load_scenario_design_settings()
    dam = next((d for d in cfg.dams if d.id == dam_id), None)
    if dam is None:
        raise ValueError(f"no dam '{dam_id}' in site '{cfg.site.id}'")

    water_volume_m3 = dam.breach_inputs.water_volume_above_invert.value
    if water_volume_m3 is None:
        raise ScenarioDesignBlockedError(
            dam_id, "water_volume_m3",
            "water_volume_above_invert is a placeholder (status: placeholder) "
            "-- cannot fix a design value",
        )

    m2_ranges = _m2_ranges(dam)
    caveats = ["moraine_extrapolation"] if dam.kind in ("moraine_dammed_lake", "landslide_dam") else []
    return design_from_ranges(cfg.site.id, dam_id, water_volume_m3, m2_ranges, caveats, settings)


def write_scenario_design(cfg: SiteConfig, dam_id: str, data_dir: Path | None = None,
                           settings: ScenarioDesignSettings | None = None) -> Path:
    """Compute and write `data/<site_id>/design/scenario_design.json`,
    validated against `contracts/schemas/scenario_design.schema.json` first.

    Returns the path written.
    """
    from backend.m0_api import schemas  # local import: keep m5_emulator importable without m0_api at module load

    payload = build_scenario_design(cfg, dam_id, settings)
    schemas.validate("scenario_design.schema.json", payload)

    data_dir = data_dir or (Path(__file__).resolve().parents[2] / "data")
    out_dir = data_dir / cfg.site.id / "design"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "scenario_design.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path
