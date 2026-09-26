"""Minimal reader for the legacy VTK (`# vtk DataFile Version 3.0`) BINARY POLYDATA files that
DualSPHysics's `IsoSurface_linux64 -saveiso` writes for the free-surface mesh (contract §4.4
`surfaces/t<seconds>.glb` -- this module reads the solver's `.vtk`, `surfaces.py` converts to glTF).

Only the two sections this project's isosurfaces actually use are read: `POINTS` (big-endian
float32 triples, per the legacy VTK spec -- binary data in legacy VTK is always big-endian
regardless of host byte order) and `POLYGONS` (big-endian int32: `count, i0, i1, ..., count, ...`).
Verified against a real `IsoSurface_linux64 -saveiso` file (`docs/decisions.md`, today's session):
header is exactly 5 ASCII lines (version, title, `BINARY`, `DATASET POLYDATA`, `POINTS n float`),
polygons are all triangles (`count == 3`); n-gons (`count > 3`) are fan-triangulated defensively.
Any other section (`POINT_DATA`, normals, ...) is ignored -- this project's glTF surfaces are
geometry-only (§1.6 "3D meshes|glTF binary `.glb`"; no per-vertex data in the contract's Scene3D).
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

_EXPECTED_HEADER = ("BINARY", "DATASET POLYDATA")


def _read_ascii_line(f) -> str:
    chunk = bytearray()
    while True:
        b = f.read(1)
        if b in (b"", b"\n"):
            break
        chunk += b
    return chunk.decode("ascii", errors="replace")


def read_polydata(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """`(points, triangles)`: `points` is `(N, 3)` float32 in the file's own frame (SPH local
    frame, §1.3 -- no transform needed), `triangles` is `(M, 3)` int32 vertex indices.

    Raises `ValueError` if the file isn't `BINARY DATASET POLYDATA` with a `POINTS ... float`
    line, or if a `POLYGONS` section it does have contains a non-polygon record (a `POINTS`
    section alone, with no `POLYGONS`, is valid and returns an empty triangle array -- some
    IsoSurface configurations can produce point clouds).
    """
    path = Path(path)
    with open(path, "rb") as f:
        header = [_read_ascii_line(f) for _ in range(2)]  # version line, title line
        keyword_lines = [_read_ascii_line(f), _read_ascii_line(f)]
        if tuple(keyword_lines) != _EXPECTED_HEADER:
            raise ValueError(f"{path}: expected 'BINARY'/'DATASET POLYDATA', got {keyword_lines!r}")

        points_line = _read_ascii_line(f)
        parts = points_line.split()
        if len(parts) != 3 or parts[0] != "POINTS" or parts[2] != "float":
            raise ValueError(f"{path}: expected 'POINTS <n> float', got {points_line!r}")
        n_points = int(parts[1])

        raw = f.read(n_points * 3 * 4)
        points = np.frombuffer(raw, dtype=">f4").astype(np.float32).reshape(n_points, 3)

        triangles: list[tuple[int, int, int]] = []
        while True:
            sep = f.read(1)
            if sep == b"":
                break
            if sep != b"\n":
                raise ValueError(f"{path}: expected a newline after the POINTS block, got {sep!r}")
            line = _read_ascii_line(f)
            if not line:
                continue  # blank separator line between sections
            fields = line.split()
            if fields[0] != "POLYGONS":
                break  # a section this project doesn't need (POINT_DATA, ...); stop here
            n_polys, total_ints = int(fields[1]), int(fields[2])
            raw_polys = f.read(total_ints * 4)
            ints = struct.unpack(f">{total_ints}i", raw_polys)
            i = 0
            for _ in range(n_polys):
                count = ints[i]
                verts = ints[i + 1:i + 1 + count]
                i += count + 1
                for k in range(1, count - 1):  # fan triangulation; a no-op when count == 3
                    triangles.append((verts[0], verts[k], verts[k + 1]))
            break  # only one POLYGONS section is expected

    tri_arr = np.asarray(triangles, dtype=np.int32) if triangles else np.zeros((0, 3), dtype=np.int32)
    return points, tri_arr
