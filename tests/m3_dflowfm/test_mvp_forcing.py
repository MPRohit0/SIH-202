from datetime import datetime, timedelta

import numpy as np

from backend.m3_dflowfm.mvp_forcing import (
    BASE_Q_M3S,
    EVENT_VOLUME_M3,
    PEAK_Q_M3S,
    PEAK_AT_IST,
    triangular_event_forcing,
    write_mvp_forcing,
)


def test_reconstructed_triangle_has_constraints_and_exact_excess_volume():
    result = triangular_event_forcing()
    assert result.timestamps_ist[np.argmax(result.q_m3s)] == PEAK_AT_IST
    assert result.q_m3s.max() == PEAK_Q_M3S
    assert result.q_m3s[0] == result.q_m3s[-1] == BASE_Q_M3S
    assert np.trapezoid(result.q_m3s - BASE_Q_M3S, result.t_s) == pytest.approx(EVENT_VOLUME_M3)
    expected_half_duration = EVENT_VOLUME_M3 / (PEAK_Q_M3S - BASE_Q_M3S)
    assert result.timestamps_ist[0] == PEAK_AT_IST - timedelta(seconds=expected_half_duration)


def test_writer_emits_provenance_and_nonempty_series(tmp_path):
    import csv
    import json

    series, provenance = write_mvp_forcing(tmp_path)
    rows = list(csv.DictReader(series.open(encoding="utf-8")))
    metadata = json.loads(provenance.read_text(encoding="utf-8"))
    assert len(rows) > 100
    assert metadata["provenance"]["status"] == "MVP_RECONSTRUCTED"
    assert metadata["provenance"]["scientific_claim"] == "NOT_OBSERVED_HYDROGRAPH"
    assert metadata["provenance"]["construction"]["integrated_excess_volume_m3"] == pytest.approx(EVENT_VOLUME_M3)


def test_naive_peak_time_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        triangular_event_forcing(peak_time_ist=datetime(2023, 10, 4, 3, 20))


import pytest
