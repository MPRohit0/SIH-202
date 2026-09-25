"""Emulator input scaling (`docs/m5_specs.md` §1: "standardised to zero mean
and unit variance"; §1: "V_w spans orders of magnitude, so log space keeps
the design and length-scales sensible").

Input names follow the contract's fixed list (`docs/handoff_contract.md`
§3.3): only `water_volume_m3`, `initial_water_level_m`, `breach_width_m`,
`failure_time_s`, `manning_multiplier` are allowed. This module only
implements the three the default emulator uses (§1's default input set);
`initial_water_level_m` and `manning_multiplier` are future work.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

Scaling = Literal["log10", "linear"]


@dataclass(frozen=True)
class InputSpec:
    """One emulator input: its contract name, how it's pre-scaled before
    standardisation, and its training-design bounds in *raw* units (used to
    flag extrapolation)."""

    name: str
    scaling: Scaling
    low: float
    high: float

    def __post_init__(self) -> None:
        if self.scaling == "log10" and self.low <= 0:
            raise ValueError(f"{self.name}: log10 scaling requires low > 0, got {self.low!r}")
        if self.high <= self.low:
            raise ValueError(f"{self.name}: high ({self.high!r}) must be > low ({self.low!r})")

    def to_dict(self) -> dict:
        return {"name": self.name, "scaling": self.scaling, "low": self.low, "high": self.high}

    @classmethod
    def from_dict(cls, d: dict) -> "InputSpec":
        return cls(name=d["name"], scaling=d["scaling"], low=d["low"], high=d["high"])


#: Default input set (docs/m5_specs.md §1): log10(V_w), B_ave, T_f.
DEFAULT_SCALING: dict[str, Scaling] = {
    "water_volume_m3": "log10",
    "breach_width_m": "linear",
    "failure_time_s": "linear",
}


def make_input_specs(ranges: dict[str, tuple[float, float]]) -> list[InputSpec]:
    """Build `InputSpec`s from `{name: (low, high)}`, in the fixed order
    `DEFAULT_SCALING` lists them, using each name's default scaling."""
    return [
        InputSpec(name=name, scaling=DEFAULT_SCALING[name], low=lo, high=hi)
        for name, (lo, hi) in ranges.items()
    ]


def _prescale(x: np.ndarray, spec: InputSpec) -> np.ndarray:
    return np.log10(x) if spec.scaling == "log10" else x


class InputScaler:
    """Pre-scales (log10 for volume) then standardises (zero mean, unit
    variance) a set of raw inputs, fit on the training design.

    `X_raw` is N x len(specs), columns in `specs` order.
    """

    def __init__(self, specs: list[InputSpec], mean: np.ndarray, std: np.ndarray):
        if len(specs) != len(mean) or len(specs) != len(std):
            raise ValueError("specs, mean and std must have the same length")
        self.specs = specs
        self.mean = np.asarray(mean, dtype=float)
        self.std = np.asarray(std, dtype=float)

    @classmethod
    def fit(cls, X_raw: np.ndarray, specs: list[InputSpec]) -> "InputScaler":
        X_raw = np.atleast_2d(X_raw)
        if X_raw.shape[1] != len(specs):
            raise ValueError(f"X_raw has {X_raw.shape[1]} columns, expected {len(specs)}")
        pre = np.column_stack([_prescale(X_raw[:, i], s) for i, s in enumerate(specs)])
        mean = pre.mean(axis=0)
        std = pre.std(axis=0)
        if np.any(std <= 0):
            zero = [s.name for s, sd in zip(specs, std) if sd <= 0]
            raise ValueError(f"zero-variance training input(s), cannot standardise: {zero}")
        return cls(specs, mean, std)

    def transform(self, X_raw: np.ndarray) -> np.ndarray:
        """Raw inputs -> standardised inputs, shape preserved (1D in -> 1D
        out, 2D in -> 2D out)."""
        X_raw = np.asarray(X_raw, dtype=float)
        scalar_row = X_raw.ndim == 1
        X2 = np.atleast_2d(X_raw)
        pre = np.column_stack([_prescale(X2[:, i], s) for i, s in enumerate(self.specs)])
        out = (pre - self.mean) / self.std
        return out[0] if scalar_row else out

    def inside_training_box(self, X_raw: np.ndarray) -> np.ndarray:
        """Per-row, per-input bool: True where the raw input lies within
        [spec.low, spec.high] (the training design's box, docs/m5_specs.md
        §6 check C: "any input outside the training box" = extrapolation).
        Shape matches `X_raw`."""
        X_raw = np.asarray(X_raw, dtype=float)
        scalar_row = X_raw.ndim == 1
        X2 = np.atleast_2d(X_raw)
        inside = np.column_stack([
            (X2[:, i] >= s.low) & (X2[:, i] <= s.high) for i, s in enumerate(self.specs)
        ])
        return inside[0] if scalar_row else inside

    def to_dict(self) -> dict:
        return {
            "specs": [s.to_dict() for s in self.specs],
            "mean": self.mean.tolist(),
            "std": self.std.tolist(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "InputScaler":
        specs = [InputSpec.from_dict(s) for s in d["specs"]]
        return cls(specs, np.asarray(d["mean"], dtype=float), np.asarray(d["std"], dtype=float))
