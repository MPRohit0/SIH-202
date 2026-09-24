"""Cascade support for M2 — two-stage imposed breach triggering.

`docs/decisions.md` ("M2 cascade engine: two-stage imposed hydrograph", decided with the user):
`Cascade.approach == 'two_stage_imposed'` (`backend/shared/site_config.py`) is the only approach
this module implements. A downstream dam's own breach hydrograph is triggered once routed inflow
from its upstream dam first reaches that dam's `trigger.value` (m3/s, per-dam — not the single
site-level `cascade.trigger` sketched in `docs/handoff_contract.md` §3.1; this is additive and
PENDING team agreement, see decisions.md).

M2 does **not** route the flood itself — the routed inflow time series at the downstream dam is an
input to this module, produced by the stage-1 Delft3D run's observation cross-section (M3), or
M5's HAND fallback. No celerity/attenuation value is invented here (CLAUDE.md rule 3).

`cascade.approach == 'dambreak_structure'` is a different approach — breaching modelled dynamically
inside a Delft3D structure — that belongs to M3, not M2; `cascade_plan` raises if it sees it.

Once triggered, the downstream dam's hydrograph releases only its OWN stored volume
(`hydrograph_for_dam`, unchanged). The routed upstream flood keeps flowing through the stage-2
hydraulic model and is superposed there, not by M2 — caveat `cascade_superposition` records this
simplification (reservoir filling by the incoming flood before breach is not modelled).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from backend.shared.site_config import SiteConfig

from .hydrograph import Hydrograph, HydrographBlocked, _caveat, hydrograph_for_dam


class UnsupportedCascadeApproach(ValueError):
    """Raised for `cascade.approach == 'dambreak_structure'`: that approach models the breach
    dynamically inside a Delft3D structure (M3's job), not as an M2 pre-computed hydrograph."""


@dataclass(frozen=True)
class CascadeStage:
    """One dam's place in the cascade, upstream -> downstream (`SiteConfig.dams` order)."""

    dam_id: str
    order: int
    triggered_by: str | None
    threshold_m3s: float | None  # None: not a triggered dam, or its trigger is a placeholder
    equations_applicable: bool


def cascade_plan(cfg: SiteConfig) -> list[CascadeStage]:
    """Upstream -> downstream stage list for every dam in `cfg`.

    Raises `UnsupportedCascadeApproach` if `cfg.cascade.approach == 'dambreak_structure'`.
    """
    if cfg.cascade is not None and cfg.cascade.approach == "dambreak_structure":
        raise UnsupportedCascadeApproach(
            f"site '{cfg.site.id}': cascade.approach='dambreak_structure' models the breach "
            f"inside a Delft3D structure (M3), not as an M2 pre-computed hydrograph; "
            f"backend/m2_breach/cascade.py only implements 'two_stage_imposed'"
        )
    stages = []
    for i, dam in enumerate(cfg.dams):
        threshold = dam.trigger.value.value if dam.trigger is not None else None
        stages.append(CascadeStage(dam_id=dam.id, order=i, triggered_by=dam.triggered_by,
                                    threshold_m3s=threshold, equations_applicable=dam.equations_applicable))
    return stages


def trigger_time(t_s, q_m3s, threshold_m3s: float) -> float | None:
    """First time `q_m3s` reaches `threshold_m3s`, linearly interpolated between samples.

    `t_s` (seconds since t0, contract rule 6) must be strictly increasing and start at >= 0.
    Returns `None` if the threshold is never reached — the downstream dam does not fail in this
    scenario, which is not an error.
    """
    t_arr = np.asarray(t_s, dtype=float)
    q_arr = np.asarray(q_m3s, dtype=float)
    if len(t_arr) != len(q_arr) or len(t_arr) < 2:
        raise ValueError("t_s and q_m3s must be equal-length arrays of at least 2 samples")
    if t_arr[0] < 0:
        raise ValueError(f"t_s must start at or after t0 (>= 0 s), got {t_arr[0]!r}")
    if np.any(np.diff(t_arr) <= 0):
        raise ValueError("t_s must be strictly increasing")
    if threshold_m3s <= 0:
        raise ValueError(f"threshold_m3s must be > 0, got {threshold_m3s!r}")

    at_or_above = np.nonzero(q_arr >= threshold_m3s)[0]
    if len(at_or_above) == 0:
        return None
    i = int(at_or_above[0])
    if i == 0:
        return float(t_arr[0])
    t_lo, t_hi = t_arr[i - 1], t_arr[i]
    q_lo, q_hi = q_arr[i - 1], q_arr[i]
    if q_hi == q_lo:
        return float(t_hi)
    frac = (threshold_m3s - q_lo) / (q_hi - q_lo)
    return float(t_lo + frac * (t_hi - t_lo))


@dataclass(frozen=True)
class TriggerInfo:
    """Contract §4.2 hydrograph sidecar's `trigger` block (additive, `docs/decisions.md`)."""

    triggered: bool
    triggered_by: str
    type: str
    threshold_m3s: float
    trigger_time_s: float | None
    inflow_peak_m3s: float | None
    inflow_source: str

    def to_dict(self) -> dict:
        return {
            "triggered": self.triggered, "triggered_by": self.triggered_by, "type": self.type,
            "threshold_m3s": self.threshold_m3s, "trigger_time_s": self.trigger_time_s,
            "inflow_peak_m3s": self.inflow_peak_m3s, "inflow_source": self.inflow_source,
        }


def triggered_hydrograph(cfg: SiteConfig, dam_id: str, params: dict, inflow_t_s, inflow_q_m3s,
                         inflow_source: str) -> tuple[Hydrograph | None, TriggerInfo]:
    """Build the triggered breach hydrograph for a downstream dam under `two_stage_imposed`.

    `inflow_t_s`/`inflow_q_m3s` is the routed inflow at `dam_id` from its upstream dam(s) — an M3
    Delft3D stage-1 observation point, or M5's HAND fallback. `inflow_source` identifies where it
    came from (e.g. `"delft3d_stage1:<run_id>"`) for provenance.

    Returns `(None, trigger)` with `trigger.triggered=False` if the inflow never reaches the
    threshold in this scenario. Raises `HydrographBlocked` if the threshold itself is a
    placeholder (block, don't guess — CLAUDE.md rule 3), or `ValueError` if `dam_id` is not a
    triggered dam.
    """
    dam = next((d for d in cfg.dams if d.id == dam_id), None)
    if dam is None:
        raise ValueError(f"site '{cfg.site.id}' has no dam '{dam_id}'")
    if dam.triggered_by is None or dam.trigger is None:
        raise ValueError(f"dam '{dam_id}' is not a triggered dam (no triggered_by/trigger configured)")
    if dam.trigger.value.value is None:
        raise HydrographBlocked(f"dam '{dam_id}': trigger.value is a placeholder (status: placeholder)")

    threshold = dam.trigger.value.value
    inflow_peak = float(np.max(np.asarray(inflow_q_m3s, dtype=float)))
    t_trig = trigger_time(inflow_t_s, inflow_q_m3s, threshold)

    base = dict(triggered_by=dam.triggered_by, type=dam.trigger.type, threshold_m3s=threshold,
                inflow_source=inflow_source)

    if t_trig is None:
        return None, TriggerInfo(triggered=False, trigger_time_s=None, inflow_peak_m3s=inflow_peak, **base)

    hg = hydrograph_for_dam(dam, {**params, "t_offset_s": t_trig})
    trigger_dict = TriggerInfo(triggered=True, trigger_time_s=t_trig, inflow_peak_m3s=inflow_peak, **base).to_dict()
    hg = replace(hg, caveats=[*hg.caveats, _caveat("cascade_superposition", severity="info")],
                trigger=trigger_dict)

    return hg, TriggerInfo(triggered=True, trigger_time_s=t_trig, inflow_peak_m3s=inflow_peak, **base)
