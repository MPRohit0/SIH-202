from __future__ import annotations

import numpy as np
import pytest

from backend.m3_dflowfm.routed_discharge import read_routed_discharge, write_routed_discharge


def test_controlled_m3_series_roundtrips_and_rejects_wrong_site(tmp_path):
    section = {"type": "LineString", "coordinates": [[10.0, 20.0], [11.0, 21.0]], "crs": "EPSG:32645"}
    csv_path, sidecar = write_routed_discharge(
        tmp_path / "routed", site_id="synth", scenario_id="s001", source_run_id="s001__delft3d",
        t_s=[0, 10, 20], q_m3s=[2.0, 3.0, 1.0], routing_method="controlled_fixture",
        section=section, provenance={"source_map": "controlled-netcdf-fixture"},
    )
    assert csv_path.stat().st_size > 0
    t, q, record = read_routed_discharge(sidecar, site_id="synth", scenario_id="s001")
    np.testing.assert_array_equal(t, [0, 10, 20])
    np.testing.assert_array_equal(q, [2, 3, 1])
    assert record["source_m3_run_id"] == "s001__delft3d"
    with pytest.raises(ValueError, match="belongs to site"):
        read_routed_discharge(sidecar, site_id="other")


def test_routed_discharge_rejects_nonmonotone_or_negative_series(tmp_path):
    kwargs = dict(site_id="synth", scenario_id="s001", source_run_id="m3", routing_method="fixture",
                  section={"type": "LineString", "coordinates": [[0, 0], [1, 1]], "crs": "EPSG:32645"},
                  provenance={"source": "fixture"})
    with pytest.raises(ValueError, match="increase"):
        write_routed_discharge(tmp_path / "badtime", t_s=[1, 1], q_m3s=[1, 2], **kwargs)
    with pytest.raises(ValueError, match="nonnegative"):
        write_routed_discharge(tmp_path / "badflow", t_s=[0, 1], q_m3s=[1, -1], **kwargs)
