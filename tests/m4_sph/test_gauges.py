"""`gauges.py` reads the solver's own `GaugesSWL_*.csv`/`GaugesVel_*.csv` (not MeasureTool);
`GaugesSWL_*.csv`'s format is checked against a real pilot run's output (`docs/decisions.md`,
today's session). No real `GaugesVel_*.csv` example exists (the pilot case has no velocity
gauges), so its fixture below follows `GaugesSWL_*.csv`'s same column layout (`time [s]` then 3
data columns) -- `gauges.py`'s docstring flags this as unverified against a real run."""

from __future__ import annotations

import numpy as np
import pytest

from backend.m4_sph import gauges
from backend.m4_sph.generator import NearfieldProbe
from backend.shared.probes import Probe


def _write_swl_csv(path, name, rows):
    text = "time [s];swlx [m];swly [m];swlz [m];pos0x [m];pos0y [m];pos0z [m]\n"
    text += "".join(f"{t!r};{x!r};{y!r};{z!r};0;0;0\n" for t, x, y, z in rows)
    (path / f"GaugesSWL_{name}.csv").write_text(text, encoding="ascii")


def _write_vel_csv(path, name, rows):
    text = "time [s];velx [m/s];vely [m/s];velz [m/s]\n"
    text += "".join(f"{t!r};{vx!r};{vy!r};{vz!r}\n" for t, vx, vy, vz in rows)
    (path / f"GaugesVel_{name}.csv").write_text(text, encoding="ascii")


def test_read_swl_gauge(tmp_path):
    _write_swl_csv(tmp_path, "swl_teesta__poi__town_a", [(0.0, 10.0, 0.0, 5.0), (1.0, 10.0, 0.0, 4.5)])
    t_s, wse_m = gauges.read_swl_gauge(tmp_path, "swl_teesta__poi__town_a")
    np.testing.assert_allclose(t_s, [0.0, 1.0])
    np.testing.assert_allclose(wse_m, [5.0, 4.5])


def test_read_velocity_gauge_is_horizontal_magnitude(tmp_path):
    _write_vel_csv(tmp_path, "vel_teesta__poi__town_a", [(0.0, 3.0, 4.0, 100.0), (1.0, 0.0, 0.0, 0.0)])
    t_s, velocity_ms = gauges.read_velocity_gauge(tmp_path, "vel_teesta__poi__town_a")
    np.testing.assert_allclose(velocity_ms, [5.0, 0.0])  # sqrt(3^2+4^2)=5, vertical component ignored


def test_build_timeseries_converts_to_site_time_and_clips_depth(tmp_path):
    probe = NearfieldProbe(probe=Probe("teesta__poi__town_a", "Town A", "settlement", 100.0, 200.0), x_m=1.0, y_m=2.0, z_bed_m=5.0)
    _write_swl_csv(tmp_path, "swl_teesta__poi__town_a", [(0.0, 0, 0, 5.0), (1.0, 0, 0, 6.5), (2.0, 0, 0, 4.9)])
    _write_vel_csv(tmp_path, "vel_teesta__poi__town_a", [(0.0, 0.0, 0.0, 0.0), (1.0, 3.0, 4.0, 0.0), (2.0, 0.0, 0.0, 0.0)])

    rows = gauges.build_timeseries(tmp_path, [probe], t_start_s=1000.0)

    assert [r["t_s"] for r in rows] == [1000.0, 1001.0, 1002.0]
    assert [r["depth_m"] for r in rows] == pytest.approx([0.0, 1.5, 0.0])  # 4.9 - 5.0 clipped to 0
    assert [r["velocity_ms"] for r in rows] == pytest.approx([0.0, 5.0, 0.0])
    assert [r["wse_m"] for r in rows] == pytest.approx([5.0, 6.5, 4.9])
    assert all(r["poi_id"] == "teesta__poi__town_a" for r in rows)


def test_build_timeseries_mismatched_gauge_times_raises(tmp_path):
    probe = NearfieldProbe(probe=Probe("p1", "P1", "settlement", 0.0, 0.0), x_m=0.0, y_m=0.0, z_bed_m=0.0)
    _write_swl_csv(tmp_path, "swl_p1", [(0.0, 0, 0, 1.0), (1.0, 0, 0, 1.0)])
    _write_vel_csv(tmp_path, "vel_p1", [(0.0, 0.0, 0.0, 0.0)])
    with pytest.raises(ValueError, match="time steps differ"):
        gauges.build_timeseries(tmp_path, [probe], t_start_s=0.0)


def test_write_timeseries_csv(tmp_path):
    rows = [{"poi_id": "p1", "t_s": 10.0, "depth_m": 1.5, "velocity_ms": 2.0, "wse_m": 6.5}]
    path = gauges.write_timeseries_csv(tmp_path / "timeseries.csv", rows)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "poi_id,t_s,depth_m,velocity_ms,wse_m"
    assert lines[1] == "p1,10.0,1.5,2.0,6.5"
