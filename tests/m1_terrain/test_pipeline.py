"""End-to-end test for backend.m1_terrain.pipeline.build_terrain, on the synthetic V-shaped
valley with two dams (a moraine lake + an embankment dam with a reservoir), per CLAUDE.md rule 2
("every module runs end-to-end on synthetic data")."""

from __future__ import annotations

import json

import pandas as pd
import pytest
import rasterio

from backend.m1_terrain.pipeline import build_terrain
from backend.m1_terrain.settings import TerrainSettings

from . import synthetic_valley as sv

EXPECTED_FILES = [
    "grid.json", "grid_nearfield.json", "dem.tif", "dem_nearfield.tif", "landcover.tif",
    "roughness.tif", "hand.tif", "domain_mask.tif", "water_mask.tif", "domain.gpkg",
    "centreline.gpkg", "chainage_samples.csv", "pois.gpkg", "nearfield.stl",
    "nearfield_frame.json", "provenance.json",
]


def _write_raw(raw_dir, cfg):
    bbox = cfg.domains.far_field.bbox.value
    breach = tuple(cfg.dams[0].breach_location.value)
    downstream = tuple(cfg.points_of_interest[0].location.value)
    lake = tuple(cfg.dams[0].location.value)
    reservoir = tuple(cfg.dams[1].location.value)
    sv.write_raw_rasters(raw_dir, bbox, breach, downstream, lake, reservoir)
    sv.write_raw_provenance(raw_dir, "srtm_gl1")


def test_build_terrain_end_to_end(tmp_path, synth_config_two_dams):
    cfg = synth_config_two_dams
    raw_dir, out_dir = tmp_path / "raw", tmp_path / "terrain"
    _write_raw(raw_dir, cfg)

    provenance = build_terrain(cfg, "srtm_gl1", raw_dir, out_dir, TerrainSettings())

    for name in EXPECTED_FILES:
        assert (out_dir / name).is_file(), f"missing {name}"

    assert provenance["has_placeholders"] is True  # site config + manning table both have placeholders
    assert provenance["vertical_datum"] == "EGM96"
    assert provenance["dem"]["product"] == "srtm_gl1"

    with rasterio.open(out_dir / "dem.tif") as ds:
        assert ds.crs.to_epsg() == 32645
        dem = ds.read(1)
    with rasterio.open(out_dir / "hand.tif") as ds:
        hand = ds.read(1)
    assert hand.shape == dem.shape

    chainage = pd.read_csv(out_dir / "chainage_samples.csv")
    assert chainage["chainage_m"].iloc[0] == 0.0
    assert chainage["chainage_m"].is_monotonic_increasing

    frame = json.loads((out_dir / "nearfield_frame.json").read_text())
    assert frame["units"] == "m"
    assert frame["crs_epsg"] == 32645


def test_build_terrain_requires_downloaded_dem(tmp_path, synth_config):
    with pytest.raises(FileNotFoundError):
        build_terrain(synth_config, "srtm_gl1", tmp_path / "raw", tmp_path / "terrain", TerrainSettings())
