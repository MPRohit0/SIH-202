"""Updated DFM fusion and DFM 2024 — Azmi (2026) Table 5, and Azmi & Thomson
(2024) for the Q_p complement.

PRIMARY (Azmi p.11, Table 5; p.15 for DFM 2024): these fusion equations are
Azmi's own contribution, not a reproduction of someone else's formula, so
they carry no SECONDARY tag. Coefficients are the median of 100,000
bootstrap fits (`docs/Equations.md` §4, `docs/paper_azmi.md`).

Q_p   = 0.3048*F16 + 0.4804*XZ9 + 0.1674*Z20                      [m3/s]
B_ave = -0.8220*F95 + 1.0021*F8 + 1.1031*XZ9                      [m]
T_f   = -1.0648*F95 + 1.5875*F8 + 0.6189*MCLM                     [h, fused;
                                                                     converted
                                                                     to s here]

Q_p (DFM 2024) = 1.23*F16 - 0.84*H14 + 0.26*XZ9                   [m3/s]

`docs/Equations.md` §4 flags the B_ave coefficient b as UNCLEAR: 1.0020 in
the coefficient column of Table 5 vs 1.0021 in the equation column. This
module uses **1.0021**, the equation-column value (the difference is
0.01% of F8 and immaterial either way; recorded here per the plan).

Fusion is done component-by-component: every DFM function takes the already
-computed `MethodResult`s for its inputs rather than raw physical inputs, so
a blocked component (XZ9 today) propagates as a blocked DFM result instead
of silently being skipped or defaulted.

T_f unit handling: Table 5's T_f coefficients are calibrated with T_f in
hours (`docs/Equations.md` §4). F95/F8/MCLM in this package return T_f in
**seconds** (rule 5 boundary conversion), so `failure_time_dfm_updated`
converts each component back to hours before the fusion arithmetic, then
converts the fused result to seconds before returning — matching Azmi's
math exactly while keeping this module's public contract in seconds.

A fused Q_p/B_ave/T_f <= 0 is possible because of the negative coefficients
(`docs/Equations.md` §4, §6). Such a value is returned as-is with warning
`dfm_nonpositive` in its branch note — never clipped (SIH26 rule, not
Azmi's).
"""

from __future__ import annotations

from .result import MethodResult

_SECONDS_PER_HOUR = 3600.0

_QP_COEF = {"F16": 0.3048, "XZ9": 0.4804, "Z20": 0.1674}
_BAVE_COEF = {"F95": -0.8220, "F8": 1.0021, "XZ9": 1.1031}
_TF_COEF = {"F95": -1.0648, "F8": 1.5875, "MCLM": 0.6189}
_QP_2024_COEF = {"F16": 1.23, "H14": -0.84, "XZ9": 0.26}


def _fuse(code: str, unit: str, coef: dict[str, float], components: dict[str, MethodResult],
          source_tag: str) -> MethodResult:
    blocked = [c for c in components.values() if c.is_blocked]
    if blocked:
        reasons = "; ".join(f"{c.code}: {c.reason}" for c in blocked)
        return MethodResult.blocked(code, unit, f"blocked because a component is blocked — {reasons}")

    value = sum(coef[name] * components[name].value for name in coef)
    branch = ", ".join(f"{coef[name]}*{name}" for name in coef)
    if value <= 0:
        branch += " [dfm_nonpositive: fused value <= 0, not clipped]"

    return MethodResult(
        code=code,
        value=value,
        unit=unit,
        branch=branch,
        coefficients=dict(coef),
        source_tag=source_tag,
        verified=False,
    )


def peak_discharge_dfm_updated(f16: MethodResult, xz9: MethodResult, z20: MethodResult) -> MethodResult:
    return _fuse("DFM_updated", "m3s", _QP_COEF, {"F16": f16, "XZ9": xz9, "Z20": z20},
                 "PRIMARY (Azmi p.11, Table 5)")


def breach_width_dfm_updated(f95: MethodResult, f8: MethodResult, xz9: MethodResult) -> MethodResult:
    return _fuse("DFM_updated", "m", _BAVE_COEF, {"F95": f95, "F8": f8, "XZ9": xz9},
                 "PRIMARY (Azmi p.11, Table 5); B_ave coefficient b=1.0021 (equation column, "
                 "not 1.0020 coefficient column — docs/Equations.md §4 UNCLEAR)")


def failure_time_dfm_updated(f95: MethodResult, f8: MethodResult, mclm: MethodResult) -> MethodResult:
    blocked = [c for c in (f95, f8, mclm) if c.is_blocked]
    if blocked:
        reasons = "; ".join(f"{c.code}: {c.reason}" for c in blocked)
        return MethodResult.blocked("DFM_updated", "s", f"blocked because a component is blocked — {reasons}")

    f95_h = f95.value / _SECONDS_PER_HOUR
    f8_h = f8.value / _SECONDS_PER_HOUR
    mclm_h = mclm.value / _SECONDS_PER_HOUR
    t_f_hours = _TF_COEF["F95"] * f95_h + _TF_COEF["F8"] * f8_h + _TF_COEF["MCLM"] * mclm_h
    t_f_s = t_f_hours * _SECONDS_PER_HOUR

    branch = ", ".join(f"{_TF_COEF[name]}*{name}(h)" for name in _TF_COEF) + "; fused in hours, returned in seconds"
    if t_f_hours <= 0:
        branch += " [dfm_nonpositive: fused value <= 0, not clipped]"

    return MethodResult(
        code="DFM_updated",
        value=t_f_s,
        unit="s",
        branch=branch,
        coefficients=dict(_TF_COEF),
        source_tag="PRIMARY (Azmi p.11, Table 5)",
        verified=False,
    )


def peak_discharge_dfm_2024(f16: MethodResult, h14: MethodResult, xz9: MethodResult) -> MethodResult:
    return _fuse("DFM_2024", "m3s", _QP_2024_COEF, {"F16": f16, "H14": h14, "XZ9": xz9},
                 "PRIMARY for the DFM 2024 fusion form (Azmi p.15); coefficients from "
                 "Azmi & Thomson (2024), Nat Hazards 120:4423-4461")
