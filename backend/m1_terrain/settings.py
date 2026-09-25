"""Team settings for the M1 terrain pipeline (`docs/decisions.md` 2026-09-25 "M1 terrain
settings"). These are engineering knobs, not facts — no `SourcedValue` wrapping (CLAUDE.md rule 3
is about facts; `docs/handoff_contract.md` rule 4 puts thresholds/settings in `docs/decisions.md`
instead)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TerrainSettings(BaseModel):
    """Every M1 pipeline setting, with its default. Overridable per CLI run; the values used for a
    given run are recorded in `terrain/provenance.json`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: valley-corridor domain: max height above the main channel (HAND), m. Generous enough for
    #: GLOF flows tens of metres deep, tight enough to keep the Delft3D mesh a manageable size.
    domain_max_hand_m: float = Field(default=50.0, gt=0)

    #: radius (m) within which a dam's `location`/`breach_location` is snapped onto the drainage
    #: network (highest flow accumulation) or onto a WorldCover water component.
    snap_radius_m: float = Field(default=300.0, gt=0)

    #: minimum flow-accumulation cell count for a cell to count as "the drainage network" when
    #: snapping a breach location or POI onto the centreline.
    stream_accum_min_cells: int = Field(default=50, gt=0)

    #: how far (m) a burned dam crest is allowed to search sideways from `dam.location` for
    #: terrain already at or above the crest elevation, before it gives up and stops the crest
    #: line there anyway (caps runaway burn-in on a mis-placed dam point).
    crest_search_max_m: float = Field(default=2000.0, gt=0)

    #: ESA WorldCover class code for permanent water bodies (`docs/data_sources.md` src_036 legend).
    lake_class_code: int = Field(default=80, ge=0, le=255)

    #: Manning table class code for the main channel (`config/manning_n.csv` row 999), applied to
    #: centreline cells so the fallback/emulator see channel roughness even where WorldCover
    #: guesses grass or bare ground for a narrow river cell.
    channel_class_code: int = Field(default=999, ge=0, le=255)

    #: priority-flood fill epsilon (m) added per downstream step, so the filled DEM has a strict
    #: downhill gradient everywhere (Barnes et al. 2014) instead of dead-flat plateaus that break D8.
    fill_epsilon_m: float = Field(default=1e-5, gt=0)
