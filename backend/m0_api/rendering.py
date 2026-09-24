"""M0-5 — render raster layers to transparent PNG overlays (contract §4.6, §5 #11).

Colour scales and class breaks come from exactly one place, `contracts/styles.json`
(contract §6), so the frontend legend, this module and M6's KML export (M6-6) can
never drift apart — this module never hardcodes a colour.

A rendered layer is a GeoTIFF on the site's canonical grid (`backend/shared/grid.py`,
contract §1.4) turned into an RGBA PNG the same shape as the grid, stretched by the
frontend across `grid.bounds_latlng` (an EPSG:4326 Leaflet image overlay is a linear
stretch onto its bounds, not a per-pixel reprojection — the grid is already
north-up in its UTM zone, so this is the standard, cheap approach). Nodata cells and
cells with no signal (value <= 0: dry ground, zero probability, zero depth) are fully
transparent, so the overlay shows only what actually floods.

`render_and_cache` writes the PNG once per `(query_id, layer_id)` next to the source
GeoTIFF (contract §1.8 `queries/<query_id>/layers/`) and reuses it on the next
request.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import rasterio
from rasterio.io import MemoryFile

from backend.m0_api import schemas

# Layers without their own styles.json entry reuse a related layer's colour scale
# (contract §4.6 layer list vs §6 styles: only one scale per quantity is defined).
LAYER_STYLE_ID = {
    "p_inundation": "p_inundation",
    "extent_class": "extent_class",
    "depth_p50": "depth_p50",
    "depth_p10": "depth_p50",
    "depth_p90": "depth_p50",
    "arrival_p50": "arrival_p50",
    "arrival_p10": "arrival_p50",
    "arrival_p90": "arrival_p50",
    "velocity_p50": "velocity_p50",
    "velocity_p90": "velocity_p50",
    "depth_diff": "depth_diff",
    "depth_diff_nearfield": "depth_diff",
}

TRANSPARENT = (0, 0, 0, 0)


@lru_cache(maxsize=1)
def load_styles() -> dict:
    return json.loads((schemas.CONTRACTS_DIR / "styles.json").read_text())


def style_for_layer(layer_id: str, styles: dict | None = None) -> tuple[str, dict]:
    styles = styles if styles is not None else load_styles()
    style_id = LAYER_STYLE_ID.get(layer_id, layer_id)
    if style_id not in styles:
        raise ValueError(f"no style for layer '{layer_id}' (style_id '{style_id}' not in styles.json)")
    return style_id, styles[style_id]


def _hex_to_rgb(hex_colour: str) -> tuple[int, int, int]:
    h = hex_colour.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _lerp_rgb(c0: tuple[int, int, int], c1: tuple[int, int, int], t: np.ndarray) -> np.ndarray:
    """t in [0, 1] -> (3, ...) uint8 array interpolated between c0 and c1."""
    c0a, c1a = np.array(c0, dtype=np.float64), np.array(c1, dtype=np.float64)
    out = c0a[:, None] + (c1a - c0a)[:, None] * t[None, :]
    return np.clip(np.round(out), 0, 255).astype(np.uint8).reshape(3, *t.shape)


def _rgba_canvas(shape: tuple[int, int]) -> np.ndarray:
    return np.zeros((4, *shape), dtype=np.uint8)


def _continuous(array: np.ndarray, valid: np.ndarray, style: dict) -> np.ndarray:
    stops = sorted(style["stops"])
    values = np.array([s[0] for s in stops], dtype=np.float64)
    colours = [_hex_to_rgb(s[1]) for s in stops]

    out = _rgba_canvas(array.shape)
    flat_val = np.clip(array, values[0], values[-1])
    idx = np.clip(np.searchsorted(values, flat_val, side="right") - 1, 0, len(values) - 2)
    lo, hi = values[idx], values[idx + 1]
    t = np.where(hi > lo, (flat_val - lo) / np.where(hi > lo, hi - lo, 1.0), 0.0)

    rgb = np.zeros((3, *array.shape), dtype=np.uint8)
    for bucket in np.unique(idx[valid]):
        mask = valid & (idx == bucket)
        rgb[:, mask] = _lerp_rgb(colours[bucket], colours[bucket + 1], t[mask])
    out[0:3] = rgb
    out[3][valid] = 255
    return out


def _classes(array: np.ndarray, valid: np.ndarray, style: dict) -> np.ndarray:
    breaks_key = next(k for k in style if k.startswith("breaks_"))
    breaks = np.array(style[breaks_key], dtype=np.float64)
    colours = [_hex_to_rgb(c) for c in style["colors"]]
    if len(colours) != len(breaks) + 1:
        raise ValueError("styles.json: 'colors' must have one more entry than 'breaks_*'")

    bucket = np.searchsorted(breaks, array, side="right")
    out = _rgba_canvas(array.shape)
    rgb = np.zeros((3, *array.shape), dtype=np.uint8)
    for b in np.unique(bucket[valid]):
        mask = valid & (bucket == b)
        rgb[:, mask] = np.array(colours[b], dtype=np.uint8)[:, None]
    out[0:3] = rgb
    out[3][valid] = 255
    return out


def _diverging(array: np.ndarray, valid: np.ndarray, style: dict) -> np.ndarray:
    lo, hi = style["range_m"]
    c_lo, c_mid, c_hi = (_hex_to_rgb(c) for c in style["colors"])
    clamped = np.clip(array, lo, hi)

    out = _rgba_canvas(array.shape)
    rgb = np.zeros((3, *array.shape), dtype=np.uint8)
    below = valid & (clamped <= 0)
    above = valid & (clamped > 0)
    if below.any():
        t = (clamped[below] - lo) / (0 - lo) if lo < 0 else np.ones_like(clamped[below])
        rgb[:, below] = _lerp_rgb(c_lo, c_mid, np.clip(t, 0, 1))
    if above.any():
        t = clamped[above] / hi if hi > 0 else np.ones_like(clamped[above])
        rgb[:, above] = _lerp_rgb(c_mid, c_hi, np.clip(t, 0, 1))
    out[0:3] = rgb
    out[3][valid] = 255
    return out


def _extent_class(array: np.ndarray, style: dict) -> np.ndarray:
    """array: uint8, 0 dry / 1 POSSIBLE / 2 HIGH (contract §4.6)."""
    out = _rgba_canvas(array.shape)
    zone_of = {1: "possible", 2: "high"}
    for code, zone_key in zone_of.items():
        zone = style[zone_key]
        mask = array == code
        if not mask.any():
            continue
        r, g, b = _hex_to_rgb(zone["fill"])
        out[0][mask], out[1][mask], out[2][mask] = r, g, b
        out[3][mask] = round(zone["opacity"] * 255)
    return out


def colorize(array: np.ndarray, nodata: float, layer_id: str, styles: dict | None = None) -> np.ndarray:
    """RGBA `(4, H, W)` uint8 for `array` (on a canonical grid), coloured by
    `layer_id`'s style in `styles.json`. Nodata and non-positive cells (dry / no
    signal) are fully transparent."""
    style_id, style = style_for_layer(layer_id, styles)
    # float64 throughout: a float32 source can drift a hair past an exact stop/break
    # value (e.g. 0.1 -> 0.10000000149), which would otherwise blend in a whisker of
    # the next stop's colour instead of returning it exactly.
    array = np.asarray(array, dtype=np.float64) if np.issubdtype(np.asarray(array).dtype, np.floating) else np.asarray(array)

    if style_id == "extent_class":
        return _extent_class(array.astype(np.uint8), style)

    valid = np.isfinite(array) & (array != nodata) & (array > 0)
    style_type = style["type"]
    if style_type == "continuous":
        return _continuous(array, valid, style)
    if style_type == "classes":
        return _classes(array, valid, style)
    if style_type == "diverging":
        # depth_diff can be legitimately negative (less depth than baseline); only nodata is excluded.
        valid = np.isfinite(array) & (array != nodata)
        return _diverging(array, valid, style)
    raise ValueError(f"unknown style type '{style_type}' for style_id '{style_id}'")


def render_layer_png(array: np.ndarray, nodata: float, layer_id: str, styles: dict | None = None) -> bytes:
    """Colour `array` per `layer_id`'s style and encode it as an RGBA PNG."""
    rgba = colorize(array, nodata, layer_id, styles)
    height, width = rgba.shape[1:]
    with MemoryFile() as mem:
        with mem.open(driver="PNG", width=width, height=height, count=4, dtype="uint8") as ds:
            ds.write(rgba)
        return bytes(mem.read())


def render_and_cache(tif_path: Path, layer_id: str, png_path: Path | None = None, styles: dict | None = None) -> bytes:
    """Render `tif_path` (a GeoTIFF on a canonical grid) to PNG, reusing a cached
    render at `png_path` (default: same path with a `.png` extension) when present."""
    tif_path = Path(tif_path)
    png_path = Path(png_path) if png_path is not None else tif_path.with_suffix(".png")
    if png_path.is_file():
        return png_path.read_bytes()

    with rasterio.open(tif_path) as ds:
        array = ds.read(1)
        nodata = ds.nodata if ds.nodata is not None else float("nan")

    png_bytes = render_layer_png(array, nodata, layer_id, styles)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    png_path.write_bytes(png_bytes)
    return png_bytes
