"""Froehlich (2016b) peak discharge — code F16.

Source: SECONDARY (Azmi p.6, Table 1, footnote a). Original: Froehlich DC
(2016b), "Predicting peak discharge from gradually breached embankment dam",
J Hydrol Eng 21(11), doi:10.1061/(asce)he.1943-5584.0001424. Original
page/equation number: NOT AVAILABLE (`docs/Equations.md` §1.1) — not yet
checked against the original paper, so `verified=False`.

Q_p = 0.0175 * k_m * k_h * (g * h_w * V_w * h_b^2 / W_ave)^0.5

Inputs (SI):
    V_w [m3]   water volume above breach invert, > 0
    h_w [m]    water height above breach invert, > 0
    h_b [m]    breach height, > 0
    W_ave [m]  average embankment width, > 0
    failure_mode: "O" (overtopping) or "P" (piping)

Output: Q_p [m3/s]

Valid range: NOT AVAILABLE (Azmi does not state one for this equation); no
calibration-range check is performed, only the physical positivity check.
"""

from __future__ import annotations

from .result import MethodResult, check_positive

_G = 9.81  # m/s^2 — NOT STATED by Azmi; SI units imply this value (docs/Equations.md §0)

_K_M = {"O": 1.85, "P": 1.0}
_H_B_THRESHOLD = 6.1  # m


def _k_h(h_b: float) -> float:
    if h_b <= _H_B_THRESHOLD:
        return 1.0
    return (h_b / _H_B_THRESHOLD) ** (1 / 8)


def peak_discharge_f16(V_w: float, h_w: float, h_b: float, W_ave: float, failure_mode: str) -> MethodResult:
    check_positive(V_w=V_w, h_w=h_w, h_b=h_b, W_ave=W_ave)
    if failure_mode not in _K_M:
        raise ValueError(f"failure_mode must be 'O' or 'P', got {failure_mode!r}")

    k_m = _K_M[failure_mode]
    k_h = _k_h(h_b)
    q_p = 0.0175 * k_m * k_h * (_G * h_w * V_w * h_b**2 / W_ave) ** 0.5

    return MethodResult(
        code="F16",
        value=q_p,
        unit="m3s",
        branch=f"k_m={k_m} ({failure_mode}); k_h={k_h:.6g} (h_b {'<=' if h_b <= _H_B_THRESHOLD else '>'} 6.1 m)",
        coefficients={"k_m": k_m, "k_h": k_h, "g": _G},
        source_tag="SECONDARY (Azmi p.6, Table 1, footnote a)",
        verified=False,
    )
