"""Wraps DualSPHysics's `MeasureTool_linux64` (contract §4.4 `summary_nearfield/*.tif`): writes
its points-definition files, runs it against a run's raw particle data, and parses the CSVs it
produces. Every detail here (file syntax, CSV layout, flag names) was checked against the real
binary on real pilot particle data before being written (`docs/decisions.md`, today's session) --
none of it is guessed from the `-h` text alone.

Two point layouts, verified separately:

- **Elevation columns** (`write_column_points`, mode `-elevation`): a `POINTSENDLIST` block per
  near-field cell, each listing a vertical range of candidate z's at that cell's (x, y).
  MeasureTool collapses each block into ONE free-surface-elevation time series -- explicit
  `(x, y, z)` triples do *not* collapse this way, only `ptels`/`POINTSENDLIST`-style ranges do.
  This is how `postprocess.py` gets depth and arrival time per cell.
- **Explicit points** (`write_explicit_points`, mode `-vars:vel`): one `(x, y, z)` triple per
  sample, each producing its own `Vel_N` time series -- used for the depth-averaging velocity
  samples (`docs/decisions.md` "SPH velocity: depth-average, not a fixed-height point").

A dry column (no fluid anywhere in its z-range) reports its elevation as `z0` -- the *bottom* of
the candidate range given to `write_column_points`, not DualSPHysics's usual `-kcdummy` fallback
(verified against the real binary: `-kcdummy`/`-kcusedummy` have no effect in `-elevation` mode,
unlike `-vars` interpolation). `postprocess.py` always sets `z0` to the cell's own bed elevation,
so a dry column's reported elevation equals its bed and depth (`elevation - bed`) comes out to
exactly `0.0` -- the project's own dry-cell convention (contract §1.5) -- with no extra dummy
handling needed.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import numpy as np


class MeasureToolError(RuntimeError):
    """Raised when the `MeasureTool_linux64` subprocess exits non-zero."""


def _binary_path(binaries_dir: str | Path | None) -> Path:
    bin_dir = binaries_dir or os.environ.get("DSPH_BIN_DIR")
    if not bin_dir:
        raise MeasureToolError(
            "no MeasureTool binary directory: pass binaries_dir or set DSPH_BIN_DIR"
        )
    return Path(bin_dir) / "MeasureTool_linux64"


def write_column_points(path: str | Path, columns: list[tuple[float, float, float, float, float]]) -> Path:
    """Write a `POINTSENDLIST`-per-column points file for `-elevation` mode.

    `columns` is `(x_m, y_m, z0_m, dz_m, z1_m)` per near-field cell (SPH frame); MeasureTool
    collapses each block's z-range into one elevation output, in the order the blocks are given.
    """
    lines = []
    for x, y, z0, dz, z1 in columns:
        x, y, z0, dz, z1 = float(x), float(y), float(z0), float(dz), float(z1)  # unwrap numpy
        # scalars: NumPy >= 2.0's repr() wraps them ("np.float64(...)"), which isn't valid here
        lines.append("POINTSENDLIST")
        lines.append(f"{x!r} {y!r} {z0!r}")
        lines.append(f"0 0 {dz!r}")
        lines.append(f"{x!r} {y!r} {z1!r}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="ascii")
    return Path(path)


def write_explicit_points(path: str | Path, points: list[tuple[float, float, float]]) -> Path:
    """Write a plain `POINTS` file: one line per `(x, y, z)` sample (SPH frame), each becoming
    its own `Vel_N` time series in `-vars:vel` mode (no column-collapsing, unlike elevation)."""
    lines = ["POINTS"] + [f"{float(x)!r} {float(y)!r} {float(z)!r}" for x, y, z in points]
    Path(path).write_text("\n".join(lines) + "\n", encoding="ascii")
    return Path(path)


def run_elevation(
    dirdata: str | Path, points_path: str | Path, out_prefix: str | Path, binaries_dir: str | Path | None = None,
) -> Path:
    """Run `MeasureTool -elevation` over `points_path`'s columns; returns the `..._Elevation.csv`
    it writes. Only fluid particles are sampled (`-onlytype:-all,+fluid`, matching every other
    MeasureTool invocation in this project)."""
    binary = _binary_path(binaries_dir)
    cmd = [
        str(binary), "-dirdata", str(dirdata), "-points", str(points_path),
        "-onlytype:-all,+fluid", "-elevation", "-savecsv", str(out_prefix),
    ]
    _run(cmd, binaries_dir)
    return Path(f"{out_prefix}_Elevation.csv")


def run_velocity(
    dirdata: str | Path, points_path: str | Path, out_prefix: str | Path, binaries_dir: str | Path | None = None,
) -> Path:
    """Run `MeasureTool -vars:vel` over `points_path`'s explicit points; returns `..._Vel.csv`."""
    binary = _binary_path(binaries_dir)
    cmd = [
        str(binary), "-dirdata", str(dirdata), "-points", str(points_path),
        "-onlytype:-all,+fluid", "-vars:-all,vel", "-savecsv", str(out_prefix),
    ]
    _run(cmd, binaries_dir)
    return Path(f"{out_prefix}_Vel.csv")


def _run(cmd: list[str], binaries_dir: str | Path | None) -> None:
    bin_dir = binaries_dir or os.environ.get("DSPH_BIN_DIR")
    env = {**os.environ, "LD_LIBRARY_PATH": str(bin_dir)}
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=3600)
    if result.returncode != 0:
        raise MeasureToolError(f"{cmd[0]} exited {result.returncode}:\n{result.stdout}\n{result.stderr}")


def parse_elevation_csv(path: str | Path, requested_xy: list[tuple[float, float]],
                        *, atol: float = 1e-3) -> tuple[np.ndarray, np.ndarray]:
    """`(t_s, elevation_m)`: `t_s` is `(T,)`, `elevation_m` is `(T, n_columns)`, reordered to match
    `requested_xy` -- the `(x, y)` of each column exactly as passed to `write_column_points`, in
    request order.

    Real format (verified against MeasureTool 5.4's own output, not just its docs):
    3 header rows (` ;PosX [m]:;...`, `PosY`, `PosZ`), then `Part;Time [s];Elevation_0 [m];...`.
    **MeasureTool's `-elevation` output re-sorts `POINTSENDLIST` columns by position (x ascending,
    then y ascending within each x) -- it does not preserve the request order `write_column_points`
    wrote them in** (verified against the real binary on real pilot particle data: a Teesta MVP run
    fed 91 x=5 columns first, y descending from 595, and got them back grouped by x with y
    ascending from 5). Every caller must reorder by `requested_xy`, using the PosX/PosY header rows
    to recover where each requested column landed; skipping this silently pairs each near-field
    cell with a *different* cell's elevation series (the cause of an unphysical ~259 m SPH depth
    field from an 11.8 m inlet on the real Teesta run, `docs/progress.md` 2026-09-27).
    """
    rows = Path(path).read_text(encoding="ascii").splitlines()
    header_x = [float(v) for v in rows[0].split(";")[2:]]
    header_y = [float(v) for v in rows[1].split(";")[2:]]
    n_cols = len(header_x)
    if len(header_y) != n_cols:
        raise ValueError(f"{path}: PosX header has {n_cols} columns but PosY header has {len(header_y)}")
    data = np.loadtxt(rows[4:], delimiter=";")
    data = data.reshape(-1, n_cols + 2)  # a single data row loses its leading dimension
    t_s, elevation = data[:, 1], data[:, 2:2 + n_cols]
    if len(requested_xy) != n_cols:
        raise ValueError(f"{path}: {n_cols} columns in the CSV but {len(requested_xy)} requested")
    header_xy = np.column_stack([header_x, header_y])
    order = np.empty(n_cols, dtype=int)
    claimed = np.zeros(n_cols, dtype=bool)
    for i, (x, y) in enumerate(requested_xy):
        distances = np.hypot(header_xy[:, 0] - x, header_xy[:, 1] - y)
        distances[claimed] = np.inf
        j = int(np.argmin(distances))
        if distances[j] > atol:
            raise ValueError(f"{path}: no unclaimed output column within {atol} m of requested "
                              f"point ({x}, {y}) (closest was {distances[j]} m away)")
        order[i] = j
        claimed[j] = True
    return t_s, elevation[:, order]


def parse_velocity_csv(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """`(t_s, vel_ms)`: `t_s` is `(T,)`, `vel_ms` is `(T, n_points, 3)` (x, y, z components),
    point order matching `write_explicit_points`. Header is `Part;Time [s];Vel_0.x [m/s];
    Vel_0.y [m/s];Vel_0.z [m/s];Vel_1.x [m/s];...` (2 header rows, not elevation's 3)."""
    rows = Path(path).read_text(encoding="ascii").splitlines()
    header = rows[1].split(";")
    n_points = (len(header) - 2) // 3
    data = np.loadtxt(rows[2:], delimiter=";")
    data = data.reshape(-1, n_points * 3 + 2)
    return data[:, 1], data[:, 2:].reshape(-1, n_points, 3)
