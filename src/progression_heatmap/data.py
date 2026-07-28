"""Local raw CSV loading and validation for Match-3 attempt data."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Literal

import pandas as pd

RAW_REQUIRED_COLUMNS = (
    "client_time",
    "user_id",
    "balance_id",
    "traffic_type",
    "payer_type",
    "failed",
    "attempt",
    "platform_name",
    "first_attempt",
    "FW",
    "CW",
    "CF",
    "FF",
    "reason_seg",
    "partition_date",
    "level_cohort",
)

RAW_INTEGER_COLUMNS = (
    "balance_id",
    "failed",
    "attempt",
    "first_attempt",
    "FW",
    "CW",
    "CF",
    "FF",
    "level_cohort",
)

RAW_TEXT_COLUMNS = (
    "user_id",
    "traffic_type",
    "payer_type",
    "platform_name",
    "reason_seg",
)

DataEngine = Literal["auto", "pandas", "pyspark"]


class DataValidationError(ValueError):
    """Raised when input data does not match the expected source schema."""


def load_raw_attempts_data(csv_path: str | Path, engine: DataEngine = "auto"):
    """Load raw attempt-level CSV data.

    In `auto` mode this returns a PySpark dataframe when a local Java/Spark runtime is
    available. If Java is unavailable, it returns a normalized pandas dataframe so local
    tests can still run in lightweight environments.
    """

    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(path)
    if engine not in {"auto", "pandas", "pyspark"}:
        msg = "engine must be one of: auto, pandas, pyspark"
        raise ValueError(msg)

    if engine in {"auto", "pyspark"} and has_working_java():
        try:
            return _load_raw_attempts_with_pyspark(path)
        except Exception as exc:
            if engine == "pyspark":
                msg = "PySpark could not load the local raw CSV file."
                raise RuntimeError(msg) from exc

    if engine == "pyspark":
        msg = "PySpark loading requires a working local Java runtime."
        raise RuntimeError(msg)

    return _load_raw_attempts_with_pandas(path)


def validate_required_columns(columns: pd.DataFrame | list[str] | tuple[str, ...]) -> None:
    """Validate that all required raw source columns are present."""

    column_names = columns.columns if isinstance(columns, pd.DataFrame) else columns
    missing_columns = sorted(set(RAW_REQUIRED_COLUMNS).difference(column_names))
    if missing_columns:
        msg = f"Missing required columns: {', '.join(missing_columns)}"
        raise DataValidationError(msg)


def normalize_raw_attempts_data(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize raw source columns into stable local test types."""

    validate_required_columns(frame)
    normalized = frame.loc[:, RAW_REQUIRED_COLUMNS].copy()

    for column in RAW_TEXT_COLUMNS:
        text_values = normalized[column].astype("string").str.strip()
        if text_values.isna().any() or (text_values == "").any():
            msg = f"Column {column!r} contains empty values."
            raise DataValidationError(msg)
        normalized[column] = text_values.astype(str)

    for column in RAW_INTEGER_COLUMNS:
        numeric_values = pd.to_numeric(normalized[column], errors="coerce")
        if numeric_values.isna().any():
            msg = f"Column {column!r} contains non-numeric values."
            raise DataValidationError(msg)
        normalized[column] = numeric_values.astype(int)

    client_time = pd.to_datetime(normalized["client_time"], errors="coerce")
    if client_time.isna().any():
        msg = "Column 'client_time' contains invalid timestamp values."
        raise DataValidationError(msg)
    normalized["client_time"] = client_time

    partition_date = pd.to_datetime(normalized["partition_date"], errors="coerce")
    if partition_date.isna().any():
        msg = "Column 'partition_date' contains invalid date values."
        raise DataValidationError(msg)
    normalized["partition_date"] = partition_date.dt.normalize()

    return normalized.sort_values(
        ["partition_date", "level_cohort", "user_id", "balance_id"],
        kind="stable",
    ).reset_index(drop=True)


def has_working_java() -> bool:
    """Return whether this machine can start a local JVM for PySpark."""

    try:
        subprocess.run(
            ["java", "-version"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return False
    return True


def _load_raw_attempts_with_pandas(path: Path) -> pd.DataFrame:
    return normalize_raw_attempts_data(pd.read_csv(path, keep_default_na=False))


def _load_raw_attempts_with_pyspark(path: Path):
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as sql_functions
    from pyspark.sql import types as sql_types

    schema = sql_types.StructType(
        [
            sql_types.StructField("client_time", sql_types.TimestampType(), nullable=False),
            sql_types.StructField("user_id", sql_types.StringType(), nullable=False),
            sql_types.StructField("balance_id", sql_types.IntegerType(), nullable=False),
            sql_types.StructField("traffic_type", sql_types.StringType(), nullable=False),
            sql_types.StructField("payer_type", sql_types.StringType(), nullable=False),
            sql_types.StructField("failed", sql_types.IntegerType(), nullable=False),
            sql_types.StructField("attempt", sql_types.IntegerType(), nullable=False),
            sql_types.StructField("platform_name", sql_types.StringType(), nullable=False),
            sql_types.StructField("first_attempt", sql_types.IntegerType(), nullable=False),
            sql_types.StructField("FW", sql_types.IntegerType(), nullable=False),
            sql_types.StructField("CW", sql_types.IntegerType(), nullable=False),
            sql_types.StructField("CF", sql_types.IntegerType(), nullable=False),
            sql_types.StructField("FF", sql_types.IntegerType(), nullable=False),
            sql_types.StructField("reason_seg", sql_types.StringType(), nullable=False),
            sql_types.StructField("partition_date", sql_types.DateType(), nullable=False),
            sql_types.StructField("level_cohort", sql_types.IntegerType(), nullable=False),
        ]
    )
    spark = (
        SparkSession.builder.master("local[1]")
        .appName("progression-heatmap-local-loader")
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )
    spark_frame = spark.read.option("header", True).schema(schema).csv(str(path))
    validate_required_columns(spark_frame.columns)
    return spark_frame.select(
        sql_functions.col("client_time"),
        sql_functions.col("user_id"),
        sql_functions.col("balance_id"),
        sql_functions.col("traffic_type"),
        sql_functions.col("payer_type"),
        sql_functions.col("failed"),
        sql_functions.col("attempt"),
        sql_functions.col("platform_name"),
        sql_functions.col("first_attempt"),
        sql_functions.col("FW"),
        sql_functions.col("CW"),
        sql_functions.col("CF"),
        sql_functions.col("FF"),
        sql_functions.col("reason_seg"),
        sql_functions.col("partition_date"),
        sql_functions.col("level_cohort"),
    )

