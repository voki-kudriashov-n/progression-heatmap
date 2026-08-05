import math

import pandas as pd

from progression_heatmap.app import (
    _aggregation_filter_values,
    _gradient_slider_format,
    _gradient_slider_step,
    _heatmap_value_bounds,
    _render_heatmap,
)


def test_aggregation_filter_values_normalize_all_selected_to_no_filter() -> None:
    all_options = ("android", "ios", "uwp")

    assert _aggregation_filter_values(all_options, all_options) == ()
    assert _aggregation_filter_values((), all_options) == ()
    assert _aggregation_filter_values(("ios", "android"), all_options) == ("android", "ios")


def test_render_heatmap_hides_low_sample_cells_without_overlay(monkeypatch) -> None:
    captured = {}

    def fake_plotly_chart(figure, **kwargs) -> None:
        captured["figure"] = figure
        captured["kwargs"] = kwargs

    monkeypatch.setattr("streamlit.plotly_chart", fake_plotly_chart)
    monkeypatch.setattr("streamlit.slider", lambda *args, **kwargs: (5.0, 15.0))

    heatmap_table = pd.DataFrame(
        [[10.0, 20.0, 30.0]],
        index=pd.Index([1], name="level_group"),
        columns=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
    )
    metric_values = pd.DataFrame(
        {
            "level_group": [1, 1, 1],
            "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
            "value": [10.0, 20.0, 30.0],
            "value_count": [10.0, 20.0, 30.0],
            "sample_count": [10.0, 20.0, 30.0],
            "is_low_sample": [True, False, False],
        }
    )

    _render_heatmap(heatmap_table, metric_values)

    figure = captured["figure"]
    assert len(figure.data) == 1
    assert math.isnan(figure.data[0].z[0][0])
    assert figure.data[0].z[0][1] == 20.0
    assert figure.data[0].z[0][2] == 30.0
    assert figure.data[0].zmin == 5.0
    assert figure.data[0].zmax == 15.0


def test_heatmap_value_bounds_ignore_hidden_cells() -> None:
    table = pd.DataFrame([[float("nan"), 20.0], [5.0, None]])

    assert _heatmap_value_bounds(table) == (5.0, 20.0)


def test_gradient_slider_uses_readable_steps_and_formats() -> None:
    assert _gradient_slider_step(0.0, 100.0) == 0.5
    assert _gradient_slider_format(0.0, 100.0) == "%.0f"
    assert _gradient_slider_step(0.0, 1.0) == 0.01
    assert _gradient_slider_format(0.0, 1.0) == "%.2f"
