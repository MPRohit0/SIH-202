"""Tests for backend.shared.grid — canonical grids, lon/lat indexing, resampling."""

import json
import warnings

import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.transform import from_bounds

from backend.shared.grid import (
    CanonicalGrid,
    build_farfield_grid,
    build_nearfield_grid,
    build_site_grids,
    lonlat_to_rowcol,
    resample_to_grid,
    rowcol_to_lonlat,
    write_grid_raster,
)
from backend.shared.site_config import load_site_config

from .conftest import SITES_DIR

GRID_JSON_KEYS = {
    "contract_version", "site_id", "grid_id", "crs_epsg", "origin_x", "origin_y",
    "cell_size_m", "width", "height", "nodata", "pixel_is",
}


def projected_bounds(bbox, epsg):
    t = Transformer.from_crs(4326, epsg, always_xy=True)
    return t.transform_bounds(*bbox, densify_pts=21)


@pytest.fixture
def far(synth_config):
    return build_farfield_grid(synth_config)


@pytest.fixture
def near(synth_config, far):
    return build_nearfield_grid(synth_config, far)


# --------------------------------------------------------------------------- far-field grid


def test_farfield_basic_fields(far):
    assert far.site_id == "synth"
    assert far.grid_id == "farfield"
    assert far.crs_epsg == 32645
    assert far.cell_size_m == 30.0
    assert far.nodata == -9999.0
    assert far.pixel_is == "area"
    assert far.shape == (far.height, far.width)


def test_farfield_origin_snapped_to_cell_multiple(far):
    assert far.origin_x % far.cell_size_m == 0
    assert far.origin_y % far.cell_size_m == 0


def test_farfield_covers_bbox_minimally(synth_config, far):
    minx, miny, maxx, maxy = projected_bounds(synth_config.domains.far_field.bbox.value, 32645)
    left, bottom, right, top = far.bounds
    cs = far.cell_size_m
    # covers the whole projected bbox ...
    assert left <= minx and bottom <= miny and right >= maxx and top >= maxy
    # ... with less than one extra cell on each side
    assert minx - left < cs and miny - bottom < cs and right - maxx < cs and top - maxy < cs


def test_farfield_transform(far):
    t = far.transform
    assert (t.a, t.b, t.c) == (far.cell_size_m, 0.0, far.origin_x)
    assert (t.d, t.e, t.f) == (0.0, -far.cell_size_m, far.origin_y)
    assert far.crs.to_epsg() == 32645


def test_bounds_latlng_contains_bbox(synth_config, far):
    (south, west), (north, east) = far.bounds_latlng
    min_lon, min_lat, max_lon, max_lat = synth_config.domains.far_field.bbox.value
    assert south <= min_lat and west <= min_lon and north >= max_lat and east >= max_lon


def test_null_bbox_raises(synth_config):
    cfg = synth_config.model_copy(deep=True)
    cfg.domains.far_field.bbox.value = None
    with pytest.raises(ValueError, match="bbox"):
        build_farfield_grid(cfg)


# --------------------------------------------------------------------------- near-field grid


def test_nearfield_fields(near):
    assert near.grid_id == "nearfield"
    assert near.cell_size_m == 10.0
    assert near.crs_epsg == 32645


def test_nearfield_nests_in_farfield(near, far):
    assert (near.origin_x - far.origin_x) % far.cell_size_m == 0
    assert (far.origin_y - near.origin_y) % far.cell_size_m == 0
    assert (near.width * near.cell_size_m) % far.cell_size_m == 0
    assert (near.height * near.cell_size_m) % far.cell_size_m == 0
    nl, nb, nr, nt = near.bounds
    fl, fb, fr, ft = far.bounds
    assert fl <= nl and fb <= nb and nr <= fr and nt <= ft


def test_nearfield_covers_bbox(synth_config, near):
    minx, miny, maxx, maxy = projected_bounds(synth_config.domains.near_field.bbox.value, 32645)
    left, bottom, right, top = near.bounds
    assert left <= minx and bottom <= miny and right >= maxx and top >= maxy


def test_nearfield_non_dividing_cell_size_raises(synth_config, far):
    odd_far = far.model_copy(update={"cell_size_m": 25.0})
    with pytest.raises(ValueError, match="divide"):
        build_nearfield_grid(synth_config, odd_far)


def test_build_site_grids(synth_config):
    grids = build_site_grids(synth_config)
    assert set(grids) == {"farfield", "nearfield"}
    assert grids["farfield"].grid_id == "farfield"


# --------------------------------------------------------------------------- grid.json


def test_grid_json_round_trip(far, tmp_path):
    path = tmp_path / "grid.json"
    far.to_json(path)
    raw = json.loads(path.read_text())
    assert set(raw) == GRID_JSON_KEYS
    assert raw["contract_version"] == "0.2.0"
    assert CanonicalGrid.from_json(path) == far


def test_grid_is_frozen(far):
    with pytest.raises(Exception):
        far.width = 1


# --------------------------------------------------------------------------- lon/lat -> row/col


def test_upper_left_corner_is_row0_col0(far):
    inv = Transformer.from_crs(far.crs_epsg, 4326, always_xy=True)
    lon, lat = inv.transform(far.origin_x + 1.0, far.origin_y - 1.0)
    assert lonlat_to_rowcol(far, lon, lat) == (0, 0)


@pytest.mark.parametrize("rc", [(0, 0), (10, 20), ("last", "last")])
def test_rowcol_round_trip(far, rc):
    row = far.height - 1 if rc[0] == "last" else rc[0]
    col = far.width - 1 if rc[1] == "last" else rc[1]
    lon, lat = rowcol_to_lonlat(far, row, col)
    assert lonlat_to_rowcol(far, lon, lat) == (row, col)


def test_rowcol_returns_python_ints_for_scalars(far):
    r, c = lonlat_to_rowcol(far, 88.5, 27.5)
    assert isinstance(r, int) and isinstance(c, int)


def test_lonlat_to_rowcol_vectorised(far):
    rows_in = np.array([0, 5, 100])
    cols_in = np.array([0, 7, 200])
    lon, lat = rowcol_to_lonlat(far, rows_in, cols_in)
    rows, cols = lonlat_to_rowcol(far, lon, lat)
    np.testing.assert_array_equal(rows, rows_in)
    np.testing.assert_array_equal(cols, cols_in)


def test_lonlat_outside_raises(far):
    with pytest.raises(ValueError, match="outside"):
        lonlat_to_rowcol(far, 88.0, 27.5)


def test_lonlat_outside_non_strict_returns_minus_one(far):
    rows, cols = lonlat_to_rowcol(far, np.array([88.5, 88.0]), np.array([27.5, 27.5]), strict=False)
    assert rows[0] >= 0 and cols[0] >= 0
    assert rows[1] == -1 and cols[1] == -1


def test_poi_index(synth_config, far):
    lon, lat = synth_config.points_of_interest[0].location.value
    r, c = lonlat_to_rowcol(far, lon, lat)
    assert 0 <= r < far.height and 0 <= c < far.width


# --------------------------------------------------------------------------- resampling

SRC_BOUNDS = (88.44, 27.44, 88.56, 27.56)  # a little larger than the synthetic far-field bbox
SRC_RES = 0.0002  # deg (~20 m)


def write_src(path, data, bounds=SRC_BOUNDS, nodata=None):
    h, w = data.shape
    transform = from_bounds(*bounds, w, h)
    with rasterio.open(
        path, "w", driver="GTiff", width=w, height=h, count=1, dtype=data.dtype,
        crs="EPSG:4326", transform=transform, nodata=nodata,
    ) as dst:
        dst.write(data, 1)
    return path


def lon_ramp(bounds=SRC_BOUNDS):
    w = round((bounds[2] - bounds[0]) / SRC_RES)
    h = round((bounds[3] - bounds[1]) / SRC_RES)
    lon_centres = bounds[0] + (np.arange(w) + 0.5) * SRC_RES
    return np.tile((lon_centres - 88.0) * 1000.0, (h, 1)).astype("float32")


def test_resample_float_bilinear_matches_analytic(far, tmp_path):
    src = write_src(tmp_path / "ramp.tif", lon_ramp(), nodata=-9999.0)
    out = resample_to_grid(src, far)
    assert out.shape == far.shape
    assert out.dtype == np.float32
    assert not np.any(out == far.nodata), "source covers the whole grid"
    rows, cols = np.meshgrid(np.arange(0, far.height, 37), np.arange(0, far.width, 41), indexing="ij")
    lon, _ = rowcol_to_lonlat(far, rows.ravel(), cols.ravel())
    expected = (lon - 88.0) * 1000.0
    np.testing.assert_allclose(out[rows.ravel(), cols.ravel()], expected, atol=0.05)


def test_resample_uint8_uses_nearest(far, tmp_path):
    base = lon_ramp()
    classes = (1 + (np.arange(base.shape[1]) // 50) % 3).astype("uint8")
    data = np.tile(classes, (base.shape[0], 1))
    src = write_src(tmp_path / "classes.tif", data, nodata=255)
    out = resample_to_grid(src, far)
    assert out.dtype == np.uint8
    assert set(np.unique(out)) <= {1, 2, 3}


def test_resample_method_override(far, tmp_path):
    base = lon_ramp()
    classes = (1 + (np.arange(base.shape[1]) // 50) % 3).astype("float32") * 10
    data = np.tile(classes, (base.shape[0], 1))
    src = write_src(tmp_path / "steps.tif", data, nodata=-9999.0)
    nearest = resample_to_grid(src, far, method="nearest")
    assert set(np.unique(nearest)) <= {10.0, 20.0, 30.0}
    bilinear = resample_to_grid(src, far)
    assert len(np.unique(bilinear)) > 3  # bilinear blends across the steps


def test_resample_unknown_method_raises(far, tmp_path):
    src = write_src(tmp_path / "ramp.tif", lon_ramp(), nodata=-9999.0)
    with pytest.raises(ValueError, match="method"):
        resample_to_grid(src, far, method="magic")


def test_resample_uncovered_cells_are_nodata(far, tmp_path):
    west_half = (88.44, 27.44, 88.50, 27.56)
    src = write_src(tmp_path / "west.tif", lon_ramp(west_half), bounds=west_half, nodata=-9999.0)
    out = resample_to_grid(src, far)
    east_col = far.width - 1
    assert np.all(out[:, east_col] == far.nodata)
    assert np.all(out[:, 0] != far.nodata)


def test_resample_accepts_open_dataset(far, tmp_path):
    src = write_src(tmp_path / "ramp.tif", lon_ramp(), nodata=-9999.0)
    with rasterio.open(src) as ds:
        out = resample_to_grid(ds, far)
    assert out.shape == far.shape


def test_write_grid_raster_aligned(far, tmp_path):
    src = write_src(tmp_path / "ramp.tif", lon_ramp(), nodata=-9999.0)
    out = resample_to_grid(src, far)
    path = write_grid_raster(tmp_path / "aligned.tif", out, far)
    with rasterio.open(path) as ds:
        assert ds.crs.to_epsg() == far.crs_epsg
        assert ds.transform == far.transform
        assert (ds.height, ds.width) == far.shape
        assert ds.nodata == far.nodata
        assert ds.dtypes[0] == "float32"
        assert ds.profile["compress"].lower() == "lzw"
        assert ds.profile["tiled"] is True
        np.testing.assert_array_equal(ds.read(1), out)


def test_write_grid_raster_uint8_nodata(far, tmp_path):
    data = np.ones(far.shape, dtype="uint8")
    path = write_grid_raster(tmp_path / "cat.tif", data, far)
    with rasterio.open(path) as ds:
        assert ds.nodata == 255


def test_write_grid_raster_shape_mismatch_raises(far, tmp_path):
    with pytest.raises(ValueError, match="shape"):
        write_grid_raster(tmp_path / "bad.tif", np.zeros((3, 3), dtype="float32"), far)


# --------------------------------------------------------------------------- real config smoke test


def test_teesta_grids_build():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cfg = load_site_config(SITES_DIR / "teesta.yaml")
    grids = build_site_grids(cfg)
    far, near = grids["farfield"], grids["nearfield"]
    assert far.crs_epsg == near.crs_epsg == 32645
    assert (near.origin_x - far.origin_x) % far.cell_size_m == 0
    assert (far.origin_y - near.origin_y) % far.cell_size_m == 0
