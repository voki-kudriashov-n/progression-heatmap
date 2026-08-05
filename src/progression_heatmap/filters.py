"""Filtering helpers for raw and aggregated progression heatmap data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

DateLike = str | date | datetime | pd.Timestamp
ATTEMPT_GROUP_FIRST = "1 attempt"
ATTEMPT_GROUP_REPEAT = "2+ attempts"
ATTEMPT_GROUPS = (ATTEMPT_GROUP_FIRST, ATTEMPT_GROUP_REPEAT)
SUPER_BALL_VALUES = (True, False)


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
    attempt_groups: tuple[str, ...] = ()
    super_ball_values: tuple[bool, ...] = ()


@dataclass(frozen=True, slots=True)
class DisplayFilters:
    """Filters that can be applied to already-grouped metric rows."""

    level_min: int | None = None
    level_max: int | None = None
    start_date: DateLike | None = None
    end_date: DateLike | None = None


@dataclass(frozen=True, slots=True)
class MetricSelection:
    """Selected post-aggregation metric."""

    metric_name: str
    calculation_method: str
    min_observations: int = 1000


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
    attempt_groups: tuple[str, ...]
    super_ball_values: tuple[bool, ...]


def apply_pre_aggregation_filters(frame, criteria: PreAggregationFilters):
    """Apply filters that affect grouped metric values."""

    _validate_level_range(criteria)
    if _is_spark_frame(frame):
        return _apply_pre_aggregation_filters_spark(frame, criteria)
    return _apply_pre_aggregation_filters_pandas(frame, criteria)


def apply_grouped_display_filters(frame, criteria: DisplayFilters):
    """Apply level and date filters after grouped statistics are available."""

    _validate_level_range(criteria)
    if _is_spark_frame(frame):
        return _apply_grouped_display_filters_spark(frame, criteria)
    return _apply_grouped_display_filters_pandas(frame, criteria)


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
        attempt_groups=tuple(_attempt_groups_pandas(frame)),
        super_ball_values=tuple(_super_ball_values_pandas(frame)),
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
    if _should_filter_attempt_groups(criteria.attempt_groups):
        filtered = filtered[_attempt_group_mask_pandas(filtered, criteria.attempt_groups)]
    if _should_filter_super_ball(criteria.super_ball_values):
        filtered = filtered[filtered["super_ball"].isin(criteria.super_ball_values)]

    return filtered.reset_index(drop=True)


def _apply_grouped_display_filters_pandas(
    frame: pd.DataFrame,
    criteria: DisplayFilters,
) -> pd.DataFrame:
    filtered = frame.copy()
    if filtered.empty:
        return filtered

    filtered["date"] = pd.to_datetime(filtered["date"]).dt.normalize()
    if criteria.level_min is not None:
        filtered = filtered[filtered["level_group"] >= criteria.level_min]
    if criteria.level_max is not None:
        filtered = filtered[filtered["level_group"] <= criteria.level_max]
    if criteria.start_date is not None:
        filtered = filtered[filtered["date"] >= _to_timestamp(criteria.start_date)]
    if criteria.end_date is not None:
        filtered = filtered[filtered["date"] <= _to_timestamp(criteria.end_date)]

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
    if _should_filter_attempt_groups(criteria.attempt_groups):
        conditions = []
        if ATTEMPT_GROUP_FIRST in criteria.attempt_groups:
            conditions.append(sql_functions.col("attempt") == 1)
        if ATTEMPT_GROUP_REPEAT in criteria.attempt_groups:
            conditions.append(sql_functions.col("attempt") >= 2)
        if conditions:
            attempt_condition = conditions[0]
            for condition in conditions[1:]:
                attempt_condition = attempt_condition | condition
            filtered = filtered.filter(attempt_condition)
    if _should_filter_super_ball(criteria.super_ball_values):
        filtered = filtered.filter(
            sql_functions.col("super_ball").isin(list(criteria.super_ball_values))
        )
    return filtered


def _apply_grouped_display_filters_spark(frame, criteria: DisplayFilters):
    from pyspark.sql import functions as sql_functions

    filtered = frame
    if criteria.level_min is not None:
        filtered = filtered.filter(sql_functions.col("level_group") >= criteria.level_min)
    if criteria.level_max is not None:
        filtered = filtered.filter(sql_functions.col("level_group") <= criteria.level_max)
    if criteria.start_date is not None:
        filtered = filtered.filter(
            sql_functions.col("date") >= _to_timestamp(criteria.start_date).date()
        )
    if criteria.end_date is not None:
        filtered = filtered.filter(
            sql_functions.col("date") <= _to_timestamp(criteria.end_date).date()
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
        attempt_groups=tuple(_attempt_groups_spark(frame)),
        super_ball_values=tuple(_super_ball_values_spark(frame)),
    )


def _validate_level_range(criteria: PreAggregationFilters | DisplayFilters) -> None:
    if (
        criteria.level_min is not None
        and criteria.level_max is not None
        and criteria.level_min > criteria.level_max
    ):
        msg = "level_min cannot be greater than level_max."
        raise ValueError(msg)


def _to_timestamp(value: DateLike) -> pd.Timestamp:
    return pd.Timestamp(value).normalize()


def _attempt_groups_pandas(frame: pd.DataFrame) -> list[str]:
    groups = []
    if (frame["attempt"] == 1).any():
        groups.append(ATTEMPT_GROUP_FIRST)
    if (frame["attempt"] >= 2).any():
        groups.append(ATTEMPT_GROUP_REPEAT)
    return groups


def _attempt_groups_spark(frame) -> list[str]:
    from pyspark.sql import functions as sql_functions

    row = frame.agg(
        sql_functions.max(
            sql_functions.when(sql_functions.col("attempt") == 1, 1).otherwise(0)
        ).alias("has_first"),
        sql_functions.max(
            sql_functions.when(sql_functions.col("attempt") >= 2, 1).otherwise(0)
        ).alias("has_repeat"),
    ).first()
    groups = []
    if row["has_first"]:
        groups.append(ATTEMPT_GROUP_FIRST)
    if row["has_repeat"]:
        groups.append(ATTEMPT_GROUP_REPEAT)
    return groups


def _super_ball_values_pandas(frame: pd.DataFrame) -> list[bool]:
    values = []
    if frame["super_ball"].eq(True).any():
        values.append(True)
    if frame["super_ball"].eq(False).any():
        values.append(False)
    return values


def _super_ball_values_spark(frame) -> list[bool]:
    from pyspark.sql import functions as sql_functions

    row = frame.agg(
        sql_functions.max(
            sql_functions.when(sql_functions.col("super_ball") == True, 1).otherwise(0)  # noqa: E712
        ).alias("has_true"),
        sql_functions.max(
            sql_functions.when(sql_functions.col("super_ball") == False, 1).otherwise(0)  # noqa: E712
        ).alias("has_false"),
    ).first()
    values = []
    if row["has_true"]:
        values.append(True)
    if row["has_false"]:
        values.append(False)
    return values


def _should_filter_attempt_groups(attempt_groups: tuple[str, ...]) -> bool:
    return bool(attempt_groups) and set(attempt_groups) != set(ATTEMPT_GROUPS)


def _should_filter_super_ball(super_ball_values: tuple[bool, ...]) -> bool:
    return bool(super_ball_values) and set(super_ball_values) != set(SUPER_BALL_VALUES)


def _attempt_group_mask_pandas(
    frame: pd.DataFrame,
    attempt_groups: tuple[str, ...],
) -> pd.Series:
    mask = pd.Series(False, index=frame.index)
    if ATTEMPT_GROUP_FIRST in attempt_groups:
        mask = mask | (frame["attempt"] == 1)
    if ATTEMPT_GROUP_REPEAT in attempt_groups:
        mask = mask | (frame["attempt"] >= 2)
    return mask


def _is_spark_frame(frame) -> bool:
    return frame.__class__.__module__.startswith("pyspark.sql")
