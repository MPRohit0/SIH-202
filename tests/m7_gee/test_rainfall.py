"""Tests for backend.m7_gee.rainfall."""

from __future__ import annotations

import pytest

from backend.m7_gee import rainfall as rf


class TestToRows:
    def test_shapes_rows_to_the_contract_columns(self):
        daily = [{"date": "2026-09-02", "precip_mm": 1.5}, {"date": "2026-09-01", "precip_mm": 0.0}]
        rows = rf.to_rows(daily, dataset="chirps")
        assert rows == [
            {"date": "2026-09-01", "precip_mm": 0.0, "dataset": "chirps", "aggregation": "catchment_mean_daily_total"},
            {"date": "2026-09-02", "precip_mm": 1.5, "dataset": "chirps", "aggregation": "catchment_mean_daily_total"},
        ]


class TestAccumulations:
    def test_sums_within_each_window(self):
        rows = [{"date": f"2026-09-{d:02d}", "precip_mm": 1.0} for d in range(1, 31)]
        out = rf.accumulations(rows, windows_days=(7, 30), as_of="2026-09-30")
        assert out["7d_mm"] == pytest.approx(7.0)
        assert out["30d_mm"] == pytest.approx(30.0)
        assert out["as_of"] == "2026-09-30"
        assert out["last_date"] == "2026-09-30"

    def test_defaults_as_of_to_the_latest_row(self):
        rows = [{"date": "2026-09-01", "precip_mm": 2.0}, {"date": "2026-09-05", "precip_mm": 3.0}]
        out = rf.accumulations(rows, windows_days=(7,))
        assert out["as_of"] == "2026-09-05"
        assert out["7d_mm"] == pytest.approx(5.0)

    def test_window_with_no_data_is_null_not_zero(self):
        rows = [{"date": "2026-01-01", "precip_mm": 5.0}]
        out = rf.accumulations(rows, windows_days=(7,), as_of="2026-09-30")
        assert out["7d_mm"] is None

    def test_empty_input_gives_all_nulls(self):
        out = rf.accumulations([], windows_days=(7, 30))
        assert out == {"7d_mm": None, "30d_mm": None, "as_of": None, "last_date": None}
