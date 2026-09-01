"""Load PST master data from the 'PST subfamily based pricing.xlsx' spreadsheet.

This script reads the spreadsheet and populates:
  - modalities (seeded)
  - families (derived from unique Family column)
  - sub_families (derived from unique Family+Sub Family combos)
  - sub_family_modalities junction (each Modality+Sub-Family row)

Usage:
    python -m pst.load_pst_data "path/to/PST subfamily based pricing.xlsx"

If no path is given, it looks for the file in the default location.
Requires DATABASE_URL to be set in the environment or .streamlit/secrets.toml.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import pandas as pd

from pst import db


DEFAULT_XLSX = (
    Path.home()
    / "OneDrive - Philips"
    / "02. Commercial IT"
    / "Spare Parts Services"
    / "PST subfamily based pricing.xlsx"
)


def load_spreadsheet(xlsx_path: str | Path | None = None) -> None:
    path = Path(xlsx_path) if xlsx_path else DEFAULT_XLSX
    if not path.exists():
        print(f"ERROR: File not found: {path}")
        sys.exit(1)

    print(f"Reading: {path}")
    df = pd.read_excel(path, dtype=str)
    df.columns = df.columns.str.strip()
    for col in df.columns:
        df[col] = df[col].fillna("").str.strip()

    print(f"  Rows: {len(df)}")

    # ---- 0. Init DB & seed modalities ----
    db.init_db()
    db.seed_modalities()
    print("  DB initialised.")

    mod_lookup = {m["code"]: m["id"] for m in db.list_modalities()}
    print(f"  Modalities seeded: {len(mod_lookup)}")

    # ---- 1. Insert Families ----
    unique_families = sorted(df["Family"].unique())
    fam_lookup: dict[str, int] = {}
    for fam_name in unique_families:
        fam_id = db.upsert_family(code=fam_name, name=fam_name, description="")
        fam_lookup[fam_name] = fam_id
    print(f"  Families inserted: {len(fam_lookup)}")

    # ---- 2. Insert Sub-Families ----
    sf_df = (
        df[["Family", "Sub Family", "Sub Family Type", "Calculation type"]]
        .drop_duplicates(["Family", "Sub Family"])
        .sort_values(["Family", "Sub Family"])
    )
    sf_lookup: dict[tuple[str, str], int] = {}
    for _, row in sf_df.iterrows():
        fam_name = row["Family"]
        sf_name = row["Sub Family"]
        sf_type = row["Sub Family Type"] if row["Sub Family Type"] in db.SUB_FAMILY_TYPES else "Normal"
        calc_type = db.calc_type_from_label(row["Calculation type"])

        sf_id = db.upsert_sub_family(
            code=sf_name,
            name=sf_name,
            family_id=fam_lookup[fam_name],
            calculation_type=calc_type,
            sub_family_type=sf_type,
        )
        sf_lookup[(fam_name, sf_name)] = sf_id
    print(f"  Sub-Families inserted: {len(sf_lookup)}")

    # ---- 3. Modality assignments ----
    sf_mod_map: dict[int, set[int]] = {}
    for _, row in df.iterrows():
        sf_id = sf_lookup.get((row["Family"], row["Sub Family"]))
        mod_id = mod_lookup.get(row["Modality Code"])
        if sf_id and mod_id:
            sf_mod_map.setdefault(sf_id, set()).add(mod_id)

    assignment_count = 0
    for sf_id, mod_ids in sf_mod_map.items():
        db.set_sub_family_modalities(sf_id, list(mod_ids))
        assignment_count += len(mod_ids)
    print(f"  Modality assignments: {assignment_count}")

    counts = db.table_counts()
    print("\n  Final table counts:")
    for table, count in counts.items():
        print(f"    {table}: {count}")
    print("\nDone!")


if __name__ == "__main__":
    xlsx = sys.argv[1] if len(sys.argv) > 1 else None
    load_spreadsheet(xlsx)
