from pathlib import Path

import pandas as pd

from progression_heatmap.config import AppConfig, ProjectConfig, load_config
from progression_heatmap.data import RAW_REQUIRED_COLUMNS
from progression_heatmap.data_sources import (
    CsvRawAttemptsDataSource,
    DatabricksDataAccessError,
    DatabricksSqlWarehouseRawAttemptsDataSource,
    SparkSqlRawAttemptsDataSource,
    SparkTableRawAttemptsDataSource,
    load_raw_attempts_from_config,
    raw_attempts_data_source_from_config,
    resolve_data_source,
)
from progression_heatmap.filters import MetricSelection, PreAggregationFilters
from progression_heatmap.metrics import aggregate_statistics, select_metric_values

SAMPLE_DATA = Path(__file__).resolve().parents[1] / "data" / "sample_heatmap_data.csv"
MM_TABLE = "game_data_prod.analytics_voki.raw_objects_mm"
MYM_TABLE = "game_data_prod.analytics_voki.raw_objects_mym"


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


class FakeSqlConnectionFactory:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.kwargs = {}
        self.query: str | None = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return FakeSqlConnection(self)


class FakeSqlConnection:
    def __init__(self, factory: FakeSqlConnectionFactory) -> None:
        self.factory = factory

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def cursor(self):
        return FakeSqlCursor(self.factory)


class FakeSqlCursor:
    def __init__(self, factory: FakeSqlConnectionFactory) -> None:
        self.factory = factory
        self.description = [(column,) for column in factory.frame.columns]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def execute(self, query: str) -> None:
        self.factory.query = query

    def fetchall(self):
        return list(self.factory.frame.itertuples(index=False, name=None))


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


def test_auto_data_source_uses_csv_outside_databricks(monkeypatch) -> None:
    monkeypatch.delenv("DATABRICKS_APP_NAME", raising=False)
    monkeypatch.delenv("DATABRICKS_APP_URL", raising=False)
    config = _project_config(data_source="auto")

    source = raw_attempts_data_source_from_config(config, "MM")

    assert resolve_data_source(config) == "csv"
    assert isinstance(source, CsvRawAttemptsDataSource)
    assert source.path == SAMPLE_DATA


def test_auto_data_source_uses_databricks_sql_inside_databricks(monkeypatch) -> None:
    monkeypatch.setenv("DATABRICKS_APP_NAME", "progression-heatmap")
    monkeypatch.setenv("DATABRICKS_WAREHOUSE_ID", "warehouse-123")
    monkeypatch.setenv("DATABRICKS_HOST", "example.cloud.databricks.com")
    monkeypatch.setenv("DATABRICKS_CLIENT_ID", "client-id")
    monkeypatch.setenv("DATABRICKS_CLIENT_SECRET", "client-secret")
    config = _project_config(data_source="auto")

    source = raw_attempts_data_source_from_config(config, "MyM")

    assert resolve_data_source(config) == "databricks_sql"
    assert isinstance(source, DatabricksSqlWarehouseRawAttemptsDataSource)
    assert source.table_name == MYM_TABLE
    assert source.warehouse_id == "warehouse-123"


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


def test_load_config_supports_project_level_sources() -> None:
    config = load_config(Path(__file__).resolve().parents[1] / "config" / "dev.toml")

    assert config.data_source == "auto"
    assert config.default_project == "MM"
    assert config.project_keys == ("MM", "MyM")
    assert config.project("MM").csv_path == SAMPLE_DATA
    assert config.project("MM").databricks_table == MM_TABLE
    assert config.project("MyM").databricks_table == MYM_TABLE


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


def test_databricks_sql_data_source_uses_warehouse_and_raw_contract() -> None:
    connection_factory = FakeSqlConnectionFactory(_raw_attempts_frame())
    source = DatabricksSqlWarehouseRawAttemptsDataSource(
        table_name=MM_TABLE,
        warehouse_id="warehouse-123",
        host="https://example.cloud.databricks.com",
        client_id="client-id",
        client_secret="client-secret",
        connection_factory=connection_factory,
        credential_provider_factory=lambda: object(),
    )

    frame = source.load_raw_attempts()

    assert connection_factory.kwargs["server_hostname"] == "example.cloud.databricks.com"
    assert connection_factory.kwargs["http_path"] == "/sql/1.0/warehouses/warehouse-123"
    assert f"from {MM_TABLE}" in connection_factory.query
    assert list(frame.columns) == list(RAW_REQUIRED_COLUMNS)
    assert "extra_column" not in frame.columns


def test_databricks_sql_data_source_wraps_permission_errors() -> None:
    source = DatabricksSqlWarehouseRawAttemptsDataSource(
        table_name=MM_TABLE,
        warehouse_id="warehouse-123",
        host="https://example.cloud.databricks.com",
        client_id="client-id",
        client_secret="client-secret",
        connection_factory=lambda **kwargs: PermissionDeniedSqlConnection(),
        credential_provider_factory=lambda: object(),
    )

    try:
        source.load_raw_attempts()
    except DatabricksDataAccessError as exc:
        assert exc.table_name == MM_TABLE
        assert exc.is_permission_error
        assert "USE CATALOG" in exc.original_message
    else:
        raise AssertionError("Expected DatabricksDataAccessError")


def test_local_project_sources_feed_metric_pipeline() -> None:
    config = load_config(Path(__file__).resolve().parents[1] / "config" / "dev.toml")

    for project_key in config.project_keys:
        frame = load_raw_attempts_from_config(config, project_key)
        statistics = aggregate_statistics(
            frame,
            PreAggregationFilters(level_min=0, level_max=2),
        )

        assert not statistics.empty


class PermissionDeniedSqlConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def cursor(self):
        return PermissionDeniedSqlCursor()


class PermissionDeniedSqlCursor:
    def __init__(self) -> None:
        self.description = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def execute(self, query: str) -> None:
        msg = (
            "[INSUFFICIENT_PERMISSIONS] Insufficient privileges: "
            "User does not have USE CATALOG on Catalog 'game_data_prod'."
        )
        raise RuntimeError(msg)

    def fetchall(self):
        return []


def _project_config(data_source: str) -> AppConfig:
    return AppConfig(
        environment="test",
        data_source=data_source,
        app_title="Test",
        data_path=None,
        projects=(
            ProjectConfig(
                key="MM",
                display_name="MM",
                csv_path=SAMPLE_DATA,
                databricks_table=MM_TABLE,
            ),
            ProjectConfig(
                key="MyM",
                display_name="MyM",
                csv_path=SAMPLE_DATA,
                databricks_table=MYM_TABLE,
            ),
        ),
        default_project="MM",
    )


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
