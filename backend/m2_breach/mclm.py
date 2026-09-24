"""MacDonald & Langridge-Monopolis (1984) failure time — code MCLM.

Source: SECONDARY (Azmi p.7, Table 2). Original: MacDonald TC,
Langridge-Monopolis J (1984) — not in Azmi's reference list, so the full
citation is NOT AVAILABLE (`docs/Equations.md` §3.3, §6.7).

T_f = 0.0179 * (0.0261 * (V_w * h_w)^0.769)^0.364                 [h, per
                                                                     Azmi;
                                                                     converted
                                                                     to s here]

Azmi gives this single form without defining the inner bracketed term
(`docs/Equations.md` §3.3, "NOT STATED"); it is applied exactly as printed.

Inputs (SI): V_w [m3] > 0, h_w [m] > 0

Output: T_f [s] — computed in hours as printed, converted to seconds at this
function's boundary (CLAUDE.md rule 5).

Valid range: NOT AVAILABLE.
"""

from __future__ import annotations

from .result import MethodResult, check_positive

_SECONDS_PER_HOUR = 3600.0


def failure_time_mclm(V_w: float, h_w: float) -> MethodResult:
    check_positive(V_w=V_w, h_w=h_w)

    t_f_hours = 0.0179 * (0.0261 * (V_w * h_w) ** 0.769) ** 0.364
    t_f_s = t_f_hours * _SECONDS_PER_HOUR

    return MethodResult(
        code="MCLM",
        value=t_f_s,
        unit="s",
        branch="T_f computed in hours per Azmi p.7 Table 2, converted to seconds",
        source_tag="SECONDARY (Azmi p.7, Table 2)",
        verified=False,
    )
