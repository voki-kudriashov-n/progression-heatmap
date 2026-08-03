from pathlib import Path

import pandas as pd
import pytest

from progression_heatmap.data import load_raw_attempts_data
from progression_heatmap.filters import MetricSelection, PreAggregationFilters
from progression_heatmap.heatmap import prepare_heatmap_records, prepare_heatmap_table
from progression_heatmap.metrics import (
    aggregate_statistics,
    select_metric_values,
    select_metric_values_with_context,
)

SAMPLE_DATA = Path(__file__).resolve().parents[1] / "data" / "sample_heatmap_data.csv"


def test_grouped_metric_values_return_non_empty_table_for_sample_data() -> None:
    frame = load_raw_attempts_data(SAMPLE_DATA, engine="pandas")
    statistics = aggregate_statistics(
        frame,
        PreAggregationFilters(level_min=0, level_max=20),
    )
    metric_values = select_metric_values(
        statistics,
        MetricSelection(metric_name="CF", calculation_method="absolute"),
    )

    heatmap_table = prepare_heatmap_table(metric_values)

    assert not heatmap_table.empty
    assert heatmap_table.index.name == "level_group"
    assert heatmap_table.columns.name == "date"
    assert len(heatmap_table.index) == 21
    assert len(heatmap_table.columns) == 50


def test_grouped_metric_values_cover_full_sample_grid() -> None:
    frame = load_raw_attempts_data(SAMPLE_DATA, engine="pandas")
    statistics = aggregate_statistics(
        frame,
        PreAggregationFilters(),
    )
    metric_values = select_metric_values(
        statistics,
        MetricSelection(metric_name="fail_rate", calculation_method="relative"),
    )

    heatmap_table = prepare_heatmap_table(metric_values)

    assert heatmap_table.shape == (901, 50)
    assert heatmap_table.notna().all().all()


def test_grouped_metric_values_return_level_group_date_value_records() -> None:
    frame = load_raw_attempts_data(SAMPLE_DATA, engine="pandas")
    statistics = aggregate_statistics(
        frame,
        PreAggregationFilters(level_min=10, level_max=12),
    )
    metric_values = select_metric_values(
        statistics,
        MetricSelection(metric_name="first_attempt", calculation_method="relative"),
    )

    records = prepare_heatmap_records(metric_values)

    assert not records.empty
    assert list(records.columns) == ["level_group", "date", "value"]
    assert pd.api.types.is_integer_dtype(records["level_group"])
    assert pd.api.types.is_datetime64_any_dtype(records["date"])
    assert pd.api.types.is_float_dtype(records["value"])
    assert records.groupby(["level_group", "date"]).size().max() == 1


def test_grouped_metrics_use_expected_calculations() -> None:
    frame = pd.DataFrame(
        {
            "client_time": pd.to_datetime(
                ["2026-01-01 00:00:00", "2026-01-01 01:00:00", "2026-01-01 02:00:00"]
            ),
            "user_id": ["u1", "u2", "u3"],
            "balance_id": [1, 2, 3],
            "traffic_type": ["organic", "organic", "paid"],
            "payer_type": ["nonpayer", "payer", "payer"],
            "failed": [1, 0, 1],
            "attempt": [1, 2, 3],
            "platform_name": ["android", "android", "ios"],
            "first_attempt": [1, 0, 0],
            "FW": [0, 1, 0],
            "CW": [0, 0, 0],
            "CF": [1, 0, 1],
            "FF": [0, 0, 0],
            "reason_seg": ["close_fail", "far_win", "close_fail"],
            "partition_date": pd.to_datetime(["2026-01-01"] * 3),
            "level_cohort": [10, 10, 10],
        }
    )

    statistics = aggregate_statistics(frame, PreAggregationFilters())
    row = statistics.iloc[0]

    assert row["attempts_absolute"] == 3
    assert row["wins_absolute"] == 1
    assert row["fails_absolute"] == 2
    assert row["CF_absolute"] == 2
    assert row["CF_relative"] == pytest.approx(2 / 3 * 100)
    assert row["CF_partial_relative"] == 100
    assert row["failed_absolute"] == 2
    assert row["fail_rate_relative"] == pytest.approx(2 / 3 * 100)
    assert row["win_rate_relative"] == pytest.approx(1 / 3 * 100)
    assert row["attempt_average"] == 2
    assert row["first_attempt_absolute"] == 1
    assert row["first_attempt_relative"] == pytest.approx(1 / 3 * 100)


def test_wins_absolute_metric_is_selectable() -> None:
    frame = load_raw_attempts_data(SAMPLE_DATA, engine="pandas")
    statistics = aggregate_statistics(
        frame,
        PreAggregationFilters(level_min=0, level_max=2),
    )

    metric_values = select_metric_values(
        statistics,
        MetricSelection(metric_name="wins", calculation_method="absolute"),
    )

    assert not metric_values.empty
    assert metric_values["value"].ge(0).all()
    assert set(metric_values["metric_name"]) == {"wins"}


def test_percentage_metric_values_include_context_and_low_sample_flag() -> None:
    frame = load_raw_attempts_data(SAMPLE_DATA, engine="pandas")
    statistics = aggregate_statistics(
        frame,
        PreAggregationFilters(level_min=0, level_max=0),
    )

    metric_values = select_metric_values_with_context(
        statistics,
        MetricSelection(
            metric_name="fail_rate",
            calculation_method="relative",
            min_observations=1000,
        ),
    )

    assert {"value_count", "sample_count", "is_low_sample"}.issubset(metric_values.columns)
    expected = statistics.loc[:, ["failed_absolute", "attempts_absolute"]].reset_index(drop=True)
    assert metric_values["value_count"].equals(expected["failed_absolute"].astype(float))
    assert metric_values["sample_count"].equals(expected["attempts_absolute"].astype(float))
    assert metric_values["is_low_sample"].all()


def test_heatmap_preparation_rejects_duplicate_cell_values() -> None:
    frame = pd.DataFrame(
        {
            "level_group": [10, 10],
            "date": [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-01")],
            "value": [1.0, 2.0],
        }
    )

    with pytest.raises(ValueError, match="exactly one value"):
        prepare_heatmap_table(frame)
