"""Rainfall accumulation over a catchment (contract §4.8 `rainfall.csv`). Pure arithmetic over the
daily catchment-mean rows `provider.rainfall_daily()` returns -- no Earth Engine calls here."""

from __future__ import annotations

from datetime import date, datetime


def to_rows(daily: list[dict], dataset: str) -> list[dict]:
    """`provider.rainfall_daily()` rows -> `rainfall.csv` rows (contract §4.8:
    `date,precip_mm,dataset,aggregation`). Sorted by date."""
    return sorted(
        ({"date": r["date"], "precip_mm": float(r["precip_mm"]), "dataset": dataset,
          "aggregation": "catchment_mean_daily_total"} for r in daily),
        key=lambda r: r["date"],
    )


def _as_date(d: str | date) -> date:
    return d if isinstance(d, date) else datetime.fromisoformat(d).date()


def accumulations(rows: list[dict], windows_days: tuple[int, ...], as_of: str | date | None = None) -> dict:
    """Trailing accumulation (mm) over each window in `windows_days`, ending at `as_of` (default:
    the latest date present). A window with no rows at all inside it reports `null`, not 0 -- a
    missing month of data must not silently read as "no rain" (contract §0 rule 9, never mix
    absence-of-data with an observed zero)."""
    if not rows:
        return {f"{w}d_mm": None for w in windows_days} | {"as_of": None, "last_date": None}

    dated = sorted(((_as_date(r["date"]), r["precip_mm"]) for r in rows), key=lambda p: p[0])
    last_date = dated[-1][0]
    end = _as_date(as_of) if as_of is not None else last_date

    out: dict = {"as_of": end.isoformat(), "last_date": last_date.isoformat()}
    for w in windows_days:
        start = end.fromordinal(end.toordinal() - w + 1)
        in_window = [precip for d, precip in dated if start <= d <= end]
        out[f"{w}d_mm"] = float(sum(in_window)) if in_window else None
    return out
