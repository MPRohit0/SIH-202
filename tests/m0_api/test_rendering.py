"""Tests for backend/m0_api/rendering.py (contract §4.6, §5 #11, §6).

Synthetic-data-only (CLAUDE.md rule 2): a small hand-built CanonicalGrid and
arrays, no real M1-M5 output.
"""

from __future__ import annotations

import numpy as np
import rasterio
import pytest
from rasterio.io import MemoryFile

from backend.m0_api import rendering
from backend.shared.grid import CanonicalGrid

GRID = CanonicalGrid(
    site_id="teesta", grid_id="farfield", crs_epsg=32645,
    origin_x=500_000.0, origin_y=3_100_000.0, cell_size_m=30.0, width=10, height=8,
)
NODATA = -9999.0


def _decode_png(png_bytes: bytes) -> np.ndarray:
    """RGBA (4, H, W) uint8 array."""
    with MemoryFile(png_bytes) as mem, mem.open() as ds:
        return ds.read()


def test_bounds_come_from_the_grid():
    south, west = GRID.bounds_latlng[0]
    north, east = GRID.bounds_latlng[1]
    assert south < north
    assert west < east
    # sanity: Teesta UTM 45N zone -> roughly 88 E, 27-28 N
    assert 80 < west < 95
    assert 20 < south < 35


def test_dry_cells_are_transparent():
    array = np.zeros(GRID.shape, dtype=np.float32)  # all dry
    png = rendering.render_layer_png(array, NODATA, "depth_p50")
    rgba = _decode_png(png)
    assert (rgba[3] == 0).all()


def test_nodata_cells_are_transparent():
    array = np.full(GRID.shape, NODATA, dtype=np.float32)
    png = rendering.render_layer_png(array, NODATA, "p_inundation")
    rgba = _decode_png(png)
    assert (rgba[3] == 0).all()


def test_classes_colours_match_styles_json():
    styles = rendering.load_styles()
    style = styles["depth_p50"]
    breaks, colors = style["breaks_m"], style["colors"]

    array = np.zeros(GRID.shape, dtype=np.float32)
    # one probe cell per bucket: just below each break, and above the last one.
    probes = [breaks[0] - 0.1] + [(breaks[i] + breaks[i + 1]) / 2 for i in range(len(breaks) - 1)] + [breaks[-1] + 1.0]
    for i, v in enumerate(probes):
        array[0, i] = v

    png = rendering.render_layer_png(array, NODATA, "depth_p50")
    rgba = _decode_png(png)
    for i, expected_hex in enumerate(colors):
        r, g, b = rendering._hex_to_rgb(expected_hex)
        assert tuple(rgba[0:3, 0, i]) == (r, g, b), f"bucket {i} colour mismatch"
        assert rgba[3, 0, i] == 255


def test_continuous_colours_match_styles_json_stops():
    styles = rendering.load_styles()
    stops = styles["p_inundation"]["stops"]

    array = np.zeros(GRID.shape, dtype=np.float32)
    for i, (value, _hex) in enumerate(stops):
        array[0, i] = value

    png = rendering.render_layer_png(array, NODATA, "p_inundation")
    rgba = _decode_png(png)
    for i, (_value, expected_hex) in enumerate(stops):
        r, g, b = rendering._hex_to_rgb(expected_hex)
        assert tuple(rgba[0:3, 0, i]) == (r, g, b), f"stop {i} colour mismatch"


def test_extent_class_uses_zone_fill_and_opacity():
    styles = rendering.load_styles()
    high, possible = styles["extent_class"]["high"], styles["extent_class"]["possible"]

    array = np.zeros(GRID.shape, dtype=np.uint8)
    array[0, 0] = 2  # HIGH
    array[0, 1] = 1  # POSSIBLE

    png = rendering.render_layer_png(array, 255, "extent_class")
    rgba = _decode_png(png)

    r, g, b = rendering._hex_to_rgb(high["fill"])
    assert tuple(rgba[0:3, 0, 0]) == (r, g, b)
    assert rgba[3, 0, 0] == round(high["opacity"] * 255)

    r, g, b = rendering._hex_to_rgb(possible["fill"])
    assert tuple(rgba[0:3, 0, 1]) == (r, g, b)
    assert rgba[3, 0, 1] == round(possible["opacity"] * 255)

    assert rgba[3, 1, 0] == 0  # dry cell stays transparent


def test_unknown_layer_id_raises():
    array = np.zeros(GRID.shape, dtype=np.float32)
    with pytest.raises(ValueError):
        rendering.render_layer_png(array, NODATA, "not_a_real_layer")


def test_render_and_cache_writes_once_and_reuses(tmp_path):
    tif_path = tmp_path / "depth_p50.tif"
    array = np.full(GRID.shape, 1.0, dtype=np.float32)
    from backend.shared.grid import write_grid_raster

    write_grid_raster(tif_path, array, GRID)

    calls = []
    real_colorize = rendering.colorize

    def spy(*args, **kwargs):
        calls.append(1)
        return real_colorize(*args, **kwargs)

    rendering.colorize = spy
    try:
        png_path = tmp_path / "depth_p50.png"
        first = rendering.render_and_cache(tif_path, "depth_p50", png_path)
        assert png_path.is_file()
        assert len(calls) == 1

        second = rendering.render_and_cache(tif_path, "depth_p50", png_path)
        assert second == first
        assert len(calls) == 1  # cache hit: colorize not called again
    finally:
        rendering.colorize = real_colorize


def test_render_and_cache_default_png_path(tmp_path):
    from backend.shared.grid import write_grid_raster

    tif_path = tmp_path / "arrival_p50.tif"
    write_grid_raster(tif_path, np.full(GRID.shape, 600.0, dtype=np.float32), GRID)

    rendering.render_and_cache(tif_path, "arrival_p50")
    assert (tmp_path / "arrival_p50.png").is_file()
