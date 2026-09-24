"""Hooshyaripor et al. (2014) peak discharge — code H14.

Used only inside DFM 2024 (`dfm.py`), never reported directly.

Source: SECONDARY (Azmi p.6, Table 1). Original: Hooshyaripor et al.
(2014) — not in Azmi's reference list, so the full citation is NOT
AVAILABLE (`docs/Equations.md` §5, §6.7).

Q_p = 0.0212 * V_w^0.5429 * h_w^0.8713                             [m3/s]

Inputs (SI): V_w [m3] > 0, h_w [m] > 0

Output: Q_p [m3/s]

Valid range: NOT AVAILABLE.
"""

from __future__ import annotations

from .result import MethodResult, check_positive


def peak_discharge_h14(V_w: float, h_w: float) -> MethodResult:
    check_positive(V_w=V_w, h_w=h_w)

    q_p = 0.0212 * V_w**0.5429 * h_w**0.8713

    return MethodResult(
        code="H14",
        value=q_p,
        unit="m3s",
        source_tag="SECONDARY (Azmi p.6, Table 1)",
        verified=False,
    )
