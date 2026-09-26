"""Tests for backend.m7_gee.imagery. No Earth Engine access needed -- `convert()` only reads
GeoTIFFs already on disk; `refresh()`'s live path is exercised separately by monkeypatching
`live_render.render_event_rgb`.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from backend.m7_gee import cache, imagery


class _SourcedValue:
    def __init__(self, value, source):
        self.value = value
        self.source = source


class _Event:
    def __init__(self, id, imagery_pre_event, imagery_post_event):  # noqa: A002 - matches Event.id
        self.id = id
        self.imagery_pre_event = imagery_pre_event
        self.imagery_post_event = imagery_post_event


class _Site:
    def __init__(self, id):  # noqa: A002 - matches Site.id
        self.id = id


class _Cfg:
    def __init__(self, events, site_id="testsite"):
        self.events = events
        self.site = _Site(site_id)


def _write_rgb_tif(path, width=40, height=30):
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.random.default_rng(0).integers(0, 256, size=(3, height, width), dtype=np.uint8)
    transform = from_origin(657830.0, 3059580.0, 10.0, 10.0)
    with rasterio.open(
        path, "w", driver="GTiff", width=width, height=height, count=3, dtype=np.uint8,
        crs="EPSG:32645", transform=transform,
    ) as dst:
        dst.write(arr)
    return arr


@pytest.fixture
def cfg_and_root(tmp_path):
    """A site config double whose event points at a real staged `..._rgb.tif` under a fake
    repo root, mirroring `cache/gee/<site_id>/<site_id>_<phase>_event.tif` -> `..._rgb.tif`."""
    repo_root = tmp_path / "repo"
    pre_tif = repo_root / "cache" / "gee" / "testsite" / "testsite_pre_event_rgb.tif"
    post_tif = repo_root / "cache" / "gee" / "testsite" / "testsite_post_event_rgb.tif"
    _write_rgb_tif(pre_tif)
    _write_rgb_tif(post_tif)

    event = _Event(
        id="synth_event_2020",
        imagery_pre_event=_SourcedValue("2020-01-01", "cache/gee/testsite/testsite_pre_event.tif"),
        imagery_post_event=_SourcedValue("2020-01-10", "cache/gee/testsite/testsite_post_event.tif"),
    )
    return _Cfg(events=[event]), repo_root


class TestEventForImagery:
    def test_raises_when_no_event_has_both_dates_set(self):
        event = _Event(id="e", imagery_pre_event=_SourcedValue("2020-01-01", "x.tif"),
                        imagery_post_event=_SourcedValue(None, "y.tif"))
        with pytest.raises(ValueError, match="no event with both"):
            imagery._event_for_imagery(_Cfg(events=[event]))


class TestRawRgbPath:
    def test_inserts_rgb_before_suffix(self, tmp_path):
        path = imagery.raw_rgb_path("cache/gee/teesta/teesta_pre_event.tif", tmp_path)
        assert path == tmp_path / "cache" / "gee" / "teesta" / "teesta_pre_event_rgb.tif"

    def test_raises_on_empty_source(self, tmp_path):
        with pytest.raises(ValueError, match="source is not set"):
            imagery.raw_rgb_path(None, tmp_path)


class TestConvert:
    def test_writes_png_fallback_and_manifest(self, cfg_and_root, tmp_path):
        cfg, repo_root = cfg_and_root
        data_dir = tmp_path / "data"

        manifest_path = imagery.convert("testsite", cfg=cfg, data_dir=data_dir, repo_root=repo_root)

        manifest = json.loads(manifest_path.read_text())
        assert manifest["site_id"] == "testsite"
        assert manifest["event_id"] == "synth_event_2020"
        assert [e["phase"] for e in manifest["imagery"]] == ["pre", "post"]

        pre = manifest["imagery"][0]
        assert pre["date"] == "2020-01-01"
        png_path = cache.gee_dir("testsite", data_dir) / pre["png"]
        fallback_path = cache.gee_dir("testsite", data_dir) / pre["fallback_png"]
        assert png_path.is_file()
        assert fallback_path.is_file()

        with rasterio.open(png_path) as ds:
            assert (ds.width, ds.height) == (40, 30)
        with rasterio.open(fallback_path) as ds:
            assert max(ds.width, ds.height) <= imagery.FALLBACK_MAX_PX

        south, west = pre["bounds_latlng"][0]
        north, east = pre["bounds_latlng"][1]
        assert south < north and west < east
        assert 27 < south < 28 and 88 < west < 89  # sanity check: Teesta-area lat/lon, not raw UTM

    def test_missing_geotiff_raises_filenotfound_naming_the_path(self, tmp_path):
        event = _Event(
            id="e", imagery_pre_event=_SourcedValue("2020-01-01", "cache/gee/nosite/nosite_pre_event.tif"),
            imagery_post_event=_SourcedValue("2020-01-10", "cache/gee/nosite/nosite_post_event.tif"),
        )
        cfg = _Cfg(events=[event])
        with pytest.raises(FileNotFoundError, match="nosite_pre_event_rgb.tif"):
            imagery.convert("nosite", cfg=cfg, data_dir=tmp_path / "data", repo_root=tmp_path / "repo")

    def test_too_few_bands_raises(self, cfg_and_root, tmp_path):
        cfg, repo_root = cfg_and_root
        one_band = repo_root / "cache" / "gee" / "testsite" / "testsite_pre_event_rgb.tif"
        with rasterio.open(one_band, "w", driver="GTiff", width=5, height=5, count=1,
                            dtype=np.uint8, crs="EPSG:32645",
                            transform=from_origin(0, 0, 1, 1)) as dst:
            dst.write(np.zeros((1, 5, 5), dtype=np.uint8))
        with pytest.raises(ValueError, match="band"):
            imagery.convert("testsite", cfg=cfg, data_dir=tmp_path / "data", repo_root=repo_root)

    def test_no_event_with_imagery_raises(self, tmp_path):
        event = _Event(id="e", imagery_pre_event=_SourcedValue(None, "x.tif"),
                        imagery_post_event=_SourcedValue(None, "y.tif"))
        cfg = _Cfg(events=[event])
        with pytest.raises(ValueError, match="no event with both"):
            imagery.convert("testsite", cfg=cfg, data_dir=tmp_path / "data", repo_root=tmp_path)

    def test_scene_ids_merged_into_gee_meta(self, cfg_and_root, tmp_path):
        cfg, repo_root = cfg_and_root
        data_dir = tmp_path / "data"
        scene_ids = {"pre": ["S2_PRE_A"], "post": ["S2_POST_A", "S2_POST_B"]}

        imagery.convert("testsite", cfg=cfg, data_dir=data_dir, repo_root=repo_root,
                         scene_ids=scene_ids)

        meta = cache.read_json("testsite", "gee_meta.json", data_dir)
        assert meta["imagery"]["scene_ids"] == ["S2_POST_A", "S2_POST_B", "S2_PRE_A"]
        assert meta["imagery"]["acquisition_dates"] == ["2020-01-01", "2020-01-10"]
        assert meta["imagery"]["source"] == "cache"
        assert meta["imagery"]["dataset"] == "sentinel-2"

    def test_no_scene_ids_leaves_gee_meta_untouched(self, cfg_and_root, tmp_path):
        cfg, repo_root = cfg_and_root
        data_dir = tmp_path / "data"

        imagery.convert("testsite", cfg=cfg, data_dir=data_dir, repo_root=repo_root)

        assert cache.read_json("testsite", "gee_meta.json", data_dir) is None

    def test_scene_ids_merge_preserves_other_gee_meta_products(self, cfg_and_root, tmp_path):
        cfg, repo_root = cfg_and_root
        data_dir = tmp_path / "data"
        cache.write_json("testsite", "gee_meta.json", {"lake_area": {"source": "cache"}}, data_dir)

        imagery.convert("testsite", cfg=cfg, data_dir=data_dir, repo_root=repo_root,
                         scene_ids={"pre": ["S2_A"], "post": []})

        meta = cache.read_json("testsite", "gee_meta.json", data_dir)
        assert meta["lake_area"] == {"source": "cache"}
        assert meta["imagery"]["scene_ids"] == ["S2_A"]


class TestRefresh:
    def test_live_success_sets_source_live(self, cfg_and_root, tmp_path, monkeypatch):
        cfg, repo_root = cfg_and_root

        def fake_render(cfg_, event_, repo_root=None, ee_project=None):
            return None  # existing staged tifs already satisfy convert()

        monkeypatch.setattr("backend.m7_gee.live_render.render_event_rgb", fake_render)

        result = imagery.refresh("testsite", cfg=cfg, data_dir=tmp_path / "data", repo_root=repo_root)
        assert result.source == "live"
        assert not result.errors
        assert result.manifest_path.is_file()

    def test_live_failure_falls_back_to_cache(self, cfg_and_root, tmp_path, monkeypatch):
        cfg, repo_root = cfg_and_root

        def failing_render(*a, **k):
            raise RuntimeError("no Earth Engine credentials")

        monkeypatch.setattr("backend.m7_gee.live_render.render_event_rgb", failing_render)

        result = imagery.refresh("testsite", cfg=cfg, data_dir=tmp_path / "data", repo_root=repo_root)
        assert result.source == "cache"
        assert any("no Earth Engine credentials" in e for e in result.errors)
        assert result.manifest_path.is_file()  # still converts whatever was already staged
