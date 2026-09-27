from backend.m3_dflowfm.mvp_case import prepare_case


def test_mvp_case_reuses_pilot_and_extends_baseline_through_stop(tmp_path):
    case, meta = prepare_case(tmp_path / "case", stop_s=108000)
    assert meta["cell_count"] == 33018
    assert meta["domain_status"] == "MVP_PILOT_DOMAIN"
    assert meta["source_count"] == 1
    assert meta["input_forcing_status"] == "MVP_RECONSTRUCTED"
    assert meta["scientific_claim"] == "NOT_OBSERVED_HYDROGRAPH"
    rows = [line.split() for line in (case / "inputs/breach_source.tim").read_text().splitlines()]
    assert float(rows[0][0]) == 0 and float(rows[0][1]) == 500
    assert max(float(row[1]) for row in rows) == 7355
    assert float(rows[-1][0]) == 1800
    assert float(rows[-1][1]) == 500
    assert (case / "inputs/teesta_2023_mvp_forcing.provenance.json").is_file()
