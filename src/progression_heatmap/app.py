"""Streamlit UI for the Match-3 progression heatmap dashboard."""

from __future__ import annotations

import base64
import hashlib
import html
import inspect
import logging
import os
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import quote

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
from progression_heatmap.filters import (
    DisplayFilters,
    MetricSelection,
    PreAggregationFilters,
    apply_grouped_display_filters,
)
from progression_heatmap.gradient_range import gradient_range
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
STATISTICS_CACHE_MAX_ENTRIES = 10
WORKSPACE_BACKGROUND = "#000000"
CHART_TEXT_COLOR = "#d7dee6"
MIN_OBSERVATIONS_DEFAULT = 0
HEATMAP_COLORSCALE = (
    (0.0, "#1f6fae"),
    (0.5, "#edf3f4"),
    (1.0, "#d47a00"),
)
LOGGER = logging.getLogger(__name__)
ASSETS_DIR = PROJECT_ROOT / "assets"
PROJECT_ICONS: dict[str, Path] = {
    "MM": ASSETS_DIR / "mm_icon.png",
    "MyM": ASSETS_DIR / "mym_icon.png",
}
ATTEMPT_GROUP_LABELS = {
    "1 attempt": "1 попытка",
    "2+ attempts": "2+ попытки",
}
BOOLEAN_LABELS = {
    True: "Да",
    False: "Нет",
}
METRIC_LABELS = {
    "CF": "CF",
    "CW": "CW",
    "FF": "FF",
    "FW": "FW",
    "attempts": "Попытки",
    "attempt": "Средняя попытка",
    "failed": "Проигрыши",
    "wins": "Победы",
    "fail_rate": "% проигрышей",
    "win_rate": "% побед",
    "first_attempt": "Первые попытки",
}
CALCULATION_METHOD_LABELS = {
    "absolute": "Абсолютное",
    "relative": "Процент",
    "partial_relative": "Процент внутри исхода",
    "average": "Среднее",
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


@dataclass(frozen=True, slots=True)
class ChartRequest:
    """Filter state that has been applied to the rendered chart."""

    aggregation_filters: PreAggregationFilters
    display_filters: DisplayFilters
    metric_selection: MetricSelection


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
        page_background="#eef5ff",
        sidebar_background="#eef5ff",
        sidebar_border="#4f70ba",
        panel_background="#dce9ff",
        control_background="#ffffff",
        control_border="#4f70ba",
        control_hover="#244f9e",
        accent_background="#4f70ba",
        accent_text="#ffffff",
        text_color="#18386a",
        muted_text_color="#4f70ba",
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
    chart_slot = st.empty()
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
        with st.sidebar:
            with st.spinner("Загрузка фильтров..."):
                filter_options = _load_filter_options(config, project_key)
        LOGGER.info(
            "app.filter_options.ui_ready project=%s elapsed_seconds=%.3f",
            project_key,
            perf_counter() - filter_started_at,
        )
        draft_request, apply_requested = _render_filters(filter_options)
        if apply_requested:
            _applied_chart_requests()[project_key] = draft_request

        chart_request = _applied_chart_requests().get(project_key)
        if chart_request is None:
            with chart_slot.container():
                st.info("Выберите фильтры и нажмите «Применить», чтобы построить heatmap.")
            return

        statistics_started_at = perf_counter()
        loading_message = "Обновление heatmap..." if apply_requested else "Загрузка heatmap..."
        with chart_slot.container():
            loading_context = st.spinner(loading_message) if apply_requested else nullcontext()
            with loading_context:
                statistics = _compute_statistics(
                    config,
                    project_key,
                    chart_request.aggregation_filters,
                )
                display_statistics = apply_grouped_display_filters(
                    statistics,
                    chart_request.display_filters,
                )
                LOGGER.info(
                    "app.statistics.display_filtered project=%s rows=%s display_filters=%s",
                    project_key,
                    len(display_statistics),
                    chart_request.display_filters,
                )
                metric_values = select_metric_values_with_context(
                    display_statistics,
                    chart_request.metric_selection,
                )
                metric_values = to_pandas_frame(metric_values)
                heatmap_table = prepare_heatmap_table(metric_values, "value")
                LOGGER.info(
                    "app.render_heatmap.ready project=%s metric_rows=%s "
                    "heatmap_rows=%s heatmap_columns=%s",
                    project_key,
                    len(metric_values),
                    len(heatmap_table.index),
                    len(heatmap_table.columns),
                )

                if config.production_simulation and resolve_data_source(config) == "csv":
                    st.warning("Для этой конфигурации активен локальный CSV.")

                _render_heatmap(
                    heatmap_table,
                    metric_values,
                    color_range_key=_chart_request_digest(project_key, chart_request),
                )
        LOGGER.info(
            "app.statistics.ui_ready project=%s rows=%s elapsed_seconds=%.3f "
            "aggregation_filters=%s",
            project_key,
            len(statistics),
            perf_counter() - statistics_started_at,
            chart_request.aggregation_filters,
        )
    except DatabricksDataAccessError as exc:
        with chart_slot.container():
            _render_databricks_data_access_error(exc)
        return
    except Exception as exc:
        LOGGER.exception("app.error project=%s source=%s", project_key, data_source)
        with chart_slot.container():
            _render_unexpected_error(exc)
        return


@st.cache_data(show_spinner=False)
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


@st.cache_data(
    show_spinner=False,
    max_entries=STATISTICS_CACHE_MAX_ENTRIES,
)
def _compute_statistics(
    config: AppConfig,
    project_key: str,
    aggregation_filters: PreAggregationFilters,
) -> pd.DataFrame:
    started_at = perf_counter()
    source = resolve_data_source(config)
    LOGGER.info(
        "app.statistics.start source=%s project=%s table=%s aggregation_filters=%s",
        source,
        project_key,
        _configured_databricks_table(config, project_key),
        aggregation_filters,
    )
    try:
        statistics = aggregate_statistics_from_config(config, project_key, aggregation_filters)
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
    query_project_key = _query_project_key(project_keys)
    selected_key = query_project_key or st.session_state.get("selected_project_key")
    if selected_key not in project_keys:
        selected_key = (
            config.default_project if config.default_project in project_keys else project_keys[0]
        )
    st.session_state.selected_project_key = selected_key

    with st.sidebar:
        st.markdown(
            _project_selector_html(config, selected_key),
            unsafe_allow_html=True,
        )

    return str(st.session_state.selected_project_key)


def _query_project_key(project_keys: tuple[str, ...]) -> str | None:
    raw_project_key = st.query_params.get("project")
    if isinstance(raw_project_key, list):
        raw_project_key = raw_project_key[0] if raw_project_key else None
    if raw_project_key in project_keys:
        return str(raw_project_key)
    return None


def _project_selector_html(config: AppConfig, selected_key: str) -> str:
    links = []
    for project_key in config.project_keys:
        project = config.project(project_key)
        icon_path = PROJECT_ICONS.get(project_key)
        if icon_path is None or not icon_path.exists():
            continue
        selected_class = " selected" if project_key == selected_key else ""
        label = html.escape(project.display_name, quote=True)
        links.append(
            f'<a class="project-selector-link{selected_class}" '
            f'href="?project={quote(project_key)}" title="{label}" aria-label="{label}">'
            f'<img src="{_project_icon_data_url(icon_path)}" alt="" />'
            "</a>"
        )
    return f'<nav class="project-switcher" aria-label="Game">{"".join(links)}</nav>'


def _project_icon_data_url(icon_path: Path) -> str:
    encoded_icon = base64.b64encode(icon_path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded_icon}"


def _applied_chart_requests() -> dict[str, ChartRequest]:
    state_key = "applied_chart_requests_by_project"
    if state_key not in st.session_state:
        st.session_state[state_key] = {}
    return st.session_state[state_key]


def _chart_request_digest(project_key: str, chart_request: ChartRequest) -> str:
    raw_key = f"{project_key}:{chart_request!r}"
    return hashlib.sha1(raw_key.encode("utf-8")).hexdigest()[:12]


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
    st.error("Приложение не может прочитать источник Databricks SQL.")
    st.write(
        "Databricks App работает от имени своего service principal. Доступ из ноутбука "
        "под вашим пользователем не выдает приложению доступ к Unity Catalog автоматически."
    )
    if error.is_gateway_error:
        st.info(
            "SQL connector получил 502/Bad Gateway. Проверьте App logs по маркерам "
            "`databricks_sql.*.connect.start`, `execute.start` и `fetch.start`. "
            "Особенно важны `host_kind`, `http_path` и последний маркер перед ошибкой."
        )
    if error.is_permission_error:
        st.info(
            "Выдайте app service principal права `USE CATALOG`, `USE SCHEMA` и `SELECT` "
            f"на `{error.table_name}`. Для SQL warehouse также нужно право `Can use`."
        )
    with st.expander("Ошибка Databricks", expanded=False):
        st.code(f"{error.original_error_class}: {error.original_message}")


def _render_unexpected_error(error: Exception) -> None:
    st.error("При загрузке данных произошла непредвиденная ошибка.")
    marker = "app.error"
    st.write(f"Проверьте Databricks App logs и traceback возле маркера `{marker}`.")
    with st.expander("Детали ошибки", expanded=False):
        st.code(f"{error.__class__.__name__}: {error}")


def _render_filters(
    filter_options,
) -> tuple[ChartRequest, bool]:
    with st.sidebar.form("filters_form", border=False):
        st.markdown('<div class="filters-title">Фильтры</div>', unsafe_allow_html=True)

        st.markdown('<div class="filters-section-title">Вид</div>', unsafe_allow_html=True)
        st.markdown('<div class="filter-field-title">Когорта уровней</div>', unsafe_allow_html=True)
        min_level_column, max_level_column = st.columns(2)
        with min_level_column:
            raw_level_min = st.number_input(
                "Мин.",
                min_value=filter_options.level_min,
                max_value=filter_options.level_max,
                value=filter_options.level_min,
                step=1,
            )
        with max_level_column:
            raw_level_max = st.number_input(
                "Макс.",
                min_value=filter_options.level_min,
                max_value=filter_options.level_max,
                value=filter_options.level_max,
                step=1,
            )
        level_min = min(int(raw_level_min), int(raw_level_max))
        level_max = max(int(raw_level_min), int(raw_level_max))

        selected_dates = st.date_input(
            "Даты",
            value=(filter_options.date_min, filter_options.date_max),
            min_value=filter_options.date_min,
            max_value=filter_options.date_max,
        )
        start_date, end_date = _coerce_date_range(
            selected_dates,
            filter_options.date_min,
            filter_options.date_max,
        )

        st.markdown(
            '<div class="filters-section-title">Сегменты</div>',
            unsafe_allow_html=True,
        )
        attempt_groups = _render_checkbox_filter_group(
            "Попытки",
            filter_options.attempt_groups,
            "attempt_group",
            format_func=_attempt_group_label,
        )
        platform_names = _render_checkbox_filter_group(
            "Платформа",
            filter_options.platform_names,
            "platform",
        )
        traffic_types = _render_checkbox_filter_group(
            "Тип трафика",
            filter_options.traffic_types,
            "traffic_type",
        )
        payer_types = _render_checkbox_filter_group(
            "Тип игрока",
            filter_options.payer_types,
            "payer_type",
        )
        super_ball_values = _render_checkbox_filter_group(
            "ДРШ активирован",
            filter_options.super_ball_values,
            "super_ball",
            format_func=_boolean_label,
        )

        st.markdown('<div class="filters-section-title">Величина</div>', unsafe_allow_html=True)
        selected_metric_name = _render_radio_filter(
            "Величина",
            tuple(metric_names()),
            "metric_name",
            format_func=_metric_label,
        )
        methods = calculation_methods_for_metric(selected_metric_name)
        default_method_index = methods.index("relative") if "relative" in methods else 0
        selected_calculation_method = _render_radio_filter(
            "Расчет",
            tuple(methods),
            f"calculation_method_{selected_metric_name}",
            default_index=default_method_index,
            format_func=_calculation_method_label,
        )
        min_observations = MIN_OBSERVATIONS_DEFAULT
        if selected_calculation_method in {"relative", "partial_relative"}:
            min_observations = st.number_input(
                "Минимум наблюдений",
                min_value=0,
                max_value=10_000_000,
                value=MIN_OBSERVATIONS_DEFAULT,
                step=100,
            )

        apply_requested = st.form_submit_button(
            "Применить",
            type="primary",
            **_stretch_width_kwargs(st.form_submit_button),
        )

    return ChartRequest(
        aggregation_filters=PreAggregationFilters(
            payer_types=_aggregation_filter_values(payer_types, filter_options.payer_types),
            traffic_types=_aggregation_filter_values(traffic_types, filter_options.traffic_types),
            platform_names=_aggregation_filter_values(
                platform_names,
                filter_options.platform_names,
            ),
            attempt_groups=_aggregation_filter_values(
                attempt_groups,
                filter_options.attempt_groups,
            ),
            super_ball_values=_aggregation_filter_values(
                super_ball_values,
                filter_options.super_ball_values,
            ),
        ),
        display_filters=DisplayFilters(
            level_min=level_min,
            level_max=level_max,
            start_date=start_date,
            end_date=end_date,
        ),
        metric_selection=MetricSelection(
            metric_name=selected_metric_name,
            calculation_method=selected_calculation_method,
            min_observations=int(min_observations),
        ),
    ), apply_requested


def _aggregation_filter_values(
    selected_options: tuple[Any, ...],
    all_options: tuple[Any, ...],
) -> tuple[Any, ...]:
    selected_set = set(selected_options)
    if not selected_set or selected_set == set(all_options):
        return ()
    return tuple(option for option in all_options if option in selected_set)


def _attempt_group_label(value: str) -> str:
    return ATTEMPT_GROUP_LABELS.get(value, value)


def _boolean_label(value: bool) -> str:
    return BOOLEAN_LABELS.get(value, str(value))


def _metric_label(value: str) -> str:
    return METRIC_LABELS.get(value, value)


def _calculation_method_label(value: str) -> str:
    return CALCULATION_METHOD_LABELS.get(value, value)


def _render_checkbox_filter_group(
    label: str,
    options: tuple[Any, ...],
    key_prefix: str,
    format_func: Any = str,
) -> tuple[Any, ...]:
    option_list = tuple(options)
    if not option_list:
        return ()

    selected_options = []
    with st.expander(label, expanded=False):
        for option in option_list:
            if st.checkbox(
                format_func(option),
                value=True,
                key=_checkbox_filter_key(key_prefix, option),
            ):
                selected_options.append(option)
    return tuple(selected_options)


def _checkbox_filter_key(key_prefix: str, option: Any) -> str:
    option_digest = hashlib.sha1(str(option).encode("utf-8")).hexdigest()[:12]
    return f"filter_{key_prefix}_{option_digest}"


def _render_radio_filter(
    label: str,
    options: tuple[str, ...],
    key_prefix: str,
    default_index: int = 0,
    format_func: Any = str,
) -> str:
    option_list = tuple(str(option) for option in options)
    if not option_list:
        msg = f"No options available for {label!r}."
        raise ValueError(msg)

    state_key = f"filter_{key_prefix}_selection"
    if st.session_state.get(state_key) not in option_list:
        st.session_state[state_key] = option_list[default_index]

    selected_value = str(st.session_state[state_key])
    with st.expander(label, expanded=False):
        selected_value = st.radio(
            label,
            option_list,
            key=state_key,
            label_visibility="collapsed",
            format_func=format_func,
        )
    return str(selected_value)


def _render_heatmap(
    heatmap_table: pd.DataFrame,
    metric_values: pd.DataFrame,
    color_range_key: str = "default",
) -> None:
    if heatmap_table.empty:
        st.info("Под текущие фильтры не попали строки.")
        return

    value_count_table = _aligned_heatmap_table(metric_values, "value_count", heatmap_table)
    sample_count_table = _aligned_heatmap_table(metric_values, "sample_count", heatmap_table)
    low_sample_table = _aligned_heatmap_table(metric_values, "is_low_sample", heatmap_table)
    low_sample_mask = low_sample_table.fillna(False).astype(bool)
    display_heatmap_table = heatmap_table.mask(low_sample_mask)

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
    plot_area_height = height - 56

    chart_column, gradient_column = st.columns((0.90, 0.10), gap="small")
    with gradient_column:
        color_range = _render_gradient_range_control(
            display_heatmap_table,
            key=f"gradient_range_{color_range_key}",
            height=plot_area_height,
        )
    if color_range is None:
        st.info("Все ячейки скрыты из-за порога «Минимум наблюдений».")  # noqa: RUF001
        return

    figure = _heatmap_figure(
        display_heatmap_table,
        customdata,
        x_values,
        y_values,
        height,
        color_range,
    )
    with chart_column:
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


def _heatmap_figure(
    display_heatmap_table: pd.DataFrame,
    customdata,
    x_values,
    y_values: list[int],
    height: int,
    color_range: tuple[float, float],
) -> go.Figure:
    heatmap_kwargs = {}
    if color_range[0] < color_range[1]:
        heatmap_kwargs = {
            "zauto": False,
            "zmin": color_range[0],
            "zmax": color_range[1],
        }

    figure = go.Figure(
        data=go.Heatmap(
            z=display_heatmap_table.to_numpy(),
            x=x_values,
            y=y_values,
            colorscale=list(HEATMAP_COLORSCALE),
            customdata=customdata,
            hovertemplate=(
                "Когорта уровней: %{y}<br>"
                "Дата: %{x|%Y-%m-%d}<br>"
                "Значение: %{z:.3f}<br>"
                "Количество величины: %{customdata[0]:,.0f}<br>"
                "Наблюдения: %{customdata[1]:,.0f}<br>"
                "Статус выборки: %{customdata[2]}<extra></extra>"
            ),
            showscale=False,
            xgap=0,
            ygap=0,
            zsmooth=False,
            **heatmap_kwargs,
        )
    )
    figure.update_layout(
        dragmode="zoom",
        font={"color": CHART_TEXT_COLOR},
        height=height,
        margin={"l": 56, "r": 24, "t": 8, "b": 48},
        modebar={"activecolor": "#d47a00", "color": "#9fb2c0"},
        paper_bgcolor=WORKSPACE_BACKGROUND,
        plot_bgcolor=WORKSPACE_BACKGROUND,
    )
    figure.update_xaxes(
        dtick="M1",
        fixedrange=False,
        showgrid=False,
        tickformat="%b %Y",
        title="Дата",
        zeroline=False,
    )
    figure.update_yaxes(
        dtick=100,
        fixedrange=False,
        range=[min(y_values) - 5, max(y_values) + 5],
        showgrid=False,
        title="Когорта уровней",
        zeroline=False,
    )
    return figure


def _render_gradient_range_control(
    display_heatmap_table: pd.DataFrame,
    key: str,
    height: int,
) -> tuple[float, float] | None:
    bounds = _heatmap_value_bounds(display_heatmap_table)
    if bounds is None:
        return None

    minimum, maximum = bounds
    return gradient_range(
        minimum=minimum,
        maximum=maximum,
        value=bounds,
        colorscale=HEATMAP_COLORSCALE,
        height=height,
        key=key,
    )


def _heatmap_value_bounds(display_heatmap_table: pd.DataFrame) -> tuple[float, float] | None:
    values = pd.to_numeric(display_heatmap_table.stack(), errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.min()), float(values.max())


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
                "мало данных" if low_sample_mask.iloc[row_index, column_index] else "достаточно",
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
        [data-testid="stHeader"],
        [data-testid="stToolbar"],
        [data-testid="stStatusWidget"],
        [data-testid="stDecoration"],
        header {{
            display: none;
        }}
        [data-testid="stAppViewContainer"] {{
            padding-top: 0;
        }}
        .main .block-container {{
            background: {WORKSPACE_BACKGROUND};
            padding-top: 1rem;
        }}
        [data-testid="stAppViewContainer"],
        [data-testid="stMain"],
        [data-testid="stMainBlockContainer"],
        .main {{
            background: {WORKSPACE_BACKGROUND};
        }}
        .stApp {{
            background: {WORKSPACE_BACKGROUND};
            color: {CHART_TEXT_COLOR};
        }}
        [data-testid="stPlotlyChart"] {{
            background: {WORKSPACE_BACKGROUND};
        }}
        [data-testid="stSidebar"] {{
            background: {theme.sidebar_background};
            border-right: 1px solid {theme.sidebar_border};
        }}
        [data-testid="stSidebar"] [data-testid="stSidebarContent"] {{
            padding: 0.8rem 1rem 1rem;
        }}
        [data-testid="stSidebar"] [data-testid="stSidebarHeader"] {{
            display: none;
        }}
        [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{
            gap: 0.45rem;
        }}
        [data-testid="stSidebar"] [data-testid="stElementContainer"] {{
            margin-bottom: 0.2rem;
        }}
        [data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.filters-title) {{
            margin-bottom: 0.45rem;
        }}
        [data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.filters-section-title) {{
            margin-bottom: 0.55rem;
            margin-top: 0.45rem;
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
        [data-testid="stSidebar"] .stButton button {{
            background: {theme.control_background};
            border: 1px solid {theme.control_border};
            border-radius: 6px;
            color: {theme.text_color};
            min-height: 2.15rem;
            padding: 0.2rem 0.45rem;
        }}
        [data-testid="stSidebar"] .stButton button:hover {{
            border-color: {theme.control_hover};
            color: {theme.text_color};
        }}
        [data-testid="stSidebar"] .stButton button[kind="primary"],
        [data-testid="stSidebar"] button[kind="primaryFormSubmit"],
        [data-testid="stSidebar"] [data-testid="stBaseButton-primaryFormSubmit"] {{
            background: {theme.accent_background};
            border-color: {theme.accent_background};
            color: {theme.accent_text};
            font-weight: 700;
        }}
        [data-testid="stSidebar"] .stButton button[kind="primary"] p,
        [data-testid="stSidebar"] button[kind="primaryFormSubmit"] p,
        [data-testid="stSidebar"] [data-testid="stBaseButton-primaryFormSubmit"] p {{
            color: {theme.accent_text};
        }}
        .project-switcher {{
            align-items: center;
            background: {theme.panel_background};
            border: 1px solid {theme.sidebar_border};
            border-radius: 8px;
            box-sizing: border-box;
            display: grid;
            gap: 0.25rem;
            grid-template-columns: repeat(2, 38px);
            justify-content: center;
            margin: 0 auto 0.75rem;
            padding: 0.25rem;
            width: min-content;
        }}
        .project-selector-link {{
            align-items: center;
            background: {theme.control_background};
            border: 1px solid transparent;
            border-radius: 5px;
            box-sizing: border-box;
            display: inline-flex;
            height: 38px;
            justify-content: center;
            transition: border-color 120ms ease, background 120ms ease;
            width: 38px;
        }}
        .project-selector-link:hover {{
            border-color: {theme.control_hover};
        }}
        .project-selector-link.selected {{
            background: {theme.accent_background};
            border-color: {theme.control_hover};
        }}
        .project-selector-link img {{
            border-radius: 4px;
            display: block;
            height: 28px;
            object-fit: contain;
            width: 28px;
        }}
        .filters-title {{
            color: {theme.text_color};
            font-size: 1.02rem;
            font-weight: 800;
            line-height: 1.2;
            margin: 0.1rem 0 0.55rem;
        }}
        .filters-section-title {{
            color: {theme.muted_text_color};
            display: block;
            font-size: 0.72rem;
            font-weight: 800;
            letter-spacing: 0;
            line-height: 1.2;
            margin: 0;
            padding: 0.1rem 0 0.45rem;
            text-transform: uppercase;
        }}
        .filter-field-title {{
            color: {theme.text_color};
            font-size: 0.92rem;
            font-weight: 700;
            line-height: 1.15;
            margin: 0 0 0.35rem;
        }}
        [data-testid="stSidebar"] [data-testid="stWidgetLabel"] {{
            margin-bottom: 0.2rem;
        }}
        [data-testid="stSidebar"] [data-testid="column"] {{
            min-width: 0;
        }}
        [data-testid="stSidebar"] [data-baseweb="input"] {{
            background: {theme.control_background};
            border-radius: 6px;
        }}
        [data-testid="stSidebar"] [data-testid="stExpander"] {{
            background: {theme.panel_background};
            border: 1px solid {theme.sidebar_border};
            border-radius: 6px;
            margin-top: 0.15rem;
        }}
        [data-testid="stSidebar"] [data-testid="stExpander"] summary {{
            min-height: 2.25rem;
            padding-bottom: 0.35rem;
            padding-top: 0.35rem;
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
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
