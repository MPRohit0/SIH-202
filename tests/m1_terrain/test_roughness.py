"""Tests for backend.m1_terrain.roughness."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.m1_terrain import roughness
from backend.m1_terrain.pipeline import MANNING_TABLE_PATH


def test_load_manning_table_reads_real_config_file():
    table = roughness.load_manning_table(MANNING_TABLE_PATH)
    assert {10, 30, 60, 80, 999}.issubset(set(table["worldcover_code"]))
    # documented team decision (docs/decisions.md): every row is a Chow 1959 proxy today
    assert (table["status"] == "placeholder").all()


def test_load_manning_table_rejects_missing_columns(tmp_path):
    path = tmp_path / "bad.csv"
    pd.DataFrame({"worldcover_code": [10], "n_default": [0.1]}).to_csv(path, index=False)
    with pytest.raises(ValueError, match="missing required column"):
        roughness.load_manning_table(path)


def test_load_manning_table_rejects_duplicate_codes(tmp_path):
    path = tmp_path / "dup.csv"
    pd.DataFrame({
        "worldcover_code": [10, 10], "class": ["a", "b"], "n_default": [0.1, 0.2],
        "n_min": [0.05, 0.05], "n_max": [0.2, 0.2], "source": ["x", "y"], "status": ["placeholder", "placeholder"],
    }).to_csv(path, index=False)
    with pytest.raises(ValueError, match="duplicate"):
        roughness.load_manning_table(path)


def test_roughness_maps_codes_to_n():
    table = roughness.load_manning_table(MANNING_TABLE_PATH)
    landcover = np.array([[10, 30], [60, 80]], dtype=np.uint8)
    n, info = roughness.roughness(landcover, table)
    row = table.set_index("worldcover_code")
    assert n[0, 0] == pytest.approx(row.loc[10, "n_default"])
    assert n[0, 1] == pytest.approx(row.loc[30, "n_default"])
    assert n[1, 0] == pytest.approx(row.loc[60, "n_default"])
    assert n[1, 1] == pytest.approx(row.loc[80, "n_default"])
    assert info["has_placeholders"] is True


def test_roughness_channel_override():
    table = roughness.load_manning_table(MANNING_TABLE_PATH)
    landcover = np.full((3, 3), 30, dtype=np.uint8)
    channel_mask = np.zeros((3, 3), dtype=bool)
    channel_mask[1, 1] = True
    n, info = roughness.roughness(landcover, table, channel_mask=channel_mask, channel_class_code=999)
    row = table.set_index("worldcover_code")
    assert n[1, 1] == pytest.approx(row.loc[999, "n_default"])
    assert n[0, 0] == pytest.approx(row.loc[30, "n_default"])
    assert info["channel_override_applied"] is True


def test_roughness_unknown_code_raises():
    table = roughness.load_manning_table(MANNING_TABLE_PATH)
    landcover = np.array([[250]], dtype=np.uint8)
    with pytest.raises(ValueError, match="250"):
        roughness.roughness(landcover, table)
