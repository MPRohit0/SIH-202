"""Zhong et al. (2020) peak discharge — code Z20.

Source: SECONDARY (Azmi p.6, Table 1). Original: Zhong Q, Chen S, Fu Z,
Shan Y (2020), "New empirical model for breaching of earth-rock dams",
Nat Hazards Rev 21(2), doi:10.1061/(asce)nh.1527-6996.0000374. Original
page/equation: NOT AVAILABLE (`docs/Equations.md` §1.3).

Q_p = sqrt(g) * h_w^(-0.5) * V_w * F

HD: F = (V_w^0.333 / h_w)^(-1.58) * (h_w / h_b)^(-0.76) * h_d^0.1    * exp(-4.55)
CD: F = (V_w^0.333 / h_w)^(-1.51) * (h_w / h_b)^(-1.09) * h_d^(-0.12) * exp(-3.61)

Only HD and CD branches are given by Azmi; `docs/Equations.md` §1.3 states
FD/ZD are NOT STATED and §7 says to raise for any dam type other than HD/CD
until that mapping is sourced (Teesta III is FD).

Inputs (SI):
    V_w [m3], h_w [m], h_b [m], h_d [m], all > 0
    dam_type: "HD" or "CD" (else BlockedEquationError)

Output: Q_p [m3/s]

Valid range: NOT AVAILABLE.
"""

from __future__ import annotations

import math

from .result import BlockedEquationError, MethodResult, check_positive

_G = 9.81  # m/s^2 — NOT STATED by Azmi; SI units imply this value

_BRANCHES = {
    "HD": {"a": -1.58, "b": -0.76, "c": 0.1, "k": -4.55},
    "CD": {"a": -1.51, "b": -1.09, "c": -0.12, "k": -3.61},
}


def peak_discharge_z20(V_w: float, h_w: float, h_b: float, h_d: float, dam_type: str) -> MethodResult:
    if dam_type not in _BRANCHES:
        raise BlockedEquationError(
            f"Z20 has no branch for dam_type={dam_type!r}; only HD/CD are given by Azmi "
            f"(docs/Equations.md §1.3), and the FD/ZD mapping is NOT STATED — blocked per §7."
        )
    check_positive(V_w=V_w, h_w=h_w, h_b=h_b, h_d=h_d)

    c = _BRANCHES[dam_type]
    F = ((V_w ** 0.333 / h_w) ** c["a"]) * ((h_w / h_b) ** c["b"]) * (h_d ** c["c"]) * math.exp(c["k"])
    q_p = (_G ** 0.5) * (h_w ** -0.5) * V_w * F

    return MethodResult(
        code="Z20",
        value=q_p,
        unit="m3s",
        branch=f"dam_type={dam_type}",
        coefficients=dict(c),
        source_tag="SECONDARY (Azmi p.6, Table 1)",
        verified=False,
    )
