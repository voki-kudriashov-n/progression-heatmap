"""Configuration loading for the progression heatmap dashboard."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "dev.toml"


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Runtime configuration for the dashboard."""

    environment: str
    data_source: str
    data_path: Path
    app_title: str
    production_simulation: bool = False


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load a TOML config file and resolve paths relative to the project root."""

    path = _resolve_config_path(config_path)
    with path.open("rb") as config_file:
        raw_config = tomllib.load(config_file)

    environment = _required_text(raw_config, "environment")
    data_source = _required_text(raw_config, "data_source")
    if data_source != "csv":
        msg = "Only local CSV data_source is supported in this first version."
        raise ValueError(msg)

    return AppConfig(
        environment=environment,
        data_source=data_source,
        data_path=_resolve_project_path(_required_text(raw_config, "data_path")),
        app_title=_required_text(raw_config, "app_title"),
        production_simulation=bool(raw_config.get("production_simulation", False)),
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


def _required_text(config: dict[str, Any], field_name: str) -> str:
    value = config.get(field_name)
    if not isinstance(value, str) or not value.strip():
        msg = f"Config field {field_name!r} must be a non-empty string."
        raise ValueError(msg)
    return value.strip()

