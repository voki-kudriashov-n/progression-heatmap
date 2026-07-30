"""Raw attempt data source adapters.

Each adapter returns the same raw attempts dataframe contract. Processing modules can
therefore stay independent from whether rows came from a local CSV or a Spark table.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from progression_heatmap.config import AppConfig
from progression_heatmap.data import (
    RAW_REQUIRED_COLUMNS,
    DataEngine,
    load_raw_attempts_data,
    select_raw_attempt_columns,
)

ConnectionFactory = Callable[..., Any]
CredentialProviderFactory = Callable[[], Any]
_TABLE_IDENTIFIER_PATTERN = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,2}$"
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


@dataclass(frozen=True, slots=True)
class DatabricksSqlWarehouseRawAttemptsDataSource:
    """Databricks SQL warehouse adapter for Databricks App runtime."""

    table_name: str
    warehouse_id: str
    host: str
    client_id: str
    client_secret: str = field(repr=False, compare=False)
    connection_factory: ConnectionFactory | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    credential_provider_factory: CredentialProviderFactory | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def load_raw_attempts(self):
        import pandas as pd

        query = _raw_attempts_query(self.table_name)
        connection_factory = self.connection_factory or _databricks_sql_connect
        credential_provider_factory = (
            self.credential_provider_factory or self._credential_provider
        )
        with connection_factory(
            server_hostname=_server_hostname(self.host),
            http_path=_warehouse_http_path(self.warehouse_id),
            credentials_provider=credential_provider_factory,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute(query)
                rows = cursor.fetchall()
                columns = [_description_column_name(column) for column in cursor.description]

        return select_raw_attempt_columns(pd.DataFrame(rows, columns=columns))

    def _credential_provider(self):
        from databricks.sdk.core import Config, oauth_service_principal

        return oauth_service_principal(
            Config(
                host=_host_url(self.host),
                client_id=self.client_id,
                client_secret=self.client_secret,
            )
        )


def raw_attempts_data_source_from_config(
    config: AppConfig,
    project_key: str | None = None,
) -> RawAttemptsDataSource:
    """Build the configured raw attempts data source."""

    data_source = resolve_data_source(config)
    project = _project_or_none(config, project_key)

    if data_source == "csv":
        csv_path = _csv_path_for_project(config, project_key)
        return CsvRawAttemptsDataSource(csv_path)

    if data_source == "databricks_sql":
        if project is None or project.databricks_table is None:
            msg = f"Project {project_key or config.default_project!r} requires databricks_table."
            raise ValueError(msg)
        return DatabricksSqlWarehouseRawAttemptsDataSource(
            table_name=project.databricks_table,
            warehouse_id=_required_env(config.databricks_warehouse_id_env),
            host=_required_env("DATABRICKS_HOST"),
            client_id=_required_env("DATABRICKS_CLIENT_ID"),
            client_secret=_required_env("DATABRICKS_CLIENT_SECRET"),
        )

    if data_source == "spark_sql":
        if config.spark_sql is None:
            msg = "spark_sql data_source requires spark_sql."
            raise ValueError(msg)
        return SparkSqlRawAttemptsDataSource(config.spark_sql)

    if data_source == "spark_table":
        if config.spark_table is None:
            msg = "spark_table data_source requires spark_table."
            raise ValueError(msg)
        return SparkTableRawAttemptsDataSource(config.spark_table)

    msg = f"Unsupported data_source: {data_source!r}"
    raise ValueError(msg)


def load_raw_attempts_from_config(config: AppConfig, project_key: str | None = None):
    """Load raw attempts through the data source configured for this app run."""

    return raw_attempts_data_source_from_config(config, project_key).load_raw_attempts()


def resolve_data_source(config: AppConfig) -> str:
    """Resolve `auto` into the concrete runtime data source."""

    if config.data_source != "auto":
        return config.data_source
    if is_databricks_app_runtime():
        return "databricks_sql"
    return "csv"


def is_databricks_app_runtime() -> bool:
    """Return whether the process is running inside Databricks Apps."""

    return bool(os.environ.get("DATABRICKS_APP_NAME") or os.environ.get("DATABRICKS_APP_URL"))


def _get_spark_session(spark_session: Any | None):
    if spark_session is not None:
        return spark_session

    from pyspark.sql import SparkSession

    active_session = SparkSession.getActiveSession()
    if active_session is not None:
        return active_session
    return SparkSession.builder.getOrCreate()


def _csv_path_for_project(config: AppConfig, project_key: str | None) -> Path:
    project = _project_or_none(config, project_key)
    if project is not None and project.csv_path is not None:
        return project.csv_path
    if config.data_path is not None:
        return config.data_path
    msg = f"Project {project_key or config.default_project!r} requires csv_path."
    raise ValueError(msg)


def _project_or_none(config: AppConfig, project_key: str | None):
    if not config.projects:
        return None
    return config.project(project_key)


def _raw_attempts_query(table_name: str) -> str:
    if not _TABLE_IDENTIFIER_PATTERN.fullmatch(table_name):
        msg = f"Unsupported Databricks table identifier: {table_name!r}"
        raise ValueError(msg)

    columns = ",\n  ".join(RAW_REQUIRED_COLUMNS)
    return f"select\n  {columns}\nfrom {table_name}"


def _databricks_sql_connect(**kwargs):
    from databricks import sql

    return sql.connect(**kwargs)


def _warehouse_http_path(warehouse_id: str) -> str:
    return f"/sql/1.0/warehouses/{warehouse_id}"


def _server_hostname(host: str) -> str:
    parsed = urlparse(_host_url(host))
    return parsed.netloc


def _host_url(host: str) -> str:
    if host.startswith(("http://", "https://")):
        return host
    return f"https://{host}"


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        msg = f"Environment variable {name!r} is required for Databricks SQL source."
        raise RuntimeError(msg)
    return value.strip()


def _description_column_name(column_description) -> str:
    if isinstance(column_description, tuple):
        return column_description[0]
    name = getattr(column_description, "name", None)
    if isinstance(name, str):
        return name
    return column_description[0]
