"""Streamlit UI for the Match-3 progression heatmap dashboard."""

from __future__ import annotations

import os
from datetime import date
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from progression_heatmap.config import AppConfig, load_config
from progression_heatmap.data_sources import load_raw_attempts_from_config
from progression_heatmap.filters import (
    MetricSelection,
    PreAggregationFilters,
    collect_raw_filter_options,
)
from progression_heatmap.heatmap import prepare_heatmap_table
from progression_heatmap.metrics import (
    aggregate_statistics,
    calculation_methods_for_metric,
    metric_names,
    select_metric_values,
    to_pandas_frame,
)

MIN_HEATMAP_HEIGHT = 560
MAX_HEATMAP_HEIGHT = 980
HEATMAP_ROW_HEIGHT = 9


def main() -> None:
    config = load_config(os.environ.get("PROGRESSION_HEATMAP_CONFIG"))
    st.set_page_config(page_title=config.app_title, layout="wide")
    _apply_page_style()

    filter_options = _load_filter_options(config)
    pre_filters, metric_selection = _render_filters(filter_options)
    statistics = _compute_statistics(config, pre_filters)
    metric_values = select_metric_values(statistics, metric_selection)
    metric_values = to_pandas_frame(metric_values)
    heatmap_table = prepare_heatmap_table(metric_values)

    if config.production_simulation:
        st.warning("Production simulation config: local CSV only, no production connection.")

    _render_heatmap(heatmap_table)

    with st.expander("Grouped metric rows", expanded=False):
        st.dataframe(metric_values, width="stretch", hide_index=True)


@st.cache_data(show_spinner="Loading raw filter values...")
def _load_filter_options(config: AppConfig):
    raw_data = load_raw_attempts_from_config(config)
    return collect_raw_filter_options(raw_data)


@st.cache_data(show_spinner="Grouping raw attempt data...")
def _compute_statistics(config: AppConfig, pre_filters: PreAggregationFilters) -> pd.DataFrame:
    raw_data = load_raw_attempts_from_config(config)
    statistics = aggregate_statistics(raw_data, pre_filters)
    return to_pandas_frame(statistics)


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

    payer_types = st.sidebar.multiselect(
        "Payer type",
        filter_options.payer_types,
        default=filter_options.payer_types,
    )
    traffic_types = st.sidebar.multiselect(
        "Traffic type",
        filter_options.traffic_types,
        default=filter_options.traffic_types,
    )
    platform_names = st.sidebar.multiselect(
        "Platform",
        filter_options.platform_names,
        default=filter_options.platform_names,
    )

    selected_metric_name = st.sidebar.selectbox("Metric name", metric_names())
    methods = calculation_methods_for_metric(selected_metric_name)
    default_method_index = methods.index("relative") if "relative" in methods else 0
    selected_calculation_method = st.sidebar.selectbox(
        "Calculation method",
        methods,
        index=default_method_index,
    )

    return PreAggregationFilters(
        level_min=level_range[0],
        level_max=level_range[1],
        start_date=start_date,
        end_date=end_date,
        payer_types=tuple(payer_types),
        traffic_types=tuple(traffic_types),
        platform_names=tuple(platform_names),
    ), MetricSelection(
        metric_name=selected_metric_name,
        calculation_method=selected_calculation_method,
    )


def _render_heatmap(heatmap_table: pd.DataFrame) -> None:
    st.subheader("Metric value by level cohort and date")
    if heatmap_table.empty:
        st.info("No rows match the current filters.")
        return

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
            hovertemplate=(
                "Level cohort: %{y}<br>"
                "Date: %{x|%Y-%m-%d}<br>"
                "Value: %{z:.3f}<extra></extra>"
            ),
            xgap=0,
            ygap=0,
            zsmooth=False,
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
        width="stretch",
        config={
            "displayModeBar": True,
            "displaylogo": False,
            "doubleClick": "reset",
            "scrollZoom": True,
        },
    )


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
