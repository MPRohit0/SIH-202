"""One independent Gaussian Process per PCA component (`docs/m5_specs.md`
§3, Donnelly et al. 2022 §"Method: PCA + independent GPs (SOGP)").

Kernel: Matern nu=1.5 (spec: "Matern 3/2 + white noise"), **ARD** — one
length scale per (standardised) input, since our inputs matter unequally
(spec: "V_w usually dominates") — plus a `WhiteKernel` noise term. Length
scales are bounded to [0.1, 10] in standardised units (spec: "with 30 points
an unbounded optimiser can pick absurd length-scales"). The optimiser
restarts `n_restarts` times from random points (spec: "the likelihood
surface is multimodal at small N") and scikit-learn keeps the best
log-marginal-likelihood automatically.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel

LENGTH_SCALE_BOUNDS = (0.1, 10.0)  # standardised units (docs/m5_specs.md §3)
AMPLITUDE_BOUNDS = (1e-3, 1e3)
NOISE_FLOOR = 1e-6                 # noise variance >= 1e-6 * component variance (spec §3)
NOISE_UPPER_BOUND = 1.0
DEFAULT_N_RESTARTS = 10


def make_kernel(n_inputs: int):
    """`ConstantKernel * Matern(nu=1.5, ARD) + WhiteKernel` (docs/m5_specs.md
    §3: "Matern 3/2 + white noise ... ARD"). `GaussianProcessRegressor` is
    always called with `normalize_y=True`, which standardises the target
    (each PCA component's scores) to zero mean/unit variance before fitting
    — so "component variance" in the spec's noise-floor rule
    ("sigma_n^2 >= 1e-6 x component variance") is exactly 1 in the space the
    kernel hyperparameters are actually optimised in, and the floor is the
    constant `NOISE_FLOOR` below.
    """
    length_scale = np.ones(n_inputs)
    amplitude = ConstantKernel(1.0, AMPLITUDE_BOUNDS)
    matern = Matern(length_scale=length_scale, length_scale_bounds=LENGTH_SCALE_BOUNDS, nu=1.5)
    white = WhiteKernel(noise_level=NOISE_FLOOR, noise_level_bounds=(NOISE_FLOOR, NOISE_UPPER_BOUND))
    return amplitude * matern + white


@dataclass
class GPFitResult:
    """One component's fitted GP plus bookkeeping the manifest reports."""

    gp: GaussianProcessRegressor
    log_marginal_likelihood: float
    length_scales: dict[str, float]
    noise_level: float
    at_bounds: list[str] = field(default_factory=list)  # input names whose fitted length scale hit a bound


def fit_component_gps(
    X_std: np.ndarray,
    scores: np.ndarray,
    input_names: list[str],
    n_restarts: int = DEFAULT_N_RESTARTS,
    seed: int = 0,
) -> list[GPFitResult]:
    """Fit one GP per column of `scores` (N x n_components) against `X_std`
    (N x n_inputs, already standardised). Returns one `GPFitResult` per
    component, in column order.
    """
    n_inputs = X_std.shape[1]
    if len(input_names) != n_inputs:
        raise ValueError(f"input_names has {len(input_names)} names, X_std has {n_inputs} columns")

    results: list[GPFitResult] = []
    for j in range(scores.shape[1]):
        y = scores[:, j]
        kernel = make_kernel(n_inputs)
        gp = GaussianProcessRegressor(
            kernel=kernel,
            normalize_y=True,
            n_restarts_optimizer=n_restarts,
            random_state=seed + j,
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ConvergenceWarning)
            gp.fit(X_std, y)
        fit_warnings = [str(w.message) for w in caught if issubclass(w.category, ConvergenceWarning)]
        results.append(describe_fitted_gp(gp, input_names, extra_warnings=fit_warnings))
    return results


def describe_fitted_gp(
    gp: GaussianProcessRegressor, input_names: list[str], extra_warnings: list[str] | None = None,
) -> GPFitResult:
    """Build a `GPFitResult` from an already-fitted `GaussianProcessRegressor`
    (used both right after `fit_component_gps` and after loading GPs back
    from disk, so length scales / noise level are read the same way in both
    places)."""
    # kernel_ = Sum(k1=Product(ConstantKernel, Matern), k2=WhiteKernel)
    fitted_matern = gp.kernel_.k1.k2
    ls = np.atleast_1d(fitted_matern.length_scale)
    length_scales = {name: float(ls[i]) for i, name in enumerate(input_names)}
    at_bounds = [
        name for name, l in length_scales.items()
        if np.isclose(l, LENGTH_SCALE_BOUNDS[0], rtol=1e-3) or np.isclose(l, LENGTH_SCALE_BOUNDS[1], rtol=1e-3)
    ]
    return GPFitResult(
        gp=gp,
        log_marginal_likelihood=float(gp.log_marginal_likelihood_value_),
        length_scales=length_scales,
        noise_level=float(gp.kernel_.k2.noise_level),
        at_bounds=at_bounds or (extra_warnings or []),
    )


def predict_components(gps: list[GPFitResult], X_std: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Predict mean and std for every component at every query row.
    Returns (mu, sigma), each (n_queries, len(gps))."""
    X_std = np.atleast_2d(X_std)
    mus = np.empty((X_std.shape[0], len(gps)))
    sigmas = np.empty((X_std.shape[0], len(gps)))
    for j, result in enumerate(gps):
        mu, sigma = result.gp.predict(X_std, return_std=True)
        mus[:, j] = mu
        sigmas[:, j] = sigma
    return mus, sigmas
