"""Prepare the single-source Teesta event replay from the frozen M3 pilot case.

This path deliberately reuses the retained 33,018-face pilot case byte-for-byte for
geometry, bed, source location, boundaries, POIs and solver settings. The only solver
input changed is the source discharge series, from the adjacent MVP reconstruction.
"""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

from backend.m3_dflowfm.mvp_forcing import write_mvp_forcing

REPO = Path(__file__).resolve().parents[2]
PILOT_CASE = REPO / "backend/m3_pilot/dflowfm/case"
MODEL = "teesta_pilot_s001__dflowfm"


def prepare_case(case_dir: str | Path, *, input_dir: str | Path | None = None,
                 stop_s: float = 108000.0) -> tuple[Path, dict]:
    """Copy the frozen case and replace only its South Lhonak source time series."""
    target = Path(case_dir).resolve()
    if target.exists():
        raise FileExistsError(f"refusing to overwrite an existing MVP case: {target}")
    source_dir = Path(input_dir) if input_dir else REPO / "data/teesta_mvp/inputs"
    csv_path = source_dir / "teesta_2023_mvp_forcing.csv"
    provenance_path = source_dir / "teesta_2023_mvp_forcing.provenance.json"
    if not csv_path.is_file() or not provenance_path.is_file():
        csv_path, provenance_path = write_mvp_forcing(source_dir)
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if provenance.get("provenance", {}).get("status") != "MVP_RECONSTRUCTED" or \
            provenance.get("provenance", {}).get("scientific_claim") != "NOT_OBSERVED_HYDROGRAPH":
        raise ValueError("MVP forcing provenance is missing its reconstructed/not-observed labels")

    shutil.copytree(PILOT_CASE, target, ignore=shutil.ignore_patterns("*.pyc", "__pycache__"))
    forcing_rows: list[tuple[float, float]] = []
    with csv_path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            forcing_rows.append((float(row["t_s_since_hydrograph_start"]), float(row["q_m3s"])))
    if len(forcing_rows) < 3 or forcing_rows[0][1] != 500 or max(q for _, q in forcing_rows) != 7355:
        shutil.rmtree(target)
        raise ValueError("forcing file does not contain the expected baseline, peak, and time series")
    if stop_s <= forcing_rows[-1][0]:
        raise ValueError("solver stop time must be later than the reconstructed event series")
    # D-Flow pilot .tim inputs use minutes since t0. Keep the supplied reconstruction's
    # time origin (t0), peak time, baseline and values unchanged, then hold its explicit
    # baseline through TStop so the external-forcing reader never runs past file end.
    with (target / "inputs/breach_source.tim").open("w", encoding="ascii") as stream:
        for seconds, discharge in forcing_rows:
            stream.write(f"{seconds / 60.0:.8f} {discharge:.6f}\n")
        stream.write(f"{stop_s / 60.0:.8f} {forcing_rows[-1][1]:.6f}\n")

    case_meta_path = target / "case_meta.json"
    pilot_meta = json.loads(case_meta_path.read_text(encoding="utf-8"))
    metadata = {
        **pilot_meta,
        "scenario_id": "teesta_2023_mvp",
        "run_id": "teesta_2023_mvp__delft3d",
        "geometry_source": "backend/m3_pilot/dflowfm/case (retained frozen pilot)",
        "domain_status": "MVP_PILOT_DOMAIN",
        "input_forcing_status": "MVP_RECONSTRUCTED",
        "scientific_claim": "NOT_OBSERVED_HYDROGRAPH",
        "source_count": 1,
        "source_id": "south_lhonak",
        "source_method": "frozen pilot South Lhonak point source",
        "forcing_csv": str(csv_path.resolve()),
        "forcing_provenance": str(provenance_path.resolve()),
        "forcing_points": len(forcing_rows),
        "forcing_solver_points": len(forcing_rows) + 1,
        "forcing_baseline_held_until_model_s": stop_s,
        "forcing_peak_q_m3s": max(q for _, q in forcing_rows),
        "forcing_start_model_s": forcing_rows[0][0],
        "forcing_peak_model_s": forcing_rows[max(range(len(forcing_rows)), key=lambda i: forcing_rows[i][1])][0],
        "solver_output_status": "PENDING_REAL_SOLVER",
        "mvp_limitation": "event replay using reconstructed source forcing; no Teesta III source or cascade",
    }
    case_meta_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    # Preserve the input and its provenance beside the case so the run remains auditable.
    shutil.copy2(csv_path, target / "inputs/teesta_2023_mvp_forcing.csv")
    shutil.copy2(provenance_path, target / "inputs/teesta_2023_mvp_forcing.provenance.json")
    return target, metadata
