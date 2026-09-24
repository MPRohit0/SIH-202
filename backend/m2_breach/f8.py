"""Froehlich (2008) breach width and failure time — code F8.

Source: SECONDARY (Azmi p.8 Table 3 footnote a / p.7 Table 2). Original:
Froehlich DC (2008), "Embankment dam breach parameters and their
uncertainties", J Hydraul Eng. Original page/equation: NOT AVAILABLE
(`docs/Equations.md` §2.2, §3.2).

B_ave = 0.27 * K_O * V_w^0.32 * h_b^0.04                          [m]
T_f   = 63.2 * sqrt(V_w / (g * h_b^2))                            [s, directly —
                                                                     see note below]

Inputs (SI): V_w [m3] > 0, h_b [m] > 0, failure_mode "O"|"P" (breach width only)

Outputs: B_ave [m], T_f [s].

Note on T_f units: `docs/Equations.md` §3.2 gives
`T_f = 63.2 * sqrt(V_w / (g*h_b^2)) / 3600  [h]  (63.2*sqrt(...) is in
seconds)` — i.e. the inner sqrt(...) term is already in seconds, and Azmi's
own /3600 only converts it to hours to match the other T_f equations before
fusing. Since this module's contract output is seconds (CLAUDE.md rule 5),
this function returns the inner seconds-valued term directly and skips the
/3600 -> hours round trip; `dfm.py` re-derives hours from this value where
the Table 5 fusion needs it.

Valid range: NOT AVAILABLE.
"""

from __future__ import annotations

from .result import MethodResult, check_positive

_G = 9.81  # m/s^2 — NOT STATED by Azmi; SI units imply this value

_K_O = {"O": 1.3, "P": 1.0}


def breach_width_f8(V_w: float, h_b: float, failure_mode: str) -> MethodResult:
    check_positive(V_w=V_w, h_b=h_b)
    if failure_mode not in _K_O:
        raise ValueError(f"failure_mode must be 'O' or 'P', got {failure_mode!r}")

    k_o = _K_O[failure_mode]
    b_ave = 0.27 * k_o * V_w**0.32 * h_b**0.04

    return MethodResult(
        code="F8",
        value=b_ave,
        unit="m",
        branch=f"K_O={k_o} ({failure_mode})",
        coefficients={"K_O": k_o},
        source_tag="SECONDARY (Azmi p.8, Table 3, footnote a)",
        verified=False,
    )


def failure_time_f8(V_w: float, h_b: float) -> MethodResult:
    check_positive(V_w=V_w, h_b=h_b)

    t_f_s = 63.2 * (V_w / (_G * h_b**2)) ** 0.5

    return MethodResult(
        code="F8",
        value=t_f_s,
        unit="s",
        branch="63.2*sqrt(V_w/(g*h_b^2)), already seconds per docs/Equations.md §3.2",
        coefficients={"g": _G},
        source_tag="SECONDARY (Azmi p.7, Table 2)",
        verified=False,
    )
