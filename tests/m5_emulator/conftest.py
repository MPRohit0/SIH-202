"""Shared fixtures for the get_flood()-related test modules
(test_confidence.py, test_monte_carlo.py, test_query.py).

`trained_small` fits on `synthetic.small_grid()` -- the same grid
`test_emulator.py` already trains on at module scope, so this follows that
existing precedent rather than inventing a coarser grid. A coarser custom
grid was tried and rejected: `synthetic.poi_cell_index`'s "centreline cell"
convention (`row = height // 2`) is off the true channel centreline by
`cell_size_m / 2`, and at a coarse cell size that's enough to fall outside
the ~25 m gorge half-width, taking POIs outside the trained corridor mask
entirely. Monte Carlo correctness tests instead keep wall time down with a
modest `n_samples` (~100-300), not a smaller grid.
"""

from __future__ import annotations

import pytest

from backend.m5_emulator import library as lib
from backend.m5_emulator import synthetic as sw
from backend.m5_emulator.emulator import EmulatorSettings, FloodEmulator
from backend.m5_emulator.inputs import make_input_specs

N_TRAIN = 20
SEED = 42


@pytest.fixture(scope="module")
def tiny_library():
    return lib.build_synthetic_library(sw.small_grid(), n=N_TRAIN, seed=SEED)


@pytest.fixture(scope="module")
def trained_small(tiny_library) -> FloodEmulator:
    ranges = {
        name: (float(tiny_library.X_raw[:, i].min()), float(tiny_library.X_raw[:, i].max()))
        for i, name in enumerate(lib.INPUT_ORDER)
    }
    specs = make_input_specs(ranges)
    return FloodEmulator.fit(
        site_id="m5synth_tiny", model="synthetic", X_raw=tiny_library.X_raw,
        maps={"max_depth": tiny_library.max_depth, "max_velocity": tiny_library.max_velocity,
              "arrival_time": tiny_library.arrival_time},
        grid=tiny_library.grid, input_specs=specs, run_ids=tiny_library.run_ids,
        t_end_s=tiny_library.t_end_s, settings=EmulatorSettings(seed=SEED, n_restarts=3),
    )


@pytest.fixture(scope="module")
def tiny_pois(trained_small):
    return {name: sw.poi_cell_index(trained_small.grid, chainage) for name, chainage in sw.SYNTHETIC_POIS.items()}
