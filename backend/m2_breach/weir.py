"""Trapezoidal broad-crested weir discharge.

Standard hydraulics, **not** from `docs/Equations.md` — that document's scope is the Azmi (2026)
breach-parameter equations (Q_p, B_ave, T_f), not flow routing. This is the textbook broad-crested
weir form for a trapezoidal breach (e.g. Fread's BREACH / DAMBRK; FEMA/USBR breach guidance),
split into a rectangular term (bottom width) and a triangular term (the two side slopes):

    Q = C_r * b * H^1.5 + C_s * z * H^2.5                              [m3/s]

Per `docs/decisions.md` (2026-09-24 session), **the coefficients C_r and C_s have no built-in
value in this module** — CLAUDE.md rule 3 forbids inventing coefficients, and no source document
in this repo gives one. They are read from `Dam.breach_hydrograph` (`backend/shared/site_config.py`)
as SourcedValues; a `Dam` without that block cannot use this method
(`backend/m2_breach/hydrograph.py` falls back to `triangular`).

Inputs (SI):
    b [m]      instantaneous bottom width of the trapezoidal breach, >= 0
    z [-]      side slope (horizontal:vertical), >= 0
    H [m]      head: water surface elevation minus breach invert elevation
    C_r [m^0.5/s]  rectangular (bottom-width) weir coefficient
    C_s [m^0.5/s]  triangular (side-slope) weir coefficient

Output: Q [m3/s]. Q = 0 for H <= 0 (no submergence below the invert).
"""

from __future__ import annotations


def weir_discharge(b: float, z: float, H: float, C_r: float, C_s: float) -> float:
    if b < 0:
        raise ValueError(f"b (bottom width) must be >= 0, got {b!r}")
    if z < 0:
        raise ValueError(f"z (side slope) must be >= 0, got {z!r}")
    if C_r <= 0 or C_s <= 0:
        raise ValueError(f"weir coefficients must be > 0, got C_r={C_r!r}, C_s={C_s!r}")
    if H <= 0:
        return 0.0
    return C_r * b * H**1.5 + C_s * z * H**2.5
