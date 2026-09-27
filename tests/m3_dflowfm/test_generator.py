from __future__ import annotations

import json

import pytest

from backend.m3_dflowfm.generator import _densified_ring, build_case, check_run_success


def test_densified_ring_obeys_mesh_spacing_and_closes():
    ring = _densified_ring([(0, 0), (1000, 0), (1000, 1000), (0, 1000), (0, 0)], 90)
    lengths = [((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
               for (x0, y0), (x1, y1) in zip(ring, ring[1:])]
    assert max(lengths) <= 90
    assert ring[0] == ring[-1] == (0.0, 0.0)


def test_builds_placeholder_synthetic_case(synth_terrain_dir, synth_m3_sites_dir, synth_hydrograph_params, tmp_path):
    case, meta = build_case(
        "synth", "s001", synth_hydrograph_params,
        data_dir=synth_terrain_dir.parent.parent,
        sites_dir=synth_m3_sites_dir,
        case_dir=tmp_path / "case",
        stop_s=7200,
    )
    assert meta["has_placeholders"] is True
    assert meta["base_flow_m3s"] == 12.0
    assert meta["mesh"]["face_count"] > 0
    assert (case / "model.mdu").is_file()
    assert (case / "inputs" / "domain_net.nc").is_file()
    assert "fileVersion = 2.01" in (case / "inputs" / "forcing.ext").read_text()
    assert "inputs/initial_fields.ini" in (case / "model.mdu").read_text()
    assert "mapInterval                       = 60.0" in (case / "model.mdu").read_text()
    assert str(case.resolve()) not in (case / "model.mdu").read_text()
    assert meta["mesh"]["roundtrip"]["node_coordinates_max_abs_error_m"] <= 1e-6
    assert json.loads((case / "case_meta.json").read_text())["has_placeholders"] is True
    assert meta["map_interval_s"] == 60.0


def test_requires_explicit_base_flow(synth_terrain_dir, synth_sites_dir, synth_hydrograph_params, tmp_path):
    with pytest.raises(ValueError, match="base_flow is missing or null"):
        build_case(
            "synth", "s001", synth_hydrograph_params,
            data_dir=synth_terrain_dir.parent.parent,
            sites_dir=synth_sites_dir,
            case_dir=tmp_path / "case",
        )


def test_run_success_uses_dia_and_both_netcdf_files(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    (output / "model.dia").write_text("** INFO   : done\n")
    (output / "model_map.nc").touch()
    (output / "model_his.nc").touch()
    assert check_run_success(tmp_path)["success"] is True

    (output / "model.dia").write_text("** ERROR  : failed\n")
    assert check_run_success(tmp_path)["success"] is False
    (output / "model.dia").write_text("** INFO   : done\n")
    (output / "model_his.nc").unlink()
    assert check_run_success(tmp_path)["success"] is False
