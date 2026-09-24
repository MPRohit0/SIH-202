"""Shared result type for every M2 base and fusion equation.

Every equation function in this package returns a `MethodResult`, whether it
succeeded or is blocked. A blocked result carries no `value` and no
`branch`/`coefficients` (there was nothing to compute); callers propagate the
block instead of guessing a number.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class BlockedEquationError(Exception):
    """Raised by an equation function that cannot be evaluated yet.

    Used when `docs/Equations.md` itself says not to compute a value (a
    missing coefficient like h_r, or an unmapped dam-type branch) rather than
    inventing one. See `docs/Equations.md` §7 ("M2 implementation checklist").
    """

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class MethodResult:
    """The output of one base or fusion equation.

    code: short method code as used in `docs/Equations.md` / `docs/paper_azmi.md`
        (F16, XZ9, Z20, F95, F8, MCLM, H14, DFM_updated, DFM_2024).
    value: the result in the contract's SI unit, or None if `status == "blocked"`.
    unit: "m3s" | "m" | "s".
    branch: human-readable record of which coefficient branch was used
        (e.g. "k_m=1.85 (O); k_h=1 (h_b<=6.1m)"), empty when blocked.
    coefficients: the numeric coefficients/exponents actually applied.
    source_tag: e.g. "SECONDARY (Azmi p.6, Table 1, footnote a)" or
        "PRIMARY (Azmi p.11, Table 5)".
    verified: True only once the equation has been checked against its
        original source, not Azmi's reproduction. Always False today
        (`docs/Equations.md` says every base equation is SECONDARY/unverified).
    in_valid_range: always None — `docs/Equations.md` states "Valid range:
        NOT AVAILABLE" for every equation, so no calibration-range check is
        performed. This is distinct from the physical sanity checks (inputs
        must be positive) each function still applies.
    status: "ok" or "blocked".
    reason: set when status == "blocked".
    """

    code: str
    value: float | None
    unit: str
    branch: str = ""
    coefficients: dict[str, float] = field(default_factory=dict)
    source_tag: str = ""
    verified: bool = False
    in_valid_range: bool | None = None
    status: str = "ok"
    reason: str | None = None

    @classmethod
    def blocked(cls, code: str, unit: str, reason: str) -> "MethodResult":
        return cls(code=code, value=None, unit=unit, status="blocked", reason=reason)

    @property
    def is_blocked(self) -> bool:
        return self.status == "blocked"

    def to_dict(self) -> dict:
        if self.is_blocked:
            return {"value": None, "status": "blocked", "reason": self.reason}
        return {"value": self.value, "in_valid_range": self.in_valid_range}


def check_positive(**kwargs: float) -> None:
    """Raise ValueError if any named input is not strictly positive.

    Every base equation in `docs/Equations.md` is undefined (division by
    zero, negative powers, log of zero) for non-positive V_w/h_w/h_b/h_d/W_ave.
    """
    for name, v in kwargs.items():
        if v is None or v <= 0:
            raise ValueError(f"{name} must be > 0, got {v!r}")


def warn_if_breach_exceeds_dam(h_b: float, h_d: float | None) -> list[str]:
    """Return a warning list if breach height exceeds dam height (h_b > h_d)."""
    if h_d is not None and h_b > h_d:
        return [f"breach_height ({h_b} m) exceeds dam_height ({h_d} m)"]
    return []
