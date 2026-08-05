from pathlib import Path

import pandas as pd
import pytest

from progression_heatmap.data import (
    RAW_REQUIRED_COLUMNS,
    DataValidationError,
    load_raw_attempts_data,
    validate_required_columns,
)

SAMPLE_DATA = Path(__file__).resolve().parents[1] / "data" / "sample_heatmap_data.csv"


def test_sample_raw_csv_loads_successfully() -> None:
    frame = load_raw_attempts_data(SAMPLE_DATA, engine="pandas")

    assert not frame.empty
    assert set(RAW_REQUIRED_COLUMNS).issubset(frame.columns)
    assert set(frame["payer_type"]) == {"nonpayer", "payer"}
    assert set(frame["platform_name"]) == {"android", "ios", "uwp"}
    assert {"organic", "paid", "crosspromo", "incent", "NULL"}.issubset(
        set(frame["traffic_type"])
    )
    assert set(frame["super_ball"]) == {False, True}


def test_sample_raw_csv_covers_databricks_safe_date_and_level_range() -> None:
    frame = load_raw_attempts_data(SAMPLE_DATA, engine="pandas")

    assert frame["level_cohort"].min() == 0
    assert frame["level_cohort"].max() == 900
    assert frame["level_cohort"].nunique() == 901
    assert frame["partition_date"].min() == pd.Timestamp("2026-01-01")
    assert frame["partition_date"].max() == pd.Timestamp("2026-02-19")
    assert frame["partition_date"].nunique() == 50


def test_required_columns_are_validated() -> None:
    columns = [
        "client_time",
        "user_id",
        "balance_id",
        "traffic_type",
        "payer_type",
        "failed",
        "attempt",
        "platform_name",
        "first_attempt",
        "FW",
        "CW",
        "CF",
        "FF",
        "reason_seg",
        "partition_date",
    ]

    with pytest.raises(DataValidationError, match=r"level_cohort|super_ball"):
        validate_required_columns(columns)
