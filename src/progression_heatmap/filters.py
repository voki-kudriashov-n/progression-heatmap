"""Filtering helpers for raw and aggregated progression heatmap data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

type DateLike = str | date | datetime | pd.Timestamp


@dataclass(frozen=True, slots=True)
class PreAggregationFilters:
    """Filters that must be applied before grouping raw attempt rows."""

    level_min: int | None = None
    level_max: int | None = None
    start_date: DateLike | None = None
    end_date: DateLike | None = None
    payer_types: tuple[str, ...] = ()
    traffic_types: tuple[str, ...] = ()
    platform_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MetricSelection:
    """Selected post-aggregation metric."""

    metric_name: str
    calculation_method: str


@dataclass(frozen=True, slots=True)
class RawFilterOptions:
    """Available values and bounds for raw-data filters."""

    level_min: int
    level_max: int
    date_min: date
    date_max: date
    payer_types: tuple[str, ...]
    traffic_types: tuple[str, ...]
    platform_names: tuple[str, ...]


def apply_pre_aggregation_filters(frame, criteria: PreAggregationFilters):
    """Apply filters that affect grouped metric values."""

    _validate_level_range(criteria)
    if _is_spark_frame(frame):
        return _apply_pre_aggregation_filters_spark(frame, criteria)
    return _apply_pre_aggregation_filters_pandas(frame, criteria)


def collect_raw_filter_options(frame) -> RawFilterOptions:
    """Collect filter bounds and distinct option values from raw source data."""

    if _is_spark_frame(frame):
        return _collect_raw_filter_options_spark(frame)
    return RawFilterOptions(
        level_min=int(frame["level_cohort"].min()),
        level_max=int(frame["level_cohort"].max()),
        date_min=pd.to_datetime(frame["partition_date"]).dt.date.min(),
        date_max=pd.to_datetime(frame["partition_date"]).dt.date.max(),
        payer_types=tuple(sorted_unique_values(frame, "payer_type")),
        traffic_types=tuple(sorted_unique_values(frame, "traffic_type")),
        platform_names=tuple(sorted_unique_values(frame, "platform_name")),
    )


def sorted_unique_values(frame, column: str) -> list[str]:
    """Return sorted non-empty unique string values for a dataframe column."""

    if _is_spark_frame(frame):
        rows = frame.select(column).distinct().dropna().orderBy(column).collect()
        return [row[column] for row in rows]
    return sorted(frame[column].dropna().astype(str).unique().tolist())


def _apply_pre_aggregation_filters_pandas(
    frame: pd.DataFrame,
    criteria: PreAggregationFilters,
) -> pd.DataFrame:
    filtered = frame.copy()

    if criteria.level_min is not None:
        filtered = filtered[filtered["level_cohort"] >= criteria.level_min]
    if criteria.level_max is not None:
        filtered = filtered[filtered["level_cohort"] <= criteria.level_max]
    if criteria.start_date is not None:
        filtered = filtered[filtered["partition_date"] >= _to_timestamp(criteria.start_date)]
    if criteria.end_date is not None:
        filtered = filtered[filtered["partition_date"] <= _to_timestamp(criteria.end_date)]
    if criteria.payer_types:
        filtered = filtered[filtered["payer_type"].isin(criteria.payer_types)]
    if criteria.traffic_types:
        filtered = filtered[filtered["traffic_type"].isin(criteria.traffic_types)]
    if criteria.platform_names:
        filtered = filtered[filtered["platform_name"].isin(criteria.platform_names)]

    return filtered.reset_index(drop=True)


def _apply_pre_aggregation_filters_spark(frame, criteria: PreAggregationFilters):
    from pyspark.sql import functions as sql_functions

    filtered = frame
    if criteria.level_min is not None:
        filtered = filtered.filter(sql_functions.col("level_cohort") >= criteria.level_min)
    if criteria.level_max is not None:
        filtered = filtered.filter(sql_functions.col("level_cohort") <= criteria.level_max)
    if criteria.start_date is not None:
        filtered = filtered.filter(
            sql_functions.col("partition_date") >= _to_timestamp(criteria.start_date).date()
        )
    if criteria.end_date is not None:
        filtered = filtered.filter(
            sql_functions.col("partition_date") <= _to_timestamp(criteria.end_date).date()
        )
    if criteria.payer_types:
        filtered = filtered.filter(sql_functions.col("payer_type").isin(list(criteria.payer_types)))
    if criteria.traffic_types:
        filtered = filtered.filter(
            sql_functions.col("traffic_type").isin(list(criteria.traffic_types))
        )
    if criteria.platform_names:
        filtered = filtered.filter(
            sql_functions.col("platform_name").isin(list(criteria.platform_names))
        )
    return filtered


def _collect_raw_filter_options_spark(frame) -> RawFilterOptions:
    from pyspark.sql import functions as sql_functions

    bounds = frame.agg(
        sql_functions.min("level_cohort").alias("level_min"),
        sql_functions.max("level_cohort").alias("level_max"),
        sql_functions.min("partition_date").alias("date_min"),
        sql_functions.max("partition_date").alias("date_max"),
    ).first()
    return RawFilterOptions(
        level_min=int(bounds["level_min"]),
        level_max=int(bounds["level_max"]),
        date_min=bounds["date_min"],
        date_max=bounds["date_max"],
        payer_types=tuple(sorted_unique_values(frame, "payer_type")),
        traffic_types=tuple(sorted_unique_values(frame, "traffic_type")),
        platform_names=tuple(sorted_unique_values(frame, "platform_name")),
    )


def _validate_level_range(criteria: PreAggregationFilters) -> None:
    if (
        criteria.level_min is not None
        and criteria.level_max is not None
        and criteria.level_min > criteria.level_max
    ):
        msg = "level_min cannot be greater than level_max."
        raise ValueError(msg)


def _to_timestamp(value: DateLike) -> pd.Timestamp:
    return pd.Timestamp(value).normalize()


def _is_spark_frame(frame) -> bool:
    return frame.__class__.__module__.startswith("pyspark.sql")

