"""CSV and Excel import/export helpers for PST master data.

Provides generic parsing and export functions used by all master data
Streamlit pages.  Handles both CSV and XLSX input, with column mapping
and validation hooks.
"""

from __future__ import annotations

import io
from typing import Any, Callable

import pandas as pd
import streamlit as st


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------

def parse_upload(uploaded_file: st.runtime.uploaded_file_manager.UploadedFile,
                 required_columns: list[str],
                 column_map: dict[str, str] | None = None,
                 ) -> tuple[pd.DataFrame | None, str | None]:
    """Parse an uploaded CSV or Excel file and validate columns.

    Parameters
    ----------
    uploaded_file : UploadedFile
        The Streamlit uploaded file object.
    required_columns : list[str]
        Column names that *must* be present (after mapping).
    column_map : dict | None
        Optional rename mapping ``{file_col: internal_col}``.

    Returns
    -------
    (DataFrame, None) on success, (None, error_message) on failure.
    """
    try:
        name = uploaded_file.name.lower()
        if name.endswith(".csv"):
            df = pd.read_csv(uploaded_file, dtype=str)
        elif name.endswith((".xlsx", ".xls")):
            df = pd.read_excel(uploaded_file, dtype=str, engine="openpyxl")
        else:
            return None, f"Unsupported file format: {uploaded_file.name}. Use CSV or XLSX."
    except Exception as exc:
        return None, f"Failed to read file: {exc}"

    # Normalise column names: strip whitespace, lowercase
    df.columns = [c.strip() for c in df.columns]

    # Apply column mapping if provided
    if column_map:
        df = df.rename(columns=column_map)

    # Strip whitespace from all string cells
    for col in df.columns:
        df[col] = df[col].fillna("").astype(str).str.strip()

    # Validate required columns
    missing = [c for c in required_columns if c not in df.columns]
    if missing:
        return None, (
            f"Missing required column(s): **{', '.join(missing)}**. "
            f"Found: {', '.join(df.columns.tolist())}"
        )

    if df.empty:
        return None, "The file is empty (no data rows found)."

    return df, None


def import_rows(
    df: pd.DataFrame,
    upsert_fn: Callable[..., int],
    row_to_kwargs: Callable[[dict[str, Any]], dict[str, Any]],
) -> tuple[int, int, list[str]]:
    """Import rows from a DataFrame using an upsert function.

    Parameters
    ----------
    df : DataFrame
        Parsed data frame.
    upsert_fn : callable
        The ``db.upsert_*`` function to call per row.
    row_to_kwargs : callable
        Converts a row dict to keyword arguments for ``upsert_fn``.

    Returns
    -------
    (inserted_count, skipped_count, list_of_errors)
    """
    inserted = 0
    skipped = 0
    errors: list[str] = []

    for idx, row in df.iterrows():
        try:
            kwargs = row_to_kwargs(row.to_dict())
            upsert_fn(**kwargs)
            inserted += 1
        except Exception as exc:
            skipped += 1
            errors.append(f"Row {idx + 2}: {exc}")  # +2 = header + 0-index

    return inserted, skipped, errors


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def to_csv_bytes(data: list[dict], columns: list[str] | None = None) -> bytes:
    """Convert a list of dicts to CSV bytes for Streamlit download.

    Parameters
    ----------
    data : list[dict]
        Row data (typically from ``db.list_*()``).
    columns : list[str] | None
        Column subset/order.  ``None`` = all keys from the first row.

    Returns
    -------
    UTF-8 encoded CSV bytes.
    """
    if not data:
        return b""
    df = pd.DataFrame(data)
    if columns:
        df = df[[c for c in columns if c in df.columns]]
    return df.to_csv(index=False).encode("utf-8")


def to_excel_bytes(data: list[dict], columns: list[str] | None = None,
                   sheet_name: str = "Data") -> bytes:
    """Convert a list of dicts to XLSX bytes for Streamlit download.

    Parameters
    ----------
    data : list[dict]
        Row data.
    columns : list[str] | None
        Column subset/order.
    sheet_name : str
        Excel sheet name.

    Returns
    -------
    XLSX file as bytes.
    """
    if not data:
        return b""
    df = pd.DataFrame(data)
    if columns:
        df = df[[c for c in columns if c in df.columns]]
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, sheet_name=sheet_name, engine="openpyxl")
    return buffer.getvalue()
