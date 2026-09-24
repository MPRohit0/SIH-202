"""Xu & Zhang (2009) peak discharge and breach width — code XZ9.

BLOCKED: both functions raise `BlockedEquationError` unconditionally. Do not
call them for a real result until h_r is sourced from the original paper.

Source: SECONDARY (Azmi p.6 Table 1 footnote b / p.8 Table 3 footnote c).
Original: Xu Y, Zhang LM (2009), "Breaching parameters for earth and
rockfill dams", J Geotech Geoenviron Eng 135(12):1957-1970,
doi:10.1061/(asce)gt.1943-5606.0000162. Original page/equation: NOT
AVAILABLE (`docs/Equations.md` §1.2, §2.3).

Why blocked: both equations divide by h_r ("reference height"), which Azmi's
reproduction never defines (`docs/Equations.md` marks it "NOT STATED —
UNCLEAR"). `docs/Equations.md` §7 explicitly says: "Block XZ9 (both Q_p and
B_ave) until h_r is sourced; don't hard-code a guess." Both formulas are kept
below, transcribed, so implementation is a one-line change once h_r has a
source — but nothing here approximates a value for it.

Q_p    = 0.175 * sqrt(g) * V_w^(5/6) * (h_d / h_r)^0.199
             * (V_w^(1/3) / h_w)^(-1.274) * exp(b3 + b4 + b5)
B_ave  = 0.787 * h_b * (h_d / h_r)^0.133 * (V_w^(1/3) / h_w)^0.652
             * exp(b3 + b4 + b5)

Inputs (SI): V_w [m3], h_w [m], h_b [m], h_d [m], dam_type ("HD"|"CD"|"FD"|"ZD"),
failure_mode ("O"|"P"), erodibility ("H"|"M"|"L").

Coefficients (`docs/Equations.md` §1.2, §2.3), kept here for when h_r is sourced:

Q_p b3 (dam type):  CD -0.503 | FD -0.591 | HD/ZD -0.649
Q_p b4 (failure):   O -0.705  | P -1.039
Q_p b5 (erodibility): H -0.007 | M -0.375 | L -1.362

B_ave b3 (dam type): CD -0.041 | FD 0.026 | HD/ZD -0.226
   (Table 1 vs Table 3 disagree on which code means core-wall vs
   concrete-faced; `docs/Equations.md` §2.3 resolves it by the printed
   words: "core walls" -> CD, "concrete-faced" -> FD, matching Table 1.)
B_ave b4 (failure): O 0.149 | P -0.389
B_ave b5 (erodibility): H 0.291 | M -0.14 | L -0.391

Output: Q_p [m3/s], B_ave [m].

Valid range: NOT AVAILABLE.
"""

from __future__ import annotations

from .result import BlockedEquationError, MethodResult

_REASON = "XZ9 needs h_r (Xu & Zhang reference height), which docs/Equations.md marks NOT STATED/UNCLEAR; blocked per §7 until sourced from the original paper."


def peak_discharge_xz9(V_w: float, h_w: float, h_b: float, h_d: float, dam_type: str,
                        failure_mode: str, erodibility: str) -> MethodResult:
    raise BlockedEquationError(_REASON)


def breach_width_xz9(V_w: float, h_w: float, h_b: float, h_d: float, dam_type: str,
                      failure_mode: str, erodibility: str) -> MethodResult:
    raise BlockedEquationError(_REASON)


def xz9_result(output: str) -> MethodResult:
    """Convenience: a blocked `MethodResult` without raising, for callers
    (dfm.py, ranges.py) that want to fold the block into a fused result
    rather than catching an exception at every call site.

    output: "peak_discharge_m3s" or "breach_width_m".
    """
    unit = "m3s" if output == "peak_discharge_m3s" else "m"
    return MethodResult.blocked("XZ9", unit, _REASON)
