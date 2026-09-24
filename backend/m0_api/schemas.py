"""Loads contracts/schemas/*.json and validates payloads against them.

Every response this module (M0) sends is checked against its contract schema
before it goes out (CLAUDE.md rule 1: "Every input/output validates against a
schema"). Schemas may `$ref` any other file in contracts/schemas/ by file name
(e.g. `"common.schema.json#/$defs/Estimate"`); the resolver below indexes every
schema file so those refs resolve without needing network access or $id
lookups.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, RefResolver

CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "contracts"
SCHEMAS_DIR = CONTRACTS_DIR / "schemas"
EXAMPLES_DIR = CONTRACTS_DIR / "examples"


class ContractViolation(ValueError):
    """A payload does not match its declared contracts/schemas/*.json schema."""


@lru_cache(maxsize=1)
def _schema_store() -> dict[str, dict]:
    """Every schema file, keyed by file name, so cross-file `$ref`s resolve."""
    if not SCHEMAS_DIR.is_dir():
        raise FileNotFoundError(
            f"{SCHEMAS_DIR} does not exist. Generate contracts/ before starting m0_api."
        )
    return {p.name: json.loads(p.read_text()) for p in SCHEMAS_DIR.glob("*.schema.json")}


@lru_cache(maxsize=None)
def load_schema(name: str) -> dict:
    """Load one schema by file name, e.g. 'flood_query_response.schema.json'."""
    store = _schema_store()
    if name not in store:
        raise FileNotFoundError(f"No schema named {name!r} in {SCHEMAS_DIR}")
    return store[name]


@lru_cache(maxsize=None)
def load_example(name: str) -> dict:
    """Load one example by file name, e.g. 'flood_query_response.example.json'."""
    path = EXAMPLES_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"No example named {name!r} in {EXAMPLES_DIR}")
    return json.loads(path.read_text())


def validator_for(schema_name: str) -> Draft202012Validator:
    schema = load_schema(schema_name)
    resolver = RefResolver(base_uri="", referrer=schema, store=_schema_store())
    return Draft202012Validator(schema, resolver=resolver)


def validate(schema_name: str, payload: Any) -> None:
    """Raise ContractViolation with every failing path if `payload` doesn't
    match `schema_name`. Used on every outgoing response and on request
    bodies that have a dedicated request schema."""
    validator = validator_for(schema_name)
    errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
    if errors:
        messages = [f"${'/'.join(str(p) for p in e.path)}: {e.message}" for e in errors]
        raise ContractViolation(f"{schema_name} — " + "; ".join(messages))
