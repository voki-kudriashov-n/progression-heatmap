"""Streamlit UI for the Match-3 progression heatmap dashboard."""

from __future__ import annotations

import logging
import os
from datetime import date
from time import perf_counter
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from progression_heatmap.config import AppConfig, load_config
from progression_heatmap.data_sources import (
    DatabricksDataAccessError,
    aggregate_statistics_from_config,
    collect_filter_options_from_config,
    resolve_data_source,
)
from progression_heatmap.filters import MetricSelection, PreAggregationFilters
from progression_heatmap.heatmap import prepare_heatmap_table
from progression_heatmap.metrics import (
    calculation_methods_for_metric,
    metric_names,
    select_metric_values_with_context,
    to_pandas_frame,
)

MIN_HEATMAP_HEIGHT = 560
MAX_HEATMAP_HEIGHT = 980
HEATMAP_ROW_HEIGHT = 9
LOGGER = logging.getLogger(__name__)


def main() -> None:
    _configure_logging()
    config_path = os.environ.get("PROGRESSION_HEATMAP_CONFIG")
    LOGGER.info("app.start config_path=%s", config_path or "<default>")
    config = load_config(config_path)
    st.set_page_config(page_title=config.app_title, layout="wide")
    _apply_page_style()

    project_key = _render_project_selector(config)
    data_source = resolve_data_source(config)
    diagnostics = _render_runtime_diagnostics(config, project_key, data_source)
    LOGGER.info(
        "app.config.loaded environment=%s source=%s project=%s table=%s",
        config.environment,
        data_source,
        project_key,
        _configured_databricks_table(config, project_key),
    )
    try:
        filter_started_at = perf_counter()
        _set_runtime_status(diagnostics, "Stage: loading filter options", filter_started_at)
        filter_options = _load_filter_options(config, project_key)
        _set_runtime_status(
            diagnostics,
            (
                "Stage: filter options loaded "
                f"levels={filter_options.level_min}-{filter_options.level_max} "
                f"dates={filter_options.date_min}..{filter_options.date_max}"
            ),
            filter_started_at,
        )
        pre_filters, metric_selection = _render_filters(filter_options)
        statistics_started_at = perf_counter()
        _set_runtime_status(
            diagnostics,
            (
                "Stage: grouping metric rows "
                f"metric={metric_selection.metric_name}/{metric_selection.calculation_method}"
            ),
            statistics_started_at,
        )
        statistics = _compute_statistics(config, project_key, pre_filters)
        _set_runtime_status(
            diagnostics,
            f"Stage: metric rows loaded rows={len(statistics)}",
            statistics_started_at,
        )
    except DatabricksDataAccessError as exc:
        _set_runtime_status(diagnostics, f"Stage: Databricks error table={exc.table_name}")
        _render_databricks_data_access_error(exc)
        return
    except Exception as exc:
        LOGGER.exception("app.error project=%s source=%s", project_key, data_source)
        _set_runtime_status(diagnostics, f"Stage: unexpected error {exc.__class__.__name__}")
        _render_unexpected_error(exc)
        return

    metric_values = select_metric_values_with_context(statistics, metric_selection)
    metric_values = to_pandas_frame(metric_values)
    heatmap_table = prepare_heatmap_table(metric_values, "value")
    LOGGER.info(
        "app.render_heatmap.ready project=%s metric_rows=%s heatmap_rows=%s heatmap_columns=%s",
        project_key,
        len(metric_values),
        len(heatmap_table.index),
        len(heatmap_table.columns),
    )

    if config.production_simulation and resolve_data_source(config) == "csv":
        st.warning("Local CSV source is active for this config.")

    _render_heatmap(heatmap_table, metric_values)

    with st.expander("Grouped metric rows", expanded=False):
        st.dataframe(metric_values, use_container_width=True, hide_index=True)


@st.cache_data(show_spinner="Loading raw filter values...")
def _load_filter_options(config: AppConfig, project_key: str):
    started_at = perf_counter()
    source = resolve_data_source(config)
    LOGGER.info(
        "app.filter_options.start source=%s project=%s table=%s",
        source,
        project_key,
        _configured_databricks_table(config, project_key),
    )
    try:
        options = collect_filter_options_from_config(config, project_key)
    except Exception:
        LOGGER.exception(
            "app.filter_options.error source=%s project=%s elapsed_seconds=%.3f",
            source,
            project_key,
            perf_counter() - started_at,
        )
        raise
    LOGGER.info(
        "app.filter_options.done source=%s project=%s elapsed_seconds=%.3f",
        source,
        project_key,
        perf_counter() - started_at,
    )
    return options


@st.cache_data(show_spinner="Grouping raw attempt data...")
def _compute_statistics(
    config: AppConfig,
    project_key: str,
    pre_filters: PreAggregationFilters,
) -> pd.DataFrame:
    started_at = perf_counter()
    source = resolve_data_source(config)
    LOGGER.info(
        "app.statistics.start source=%s project=%s table=%s filters=%s",
        source,
        project_key,
        _configured_databricks_table(config, project_key),
        pre_filters,
    )
    try:
        statistics = aggregate_statistics_from_config(config, project_key, pre_filters)
        statistics_frame = to_pandas_frame(statistics)
    except Exception:
        LOGGER.exception(
            "app.statistics.error source=%s project=%s elapsed_seconds=%.3f",
            source,
            project_key,
            perf_counter() - started_at,
        )
        raise
    LOGGER.info(
        "app.statistics.done source=%s project=%s rows=%s elapsed_seconds=%.3f",
        source,
        project_key,
        len(statistics_frame),
        perf_counter() - started_at,
    )
    return statistics_frame


def _render_project_selector(config: AppConfig) -> str:
    st.sidebar.header("Project")
    if not config.projects:
        return config.default_project

    project_keys = config.project_keys
    default_index = (
        project_keys.index(config.default_project) if config.default_project in project_keys else 0
    )
    return st.sidebar.selectbox(
        "Game",
        project_keys,
        index=default_index,
        format_func=lambda key: config.project(key).display_name,
    )


def _render_runtime_diagnostics(config: AppConfig, project_key: str, data_source: str):
    with st.sidebar.expander("Diagnostics", expanded=data_source == "databricks_sql"):
        st.caption(f"Source: `{data_source}`")
        st.caption(f"Project: `{project_key}`")
        table_name = _configured_databricks_table(config, project_key)
        if table_name is not None:
            st.caption(f"Table: `{table_name}`")
        st.caption(f"Uses Databricks SQL: `{data_source == 'databricks_sql'}`")
        return st.empty()


def _set_runtime_status(status_slot, message: str, started_at: float | None = None) -> None:
    if started_at is None:
        status_slot.info(message)
        return
    status_slot.info(f"{message}\n\nElapsed: `{perf_counter() - started_at:.1f}s`")


def _configured_databricks_table(config: AppConfig, project_key: str) -> str | None:
    if not config.projects:
        return None
    return config.project(project_key).databricks_table


def _configure_logging() -> None:
    raw_level = os.environ.get("PROGRESSION_HEATMAP_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, raw_level, logging.INFO)
    package_logger = logging.getLogger("progression_heatmap")
    package_logger.setLevel(level)
    package_logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    existing_handler = None
    for handler in package_logger.handlers:
        if getattr(handler, "_progression_heatmap_handler", False):
            existing_handler = handler
            break

    if existing_handler is None:
        handler = logging.StreamHandler()
        handler._progression_heatmap_handler = True
        handler.setFormatter(formatter)
        package_logger.addHandler(handler)
    else:
        existing_handler.setFormatter(formatter)

    for handler in package_logger.handlers:
        handler.setLevel(level)


def _render_databricks_data_access_error(error: DatabricksDataAccessError) -> None:
    st.error("Databricks SQL source is not accessible to this app.")
    st.write(
        "The app runs as its own Databricks service principal. Notebook access with "
        "your user does not automatically grant this app access to Unity Catalog data."
    )
    if error.is_gateway_error:
        st.info(
            "The SQL connector received a 502/Bad Gateway response. Check App logs for "
            "`databricks_sql.*.connect.start`, `execute.start`, and `fetch.start`. "
            "Pay special attention to `host_kind`, `http_path`, and the last marker before "
            "the error."
        )
    if error.is_permission_error:
        st.info(
            "Grant the app service principal `USE CATALOG`, `USE SCHEMA`, and `SELECT` "
            f"for `{error.table_name}`. The SQL warehouse resource also needs `Can use`."
        )
    with st.expander("Databricks error", expanded=False):
        st.code(f"{error.original_error_class}: {error.original_message}")


def _render_unexpected_error(error: Exception) -> None:
    st.error("The dashboard hit an unexpected error while loading data.")
    st.write("Check the Databricks App logs for the matching `app.error` traceback.")
    with st.expander("Error details", expanded=False):
        st.code(f"{error.__class__.__name__}: {error}")


def _render_filters(filter_options) -> tuple[PreAggregationFilters, MetricSelection]:
    st.sidebar.header("Filters")

    level_range = st.sidebar.slider(
        "Level cohort range",
        min_value=filter_options.level_min,
        max_value=filter_options.level_max,
        value=(filter_options.level_min, filter_options.level_max),
        step=1,
    )

    selected_dates = st.sidebar.date_input(
        "Time range",
        value=(filter_options.date_min, filter_options.date_max),
        min_value=filter_options.date_min,
        max_value=filter_options.date_max,
    )
    start_date, end_date = _coerce_date_range(
        selected_dates,
        filter_options.date_min,
        filter_options.date_max,
    )

    attempt_groups = st.sidebar.multiselect(
        "Attempt group",
        filter_options.attempt_groups,
        default=filter_options.attempt_groups,
    )
    platform_names = st.sidebar.multiselect(
        "Platform",
        filter_options.platform_names,
        default=filter_options.platform_names,
    )
    traffic_types = st.sidebar.multiselect(
        "Traffic type",
        filter_options.traffic_types,
        default=filter_options.traffic_types,
    )
    payer_types = st.sidebar.multiselect(
        "Payer type",
        filter_options.payer_types,
        default=filter_options.payer_types,
    )

    selected_metric_name = st.sidebar.selectbox("Metric name", metric_names())
    methods = calculation_methods_for_metric(selected_metric_name)
    default_method_index = methods.index("relative") if "relative" in methods else 0
    selected_calculation_method = st.sidebar.selectbox(
        "Calculation method",
        methods,
        index=default_method_index,
    )
    min_observations = 1000
    if selected_calculation_method in {"relative", "partial_relative"}:
        min_observations = st.sidebar.number_input(
            "Minimum observations",
            min_value=0,
            max_value=10_000_000,
            value=1000,
            step=100,
        )

    return PreAggregationFilters(
        level_min=level_range[0],
        level_max=level_range[1],
        start_date=start_date,
        end_date=end_date,
        payer_types=tuple(payer_types),
        traffic_types=tuple(traffic_types),
        platform_names=tuple(platform_names),
        attempt_groups=tuple(attempt_groups),
    ), MetricSelection(
        metric_name=selected_metric_name,
        calculation_method=selected_calculation_method,
        min_observations=int(min_observations),
    )


def _render_heatmap(heatmap_table: pd.DataFrame, metric_values: pd.DataFrame) -> None:
    st.subheader("Metric value by level cohort and date")
    if heatmap_table.empty:
        st.info("No rows match the current filters.")
        return

    value_count_table = _aligned_heatmap_table(metric_values, "value_count", heatmap_table)
    sample_count_table = _aligned_heatmap_table(metric_values, "sample_count", heatmap_table)
    low_sample_table = _aligned_heatmap_table(metric_values, "is_low_sample", heatmap_table)
    low_sample_mask = low_sample_table.fillna(False).astype(bool)
    customdata = _heatmap_custom_data(
        heatmap_table,
        value_count_table,
        sample_count_table,
        low_sample_mask,
    )

    x_values = pd.to_datetime(heatmap_table.columns).to_pydatetime()
    y_values = heatmap_table.index.astype(int).tolist()
    height = min(
        max(MIN_HEATMAP_HEIGHT, len(y_values) * HEATMAP_ROW_HEIGHT),
        MAX_HEATMAP_HEIGHT,
    )

    figure = go.Figure(
        data=go.Heatmap(
            z=heatmap_table.to_numpy(),
            x=x_values,
            y=y_values,
            colorscale=[
                [0.0, "#1f6fae"],
                [0.5, "#edf3f4"],
                [1.0, "#d47a00"],
            ],
            colorbar={
                "title": {"text": "Metric value", "font": {"color": "#eef3f7"}},
                "tickfont": {"color": "#d7dee6"},
            },
            customdata=customdata,
            hovertemplate=(
                "Level cohort: %{y}<br>"
                "Date: %{x|%Y-%m-%d}<br>"
                "Value: %{z:.3f}<br>"
                "Metric count: %{customdata[0]:,.0f}<br>"
                "Sample count: %{customdata[1]:,.0f}<br>"
                "Sample status: %{customdata[2]}<extra></extra>"
            ),
            xgap=0,
            ygap=0,
            zsmooth=False,
        )
    )
    if low_sample_mask.any().any():
        low_sample_z = low_sample_mask.astype(float).where(low_sample_mask)
        figure.add_trace(
            go.Heatmap(
                z=low_sample_z.to_numpy(),
                x=x_values,
                y=y_values,
                colorscale=[[0.0, "#6b7280"], [1.0, "#6b7280"]],
                customdata=customdata,
                hovertemplate=(
                    "Level cohort: %{y}<br>"
                    "Date: %{x|%Y-%m-%d}<br>"
                    "Value: %{customdata[3]:.3f}<br>"
                    "Metric count: %{customdata[0]:,.0f}<br>"
                    "Sample count: %{customdata[1]:,.0f}<br>"
                    "Sample status: %{customdata[2]}<extra></extra>"
                ),
                opacity=0.88,
                showscale=False,
                xgap=0,
                ygap=0,
                zmin=0,
                zmax=1,
            )
        )
    figure.update_layout(
        dragmode="zoom",
        font={"color": "#d7dee6"},
        height=height,
        margin={"l": 56, "r": 24, "t": 8, "b": 48},
        modebar={"activecolor": "#d47a00", "color": "#9fb2c0"},
        paper_bgcolor="#0f171d",
        plot_bgcolor="#0b1117",
    )
    figure.update_xaxes(
        dtick="M1",
        fixedrange=False,
        showgrid=False,
        tickformat="%b %Y",
        title="Date",
        zeroline=False,
    )
    figure.update_yaxes(
        dtick=100,
        fixedrange=False,
        range=[min(y_values) - 5, max(y_values) + 5],
        showgrid=False,
        title="Level cohort",
        zeroline=False,
    )
    st.plotly_chart(
        figure,
        use_container_width=True,
        config={
            "displayModeBar": True,
            "displaylogo": False,
            "doubleClick": "reset",
            "scrollZoom": True,
        },
    )


def _aligned_heatmap_table(
    metric_values: pd.DataFrame,
    value_column: str,
    template: pd.DataFrame,
) -> pd.DataFrame:
    table = prepare_heatmap_table(metric_values, value_column)
    return table.reindex(index=template.index, columns=template.columns)


def _heatmap_custom_data(
    heatmap_table: pd.DataFrame,
    value_count_table: pd.DataFrame,
    sample_count_table: pd.DataFrame,
    low_sample_mask: pd.DataFrame,
):
    return [
        [
            [
                value_count_table.iloc[row_index, column_index],
                sample_count_table.iloc[row_index, column_index],
                "low sample" if low_sample_mask.iloc[row_index, column_index] else "ok",
                heatmap_table.iloc[row_index, column_index],
            ]
            for column_index in range(len(value_count_table.columns))
        ]
        for row_index in range(len(value_count_table.index))
    ]


def _coerce_date_range(value: Any, default_start: date, default_end: date) -> tuple[date, date]:
    if isinstance(value, tuple | list) and len(value) == 2:
        return value[0], value[1]
    return default_start, default_end


def _apply_page_style() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background: #0f171d;
            color: #edf2f5;
        }
        [data-testid="stSidebar"] {
            background: #111b22;
            border-right: 1px solid #22313b;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
