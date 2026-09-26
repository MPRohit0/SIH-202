"""Minimal glTF 2.0 binary (`.glb`) writer for one geometry-only triangle mesh (contract §1.6
"3D meshes|glTF binary `.glb`"). No materials, no per-vertex data -- the SPH water surfaces this
project writes (`surfaces/t<seconds>.glb`, §4.4) are geometry the frontend shades itself.

No `pygltflib`/`trimesh` dependency (not in `environment.yml`, CLAUDE.md stack): the `.glb`
container (glTF 2.0 spec §Binary glTF: a 12-byte header, a JSON chunk, a BIN chunk) is simple
enough to write by hand and easy to keep dependency-free for a single mesh-out use.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np

_GLB_MAGIC = 0x46546C67  # "glTF"
_GLB_VERSION = 2
_CHUNK_JSON = 0x4E4F534A  # "JSON"
_CHUNK_BIN = 0x004E4942  # "BIN\0"

_COMPONENT_FLOAT = 5126
_COMPONENT_UNSIGNED_SHORT = 5123
_COMPONENT_UNSIGNED_INT = 5125
_TARGET_ARRAY_BUFFER = 34962
_TARGET_ELEMENT_ARRAY_BUFFER = 34963
_MODE_TRIANGLES = 4


def _pad(data: bytes, boundary: int, fill: bytes) -> bytes:
    remainder = len(data) % boundary
    return data if remainder == 0 else data + fill * (boundary - remainder)


def write_glb(path: str | Path, points: np.ndarray, triangles: np.ndarray) -> Path:
    """Write `points` `(N, 3)` float and `triangles` `(M, 3)` int as a one-mesh `.glb`.

    Index componentType is `UNSIGNED_SHORT` (fits glTF's stricter WebGL-era readers) when
    `N < 65536`, else `UNSIGNED_INT`; empty `triangles` writes a mesh with no `indices`
    (POINTS mode) since some near-empty isosurfaces have no faces (`vtk_polydata.read_polydata`).
    """
    points = np.asarray(points, dtype="<f4")
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError(f"points must be (N, 3), got shape {points.shape}")
    n_points = points.shape[0]

    # Position bytes are always a multiple of 4 (3 floats/point) -- no per-view padding needed.
    # Only the very end of the BIN chunk needs padding (glTF spec: chunk length % 4 == 0);
    # bufferView.byteLength must stay the *unpadded* data size, or a reader treats the padding
    # itself as extra index/vertex data.
    pos_bytes = points.tobytes()
    buffer_views = [{
        "buffer": 0, "byteOffset": 0, "byteLength": len(pos_bytes), "target": _TARGET_ARRAY_BUFFER,
    }]
    accessors = [{
        "bufferView": 0, "byteOffset": 0, "componentType": _COMPONENT_FLOAT, "count": n_points,
        "type": "VEC3",
        "min": points.min(axis=0).tolist() if n_points else [0.0, 0.0, 0.0],
        "max": points.max(axis=0).tolist() if n_points else [0.0, 0.0, 0.0],
    }]

    primitive = {"attributes": {"POSITION": 0}, "mode": _MODE_TRIANGLES}
    bin_chunks = [pos_bytes]

    triangles = np.asarray(triangles, dtype=np.int64).reshape(-1, 3) if len(triangles) else np.zeros((0, 3), dtype=np.int64)
    if triangles.size:
        index_dtype, component_type = ("<u2", _COMPONENT_UNSIGNED_SHORT) if n_points < 65536 else ("<u4", _COMPONENT_UNSIGNED_INT)
        idx = triangles.astype(index_dtype).reshape(-1)
        idx_bytes = idx.tobytes()
        idx_offset = sum(len(c) for c in bin_chunks)
        buffer_views.append({
            "buffer": 0, "byteOffset": idx_offset, "byteLength": len(idx_bytes), "target": _TARGET_ELEMENT_ARRAY_BUFFER,
        })
        accessors.append({
            "bufferView": 1, "byteOffset": 0, "componentType": component_type, "count": int(idx.size), "type": "SCALAR",
        })
        primitive["indices"] = 1
        bin_chunks.append(idx_bytes)
    else:
        primitive["mode"] = 0  # POINTS -- no faces to draw

    bin_data = _pad(b"".join(bin_chunks), 4, b"\x00")
    gltf = {
        "asset": {"version": "2.0", "generator": "backend.m4_sph.gltf_writer"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [primitive]}],
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{"byteLength": len(bin_data)}],
    }

    json_bytes = _pad(json.dumps(gltf).encode("utf-8"), 4, b" ")
    header = struct.pack("<III", _GLB_MAGIC, _GLB_VERSION, 12 + 8 + len(json_bytes) + 8 + len(bin_data))
    json_chunk = struct.pack("<II", len(json_bytes), _CHUNK_JSON) + json_bytes
    bin_chunk = struct.pack("<II", len(bin_data), _CHUNK_BIN) + bin_data

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + json_chunk + bin_chunk)
    return path
