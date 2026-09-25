"""Tests for backend.m1_terrain.stl."""

from __future__ import annotations

import struct

import numpy as np
import pytest

from backend.m1_terrain import stl
from backend.shared.grid import CanonicalGrid


def _grid(h=5, w=6, cs=10.0):
    return CanonicalGrid(site_id="test", grid_id="nearfield", crs_epsg=32645, origin_x=1000.0,
                          origin_y=1000.0 + h * cs, cell_size_m=cs, width=w, height=h)


def test_nearfield_frame_is_the_lower_left_corner():
    grid = _grid()
    frame = stl.nearfield_frame(grid)
    left, bottom, _, _ = grid.bounds
    assert frame["origin_x"] == pytest.approx(left)
    assert frame["origin_y"] == pytest.approx(bottom)
    assert frame["crs_epsg"] == grid.crs_epsg


def test_triangle_count_and_local_coords():
    grid = _grid()
    dem = (np.arange(grid.height * grid.width, dtype=np.float32).reshape(grid.shape) + 500.0)
    frame = stl.nearfield_frame(grid)
    triangles = stl.build_triangles(dem, grid, frame)

    assert triangles.shape == (2 * (grid.height - 1) * (grid.width - 1), 3, 3)
    assert triangles[..., 0].min() >= -1e-3  # x >= 0 (local frame origin is the lower-left corner)
    assert triangles[..., 1].min() >= -1e-3  # y >= 0
    assert triangles[..., 2].max() <= dem.max() + 1e-3
    assert triangles[..., 2].min() >= dem.min() - 1e-3


def test_write_stl_binary_format_round_trips(tmp_path):
    grid = _grid()
    dem = np.full(grid.shape, 1234.5, dtype=np.float32)
    frame = stl.nearfield_frame(grid)
    triangles = stl.build_triangles(dem, grid, frame)
    path = stl.write_stl(triangles, tmp_path / "nearfield.stl")

    data = path.read_bytes()
    assert len(data) == 80 + 4 + len(triangles) * 50
    n_triangles = struct.unpack("<I", data[80:84])[0]
    assert n_triangles == len(triangles)
