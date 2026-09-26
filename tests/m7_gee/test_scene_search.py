"""Tests for backend.m7_gee.scene_search.

No real Earth Engine access: `ee` is replaced in `sys.modules` with `fake_ee.FakeEE`, a small
in-memory scene catalogue (see that module's docstring). Thumbnail "downloads" are captured by
monkeypatching `scene_search.httpx.get` instead of hitting the network.
"""

from __future__ import annotations

import sys

import pytest

from backend.m7_gee import scene_search as ss
from backend.shared.site_config import load_site_config

from .fake_ee import FakeEE

FIXTURES_DIR = "tests/fixtures/shared"


@pytest.fixture
def fake_ee(monkeypatch):
    fake = FakeEE()
    monkeypatch.setitem(sys.modules, "ee", fake)
    return fake


@pytest.fixture
def site_config():
    return load_site_config("synth", sites_dir=FIXTURES_DIR)


def _populate(fake: FakeEE) -> None:
    fake.add_scene(ss.S2_COLLECTION, "S2_CLEAR", date="2023-10-05", cloud_pct=5.0, cloud_pct_aoi=0.02)
    fake.add_scene(ss.S2_COLLECTION, "S2_CLOUDY", date="2023-10-08", cloud_pct=80.0, cloud_pct_aoi=0.75)
    fake.add_scene(ss.S2_COLLECTION, "S2_OUT_OF_RANGE", date="2023-11-01", cloud_pct=1.0, cloud_pct_aoi=0.0)
    fake.add_scene(ss.S1_COLLECTION, "S1_ASC", date="2023-10-06", orbit_pass="ASCENDING")
    fake.add_scene(ss.S1_COLLECTION, "S1_DESC", date="2023-10-09", orbit_pass="DESCENDING")


class TestSearchSentinel2:
    def test_filters_by_date_and_returns_newest_first(self, fake_ee, site_config):
        _populate(fake_ee)
        aoi = ss._aoi_geometry(site_config, "far_field")
        results = ss.search_sentinel2(aoi, "2023-10-01", "2023-10-31", max_cloud_pct=None, max_scenes=20)
        assert [r["scene_id"] for r in results] == ["S2_CLOUDY", "S2_CLEAR"]

    def test_max_cloud_pct_filters_on_whole_tile_metadata(self, fake_ee, site_config):
        _populate(fake_ee)
        aoi = ss._aoi_geometry(site_config, "far_field")
        results = ss.search_sentinel2(aoi, "2023-10-01", "2023-10-31", max_cloud_pct=10.0, max_scenes=20)
        assert [r["scene_id"] for r in results] == ["S2_CLEAR"]

    def test_cloud_pct_aoi_is_a_percentage_derived_from_the_scl_fraction(self, fake_ee, site_config):
        _populate(fake_ee)
        aoi = ss._aoi_geometry(site_config, "far_field")
        results = ss.search_sentinel2(aoi, "2023-10-01", "2023-10-31", max_cloud_pct=None, max_scenes=20)
        clear = next(r for r in results if r["scene_id"] == "S2_CLEAR")
        assert clear["cloud_pct_aoi"] == pytest.approx(2.0)
        assert clear["cloud_pct_scene"] == pytest.approx(5.0)


class TestSearchSentinel1:
    def test_has_no_cloud_percentage(self, fake_ee, site_config):
        _populate(fake_ee)
        aoi = ss._aoi_geometry(site_config, "far_field")
        results = ss.search_sentinel1(aoi, "2023-10-01", "2023-10-31", max_scenes=20)
        assert [r["scene_id"] for r in results] == ["S1_DESC", "S1_ASC"]
        assert all(r["cloud_pct_scene"] is None and r["cloud_pct_aoi"] is None for r in results)
        assert "DESCENDING" in results[0]["product"]


class TestRun:
    def test_writes_manifest_and_thumbnails(self, fake_ee, monkeypatch, tmp_path):
        _populate(fake_ee)

        def fake_get(url, timeout=None, follow_redirects=None):
            class Resp:
                content = b"fake-png-bytes"

                def raise_for_status(self):
                    pass

            return Resp()

        monkeypatch.setattr(ss.httpx, "get", fake_get)
        monkeypatch.setattr(ss, "load_site_config",
                             lambda site_id: load_site_config("synth", sites_dir=FIXTURES_DIR))

        out_dir = tmp_path / "scene_search"
        scenes = ss.run(
            "synth", "2023-10-01", "2023-10-31", "far_field", ["s2", "s1"],
            max_cloud_pct=None, max_scenes_per_satellite=20, out_dir=out_dir,
            ee_project=None, save_thumbnails=True,
        )

        assert len(scenes) == 4
        manifest = out_dir / "scenes.csv"
        assert manifest.is_file()
        rows = manifest.read_text(encoding="utf-8").splitlines()
        assert rows[0] == "date,satellite,scene_id,cloud_pct_scene,cloud_pct_aoi,product,thumbnail_path"
        assert len(rows) == 1 + len(scenes)

        for s in scenes:
            assert s.thumbnail_path is not None
            assert (out_dir / "thumbnails" / f"{s.scene_id}.png").read_bytes() == b"fake-png-bytes"

    def test_no_thumbnails_skips_downloads(self, fake_ee, monkeypatch, tmp_path):
        _populate(fake_ee)
        monkeypatch.setattr(ss, "load_site_config",
                             lambda site_id: load_site_config("synth", sites_dir=FIXTURES_DIR))

        def fail_get(*a, **k):
            raise AssertionError("should not download thumbnails")

        monkeypatch.setattr(ss.httpx, "get", fail_get)

        scenes = ss.run(
            "synth", "2023-10-01", "2023-10-31", "far_field", ["s2"],
            max_cloud_pct=None, max_scenes_per_satellite=20, out_dir=tmp_path / "out",
            ee_project=None, save_thumbnails=False,
        )
        assert all(s.thumbnail_path is None for s in scenes)


class TestAoiGeometry:
    def test_raises_on_null_bbox(self, fake_ee):
        placeholder_config = load_site_config("synth", sites_dir=FIXTURES_DIR)
        placeholder_config.domains.near_field.bbox.value = None
        with pytest.raises(ValueError, match="null value"):
            ss._aoi_geometry(placeholder_config, "near_field")


class TestMainCli:
    def test_unknown_satellite_errors_out(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            ss.main(["synth", "--start", "2023-10-01", "--end", "2023-10-31", "--satellites", "s2,s99"])
        assert exc_info.value.code == 2
        assert "unknown satellite" in capsys.readouterr().err


class TestEeInitialize:
    """`_ee_initialize` prefers a service account from the environment/`.env` over the default
    `ee.Initialize()` project flow, and never touches the real `.env` file in tests."""

    def test_no_credentials_uses_project_initialize(self, fake_ee, monkeypatch):
        monkeypatch.delenv(ss.GEE_SA_EMAIL_ENV, raising=False)
        monkeypatch.delenv(ss.GEE_SA_KEY_PATH_ENV, raising=False)
        monkeypatch.setattr(ss, "ENV_FILE", ss.Path("/nonexistent/.env"))
        ss._ee_initialize("my-project")
        assert fake_ee.initialized_with_project == "my-project"
        assert fake_ee.initialized_with_credentials is None

    def test_service_account_env_vars_used_when_key_file_exists(self, fake_ee, monkeypatch, tmp_path):
        key_path = tmp_path / "key.json"
        key_path.write_text("{}", encoding="utf-8")
        monkeypatch.setenv(ss.GEE_SA_EMAIL_ENV, "sa@example.iam.gserviceaccount.com")
        monkeypatch.setenv(ss.GEE_SA_KEY_PATH_ENV, str(key_path))
        ss._ee_initialize(None)
        assert fake_ee.initialized_with_credentials == (
            "service_account_credentials", "sa@example.iam.gserviceaccount.com", str(key_path))

    def test_service_account_key_path_missing_raises(self, fake_ee, monkeypatch):
        monkeypatch.setenv(ss.GEE_SA_EMAIL_ENV, "sa@example.iam.gserviceaccount.com")
        monkeypatch.setenv(ss.GEE_SA_KEY_PATH_ENV, "/nonexistent/key.json")
        with pytest.raises(RuntimeError, match="Earth Engine initialisation failed"):
            ss._ee_initialize(None)
