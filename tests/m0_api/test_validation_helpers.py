"""Unit tests for backend/m0_api/validation_helpers.py (Task D: Validation tab).

Every function must stay honest when its inputs are missing: no IoU/F1, arrival time or
discharge number may appear unless it was actually computed from real files on disk.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from backend.m0_api import validation_helpers as vh


def _write_timeseries(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["poi_id", "t_s", "depth_m", "velocity_ms", "wse_m", "arrival_s_since_t0"])
        writer.writeheader()
        writer.writerows(rows)


def _write_hydrograph(path: Path, peak_time_ist: str, duration_s: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "provenance": {
            "source_constraints": {
                "peak_time_ist": {"value": peak_time_ist, "status": "MVP reconstruction target"},
            },
            "construction": {"duration_s": duration_s},
        }
    }))


class TestObservedExtentStatus:
    def test_missing_reports_not_digitized(self, tmp_path):
        result = vh.observed_extent_status("teesta", "sikkim_glof_2023", tmp_path)
        assert result["available"] is False
        assert "not yet digitized" in result["note"]

    def test_present_reports_url(self, tmp_path):
        observed_dir = tmp_path / "teesta" / "gee" / "observed"
        observed_dir.mkdir(parents=True)
        (observed_dir / "sikkim_glof_2023_observed.geojson").write_text("{}")
        result = vh.observed_extent_status("teesta", "sikkim_glof_2023", tmp_path)
        assert result["available"] is True
        assert result["extent_url"] == "/api/v1/files/teesta/gee/observed/sikkim_glof_2023_observed.geojson"


class TestLiteratureComparison:
    def test_no_run_id_is_unavailable(self, tmp_path):
        result = vh.build_literature_comparison("teesta", {}, tmp_path)
        assert result["available"] is False
        assert result["simulated"] is None
        assert len(result["literature"]) == 3  # still surfaces the citations for context

    def test_no_timeseries_file_is_unavailable(self, tmp_path):
        result = vh.build_literature_comparison("teesta", {"run_id": "r1"}, tmp_path)
        assert result["available"] is False

    def test_no_matching_poi_is_unavailable(self, tmp_path):
        _write_timeseries(tmp_path / "teesta" / "runs" / "r1" / "timeseries.csv", [
            {"poi_id": "teesta_pilot__poi__lachen", "t_s": "0", "depth_m": "0", "velocity_ms": "0",
             "wse_m": "100", "arrival_s_since_t0": ""},
        ])
        result = vh.build_literature_comparison("teesta", {"run_id": "r1"}, tmp_path)
        assert result["available"] is False

    def test_poi_with_no_arrival_is_unavailable(self, tmp_path):
        _write_timeseries(tmp_path / "teesta" / "runs" / "r1" / "timeseries.csv", [
            {"poi_id": "teesta_pilot__poi__chungthang", "t_s": "0", "depth_m": "0", "velocity_ms": "0",
             "wse_m": "1583", "arrival_s_since_t0": ""},
        ])
        result = vh.build_literature_comparison("teesta", {"run_id": "r1"}, tmp_path)
        assert result["available"] is False

    def test_real_poi_output_without_hydrograph_gives_relative_arrival_only(self, tmp_path):
        _write_timeseries(tmp_path / "teesta" / "runs" / "r1" / "timeseries.csv", [
            {"poi_id": "teesta_pilot__poi__chungthang", "t_s": "0", "depth_m": "0", "velocity_ms": "0",
             "wse_m": "1583", "arrival_s_since_t0": ""},
            {"poi_id": "teesta_pilot__poi__chungthang", "t_s": "23340", "depth_m": "11.6", "velocity_ms": "0.39",
             "wse_m": "1594.77", "arrival_s_since_t0": "22920.0"},
        ])
        result = vh.build_literature_comparison("teesta", {"run_id": "r1"}, tmp_path)
        assert result["available"] is True
        assert result["simulated"]["arrival_s_since_t0"] == 22920.0
        assert result["simulated"]["peak_depth_m"] == pytest.approx(11.6)
        assert result["simulated"]["peak_velocity_ms"] == pytest.approx(0.39)
        assert "arrival_time_ist_estimate" not in result["simulated"]

    def test_real_poi_output_with_hydrograph_derives_absolute_arrival(self, tmp_path):
        _write_timeseries(tmp_path / "teesta" / "runs" / "r1" / "timeseries.csv", [
            {"poi_id": "teesta_pilot__poi__chungthang", "t_s": "23340", "depth_m": "11.6", "velocity_ms": "0.39",
             "wse_m": "1594.77", "arrival_s_since_t0": "22920.0"},
        ])
        _write_hydrograph(tmp_path / "teesta" / "breach" / "hydrographs" / "h.json",
                           "2023-10-04T03:20:00+05:30", 14587.892049598833)
        run_meta = {"run_id": "r1", "forcing_provenance_path": "breach/hydrographs/h.json"}
        result = vh.build_literature_comparison("teesta", run_meta, tmp_path)
        assert result["available"] is True
        # t0 = 03:20:00 - 14587.892.../2 s (~4.05 h / 2 = ~2.03 h) = ~01:18:06 IST
        # arrival = t0 + 22920 s (6.37 h) = ~07:39:36 IST same day
        assert result["simulated"]["arrival_time_ist_estimate"].startswith("2023-10-04T07:")
        assert "t0_derivation" in result["simulated"]
        # Every returned literature citation is honestly labelled a reconstruction, not an observation.
        for citation in result["literature"]:
            assert "not a direct field observation" in citation["note"] or "not an independent check" in citation["note"]


class TestPredictedExtent:
    def _write_max_depth_tif(self, path: Path, values: np.ndarray, res=90.0, nodata=-9999.0) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        transform = from_origin(0, 0, res, res)
        with rasterio.open(path, "w", driver="GTiff", height=values.shape[0], width=values.shape[1],
                            count=1, dtype=values.dtype, crs="EPSG:32645", transform=transform, nodata=nodata) as ds:
            ds.write(values, 1)

    def test_no_threshold_or_raster_returns_none(self, tmp_path):
        assert vh.build_predicted_extent({}, tmp_path) is None
        assert vh.build_predicted_extent({"thresholds": {"extent_m": 0.3}}, tmp_path) is None

    def test_computes_real_area_from_raster(self, tmp_path):
        run_dir = tmp_path / "run"
        values = np.array([[-9999.0, 0.0, 0.5], [0.2, 0.31, 5.0]], dtype="float32")
        self._write_max_depth_tif(run_dir / "summary" / "max_depth.tif", values)
        run_meta = {"thresholds": {"extent_m": 0.3}, "run_id": "r1"}
        result = vh.build_predicted_extent(run_meta, run_dir)
        assert result is not None
        # wet cells strictly > 0.3 and != nodata: 0.31, 0.5 and 5.0 -> 3 cells * 90*90 m2
        assert result["value"] == pytest.approx(3 * 90.0 * 90.0)
        assert result["kind"] == "predicted"
        assert result["unit"] == "m2"


class TestSyntheticLoocvSummary:
    def test_missing_report_returns_none(self, tmp_path):
        assert vh.synthetic_loocv_summary(tmp_path / "nope.json") is None

    def test_present_report_is_labelled_synthetic(self, tmp_path):
        report = tmp_path / "loocv.json"
        report.write_text(json.dumps({
            "model": "synthetic", "n_runs": 30,
            "summary": {"extent": {"grade": "A"}},
            "baseline_linear": {}, "baseline_nearest": {}, "acceptance": {"pass": True},
            "grade_thresholds_ref": "docs/m5_spec.md",
        }))
        result = vh.synthetic_loocv_summary(report)
        assert result["world"] == "synthetic_test_world"
        assert "synthetic" in result["note"].lower()
        assert result["n_runs"] == 30
        assert result["summary"] == {"extent": {"grade": "A"}}
