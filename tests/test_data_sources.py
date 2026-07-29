from pathlib import Path

import pandas as pd

from progression_heatmap.config import AppConfig, load_config
from progression_heatmap.data import RAW_REQUIRED_COLUMNS
from progression_heatmap.data_sources import (
    CsvRawAttemptsDataSource,
    SparkSqlRawAttemptsDataSource,
    SparkTableRawAttemptsDataSource,
    raw_attempts_data_source_from_config,
)
from progression_heatmap.filters import MetricSelection, PreAggregationFilters
from progression_heatmap.metrics import aggregate_statistics, select_metric_values

SAMPLE_DATA = Path(__file__).resolve().parents[1] / "data" / "sample_heatmap_data.csv"


class FakeSparkSession:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.sql_query: str | None = None
        self.table_name: str | None = None

    def sql(self, query: str) -> pd.DataFrame:
        self.sql_query = query
        return self.frame

    def table(self, table_name: str) -> pd.DataFrame:
        self.table_name = table_name
        return self.frame


def test_csv_data_source_feeds_metric_pipeline() -> None:
    frame = CsvRawAttemptsDataSource(SAMPLE_DATA, engine="pandas").load_raw_attempts()
    statistics = aggregate_statistics(frame, PreAggregationFilters(level_min=0, level_max=2))
    metric_values = select_metric_values(
        statistics,
        MetricSelection(metric_name="fail_rate", calculation_method="relative"),
    )

    assert not metric_values.empty
    assert list(metric_values.columns) == [
        "level_group",
        "date",
        "value",
        "metric_name",
        "calculation_method",
    ]


def test_config_factory_builds_csv_data_source() -> None:
    config = AppConfig(
        environment="dev",
        data_source="csv",
        app_title="Test",
        data_path=SAMPLE_DATA,
    )

    source = raw_attempts_data_source_from_config(config)

    assert isinstance(source, CsvRawAttemptsDataSource)
    assert source.path == SAMPLE_DATA


def test_load_config_supports_spark_sql_source(tmp_path: Path) -> None:
    config_path = tmp_path / "spark.toml"
    config_path.write_text(
        """
        environment = "dev"
        data_source = "spark_sql"
        spark_sql = "select * from raw_attempts"
        app_title = "Spark Source"
        """,
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.data_source == "spark_sql"
    assert config.data_path is None
    assert config.spark_sql == "select * from raw_attempts"


def test_spark_sql_data_source_uses_query_and_raw_contract() -> None:
    spark = FakeSparkSession(_raw_attempts_frame())
    source = SparkSqlRawAttemptsDataSource(
        "select * from raw_attempts",
        spark_session=spark,
    )

    frame = source.load_raw_attempts()

    assert spark.sql_query == "select * from raw_attempts"
    assert list(frame.columns) == list(RAW_REQUIRED_COLUMNS)
    assert "extra_column" not in frame.columns


def test_spark_table_data_source_uses_table_name_and_raw_contract() -> None:
    spark = FakeSparkSession(_raw_attempts_frame())
    source = SparkTableRawAttemptsDataSource("catalog.schema.raw_attempts", spark_session=spark)

    frame = source.load_raw_attempts()

    assert spark.table_name == "catalog.schema.raw_attempts"
    assert list(frame.columns) == list(RAW_REQUIRED_COLUMNS)
    assert "extra_column" not in frame.columns


def _raw_attempts_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "client_time": ["2026-01-01 00:00:00"],
            "user_id": ["u1"],
            "balance_id": [1],
            "traffic_type": ["organic"],
            "payer_type": ["payer"],
            "failed": [1],
            "attempt": [2],
            "platform_name": ["ios"],
            "first_attempt": [0],
            "FW": [0],
            "CW": [0],
            "CF": [1],
            "FF": [0],
            "reason_seg": ["close_fail"],
            "partition_date": ["2026-01-01"],
            "level_cohort": [10],
            "extra_column": ["ignored"],
        }
    )
