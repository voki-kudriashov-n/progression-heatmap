"""Configuration loading for the progression heatmap dashboard."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "dev.toml"
SUPPORTED_DATA_SOURCES = ("auto", "csv", "databricks_sql", "spark_sql", "spark_table")
DEFAULT_PROJECT = "MM"
DEFAULT_WAREHOUSE_ID_ENV = "DATABRICKS_WAREHOUSE_ID"


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    """Source configuration for one game project."""

    key: str
    display_name: str
    csv_path: Path | None = None
    databricks_table: str | None = None


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Runtime configuration for the dashboard."""

    environment: str
    data_source: str
    data_path: Path | None
    app_title: str
    production_simulation: bool = False
    spark_sql: str | None = None
    spark_table: str | None = None
    projects: tuple[ProjectConfig, ...] = ()
    default_project: str = DEFAULT_PROJECT
    databricks_warehouse_id_env: str = DEFAULT_WAREHOUSE_ID_ENV

    @property
    def project_keys(self) -> tuple[str, ...]:
        """Return configured project keys in UI order."""

        return tuple(project.key for project in self.projects)

    def project(self, project_key: str | None = None) -> ProjectConfig:
        """Return one configured project by key."""

        selected_key = project_key or self.default_project
        for project in self.projects:
            if project.key == selected_key:
                return project
        msg = f"Unknown project: {selected_key!r}"
        raise ValueError(msg)


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load a TOML config file and resolve paths relative to the project root."""

    path = _resolve_config_path(config_path)
    with path.open("rb") as config_file:
        raw_config = tomllib.load(config_file)

    environment = _required_text(raw_config, "environment")
    data_source = _required_text(raw_config, "data_source")
    if data_source not in SUPPORTED_DATA_SOURCES:
        msg = f"data_source must be one of: {', '.join(SUPPORTED_DATA_SOURCES)}"
        raise ValueError(msg)

    data_path = None
    spark_sql = None
    spark_table = None
    if data_source == "csv":
        raw_data_path = raw_config.get("data_path")
        if raw_data_path is not None:
            data_path = _resolve_project_path(_required_text(raw_config, "data_path"))
    elif data_source == "spark_sql":
        spark_sql = _required_text(raw_config, "spark_sql")
    elif data_source == "spark_table":
        spark_table = _required_text(raw_config, "spark_table")

    projects = _load_project_configs(raw_config)
    default_project = _optional_text(raw_config, "default_project", DEFAULT_PROJECT)
    if projects and default_project not in {project.key for project in projects}:
        msg = f"default_project {default_project!r} is not configured in projects."
        raise ValueError(msg)

    return AppConfig(
        environment=environment,
        data_source=data_source,
        app_title=_required_text(raw_config, "app_title"),
        data_path=data_path,
        production_simulation=bool(raw_config.get("production_simulation", False)),
        spark_sql=spark_sql,
        spark_table=spark_table,
        projects=projects,
        default_project=default_project,
        databricks_warehouse_id_env=_optional_text(
            raw_config,
            "databricks_warehouse_id_env",
            DEFAULT_WAREHOUSE_ID_ENV,
        ),
    )


def _resolve_config_path(config_path: str | Path | None) -> Path:
    raw_path = config_path or os.environ.get("PROGRESSION_HEATMAP_CONFIG") or DEFAULT_CONFIG_PATH
    path = Path(raw_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _resolve_project_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _load_project_configs(config: dict[str, Any]) -> tuple[ProjectConfig, ...]:
    raw_projects = config.get("projects", {})
    if not isinstance(raw_projects, dict):
        msg = "Config field 'projects' must be a TOML table."
        raise ValueError(msg)

    projects = []
    for project_key, raw_project in raw_projects.items():
        if not isinstance(raw_project, dict):
            msg = f"Project config for {project_key!r} must be a TOML table."
            raise ValueError(msg)
        display_name = _optional_text(raw_project, "display_name", project_key)
        raw_csv_path = raw_project.get("csv_path")
        csv_path = _resolve_project_path(raw_csv_path) if isinstance(raw_csv_path, str) else None
        databricks_table = _optional_text_or_none(raw_project, "databricks_table")
        projects.append(
            ProjectConfig(
                key=project_key,
                display_name=display_name,
                csv_path=csv_path,
                databricks_table=databricks_table,
            )
        )
    return tuple(projects)


def _required_text(config: dict[str, Any], field_name: str) -> str:
    value = config.get(field_name)
    if not isinstance(value, str) or not value.strip():
        msg = f"Config field {field_name!r} must be a non-empty string."
        raise ValueError(msg)
    return value.strip()


def _optional_text(config: dict[str, Any], field_name: str, default: str) -> str:
    value = config.get(field_name, default)
    if not isinstance(value, str) or not value.strip():
        msg = f"Config field {field_name!r} must be a non-empty string."
        raise ValueError(msg)
    return value.strip()


def _optional_text_or_none(config: dict[str, Any], field_name: str) -> str | None:
    value = config.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        msg = f"Config field {field_name!r} must be a non-empty string when provided."
        raise ValueError(msg)
    return value.strip()
