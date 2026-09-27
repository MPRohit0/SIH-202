"""M1: near-field terrain mesh for DualSPHysics (`docs/handoff_contract.md` §4.1 `nearfield.stl`,
`nearfield_frame.json`; §1.3 "SPH geometry: local metric frame, x = UTM x − frame origin x,
y = UTM y − frame origin y, z = elevation"). Hand-written binary STL — no `numpy-stl` dependency.
The frame origin is the near-field grid's lower-left corner, so every mesh vertex has x, y >= 0."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np

from backend.shared.grid import FLOAT_NODATA, CanonicalGrid

CONTRACT_VERSION = "0.3.0"


def nearfield_frame(grid: CanonicalGrid) -> dict:
    left, bottom, _, _ = grid.bounds
    return {
        "contract_version": CONTRACT_VERSION, "crs_epsg": grid.crs_epsg,
        "origin_x": left, "origin_y": bottom, "units": "m",
    }


def write_nearfield_frame(grid: CanonicalGrid, path: str | Path) -> Path:
    path = Path(path)
    path.write_text(json.dumps(nearfield_frame(grid), indent=2) + "\n", encoding="utf-8")
    return path


def build_triangles(dem: np.ndarray, grid: CanonicalGrid, frame: dict, fill_value: float = 0.0) -> np.ndarray:
    """`(n_triangles, 3, 3)` float32 vertex array: two triangles per cell-centre quad. Nodata
    cells are filled with `fill_value` (documented in `provenance.json`, not hidden) rather than
    left as holes, since SPH particle generation from the mesh needs a watertight surface."""
    dem = np.where(dem == FLOAT_NODATA, fill_value, dem)
    rows, cols = np.indices(dem.shape)
    x = grid.origin_x + (cols + 0.5) * grid.cell_size_m - frame["origin_x"]
    y = grid.origin_y - (rows + 0.5) * grid.cell_size_m - frame["origin_y"]
    z = dem.astype(np.float64)

    def quad_corner(rs: slice, cs: slice) -> np.ndarray:
        return np.stack([x[rs, cs], y[rs, cs], z[rs, cs]], axis=-1)

    v00 = quad_corner(slice(None, -1), slice(None, -1))
    v01 = quad_corner(slice(None, -1), slice(1, None))
    v10 = quad_corner(slice(1, None), slice(None, -1))
    v11 = quad_corner(slice(1, None), slice(1, None))

    tri_a = np.stack([v00, v10, v01], axis=-2)  # (h-1, w-1, 3, 3)
    tri_b = np.stack([v10, v11, v01], axis=-2)
    triangles = np.concatenate([tri_a.reshape(-1, 3, 3), tri_b.reshape(-1, 3, 3)], axis=0)
    return triangles.astype(np.float32)


def _face_normals(triangles: np.ndarray) -> np.ndarray:
    u = triangles[:, 1] - triangles[:, 0]
    v = triangles[:, 2] - triangles[:, 0]
    n = np.cross(u, v)
    norm = np.linalg.norm(n, axis=1, keepdims=True)
    norm[norm == 0] = 1.0
    return (n / norm).astype(np.float32)


def write_stl(triangles: np.ndarray, path: str | Path, *, header: bytes = b"SIH26 M1 near-field terrain") -> Path:
    """Write `triangles` (`(n, 3, 3)` float32, one triangle per row) as binary STL."""
    normals = _face_normals(triangles)
    path = Path(path)
    with open(path, "wb") as f:
        f.write(header[:80].ljust(80, b"\0"))
        f.write(struct.pack("<I", len(triangles)))
        for tri, n in zip(triangles, normals):
            f.write(struct.pack("<3f", *n))
            f.write(struct.pack("<9f", *tri.reshape(-1)))
            f.write(struct.pack("<H", 0))
    return path
