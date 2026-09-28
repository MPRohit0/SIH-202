"""Tests for backend.m6_impact.loss: damage_fraction, building/road loss pricing,
and the top-level estimate_loss Estimate (docs/handoff_contract.md §4.7 loss_inr)."""

from __future__ import annotations

import csv
import warnings
from pathlib import Path

import numpy as np
import pytest

from backend.m6_impact.loss import (
    LossConfig,
    building_losses,
    damage_fraction,
    estimate_loss,
    load_asset_values,
    load_damage_curves,
    load_loss_config,
    road_losses,
    sample_depth,
)
from backend.shared.grid import CanonicalGrid

CRS_EPSG = 32645  # Teesta UTM zone


def _grid() -> CanonicalGrid:
    """10x10 cells, 10 m, origin (0, 100) -> a 100 m x 100 m UTM square,
    x in [0, 100], y in [0, 100] (top-left origin)."""
    return CanonicalGrid(site_id="loss_test", grid_id="farfield", crs_epsg=CRS_EPSG,
                          origin_x=0.0, origin_y=100.0, cell_size_m=10.0, width=10, height=10)


def _write_damage_curves(path: Path) -> None:
    rows = [
        ("residential", 0.0, 0.0), ("residential", 1.0, 0.49405032354045164), ("residential", 6.0, 1.0),
        ("commercial", 0.0, 0.0), ("commercial", 1.0, 0.5), ("commercial", 6.0, 1.0),
        ("industrial", 0.0, 0.0), ("industrial", 1.0, 0.48), ("industrial", 6.0, 1.0),
        ("infrastructure_roads", 0.0, 0.0), ("infrastructure_roads", 1.0, 0.37), ("infrastructure_roads", 6.0, 1.0),
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["asset_class", "depth_m", "damage_fraction", "source"])
        for cls, d, frac in rows:
            w.writerow([cls, d, frac, "src_031"])


def _write_asset_values(path: Path, *, sourced: bool, fx: float = 2.0, idx: float = 3.0) -> None:
    eur = {"residential": 212.78, "commercial": 323.98, "industrial": 293.10, "infrastructure_roads": 2.963}
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["asset_class", "value_inr_per_unit", "unit", "source", "status", "value_eur2010", "jrc_cell"])
        for cls, e in eur.items():
            inr = e * fx * idx if sourced else ""
            status = "sourced" if sourced else "placeholder"
            w.writerow([cls, inr, "INR/m2", "src_032", status, e, f"'MaxDamage-X'!Z{1}"])


def _config(*, sourced: bool, fx: float = 2.0, idx: float = 3.0, road_width_sourced: bool = False) -> LossConfig:
    cfg = load_loss_config().model_copy(deep=True)
    status = "sourced" if sourced else "placeholder"
    cfg.eur_to_inr_2010 = cfg.eur_to_inr_2010.model_copy(update={"value": fx, "status": status})
    cfg.price_index_2010_to_current = cfg.price_index_2010_to_current.model_copy(update={"value": idx, "status": status})
    # config/impact.yaml ships default_road_width_m as `sourced` (docs/data_sources.md src_051);
    # most tests here are about the FX/price-index placeholder behaviour, not roads, so default
    # to forcing it back to `placeholder` unless a test opts in.
    cfg.default_road_width_m = cfg.default_road_width_m.model_copy(
        update={"value": 5.0 if road_width_sourced else None, "status": "sourced" if road_width_sourced else "placeholder"})
    return cfg


@pytest.fixture
def exposure_dir(tmp_path) -> Path:
    d = tmp_path / "exposure"
    d.mkdir()
    _write_damage_curves(d / "damage_curves.csv")
    return d


# =============================================================================
# damage_fraction
# =============================================================================


def test_damage_fraction_exact_at_tabulated_points():
    curves = {"residential": (np.array([0.0, 1.0, 6.0]), np.array([0.0, 0.49405032354045164, 1.0]))}
    assert damage_fraction(curves, "residential", np.array([1.0]), 6.0)[0] == pytest.approx(0.49405032354045164)


def test_damage_fraction_linear_at_midpoint():
    curves = {"residential": (np.array([0.0, 2.0]), np.array([0.0, 1.0]))}
    assert damage_fraction(curves, "residential", np.array([1.0]), 6.0)[0] == pytest.approx(0.5)


def test_damage_fraction_zero_at_or_below_zero_depth():
    curves = {"residential": (np.array([0.0, 1.0]), np.array([0.0, 0.5]))}
    assert damage_fraction(curves, "residential", np.array([0.0, -1.0]), 6.0) == pytest.approx([0.0, 0.0])


def test_damage_fraction_capped_above_depth_cap_with_warning():
    curves = {"residential": (np.array([0.0, 6.0]), np.array([0.0, 1.0]))}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = damage_fraction(curves, "residential", np.array([10.0]), 6.0)
    assert result[0] == pytest.approx(1.0)
    assert any("exceeds the JRC tabulated range" in str(w.message) for w in caught)


# =============================================================================
# sample_depth
# =============================================================================


def test_sample_depth_inside_and_outside_grid():
    grid = _grid()
    depth = np.zeros((10, 10), dtype=np.float32)
    depth[0, 0] = 1.5  # top-left cell: x in [0,10], y in [90,100]
    result = sample_depth(grid, depth, xs=np.array([5.0, -50.0]), ys=np.array([95.0, 95.0]))
    assert result[0] == pytest.approx(1.5)
    assert np.isnan(result[1])


def test_sample_depth_nodata_becomes_nan():
    grid = _grid()
    depth = np.full((10, 10), -9999.0, dtype=np.float32)
    result = sample_depth(grid, depth, xs=np.array([5.0]), ys=np.array([95.0]))
    assert np.isnan(result[0])


# =============================================================================
# building_losses (via a tiny synthetic GeoDataFrame — no exposure_osm dependency)
# =============================================================================


def _building_gdf(rows: list[dict]):
    import geopandas as gpd
    from shapely.geometry import Polygon

    return gpd.GeoDataFrame(rows, geometry="geometry", crs=f"EPSG:{CRS_EPSG}")


def test_building_losses_single_building_matches_hand_computed_value(exposure_dir):
    from shapely.geometry import Polygon

    # 10x10 m square footprint (100 m2), centred in a wet cell with depth 1.0 m.
    poly = Polygon([(20, 70), (30, 70), (30, 80), (20, 80)])  # centroid (25, 75) -> row2,col2
    gdf = _building_gdf([{"osm_id": "way/1", "kind": "house", "name": None, "geometry": poly}])

    grid = _grid()
    depth = np.zeros((10, 10), dtype=np.float32)
    row, col = 2, 2
    depth[row, col] = 1.0

    curves = load_damage_curves(exposure_dir / "damage_curves.csv")
    _write_asset_values(exposure_dir / "asset_values.csv", sourced=True, fx=2.0, idx=3.0)
    config = _config(sourced=True, fx=2.0, idx=3.0)
    values = load_asset_values(exposure_dir / "asset_values.csv", config)

    result = building_losses(gdf, grid, depth, curves, values, config)
    expected = 0.49405032354045164 * 100.0 * (212.78 * 2.0 * 3.0)
    assert result["residential"]["loss_inr"] == pytest.approx(expected, rel=1e-6)
    assert result["residential"]["n_excluded"] == 0


def test_building_losses_dry_building_excluded_and_counted(exposure_dir):
    from shapely.geometry import Polygon

    poly = Polygon([(20, 70), (30, 70), (30, 80), (20, 80)])
    gdf = _building_gdf([{"osm_id": "way/1", "kind": "house", "name": None, "geometry": poly}])
    grid = _grid()
    depth = np.zeros((10, 10), dtype=np.float32)  # everywhere dry

    curves = load_damage_curves(exposure_dir / "damage_curves.csv")
    _write_asset_values(exposure_dir / "asset_values.csv", sourced=True)
    config = _config(sourced=True)
    values = load_asset_values(exposure_dir / "asset_values.csv", config)

    result = building_losses(gdf, grid, depth, curves, values, config)
    assert result["residential"]["loss_inr"] == pytest.approx(0.0)
    assert result["residential"]["n_excluded"] == 1


def test_building_losses_unmapped_kind_falls_back_to_default_class(exposure_dir):
    from shapely.geometry import Polygon

    poly = Polygon([(20, 70), (30, 70), (30, 80), (20, 80)])
    gdf = _building_gdf([{"osm_id": "way/1", "kind": "shed", "name": None, "geometry": poly}])  # not in config map
    grid = _grid()
    depth = np.zeros((10, 10), dtype=np.float32)
    depth[2, 2] = 1.0

    curves = load_damage_curves(exposure_dir / "damage_curves.csv")
    _write_asset_values(exposure_dir / "asset_values.csv", sourced=True)
    config = _config(sourced=True)
    values = load_asset_values(exposure_dir / "asset_values.csv", config)

    result = building_losses(gdf, grid, depth, curves, values, config)
    assert config.default_building_class == "residential"
    assert "residential" in result
    assert result["residential"]["loss_inr"] > 0


def _roads_gdf(rows: list[dict]):
    import geopandas as gpd

    return gpd.GeoDataFrame(rows, geometry="geometry", crs=f"EPSG:{CRS_EPSG}")


def test_road_losses_priced_with_sourced_width(exposure_dir):
    from shapely.geometry import LineString

    # A 40 m road straight through the grid at y=95 (row 0), crossing 4 cells at x=0..40.
    line = LineString([(0, 95), (40, 95)])
    gdf = _roads_gdf([{"osm_id": "way/1", "kind": "residential", "name": None, "geometry": line}])
    grid = _grid()
    depth = np.zeros((10, 10), dtype=np.float32)
    depth[0, :] = 1.0  # the whole row the road runs through is wet at 1.0 m

    curves = load_damage_curves(exposure_dir / "damage_curves.csv")
    _write_asset_values(exposure_dir / "asset_values.csv", sourced=True, fx=2.0, idx=3.0)
    config = _config(sourced=True, fx=2.0, idx=3.0)
    config.default_road_width_m = config.default_road_width_m.model_copy(update={"value": 5.0, "status": "sourced"})
    values = load_asset_values(exposure_dir / "asset_values.csv", config)

    result = road_losses(gdf, grid, depth, curves, values, config)
    expected = 0.37 * line.length * 5.0 * (2.963 * 2.0 * 3.0)
    assert result["loss_inr"] == pytest.approx(expected, rel=1e-2)
    assert result["flooded_length_m"] == pytest.approx(line.length, rel=1e-6)


def test_road_losses_placeholder_width_gives_none(exposure_dir):
    from shapely.geometry import LineString

    line = LineString([(0, 95), (40, 95)])
    gdf = _roads_gdf([{"osm_id": "way/1", "kind": "residential", "name": None, "geometry": line}])
    grid = _grid()
    depth = np.zeros((10, 10), dtype=np.float32)
    depth[0, :] = 1.0

    curves = load_damage_curves(exposure_dir / "damage_curves.csv")
    _write_asset_values(exposure_dir / "asset_values.csv", sourced=True, fx=2.0, idx=3.0)
    config = _config(sourced=True, fx=2.0, idx=3.0)  # default_road_width_m stays placeholder
    values = load_asset_values(exposure_dir / "asset_values.csv", config)

    result = road_losses(gdf, grid, depth, curves, values, config)
    assert result["loss_inr"] is None
    assert result["flooded_length_m"] == pytest.approx(line.length, rel=1e-6)  # still tracked, just not priced


def test_building_losses_placeholder_fx_gives_none(exposure_dir):
    from shapely.geometry import Polygon

    poly = Polygon([(20, 70), (30, 70), (30, 80), (20, 80)])
    gdf = _building_gdf([{"osm_id": "way/1", "kind": "house", "name": None, "geometry": poly}])
    grid = _grid()
    depth = np.zeros((10, 10), dtype=np.float32)
    depth[2, 2] = 1.0

    curves = load_damage_curves(exposure_dir / "damage_curves.csv")
    _write_asset_values(exposure_dir / "asset_values.csv", sourced=False)
    config = _config(sourced=False)
    values = load_asset_values(exposure_dir / "asset_values.csv", config)

    result = building_losses(gdf, grid, depth, curves, values, config)
    assert result["residential"]["loss_inr"] is None


# =============================================================================
# load_asset_values staleness check
# =============================================================================


def test_load_asset_values_raises_on_stale_csv(exposure_dir):
    _write_asset_values(exposure_dir / "asset_values.csv", sourced=True, fx=2.0, idx=3.0)
    config = _config(sourced=True, fx=99.0, idx=3.0)  # config changed, CSV not regenerated
    with pytest.raises(ValueError, match="does not match"):
        load_asset_values(exposure_dir / "asset_values.csv", config)


# =============================================================================
# estimate_loss end to end
# =============================================================================


def _empty_gpkg(path: Path, geom_type: str) -> None:
    import geopandas as gpd

    gpd.GeoDataFrame(columns=["osm_id", "kind", "name", "geometry"], geometry="geometry",
                      crs=f"EPSG:{CRS_EPSG}").to_file(path, driver="GPKG", layer=path.stem, geometry_type=geom_type)


def _buildings_gpkg(path: Path, rows: list[dict]) -> None:
    import geopandas as gpd

    gpd.GeoDataFrame(rows, geometry="geometry", crs=f"EPSG:{CRS_EPSG}").to_file(
        path, driver="GPKG", layer=path.stem, geometry_type="Polygon")


def test_estimate_loss_ordering_and_placeholder_behaviour(exposure_dir):
    from shapely.geometry import Polygon

    grid = _grid()
    poly = Polygon([(20, 70), (30, 70), (30, 80), (20, 80)])
    _buildings_gpkg(exposure_dir / "buildings.gpkg", [{"osm_id": "way/1", "kind": "house", "name": None, "geometry": poly}])
    _empty_gpkg(exposure_dir / "roads.gpkg", "LineString")

    depth_p10 = np.zeros((10, 10), dtype=np.float32)
    depth_p50 = np.zeros((10, 10), dtype=np.float32)
    depth_p90 = np.zeros((10, 10), dtype=np.float32)
    depth_p10[2, 2], depth_p50[2, 2], depth_p90[2, 2] = 0.5, 1.0, 2.0

    # Placeholder FX: no numbers, but the shape is right and nothing crashes.
    _write_asset_values(exposure_dir / "asset_values.csv", sourced=False)
    placeholder_result = estimate_loss(depth_p10, depth_p50, depth_p90, grid, exposure_dir,
                                        config=_config(sourced=False))
    assert placeholder_result["loss_inr"]["value"] is None
    assert placeholder_result["loss_inr"]["interval"] == "none"
    assert "loss_inr" in placeholder_result["placeholder_fields"]
    assert any("src_031" in a for a in placeholder_result["loss_inr"]["assumptions"])
    assert any("src_032" in a for a in placeholder_result["loss_inr"]["assumptions"])
    assert any("placeholder" in a for a in placeholder_result["loss_inr"]["assumptions"])

    # Sourced FX: real numbers, P10 <= P50 <= P90 (all monotonic in depth for one building/cell).
    _write_asset_values(exposure_dir / "asset_values.csv", sourced=True, fx=2.0, idx=3.0)
    result = estimate_loss(depth_p10, depth_p50, depth_p90, grid, exposure_dir, config=_config(sourced=True, fx=2.0, idx=3.0))
    loss = result["loss_inr"]
    assert loss["low"] <= loss["value"] <= loss["high"]
    assert loss["value"] > 0
    # default_road_width_m is still a placeholder in the base config (_config only
    # overrides FX/price index), so roads stay an honest null Estimate even though
    # this test's roads.gpkg is empty; only the building class must be priced.
    assert result["placeholder_fields"] == ["loss_inr.by_asset_class.infrastructure_roads"]


def test_estimate_loss_assumptions_list_unpriced_classes(exposure_dir):
    grid = _grid()
    _empty_gpkg(exposure_dir / "buildings.gpkg", "Polygon")
    _empty_gpkg(exposure_dir / "roads.gpkg", "LineString")
    _write_asset_values(exposure_dir / "asset_values.csv", sourced=True)

    depth = np.zeros((10, 10), dtype=np.float32)
    result = estimate_loss(depth, depth, depth, grid, exposure_dir, config=_config(sourced=True))
    assumptions = " ".join(result["loss_inr"]["assumptions"])
    assert "hospitals, schools and bridges" in assumptions
    assert "agriculture" in assumptions


# =============================================================================
# Contract validation: a loss_inr this module produces must fit impact.schema.json
# =============================================================================


def test_loss_inr_validates_against_impact_schema(exposure_dir):
    from backend.m0_api.schemas import load_example, validate

    grid = _grid()
    from shapely.geometry import Polygon

    poly = Polygon([(20, 70), (30, 70), (30, 80), (20, 80)])
    _buildings_gpkg(exposure_dir / "buildings.gpkg", [{"osm_id": "way/1", "kind": "house", "name": None, "geometry": poly}])
    _empty_gpkg(exposure_dir / "roads.gpkg", "LineString")
    _write_asset_values(exposure_dir / "asset_values.csv", sourced=True, fx=2.0, idx=3.0)

    depth = np.zeros((10, 10), dtype=np.float32)
    depth[2, 2] = 1.0
    result = estimate_loss(depth, depth, depth, grid, exposure_dir, config=_config(sourced=True, fx=2.0, idx=3.0))

    example = load_example("impact.example.json")
    example["loss_inr"] = result["loss_inr"]
    validate("impact.schema.json", example)  # raises ContractViolation on mismatch
