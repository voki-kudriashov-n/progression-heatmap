"""Raw attempt data source adapters.

Each adapter returns the same raw attempts dataframe contract. Processing modules can
therefore stay independent from whether rows came from a local CSV or a Spark table.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol
from urllib.parse import urlparse

from progression_heatmap.config import AppConfig
from progression_heatmap.data import (
    RAW_REQUIRED_COLUMNS,
    DataEngine,
    load_raw_attempts_data,
    select_raw_attempt_columns,
)
from progression_heatmap.filters import (
    ATTEMPT_GROUP_FIRST,
    ATTEMPT_GROUP_REPEAT,
    ATTEMPT_GROUPS,
    DateLike,
    PreAggregationFilters,
    RawFilterOptions,
    collect_raw_filter_options,
)
from progression_heatmap.metrics import aggregate_statistics

ConnectionFactory = Callable[..., Any]
CredentialProviderFactory = Callable[[], Any]
LOGGER = logging.getLogger(__name__)
_TABLE_IDENTIFIER_PATTERN = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,2}$"
)
_WAREHOUSE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class DataSourceError(RuntimeError):
    """Raised when a configured data source cannot return raw attempt rows."""


class DatabricksDataAccessError(DataSourceError):
    """Raised when Databricks SQL cannot read the configured source table."""

    def __init__(self, table_name: str, original_error: Exception) -> None:
        self.table_name = table_name
        self.original_error_class = original_error.__class__.__name__
        self.original_message = str(original_error)
        super().__init__(
            f"Databricks SQL could not read table {table_name!r}: "
            f"{self.original_error_class}: {self.original_message}"
        )

    @property
    def is_permission_error(self) -> bool:
        """Return whether the original Databricks error looks permission-related."""

        permission_markers = (
            "INSUFFICIENT_PERMISSIONS",
            "USE CATALOG",
            "USE SCHEMA",
            "SELECT",
            "PERMISSION_DENIED",
            "privileges",
        )
        return any(marker in self.original_message for marker in permission_markers)

    @property
    def is_gateway_error(self) -> bool:
        """Return whether the original Databricks error looks gateway-related."""

        gateway_markers = (
            "502",
            "Bad Gateway",
            "Databricks App - 502",
            "App Not Available",
        )
        return any(marker in self.original_message for marker in gateway_markers)


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
        LOGGER.info("csv.load_raw_attempts.start path=%s engine=%s", self.path, self.engine)
        started_at = perf_counter()
        frame = load_raw_attempts_data(self.path, engine=self.engine)
        LOGGER.info(
            "csv.load_raw_attempts.done path=%s frame_type=%s elapsed_seconds=%.3f",
            self.path,
            frame.__class__.__name__,
            perf_counter() - started_at,
        )
        return frame


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
        rows, columns = self._execute_query(query, stage="raw_attempts")

        return select_raw_attempt_columns(pd.DataFrame(rows, columns=columns))

    def collect_filter_options(self) -> RawFilterOptions:
        """Collect filter options through small warehouse-side SQL queries."""

        options = self._query_to_pandas(
            _filter_options_query(self.table_name),
            stage="filter_options",
        ).iloc[0]
        return RawFilterOptions(
            level_min=int(options["level_min"]),
            level_max=int(options["level_max"]),
            date_min=_python_date(options["date_min"]),
            date_max=_python_date(options["date_max"]),
            payer_types=_json_array_tuple(options["payer_types"]),
            traffic_types=_json_array_tuple(options["traffic_types"]),
            platform_names=_json_array_tuple(options["platform_names"]),
            attempt_groups=_json_array_tuple(options["attempt_groups"]),
        )

    def aggregate_statistics(self, criteria: PreAggregationFilters):
        """Aggregate statistics in Databricks SQL and return grouped pandas rows."""

        return self._query_to_pandas(
            _aggregate_statistics_query(self.table_name, criteria),
            stage="aggregate_statistics",
        )

    def _query_to_pandas(self, query: str, stage: str):
        import pandas as pd

        rows, columns = self._execute_query(query, stage=stage)
        return pd.DataFrame(rows, columns=columns)

    def _execute_query(self, query: str, stage: str):
        connection_factory = self.connection_factory or _databricks_sql_connect
        credential_provider_factory = (
            self.credential_provider_factory or self._credential_provider
        )
        started_at = perf_counter()
        try:
            server_hostname = _server_hostname(self.host)
            http_path = _warehouse_http_path(self.warehouse_id)
            LOGGER.info(
                "databricks_sql.%s.connect.start table=%s host=%s host_kind=%s "
                "warehouse_value_shape=%s http_path=%s",
                stage,
                self.table_name,
                server_hostname,
                _host_kind(server_hostname),
                _warehouse_value_shape(self.warehouse_id),
                http_path,
            )
            with connection_factory(
                server_hostname=server_hostname,
                http_path=http_path,
                credentials_provider=credential_provider_factory,
            ) as connection:
                LOGGER.info(
                    "databricks_sql.%s.connect.done table=%s elapsed_seconds=%.3f",
                    stage,
                    self.table_name,
                    perf_counter() - started_at,
                )
                with connection.cursor() as cursor:
                    execute_started_at = perf_counter()
                    LOGGER.info(
                        "databricks_sql.%s.execute.start table=%s query=%s",
                        stage,
                        self.table_name,
                        _compact_sql(query),
                    )
                    cursor.execute(query)
                    LOGGER.info(
                        "databricks_sql.%s.execute.done table=%s elapsed_seconds=%.3f",
                        stage,
                        self.table_name,
                        perf_counter() - execute_started_at,
                    )
                    fetch_started_at = perf_counter()
                    LOGGER.info(
                        "databricks_sql.%s.fetch.start table=%s",
                        stage,
                        self.table_name,
                    )
                    rows = cursor.fetchall()
                    columns = [
                        _description_column_name(column) for column in cursor.description
                    ]
                    LOGGER.info(
                        "databricks_sql.%s.fetch.done table=%s rows=%s columns=%s "
                        "elapsed_seconds=%.3f total_elapsed_seconds=%.3f",
                        stage,
                        self.table_name,
                        len(rows),
                        len(columns),
                        perf_counter() - fetch_started_at,
                        perf_counter() - started_at,
                    )
        except Exception as exc:
            LOGGER.exception(
                "databricks_sql.%s.error table=%s elapsed_seconds=%.3f error_class=%s",
                stage,
                self.table_name,
                perf_counter() - started_at,
                exc.__class__.__name__,
            )
            raise DatabricksDataAccessError(self.table_name, exc) from exc

        return rows, columns

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
    LOGGER.info(
        "data_source.resolve requested=%s resolved=%s project=%s table=%s csv_path=%s",
        config.data_source,
        data_source,
        project_key or config.default_project,
        project.databricks_table if project is not None else None,
        project.csv_path if project is not None else config.data_path,
    )

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


def collect_filter_options_from_config(
    config: AppConfig,
    project_key: str | None = None,
) -> RawFilterOptions:
    """Collect raw filter options through the configured source."""

    source = raw_attempts_data_source_from_config(config, project_key)
    if isinstance(source, DatabricksSqlWarehouseRawAttemptsDataSource):
        return source.collect_filter_options()
    return collect_raw_filter_options(source.load_raw_attempts())


def aggregate_statistics_from_config(
    config: AppConfig,
    project_key: str | None,
    criteria: PreAggregationFilters,
):
    """Aggregate statistics through the configured source."""

    source = raw_attempts_data_source_from_config(config, project_key)
    if isinstance(source, DatabricksSqlWarehouseRawAttemptsDataSource):
        return source.aggregate_statistics(criteria)
    return aggregate_statistics(source.load_raw_attempts(), criteria)


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
    _validate_table_identifier(table_name)

    columns = ",\n  ".join(RAW_REQUIRED_COLUMNS)
    return f"select\n  {columns}\nfrom {table_name}"


def _validate_table_identifier(table_name: str) -> None:
    if not _TABLE_IDENTIFIER_PATTERN.fullmatch(table_name):
        msg = f"Unsupported Databricks table identifier: {table_name!r}"
        raise ValueError(msg)


def _filter_options_query(table_name: str) -> str:
    _validate_table_identifier(table_name)
    return (
        "select\n"
        "  min(cast(level_cohort as int)) as level_min,\n"
        "  max(cast(level_cohort as int)) as level_max,\n"
        "  min(cast(partition_date as date)) as date_min,\n"
        "  max(cast(partition_date as date)) as date_max,\n"
        "  to_json(sort_array(collect_set(cast(payer_type as string)))) as payer_types,\n"
        "  to_json(sort_array(collect_set(cast(traffic_type as string)))) as traffic_types,\n"
        "  to_json(sort_array(collect_set(cast(platform_name as string)))) as platform_names,\n"
        "  to_json(sort_array(collect_set(\n"
        "    case\n"
        f"      when cast(attempt as int) = 1 then '{ATTEMPT_GROUP_FIRST}'\n"
        f"      when cast(attempt as int) >= 2 then '{ATTEMPT_GROUP_REPEAT}'\n"
        "    end\n"
        "  ))) as attempt_groups\n"
        f"from {table_name}"
    )


def _aggregate_statistics_query(table_name: str, criteria: PreAggregationFilters) -> str:
    _validate_table_identifier(table_name)
    where_clause = _where_clause(criteria)
    return (
        "with filtered as (\n"
        "  select\n"
        "    cast(level_cohort as int) as level_cohort,\n"
        "    cast(partition_date as date) as partition_date,\n"
        "    cast(FW as double) as FW,\n"
        "    cast(CW as double) as CW,\n"
        "    cast(CF as double) as CF,\n"
        "    cast(FF as double) as FF,\n"
        "    cast(failed as double) as failed,\n"
        "    cast(attempt as double) as attempt,\n"
        "    cast(first_attempt as double) as first_attempt\n"
        f"  from {table_name}\n"
        f"{where_clause}"
        "),\n"
        "grouped as (\n"
        "  select\n"
        "    level_cohort as level_group,\n"
        "    partition_date as date,\n"
        "    sum(FW) as FW_absolute,\n"
        "    sum(CW) as CW_absolute,\n"
        "    sum(CF) as CF_absolute,\n"
        "    sum(FF) as FF_absolute,\n"
        "    sum(FW) + sum(CW) as wins_absolute,\n"
        "    sum(FF) + sum(CF) as fails_absolute,\n"
        "    cast(count(*) as double) as attempts_absolute,\n"
        "    sum(failed) as failed_absolute,\n"
        "    avg(attempt) as attempt_average,\n"
        "    sum(first_attempt) as first_attempt_absolute\n"
        "  from filtered\n"
        "  group by level_cohort, partition_date\n"
        "),\n"
        "totals as (\n"
        "  select\n"
        "    *,\n"
        "    wins_absolute as wins,\n"
        "    fails_absolute as fails\n"
        "  from grouped\n"
        ")\n"
        "select\n"
        "  cast(level_group as int) as level_group,\n"
        "  date,\n"
        "  cast(FW_absolute as double) as FW_absolute,\n"
        "  cast(CW_absolute as double) as CW_absolute,\n"
        "  cast(CF_absolute as double) as CF_absolute,\n"
        "  cast(FF_absolute as double) as FF_absolute,\n"
        "  cast(wins_absolute as double) as wins_absolute,\n"
        "  cast(fails_absolute as double) as fails_absolute,\n"
        "  cast(attempts_absolute as double) as attempts_absolute,\n"
        "  cast(failed_absolute as double) as failed_absolute,\n"
        "  cast(attempt_average as double) as attempt_average,\n"
        "  cast(first_attempt_absolute as double) as first_attempt_absolute,\n"
        "  case when attempts_absolute != 0 then FW_absolute / attempts_absolute * 100 "
        "else 0.0 end as FW_relative,\n"
        "  case when attempts_absolute != 0 then CW_absolute / attempts_absolute * 100 "
        "else 0.0 end as CW_relative,\n"
        "  case when attempts_absolute != 0 then CF_absolute / attempts_absolute * 100 "
        "else 0.0 end as CF_relative,\n"
        "  case when attempts_absolute != 0 then FF_absolute / attempts_absolute * 100 "
        "else 0.0 end as FF_relative,\n"
        "  case when wins != 0 then FW_absolute / wins * 100 "
        "else 0.0 end as FW_partial_relative,\n"
        "  case when wins != 0 then CW_absolute / wins * 100 "
        "else 0.0 end as CW_partial_relative,\n"
        "  case when fails != 0 then FF_absolute / fails * 100 "
        "else 0.0 end as FF_partial_relative,\n"
        "  case when fails != 0 then CF_absolute / fails * 100 "
        "else 0.0 end as CF_partial_relative,\n"
        "  case when attempts_absolute != 0 then failed_absolute / attempts_absolute * 100 "
        "else 0.0 end as fail_rate_relative,\n"
        "  100 - case when attempts_absolute != 0 then "
        "failed_absolute / attempts_absolute * 100 else 0.0 end as win_rate_relative,\n"
        "  case when attempts_absolute != 0 then "
        "first_attempt_absolute / attempts_absolute * 100 else 0.0 end as first_attempt_relative\n"
        "from totals\n"
        "order by level_group, date"
    )


def _where_clause(criteria: PreAggregationFilters) -> str:
    if (
        criteria.level_min is not None
        and criteria.level_max is not None
        and criteria.level_min > criteria.level_max
    ):
        msg = "level_min cannot be greater than level_max."
        raise ValueError(msg)

    conditions = []
    if criteria.level_min is not None:
        conditions.append(f"cast(level_cohort as int) >= {int(criteria.level_min)}")
    if criteria.level_max is not None:
        conditions.append(f"cast(level_cohort as int) <= {int(criteria.level_max)}")
    if criteria.start_date is not None:
        conditions.append(
            f"cast(partition_date as date) >= {_sql_date_literal(criteria.start_date)}"
        )
    if criteria.end_date is not None:
        conditions.append(
            f"cast(partition_date as date) <= {_sql_date_literal(criteria.end_date)}"
        )
    if criteria.payer_types:
        conditions.append(_sql_in_clause("payer_type", criteria.payer_types))
    if criteria.traffic_types:
        conditions.append(_sql_in_clause("traffic_type", criteria.traffic_types))
    if criteria.platform_names:
        conditions.append(_sql_in_clause("platform_name", criteria.platform_names))
    attempt_group_condition = _attempt_group_condition(criteria.attempt_groups)
    if attempt_group_condition is not None:
        conditions.append(attempt_group_condition)

    if not conditions:
        return ""
    return "  where " + "\n    and ".join(conditions) + "\n"


def _sql_in_clause(column_name: str, values: tuple[str, ...]) -> str:
    literals = ", ".join(_sql_string_literal(value) for value in values)
    return f"cast({column_name} as string) in ({literals})"


def _attempt_group_condition(attempt_groups: tuple[str, ...]) -> str | None:
    if not attempt_groups or set(attempt_groups) == set(ATTEMPT_GROUPS):
        return None

    conditions = []
    for attempt_group in attempt_groups:
        if attempt_group == ATTEMPT_GROUP_FIRST:
            conditions.append("cast(attempt as int) = 1")
        elif attempt_group == ATTEMPT_GROUP_REPEAT:
            conditions.append("cast(attempt as int) >= 2")
        else:
            msg = f"Unsupported attempt group: {attempt_group!r}"
            raise ValueError(msg)

    if not conditions:
        return None
    return "(" + " or ".join(conditions) + ")"


def _sql_string_literal(value: str) -> str:
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def _sql_date_literal(value: DateLike) -> str:
    return f"date '{_python_date(value).isoformat()}'"


def _json_array_tuple(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(str(item) for item in json.loads(value))
    return tuple(str(item) for item in value)


def _compact_sql(query: str, max_length: int = 1200) -> str:
    compact = " ".join(query.split())
    if len(compact) <= max_length:
        return compact
    return compact[: max_length - 3] + "..."


def _python_date(value: DateLike):
    import pandas as pd

    return pd.Timestamp(value).date()


def _databricks_sql_connect(**kwargs):
    from databricks import sql

    return sql.connect(**kwargs)


def _warehouse_http_path(warehouse_id: str) -> str:
    value = warehouse_id.strip()
    if value.startswith("/sql/"):
        return value

    parsed = urlparse(value)
    if parsed.scheme and parsed.path.startswith("/sql/"):
        return parsed.path

    if not _WAREHOUSE_ID_PATTERN.fullmatch(value):
        msg = (
            "DATABRICKS_WAREHOUSE_ID must be a warehouse id or SQL warehouse http_path, "
            f"got {value!r}."
        )
        raise ValueError(msg)
    return f"/sql/1.0/warehouses/{value}"


def _server_hostname(host: str) -> str:
    parsed = urlparse(_host_url(host))
    return parsed.netloc


def _host_kind(server_hostname: str) -> str:
    if "databricksapps.com" in server_hostname:
        return "databricks_app"
    if "databricks.com" in server_hostname:
        return "workspace"
    return "custom"


def _warehouse_value_shape(warehouse_id: str) -> str:
    value = warehouse_id.strip()
    if value.startswith("/sql/"):
        return "http_path"
    parsed = urlparse(value)
    if parsed.scheme and parsed.path.startswith("/sql/"):
        return "http_path_url"
    if _WAREHOUSE_ID_PATTERN.fullmatch(value):
        return "id"
    return "unknown"


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
