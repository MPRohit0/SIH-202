"""M7 GEE fetch orchestrator + CLI: `data/<site_id>/gee/` (contract §4.8) `lake_area.csv`,
`lake_latest.geojson`, `rainfall.csv`, `gee_meta.json`, `recheck.json`.

CLI: `python -m backend.m7_gee.fetch <site_id> [--months N] [--rain-days N]
[--rain-dataset chirps|gpm_imerg] [--ee-project P] [--recheck-threshold-pct X]
[--reference-area-m2 A] [--model delft3d] [--data-dir DIR]`.

Order of work (`docs/decisions.md` "M7 GEE fetch"): per month, oldest to newest -- Sentinel-2 NDWI,
falling back to Sentinel-1 VV when S2 is too cloudy, or skipped when the lake is ice-covered
(`lake_area.choose_method`) -- then the polygon for the latest valid month, then the HydroBASINS
catchment and its rainfall, then the recheck against the trained library's reference area.
Past months already in the cache are not refetched (`cache.merge_lake_rows`); the current and
previous month always are, since they can still change.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pyproj

from backend.shared.site_config import Dam, SiteConfig, load_site_config

from . import cache, lake_area as la, rainfall as rf, recheck as rc
from .provider import EarthEngineProvider, Provider
from .settings import GeeSettings

log = logging.getLogger("m7.fetch")

LAKE_DAM_KINDS = ("moraine_dammed_lake", "landslide_dam")
REFETCH_TRAILING_MONTHS = 2  # the current + previous month are always refetched, even if cached


@dataclass
class FetchResult:
    site_id: str
    lake_area_path: Path | None = None
    lake_latest_path: Path | None = None
    rainfall_path: Path | None = None
    meta_path: Path | None = None
    recheck_path: Path | None = None
    errors: list[str] = field(default_factory=list)


def _month_starts(months_back: int, as_of: date | None = None) -> list[date]:
    """`months_back` month-start dates, oldest first, ending with the month containing `as_of`
    (default: today, UTC)."""
    as_of = as_of or datetime.now(timezone.utc).date()
    current = as_of.replace(day=1)
    out = []
    y, m = current.year, current.month
    for _ in range(months_back):
        out.append(date(y, m, 1))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return list(reversed(out))


def _month_end(month_start: date) -> date:
    y, m = month_start.year, month_start.month
    return date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)


def lake_seed_dam(cfg: SiteConfig) -> Dam:
    for dam in cfg.dams:
        if dam.kind in LAKE_DAM_KINDS:
            return dam
    raise ValueError(
        f"site '{cfg.site.id}' has no dam of kind {LAKE_DAM_KINDS} to seed the lake-area fetch on"
    )


def _placeholder_deps(cfg: SiteConfig, dam: Dam) -> list[str]:
    deps = []
    if cfg.crs.utm_epsg.status == "placeholder":
        deps.append("crs.utm_epsg")
    if dam.location.status == "placeholder":
        idx = next(i for i, d in enumerate(cfg.dams) if d.id == dam.id)
        deps.append(f"dams[{idx}].location")
    return deps


def _lonlat_to_utm(lon: float, lat: float, epsg: int) -> tuple[float, float]:
    return pyproj.Transformer.from_crs(4326, epsg, always_xy=True).transform(lon, lat)


def _fetch_lake_area(
    site_id: str, cfg: SiteConfig, dam: Dam, provider: Provider, settings: GeeSettings, data_dir: Path,
) -> tuple[list[dict], dict, dict | None]:
    """Returns (merged rows, per-month detail for `gee_meta.json`, the latest valid month's
    component/grid/date for `lake_latest.geojson` -- or `None` if no month fetched this run had a
    usable component)."""
    epsg = cfg.crs.utm_epsg.value
    seed_x, seed_y = _lonlat_to_utm(dam.location.value[0], dam.location.value[1], epsg)
    grid = la.build_aoi_grid(seed_x, seed_y, epsg, settings)
    seed_rc = la.seed_rowcol(grid, seed_x, seed_y)

    cached_rows = cache.read_lake_area(site_id, data_dir)
    cached_dates = {r["date"] for r in cached_rows}
    months = _month_starts(settings.months_back)
    always_refetch = {m.isoformat() for m in months[-REFETCH_TRAILING_MONTHS:]}

    fresh_rows: list[dict] = []
    month_detail: dict[str, dict] = {}
    latest_component = None  # (date_str, component, grid)

    for month_start in months:
        date_str = month_start.isoformat()
        if date_str in cached_dates and date_str not in always_refetch:
            continue
        month_end = _month_end(month_start)

        s2 = provider.s2_month(grid, month_start, month_end)
        cloud_pct = None if s2 is None else round(100.0 - s2.valid_pct, 1)
        snow_ice_pct = None if s2 is None else s2.snow_ice_pct

        raster, method = None, "skip"
        if snow_ice_pct is not None and snow_ice_pct > settings.max_snow_ice_pct:
            method, reason = "skip", "snow_ice"
        elif s2 is not None and cloud_pct is not None and cloud_pct <= settings.max_cloud_pct:
            method, reason = "s2_water_index", None
            raster = s2
        else:
            s1 = provider.s1_month(grid, month_start, month_end)
            if s1 is not None and s1.valid_pct >= settings.min_valid_pct:
                method, reason = "s1_threshold", None
                raster = s1
            else:
                method, reason = "skip", "no_usable_scene"

        if raster is None:
            fresh_rows.append({"date": date_str, "area_m2": None, "method": None,
                                "cloud_pct": cloud_pct, "scene_ids": ""})
            month_detail[date_str] = {"method": "skip", "reason": reason,
                                       "cloud_pct": cloud_pct, "snow_ice_pct": snow_ice_pct}
            continue

        clamp = (settings.ndwi_threshold_clamp if method == "s2_water_index"
                 else settings.s1_vv_threshold_clamp_db)
        below = method == "s1_threshold"
        threshold = la.otsu_threshold(raster.index, clamp)
        nir = raster.nir if method == "s2_water_index" else None
        mask = la.water_mask(raster.index, threshold, below=below,
                              nir=nir, nir_max=settings.nir_reflectance_max)
        component = la.seed_component(mask, seed_rc)
        area_m2 = la.component_area_m2(component, grid)

        fresh_rows.append({
            "date": date_str, "area_m2": area_m2, "method": method,
            "cloud_pct": cloud_pct if method == "s2_water_index" else None,
            "scene_ids": ";".join(raster.scene_ids),
        })
        month_detail[date_str] = {
            "method": method, "threshold": threshold, "cloud_pct": cloud_pct,
            "snow_ice_pct": snow_ice_pct, "scene_ids": raster.scene_ids,
            "acquisition_dates": raster.acquisition_dates,
        }
        if latest_component is None or date_str > latest_component[0]:
            latest_component = (date_str, component, grid, method)

    merged = cache.merge_lake_rows(cached_rows, fresh_rows)
    latest = None
    if latest_component is not None:
        latest_date, component, comp_grid, method = latest_component
        latest_valid_date = max((r["date"] for r in merged if r["area_m2"] is not None), default=None)
        if latest_valid_date == latest_date:
            latest = {"date": latest_date, "component": component, "grid": comp_grid, "method": method}

    return merged, month_detail, latest


def run(
    site_id: str,
    settings: GeeSettings | None = None,
    provider: Provider | None = None,
    data_dir: str | Path = cache.DATA_DIR,
    reference_area_m2: float | None = None,
    model: str = "delft3d",
) -> FetchResult:
    settings = settings or GeeSettings()
    provider = provider or EarthEngineProvider()
    data_dir = Path(data_dir)
    cfg = load_site_config(site_id)
    dam = lake_seed_dam(cfg)
    placeholder_deps = _placeholder_deps(cfg, dam)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = FetchResult(site_id=site_id)

    try:
        lake_rows, month_detail, latest = _fetch_lake_area(site_id, cfg, dam, provider, settings, data_dir)
        lake_area_source = "live"
    except Exception as e:  # provider failure: keep the existing cache (contract §4.8 fallback)
        log.warning("lake-area fetch failed for '%s', keeping cache: %s", site_id, e)
        result.errors.append(f"lake_area: {e}")
        lake_rows = cache.read_lake_area(site_id, data_dir)
        month_detail, latest, lake_area_source = {}, None, "cache"

    result.lake_area_path = cache.write_lake_area(site_id, lake_rows, data_dir)

    if latest is not None:
        geojson = la.polygonize_lonlat(latest["component"], latest["grid"])
        area_m2 = next(r["area_m2"] for r in lake_rows if r["date"] == latest["date"])
        feature = {"type": "Feature", "geometry": geojson,
                    "properties": {"date": latest["date"], "area_m2": area_m2, "method": latest["method"]}}
        result.lake_latest_path = cache.write_lake_latest(site_id, feature, data_dir)
    else:
        result.lake_latest_path = cache.gee_dir(site_id, data_dir) / "lake_latest.geojson"
        if not result.lake_latest_path.is_file():
            cache.write_lake_latest(site_id, {}, data_dir)

    try:
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=settings.rain_days_back)
        catchment = provider.catchment(dam.location.value[0], dam.location.value[1], settings.hydrobasins_level)
        daily = provider.rainfall_daily(catchment["geojson"], start, end, settings.rain_dataset)
        rain_rows = rf.to_rows(daily, dataset=settings.rain_dataset)
        rain_source = "live"
    except Exception as e:
        log.warning("rainfall fetch failed for '%s', keeping cache: %s", site_id, e)
        result.errors.append(f"rainfall: {e}")
        rain_rows = cache.read_rainfall(site_id, data_dir)
        catchment = {"basin_ids": [], "geojson": None}
        rain_source = "cache"

    result.rainfall_path = cache.write_rainfall(site_id, rain_rows, data_dir)
    if catchment.get("geojson") is not None:
        cache.write_json(site_id, "catchment.geojson", catchment["geojson"], data_dir)

    accum = rf.accumulations(rain_rows, settings.rain_accumulation_windows_days)

    all_scene_ids = sorted({sid for d in month_detail.values() for sid in d.get("scene_ids", [])})
    all_acq_dates = sorted({dt for d in month_detail.values() for dt in d.get("acquisition_dates", [])})
    cloud_pcts = [d["cloud_pct"] for d in month_detail.values() if d.get("cloud_pct") is not None]

    meta = {
        "contract_version": cache.CONTRACT_VERSION,
        "site_id": site_id,
        "fetched_at": now,
        "lake_area": {"dataset": "sentinel-1/sentinel-2", "scene_ids": all_scene_ids,
                      "acquisition_dates": all_acq_dates,
                      "cloud_pct": round(sum(cloud_pcts) / len(cloud_pcts), 1) if cloud_pcts else None,
                      "fetched_at": now, "source": lake_area_source},
        "lake_latest": {"dataset": "sentinel-1/sentinel-2",
                         "scene_ids": month_detail.get(latest["date"], {}).get("scene_ids", []) if latest else [],
                         "acquisition_dates": month_detail.get(latest["date"], {}).get("acquisition_dates", []) if latest else [],
                         "cloud_pct": month_detail.get(latest["date"], {}).get("cloud_pct") if latest else None,
                         "fetched_at": now, "source": lake_area_source if latest else "cache"},
        "rainfall": {"dataset": settings.rain_dataset, "scene_ids": [], "acquisition_dates": [],
                     "cloud_pct": None, "fetched_at": now, "source": rain_source},
        "lake_area_months": month_detail,
        "catchment": {"basin_ids": catchment.get("basin_ids", [])},
        "rainfall_accumulations": accum,
        "settings": {k: (list(v) if isinstance(v, tuple) else v) for k, v in settings.model_dump().items()},
        "has_placeholders": bool(placeholder_deps),
        "placeholder_fields": placeholder_deps,
        "caveats": [
            {"id": "clear_sky_bias", "severity": "info",
             "text_key": "caveat_gee_clear_sky_bias"},
            {"id": "radar_shadow", "severity": "info",
             "text_key": "caveat_gee_radar_shadow"},
            {"id": "chirps_mountain_underestimate", "severity": "warning",
             "text_key": "caveat_gee_chirps_mountain_underestimate"},
        ],
    }
    result.meta_path = cache.write_json(site_id, "gee_meta.json", meta, data_dir)

    latest_area = next((r["area_m2"] for r in reversed(lake_rows) if r["area_m2"] is not None), None)
    if reference_area_m2 is None:
        manifest = _read_trained_at(site_id, model, data_dir)
        reference_area_m2 = rc.reference_area(lake_rows, manifest["trained_at"]) if manifest else None
    recheck = rc.compute_recheck(site_id, latest_area, reference_area_m2, settings.recheck_threshold_pct, now)
    result.recheck_path = cache.write_json(site_id, "recheck.json", recheck, data_dir)

    return result


def _read_trained_at(site_id: str, model: str, data_dir: Path) -> dict | None:
    manifest_path = Path(data_dir) / site_id / "emulator" / model / "manifest.json"
    if not manifest_path.is_file():
        return None
    import json
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("site_id")
    parser.add_argument("--months", type=int, default=None, help="overrides GeeSettings.months_back")
    parser.add_argument("--rain-days", type=int, default=None, help="overrides GeeSettings.rain_days_back")
    parser.add_argument("--rain-dataset", choices=["chirps", "gpm_imerg"], default=None)
    parser.add_argument("--ee-project", default=None, help="Cloud project for ee.Initialize()")
    parser.add_argument("--recheck-threshold-pct", type=float, default=None)
    parser.add_argument("--reference-area-m2", type=float, default=None)
    parser.add_argument("--model", default="delft3d", choices=["delft3d", "sph"])
    parser.add_argument("--data-dir", type=Path, default=cache.DATA_DIR)
    args = parser.parse_args(argv)

    overrides = {}
    if args.months is not None:
        overrides["months_back"] = args.months
    if args.rain_days is not None:
        overrides["rain_days_back"] = args.rain_days
    if args.rain_dataset is not None:
        overrides["rain_dataset"] = args.rain_dataset
    if args.recheck_threshold_pct is not None:
        overrides["recheck_threshold_pct"] = args.recheck_threshold_pct
    settings = GeeSettings(**overrides)

    from .scene_search import _ee_initialize
    try:
        _ee_initialize(args.ee_project)
        provider = EarthEngineProvider()
    except RuntimeError as e:
        log.warning("Earth Engine unavailable (%s); falling back to the existing cache only.", e)
        provider = _CacheOnlyProvider()

    try:
        result = run(args.site_id, settings=settings, provider=provider, data_dir=args.data_dir,
                     reference_area_m2=args.reference_area_m2, model=args.model)
    except (FileNotFoundError, ValueError) as e:
        log.error(str(e))
        return 1

    for path in (result.lake_area_path, result.lake_latest_path, result.rainfall_path,
                 result.meta_path, result.recheck_path):
        print(f"wrote {path}")
    if result.errors:
        for e in result.errors:
            log.warning("%s", e)
    return 0


def best_effort_provider(ee_project: str | None = None) -> Provider:
    """A live `EarthEngineProvider` if Earth Engine can be reached, else `_CacheOnlyProvider` so
    `run()` falls back to the existing cache (contract §4.8). Shared by `POST /gee/{id}/refresh`
    (`backend/m0_api/main.py`) and the worker's scheduled re-checks, so both use the exact same
    live/cache decision."""
    from .scene_search import _ee_initialize

    try:
        _ee_initialize(ee_project)
        return EarthEngineProvider()
    except Exception as e:
        log.warning("Earth Engine unavailable (%s); falling back to the existing cache only.", e)
        return _CacheOnlyProvider()


class _CacheOnlyProvider:
    """Used by the CLI when Earth Engine itself can't be reached at all -- every call fails, which
    makes `run()` fall back to the cache for both lake area and rainfall (contract §4.8: "cache,
    then screenshot fallback")."""

    def s2_month(self, *a, **k):
        raise RuntimeError("Earth Engine unavailable")

    def s1_month(self, *a, **k):
        raise RuntimeError("Earth Engine unavailable")

    def catchment(self, *a, **k):
        raise RuntimeError("Earth Engine unavailable")

    def rainfall_daily(self, *a, **k):
        raise RuntimeError("Earth Engine unavailable")


if __name__ == "__main__":
    sys.exit(main())
