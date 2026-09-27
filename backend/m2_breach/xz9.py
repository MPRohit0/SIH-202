"""Xu & Zhang (2009) peak discharge and breach width — code XZ9.

The fixed reference height is part of the Xu & Zhang model, not a site input.
The breach-width equation and coefficients are reproduced from Xu & Zhang
(2009), *Breaching parameters for earth and rockfill dams*, J Geotech
Geoenviron Eng 135(12):1957-1970, doi:10.1061/(asce)gt.1943-5606.0000162.

Inputs use SI units: V_w [m3], h_w [m], h_b [m], h_d [m], dam_type
(HD|CD|FD|ZD), failure_mode (O|P), and erodibility (H|M|L).
"""

from __future__ import annotations

from math import exp

from .result import BlockedEquationError, MethodResult, check_positive

XZ9_REFERENCE_HEIGHT_M = 15.0

_B3_DAM_TYPE = {"CD": -0.041, "FD": 0.026, "HD": -0.226, "ZD": -0.226}
_B4_FAILURE_MODE = {"O": 0.149, "P": -0.389}
_B5_ERODIBILITY = {"H": 0.291, "M": -0.140, "L": -0.391}


def peak_discharge_xz9(V_w: float, h_w: float, h_b: float, h_d: float, dam_type: str,
                       failure_mode: str, erodibility: str) -> MethodResult:
    """Peak-discharge XZ9 is still unavailable: its gravity/source treatment
    is not specified by the project equation transcription."""
    raise BlockedEquationError("XZ9 peak-discharge equation remains unavailable; see docs/Equations.md §1.2")


def breach_width_xz9(V_w: float, h_w: float, h_b: float, h_d: float, dam_type: str,
                     failure_mode: str, erodibility: str) -> MethodResult:
    """Xu & Zhang (2009) average breach width, in metres.

    B_ave = 0.787*h_b*(h_d/h_r)^0.133*(V_w^(1/3)/h_w)^0.652*exp(B3),
    B3 = b3 + b4 + b5.
    """
    check_positive(V_w=V_w, h_w=h_w, h_b=h_b, h_d=h_d)
    try:
        b3 = _B3_DAM_TYPE[dam_type]
    except (KeyError, TypeError):
        raise ValueError(f"dam_type must be one of {tuple(_B3_DAM_TYPE)}, got {dam_type!r}") from None
    try:
        b4 = _B4_FAILURE_MODE[failure_mode]
    except (KeyError, TypeError):
        raise ValueError(f"failure_mode must be one of {tuple(_B4_FAILURE_MODE)}, got {failure_mode!r}") from None
    try:
        b5 = _B5_ERODIBILITY[erodibility]
    except (KeyError, TypeError):
        raise ValueError(f"erodibility must be one of {tuple(_B5_ERODIBILITY)}, got {erodibility!r}") from None

    b3_sum = b3 + b4 + b5
    value = (0.787 * h_b * (h_d / XZ9_REFERENCE_HEIGHT_M) ** 0.133
             * (V_w ** (1.0 / 3.0) / h_w) ** 0.652 * exp(b3_sum))
    return MethodResult(
        code="XZ9", value=value, unit="m",
        branch=f"B3={b3_sum} (b3={b3}, b4={b4}, b5={b5})",
        coefficients={"prefactor": 0.787, "h_d_over_h_r_exponent": 0.133,
                      "volume_depth_ratio_exponent": 0.652,
                      "b3_dam_type": b3, "b4_failure_mode": b4, "b5_erodibility": b5,
                      "h_r_m": XZ9_REFERENCE_HEIGHT_M},
        source_tag="PRIMARY (Xu & Zhang 2009)", verified=False,
    )


def xz9_result(output: str) -> MethodResult:
    """Return an unavailable XZ9 result for legacy callers without physical inputs.

    Width calculations must use :func:`breach_width_xz9` with the dam inputs.
    """
    if output == "breach_width_m":
        reason = "XZ9 breach width requires physical inputs; call breach_width_xz9"
        return MethodResult.blocked("XZ9", "m", reason)
    reason = "XZ9 peak-discharge equation remains unavailable; see docs/Equations.md §1.2"
    return MethodResult.blocked("XZ9", "m3s", reason)
