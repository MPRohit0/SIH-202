"""Tests for backend.m7_gee.observed. Runs entirely on a synthetic GeoJSON fixture -- no real
digitized flood outline needed (CLAUDE.md rule 2)."""

from __future__ import annotations

import json

import pytest

from backend.m7_gee import cache, observed


class _DateValue:
    def __init__(self, value):
        self.value = value


class _Event:
    def __init__(self, id, onset="2023-10-04"):  # noqa: A002 - matches Event.id
        self.id = id
        self.onset = _DateValue(onset)


class _Site:
    def __init__(self, id):  # noqa: A002 - matches Site.id
        self.id = id


class _Cfg:
    def __init__(self, events, site_id="testsite"):
        self.events = events
        self.site = _Site(site_id)


FEATURE_COLLECTION = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[88.6, 27.6], [88.61, 27.6],
                                                                              [88.61, 27.61], [88.6, 27.6]]]},
         "properties": {}},
    ],
}


@pytest.fixture
def cfg():
    return _Cfg(events=[_Event(id="synth_event_2020")])


@pytest.fixture
def source_geojson(tmp_path):
    path = tmp_path / "flood_extent.geojson"
    path.write_text(json.dumps(FEATURE_COLLECTION))
    return path


class TestConvert:
    def test_stamps_contract_properties(self, cfg, source_geojson, tmp_path):
        data_dir = tmp_path / "data"

        out_path = observed.convert(
            "testsite", "synth_event_2020", source_geojson, "j.doe",
            cfg=cfg, data_dir=data_dir,
        )

        payload = json.loads(out_path.read_text())
        assert out_path == cache.gee_dir("testsite", data_dir) / "observed" / "synth_event_2020_observed.geojson"
        props = payload["features"][0]["properties"]
        assert props == {
            "event_id": "synth_event_2020", "method": "manual_digitized",
            "imagery_ref": "synth_event_2020_post", "digitized_by": "j.doe",
            "date": "2023-10-04", "kind": "observed",
        }

    def test_defaults_date_to_event_onset_and_imagery_ref(self, cfg, source_geojson, tmp_path):
        out_path = observed.convert(
            "testsite", "synth_event_2020", source_geojson, "j.doe", cfg=cfg, data_dir=tmp_path / "data",
        )
        props = json.loads(out_path.read_text())["features"][0]["properties"]
        assert props["date"] == "2023-10-04"
        assert props["imagery_ref"] == "synth_event_2020_post"

    def test_explicit_date_and_imagery_ref_override_defaults(self, cfg, source_geojson, tmp_path):
        out_path = observed.convert(
            "testsite", "synth_event_2020", source_geojson, "j.doe", cfg=cfg, data_dir=tmp_path / "data",
            date="2023-10-10", imagery_ref="custom_ref",
        )
        props = json.loads(out_path.read_text())["features"][0]["properties"]
        assert props["date"] == "2023-10-10"
        assert props["imagery_ref"] == "custom_ref"

    def test_change_detection_method(self, cfg, source_geojson, tmp_path):
        out_path = observed.convert(
            "testsite", "synth_event_2020", source_geojson, "pipeline",
            method="change_detection", cfg=cfg, data_dir=tmp_path / "data",
        )
        props = json.loads(out_path.read_text())["features"][0]["properties"]
        assert props["method"] == "change_detection"

    def test_single_feature_geojson_is_wrapped(self, cfg, tmp_path):
        source_path = tmp_path / "single.geojson"
        source_path.write_text(json.dumps(FEATURE_COLLECTION["features"][0]))

        out_path = observed.convert(
            "testsite", "synth_event_2020", source_path, "j.doe", cfg=cfg, data_dir=tmp_path / "data",
        )
        payload = json.loads(out_path.read_text())
        assert payload["type"] == "FeatureCollection"
        assert len(payload["features"]) == 1

    def test_missing_source_raises_filenotfound(self, cfg, tmp_path):
        with pytest.raises(FileNotFoundError, match="missing.geojson"):
            observed.convert("testsite", "synth_event_2020", tmp_path / "missing.geojson", "j.doe",
                              cfg=cfg, data_dir=tmp_path / "data")

    def test_unknown_event_raises(self, cfg, source_geojson, tmp_path):
        with pytest.raises(ValueError, match="no event 'nope'"):
            observed.convert("testsite", "nope", source_geojson, "j.doe", cfg=cfg, data_dir=tmp_path / "data")

    def test_not_geojson_raises(self, cfg, tmp_path):
        bad = tmp_path / "bad.geojson"
        bad.write_text(json.dumps({"type": "NotGeoJSON"}))
        with pytest.raises(ValueError, match="not a GeoJSON"):
            observed.convert("testsite", "synth_event_2020", bad, "j.doe", cfg=cfg, data_dir=tmp_path / "data")

    def test_empty_feature_collection_raises(self, cfg, tmp_path):
        empty = tmp_path / "empty.geojson"
        empty.write_text(json.dumps({"type": "FeatureCollection", "features": []}))
        with pytest.raises(ValueError, match="no features"):
            observed.convert("testsite", "synth_event_2020", empty, "j.doe", cfg=cfg, data_dir=tmp_path / "data")
