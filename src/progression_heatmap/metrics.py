"""Spark-compatible grouped metric calculations for the heatmap."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from progression_heatmap.filters import (
    MetricSelection,
    PreAggregationFilters,
    apply_pre_aggregation_filters,
)


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    """A selectable metric backed by a precomputed grouped statistic column."""

    metric_name: str
    calculation_method: str
    column_name: str
    value_count_column: str | None = None
    sample_count_column: str | None = None

    @property
    def is_percentage(self) -> bool:
        """Return whether this metric is a percentage derived from a sample count."""

        return self.calculation_method in {"relative", "partial_relative"}


METRIC_DEFINITIONS = (
    MetricDefinition("CF", "absolute", "CF_absolute", "CF_absolute", "attempts_absolute"),
    MetricDefinition("CW", "absolute", "CW_absolute", "CW_absolute", "attempts_absolute"),
    MetricDefinition("FF", "absolute", "FF_absolute", "FF_absolute", "attempts_absolute"),
    MetricDefinition("FW", "absolute", "FW_absolute", "FW_absolute", "attempts_absolute"),
    MetricDefinition("CF", "relative", "CF_relative", "CF_absolute", "attempts_absolute"),
    MetricDefinition("CW", "relative", "CW_relative", "CW_absolute", "attempts_absolute"),
    MetricDefinition("FF", "relative", "FF_relative", "FF_absolute", "attempts_absolute"),
    MetricDefinition("FW", "relative", "FW_relative", "FW_absolute", "attempts_absolute"),
    MetricDefinition(
        "CF",
        "partial_relative",
        "CF_partial_relative",
        "CF_absolute",
        "fails_absolute",
    ),
    MetricDefinition(
        "CW",
        "partial_relative",
        "CW_partial_relative",
        "CW_absolute",
        "wins_absolute",
    ),
    MetricDefinition(
        "FF",
        "partial_relative",
        "FF_partial_relative",
        "FF_absolute",
        "fails_absolute",
    ),
    MetricDefinition(
        "FW",
        "partial_relative",
        "FW_partial_relative",
        "FW_absolute",
        "wins_absolute",
    ),
    MetricDefinition(
        "attempts",
        "absolute",
        "attempts_absolute",
        "attempts_absolute",
        "attempts_absolute",
    ),
    MetricDefinition("attempt", "average", "attempt_average", None, "attempts_absolute"),
    MetricDefinition(
        "failed",
        "absolute",
        "failed_absolute",
        "failed_absolute",
        "attempts_absolute",
    ),
    MetricDefinition("wins", "absolute", "wins_absolute", "wins_absolute", "attempts_absolute"),
    MetricDefinition(
        "fail_rate",
        "relative",
        "fail_rate_relative",
        "failed_absolute",
        "attempts_absolute",
    ),
    MetricDefinition(
        "win_rate",
        "relative",
        "win_rate_relative",
        "wins_absolute",
        "attempts_absolute",
    ),
    MetricDefinition(
        "first_attempt",
        "absolute",
        "first_attempt_absolute",
        "first_attempt_absolute",
        "attempts_absolute",
    ),
    MetricDefinition(
        "first_attempt",
        "relative",
        "first_attempt_relative",
        "first_attempt_absolute",
        "attempts_absolute",
    ),
)


def aggregate_statistics(frame, criteria: PreAggregationFilters):
    """Apply pre-group filters and calculate all grouped statistics."""

    filtered = apply_pre_aggregation_filters(frame, criteria)
    if _is_spark_frame(filtered):
        return _aggregate_statistics_spark(filtered)
    return _aggregate_statistics_pandas(filtered)


def select_metric_values(statistics_frame, selection: MetricSelection):
    """Select one metric from precomputed grouped statistics as heatmap values."""

    selected = select_metric_values_with_context(statistics_frame, selection)
    if _is_spark_frame(selected):
        return selected.select("level_group", "date", "value", "metric_name", "calculation_method")
    return selected.loc[:, ["level_group", "date", "value", "metric_name", "calculation_method"]]


def select_metric_values_with_context(statistics_frame, selection: MetricSelection):
    """Select one metric and keep counts used for hover and reliability shading."""

    metric = get_metric_definition(selection.metric_name, selection.calculation_method)
    if _is_spark_frame(statistics_frame):
        return _select_metric_values_with_context_spark(statistics_frame, metric, selection)
    return _select_metric_values_with_context_pandas(statistics_frame, metric, selection)


def metric_names() -> list[str]:
    """Return available metric names in stable UI order."""

    seen = []
    for definition in METRIC_DEFINITIONS:
        if definition.metric_name not in seen:
            seen.append(definition.metric_name)
    return seen


def calculation_methods_for_metric(metric_name: str) -> list[str]:
    """Return available calculation methods for one metric."""

    return [
        definition.calculation_method
        for definition in METRIC_DEFINITIONS
        if definition.metric_name == metric_name
    ]


def get_metric_definition(metric_name: str, calculation_method: str) -> MetricDefinition:
    """Look up the grouped statistic backing a metric selection."""

    for definition in METRIC_DEFINITIONS:
        if (
            definition.metric_name == metric_name
            and definition.calculation_method == calculation_method
        ):
            return definition
    msg = f"Unsupported metric selection: {metric_name!r} / {calculation_method!r}"
    raise ValueError(msg)


def to_pandas_frame(frame) -> pd.DataFrame:
    """Convert Spark or pandas dataframes to a pandas dataframe for rendering."""

    if _is_spark_frame(frame):
        return frame.toPandas()
    return frame.copy()


def _aggregate_statistics_pandas(frame: pd.DataFrame) -> pd.DataFrame:
    grouped = (
        frame.groupby(["level_cohort", "partition_date"], as_index=False)
        .agg(
            FW_absolute=("FW", "sum"),
            CW_absolute=("CW", "sum"),
            CF_absolute=("CF", "sum"),
            FF_absolute=("FF", "sum"),
            attempts_absolute=("user_id", "size"),
            failed_absolute=("failed", "sum"),
            attempt_average=("attempt", "mean"),
            first_attempt_absolute=("first_attempt", "sum"),
        )
        .rename(columns={"level_cohort": "level_group", "partition_date": "date"})
    )
    return _add_derived_statistics_pandas(grouped)


def _aggregate_statistics_spark(frame):
    from pyspark.sql import functions as sql_functions

    grouped = frame.groupBy("level_cohort", "partition_date").agg(
        sql_functions.sum("FW").cast("double").alias("FW_absolute"),
        sql_functions.sum("CW").cast("double").alias("CW_absolute"),
        sql_functions.sum("CF").cast("double").alias("CF_absolute"),
        sql_functions.sum("FF").cast("double").alias("FF_absolute"),
        sql_functions.count("*").cast("double").alias("attempts_absolute"),
        sql_functions.sum("failed").cast("double").alias("failed_absolute"),
        sql_functions.avg("attempt").cast("double").alias("attempt_average"),
        sql_functions.sum("first_attempt").cast("double").alias("first_attempt_absolute"),
    )
    grouped = grouped.select(
        sql_functions.col("level_cohort").alias("level_group"),
        sql_functions.col("partition_date").alias("date"),
        "*",
    ).drop("level_cohort", "partition_date")
    return _add_derived_statistics_spark(grouped)


def _add_derived_statistics_pandas(frame: pd.DataFrame) -> pd.DataFrame:
    statistics = frame.copy()
    attempts = statistics["attempts_absolute"]
    statistics["wins_absolute"] = statistics["FW_absolute"] + statistics["CW_absolute"]
    statistics["fails_absolute"] = statistics["FF_absolute"] + statistics["CF_absolute"]
    wins = statistics["wins_absolute"]
    fails = statistics["fails_absolute"]

    for metric_name in ("FW", "CW", "CF", "FF"):
        statistics[f"{metric_name}_relative"] = _safe_percent_pandas(
            statistics[f"{metric_name}_absolute"],
            attempts,
        )

    statistics["FW_partial_relative"] = _safe_percent_pandas(statistics["FW_absolute"], wins)
    statistics["CW_partial_relative"] = _safe_percent_pandas(statistics["CW_absolute"], wins)
    statistics["FF_partial_relative"] = _safe_percent_pandas(statistics["FF_absolute"], fails)
    statistics["CF_partial_relative"] = _safe_percent_pandas(statistics["CF_absolute"], fails)
    statistics["fail_rate_relative"] = _safe_percent_pandas(
        statistics["failed_absolute"],
        attempts,
    )
    statistics["win_rate_relative"] = 100 - statistics["fail_rate_relative"]
    statistics["first_attempt_relative"] = _safe_percent_pandas(
        statistics["first_attempt_absolute"],
        attempts,
    )

    numeric_columns = _numeric_statistic_columns()
    statistics[numeric_columns] = statistics[numeric_columns].astype(float)
    statistics["level_group"] = statistics["level_group"].astype(int)
    statistics["date"] = pd.to_datetime(statistics["date"]).dt.normalize()
    return statistics.sort_values(["level_group", "date"], kind="stable").reset_index(drop=True)


def _add_derived_statistics_spark(frame):
    from pyspark.sql import functions as sql_functions

    attempts = sql_functions.col("attempts_absolute")
    statistics = frame.withColumn(
        "wins_absolute",
        sql_functions.col("FW_absolute") + sql_functions.col("CW_absolute"),
    ).withColumn(
        "fails_absolute",
        sql_functions.col("FF_absolute") + sql_functions.col("CF_absolute"),
    )
    wins = sql_functions.col("wins_absolute")
    fails = sql_functions.col("fails_absolute")
    for metric_name in ("FW", "CW", "CF", "FF"):
        statistics = statistics.withColumn(
            f"{metric_name}_relative",
            _safe_percent_spark(sql_functions.col(f"{metric_name}_absolute"), attempts),
        )

    return (
        statistics.withColumn(
            "FW_partial_relative",
            _safe_percent_spark(sql_functions.col("FW_absolute"), wins),
        )
        .withColumn(
            "CW_partial_relative",
            _safe_percent_spark(sql_functions.col("CW_absolute"), wins),
        )
        .withColumn(
            "FF_partial_relative",
            _safe_percent_spark(sql_functions.col("FF_absolute"), fails),
        )
        .withColumn(
            "CF_partial_relative",
            _safe_percent_spark(sql_functions.col("CF_absolute"), fails),
        )
        .withColumn(
            "fail_rate_relative",
            _safe_percent_spark(sql_functions.col("failed_absolute"), attempts),
        )
        .withColumn("win_rate_relative", 100 - sql_functions.col("fail_rate_relative"))
        .withColumn(
            "first_attempt_relative",
            _safe_percent_spark(sql_functions.col("first_attempt_absolute"), attempts),
        )
        .orderBy("level_group", "date")
    )


def _select_metric_values_with_context_pandas(
    statistics_frame: pd.DataFrame,
    metric: MetricDefinition,
    selection: MetricSelection,
) -> pd.DataFrame:
    selected = statistics_frame.loc[:, ["level_group", "date", metric.column_name]].copy()
    selected = selected.rename(columns={metric.column_name: "value"})
    selected["metric_name"] = metric.metric_name
    selected["calculation_method"] = metric.calculation_method
    selected["value_count"] = _metric_context_column_pandas(
        statistics_frame,
        metric.value_count_column,
        selected["value"],
    )
    selected["sample_count"] = _metric_context_column_pandas(
        statistics_frame,
        metric.sample_count_column,
        pd.Series(0, index=statistics_frame.index),
    )
    selected["is_low_sample"] = (
        metric.is_percentage
        & (selected["sample_count"] < selection.min_observations)
    )
    selected["date"] = pd.to_datetime(selected["date"]).dt.normalize()
    selected["value"] = selected["value"].astype(float)
    selected["value_count"] = selected["value_count"].astype(float)
    selected["sample_count"] = selected["sample_count"].astype(float)
    return selected.loc[
        :,
        [
            "level_group",
            "date",
            "value",
            "metric_name",
            "calculation_method",
            "value_count",
            "sample_count",
            "is_low_sample",
        ],
    ]


def _select_metric_values_with_context_spark(
    statistics_frame,
    metric: MetricDefinition,
    selection: MetricSelection,
):
    from pyspark.sql import functions as sql_functions

    value_count = _metric_context_column_spark(
        metric.value_count_column,
        sql_functions.col(metric.column_name),
    )
    sample_count = _metric_context_column_spark(
        metric.sample_count_column,
        sql_functions.lit(0.0),
    )
    return statistics_frame.select(
        sql_functions.col("level_group").cast("int").alias("level_group"),
        sql_functions.col("date").alias("date"),
        sql_functions.col(metric.column_name).cast("double").alias("value"),
        sql_functions.lit(metric.metric_name).alias("metric_name"),
        sql_functions.lit(metric.calculation_method).alias("calculation_method"),
        value_count.cast("double").alias("value_count"),
        sample_count.cast("double").alias("sample_count"),
        (
            sql_functions.lit(metric.is_percentage)
            & (sample_count < sql_functions.lit(selection.min_observations))
        ).alias("is_low_sample"),
    )


def _metric_context_column_pandas(
    statistics_frame: pd.DataFrame,
    column_name: str | None,
    default: pd.Series,
) -> pd.Series:
    if column_name is None:
        return default
    return statistics_frame[column_name]


def _metric_context_column_spark(column_name: str | None, default):
    from pyspark.sql import functions as sql_functions

    if column_name is None:
        return default
    return sql_functions.col(column_name)


def _numeric_statistic_columns() -> list[str]:
    columns = {"wins_absolute", "fails_absolute"}
    for definition in METRIC_DEFINITIONS:
        columns.add(definition.column_name)
        if definition.value_count_column is not None:
            columns.add(definition.value_count_column)
        if definition.sample_count_column is not None:
            columns.add(definition.sample_count_column)
    return sorted(columns)


def _safe_percent_pandas(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator.div(denominator.where(denominator != 0)).mul(100).fillna(0)


def _safe_percent_spark(numerator, denominator):
    from pyspark.sql import functions as sql_functions

    return sql_functions.when(denominator != 0, numerator / denominator * 100).otherwise(0.0)


def _is_spark_frame(frame) -> bool:
    return frame.__class__.__module__.startswith("pyspark.sql")
