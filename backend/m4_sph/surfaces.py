"""Free-surface meshes for the 3D view (contract §4.4 `surfaces/t<seconds>.glb`, SPH only).

Runs DualSPHysics's `IsoSurface_linux64 -saveiso` (verified against real particle data,
`docs/decisions.md` today's session: it writes one legacy-VTK binary polydata mesh per PART,
`<prefix>_NNNN.vtk`, all triangles) over a run's raw particle data, then keeps only the meshes
nearest each multiple of `settings.surface_interval_s` -- converted to `.glb` with
`vtk_polydata`/`gltf_writer` -- so the 3D view gets a manageable number of snapshots instead of
one per PART output (contract's `max_payload_mb`, Scene3D §5.9).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import numpy as np

from .gltf_writer import write_glb
from .vtk_polydata import read_polydata


class IsoSurfaceError(RuntimeError):
    """Raised when the `IsoSurface_linux64` subprocess exits non-zero."""


def run_isosurface(dirdata: str | Path, out_prefix: str | Path, binaries_dir: str | Path | None = None) -> None:
    """Run `IsoSurface -saveiso` over every PART in `dirdata`, writing `<out_prefix>_NNNN.vtk`
    (fluid particles only, matching every MeasureTool invocation in this module)."""
    bin_dir = binaries_dir or os.environ.get("DSPH_BIN_DIR")
    if not bin_dir:
        raise IsoSurfaceError("no IsoSurface binary directory: pass binaries_dir or set DSPH_BIN_DIR")
    binary = Path(bin_dir) / "IsoSurface_linux64"
    cmd = [str(binary), "-dirdata", str(dirdata), "-onlytype:-all,+fluid", "-saveiso", str(out_prefix)]
    env = {**os.environ, "LD_LIBRARY_PATH": str(bin_dir)}
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=3600)
    if result.returncode != 0:
        raise IsoSurfaceError(f"{cmd[0]} exited {result.returncode}:\n{result.stdout}\n{result.stderr}")


def select_snapshot_indices(times_s: list[float], interval_s: float) -> list[int]:
    """The index of the PART nearest each multiple of `interval_s` within `[times_s[0],
    times_s[-1]]`, deduplicated and sorted -- `times_s` is solver time (seconds since the case's
    own `t_start_s`), one entry per `<out_prefix>_NNNN.vtk` file, in file order."""
    if not times_s:
        return []
    times = np.asarray(times_s, dtype=float)
    last = times[-1]
    n_steps = int(last // interval_s) + 1
    targets = np.arange(n_steps) * interval_s
    indices = sorted({int(np.argmin(np.abs(times - t))) for t in targets})
    return indices


def convert_surfaces(
    vtk_prefix: str | Path, times_s: list[float], interval_s: float, t_start_s: float, out_dir: str | Path,
) -> list[Path]:
    """Convert the snapshots `select_snapshot_indices` picks from `<vtk_prefix>_NNNN.vtk` to
    `<out_dir>/t<seconds>.glb`, `seconds` = site time (`t_start_s` + solver time, rule 6),
    rounded to the nearest second per the contract's path pattern."""
    out_dir = Path(out_dir)
    written: list[Path] = []
    seen_seconds: set[int] = set()
    for i in select_snapshot_indices(times_s, interval_s):
        seconds = round(times_s[i] + t_start_s)
        if seconds in seen_seconds:
            continue  # two snapshots rounded to the same second (interval_s finer than the PART
            # cadence) -- keep the first rather than silently overwrite it with the second
        seen_seconds.add(seconds)
        points, triangles = read_polydata(Path(f"{vtk_prefix}_{i:04d}.vtk"))
        written.append(write_glb(out_dir / f"t{seconds}.glb", points, triangles))
    return written
