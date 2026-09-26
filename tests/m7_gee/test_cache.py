"""Tests for backend.m7_gee.cache."""

from __future__ import annotations

import json

import pytest

from backend.m7_gee import cache


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path


class TestLakeAreaRoundTrip:
    def test_write_then_read_preserves_types(self, data_dir):
        rows = [
            {"date": "2026-08-01", "area_m2": 123456.0, "method": "s2_water_index",
             "cloud_pct": 5.0, "scene_ids": "S2_A;S2_B"},
            {"date": "2026-09-01", "area_m2": None, "method": None, "cloud_pct": None, "scene_ids": ""},
        ]
        cache.write_lake_area("teesta", rows, data_dir)
        back = cache.read_lake_area("teesta", data_dir)
        assert back[0]["area_m2"] == pytest.approx(123456.0)
        assert back[0]["cloud_pct"] == pytest.approx(5.0)
        assert back[1]["area_m2"] is None

    def test_header_matches_the_contract_exactly(self, data_dir):
        cache.write_lake_area("teesta", [], data_dir)
        path = cache.gee_dir("teesta", data_dir) / "lake_area.csv"
        assert path.read_text().splitlines()[0] == "date,area_m2,method,cloud_pct,scene_ids"


class TestMergeLakeRows:
    def test_fresh_rows_replace_same_date_rows(self):
        cached = [{"date": "2026-08-01", "area_m2": 100.0}]
        fresh = [{"date": "2026-08-01", "area_m2": 200.0}]
        merged = cache.merge_lake_rows(cached, fresh)
        assert merged == [{"date": "2026-08-01", "area_m2": 200.0}]

    def test_cached_rows_not_in_fresh_are_kept(self):
        cached = [{"date": "2026-07-01", "area_m2": 90.0}, {"date": "2026-08-01", "area_m2": 100.0}]
        fresh = [{"date": "2026-09-01", "area_m2": 300.0}]
        merged = cache.merge_lake_rows(cached, fresh)
        assert [r["date"] for r in merged] == ["2026-07-01", "2026-08-01", "2026-09-01"]

    def test_output_is_sorted_by_date(self):
        cached = [{"date": "2026-09-01", "area_m2": 1.0}]
        fresh = [{"date": "2026-07-01", "area_m2": 2.0}]
        merged = cache.merge_lake_rows(cached, fresh)
        assert [r["date"] for r in merged] == ["2026-07-01", "2026-09-01"]


class TestAtomicWrites:
    def test_write_json_leaves_no_tmp_file_behind(self, data_dir):
        cache.write_json("teesta", "gee_meta.json", {"a": 1}, data_dir)
        gee = cache.gee_dir("teesta", data_dir)
        assert sorted(p.name for p in gee.iterdir()) == ["gee_meta.json"]
        assert json.loads((gee / "gee_meta.json").read_text()) == {"a": 1}

    def test_write_json_overwrites_cleanly(self, data_dir):
        cache.write_json("teesta", "recheck.json", {"a": 1}, data_dir)
        cache.write_json("teesta", "recheck.json", {"a": 2}, data_dir)
        assert cache.read_json("teesta", "recheck.json", data_dir) == {"a": 2}


class TestLoadLayers:
    def test_validates_against_the_contract_schema(self, data_dir):
        cache.write_lake_area("teesta", [
            {"date": "2026-08-01", "area_m2": 1000.0, "method": "s2_water_index",
             "cloud_pct": 2.0, "scene_ids": "S2_A"},
        ], data_dir)
        cache.write_lake_latest("teesta", {
            "type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[88.2, 27.9], [88.21, 27.9],
                                                                                 [88.21, 27.91], [88.2, 27.9]]]},
            "properties": {"date": "2026-08-01", "area_m2": 1000.0, "method": "s2_water_index"},
        }, data_dir)
        cache.write_rainfall("teesta", [
            {"date": "2026-09-20", "precip_mm": 1.0, "dataset": "chirps", "aggregation": "catchment_mean_daily_total"},
        ], data_dir)
        cache.write_json("teesta", "gee_meta.json", {"fetched_at": "2026-09-24T10:15:00Z"}, data_dir)
        cache.write_json("teesta", "recheck.json", {"outdated": False, "change_pct": 1.0, "threshold_pct": 10.0}, data_dir)

        layers = cache.load_layers("teesta", data_dir)

        from backend.m0_api import schemas
        schemas.validate("gee_layers.schema.json", layers)
        assert layers["source"] == "cache"

    def test_source_is_screenshot_fallback_when_only_screenshots_exist(self, data_dir):
        fallback_dir = cache.gee_dir("teesta", data_dir) / "fallback"
        fallback_dir.mkdir(parents=True)
        (fallback_dir / "shot.png").write_bytes(b"x")
        layers = cache.load_layers("teesta", data_dir)
        assert layers["source"] == "screenshot_fallback"
        assert layers["lake_area_series"] == []

    def test_imagery_populated_from_manifest(self, data_dir):
        cache.write_json("teesta", "gee_meta.json", {"fetched_at": "2026-09-24T10:15:00Z"}, data_dir)
        cache.write_json("teesta", "recheck.json", {"outdated": False, "change_pct": 1.0, "threshold_pct": 10.0}, data_dir)
        cache.write_json("teesta", "imagery/manifest.json", {
            "site_id": "teesta", "event_id": "sikkim_glof_2023",
            "imagery": [{
                "event_id": "sikkim_glof_2023", "phase": "pre", "date": "2023-09-28",
                "png": "imagery/sikkim_glof_2023_pre_20230928.png",
                "fallback_png": "imagery/sikkim_glof_2023_pre_20230928_fallback.png",
                "bounds_latlng": [[27.5, 88.6], [27.6, 88.7]], "width": 902, "height": 1010,
            }],
        }, data_dir)

        layers = cache.load_layers("teesta", data_dir)

        assert layers["imagery"] == [{
            "event_id": "sikkim_glof_2023", "phase": "pre", "date": "2023-09-28",
            "url": "/api/v1/files/teesta/gee/imagery/sikkim_glof_2023_pre_20230928.png",
            "fallback_url": "/api/v1/files/teesta/gee/imagery/sikkim_glof_2023_pre_20230928_fallback.png",
            "bounds_latlng": [[27.5, 88.6], [27.6, 88.7]],
        }]
        from backend.m0_api import schemas
        schemas.validate("gee_layers.schema.json", layers)

    def test_imagery_is_empty_when_no_manifest(self, data_dir):
        assert cache.read_imagery("teesta", data_dir) == []

    def test_observed_extents_populated_from_disk(self, data_dir):
        cache.write_json("teesta", "gee_meta.json", {"fetched_at": "2026-09-24T10:15:00Z"}, data_dir)
        cache.write_json("teesta", "recheck.json", {"outdated": False, "change_pct": 1.0, "threshold_pct": 10.0}, data_dir)
        cache.write_json("teesta", "observed/sikkim_glof_2023_observed.geojson", {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": None,
                          "properties": {"event_id": "sikkim_glof_2023", "method": "manual_digitized"}}],
        }, data_dir)

        layers = cache.load_layers("teesta", data_dir)

        assert layers["observed_extents"] == [{
            "event_id": "sikkim_glof_2023",
            "url": "/api/v1/files/teesta/gee/observed/sikkim_glof_2023_observed.geojson",
            "method": "manual_digitized",
        }]
        from backend.m0_api import schemas
        schemas.validate("gee_layers.schema.json", layers)

    def test_observed_extents_empty_when_no_directory(self, data_dir):
        assert cache.read_observed_extents("teesta", data_dir) == []
