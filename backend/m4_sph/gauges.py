"""Builds `timeseries.csv` (contract §4.4: `poi_id,t_s,depth_m,velocity_ms,wse_m`, long format)
from the solver's own real-time gauge CSVs -- not MeasureTool. `generator.build_nearfield_case`
already places one `swl` and one `velocity` gauge per near-field probe (named `swl_<poi_id>` /
`vel_<poi_id>`, `case_xml.SwlGauge`/`VelocityGauge`); DualSPHysics writes those out itself, during
the run, as `GaugesSWL_<name>.csv` / `GaugesVel_<name>.csv` in the run's raw output directory --
no separate tool invocation needed to get probe time series.

`velocity_ms` here is the single fixed-height point sample the gauge is placed at
(`settings.probe_velocity_height_m` above the bed) -- a different quantity from
`summary_nearfield/max_velocity.tif`'s depth-averaged column value (`measuretool.py`,
`docs/decisions.md` "SPH velocity: depth-average, not a fixed-height point"): that decision was
about comparing grid-wide maxima against Delft3D's depth-averaged output, not about what a single
probe reports at one instant. Verified `GaugesSWL_*.csv`'s real header/format against a real run
(`time [s];swlx [m];swly [m];swlz [m];pos0x...`); no real `GaugesVel_*.csv` example was available
(the pilot case has no velocity gauges), so its header is read positionally (first 3 data columns
after `time [s]`, whatever their exact label) rather than assumed to be an exact string.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .generator import NearfieldProbe


def _read_gauge_csv(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """`(t_s, xyz)`: the header row's first 3 data columns after `time [s]`, positionally --
    robust to the exact column label (`swlx`/`velx`/...) as long as x, y, z come first."""
    rows = path.read_text(encoding="ascii").splitlines()
    data = np.loadtxt(rows[1:], delimiter=";")
    data = data.reshape(-1, len(rows[0].split(";")))
    return data[:, 0], data[:, 1:4]


def read_swl_gauge(raw_dir: str | Path, name: str) -> tuple[np.ndarray, np.ndarray]:
    """`(t_s, wse_m)` from `GaugesSWL_<name>.csv`'s `swlz` column (the free-surface elevation)."""
    t_s, xyz = _read_gauge_csv(Path(raw_dir) / f"GaugesSWL_{name}.csv")
    return t_s, xyz[:, 2]


def read_velocity_gauge(raw_dir: str | Path, name: str) -> tuple[np.ndarray, np.ndarray]:
    """`(t_s, velocity_ms)` from `GaugesVel_<name>.csv`, horizontal magnitude `sqrt(vx^2+vy^2)`
    (vertical velocity isn't part of the hazard quantity the contract's `velocity_ms` reports)."""
    t_s, vel_xyz = _read_gauge_csv(Path(raw_dir) / f"GaugesVel_{name}.csv")
    return t_s, np.hypot(vel_xyz[:, 0], vel_xyz[:, 1])


def build_timeseries(
    raw_dir: str | Path, probes: list[NearfieldProbe], t_start_s: float,
) -> list[dict]:
    """Rows for `timeseries.csv` (contract §4.4), one per `(poi_id, t_s)`: `t_s` converted from
    solver time (0 at `t_start_s`) to site time (seconds since t0, CLAUDE.md rule 6) by adding
    `t_start_s`. `depth_m = wse_m - z_bed_m`, clipped at 0 (contract §1.5: dry cells are `0.0`,
    never negative)."""
    rows: list[dict] = []
    for p in probes:
        t_wse, wse_m = read_swl_gauge(raw_dir, f"swl_{p.probe.poi_id}")
        t_vel, velocity_ms = read_velocity_gauge(raw_dir, f"vel_{p.probe.poi_id}")
        if not np.array_equal(t_wse, t_vel):
            raise ValueError(
                f"{p.probe.poi_id}: swl and velocity gauge time steps differ -- "
                f"both gauges should share the solver's PART output cadence"
            )
        depth_m = np.clip(wse_m - p.z_bed_m, 0.0, None)
        for t, d, v, w in zip(t_wse, depth_m, velocity_ms, wse_m):
            rows.append({
                "poi_id": p.probe.poi_id, "t_s": float(t) + t_start_s,
                "depth_m": float(d), "velocity_ms": float(v), "wse_m": float(w),
            })
    return rows


def write_timeseries_csv(path: str | Path, rows: list[dict]) -> Path:
    path = Path(path)
    with open(path, "w", encoding="utf-8") as f:
        f.write("poi_id,t_s,depth_m,velocity_ms,wse_m\n")
        for r in rows:
            f.write(f"{r['poi_id']},{r['t_s']!r},{r['depth_m']!r},{r['velocity_ms']!r},{r['wse_m']!r}\n")
    return path
