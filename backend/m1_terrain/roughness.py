"""M1: Manning's n roughness raster from land cover (`docs/handoff_contract.md` §4.1
`roughness.tif`).

Table: `config/manning_n.csv`, not the contract's originally-documented `data/manning_table.csv`
path/columns (`docs/decisions.md` 2026-09-25 "M1 Manning table path" — the table is
project-maintained, not a raw download, so it belongs in git-tracked `config/`, not gitignored
`data/`). Every row is currently `status: placeholder` (Chow 1959 proxies, no site-specific
calibration yet — see the file's own `notes` column), so every `roughness.tif` this module
produces sets `has_placeholders: true` in `provenance.json`.
Columns: `worldcover_code,class,n_default,n_min,n_max,source,source_row,confidence,status,notes`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from backend.shared.grid import FLOAT_NODATA, UINT8_NODATA

REQUIRED_COLUMNS = ["worldcover_code", "class", "n_default", "n_min", "n_max", "source", "status"]


def load_manning_table(path: str | Path) -> pd.DataFrame:
    """Load and validate `config/manning_n.csv`. Raises if a required column is missing or a
    `worldcover_code` repeats."""
    df = pd.read_csv(path)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: manning table is missing required column(s) {missing}")
    if df["worldcover_code"].duplicated().any():
        dups = sorted(df.loc[df["worldcover_code"].duplicated(), "worldcover_code"].tolist())
        raise ValueError(f"{path}: duplicate worldcover_code value(s) {dups}")
    return df


def roughness(
    landcover: np.ndarray,
    table: pd.DataFrame,
    channel_mask: np.ndarray | None = None,
    channel_class_code: int = 999,
) -> tuple[np.ndarray, dict]:
    """`(n_raster, info)`. `n_raster` is float32 Manning's n on `landcover`'s grid.
    `channel_mask` (if given) is forced to `channel_class_code`'s n regardless of the underlying
    land cover, so the main channel is never priced as grass/bare ground because WorldCover's 10 m
    pixels don't resolve a narrow river. Raises if `landcover` has a code absent from the table."""
    codes_present = set(int(c) for c in np.unique(landcover)) - {int(UINT8_NODATA)}
    known = set(table["worldcover_code"].astype(int))
    unknown = sorted(codes_present - known)
    if unknown:
        raise ValueError(f"landcover has code(s) {unknown} with no row in the manning table")

    n_by_code = dict(zip(table["worldcover_code"].astype(int), table["n_default"].astype(float)))
    out = np.full(landcover.shape, FLOAT_NODATA, dtype=np.float32)
    for code, n in n_by_code.items():
        out[landcover == code] = n

    used_channel_override = False
    if channel_mask is not None:
        if channel_class_code not in n_by_code:
            raise ValueError(f"channel_class_code {channel_class_code} has no row in the manning table")
        out[channel_mask] = n_by_code[channel_class_code]
        used_channel_override = True

    placeholder_codes = sorted(int(c) for c in table.loc[table["status"] == "placeholder", "worldcover_code"])
    info = {
        "codes_present": sorted(codes_present), "channel_override_applied": used_channel_override,
        "channel_class_code": channel_class_code, "placeholder_codes": placeholder_codes,
        "has_placeholders": bool(placeholder_codes),
    }
    return out, info
