"""Live Earth Engine render of the near-field pre-/post-event RGB composite -- backs
`imagery.refresh`. Needs a live Earth Engine session (`scene_search._ee_initialize`, which also
checks `GEE_SERVICE_ACCOUNT_EMAIL` / `GEE_SERVICE_ACCOUNT_KEY_PATH` in `.env`). Everything here can
raise (no scene near the date, no credentials, no network); `imagery.refresh` catches that and
falls back to the cached `_rgb.tif` (contract §4.8 fallback), so this module is exercised only by
a manual smoke test with real EE access, same as `provider.EarthEngineProvider`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import rasterio

from backend.shared.grid import build_farfield_grid, build_nearfield_grid
from backend.shared.site_config import Event, SiteConfig

from .imagery import REPO_ROOT, raw_rgb_path
from .provider import S2_COLLECTION
from .scene_search import S2_VIS, _ee_initialize

DATE_WINDOW_DAYS = 15  # +/- this many days around the event date when searching for a usable scene


def render_event_rgb(
    cfg: SiteConfig, event: Event, repo_root: Path = REPO_ROOT, ee_project: str | None = None,
) -> None:
    """Renders a least-cloudy Sentinel-2 RGB composite for each phase's date over the site's
    near-field AOI, overwriting the `..._rgb.tif` each phase's `imagery_pre_event`/
    `imagery_post_event.source` points at (`imagery.raw_rgb_path`, resolved under `repo_root`)."""
    import ee

    _ee_initialize(ee_project)
    far = build_farfield_grid(cfg)
    grid = build_nearfield_grid(cfg, far)

    pixel_grid = {
        "dimensions": {"width": grid.width, "height": grid.height},
        "affineTransform": {
            "scaleX": grid.cell_size_m, "shearX": 0.0, "translateX": grid.origin_x,
            "shearY": 0.0, "scaleY": -grid.cell_size_m, "translateY": grid.origin_y,
        },
        "crsCode": f"EPSG:{grid.crs_epsg}",
    }
    left, top = grid.origin_x, grid.origin_y
    right, bottom = left + grid.width * grid.cell_size_m, top - grid.height * grid.cell_size_m
    aoi = ee.Geometry.Rectangle([left, bottom, right, top], proj=f"EPSG:{grid.crs_epsg}", geodesic=False)

    for phase, sv in (("pre", event.imagery_pre_event), ("post", event.imagery_post_event)):
        date_str = str(sv.value)[:10]
        start = ee.Date(date_str).advance(-DATE_WINDOW_DAYS, "day")
        end = ee.Date(date_str).advance(DATE_WINDOW_DAYS, "day")
        coll = (ee.ImageCollection(S2_COLLECTION).filterBounds(aoi).filterDate(start, end)
                .sort("CLOUDY_PIXEL_PERCENTAGE"))
        if coll.size().getInfo() == 0:
            raise RuntimeError(f"no Sentinel-2 scene within {DATE_WINDOW_DAYS} days of {date_str} "
                                f"for '{cfg.site.id}' {phase}-event")

        bands = ["B4", "B3", "B2"]
        scaled = (
            ee.Image(coll.first()).select(bands)
            .subtract(S2_VIS["min"]).divide(S2_VIS["max"] - S2_VIS["min"])
            .max(0).min(1).pow(1.0 / S2_VIS["gamma"])
        )
        vis = scaled.multiply(255).uint8().clip(aoi)

        arr = ee.data.computePixels({"expression": vis, "fileFormat": "NUMPY_NDARRAY", "grid": pixel_grid})
        rgb = np.stack([np.asarray(arr[b], dtype=np.uint8) for b in bands])

        out_path = raw_rgb_path(sv.source, repo_root)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(
            out_path, "w", driver="GTiff", width=grid.width, height=grid.height, count=3,
            dtype=np.uint8, crs=grid.crs, transform=grid.transform,
        ) as dst:
            dst.write(rgb)
