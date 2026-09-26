"""`vtk_polydata.read_polydata` against hand-built legacy VTK BINARY POLYDATA files (the exact
byte layout was checked against a real `IsoSurface_linux64 -saveiso` file before being hard-coded
here -- `docs/decisions.md`, today's session). `test_surfaces.py`'s real-binary smoke test
exercises the reader against an actual IsoSurface output; this file exercises the format edges
(n-gon fan triangulation, no-POLYGONS point clouds) a real run may not happen to produce."""

from __future__ import annotations

import struct

import numpy as np

from backend.m4_sph.vtk_polydata import read_polydata


def _write_legacy_vtk(path, points: np.ndarray, polygons: list[list[int]]):
    header = "# vtk DataFile Version 3.0\nvtk output\nBINARY\nDATASET POLYDATA\n"
    header += f"POINTS {len(points)} float\n"
    body = struct.pack(f">{points.size}f", *points.astype(">f4").flatten())
    poly_header = f"\nPOLYGONS {len(polygons)} {sum(len(p) + 1 for p in polygons)}\n"
    poly_body = b"".join(struct.pack(f">{len(p) + 1}i", len(p), *p) for p in polygons)
    with open(path, "wb") as f:
        f.write(header.encode("ascii"))
        f.write(body)
        f.write(poly_header.encode("ascii"))
        f.write(poly_body)


def test_reads_a_single_triangle(tmp_path):
    points = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float)
    path = tmp_path / "tri.vtk"
    _write_legacy_vtk(path, points, [[0, 1, 2]])

    read_points, triangles = read_polydata(path)
    np.testing.assert_allclose(read_points, points, atol=1e-6)
    np.testing.assert_array_equal(triangles, [[0, 1, 2]])


def test_fan_triangulates_a_quad(tmp_path):
    points = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=float)
    path = tmp_path / "quad.vtk"
    _write_legacy_vtk(path, points, [[0, 1, 2, 3]])

    _, triangles = read_polydata(path)
    assert triangles.shape == (2, 3)
    np.testing.assert_array_equal(triangles, [[0, 1, 2], [0, 2, 3]])


def test_points_only_file_has_no_triangles(tmp_path):
    points = np.array([[0, 0, 0], [1, 1, 1]], dtype=float)
    path = tmp_path / "pts.vtk"
    _write_legacy_vtk(path, points, [])

    read_points, triangles = read_polydata(path)
    assert read_points.shape == (2, 3)
    assert triangles.shape == (0, 3)


def test_no_polygons_section_at_all_has_no_triangles(tmp_path):
    """A file that ends right after POINTS, with no POLYGONS header at all."""
    points = np.array([[0, 0, 0], [1, 1, 1]], dtype=float)
    path = tmp_path / "pts_bare.vtk"
    header = "# vtk DataFile Version 3.0\nvtk output\nBINARY\nDATASET POLYDATA\nPOINTS 2 float\n"
    body = struct.pack(f">{points.size}f", *points.astype(">f4").flatten())
    path.write_bytes(header.encode("ascii") + body)

    read_points, triangles = read_polydata(path)
    assert read_points.shape == (2, 3)
    assert triangles.shape == (0, 3)
