"""Froehlich (1995) breach width and failure time — code F95.

Source: SECONDARY (Azmi p.8 Table 3 footnote b / p.7 Table 2). Original:
Froehlich DC (1995), "Embankment dam breach parameters revisited", Water
Resources Engineering (ASCE). Original page/equation: NOT AVAILABLE
(`docs/Equations.md` §2.1, §3.1).

B_ave = 0.1803 * K_n * V_w^0.32 * h_b^0.19                       [m]
T_f   = 0.00254 * V_w^0.53 * h_b^(-0.9)                          [h, per Azmi;
                                                                    converted
                                                                    to s here]

Inputs (SI): V_w [m3] > 0, h_b [m] > 0, failure_mode "O"|"P" (breach width only)

Outputs: B_ave [m], T_f [s] — T_f is computed in hours exactly as printed by
Azmi, then converted to seconds at this function's boundary (CLAUDE.md rule
5: "Failure time is stored in seconds even if an equation returns hours —
convert at the function boundary").

Valid range: NOT AVAILABLE.
"""

from __future__ import annotations

from .result import MethodResult, check_positive

_K_N = {"O": 1.4, "P": 1.0}
_SECONDS_PER_HOUR = 3600.0


def breach_width_f95(V_w: float, h_b: float, failure_mode: str) -> MethodResult:
    check_positive(V_w=V_w, h_b=h_b)
    if failure_mode not in _K_N:
        raise ValueError(f"failure_mode must be 'O' or 'P', got {failure_mode!r}")

    k_n = _K_N[failure_mode]
    b_ave = 0.1803 * k_n * V_w**0.32 * h_b**0.19

    return MethodResult(
        code="F95",
        value=b_ave,
        unit="m",
        branch=f"K_n={k_n} ({failure_mode})",
        coefficients={"K_n": k_n},
        source_tag="SECONDARY (Azmi p.8, Table 3, footnote b)",
        verified=False,
    )


def failure_time_f95(V_w: float, h_b: float) -> MethodResult:
    check_positive(V_w=V_w, h_b=h_b)

    t_f_hours = 0.00254 * V_w**0.53 * h_b ** (-0.9)
    t_f_s = t_f_hours * _SECONDS_PER_HOUR

    return MethodResult(
        code="F95",
        value=t_f_s,
        unit="s",
        branch="T_f computed in hours per Azmi p.7 Table 2, converted to seconds",
        source_tag="SECONDARY (Azmi p.7, Table 2)",
        verified=False,
    )
