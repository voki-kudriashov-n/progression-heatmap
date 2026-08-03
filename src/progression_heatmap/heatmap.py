"""Heatmap preparation logic independent of Streamlit."""

from __future__ import annotations

import pandas as pd

HEATMAP_INDEX_COLUMNS = ("level_group", "date")


def prepare_heatmap_table(frame: pd.DataFrame, value_column: str = "value") -> pd.DataFrame:
    """Pivot filtered rows into a level_group x date table without aggregation."""

    required_columns = (*HEATMAP_INDEX_COLUMNS, value_column)
    missing_columns = sorted(set(required_columns).difference(frame.columns))
    if missing_columns:
        msg = f"Missing heatmap columns: {', '.join(missing_columns)}"
        raise ValueError(msg)

    if frame.empty:
        return pd.DataFrame()

    heatmap_input = frame.loc[:, required_columns].copy()
    heatmap_input["date"] = pd.to_datetime(heatmap_input["date"]).dt.normalize()
    heatmap_input["level_group"] = pd.to_numeric(heatmap_input["level_group"])
    heatmap_input[value_column] = pd.to_numeric(heatmap_input[value_column])

    duplicate_cells = heatmap_input.duplicated(["level_group", "date"], keep=False)
    if duplicate_cells.any():
        msg = (
            "Each heatmap cell must have exactly one value; "
            "duplicate level_group/date rows found."
        )
        raise ValueError(msg)

    heatmap_table = heatmap_input.pivot(
        index="level_group",
        columns="date",
        values=value_column,
    )
    heatmap_table = heatmap_table.sort_index(axis=0).sort_index(axis=1)
    heatmap_table.index.name = "level_group"
    heatmap_table.columns.name = "date"
    return heatmap_table


def prepare_heatmap_records(frame: pd.DataFrame) -> pd.DataFrame:
    """Return long-form records suitable for Streamlit/Altair heatmap rendering."""

    heatmap_table = prepare_heatmap_table(frame)
    if heatmap_table.empty:
        return pd.DataFrame(columns=["level_group", "date", "value"])

    records = heatmap_table.reset_index().melt(
        id_vars="level_group",
        var_name="date",
        value_name="value",
    )
    records = records.dropna(subset=["value"])
    records["date"] = pd.to_datetime(records["date"]).dt.normalize()
    records["level_group"] = records["level_group"].astype(int)
    records["value"] = records["value"].astype(float)
    return records.sort_values(["level_group", "date"], kind="stable").reset_index(drop=True)
