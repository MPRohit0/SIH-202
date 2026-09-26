"""`select_snapshot_indices` is pure numpy (no binary needed); `run_isosurface`/`convert_surfaces`
are exercised against the real `IsoSurface_linux64` on the shipped pilot particle data, gated on
`DSPH_BIN_DIR` like every other real-binary check in this project."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.m4_sph import surfaces

DSPH_BIN_DIR = os.environ.get("DSPH_BIN_DIR")
PILOT_DATA = Path(DSPH_BIN_DIR).parents[1] / "examples" / "main" / "01_DamBreak" / "CaseDambreakVal2D_out" / "data" if DSPH_BIN_DIR else None


def test_select_snapshot_indices_picks_nearest_to_each_interval():
    # multiples of 2s up to 5.0s are 0, 2, 4 -- nearest sample to each is 0.0, 2.1, 4.05
    times_s = [0.0, 0.9, 2.1, 2.9, 4.05, 5.0]
    assert surfaces.select_snapshot_indices(times_s, interval_s=2.0) == [0, 2, 4]


def test_select_snapshot_indices_empty():
    assert surfaces.select_snapshot_indices([], interval_s=300.0) == []


def test_select_snapshot_indices_single_sample():
    assert surfaces.select_snapshot_indices([0.0], interval_s=300.0) == [0]


@pytest.mark.skipif(not DSPH_BIN_DIR, reason="set DSPH_BIN_DIR to a DualSPHysics bin/ directory to run")
def test_real_isosurface_and_convert(tmp_path):
    prefix = tmp_path / "surf"
    surfaces.run_isosurface(PILOT_DATA, prefix, DSPH_BIN_DIR)
    vtk_files = sorted(tmp_path.glob("surf_*.vtk"))
    assert len(vtk_files) > 1

    time_out_s = 0.01  # CaseDambreakVal2D's TimeOut
    times_s = [i * time_out_s for i in range(len(vtk_files))]
    out_dir = tmp_path / "surfaces"
    written = surfaces.convert_surfaces(prefix, times_s, interval_s=0.5, t_start_s=2000.0, out_dir=out_dir)

    assert written
    assert all(p.is_file() and p.stat().st_size > 0 for p in written)
    assert all(p.name.startswith("t2") and p.suffix == ".glb" for p in written)
    assert len({p.name for p in written}) == len(written)  # no duplicate seconds
