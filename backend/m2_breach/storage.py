"""Storage curve above the final breach invert.

Used by `hydrograph.py` for level-pool routing: `volume(h)` and its inverse `head(v)`, where `h` is
measured in metres above the **final breach invert elevation** (not the dam base or an arbitrary
datum), so the routed head H = head(V) feeds directly into `weir.weir_discharge`.

Two sources, matching `Dam.volume_elevation.method` (`backend/shared/site_config.py`):

- `from_surveyed_curve`: piecewise-linear interpolation of a surveyed elevation-volume curve
  (bathymetry), shifted so h=0 is the breach invert.
- `from_area_volume_relation`: used when bathymetry is missing. Site config gives only the
  single fact usually available for an unsurveyed lake — its area-volume exponent `b` in the
  power-law relation `V = a * A^b` (Huggel et al. 2004-style lake-volume estimation) — plus the
  one calibration point M2 already has, (h_w, V_w): the water height and volume above the breach
  invert at the scenario's initial water level. This module is **not** a reproduction of any
  paper's formula; it is an SIH26-derived interpolation between those two facts, documented here:

  Assume the basin is self-similar as it drains, i.e. surface area A(h) ∝ h^n for some n > 0 (a
  cone or paraboloid-like shape near the bottom). Then dV/dh = A(h) ∝ h^n, so V(h) ∝ h^(n+1).
  Substituting V ∝ A^b ∝ h^(n*b) into V ∝ h^(n+1) gives n*b = n+1, i.e. n = 1/(b-1), so
  V(h) ∝ h^(1 + n) = h^(b/(b-1)). Calibrating the proportionality constant against the known
  point (h_w, V_w):

      V(h) = V_w * (h / h_w)^m,   m = b / (b - 1)

  This is a shape assumption, not a measurement — every `Hydrograph` built from it carries caveat
  `storage_from_area_volume_relation`. `b` must be > 1 (enforced in `site_config.py`) so `m > 1`,
  keeping the basin narrowing towards the invert as physically expected.

Both curves index volume as "volume released above the invert once the water surface has dropped
to h", i.e. `volume(h) = V_total_above_invert(h)`. `head(v)` is the inverse.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

STORAGE_FROM_AREA_VOLUME_RELATION_CAVEAT = "storage_from_area_volume_relation"


@dataclass(frozen=True)
class StorageCurve:
    """Monotone increasing volume(h) above the breach invert, h in [0, h_max]."""

    h_points: np.ndarray  # ascending, h_points[0] == 0
    v_points: np.ndarray  # ascending, v_points[0] == 0
    caveats: tuple[str, ...] = ()

    def volume(self, h: float) -> float:
        h = min(max(h, 0.0), self.h_points[-1])
        return float(np.interp(h, self.h_points, self.v_points))

    def head(self, v: float) -> float:
        v = min(max(v, 0.0), self.v_points[-1])
        return float(np.interp(v, self.v_points, self.h_points))


def from_area_volume_relation(V_w: float, h_w: float, b: float) -> StorageCurve:
    """Build a `StorageCurve` from the area-volume exponent `b` and the calibration point
    (h_w, V_w) — see module docstring for the derivation. `n_points` samples give `np.interp`
    enough resolution for the ODE integration in `hydrograph.py`.
    """
    if V_w <= 0 or h_w <= 0:
        raise ValueError(f"V_w and h_w must be > 0, got V_w={V_w!r}, h_w={h_w!r}")
    if b <= 1:
        raise ValueError(f"b must be > 1, got {b!r}")

    m = b / (b - 1)
    n_points = 200
    h_points = np.linspace(0.0, h_w, n_points)
    v_points = V_w * (h_points / h_w) ** m
    v_points[0] = 0.0
    return StorageCurve(h_points=h_points, v_points=v_points,
                         caveats=(STORAGE_FROM_AREA_VOLUME_RELATION_CAVEAT,))


def from_surveyed_curve(points: list[list[float]], invert_elevation_m: float) -> StorageCurve:
    """Build a `StorageCurve` from a surveyed elevation-volume curve, shifted so h=0 is
    `invert_elevation_m`. `points` are `[[elevation_m, volume_m3], ...]`, strictly increasing in
    both columns (enforced by `CurveValue` in site_config.py).
    """
    elevations = np.array([p[0] for p in points], dtype=float)
    volumes = np.array([p[1] for p in points], dtype=float)

    if not (elevations[0] <= invert_elevation_m <= elevations[-1]):
        raise ValueError(f"breach_invert_elevation_m ({invert_elevation_m}) is outside the "
                          f"surveyed curve's elevation range [{elevations[0]}, {elevations[-1]}]")

    v_invert = float(np.interp(invert_elevation_m, elevations, volumes))
    h_points = elevations - invert_elevation_m
    v_points = volumes - v_invert

    # keep only points at or above the invert, plus the invert itself as h=0
    mask = h_points >= 0
    h_points = np.concatenate(([0.0], h_points[mask]))
    v_points = np.concatenate(([0.0], v_points[mask]))
    # de-duplicate h=0 if the invert coincided with a surveyed point
    _, unique_idx = np.unique(h_points, return_index=True)
    unique_idx.sort()
    h_points, v_points = h_points[unique_idx], v_points[unique_idx]

    return StorageCurve(h_points=h_points, v_points=v_points)
