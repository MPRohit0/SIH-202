"""Run contract post-processing for the current Teesta D-Flow FM pilot output."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.m3_common.postprocess import PostprocessConfig, postprocess_dflowfm  # noqa: E402

DEFAULT_CASE = ROOT / "data/teesta_pilot/runs/teesta_pilot_s001/dflowfm_reproduction_map60/case"
DEFAULT_RUN = ROOT / "data/teesta_pilot/runs/teesta_pilot_s001__delft3d"
GRID = ROOT / "data/teesta_pilot/terrain/grid.json"
DOMAIN_MASK = ROOT / "data/teesta_pilot/terrain/domain_mask.tif"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, default=DEFAULT_CASE)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--delete-raw-map", action="store_true",
                        help="delete the raw *_map.nc only after all contract outputs validate")
    args = parser.parse_args()
    meta = postprocess_dflowfm(
        args.case_dir, args.run_dir, grid_path=GRID, domain_mask_path=DOMAIN_MASK,
        run_id="teesta_pilot_s001__delft3d", scenario_id="teesta_pilot_s001",
        hydrographs=["breach/hydrographs/teesta_pilot_s001__south_lhonak.csv"],
        spinup_s=7200.0, config=PostprocessConfig(delete_raw_map=args.delete_raw_map),
    )
    print(f"postprocessed {meta['run_id']} to {args.run_dir}")


if __name__ == "__main__":
    main()
