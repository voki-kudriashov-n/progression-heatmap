"""Raw attempt data source adapters.

Each adapter returns the same raw attempts dataframe contract. Processing modules can
therefore stay independent from whether rows came from a local CSV or a Spark table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from progression_heatmap.config import AppConfig
from progression_heatmap.data import (
    DataEngine,
    load_raw_attempts_data,
    select_raw_attempt_columns,
)


class RawAttemptsDataSource(Protocol):
    """Loads raw attempt-level rows for the analytics pipeline."""

    def load_raw_attempts(self):
        """Return pandas or Spark dataframe rows matching the raw attempts schema."""


@dataclass(frozen=True, slots=True)
class CsvRawAttemptsDataSource:
    """Local CSV adapter used by development and tests."""

    path: Path
    engine: DataEngine = "auto"

    def load_raw_attempts(self):
        return load_raw_attempts_data(self.path, engine=self.engine)


@dataclass(frozen=True, slots=True)
class SparkSqlRawAttemptsDataSource:
    """Spark SQL adapter intended for Databricks App usage."""

    query: str
    spark_session: Any | None = field(default=None, repr=False, compare=False)

    def load_raw_attempts(self):
        spark = _get_spark_session(self.spark_session)
        return select_raw_attempt_columns(spark.sql(self.query))


@dataclass(frozen=True, slots=True)
class SparkTableRawAttemptsDataSource:
    """Spark table adapter for sources that already expose the required raw columns."""

    table_name: str
    spark_session: Any | None = field(default=None, repr=False, compare=False)

    def load_raw_attempts(self):
        spark = _get_spark_session(self.spark_session)
        return select_raw_attempt_columns(spark.table(self.table_name))


def raw_attempts_data_source_from_config(config: AppConfig) -> RawAttemptsDataSource:
    """Build the configured raw attempts data source."""

    if config.data_source == "csv":
        if config.data_path is None:
            msg = "CSV data_source requires data_path."
            raise ValueError(msg)
        return CsvRawAttemptsDataSource(config.data_path)

    if config.data_source == "spark_sql":
        if config.spark_sql is None:
            msg = "spark_sql data_source requires spark_sql."
            raise ValueError(msg)
        return SparkSqlRawAttemptsDataSource(config.spark_sql)

    if config.data_source == "spark_table":
        if config.spark_table is None:
            msg = "spark_table data_source requires spark_table."
            raise ValueError(msg)
        return SparkTableRawAttemptsDataSource(config.spark_table)

    msg = f"Unsupported data_source: {config.data_source!r}"
    raise ValueError(msg)


def load_raw_attempts_from_config(config: AppConfig):
    """Load raw attempts through the data source configured for this app run."""

    return raw_attempts_data_source_from_config(config).load_raw_attempts()


def _get_spark_session(spark_session: Any | None):
    if spark_session is not None:
        return spark_session

    from pyspark.sql import SparkSession

    active_session = SparkSession.getActiveSession()
    if active_session is not None:
        return active_session
    return SparkSession.builder.getOrCreate()
