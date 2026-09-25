"""Tests for backend.m1_terrain.download — M1-1 DEM/landcover fetching.

No real network access: OpenTopography requests go through an httpx.MockTransport;
ESA WorldCover and CartoDEM are mosaicked from small synthetic GeoTIFFs on disk.
Per CLAUDE.md rule 12, the API key must never appear in a written file or a raised
error message — several tests check that directly.
"""

from __future__ import annotations

import json
import logging

import httpx
import numpy as np
import pytest
import rasterio
from affine import Affine

from backend.m1_terrain import download as dl

FAKE_KEY = "sekrit-test-key-should-never-leak"


# =============================================================================
# helpers
# =============================================================================


def _write_geotiff(path, bounds, res_deg, value, dtype=np.float32, crs="EPSG:4326", nodata=None):
    west, south, east, north = bounds
    width = max(1, round((east - west) / res_deg))
    height = max(1, round((north - south) / res_deg))
    transform = Affine(res_deg, 0.0, west, 0.0, -res_deg, north)
    data = np.full((height, width), value, dtype=dtype)
    with rasterio.open(
        path, "w", driver="GTiff", width=width, height=height, count=1,
        dtype=data.dtype, crs=crs, transform=transform, nodata=nodata,
    ) as dst:
        dst.write(data, 1)
    return path


def _geotiff_bytes(bounds, res_deg=0.01, value=5.0):
    from io import BytesIO

    west, south, east, north = bounds
    width = max(1, round((east - west) / res_deg))
    height = max(1, round((north - south) / res_deg))
    transform = Affine(res_deg, 0.0, west, 0.0, -res_deg, north)
    data = np.full((height, width), value, dtype=np.float32)
    with rasterio.io.MemoryFile() as mem:
        with mem.open(
            driver="GTiff", width=width, height=height, count=1,
            dtype=data.dtype, crs="EPSG:4326", transform=transform, nodata=-9999.0,
        ) as dst:
            dst.write(data, 1)
        return mem.read()


# =============================================================================
# bbox / api key helpers
# =============================================================================


def test_site_bbox_with_margin(synth_config):
    bbox = dl.site_bbox_with_margin(synth_config, margin_deg=0.01)
    assert bbox == pytest.approx((88.44, 27.44, 88.56, 27.56))


def test_site_bbox_rejects_placeholder(synth_config):
    cfg = synth_config.model_copy(deep=True)
    cfg.domains.far_field.bbox.value = None
    cfg.domains.far_field.bbox.status = "placeholder"
    with pytest.raises(dl.DownloadError, match="placeholder"):
        dl.site_bbox_with_margin(cfg)


def test_api_key_from_environment(monkeypatch):
    monkeypatch.setenv("OPENTOPOGRAPHY_API_KEY", FAKE_KEY)
    assert dl.opentopography_api_key() == FAKE_KEY


def test_api_key_from_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENTOPOGRAPHY_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(f"SOME_OTHER_VAR=x\nOPENTOPOGRAPHY_API_KEY={FAKE_KEY}\n")
    monkeypatch.setattr(dl, "ENV_FILE", env_file)
    assert dl.opentopography_api_key() == FAKE_KEY


def test_api_key_missing_raises_without_leaking(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENTOPOGRAPHY_API_KEY", raising=False)
    monkeypatch.setattr(dl, "ENV_FILE", tmp_path / "nope.env")
    with pytest.raises(dl.DownloadError, match="OPENTOPOGRAPHY_API_KEY"):
        dl.opentopography_api_key()


# =============================================================================
# fetch_opentopography
# =============================================================================


def test_fetch_opentopography_request_covers_grid_bounds_and_writes_provenance(tmp_path, synth_config, monkeypatch):
    monkeypatch.setenv("OPENTOPOGRAPHY_API_KEY", FAKE_KEY)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        params = dict(request.url.params)
        captured["params"] = params
        bbox = (float(params["west"]), float(params["south"]), float(params["east"]), float(params["north"]))
        body = _geotiff_bytes(bbox)
        return httpx.Response(200, headers={"content-type": "image/tiff"}, content=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    raw_dir = tmp_path / "raw"
    entry = dl.fetch_opentopography(synth_config, "srtm_gl1", raw_dir, client=client)

    assert entry["status"] == "fetched"
    assert captured["params"]["demtype"] == "SRTMGL1"
    expected_bbox = dl.site_bbox_with_margin(synth_config)
    got_bbox = (float(captured["params"]["west"]), float(captured["params"]["south"]),
                float(captured["params"]["east"]), float(captured["params"]["north"]))
    assert got_bbox == pytest.approx(expected_bbox)

    out_path = raw_dir / "dem_srtm_gl1.tif"
    assert out_path.exists()
    assert entry["source"] == "src_033"
    assert entry["vertical_datum"] == "EGM96"

    provenance = json.loads((raw_dir / "provenance.json").read_text())
    assert "dem_srtm_gl1" in provenance
    # The outbound request necessarily carries the key in its query string; what must never
    # happen is the key leaking into anything written to disk or raised as an error (rule 12).
    assert FAKE_KEY not in json.dumps(provenance)


def test_no_log_record_contains_the_api_key(tmp_path, synth_config, monkeypatch, caplog):
    """httpx logs 'HTTP Request: GET <url> ...' at INFO by default, and <url> carries
    API_Key=<key> in its query string; download.py silences the httpx logger to WARNING at
    import so that line never fires, and any URL we log ourselves is redacted (rule 12)."""
    monkeypatch.setenv("OPENTOPOGRAPHY_API_KEY", FAKE_KEY)

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        bbox = (float(params["west"]), float(params["south"]), float(params["east"]), float(params["north"]))
        return httpx.Response(200, headers={"content-type": "image/tiff"}, content=_geotiff_bytes(bbox))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    raw_dir = tmp_path / "raw"
    with caplog.at_level(logging.DEBUG):
        dl.fetch_opentopography(synth_config, "srtm_gl1", raw_dir, client=client)

    assert caplog.records, "expected at least our own debug log line to have been emitted"
    for record in caplog.records:
        assert FAKE_KEY not in record.getMessage()

    # The httpx logger is silenced to WARNING, so its INFO-level request-summary line (which
    # would otherwise contain the raw key in the URL) must not have reached caplog at all.
    assert not [r for r in caplog.records if r.name == "httpx" and r.levelno < logging.WARNING]

    # Our own debug line logs the redacted URL, never the raw key.
    own_messages = [r.getMessage() for r in caplog.records if r.name == "m1.download"]
    assert any("API_Key=***" in m for m in own_messages)


def test_fetch_opentopography_error_response_cleans_up_and_never_leaks_key(tmp_path, synth_config, monkeypatch):
    monkeypatch.setenv("OPENTOPOGRAPHY_API_KEY", FAKE_KEY)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, headers={"content-type": "application/json"},
                               json={"error": "bad bbox"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    raw_dir = tmp_path / "raw"
    with pytest.raises(dl.DownloadError) as excinfo:
        dl.fetch_opentopography(synth_config, "copernicus_glo30", raw_dir, client=client)

    assert FAKE_KEY not in str(excinfo.value)
    out_path = raw_dir / "dem_copernicus_glo30.tif"
    assert not out_path.exists()
    assert not (raw_dir / "dem_copernicus_glo30.tif.part").exists()


def test_fetch_opentopography_invalid_raster_body_is_rejected(tmp_path, synth_config, monkeypatch):
    monkeypatch.setenv("OPENTOPOGRAPHY_API_KEY", FAKE_KEY)

    def handler(request: httpx.Request) -> httpx.Response:
        # 200 status but not actually a GeoTIFF
        return httpx.Response(200, headers={"content-type": "image/tiff"}, content=b"not a real tiff")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    raw_dir = tmp_path / "raw"
    with pytest.raises(Exception):
        dl.fetch_opentopography(synth_config, "srtm_gl1", raw_dir, client=client)
    assert not (raw_dir / "dem_srtm_gl1.tif").exists()
    assert not (raw_dir / "dem_srtm_gl1.tif.part").exists()


def test_fetch_opentopography_skips_existing(tmp_path, synth_config):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "dem_srtm_gl1.tif").write_text("placeholder")

    def _boom(request):
        raise AssertionError("should not make a request when the output already exists")

    client = httpx.Client(transport=httpx.MockTransport(_boom))
    entry = dl.fetch_opentopography(synth_config, "srtm_gl1", raw_dir, client=client)
    assert entry == {"file": "dem_srtm_gl1.tif", "status": "skipped_existing"}


def test_fetch_opentopography_force_redownloads(tmp_path, synth_config, monkeypatch):
    monkeypatch.setenv("OPENTOPOGRAPHY_API_KEY", FAKE_KEY)
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "dem_srtm_gl1.tif").write_text("stale placeholder")

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        params = dict(request.url.params)
        bbox = (float(params["west"]), float(params["south"]), float(params["east"]), float(params["north"]))
        return httpx.Response(200, headers={"content-type": "image/tiff"}, content=_geotiff_bytes(bbox))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    entry = dl.fetch_opentopography(synth_config, "srtm_gl1", raw_dir, client=client, force=True)
    assert entry["status"] == "fetched"
    assert calls["n"] == 1


def test_fetch_opentopography_unknown_product_rejected(tmp_path, synth_config):
    with pytest.raises(ValueError, match="unknown"):
        dl.fetch_opentopography(synth_config, "nope", tmp_path / "raw")


# =============================================================================
# worldcover_tiles
# =============================================================================


@pytest.mark.parametrize("bbox,expected", [
    ((88.44, 27.44, 88.56, 27.56), ["N27E087"]),
    ((88.9, 27.9, 89.9, 28.5), ["N27E087"]),
    ((-1.0, -1.0, 0.5, 0.5), ["S03W003", "N00W003", "S03E000", "N00E000"]),
])
def test_worldcover_tiles(bbox, expected):
    assert sorted(dl.worldcover_tiles(bbox)) == sorted(expected)


def test_worldcover_tiles_multi_tile_span():
    tiles = dl.worldcover_tiles((88.9, 27.5, 90.1, 28.5))
    assert set(tiles) == {"N27E087", "N27E090"}


# =============================================================================
# fetch_worldcover
# =============================================================================


def test_fetch_worldcover_mosaics_local_tile(tmp_path, synth_config):
    tile_dir = tmp_path / "tiles"
    tile_dir.mkdir()
    # synth bbox+margin (88.44,27.44,88.56,27.56) falls entirely inside tile N27E087 (87-90E, 27-30N)
    _write_geotiff(tile_dir / "ESA_WorldCover_10m_2021_v200_N27E087_Map.tif",
                   bounds=(87.0, 27.0, 90.0, 30.0), res_deg=0.05, value=10, dtype=np.uint8, nodata=0)

    raw_dir = tmp_path / "raw"
    entry = dl.fetch_worldcover(synth_config, raw_dir, base_url=str(tile_dir))

    assert entry["status"] == "fetched"
    assert entry["tiles_used"] == ["N27E087"]
    assert entry["tiles_skipped"] == []
    out_path = raw_dir / "landcover_esa_worldcover.tif"
    assert out_path.exists()
    with rasterio.open(out_path) as ds:
        data = ds.read(1)
        assert (data == 10).all()
        # rio_merge windows to whole source pixels, so bounds only cover the bbox to within
        # one source cell (res_deg=0.05 above), not exactly.
        left, bottom, right, top = ds.bounds
        tol = 0.05
        assert left <= 88.44 + tol and bottom <= 27.44 + tol and right >= 88.56 - tol and top >= 27.56 - tol


def test_fetch_worldcover_no_tiles_available_raises(tmp_path, synth_config):
    empty_dir = tmp_path / "empty_tiles"
    empty_dir.mkdir()
    with pytest.raises(dl.DownloadError, match="no ESA WorldCover tiles"):
        dl.fetch_worldcover(synth_config, tmp_path / "raw", base_url=str(empty_dir))


def test_fetch_worldcover_skips_existing(tmp_path, synth_config):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "landcover_esa_worldcover.tif").write_text("placeholder")
    entry = dl.fetch_worldcover(synth_config, raw_dir, base_url=str(tmp_path / "nonexistent"))
    assert entry == {"file": "landcover_esa_worldcover.tif", "status": "skipped_existing"}


# =============================================================================
# mosaic_cartodem
# =============================================================================


def test_mosaic_cartodem_two_tiles(tmp_path, synth_config):
    tile_dir = tmp_path / "cartodem_tiles"
    tile_dir.mkdir()
    _write_geotiff(tile_dir / "tile_west.tif", bounds=(88.40, 27.40, 88.50, 27.60), res_deg=0.01, value=1500.0)
    _write_geotiff(tile_dir / "tile_east.tif", bounds=(88.50, 27.40, 88.60, 27.60), res_deg=0.01, value=1600.0)

    raw_dir = tmp_path / "raw"
    entry = dl.mosaic_cartodem(synth_config, tile_dir, raw_dir, version="v1", vertical_datum="WGS84_ellipsoid")

    assert entry["status"] == "fetched"
    assert entry["version"] == "v1"
    assert entry["vertical_datum"] == "WGS84_ellipsoid"
    out_path = raw_dir / "dem_cartodem.tif"
    assert out_path.exists()
    with rasterio.open(out_path) as ds:
        left, bottom, right, top = ds.bounds
        tol = 0.01  # one source pixel; rio_merge windows to whole source pixels
        assert left <= 88.44 + tol and right >= 88.56 - tol


def test_mosaic_cartodem_empty_dir_raises(tmp_path, synth_config):
    tile_dir = tmp_path / "empty"
    tile_dir.mkdir()
    with pytest.raises(dl.DownloadError, match="no .tif tiles"):
        dl.mosaic_cartodem(synth_config, tile_dir, tmp_path / "raw")


def test_mosaic_cartodem_mixed_crs_rejected(tmp_path, synth_config):
    tile_dir = tmp_path / "mixed"
    tile_dir.mkdir()
    _write_geotiff(tile_dir / "a.tif", bounds=(88.40, 27.40, 88.50, 27.60), res_deg=0.01, value=1.0, crs="EPSG:4326")
    _write_geotiff(tile_dir / "b.tif", bounds=(88.50, 27.40, 88.60, 27.60), res_deg=0.01, value=1.0, crs="EPSG:32645")
    with pytest.raises(dl.DownloadError, match="mixed CRS"):
        dl.mosaic_cartodem(synth_config, tile_dir, tmp_path / "raw")


def test_mosaic_cartodem_missing_version_logs_warning(tmp_path, synth_config, caplog):
    tile_dir = tmp_path / "tiles"
    tile_dir.mkdir()
    _write_geotiff(tile_dir / "a.tif", bounds=(88.40, 27.40, 88.60, 27.60), res_deg=0.01, value=1.0)
    with caplog.at_level(logging.WARNING, logger="m1.download"):
        entry = dl.mosaic_cartodem(synth_config, tile_dir, tmp_path / "raw")
    assert entry["version"] is None
    assert entry["vertical_datum"] is None
    assert any("version" in r.message for r in caplog.records)


def test_mosaic_cartodem_skips_existing(tmp_path, synth_config):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "dem_cartodem.tif").write_text("placeholder")
    entry = dl.mosaic_cartodem(synth_config, tmp_path / "nonexistent_tiles", raw_dir)
    assert entry == {"file": "dem_cartodem.tif", "status": "skipped_existing"}
