"""The two A1 baselines (`docs/m5_specs.md` §8): a GP that can't beat these
isn't worth the complexity of a GP.

1. **Linear-in-scores** — the same PCA basis a fold's `FloodEmulator` fits,
   with each component score fitted by ordinary least squares on the
   standardised inputs, instead of a GP. Isolates whether the GP adds
   anything over a linear fit in the same basis.
2. **Nearest-run blending** — an inverse-distance-weighted average of the 3
   nearest training runs' *physical* maps in standardised input space. The
   method a sceptical reviewer would propose first; never touches PCA.

Both predict without an uncertainty estimate (`interval: null` downstream);
`loocv.py` calls `FloodEmulator.maps_from_latent`/`maps_from_corridor_physical`
so the decode -> clip -> arrival-mask pipeline is identical to the GP's.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from backend.m5_emulator.emulator import OUTPUT_KEYS
from backend.m5_emulator.transforms import fill_arrival


@dataclass
class LinearScoresBaseline:
    """Ordinary least squares (with intercept), one fit per PCA component,
    per output. `coefficients[raw_name]` is (n_components, n_inputs + 1),
    last column the intercept."""

    coefficients: dict[str, np.ndarray]

    @classmethod
    def fit(cls, X_std_train: np.ndarray, scores_train: dict[str, np.ndarray]) -> "LinearScoresBaseline":
        """`X_std_train`: (N-1, n_inputs), standardised. `scores_train`:
        raw_name -> (N-1, n_components) PCA scores from the same fold's
        basis. Degenerate at N-1 <= n_inputs+1 only in the sense lstsq gives
        the minimum-norm solution; no special-casing needed."""
        design = np.column_stack([X_std_train, np.ones(X_std_train.shape[0])])
        coefficients: dict[str, np.ndarray] = {}
        for raw_name, scores in scores_train.items():
            coeffs, *_ = np.linalg.lstsq(design, scores, rcond=None)  # (n_inputs+1, n_components)
            coefficients[raw_name] = coeffs.T  # (n_components, n_inputs+1)
        return cls(coefficients=coefficients)

    def predict_latent(self, x_std_query: np.ndarray) -> dict[str, np.ndarray]:
        """One query row (n_inputs,), standardised -> raw_name -> predicted
        PCA scores (n_components,)."""
        x_row = np.concatenate([np.asarray(x_std_query, dtype=float), [1.0]])
        return {raw_name: coeffs @ x_row for raw_name, coeffs in self.coefficients.items()}


@dataclass
class NearestRunBaseline:
    """Inverse-distance-weighted (power 2) average of the `k` nearest
    training runs' physical corridor maps, in standardised input space.
    Arrival is filled (`fill_arrival`) before blending — averaging a mix of
    real arrivals and `FLOAT_NODATA` would be meaningless — and the result is
    masked to nodata downstream by `FloodEmulator.maps_from_corridor_physical`,
    same as every other method."""

    X_std_train: np.ndarray                    # (N-1, n_inputs)
    corridor_physical: dict[str, np.ndarray]    # raw_name -> (N-1, n_corridor_cells), arrival pre-filled
    k: int = 3

    @classmethod
    def fit(
        cls, X_std_train: np.ndarray, corridor_raw: dict[str, np.ndarray], t_end_s: float, k: int = 3,
    ) -> "NearestRunBaseline":
        """`corridor_raw`: raw_name -> (N-1, n_corridor_cells) untransformed
        physical values, sliced to the fold's corridor mask (arrival not yet
        filled)."""
        corridor_physical = dict(corridor_raw)
        corridor_physical["arrival_time"] = fill_arrival(corridor_raw["arrival_time"], t_end_s)
        return cls(X_std_train=np.asarray(X_std_train, dtype=float), corridor_physical=corridor_physical, k=k)

    def predict_corridor(self, x_std_query: np.ndarray) -> dict[str, np.ndarray]:
        """One query row, standardised -> raw_name -> IDW-blended physical
        corridor values (n_corridor_cells,). If the query coincides exactly
        with a training point (distance 0), that run's map is returned
        as-is."""
        x_std_query = np.asarray(x_std_query, dtype=float)
        dist = np.linalg.norm(self.X_std_train - x_std_query, axis=1)
        n_neighbours = min(self.k, len(dist))
        nearest = np.argsort(dist)[:n_neighbours]

        exact = np.flatnonzero(dist[nearest] == 0.0)
        if exact.size > 0:
            weights = np.zeros(n_neighbours)
            weights[exact[0]] = 1.0
        else:
            weights = 1.0 / (dist[nearest] ** 2)
            weights /= weights.sum()

        out: dict[str, np.ndarray] = {}
        for raw_name in OUTPUT_KEYS:
            stack = self.corridor_physical[raw_name][nearest]  # (n_neighbours, n_corridor_cells)
            out[raw_name] = (weights[:, None] * stack).sum(axis=0)
        return out
