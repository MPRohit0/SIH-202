"""`gltf_writer.write_glb`: reads its own `.glb` container back apart (glTF 2.0 binary layout --
12-byte header, JSON chunk, BIN chunk) and checks the geometry round-trips, since no glTF
library is in `environment.yml` to validate against."""

from __future__ import annotations

import json
import struct

import numpy as np

from backend.m4_sph.gltf_writer import write_glb


def _read_glb(path):
    data = path.read_bytes()
    magic, version, length = struct.unpack("<III", data[:12])
    assert magic == 0x46546C67
    assert version == 2
    assert length == len(data)
    json_len, json_type = struct.unpack("<II", data[12:20])
    assert json_type == 0x4E4F534A
    gltf = json.loads(data[20:20 + json_len])
    bin_offset = 20 + json_len
    bin_len, bin_type = struct.unpack("<II", data[bin_offset:bin_offset + 8])
    assert bin_type == 0x004E4942
    bin_data = data[bin_offset + 8:bin_offset + 8 + bin_len]
    return gltf, bin_data


def test_round_trips_a_triangle(tmp_path):
    points = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 5]], dtype=np.float32)
    triangles = np.array([[0, 1, 2]], dtype=np.int32)
    path = write_glb(tmp_path / "tri.glb", points, triangles)

    gltf, bin_data = _read_glb(path)
    pos_view = gltf["bufferViews"][gltf["accessors"][0]["bufferView"]]
    idx_view = gltf["bufferViews"][gltf["accessors"][1]["bufferView"]]

    pos_bytes = bin_data[pos_view["byteOffset"]:pos_view["byteOffset"] + pos_view["byteLength"]]
    got_points = np.frombuffer(pos_bytes, dtype="<f4").reshape(-1, 3)
    np.testing.assert_allclose(got_points, points)

    idx_bytes = bin_data[idx_view["byteOffset"]:idx_view["byteOffset"] + idx_view["byteLength"]]
    got_indices = np.frombuffer(idx_bytes, dtype="<u2")  # < 65536 points -> UNSIGNED_SHORT
    np.testing.assert_array_equal(got_indices, [0, 1, 2])

    assert gltf["accessors"][0]["min"] == points.min(axis=0).tolist()
    assert gltf["accessors"][0]["max"] == points.max(axis=0).tolist()
    assert gltf["meshes"][0]["primitives"][0]["mode"] == 4  # TRIANGLES


def test_empty_triangles_writes_points_mode(tmp_path):
    points = np.array([[0, 0, 0], [1, 1, 1]], dtype=np.float32)
    path = write_glb(tmp_path / "pts.glb", points, np.zeros((0, 3), dtype=np.int32))

    gltf, _ = _read_glb(path)
    assert "indices" not in gltf["meshes"][0]["primitives"][0]
    assert gltf["meshes"][0]["primitives"][0]["mode"] == 0  # POINTS
    assert len(gltf["accessors"]) == 1


def test_large_mesh_uses_unsigned_int_indices(tmp_path):
    n = 70_000  # > 65535, forces UNSIGNED_INT indices
    points = np.zeros((n, 3), dtype=np.float32)
    triangles = np.array([[0, 1, 2], [n - 3, n - 2, n - 1]], dtype=np.int64)
    path = write_glb(tmp_path / "big.glb", points, triangles)

    gltf, bin_data = _read_glb(path)
    assert gltf["accessors"][1]["componentType"] == 5125  # UNSIGNED_INT
    idx_view = gltf["bufferViews"][gltf["accessors"][1]["bufferView"]]
    idx_bytes = bin_data[idx_view["byteOffset"]:idx_view["byteOffset"] + idx_view["byteLength"]]
    got_indices = np.frombuffer(idx_bytes, dtype="<u4")
    np.testing.assert_array_equal(got_indices, [0, 1, 2, n - 3, n - 2, n - 1])
