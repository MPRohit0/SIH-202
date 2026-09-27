"""Deterministic, explicitly reconstructed forcing for the Teesta 2023 MVP.

This is not an observed hydrograph. It imposes the user-specified base flow, event
volume, and Chungthang peak constraint as a symmetric triangular excess-flow pulse.
The caller must separately document where the series is applied in the hydraulic model.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

IST = ZoneInfo("Asia/Kolkata")
BASE_Q_M3S = 500.0
PEAK_Q_M3S = 7355.0
EVENT_VOLUME_M3 = 50_000_000.0
PEAK_AT_IST = datetime(2023, 10, 4, 3, 20, tzinfo=IST)
SAMPLE_INTERVAL_S = 60.0


@dataclass(frozen=True)
class ReconstructedForcing:
    timestamps_ist: tuple[datetime, ...]
    t_s: np.ndarray
    q_m3s: np.ndarray
    peak_time_ist: datetime
    event_volume_m3: float
    duration_s: float


def triangular_event_forcing(*, peak_time_ist: datetime = PEAK_AT_IST,
                             base_q_m3s: float = BASE_Q_M3S,
                             peak_q_m3s: float = PEAK_Q_M3S,
                             excess_volume_m3: float = EVENT_VOLUME_M3,
                             interval_s: float = SAMPLE_INTERVAL_S) -> ReconstructedForcing:
    """Construct a symmetric triangle over baseline with exactly the requested excess volume.

    For excess peak ``q_peak - q_base``, duration is ``2 V_excess / excess_peak``.
    The generated points are sampled at ``interval_s`` and include exact start, peak and
    end timestamps; trapezoidal integration therefore preserves the target volume.
    """
    if peak_time_ist.tzinfo is None:
        raise ValueError("peak_time_ist must be timezone-aware")
    if not (0 <= base_q_m3s < peak_q_m3s) or excess_volume_m3 <= 0 or interval_s <= 0:
        raise ValueError("require 0 <= base < peak, positive excess volume and interval")
    peak_time_ist = peak_time_ist.astimezone(IST)
    excess_peak = peak_q_m3s - base_q_m3s
    duration_s = 2.0 * excess_volume_m3 / excess_peak
    half = duration_s / 2.0
    start = peak_time_ist - timedelta(seconds=half)
    end = peak_time_ist + timedelta(seconds=half)
    left = np.arange(0.0, half, interval_s, dtype=float)
    right = half + np.arange(interval_s, half, interval_s, dtype=float)
    t_s = np.unique(np.concatenate(([0.0], left, [half], right, [duration_s])))
    q = base_q_m3s + excess_peak * (1.0 - np.abs(t_s - half) / half)
    q[0] = base_q_m3s
    q[-1] = base_q_m3s
    timestamps = tuple(start + timedelta(seconds=float(t)) for t in t_s)
    integrated = float(np.trapezoid(q - base_q_m3s, t_s))
    if not np.isclose(integrated, excess_volume_m3, rtol=1e-12, atol=1e-5):
        raise ArithmeticError(f"triangular forcing volume {integrated} differs from target")
    return ReconstructedForcing(timestamps, t_s, q, peak_time_ist,
                                integrated, duration_s)


def write_mvp_forcing(output_dir: str | Path) -> tuple[Path, Path]:
    """Write the timeseries and adjacent provenance note for this reconstruction."""
    result = triangular_event_forcing()
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    series_path = root / "teesta_2023_mvp_forcing.csv"
    provenance_path = root / "teesta_2023_mvp_forcing.provenance.json"
    with series_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["timestamp_ist", "t_s_since_hydrograph_start", "q_m3s"])
        writer.writerows((stamp.isoformat(), f"{t:.6f}", f"{q:.6f}")
                         for stamp, t, q in zip(result.timestamps_ist, result.t_s, result.q_m3s))
    metadata = {
        "scenario_id": "teesta_2023_mvp",
        "provenance": {
            "status": "MVP_RECONSTRUCTED",
            "scientific_claim": "NOT_OBSERVED_HYDROGRAPH",
            "source_constraints": {
                "event_volume_m3": {"value": EVENT_VOLUME_M3, "status": "approximate event constraint supplied for MVP"},
                "peak_discharge_m3s": {"value": PEAK_Q_M3S, "location": "Chungthang", "status": "user-specified reconstruction target; not reported by the cited White Rose paper"},
                "base_flow_m3s": {"value": BASE_Q_M3S, "status": "MVP forcing assumption"},
                "peak_time_ist": {"value": PEAK_AT_IST.isoformat(), "status": "MVP reconstruction target; source timing differs"},
            },
            "sources": [
                "https://parivesh.nic.in/utildoc/114429141_1733834917785.pdf",
                "https://eprints.whiterose.ac.uk/id/eprint/224098/",
                "https://cwc.gov.in/sites/default/files/agenda-3rd-ncds-meeting.pdf",
                "https://doi.org/10.1007/s11069-025-07350-9",
            ],
            "construction": {
                "formula": "Q(t)=Q_base+(Q_peak-Q_base)*(1-|t-t_peak|/(T/2)) for |t-t_peak|<=T/2; Q_base otherwise",
                "duration_s": result.duration_s,
                "duration_formula": "T=2*V_excess/(Q_peak-Q_base)",
                "excess_volume_target_m3": EVENT_VOLUME_M3,
                "integrated_excess_volume_m3": result.event_volume_m3,
                "sample_interval_s": SAMPLE_INTERVAL_S,
                "shape": "symmetric triangular excess above baseline",
            },
            "limitation": "This constraint-derived series is not a complete observed hydrograph and does not establish a routed hydrograph at any other model location.",
        },
    }
    provenance_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return series_path, provenance_path
