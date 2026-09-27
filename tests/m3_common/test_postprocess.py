from __future__ import annotations

import csv
import json
from pathlib import Path

import rasterio

from backend.m3_common.postprocess import PostprocessConfig, postprocess_dflowfm

ROOT = Path(__file__).resolve().parents[2]
CASE = ROOT / "data/teesta_pilot/runs/teesta_pilot_s001/dflowfm_reproduction_map60/case"


def test_postprocess_pilot_outputs_match_contract(tmp_path: Path) -> None:
    if not (CASE / "output/model_map.nc").is_file():
        import pytest
        pytest.skip("D-Flow FM pilot output is not available")
    result = postprocess_dflowfm(
        CASE, tmp_path / "run", grid_path=ROOT / "data/teesta_pilot/terrain/grid.json",
        domain_mask_path=ROOT / "data/teesta_pilot/terrain/domain_mask.tif",
        run_id="teesta_pilot_s001__delft3d", scenario_id="teesta_pilot_s001",
        spinup_s=7200, config=PostprocessConfig(),
    )
    assert result["status"] == "postprocessed"
    assert result["cell_count"] == 3234
    assert result["mass_balance_error_pct"] is None  # FM balance output was disabled in this run.
    for name in ("max_depth", "max_velocity", "arrival_time"):
        with rasterio.open(tmp_path / "run/summary" / f"{name}.tif") as ds:
            assert (ds.height, ds.width) == (623, 611)
            assert ds.nodata == -9999.0
            assert ds.crs.to_epsg() == 32645
            values = ds.read(1)
            if name != "arrival_time":
                assert (values != -9999.0).any()
                assert values[values != -9999.0].min() >= 0
            else:
                # The current pilot has no >0.1 m cells inside its configured domain mask.
                assert (values == -9999.0).all()
    with (tmp_path / "run/timeseries.csv").open(newline="") as stream:
        reader = csv.reader(stream)
        assert next(reader) == ["poi_id", "t_s", "depth_m", "velocity_ms", "wse_m"]
    json.loads((tmp_path / "run/run_meta.json").read_text())
    assert (CASE / "output/model_map.nc").exists()  # default is keep for pilot.


def test_map_is_deleted_only_after_successful_postprocessing(tmp_path: Path) -> None:
    if not (CASE / "output/model_map.nc").is_file():
        import pytest
        pytest.skip("D-Flow FM pilot output is not available")
    # Use a private case copy so deletion behavior never mutates the checked-in pilot output.
    import shutil
    private_case = tmp_path / "case"
    shutil.copytree(CASE, private_case)
    postprocess_dflowfm(
        private_case, tmp_path / "run", grid_path=ROOT / "data/teesta_pilot/terrain/grid.json",
        domain_mask_path=ROOT / "data/teesta_pilot/terrain/domain_mask.tif",
        run_id="teesta_pilot_s001__delft3d", scenario_id="teesta_pilot_s001", spinup_s=7200,
        config=PostprocessConfig(delete_raw_map=True),
    )
    assert not (private_case / "output/model_map.nc").exists()
    assert (tmp_path / "run/run_meta.json").exists()


def test_broken_mdu_is_caught_even_when_kernel_returns_zero(tmp_path: Path) -> None:
    import shutil
    import pytest
    from backend.m3_dflowfm.launcher import DEFAULT_KERNEL, check_success, launch_case

    if not DEFAULT_KERNEL.exists():
        pytest.skip("D-Flow FM kernel is unavailable")
    case = tmp_path / "broken_case"
    case.mkdir()
    shutil.copytree(CASE / "inputs", case / "inputs")
    (case / "model.mdu").write_text("THIS IS A DELIBERATELY BROKEN MDU FILE\n")
    process = launch_case(case, tmp_path / "run")
    process.wait(timeout=30)
    result = check_success(case, "model")
    assert process.returncode == 0  # D-Flow FM can fail internally while returning success.
    assert not result["success"]
    assert result["missing_outputs"]
    assert "** ERROR" in (tmp_path / "run/log.txt").read_text(errors="replace")


def test_fm_water_balance_volume_error_is_reported_as_percent(tmp_path: Path) -> None:
    import numpy as np
    import xarray as xr
    from backend.m3_common.postprocess import _balance_error

    output = tmp_path / "output"
    output.mkdir()
    xr.Dataset({
        "water_balance_volume_error": ("time", np.array([0.0, 2.0])),
        "water_balance_laterals_in": ("time", np.array([0.0, 100.0])),
    }).to_netcdf(output / "test_his.nc")
    assert _balance_error(tmp_path) == 2.0
