"""End-to-end tests for backend.m7_gee.fetch, against SyntheticProvider (CLAUDE.md rule 2: every
module runs end to end on synthetic data before real data exists) and `tests/fixtures/shared/
synth.yaml`.
"""

from __future__ import annotations

import json

import pytest

from backend.m7_gee import cache, fetch
from backend.m7_gee.provider import SyntheticProvider
from backend.m7_gee.settings import GeeSettings
from backend.shared.site_config import load_site_config

FIXTURES_DIR = "tests/fixtures/shared"


@pytest.fixture(autouse=True)
def _synth_site(monkeypatch):
    monkeypatch.setattr(fetch, "load_site_config", lambda site_id: load_site_config("synth", sites_dir=FIXTURES_DIR))


class TestRunEndToEnd:
    def test_writes_all_five_contract_files(self, tmp_path):
        settings = GeeSettings(months_back=3)
        provider = SyntheticProvider()
        result = fetch.run("synth", settings=settings, provider=provider, data_dir=tmp_path)

        assert result.errors == []
        for path in (result.lake_area_path, result.lake_latest_path, result.rainfall_path,
                     result.meta_path, result.recheck_path):
            assert path.is_file()

    def test_lake_area_csv_header_matches_the_contract(self, tmp_path):
        fetch.run("synth", settings=GeeSettings(months_back=2), provider=SyntheticProvider(), data_dir=tmp_path)
        path = cache.gee_dir("synth", tmp_path) / "lake_area.csv"
        assert path.read_text().splitlines()[0] == "date,area_m2,method,cloud_pct,scene_ids"

    def test_rainfall_csv_header_matches_the_contract(self, tmp_path):
        fetch.run("synth", settings=GeeSettings(months_back=1), provider=SyntheticProvider(), data_dir=tmp_path)
        path = cache.gee_dir("synth", tmp_path) / "rainfall.csv"
        assert path.read_text().splitlines()[0] == "date,precip_mm,dataset,aggregation"

    def test_all_months_use_s2_when_conditions_are_clear(self, tmp_path):
        fetch.run("synth", settings=GeeSettings(months_back=3), provider=SyntheticProvider(), data_dir=tmp_path)
        rows = cache.read_lake_area("synth", tmp_path)
        assert len(rows) == 3
        assert all(r["method"] == "s2_water_index" for r in rows)
        assert all(r["area_m2"] is not None for r in rows)

    def test_cloudy_month_falls_back_to_s1(self, tmp_path):
        months = fetch._month_starts(3)
        cloudy_key = months[1].strftime("%Y-%m")
        provider = SyntheticProvider(cloudy_months=(cloudy_key,))
        fetch.run("synth", settings=GeeSettings(months_back=3), provider=provider, data_dir=tmp_path)
        rows = {r["date"]: r for r in cache.read_lake_area("synth", tmp_path)}
        assert rows[months[1].isoformat()]["method"] == "s1_threshold"
        assert rows[months[1].isoformat()]["cloud_pct"] is None  # only s2 rows carry cloud_pct

    def test_icy_month_is_skipped_with_no_area(self, tmp_path):
        months = fetch._month_starts(3)
        icy_key = months[0].strftime("%Y-%m")
        provider = SyntheticProvider(icy_months=(icy_key,))
        fetch.run("synth", settings=GeeSettings(months_back=3), provider=provider, data_dir=tmp_path)
        rows = {r["date"]: r for r in cache.read_lake_area("synth", tmp_path)}
        assert rows[months[0].isoformat()]["area_m2"] is None
        assert rows[months[0].isoformat()]["method"] is None

    def test_gee_meta_records_settings_and_has_placeholders(self, tmp_path):
        fetch.run("synth", settings=GeeSettings(months_back=1), provider=SyntheticProvider(), data_dir=tmp_path)
        meta = json.loads((cache.gee_dir("synth", tmp_path) / "gee_meta.json").read_text())
        assert meta["contract_version"] == "0.3.0"
        assert meta["site_id"] == "synth"
        assert "months_back" in meta["settings"]
        assert meta["has_placeholders"] is False  # synth_lake's location and crs.utm_epsg are both sourced
        assert meta["lake_area"]["source"] == "live"

    def test_lake_latest_geojson_is_the_newest_valid_month(self, tmp_path):
        fetch.run("synth", settings=GeeSettings(months_back=3), provider=SyntheticProvider(), data_dir=tmp_path)
        fc = json.loads((cache.gee_dir("synth", tmp_path) / "lake_latest.geojson").read_text())
        assert len(fc["features"]) == 1
        months = fetch._month_starts(3)
        assert fc["features"][0]["properties"]["date"] == months[-1].isoformat()

    def test_second_run_does_not_refetch_old_finished_months(self, tmp_path):
        settings = GeeSettings(months_back=4)
        calls = {"n": 0}

        class CountingProvider(SyntheticProvider):
            def s2_month(self, grid, month_start, month_end):
                calls["n"] += 1
                return super().s2_month(grid, month_start, month_end)

        fetch.run("synth", settings=settings, provider=CountingProvider(), data_dir=tmp_path)
        first_calls = calls["n"]
        assert first_calls == 4

        fetch.run("synth", settings=settings, provider=CountingProvider(), data_dir=tmp_path)
        second_calls = calls["n"] - first_calls
        # only the trailing REFETCH_TRAILING_MONTHS months are refetched on the second run
        assert second_calls == fetch.REFETCH_TRAILING_MONTHS

    def test_shrinking_lake_is_visible_across_months(self, tmp_path):
        months = fetch._month_starts(3)
        shrink_after = months[0].strftime("%Y-%m")
        provider = SyntheticProvider(shrink_after=shrink_after, shrink_radius_px=15)
        fetch.run("synth", settings=GeeSettings(months_back=3), provider=provider, data_dir=tmp_path)
        rows = cache.read_lake_area("synth", tmp_path)
        assert rows[0]["area_m2"] > rows[-1]["area_m2"]

    def test_snow_bridge_does_not_inflate_area_via_nir_filter(self, tmp_path):
        """End-to-end regression (docs/decisions.md 2026-09-28) for the South Lhonak overestimate:
        a bright-NIR corridor that would otherwise bridge the seeded lake to a second, separate
        water body is excluded by the NIR test, so the fetched area matches the seeded lake alone,
        not the lake plus the bridge plus the second water body."""
        months = fetch._month_starts(1)
        key = months[0].strftime("%Y-%m")
        settings = GeeSettings(months_back=1)

        plain = fetch.run("synth", settings=settings, provider=SyntheticProvider(lake_radius_px=20),
                           data_dir=tmp_path / "plain")
        bridged = fetch.run("synth", settings=settings,
                             provider=SyntheticProvider(lake_radius_px=20, snow_bridge_months=(key,)),
                             data_dir=tmp_path / "bridged")

        plain_area = cache.read_lake_area("synth", tmp_path / "plain")[0]["area_m2"]
        bridged_area = cache.read_lake_area("synth", tmp_path / "bridged")[0]["area_m2"]
        assert bridged_area == pytest.approx(plain_area, rel=0.05)

    def test_reference_area_override_feeds_the_recheck(self, tmp_path):
        fetch.run("synth", settings=GeeSettings(months_back=1), provider=SyntheticProvider(),
                   data_dir=tmp_path, reference_area_m2=1.0)
        recheck = json.loads((cache.gee_dir("synth", tmp_path) / "recheck.json").read_text())
        assert recheck["reference_area_m2"] == pytest.approx(1.0)
        assert recheck["outdated"] is True  # any real lake area is wildly different from 1 m^2

    def test_no_trained_library_gives_a_non_outdated_recheck(self, tmp_path):
        fetch.run("synth", settings=GeeSettings(months_back=1), provider=SyntheticProvider(), data_dir=tmp_path)
        recheck = json.loads((cache.gee_dir("synth", tmp_path) / "recheck.json").read_text())
        assert recheck["reference_area_m2"] is None
        assert recheck["outdated"] is False
        assert recheck["reason"] == "no_trained_library"


class TestProviderFailureKeepsCache:
    def test_a_second_run_that_fails_keeps_the_first_runs_lake_area(self, tmp_path):
        fetch.run("synth", settings=GeeSettings(months_back=2), provider=SyntheticProvider(), data_dir=tmp_path)
        first_rows = cache.read_lake_area("synth", tmp_path)

        class FailingProvider:
            def s2_month(self, *a, **k):
                raise RuntimeError("network down")

            def s1_month(self, *a, **k):
                raise RuntimeError("network down")

            def catchment(self, *a, **k):
                raise RuntimeError("network down")

            def rainfall_daily(self, *a, **k):
                raise RuntimeError("network down")

        result = fetch.run("synth", settings=GeeSettings(months_back=2), provider=FailingProvider(), data_dir=tmp_path)
        assert result.errors  # the failure is reported, not silently swallowed
        second_rows = cache.read_lake_area("synth", tmp_path)
        assert second_rows == first_rows

        meta = json.loads((cache.gee_dir("synth", tmp_path) / "gee_meta.json").read_text())
        assert meta["lake_area"]["source"] == "cache"
        assert meta["rainfall"]["source"] == "cache"


class TestLakeSeedDam:
    def test_raises_when_no_lake_dam_exists(self):
        cfg = load_site_config("synth", sites_dir=FIXTURES_DIR)
        cfg.dams = [d for d in cfg.dams if d.kind not in fetch.LAKE_DAM_KINDS]
        with pytest.raises(ValueError, match="no dam of kind"):
            fetch.lake_seed_dam(cfg)


class TestMonthStarts:
    def test_returns_oldest_first_ending_at_as_of_month(self):
        from datetime import date
        months = fetch._month_starts(3, as_of=date(2026, 9, 15))
        assert months == [date(2026, 7, 1), date(2026, 8, 1), date(2026, 9, 1)]

    def test_wraps_year_boundary(self):
        from datetime import date
        months = fetch._month_starts(3, as_of=date(2026, 1, 15))
        assert months == [date(2025, 11, 1), date(2025, 12, 1), date(2026, 1, 1)]
