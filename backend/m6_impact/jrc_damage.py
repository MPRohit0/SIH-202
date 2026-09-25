"""Extract `damage_curves.csv` and `asset_values.csv` (docs/handoff_contract.md §4.7
"Exposure inputs") from the JRC global flood depth-damage functions workbook:

    Huizinga, J., de Moel, H., Szewczyk, W. (2017). Global flood depth-damage
    functions. Methodology and the database with guidelines. JRC EUR 28552 EN.
    doi: 10.2760/16510. docs/data_sources.md src_031 (damage functions) /
    src_032 (max damage values).

`damage_curves.csv` takes the ASIA depth-damage fractions from the workbook's
'Damage functions' sheet, one row per (asset_class, depth_m). `asset_values.csv`
takes India's max-damage values from the six 'MaxDamage-*' sheets, in 2010 EUR
per m2, converted to `value_inr_per_unit` using `config/impact.yaml`'s FX rate
and price index (both placeholders until the team sources them — CLAUDE.md
rule 3, never invent a coefficient). Every row cites the exact sheet and cell
it came from, in `jrc_cell`.

CLI: `python -m backend.m6_impact.jrc_damage <site_id> <xlsx_path>`
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from backend.m6_impact.loss import LossConfig, load_loss_config

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

#: JRC 'Damage functions' sheet class label -> our asset_class slug.
DAMAGE_CLASS_LABELS: dict[str, str] = {
    "Residential buildings": "residential",
    "Commercial buildings": "commercial",
    "Industrial buildings": "industrial",
    "Transport": "transport",
    "Infrastructure - roads": "infrastructure_roads",
    "Agriculture": "agriculture",
}

#: asset_class -> the MaxDamage-* sheet holding its max damage value.
MAXDAMAGE_SHEET: dict[str, str] = {
    "residential": "MaxDamage-Residential",
    "commercial": "MaxDamage-Commercial",
    "industrial": "MaxDamage-Industrial",
}

M2_PER_HA = 10_000.0


class JrcExtractionError(ValueError):
    """The workbook doesn't have the sheet/row/column layout this extractor expects."""


def _col_index(ws, header_row: int, label: str) -> int:
    """1-based column index of the first cell in `header_row` equal to `label` (stripped)."""
    for cell in ws[header_row]:
        if cell.value is not None and str(cell.value).strip() == label:
            return cell.column
    raise JrcExtractionError(f"{ws.title!r}: no column {label!r} in header row {header_row}")


def _row_by_label(ws, col: int, label: str, *, start: int = 1) -> int:
    """1-based row index of the first cell in column `col` equal to `label` (stripped)."""
    for row in range(start, ws.max_row + 1):
        v = ws.cell(row=row, column=col).value
        if v is not None and str(v).strip() == label:
            return row
    raise JrcExtractionError(f"{ws.title!r}: no {label!r} in column {get_column_letter(col)}")


def _cell_ref(sheet: str, row: int, col: int) -> str:
    return f"'{sheet}'!{get_column_letter(col)}{row}"


# =============================================================================
# damage_curves.csv — 'Damage functions' sheet, ASIA column
# =============================================================================


def extract_damage_curves(xlsx_path: str | Path) -> list[dict[str, Any]]:
    """Rows of `{asset_class, depth_m, damage_fraction, source}` for the 6 JRC
    classes, ASIA column, depth 0-6 m (docs/handoff_contract.md §4.7's CSV has
    no `status` column, so a plain 'src_031' is all `source` carries)."""
    wb = load_workbook(xlsx_path, data_only=True)
    ws = wb["Damage functions"]
    # Row 1 is blank, row 2 holds "Damage\nclass" / "Flood depth,\n[m]" / "Damage function" /
    # "Standard deviation", row 3 holds the per-continent sub-headers (EUROPE ... ASIA ...), data from row 4.
    class_col = _col_index(ws, header_row=2, label="Damage\nclass")
    depth_col = _col_index(ws, header_row=2, label="Flood depth,\n[m]")
    asia_col = _col_index(ws, header_row=3, label="ASIA")

    rows: list[dict[str, Any]] = []
    current: str | None = None
    for r in range(4, ws.max_row + 1):
        label = ws.cell(row=r, column=class_col).value
        if label is not None:
            current = DAMAGE_CLASS_LABELS.get(str(label).strip())
        depth = ws.cell(row=r, column=depth_col).value
        asia = ws.cell(row=r, column=asia_col).value
        if current is None or depth is None or not isinstance(asia, (int, float)):
            continue
        rows.append({
            "asset_class": current,
            "depth_m": float(depth),
            "damage_fraction": float(asia),
            "source": "src_031",
        })

    missing = set(DAMAGE_CLASS_LABELS.values()) - {r["asset_class"] for r in rows}
    if missing:
        raise JrcExtractionError(f"no ASIA damage-function rows found for {sorted(missing)}")
    return rows


# =============================================================================
# asset_values.csv — MaxDamage-* sheets, India
# =============================================================================


def _building_based_total(xlsx_path_wb, asset_class: str, country: str) -> tuple[float, str]:
    """(value_eur2010_per_m2, jrc_cell) — the 'building based / Total' column
    (docs/handoff_contract.md §4.7: "Euros/m2 ... 2010 price level")."""
    ws = xlsx_path_wb[MAXDAMAGE_SHEET[asset_class]]
    country_col = _col_index(ws, header_row=2, label="Country")
    total_col = _col_index(ws, header_row=1, label="Building based")
    # header row 1 merges "Building based" across 3 columns (Structure, Content, Total);
    # the 3rd of those sub-columns is Total (row 2's own header confirms it).
    total_col += 2
    if str(ws.cell(row=2, column=total_col).value).strip() != "Total":
        raise JrcExtractionError(f"{ws.title!r}: expected 'Total' at column {get_column_letter(total_col)}, "
                                  f"row 2; got {ws.cell(row=2, column=total_col).value!r}")
    row = _row_by_label(ws, country_col, country, start=3)
    value = ws.cell(row=row, column=total_col).value
    if not isinstance(value, (int, float)):
        raise JrcExtractionError(f"{ws.title!r} {country}: Total max-damage value is not numeric ({value!r})")
    return float(value), _cell_ref(ws.title, row, total_col)


def _agriculture_value(xlsx_path_wb, country: str) -> tuple[float, str]:
    """Value added per hectare -> per m2 (docs/handoff_contract.md §4.7 CSV is per-unit).

    Unlike the other MaxDamage-* sheets, this one has no literal 'Country' header cell
    (row 1/2 hold only the value-column headers) — country names start directly in
    column A, row 3, so the country column is fixed rather than looked up by label."""
    ws = xlsx_path_wb["MaxDamage-Agriculture"]
    country_col = 1  # column A
    value_col = country_col + 1  # "Value Added/Hectare (avg 2008-2012)"
    row = _row_by_label(ws, country_col, country, start=3)
    value_per_ha = ws.cell(row=row, column=value_col).value
    if not isinstance(value_per_ha, (int, float)):
        raise JrcExtractionError(f"MaxDamage-Agriculture {country}: value added/ha is not numeric ({value_per_ha!r})")
    return float(value_per_ha) / M2_PER_HA, _cell_ref(ws.title, row, value_col) + " (EUR/ha, converted to EUR/m2)"


def _gdp_scaled_value(xlsx_path_wb, sheet_name: str, country: str, region: str) -> tuple[float, str]:
    """Infrastructure/Transport: country GDP-per-capita x (region max damage / region GDP-per-capita),
    the recipe documented in each MaxDamage-Infrastructure/-Transport sheet's own 'How to calculate' block."""
    ws = xlsx_path_wb[sheet_name]
    country_col = _col_index(ws, header_row=2, label="Country")
    gdp_col = country_col + 1
    country_row = _row_by_label(ws, country_col, country, start=3)
    country_gdp = ws.cell(row=country_row, column=gdp_col).value
    if not isinstance(country_gdp, (int, float)):
        raise JrcExtractionError(f"{sheet_name} {country}: GDP per capita is not numeric ({country_gdp!r})")

    label_col = _col_index(ws, header_row=2, label="How to calculate") + 1  # e.g. "Asia:"
    ratio_col, gdp_ref_col = label_col + 1, label_col + 2
    region_row = None
    for r in range(3, ws.max_row + 1):
        v = ws.cell(row=r, column=label_col).value
        if v is not None and str(v).strip().rstrip(":").upper() == region.upper():
            region_row = r
            break
    if region_row is None:
        raise JrcExtractionError(f"{sheet_name}: no region row for {region!r} in column {get_column_letter(label_col)}")

    region_max_damage = ws.cell(row=region_row, column=ratio_col).value
    region_gdp = ws.cell(row=region_row, column=gdp_ref_col).value
    if not isinstance(region_max_damage, (int, float)) or not isinstance(region_gdp, (int, float)):
        raise JrcExtractionError(f"{sheet_name} {region}: max-damage/GDP reference values are not numeric")

    value = float(country_gdp) * (float(region_max_damage) / float(region_gdp))
    cell = (f"{_cell_ref(ws.title, country_row, gdp_col)} (GDP) x "
            f"{_cell_ref(ws.title, region_row, ratio_col)}/{_cell_ref(ws.title, region_row, gdp_ref_col)} "
            f"({region} ratio, EUR/m2 per 2010 US$ GDP)")
    return value, cell


def extract_asset_values(xlsx_path: str | Path, config: LossConfig) -> list[dict[str, Any]]:
    """Rows of `{asset_class, value_inr_per_unit, unit, source, status, value_eur2010, jrc_cell}`,
    one per JRC class, for `config.loss.jrc_country`. `value_inr_per_unit` is EUR2010 x FX x price
    index and is left as `""` (with `status: placeholder`) while either factor is a placeholder."""
    wb = load_workbook(xlsx_path, data_only=True)
    country = config.jrc_country
    region = config.jrc_region

    eur_values: dict[str, tuple[float, str]] = {
        "residential": _building_based_total(wb, "residential", country),
        "commercial": _building_based_total(wb, "commercial", country),
        "industrial": _building_based_total(wb, "industrial", country),
        "agriculture": _agriculture_value(wb, country),
        "infrastructure_roads": _gdp_scaled_value(wb, "MaxDamage-Infrastructure", country, region),
        "transport": _gdp_scaled_value(wb, "MaxDamage-Transport", country, region),
    }

    fx, index = config.eur_to_inr_2010, config.price_index_2010_to_current
    inr_status = "sourced" if (fx.status == "sourced" and index.status == "sourced") else "placeholder"

    rows = []
    for asset_class, (eur, cell) in eur_values.items():
        value_inr = eur * fx.value * index.value if inr_status == "sourced" else None
        rows.append({
            "asset_class": asset_class,
            "value_inr_per_unit": value_inr if value_inr is not None else "",
            "unit": "INR/m2",
            "source": "src_032",
            "status": inr_status,
            "value_eur2010": eur,
            "jrc_cell": cell,
        })
    return rows


# =============================================================================
# CSV writers / CLI
# =============================================================================


def write_damage_curves_csv(rows: list[dict[str, Any]], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["asset_class", "depth_m", "damage_fraction", "source"])
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_asset_values_csv(rows: list[dict[str, Any]], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["asset_class", "value_inr_per_unit", "unit", "source", "status", "value_eur2010", "jrc_cell"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_all(site_id: str, xlsx_path: str | Path, data_dir: Path = DATA_DIR,
              config: LossConfig | None = None) -> dict[str, Path]:
    config = config or load_loss_config()
    exposure_dir = data_dir / site_id / "exposure"
    damage_path = write_damage_curves_csv(extract_damage_curves(xlsx_path), exposure_dir / "damage_curves.csv")
    values_path = write_asset_values_csv(extract_asset_values(xlsx_path, config), exposure_dir / "asset_values.csv")
    return {"damage_curves": damage_path, "asset_values": values_path}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("site_id", help="site id (writes to data/<site_id>/exposure/)")
    parser.add_argument("xlsx_path", help="path to the JRC depth-damage functions workbook")
    parser.add_argument("--data-dir", default=str(DATA_DIR), help="override the data/ root")
    args = parser.parse_args(argv)

    out = write_all(args.site_id, args.xlsx_path, data_dir=Path(args.data_dir))
    for name, path in out.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
