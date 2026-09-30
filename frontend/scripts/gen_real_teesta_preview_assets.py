"""Generate frontend/public/preview/teesta_real_* (design/target-state-preview).

The preview demo engine paints a synthetic "gorge" channel for every site
(frontend/src/data/preview/engine/raster.ts, scene3d.ts) so it works fully
offline with no real DEM or solver output required. Teesta is the one site
with a real, registered D-Flow FM run already on disk
(data/teesta/runs/teesta_2023_mvp__delft3d, see docs/decisions.md and
backend/m0_api/real_query.py) -- this script takes a one-time static snapshot
of that real run's depth raster and terrain/flood-surface arrays so the
Teesta scenario map can show the real flood shape and real mountain terrain
instead of the synthetic model, without preview mode depending on a live
backend at runtime (CLAUDE.md rule 11).

Run from the repo root with the project's own Python env (needs rasterio):
    .venv/bin/python frontend/scripts/gen_real_teesta_preview_assets.py

Re-run this whenever the registered teesta_2023_mvp__delft3d run changes.
Outputs (checked into git, not gitignored -- these are real, small, static
fixtures, not generated data):
    frontend/public/preview/teesta_real_depth_p50.png
    frontend/public/preview/teesta_real_terrain.bin
    frontend/public/preview/teesta_real_flood_surface.bin
    frontend/public/preview/teesta_real_scene3d.json
"""
from __future__ import annotations

import json
from pathlib import Path

import rasterio

from backend.m0_api import rendering, scene3d as api_scene3d
from backend.shared.grid import raster_bounds_latlng

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = REPO_ROOT / "data/teesta/runs/teesta_2023_mvp__delft3d"
TERRAIN_DIR = REPO_ROOT / "data/teesta/terrain"
OUT_DIR = REPO_ROOT / "frontend/public/preview"

# Small enough to stay a light, git-friendly preview fixture (~200 KB/array)
# rather than the ~5.6 MB/array main's live scene3d endpoint serves at full
# TARGET_GRID_BYTES resolution -- plenty for a rotatable 3D preview.
TARGET_BYTES = 400_000


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    depth_path = RUN_DIR / "summary/max_depth.tif"
    dem_path = TERRAIN_DIR / "dem.tif"

    # 1. Real depth_p50 PNG + its real bounds, via the same styling/rendering
    #    code (contracts/styles.json depth_p50) and bounds helper main uses.
    png_bytes = rendering.render_layer_png(*_read_depth(depth_path), "depth_p50")
    (OUT_DIR / "teesta_real_depth_p50.png").write_bytes(png_bytes)
    bounds_latlng = raster_bounds_latlng(depth_path)

    # 2. Real terrain + flood-surface arrays (same resampling function main's
    #    /scene3d endpoint uses), downsized to TARGET_BYTES.
    terrain, flood, grid_meta = api_scene3d._resampled_arrays(dem_path, depth_path, TARGET_BYTES)
    (OUT_DIR / "teesta_real_terrain.bin").write_bytes(terrain.astype("<f4").tobytes())
    (OUT_DIR / "teesta_real_flood_surface.bin").write_bytes(flood.astype("<f4").tobytes())

    frame_path = TERRAIN_DIR / "nearfield_frame.json"
    frame = (json.loads(frame_path.read_text()) if frame_path.is_file()
              else {"origin_x": grid_meta["origin_x_utm_m"], "origin_y": grid_meta["origin_y_utm_m"],
                    "crs_epsg": grid_meta["crs_epsg"]})
    origin_local_x = grid_meta["origin_x_utm_m"] - frame["origin_x"]
    origin_local_y = grid_meta["origin_y_utm_m"] - frame["origin_y"]

    meta = {
        "contract_version": "0.3.0",
        "source_run_id": "teesta_2023_mvp__delft3d",
        "frame": {
            "crs_epsg": frame["crs_epsg"], "origin_x_utm_m": frame["origin_x"], "origin_y_utm_m": frame["origin_y"],
            "vertical_exaggeration": 1.5, "vertical_exaggeration_applies_to": "z_axis",
            "units": "m", "axis_order": "east,north,up",
        },
        "terrain": {
            "url": "/preview/teesta_real_terrain.bin", "encoding": "float32_le_row_major",
            **grid_meta, "origin_local_x_m": origin_local_x, "origin_local_y_m": origin_local_y,
            "byte_length": int(terrain.nbytes),
        },
        "flood_surface": {
            "url": "/preview/teesta_real_flood_surface.bin", "encoding": "float32_le_row_major",
            "nodata": -9999.0, "basis": "terrain + depth_p50 (real teesta_2023_mvp__delft3d registered run)",
            "width": grid_meta["width"], "height": grid_meta["height"], "byte_length": int(flood.nbytes),
        },
        "depth_raster": {"url": "/preview/teesta_real_depth_p50.png", "bounds_latlng": bounds_latlng, "unit": "m"},
    }
    (OUT_DIR / "teesta_real_scene3d.json").write_text(json.dumps(meta, indent=2))
    print(f"wrote {OUT_DIR} (terrain grid {grid_meta['width']}x{grid_meta['height']})")


def _read_depth(path: Path):
    with rasterio.open(path) as ds:
        return ds.read(1), (ds.nodata if ds.nodata is not None else -9999.0)


if __name__ == "__main__":
    main()
