"""Dual-method ranges: the recommended method pair per output, combined into
a low/high range.

Recommended pairs (`docs/paper_azmi.md` §"Recommended method pair per
output", `docs/Equations.md` is silent on this — it is Azmi's own
recommendation):

    Q_p:   Updated DFM + DFM 2024
    B_ave: Updated DFM + XZ9
    T_f:   Updated DFM + F8

The paper says the pair gives "the most comprehensive and reliable range"
but does not say how to combine the two values into one. Per
`docs/paper_azmi.md`: "SIH26 interpretation: compute both and use them as
the low/high bounds of that output's scenario range" — i.e. low = min(pair),
high = max(pair). This module implements that interpretation, not something
stated by Azmi.

Because XZ9 is blocked (`xz9.py`), Q_p's pair (DFM_updated needs XZ9;
DFM_2024 needs XZ9) and B_ave's pair (DFM_updated needs XZ9; XZ9 itself) are
both blocked today. Only T_f's pair (DFM_updated needs F95/F8/MCLM, no XZ9;
F8 alone) is computable.
"""

from __future__ import annotations

from dataclasses import dataclass

from .result import MethodResult

PAIRS: dict[str, tuple[str, str]] = {
    "peak_discharge_m3s": ("DFM_updated", "DFM_2024"),
    "breach_width_m": ("DFM_updated", "XZ9"),
    "failure_time_s": ("DFM_updated", "F8"),
}


@dataclass(frozen=True)
class MethodRange:
    low: float | None
    high: float | None
    unit: str
    interval: str
    selected_pair: tuple[str, str]
    status: str  # "ok" | "blocked"
    reason: str | None = None

    def to_dict(self) -> dict:
        d = {
            "low": self.low,
            "high": self.high,
            "unit": self.unit,
            "interval": self.interval,
            "selected_pair": list(self.selected_pair),
        }
        if self.status == "blocked":
            d["status"] = "blocked"
            d["reason"] = self.reason
        return d


def method_range(output: str, primary: MethodResult, complement: MethodResult) -> MethodRange:
    """Combine the recommended pair for `output` into a low/high range.

    `primary` and `complement` must be the `MethodResult`s for
    `PAIRS[output]`, in that order, in the output's SI unit.
    """
    pair = PAIRS[output]
    unit = primary.unit

    if primary.is_blocked or complement.is_blocked:
        blocked = [r for r in (primary, complement) if r.is_blocked]
        reasons = "; ".join(f"{r.code}: {r.reason}" for r in blocked)
        return MethodRange(low=None, high=None, unit=unit, interval="method_range",
                            selected_pair=pair, status="blocked", reason=reasons)

    lo, hi = sorted((primary.value, complement.value))
    return MethodRange(low=lo, high=hi, unit=unit, interval="method_range",
                        selected_pair=pair, status="ok")
