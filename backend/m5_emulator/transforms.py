"""Per-output transforms applied before PCA and undone after decoding
(`docs/m5_specs.md` §3: "Depth transform", "Velocity transform", "Arrival in
dry cells").

Depth and velocity are non-negative and right-skewed (most cells shallow/slow,
a few deep/fast near the channel), so `log1p` is applied before PCA and
`expm1` after decoding — it keeps the shallow floodplain from being swamped
by the channel the way raw-metre PCA would, for the same reason Donnelly et
al. (2022) score depth with RMSLE rather than RMSE. Arrival time has no such
skew and is left untransformed; its only preprocessing is filling dry cells
(§3: "PCA can't take NaN") so the stack has no nodata before PCA.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from backend.shared.grid import FLOAT_NODATA


@dataclass(frozen=True)
class OutputTransform:
    """A named, invertible transform applied to one output map stack before
    PCA. `inverse` is applied to decoded PCA output, so it must accept
    whatever range the GP mean/band can produce (including values outside
    the training data's range) without raising."""

    name: str
    forward: Callable[[np.ndarray], np.ndarray]
    inverse: Callable[[np.ndarray], np.ndarray]

    def __call__(self, x: np.ndarray) -> np.ndarray:
        return self.forward(x)


def _log1p_forward(x: np.ndarray) -> np.ndarray:
    return np.log1p(np.maximum(x, 0.0))


def _log1p_inverse(z: np.ndarray) -> np.ndarray:
    """`expm1`, clipped to >= 0 (docs/m5_specs.md: "clip depth >= 0"; the
    same clip is physically correct for velocity)."""
    return np.maximum(np.expm1(z), 0.0)


def _identity(x: np.ndarray) -> np.ndarray:
    return x


LOG1P = OutputTransform(name="log1p", forward=_log1p_forward, inverse=_log1p_inverse)
IDENTITY = OutputTransform(name="identity", forward=_identity, inverse=_identity)

#: Default transform per output (docs/m5_specs.md §3). Depth and velocity
#: both use log1p for the same reason (fair weight to shallow/slow cells);
#: arrival is filled (see `fill_arrival`) but not otherwise transformed.
DEFAULT_TRANSFORMS: dict[str, OutputTransform] = {
    "max_depth": LOG1P,
    "max_velocity": LOG1P,
    "arrival_time": IDENTITY,
}

TRANSFORMS_BY_NAME: dict[str, OutputTransform] = {t.name: t for t in (LOG1P, IDENTITY)}


def fill_arrival(arrival_s: np.ndarray, t_end_s: float) -> np.ndarray:
    """Fill dry cells (nodata or NaN) with `t_end_s` ("didn't arrive within
    the run", docs/m5_specs.md §3), then clip to [0, t_end_s] so a noisy or
    extrapolated GP decode can't produce a negative or unbounded arrival.

    `t_end_s` must be > 0; it is the run's simulation end time (real runs:
    `run_meta.json.sim_duration_s`; the synthetic library: see
    `library.build_synthetic_library`).
    """
    if t_end_s <= 0:
        raise ValueError(f"t_end_s must be > 0, got {t_end_s!r}")
    dry = ~np.isfinite(arrival_s) | (arrival_s == FLOAT_NODATA)
    filled = np.where(dry, t_end_s, arrival_s)
    return np.clip(filled, 0.0, t_end_s)
