# contracts/

JSON Schemas (`schemas/`) and one valid example per schema (`examples/`), plus
`styles.json` (contract §6), generated from `docs/handoff_contract.md`. If code and
this directory disagree, the handoff contract is the source of truth (contract §0
rule 1) — fix here, don't hand-edit around it.

- `schemas/common.schema.json` holds the shared building blocks (`SourcedValue`,
  `Estimate`, `Confidence`, `Caveat`, `Provenance`, `LayerRef`, `Error` — contract
  §2). Other schemas `$ref` it by file name, e.g. `"common.schema.json#/$defs/Estimate"`.
- Every other `schemas/*.schema.json` file is one response or request payload from
  contract §5 / §4. `$ref`s between schema files resolve by file name (see
  `backend/m0_api/schemas.py`).
- `examples/*.example.json` are the payloads `backend/m0_api`'s mock mode serves
  (contract §8: "The frontend's mock mode serves the example files from
  `contracts/`, so mocks can never drift from the contract"). Numeric values
  follow the contract's own "0.0 / ILLUSTRATIVE" convention — they are not site
  facts (CLAUDE.md rule 3).
- `schemas/site_config.schema.json` (contract §3.1) is the one exception to
  "generated from `docs/handoff_contract.md`": it's generated straight from
  `backend.shared.site_config.SiteConfig.model_json_schema()`, since §3.1 is
  itself written to mirror that model (`docs/decisions.md` 2026-09-25). Regenerate
  it after any change to `site_config.py`'s models, don't hand-edit it.
- `tests/m0_api/test_schemas.py` checks every example against its schema;
  `tests/m0_api/test_endpoints.py` checks every live endpoint's response the
  same way.

Known gaps, not yet resolved (see `docs/decisions.md`):

- `docs/m5_spec.md`, `docs/equations.md` and `docs/events/` don't exist yet, so
  the schemas here don't encode the confidence-rule thresholds or per-event
  specifics — only the shapes contract §2-§5 already spell out.
