"""GPU memory / particle-count estimator for DualSPHysics (M4) near-field cases.

Calibrated from the pilot run's raw logs in `backend/m4_pilot/` (this module stays in
`backend/m4_sph/` since the real case generator imports it — see `docs/decisions.md` "M4 pilot
files moved into `backend/m4_sph/`"): `gencase_output.log` and `dualsphysics_output.log`
(CaseDambreakVal2D, dp=0.01 m, 21,001 particles, RTX 4060 Laptop GPU, 8188 MiB) plus the
concurrent `nvidia_smi.log` sampled during the solver run.

The pilot case is a small 2D validation case, not a real 3D near-field GLOF
domain. Per-particle GPU memory (bytes/particle) is read directly from
DualSPHysics's own "GPU Memory" report, so it should hold for any case using
the same particle arrays (DBC boundary, single precision, Verlet). The fixed
CUDA context overhead is likewise measured, not guessed. What is NOT
calibrated from this pilot — because it is a 2D case — is the ratio of
boundary particles to fluid particles for a real terrain-following 3D floor,
NOR the cell/particle ratio (`cells_per_particle`): a 2D case's cell-linked-list
needs a 2D grid of cells for the same particle spacing, while a 3D domain needs
a 3D grid, so `cells_per_particle` (and the `bytes_per_cell` contribution to the
total estimate) measured here likely **undercounts** a real 3D near-field case.
Both the boundary:fluid ratio and the cell/particle ratio are exposed as
parameters (`boundary_layers` / this module's calibration) instead of hardcoded
constants, and the estimate should be re-checked — ideally recalibrated from a
real 3D `nearfield.stl` pilot run (M4-1) — once one exists.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

PILOT_DIR = Path(__file__).parent.parent / "m4_pilot"


@dataclass
class Calibration:
    bytes_per_particle: float       # DualSPHysics "GPU Memory" / particle count
    bytes_per_cell: float           # DualSPHysics "GPU Memory (for cells)" / cell count
    cells_per_particle: float       # observed cell/particle ratio in the pilot case
    context_overhead_mib: float     # nvidia-smi peak-during-run minus baseline-idle,
                                     # minus the solver's own reported particle+cell memory


def parse_dualsphysics_log(path: Path) -> dict:
    """Pull particle/cell counts and the solver's own GPU memory accounting
    out of a DualSPHysics run log (values only appear once, at the summary
    printed at the end of the run)."""
    text = path.read_text()

    def grab_int(pattern: str) -> int:
        m = re.search(pattern, text)
        if not m:
            raise ValueError(f"pattern not found in {path}: {pattern}")
        return int(m.group(1).replace(",", ""))

    return {
        "max_particles": grab_int(r"Maximum number of particles\.+:\s*([\d,]+)"),
        "max_cells": grab_int(r"Maximum number of cells\.+:\s*([\d,]+)"),
        "gpu_memory_bytes": grab_int(r"GPU Memory\.+:\s*([\d,]+)"),
        "gpu_memory_cells_bytes": grab_int(r"GPU Memory \(for cells\)\.+:\s*([\d,]+)"),
    }


def parse_nvidia_smi_log(path: Path) -> dict:
    """Baseline (first sample) and peak `memory.used` from an `nvidia-smi
    --query-gpu=... --format=csv -l 1`-style CSV log taken while the solver ran."""
    lines = [l for l in path.read_text().splitlines() if l.strip()]
    header, rows = lines[0], lines[1:]
    used_mib = []
    for row in rows:
        parts = [p.strip() for p in row.split(",")]
        used_mib.append(int(parts[1].split()[0]))
    return {
        "baseline_mib": used_mib[0],
        "peak_mib": max(used_mib),
    }


def calibrate(pilot_dir: Path = PILOT_DIR) -> Calibration:
    dsph = parse_dualsphysics_log(pilot_dir / "dualsphysics_output.log")
    smi = parse_nvidia_smi_log(pilot_dir / "nvidia_smi.log")

    bytes_per_particle = dsph["gpu_memory_bytes"] / dsph["max_particles"]
    bytes_per_cell = dsph["gpu_memory_cells_bytes"] / dsph["max_cells"]
    cells_per_particle = dsph["max_cells"] / dsph["max_particles"]

    solver_reported_mib = (dsph["gpu_memory_bytes"] + dsph["gpu_memory_cells_bytes"]) / (1024 * 1024)
    context_overhead_mib = (smi["peak_mib"] - smi["baseline_mib"]) - solver_reported_mib
    context_overhead_mib = max(context_overhead_mib, 0.0)

    return Calibration(
        bytes_per_particle=bytes_per_particle,
        bytes_per_cell=bytes_per_cell,
        cells_per_particle=cells_per_particle,
        context_overhead_mib=context_overhead_mib,
    )


def estimate_particle_count(
    domain_x_m: float,
    domain_y_m: float,
    fluid_depth_m: float,
    dp_m: float,
    boundary_layers: int = 3,
) -> dict:
    """Rough particle count for a 3D near-field case: fluid particles fill
    the footprint to `fluid_depth_m`, boundary particles cover the footprint
    floor `boundary_layers` deep (DualSPHysics DBC typically uses 3-4 layers).
    Not a substitute for GenCase's real count from `nearfield.stl` — use once
    a real terrain mesh is available to validate the boundary_layers default.
    """
    footprint_m2 = domain_x_m * domain_y_m
    fluid_particles = footprint_m2 * fluid_depth_m / dp_m**3
    boundary_particles = boundary_layers * footprint_m2 / dp_m**2
    total = fluid_particles + boundary_particles
    return {
        "fluid_particles": fluid_particles,
        "boundary_particles": boundary_particles,
        "total_particles": total,
    }


def estimate_vram_mib(total_particles: float, calibration: Calibration) -> float:
    cells = total_particles * calibration.cells_per_particle
    particle_bytes = total_particles * calibration.bytes_per_particle
    cell_bytes = cells * calibration.bytes_per_cell
    return (particle_bytes + cell_bytes) / (1024 * 1024) + calibration.context_overhead_mib


def smallest_dp_within_budget(
    domain_x_m: float,
    domain_y_m: float,
    fluid_depth_m: float,
    calibration: Calibration,
    vram_budget_mib: float = 8188.0,
    margin: float = 0.15,
    boundary_layers: int = 3,
    dp_min_m: float = 0.001,
    dp_max_m: float = 2.0,
) -> dict:
    """Binary-search the smallest (finest) dp whose predicted VRAM use stays
    within `vram_budget_mib * (1 - margin)`. VRAM use is monotonically
    decreasing in dp, so this is well-posed."""
    usable_mib = vram_budget_mib * (1 - margin)

    def vram_at(dp: float) -> float:
        counts = estimate_particle_count(domain_x_m, domain_y_m, fluid_depth_m, dp, boundary_layers)
        return estimate_vram_mib(counts["total_particles"], calibration)

    if vram_at(dp_max_m) > usable_mib:
        return {
            "feasible": False,
            "reason": f"even dp_max_m={dp_max_m} exceeds the {usable_mib:.0f} MiB budget",
            "vram_at_dp_max_mib": vram_at(dp_max_m),
        }

    lo, hi = dp_min_m, dp_max_m  # lo may be infeasible (too fine), hi is feasible
    if vram_at(lo) <= usable_mib:
        best_dp = lo
    else:
        for _ in range(60):
            mid = (lo + hi) / 2
            if vram_at(mid) <= usable_mib:
                hi = mid
            else:
                lo = mid
        best_dp = hi

    counts = estimate_particle_count(domain_x_m, domain_y_m, fluid_depth_m, best_dp, boundary_layers)
    vram = estimate_vram_mib(counts["total_particles"], calibration)
    return {
        "feasible": True,
        "dp_m": best_dp,
        "total_particles": counts["total_particles"],
        "predicted_vram_mib": vram,
        "budget_mib": usable_mib,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--domain-x-m", type=float, required=True)
    p.add_argument("--domain-y-m", type=float, required=True)
    p.add_argument("--fluid-depth-m", type=float, required=True)
    p.add_argument("--dp-m", type=float, help="if given, just report count/VRAM for this dp")
    p.add_argument("--boundary-layers", type=int, default=3)
    p.add_argument("--vram-budget-mib", type=float, default=8188.0)
    p.add_argument("--margin", type=float, default=0.15)
    args = p.parse_args()

    cal = calibrate()
    print(f"calibration (from {PILOT_DIR}): {cal}")

    if args.dp_m is not None:
        counts = estimate_particle_count(
            args.domain_x_m, args.domain_y_m, args.fluid_depth_m, args.dp_m, args.boundary_layers
        )
        vram = estimate_vram_mib(counts["total_particles"], cal)
        print(f"dp={args.dp_m} m -> {counts['total_particles']:,.0f} particles, {vram:,.0f} MiB predicted")
    else:
        result = smallest_dp_within_budget(
            args.domain_x_m,
            args.domain_y_m,
            args.fluid_depth_m,
            cal,
            vram_budget_mib=args.vram_budget_mib,
            margin=args.margin,
            boundary_layers=args.boundary_layers,
        )
        print(result)


if __name__ == "__main__":
    main()
