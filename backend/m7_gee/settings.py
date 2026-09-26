"""Team settings for the M7 GEE fetch pipeline (`docs/decisions.md` "M7 GEE fetch"). These are
engineering knobs, not facts -- no `SourcedValue` wrapping (CLAUDE.md rule 3 is about facts;
`docs/handoff_contract.md` rule 4 puts thresholds/settings in `docs/decisions.md` instead), same
pattern as `backend/m1_terrain/settings.py`."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GeeSettings(BaseModel):
    """Every M7 fetch setting, with its default. Overridable per CLI run; the values used for a
    given run are recorded in `gee_meta.json`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: half-width (m) of the square AOI grid built around the lake seed point.
    lake_buffer_m: float = Field(default=3000.0, gt=0)

    #: pixel size (m) of the local AOI grid used for water classification.
    pixel_size_m: float = Field(default=10.0, gt=0)

    #: how many trailing months (inclusive of the current one) to build the lake-area series for.
    months_back: int = Field(default=24, gt=0)

    #: Sentinel-2 monthly composite is used only if its cloud share over the AOI buffer is at or
    #: below this; otherwise the month falls back to Sentinel-1.
    max_cloud_pct: float = Field(default=20.0, ge=0, le=100)

    #: a month is skipped entirely (no area row written) if the SCL snow/ice class covers more of
    #: the AOI buffer than this -- both NDWI and SAR under-detect an ice-covered lake.
    max_snow_ice_pct: float = Field(default=30.0, ge=0, le=100)

    #: a month is skipped if fewer than this share of AOI buffer pixels have any valid
    #: observation at all that month (e.g. a gap in Sentinel-1 coverage).
    min_valid_pct: float = Field(default=50.0, ge=0, le=100)

    #: Otsu threshold on the NDWI index is clamped to this range -- keeps a degenerate histogram
    #: (e.g. an almost-uniform composite) from picking a threshold that is not physically sensible.
    ndwi_threshold_clamp: tuple[float, float] = (-0.2, 0.4)

    #: Otsu threshold on Sentinel-1 VV backscatter (dB) is clamped to this range.
    s1_vv_threshold_clamp_db: tuple[float, float] = (-22.0, -10.0)

    #: how many trailing days of rainfall accumulation to fetch.
    rain_days_back: int = Field(default=30, gt=0)

    #: rainfall accumulation windows (days) recorded in `gee_meta.json`.
    rain_accumulation_windows_days: tuple[int, ...] = (7, 30)

    rain_dataset: Literal["chirps", "gpm_imerg"] = "chirps"

    #: HydroBASINS level used to build the rainfall catchment (higher = smaller, more detailed
    #: basins; level 12 is HydroSHEDS' finest standard level).
    hydrobasins_level: int = Field(default=12, ge=1, le=12)

    #: `recheck.json` `threshold_pct` default -- a site's library is flagged `outdated_lake_area_
    #: change` once |change_pct| reaches this. Matches the contract's example payload (§5.8).
    #: PENDING team agreement (docs/decisions.md "M7 GEE fetch").
    recheck_threshold_pct: float = Field(default=10.0, gt=0)
