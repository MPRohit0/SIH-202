"""Tests for backend.m7_gee.recheck."""

from __future__ import annotations

import pytest

from backend.m7_gee import recheck as rc

SERIES = [
    {"date": "2026-01-01", "area_m2": 1_000_000.0},
    {"date": "2026-02-01", "area_m2": None},  # a skipped (ice) month
    {"date": "2026-03-01", "area_m2": 1_050_000.0},
    {"date": "2026-06-01", "area_m2": 1_300_000.0},
]


class TestReferenceArea:
    def test_picks_latest_row_on_or_before_trained_at(self):
        assert rc.reference_area(SERIES, trained_at="2026-04-01T00:00:00Z") == pytest.approx(1_050_000.0)

    def test_exact_date_match_is_inclusive(self):
        assert rc.reference_area(SERIES, trained_at="2026-03-01") == pytest.approx(1_050_000.0)

    def test_skips_rows_with_no_area(self):
        # trained_at lands between the null Feb row and the Jan row that precedes it
        assert rc.reference_area(SERIES, trained_at="2026-02-15") == pytest.approx(1_000_000.0)

    def test_no_row_old_enough_returns_none(self):
        assert rc.reference_area(SERIES, trained_at="2025-12-01") is None


class TestComputeRecheck:
    def test_within_threshold_is_not_outdated(self):
        out = rc.compute_recheck("teesta", latest_area_m2=1_030_000.0, reference_area_m2=1_000_000.0,
                                  threshold_pct=10.0, checked_at="2026-09-24T10:15:00Z")
        assert out == {
            "site_id": "teesta", "checked_at": "2026-09-24T10:15:00Z",
            "latest_area_m2": 1_030_000.0, "reference_area_m2": 1_000_000.0,
            "change_pct": pytest.approx(3.0), "threshold_pct": 10.0,
            "outdated": False, "reason": "within_threshold",
        }

    def test_exceeding_threshold_is_outdated(self):
        out = rc.compute_recheck("teesta", latest_area_m2=1_150_000.0, reference_area_m2=1_000_000.0,
                                  threshold_pct=10.0, checked_at="2026-09-24T10:15:00Z")
        assert out["outdated"] is True
        assert out["reason"] == "outdated_lake_area_change"
        assert out["change_pct"] == pytest.approx(15.0)

    def test_change_exactly_at_threshold_is_outdated(self):
        out = rc.compute_recheck("teesta", latest_area_m2=1_100_000.0, reference_area_m2=1_000_000.0,
                                  threshold_pct=10.0)
        assert out["outdated"] is True

    def test_a_shrinking_lake_uses_absolute_change(self):
        out = rc.compute_recheck("teesta", latest_area_m2=850_000.0, reference_area_m2=1_000_000.0,
                                  threshold_pct=10.0)
        assert out["change_pct"] == pytest.approx(-15.0)
        assert out["outdated"] is True

    def test_no_trained_library_is_never_outdated(self):
        out = rc.compute_recheck("teesta", latest_area_m2=1_000_000.0, reference_area_m2=None,
                                  threshold_pct=10.0)
        assert out["outdated"] is False
        assert out["reason"] == "no_trained_library"
        assert out["change_pct"] is None

    def test_no_lake_area_data_at_all(self):
        out = rc.compute_recheck("teesta", latest_area_m2=None, reference_area_m2=None, threshold_pct=10.0)
        assert out["outdated"] is False
        assert out["reason"] == "no_lake_area_data"

    def test_checked_at_defaults_to_now_utc_z_suffixed(self):
        out = rc.compute_recheck("teesta", latest_area_m2=1.0, reference_area_m2=1.0, threshold_pct=10.0)
        assert out["checked_at"].endswith("Z")
