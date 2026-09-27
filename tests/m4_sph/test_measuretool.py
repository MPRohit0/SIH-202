"""Unit tests for `measuretool.py`'s points-file writers and CSV parsers, against literal text
fixed in the exact format the real `MeasureTool_linux64` 5.4 writes (checked against the binary
on real pilot particle data before being hard-coded here -- `docs/decisions.md`, today's session).
A real-binary smoke test (gated on `DSPH_BIN_DIR`, mirroring `test_gencase_smoke.py`) exercises
the subprocess call itself."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from backend.m4_sph import measuretool as mt

DSPH_BIN_DIR = os.environ.get("DSPH_BIN_DIR")
PILOT_DATA = Path(DSPH_BIN_DIR).parents[1] / "examples" / "main" / "01_DamBreak" / "CaseDambreakVal2D_out" / "data" if DSPH_BIN_DIR else None


def test_write_column_points_format(tmp_path):
    path = mt.write_column_points(tmp_path / "cols.txt", [(0.2, 0.0, 1.0, 0.5, 3.0), (0.4, 0.0, 2.0, 0.25, 4.0)])
    text = path.read_text(encoding="ascii")
    assert text.splitlines() == [
        "POINTSENDLIST", "0.2 0.0 1.0", "0 0 0.5", "0.2 0.0 3.0",
        "POINTSENDLIST", "0.4 0.0 2.0", "0 0 0.25", "0.4 0.0 4.0",
    ]


def test_write_explicit_points_format(tmp_path):
    path = mt.write_explicit_points(tmp_path / "pts.txt", [(0.2, 0.0, 0.5), (0.4, 0.0, 1.0)])
    text = path.read_text(encoding="ascii")
    assert text.splitlines() == ["POINTS", "0.2 0.0 0.5", "0.4 0.0 1.0"]


def test_parse_elevation_csv_single_column(tmp_path):
    path = tmp_path / "elev.csv"
    path.write_text(
        " ;PosX [m]:;0.2\n ;PosY [m]:;0\n ;PosZ [m]:;2.00973\n"
        "Part;Time [s];Elevation_0 [m]\n"
        "0;0;2.00973\n"
        "1;0.0100156;2.00971\n",
        encoding="ascii",
    )
    t_s, elevation = mt.parse_elevation_csv(path, [(0.2, 0.0)])
    np.testing.assert_allclose(t_s, [0.0, 0.0100156])
    assert elevation.shape == (2, 1)
    np.testing.assert_allclose(elevation[:, 0], [2.00973, 2.00971])


def test_parse_elevation_csv_multiple_columns(tmp_path):
    path = tmp_path / "elev.csv"
    path.write_text(
        " ;PosX [m]:;0.2;0.4\n ;PosY [m]:;0;0\n ;PosZ [m]:;0;0\n"
        "Part;Time [s];Elevation_0 [m];Elevation_1 [m]\n"
        "0;0;2.00973;2.00973\n"
        "1;0.0100156;2.00971;2.00969\n",
        encoding="ascii",
    )
    t_s, elevation = mt.parse_elevation_csv(path, [(0.2, 0.0), (0.4, 0.0)])
    assert elevation.shape == (2, 2)
    np.testing.assert_allclose(elevation[1], [2.00971, 2.00969])


def test_parse_elevation_csv_reorders_when_measuretool_sorts_columns(tmp_path):
    """MeasureTool's `-elevation` output re-sorts POINTSENDLIST columns by position; this is the
    real behaviour that produced an unphysical ~259 m SPH depth field on the Teesta MVP run
    (docs/progress.md 2026-09-27) before this reordering was added. The CSV here lists column
    (0.4, 0.0) before (0.2, 0.0), the opposite of the request order."""
    path = tmp_path / "elev.csv"
    path.write_text(
        " ;PosX [m]:;0.4;0.2\n ;PosY [m]:;0;0\n ;PosZ [m]:;0;0\n"
        "Part;Time [s];Elevation_0 [m];Elevation_1 [m]\n"
        "0;0;9.0;1.0\n"
        "1;0.01;9.5;1.5\n",
        encoding="ascii",
    )
    t_s, elevation = mt.parse_elevation_csv(path, [(0.2, 0.0), (0.4, 0.0)])
    # requested (0.2, 0.0) first -> its series (1.0, 1.5) must come back in column 0
    np.testing.assert_allclose(elevation[:, 0], [1.0, 1.5])
    np.testing.assert_allclose(elevation[:, 1], [9.0, 9.5])


def test_parse_elevation_csv_rejects_unmatched_point(tmp_path):
    path = tmp_path / "elev.csv"
    path.write_text(
        " ;PosX [m]:;0.2\n ;PosY [m]:;0\n ;PosZ [m]:;0\n"
        "Part;Time [s];Elevation_0 [m]\n0;0;1.0\n",
        encoding="ascii",
    )
    with pytest.raises(ValueError, match="no unclaimed output column"):
        mt.parse_elevation_csv(path, [(99.0, 99.0)])


def test_parse_velocity_csv(tmp_path):
    path = tmp_path / "vel.csv"
    path.write_text(
        " ;Pos X/Y/Z [m]:;0.2;0;0;0.4;0;0.5\n"
        "Part;Time [s];Vel_0.x [m/s];Vel_0.y [m/s];Vel_0.z [m/s];Vel_1.x [m/s];Vel_1.y [m/s];Vel_1.z [m/s]\n"
        "0;0;0;0;0;0;0;0\n"
        "1;0.01;0.1;0.2;0.3;0.4;0.5;0.6\n",
        encoding="ascii",
    )
    t_s, vel = mt.parse_velocity_csv(path)
    assert vel.shape == (2, 2, 3)
    np.testing.assert_allclose(vel[1, 0], [0.1, 0.2, 0.3])
    np.testing.assert_allclose(vel[1, 1], [0.4, 0.5, 0.6])


@pytest.mark.skipif(not DSPH_BIN_DIR, reason="set DSPH_BIN_DIR to a DualSPHysics bin/ directory to run")
def test_real_binary_elevation_and_velocity_on_pilot_data(tmp_path):
    """Runs the real `MeasureTool_linux64` against the shipped pilot dam-break particle data
    (no case generation/solving needed -- that data already exists on disk)."""
    cols = [(0.2, 0.0, 0.0, 0.02, 2.1), (0.4, 0.0, 0.0, 0.02, 2.1)]
    points_path = mt.write_column_points(tmp_path / "cols.txt", cols)
    elev_csv = mt.run_elevation(PILOT_DATA, points_path, tmp_path / "elev", DSPH_BIN_DIR)
    t_s, elevation = mt.parse_elevation_csv(elev_csv, [(c[0], c[1]) for c in cols])
    assert elevation.shape[1] == 2
    assert elevation[0, 0] == pytest.approx(2.00973, abs=1e-3)  # initial water column height
    assert elevation[-1, 0] < elevation[0, 0]  # the dam has broken and the column has drained

    pts = [(0.2, 0, 0), (0.2, 0, 0.5), (0.4, 0, 0), (0.4, 0, 0.5)]
    vel_points_path = mt.write_explicit_points(tmp_path / "pts.txt", pts)
    vel_csv = mt.run_velocity(PILOT_DATA, vel_points_path, tmp_path / "vel", DSPH_BIN_DIR)
    t_vel, vel = mt.parse_velocity_csv(vel_csv)
    np.testing.assert_allclose(t_vel, t_s)
    assert vel.shape == (len(t_s), 4, 3)
