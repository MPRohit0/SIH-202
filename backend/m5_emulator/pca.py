"""PCA on a training-run map stack (`docs/m5_specs.md` §3, Donnelly et al.
2022 §"Method: PCA + independent GPs").

A "map stack" is N runs x n_cells, already transformed (`transforms.py`) and
restricted to the corridor mask below. PCA is computed by a centred thin SVD
(exact, not randomised — Donnelly use randomised SVD for 876,204 cells; our
corridor masks and N are small enough that an exact SVD is cheap and there is
no reason to trade accuracy for speed we don't need).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage


def corridor_mask(depth_stack: np.ndarray, grid_shape: tuple[int, int],
                   wet_m: float = 0.03, buffer_cells: int = 3) -> np.ndarray:
    """Boolean (height, width) mask: cells wet (depth > `wet_m`) in *any*
    training run, dilated by `buffer_cells` (docs/m5_specs.md §3: "union of
    cells wet ... in any training run, plus a 3-cell buffer").

    `depth_stack` is N x n_cells (flattened row-major, i.e. `.reshape(-1)` of
    a (height, width) array) of untransformed depth in metres.
    """
    wet_any = (depth_stack > wet_m).any(axis=0).reshape(grid_shape)
    if buffer_cells <= 0:
        return wet_any
    structure = ndimage.generate_binary_structure(2, 1)
    return ndimage.binary_dilation(wet_any, structure=structure, iterations=buffer_cells)


@dataclass(frozen=True)
class PCABasis:
    """A fitted PCA basis on the corridor cells of one output's transformed
    map stack. `components` are stored float32 (docs/m5_specs.md §3:
    "Storage: PCA loadings as float32").
    """

    mean: np.ndarray               # (n_corridor_cells,) float64 — kept full precision for accurate decoding
    components: np.ndarray         # (n_components, n_corridor_cells) float32, rows unit-norm (right singular vectors)
    explained_variance: np.ndarray  # (n_components,) float64 — variance along each component (singular_value**2 / (N-1))
    explained_variance_ratio: np.ndarray  # (n_components,) float64, sums to <= 1
    n_train: int

    @property
    def n_components(self) -> int:
        return self.components.shape[0]

    def encode(self, Z: np.ndarray) -> np.ndarray:
        """Transformed corridor values (M x n_corridor_cells) -> PCA scores
        (M x n_components)."""
        return (Z - self.mean) @ self.components.T.astype(np.float64)

    def decode(self, scores: np.ndarray) -> np.ndarray:
        """PCA scores (M x n_components) -> transformed corridor values
        (M x n_corridor_cells)."""
        return scores @ self.components.astype(np.float64) + self.mean

    def decode_std(self, sigma: np.ndarray) -> np.ndarray:
        """Per-component GP std (M x n_components) -> per-cell std in
        transformed space (M x n_corridor_cells), via
        `Var(y_i) = sum_j W_ij^2 * sigma_j^2` (docs/m5_specs.md §5.1,
        Donnelly et al. 2022's independent-GP variance-propagation note).

        This is **emulator uncertainty only**: it omits the PCA truncation
        error (the reconstruction RMSE reported by `fit_pca` covers that
        separately) and any input/breach-parameter uncertainty.
        """
        w2 = (self.components.astype(np.float64) ** 2)  # (n_components, n_cells)
        var = (sigma ** 2) @ w2  # (M, n_cells)
        return np.sqrt(var)

    def reconstruction_rmse(self, Z: np.ndarray) -> float:
        """RMSE (transformed space) of projecting `Z` onto this basis and
        decoding back, over every corridor cell of every row."""
        recon = self.decode(self.encode(Z))
        return float(np.sqrt(np.mean((Z - recon) ** 2)))

    def to_dict(self) -> dict:
        return {
            "mean": self.mean.astype(np.float64),
            "components": self.components.astype(np.float32),
            "explained_variance": self.explained_variance.astype(np.float64),
            "explained_variance_ratio": self.explained_variance_ratio.astype(np.float64),
            "n_train": np.array(self.n_train),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PCABasis":
        return cls(
            mean=np.asarray(d["mean"], dtype=np.float64),
            components=np.asarray(d["components"], dtype=np.float32),
            explained_variance=np.asarray(d["explained_variance"], dtype=np.float64),
            explained_variance_ratio=np.asarray(d["explained_variance_ratio"], dtype=np.float64),
            n_train=int(d["n_train"]),
        )


def fit_pca(Z: np.ndarray, variance: float = 0.99, max_components: int | None = None) -> PCABasis:
    """Fit a PCA basis on `Z` (N x n_corridor_cells, already transformed).

    Keeps the smallest number of components whose cumulative explained
    variance ratio reaches `variance` (docs/m5_specs.md §3: "smallest D*
    reaching 99% variance"), capped at `max_components` if given (spec:
    "capped at N - 2", passed in by the caller since it depends on N).
    Always keeps at least 1 component.
    """
    N = Z.shape[0]
    if N < 2:
        raise ValueError(f"fit_pca needs at least 2 training runs, got {N}")
    mean = Z.mean(axis=0)
    centred = Z - mean
    # full_matrices=False: thin SVD, U is N x min(N, n_cells)
    U, S, Vt = np.linalg.svd(centred, full_matrices=False)

    eigenvalues = (S ** 2) / (N - 1)
    total_variance = eigenvalues.sum()
    if total_variance <= 0:
        # degenerate: every training map identical after transform+masking
        d_star = 1
        ratio = np.array([1.0] + [0.0] * (len(eigenvalues) - 1)) if len(eigenvalues) > 1 else np.array([1.0])
    else:
        ratio = eigenvalues / total_variance
        cumulative = np.cumsum(ratio)
        d_star = int(np.searchsorted(cumulative, variance) + 1)
        d_star = min(d_star, len(eigenvalues))

    if max_components is not None:
        d_star = max(1, min(d_star, max_components))

    return PCABasis(
        mean=mean,
        components=Vt[:d_star].astype(np.float32),
        explained_variance=eigenvalues[:d_star],
        explained_variance_ratio=ratio[:d_star],
        n_train=N,
    )
