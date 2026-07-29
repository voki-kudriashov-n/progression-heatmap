from pathlib import Path

import pandas as pd
import pytest

from progression_heatmap.data import load_raw_attempts_data
from progression_heatmap.filters import (
    MetricSelection,
    PreAggregationFilters,
    apply_pre_aggregation_filters,
    collect_raw_filter_options,
)

SAMPLE_DATA = Path(__file__).resolve().parents[1] / "data" / "sample_heatmap_data.csv"


@pytest.fixture
def sample_frame() -> pd.DataFrame:
    return load_raw_attempts_data(SAMPLE_DATA, engine="pandas")


def test_level_range_filter(sample_frame: pd.DataFrame) -> None:
    filtered = apply_pre_aggregation_filters(
        sample_frame,
        PreAggregationFilters(level_min=20, level_max=40),
    )

    assert not filtered.empty
    assert filtered["level_cohort"].min() >= 20
    assert filtered["level_cohort"].max() <= 40


def test_date_range_filter(sample_frame: pd.DataFrame) -> None:
    filtered = apply_pre_aggregation_filters(
        sample_frame,
        PreAggregationFilters(start_date="2026-02-01", end_date="2026-04-01"),
    )

    assert not filtered.empty
    assert filtered["partition_date"].min() >= pd.Timestamp("2026-02-01")
    assert filtered["partition_date"].max() <= pd.Timestamp("2026-04-01")


def test_payer_type_filter(sample_frame: pd.DataFrame) -> None:
    filtered = apply_pre_aggregation_filters(
        sample_frame,
        PreAggregationFilters(payer_types=("payer",)),
    )

    assert not filtered.empty
    assert set(filtered["payer_type"]) == {"payer"}


def test_traffic_type_filter(sample_frame: pd.DataFrame) -> None:
    filtered = apply_pre_aggregation_filters(
        sample_frame,
        PreAggregationFilters(traffic_types=("organic", "paid")),
    )

    assert not filtered.empty
    assert set(filtered["traffic_type"]).issubset({"organic", "paid"})


def test_platform_name_filter(sample_frame: pd.DataFrame) -> None:
    filtered = apply_pre_aggregation_filters(
        sample_frame,
        PreAggregationFilters(platform_names=("android",)),
    )

    assert not filtered.empty
    assert set(filtered["platform_name"]) == {"android"}


def test_raw_filter_options(sample_frame: pd.DataFrame) -> None:
    options = collect_raw_filter_options(sample_frame)

    assert options.level_min == 0
    assert options.level_max == 900
    assert options.date_min.isoformat() == "2026-01-01"
    assert options.date_max.isoformat() == "2026-02-19"
    assert "payer" in options.payer_types
    assert "organic" in options.traffic_types
    assert "android" in options.platform_names


def test_metric_selection_requires_supported_values() -> None:
    selection = MetricSelection(metric_name="CF", calculation_method="relative")

    assert selection.metric_name == "CF"
    assert selection.calculation_method == "relative"
