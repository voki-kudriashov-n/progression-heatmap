import plotly.graph_objects as go

from progression_heatmap import plotly_chart


def test_plotly_html_uses_custom_smooth_wheel_zoom(monkeypatch) -> None:
    captured = {}

    def fake_to_html(figure, **kwargs) -> str:
        captured["figure"] = figure
        captured.update(kwargs)
        return '<div id="plot"></div>'

    monkeypatch.setattr(plotly_chart.pio, "to_html", fake_to_html)

    html = plotly_chart._plotly_html(go.Figure(), height=560)

    assert captured["config"]["scrollZoom"] is False
    assert captured["config"]["displayModeBar"] is True
    assert captured["full_html"] is False
    assert captured["include_plotlyjs"] is True
    assert 'addEventListener(\n    "wheel"' in captured["post_script"]
    assert "Plotly.relayout" in captured["post_script"]
    assert "height: 560px" in html
