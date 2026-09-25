"""Loss estimation from JRC depth-damage curves and asset values
(docs/handoff_contract.md §4.7 `loss_inr`; docs/impact_outputs.md §5).

Reads `damage_curves.csv` and `asset_values.csv` (written by
`backend.m6_impact.jrc_damage`) plus `exposure/buildings.gpkg` and
`exposure/roads.gpkg`, and computes loss at the P10/P50/P90 max-depth maps a
flood query produces.

**Scope**: only buildings (residential/commercial/industrial, from
`buildings.gpkg` footprint polygons) and roads (`roads.gpkg`, using a single
placeholder width) are priced. `facilities.gpkg` (hospitals, schools, bridges)
holds points, not footprint polygons — there is no area to apply a per-m2
damage value to without inventing one (CLAUDE.md rule 3) — and `exposure/` has
no cropland layer for agriculture. Both are named in every result's
`assumptions`, never silently dropped.

Every number this module can't compute yet (the FX rate, the price index, the
road width — all `status: placeholder` in `config/impact.yaml`) comes back as
a null Estimate rather than an invented one (`backend/m5_emulator/query.py`'s
`peak_discharge_m3s` pattern).
"""

from __future__ import annotations

import csv
import logging
import warnings
from pathlib import Path
from typing import Literal

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from backend.shared.grid import FLOAT_NODATA, CanonicalGrid

log = logging.getLogger("m6.loss")

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "impact.yaml"

#: asset_class values not priced in loss_inr (see module docstring "Scope").
UNPRICED_CLASSES = ("hospitals", "schools", "bridges", "agriculture")


# =============================================================================
# Config
# =============================================================================


class _LossValue(BaseModel):
    """Same shape as `sites/*.yaml`'s SourcedValue (`backend/shared/site_config.py`),
    but with a free-text `unit` — this config isn't part of the site-config contract."""

    model_config = ConfigDict(extra="forbid")

    value: float | None
    unit: str
    source: str
    status: Literal["sourced", "placeholder"]
    note: str | None = None

    @model_validator(mode="after")
    def _check_status(self):
        if self.value is None and self.status != "placeholder":
            raise ValueError(f"value is null but status is '{self.status}'; null is allowed only for placeholders")
        return self


class LossConfig(BaseModel):
    """`config/impact.yaml`'s `loss:` block (docs/impact_outputs.md §5)."""

    model_config = ConfigDict(extra="forbid")

    jrc_source_damage_curves: str
    jrc_source_asset_values: str
    jrc_region: str
    jrc_country: str
    depth_cap_m: float
    eur_to_inr_2010: _LossValue
    price_index_2010_to_current: _LossValue
    default_road_width_m: _LossValue
    default_building_class: str
    osm_building_to_jrc: dict[str, str]


def load_loss_config(path: str | Path = CONFIG_PATH) -> LossConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return LossConfig.model_validate(raw["loss"])


# =============================================================================
# damage_curves.csv / asset_values.csv
# =============================================================================


def load_damage_curves(path: str | Path) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """asset_class -> (depths_m ascending, damage_fraction), from `damage_curves.csv`
    (docs/handoff_contract.md §4.7: `asset_class,depth_m,damage_fraction,source`)."""
    by_class: dict[str, list[tuple[float, float]]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            by_class.setdefault(row["asset_class"], []).append((float(row["depth_m"]), float(row["damage_fraction"])))
    curves = {}
    for cls, points in by_class.items():
        points.sort()
        depths, fracs = zip(*points)
        curves[cls] = (np.array(depths, dtype=float), np.array(fracs, dtype=float))
    return curves


def damage_fraction(curves: dict[str, tuple[np.ndarray, np.ndarray]], asset_class: str,
                     depth_m: np.ndarray, depth_cap_m: float) -> np.ndarray:
    """Fraction of asset value lost at `depth_m` (metres, >= 0), linearly interpolated
    between the JRC tabulated points (docs/data_sources.md src_031). Capped at
    `depth_cap_m` — the top of the JRC table — where the fraction is 1.0; depths
    above it warn once per call rather than extrapolating past the source data."""
    if asset_class not in curves:
        raise KeyError(f"no damage curve for asset_class {asset_class!r}; have {sorted(curves)}")
    depths, fracs = curves[asset_class]
    d = np.clip(np.asarray(depth_m, dtype=float), 0.0, None)
    if np.any(d > depth_cap_m):
        warnings.warn(f"depth exceeds the JRC tabulated range (0-{depth_cap_m} m) for "
                       f"asset_class {asset_class!r}; capped at fraction 1.0 rather than extrapolated",
                       stacklevel=2)
    return np.interp(np.minimum(d, depth_cap_m), depths, fracs)


def load_asset_values(path: str | Path, config: LossConfig) -> dict[str, dict]:
    """asset_class -> row dict from `asset_values.csv`. Raises if `value_inr_per_unit`
    doesn't match `value_eur2010 x FX x price_index` for the FX/index currently in
    `config` — catches an asset_values.csv left stale after the config was edited
    (regenerate with `python -m backend.m6_impact.jrc_damage`)."""
    rows: dict[str, dict] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows[row["asset_class"]] = row

    fx, idx = config.eur_to_inr_2010, config.price_index_2010_to_current
    if fx.status == "sourced" and idx.status == "sourced":
        for cls, row in rows.items():
            expected = float(row["value_eur2010"]) * fx.value * idx.value
            actual = row.get("value_inr_per_unit")
            if actual in (None, ""):
                raise ValueError(f"asset_values.csv row {cls!r}: value_inr_per_unit is empty but config's "
                                  f"FX rate and price index are both sourced; regenerate the CSV")
            if not np.isclose(float(actual), expected, rtol=1e-6):
                raise ValueError(f"asset_values.csv row {cls!r}: value_inr_per_unit={actual} does not match "
                                  f"value_eur2010 x FX x index = {expected}; regenerate the CSV with "
                                  f"python -m backend.m6_impact.jrc_damage")
    return rows


# =============================================================================
# Depth sampling
# =============================================================================


def sample_depth(grid: CanonicalGrid, depth_array: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Nearest-cell depth (m) at UTM `(xs, ys)` points on `grid`. Points outside the
    grid, or landing on a nodata cell, come back as NaN (excluded by callers)."""
    xs, ys = np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)
    col = np.floor((xs - grid.origin_x) / grid.cell_size_m).astype(np.int64)
    row = np.floor((grid.origin_y - ys) / grid.cell_size_m).astype(np.int64)
    inside = (row >= 0) & (row < grid.height) & (col >= 0) & (col < grid.width)

    depth = np.full(xs.shape, np.nan, dtype=float)
    depth[inside] = depth_array[row[inside], col[inside]]
    depth[depth == FLOAT_NODATA] = np.nan
    return depth


# =============================================================================
# Building / road losses
# =============================================================================


def building_losses(buildings_gdf, grid: CanonicalGrid, depth_array: np.ndarray,
                     curves: dict, values: dict[str, dict], config: LossConfig) -> dict[str, dict]:
    """`{jrc_class: {"loss_inr": float, "n_excluded": int}}` for one depth map.
    Depth is sampled at each building's footprint centroid; loss = damage
    fraction x footprint area (m2) x asset value (INR/m2). Buildings whose
    centroid falls outside the grid, on a dry or nodata cell, are excluded and
    counted (not silently dropped)."""
    if len(buildings_gdf) == 0:
        return {}

    gdf = buildings_gdf.to_crs(grid.crs) if buildings_gdf.crs is not None else buildings_gdf
    centroids = gdf.geometry.centroid
    areas = gdf.geometry.area.to_numpy()
    depths = sample_depth(grid, depth_array, centroids.x.to_numpy(), centroids.y.to_numpy())
    classes = np.array([config.osm_building_to_jrc.get(k, config.default_building_class) for k in gdf["kind"]])

    wet = ~np.isnan(depths) & (depths > 0.0)
    out: dict[str, dict] = {}
    for cls in np.unique(classes):
        cls_mask = classes == cls
        n_excluded = int((~wet & cls_mask).sum())
        priced_mask = wet & cls_mask
        row = values.get(cls)
        if row is None or row["value_inr_per_unit"] in (None, ""):
            out[cls] = {"loss_inr": None, "n_excluded": n_excluded, "n_buildings": int(cls_mask.sum())}
            continue
        value_per_m2 = float(row["value_inr_per_unit"])
        frac = damage_fraction(curves, cls, depths[priced_mask], config.depth_cap_m) if priced_mask.any() else np.array([])
        loss = float(np.sum(frac * areas[priced_mask] * value_per_m2))
        out[cls] = {"loss_inr": loss, "n_excluded": n_excluded, "n_buildings": int(cls_mask.sum())}
    return out


def _densify(line, spacing_m: float) -> tuple[np.ndarray, float]:
    """n evenly spaced sample points along `line` (a shapely LineString) and the
    length (m) each represents, for depth sampling finer than the line's own vertices."""
    length = line.length
    if length <= 0:
        p = line.interpolate(0.0)
        return np.array([[p.x, p.y]]), 0.0
    n = max(1, int(np.ceil(length / spacing_m)))
    pts = np.array([[p.x, p.y] for p in (line.interpolate((i + 0.5) / n, normalized=True) for i in range(n))])
    return pts, length / n


def road_losses(roads_gdf, grid: CanonicalGrid, depth_array: np.ndarray,
                 curves: dict, values: dict[str, dict], config: LossConfig) -> dict:
    """`{"loss_inr": float | None, "flooded_length_m": float}` for one depth map.
    Densifies each road line at the grid resolution, samples depth per segment,
    and prices `damage_fraction x segment_length x road_width x value (INR/m2)`.
    `loss_inr` is None while `config.default_road_width_m` is a placeholder — a
    length can't be priced with an invented width (CLAUDE.md rule 3)."""
    if len(roads_gdf) == 0:
        return {"loss_inr": 0.0 if config.default_road_width_m.status == "sourced" else None, "flooded_length_m": 0.0}

    gdf = roads_gdf.to_crs(grid.crs) if roads_gdf.crs is not None else roads_gdf
    row = values.get("infrastructure_roads")
    width = config.default_road_width_m.value
    priceable = (width is not None and config.default_road_width_m.status == "sourced"
                 and row is not None and row["value_inr_per_unit"] not in (None, ""))
    value_per_m2 = float(row["value_inr_per_unit"]) if priceable else None

    total_loss = 0.0
    flooded_length = 0.0
    for line in gdf.geometry:
        pts, seg_len = _densify(line, grid.cell_size_m)
        depths = sample_depth(grid, depth_array, pts[:, 0], pts[:, 1])
        wet = ~np.isnan(depths) & (depths > 0.0)
        if not wet.any():
            continue
        flooded_length += float(wet.sum()) * seg_len
        if priceable:
            frac = damage_fraction(curves, "infrastructure_roads", depths[wet], config.depth_cap_m)
            total_loss += float(np.sum(frac * seg_len * width * value_per_m2))

    return {"loss_inr": total_loss if priceable else None, "flooded_length_m": flooded_length}


# =============================================================================
# Top-level Estimate
# =============================================================================


def _estimate(value, low, high, unit: str | None, *, kind: str = "predicted",
              interval: str = "P10-P90", confidence: str | None = None, basis: str | None = None) -> dict:
    """Same shape as `backend/m5_emulator/query.py`'s `_estimate` helper."""
    d = {"value": value, "low": low, "high": high, "unit": unit, "interval": interval, "kind": kind}
    if confidence is not None:
        d["confidence"] = confidence
    if basis is not None:
        d["basis"] = basis
    return d


def estimate_loss(depth_p10: np.ndarray, depth_p50: np.ndarray, depth_p90: np.ndarray,
                   grid: CanonicalGrid, exposure_dir: str | Path, config: LossConfig | None = None,
                   depth_confidence: str | None = None) -> dict:
    """`loss_inr` (an Estimate) plus `placeholder_fields` and `caveats`, from the
    P10/P50/P90 max-depth maps of one flood query (docs/handoff_contract.md §4.7).

    `low`/`high` sum each depth map's own per-cell loss independently, which
    treats every cell as hitting its own percentile at once — the reported
    range is therefore WIDER than the true P10-P90 of total loss (an
    assumption, listed in the output, not a bug: computing the correlated
    range would need per-sample Monte Carlo loss, not three summary maps)."""
    config = config or load_loss_config()
    exposure_dir = Path(exposure_dir)
    curves = load_damage_curves(exposure_dir / "damage_curves.csv")
    values = load_asset_values(exposure_dir / "asset_values.csv", config)

    import geopandas as gpd
    buildings = gpd.read_file(exposure_dir / "buildings.gpkg")
    roads = gpd.read_file(exposure_dir / "roads.gpkg")

    by_percentile: dict[str, dict] = {}
    for name, depth in (("p10", depth_p10), ("p50", depth_p50), ("p90", depth_p90)):
        b = building_losses(buildings, grid, depth, curves, values, config)
        r = road_losses(roads, grid, depth, curves, values, config)
        by_percentile[name] = {"buildings": b, "roads": r}

    def _total(percentile: str) -> float | None:
        d = by_percentile[percentile]
        parts = [v["loss_inr"] for v in d["buildings"].values() if v["loss_inr"] is not None]
        parts += [d["roads"]["loss_inr"]] if d["roads"]["loss_inr"] is not None else []
        return float(sum(parts)) if parts else None

    value, low, high = _total("p50"), _total("p10"), _total("p90")
    has_number = value is not None

    by_asset_class: dict[str, dict] = {}
    all_building_classes = set().union(*(d["buildings"] for d in by_percentile.values()))
    for cls in sorted(all_building_classes):
        med = by_percentile["p50"]["buildings"].get(cls, {}).get("loss_inr")
        lo = by_percentile["p10"]["buildings"].get(cls, {}).get("loss_inr")
        hi = by_percentile["p90"]["buildings"].get(cls, {}).get("loss_inr")
        if med is None:
            by_asset_class[cls] = _estimate(None, None, None, "INR", interval="none",
                                             basis="asset_values.csv value_inr_per_unit is empty (FX/price index placeholder)")
        else:
            by_asset_class[cls] = _estimate(med, lo, hi, "INR", confidence=depth_confidence)
    roads_med = by_percentile["p50"]["roads"]["loss_inr"]
    if roads_med is None:
        by_asset_class["infrastructure_roads"] = _estimate(
            None, None, None, "INR", interval="none",
            basis="config.loss.default_road_width_m is a placeholder; no invented road width")
    else:
        by_asset_class["infrastructure_roads"] = _estimate(
            roads_med, by_percentile["p10"]["roads"]["loss_inr"], by_percentile["p90"]["roads"]["loss_inr"], "INR",
            confidence=depth_confidence)

    n_excluded = sum(v["n_excluded"] for v in by_percentile["p50"]["buildings"].values())
    n_default_class = sum(1 for k in buildings["kind"] if k not in config.osm_building_to_jrc) if len(buildings) else 0

    assumptions = [
        f"damage curves: {config.jrc_source_damage_curves} (JRC {config.jrc_region})",
        f"asset values: {config.jrc_source_asset_values} (JRC {config.jrc_country}, 2010 national averages; "
        f"Himalayan stone/timber-built houses may differ substantially from this national average)",
        "loss = damage fraction x footprint/road area x asset value, sampled at each building's "
        "footprint centroid or at road segments densified to the grid resolution",
        f"buildings with an unmapped OSM building=* kind are counted as "
        f"'{config.default_building_class}' ({n_default_class} building(s))",
        f"{n_excluded} building(s) excluded (outside the grid or on a dry/nodata cell)",
        "hospitals, schools and bridges (facilities.gpkg) are not priced: they are points, "
        "not footprint polygons, so there is no area to apply a damage value to",
        "agriculture is not priced: exposure/ has no cropland layer",
        "low/high sum each percentile depth map's own loss independently, so the range is wider "
        "than the true P10-P90 of total loss (cells don't all hit their own percentile at once)",
        "clear-water model: debris impact and channel-erosion damage are not captured",
    ]
    if config.eur_to_inr_2010.status == "placeholder":
        assumptions.append(f"EUR->INR rate: {config.eur_to_inr_2010.source} (placeholder)")
    if config.price_index_2010_to_current.status == "placeholder":
        assumptions.append(f"price index 2010->current: {config.price_index_2010_to_current.source} (placeholder)")
    if config.default_road_width_m.status == "placeholder":
        assumptions.append(f"road width: {config.default_road_width_m.source} (placeholder)")

    if has_number:
        loss_estimate = _estimate(value, low, high, "INR", confidence=depth_confidence)
    else:
        loss_estimate = _estimate(None, None, None, "INR", interval="none",
                                   basis="no priced asset class has a sourced value_inr_per_unit yet "
                                         "(EUR->INR rate and/or price index are placeholders)")
    loss_estimate["by_asset_class"] = by_asset_class
    loss_estimate["assumptions"] = assumptions

    placeholder_fields = []
    if not has_number:
        placeholder_fields.append("loss_inr")
    for cls, est in by_asset_class.items():
        if est["value"] is None:
            placeholder_fields.append(f"loss_inr.by_asset_class.{cls}")

    caveats = [{"id": "loss_national_average", "severity": "warning",
                "text_key": "caveat_loss_national_average"}]
    if not has_number:
        caveats.append({"id": "loss_placeholder", "severity": "warning", "text_key": "caveat_loss_placeholder"})

    return {"loss_inr": loss_estimate, "placeholder_fields": placeholder_fields, "caveats": caveats}
