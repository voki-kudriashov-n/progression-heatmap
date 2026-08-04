"""Streamlit UI for the Match-3 progression heatmap dashboard."""

from __future__ import annotations

import base64
import hashlib
import inspect
import logging
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from time import perf_counter
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from progression_heatmap.config import PROJECT_ROOT, AppConfig, load_config
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
ASSETS_DIR = PROJECT_ROOT / "assets"
PROJECT_ICONS: dict[str, Path] = {
    "MM": ASSETS_DIR / "mm_icon.png",
    "MyM": ASSETS_DIR / "mym_icon.png",
}


@dataclass(frozen=True, slots=True)
class ProjectTheme:
    """UI theme colors for one project selector state."""

    page_background: str
    sidebar_background: str
    sidebar_border: str
    panel_background: str
    control_background: str
    control_border: str
    control_hover: str
    accent_background: str
    accent_text: str
    text_color: str
    muted_text_color: str


PROJECT_THEMES: dict[str, ProjectTheme] = {
    "MM": ProjectTheme(
        page_background="#201412",
        sidebar_background="#4b1f1d",
        sidebar_border="#8a3a2f",
        panel_background="#3a1a17",
        control_background="#251311",
        control_border="#8a3a2f",
        control_hover="#f0c36a",
        accent_background="#f0c36a",
        accent_text="#2a130f",
        text_color="#f8e6bf",
        muted_text_color="#d7b77a",
    ),
    "MyM": ProjectTheme(
        page_background="#f5f8ff",
        sidebar_background="#ffffff",
        sidebar_border="#cad8f0",
        panel_background="#edf3ff",
        control_background="#ffffff",
        control_border="#b9c9e8",
        control_hover="#4f70ba",
        accent_background="#4f70ba",
        accent_text="#ffffff",
        text_color="#172642",
        muted_text_color="#5d7096",
    ),
}


def main() -> None:
    _configure_logging()
    config_path = os.environ.get("PROGRESSION_HEATMAP_CONFIG")
    LOGGER.info("app.start config_path=%s", config_path or "<default>")
    config = load_config(config_path)
    st.set_page_config(page_title=config.app_title, layout="wide")

    project_key = _render_project_selector(config)
    _apply_page_style(_project_theme(project_key))
    data_source = resolve_data_source(config)
    LOGGER.info(
        "app.config.loaded environment=%s source=%s project=%s table=%s",
        config.environment,
        data_source,
        project_key,
        _configured_databricks_table(config, project_key),
    )
    try:
        filter_started_at = perf_counter()
        filter_options = _load_filter_options(config, project_key)
        LOGGER.info(
            "app.filter_options.ui_ready project=%s elapsed_seconds=%.3f",
            project_key,
            perf_counter() - filter_started_at,
        )
        pre_filters, metric_selection = _render_filters(filter_options)
        statistics_started_at = perf_counter()
        statistics = _compute_statistics(config, project_key, pre_filters)
        LOGGER.info(
            "app.statistics.ui_ready project=%s rows=%s elapsed_seconds=%.3f",
            project_key,
            len(statistics),
            perf_counter() - statistics_started_at,
        )
    except DatabricksDataAccessError as exc:
        _render_databricks_data_access_error(exc)
        return
    except Exception as exc:
        LOGGER.exception("app.error project=%s source=%s", project_key, data_source)
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
    if not config.projects:
        return config.default_project

    project_keys = config.project_keys
    selected_key = st.session_state.get("selected_project_key")
    if selected_key not in project_keys:
        selected_key = (
            config.default_project if config.default_project in project_keys else project_keys[0]
        )
        st.session_state.selected_project_key = selected_key

    with st.sidebar:
        st.header("Project")
        columns = st.columns(len(project_keys))
        for column, project_key in zip(columns, project_keys, strict=False):
            project = config.project(project_key)
            with column:
                icon_path = PROJECT_ICONS.get(project_key)
                if icon_path is not None and icon_path.exists():
                    _render_project_icon(icon_path)
                button_type = "primary" if project_key == selected_key else "secondary"
                if st.button(
                    project.display_name,
                    key=f"project_selector_{project_key}",
                    type=button_type,
                    **_stretch_width_kwargs(st.button),
                ):
                    st.session_state.selected_project_key = project_key
                    st.rerun()

    return str(st.session_state.selected_project_key)


def _render_project_icon(icon_path: Path) -> None:
    encoded_icon = base64.b64encode(icon_path.read_bytes()).decode("ascii")
    st.markdown(
        f'<img class="project-selector-icon" src="data:image/png;base64,{encoded_icon}" alt="" />',
        unsafe_allow_html=True,
    )


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
    st.sidebar.caption(f"{level_range[0]} - {level_range[1]}")

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

    attempt_groups = _render_checkbox_filter_group(
        "Attempt group",
        filter_options.attempt_groups,
        "attempt_group",
    )
    platform_names = _render_checkbox_filter_group(
        "Platform",
        filter_options.platform_names,
        "platform",
    )
    traffic_types = _render_checkbox_filter_group(
        "Traffic type",
        filter_options.traffic_types,
        "traffic_type",
    )
    payer_types = _render_checkbox_filter_group(
        "Payer type",
        filter_options.payer_types,
        "payer_type",
    )

    selected_metric_name = _render_radio_filter("Metric", tuple(metric_names()), "metric_name")
    methods = calculation_methods_for_metric(selected_metric_name)
    default_method_index = methods.index("relative") if "relative" in methods else 0
    selected_calculation_method = _render_radio_filter(
        "Calculation method",
        tuple(methods),
        f"calculation_method_{selected_metric_name}",
        default_index=default_method_index,
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


def _render_checkbox_filter_group(
    label: str,
    options: tuple[str, ...],
    key_prefix: str,
) -> tuple[str, ...]:
    option_list = tuple(str(option) for option in options)
    if not option_list:
        return ()

    selected_count = sum(
        bool(st.session_state.get(_checkbox_filter_key(key_prefix, option), True))
        for option in option_list
    )
    selected_options = []
    with st.sidebar.expander(f"{label} ({selected_count}/{len(option_list)})", expanded=False):
        for option in option_list:
            if st.checkbox(
                option,
                value=True,
                key=_checkbox_filter_key(key_prefix, option),
            ):
                selected_options.append(option)
    return tuple(selected_options)


def _checkbox_filter_key(key_prefix: str, option: str) -> str:
    option_digest = hashlib.sha1(option.encode("utf-8")).hexdigest()[:12]
    return f"filter_{key_prefix}_{option_digest}"


def _render_radio_filter(
    label: str,
    options: tuple[str, ...],
    key_prefix: str,
    default_index: int = 0,
) -> str:
    option_list = tuple(str(option) for option in options)
    if not option_list:
        msg = f"No options available for {label!r}."
        raise ValueError(msg)

    state_key = f"filter_{key_prefix}_selection"
    if st.session_state.get(state_key) not in option_list:
        st.session_state[state_key] = option_list[default_index]

    selected_value = str(st.session_state[state_key])
    with st.sidebar.expander(f"{label}: {selected_value}", expanded=False):
        selected_value = st.radio(
            label,
            option_list,
            key=state_key,
            label_visibility="collapsed",
        )
    return str(selected_value)


def _render_heatmap(heatmap_table: pd.DataFrame, metric_values: pd.DataFrame) -> None:
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
        **_stretch_width_kwargs(st.plotly_chart),
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


def _project_theme(project_key: str) -> ProjectTheme:
    return PROJECT_THEMES.get(project_key, PROJECT_THEMES["MM"])


def _stretch_width_kwargs(component: Any) -> dict[str, bool | str]:
    if "width" in inspect.signature(component).parameters:
        return {"width": "stretch"}
    return {"use_container_width": True}


def _apply_page_style(theme: ProjectTheme) -> None:
    st.markdown(
        f"""
        <style>
        .stApp {{
            background: {theme.page_background};
            color: {theme.text_color};
        }}
        [data-testid="stSidebar"] {{
            background: {theme.sidebar_background};
            border-right: 1px solid {theme.sidebar_border};
        }}
        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3,
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] span {{
            color: {theme.text_color};
        }}
        [data-testid="stSidebar"] small,
        [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {{
            color: {theme.muted_text_color};
        }}
        .project-selector-icon {{
            border-radius: 6px;
            display: block;
            height: 36px;
            margin: 0 auto 0.25rem auto;
            object-fit: contain;
            width: 36px;
        }}
        [data-testid="stSidebar"] .stButton > button {{
            background: {theme.control_background};
            border: 1px solid {theme.control_border};
            border-radius: 6px;
            color: {theme.text_color};
            min-height: 2.15rem;
            padding: 0.2rem 0.45rem;
        }}
        [data-testid="stSidebar"] .stButton > button:hover {{
            border-color: {theme.control_hover};
            color: {theme.text_color};
        }}
        [data-testid="stSidebar"] .stButton > button[kind="primary"] {{
            background: {theme.accent_background};
            border-color: {theme.accent_background};
            color: {theme.accent_text};
            font-weight: 700;
        }}
        [data-testid="stSidebar"] .stButton > button[kind="primary"] p {{
            color: {theme.accent_text};
        }}
        [data-testid="stSidebar"] [data-testid="stExpander"] {{
            background: {theme.panel_background};
            border: 1px solid {theme.sidebar_border};
            border-radius: 6px;
        }}
        [data-testid="stSidebar"] [data-testid="stExpander"] summary {{
            min-height: 2.4rem;
        }}
        [data-testid="stSidebar"] .stCheckbox label,
        [data-testid="stSidebar"] .stRadio label {{
            align-items: flex-start;
        }}
        [data-testid="stSidebar"] .stCheckbox label p,
        [data-testid="stSidebar"] .stRadio label p,
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {{
            overflow-wrap: anywhere;
            white-space: normal;
        }}
        [data-testid="stSidebar"] [data-baseweb="input"] input {{
            background: {theme.control_background};
            color: {theme.text_color};
        }}
        [data-testid="stSidebar"] [data-testid="stSliderThumbValue"],
        [data-testid="stSidebar"] [data-testid="stSliderTickBar"] {{
            display: none;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
