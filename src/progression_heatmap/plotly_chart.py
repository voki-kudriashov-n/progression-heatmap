"""Plotly rendering helpers for Streamlit."""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go
import plotly.io as pio
import streamlit.components.v1 as components

_PLOTLY_CONFIG: dict[str, Any] = {
    "displayModeBar": True,
    "displaylogo": False,
    "doubleClick": "reset",
    "responsive": True,
    # Plotly's native wheel zoom is too jumpy on high-resolution touchpads.
    # A custom handler below keeps the interaction but clamps each frame.
    "scrollZoom": False,
}

_SMOOTH_TRACKPAD_ZOOM_SCRIPT = r"""
(function () {
  const graph = document.getElementById("{plot_id}");
  if (!graph || !window.Plotly) {
    return;
  }

  const MAX_FRAME_DELTA = 42;
  const ZOOM_SPEED = 0.0032;
  const MIN_X_SPAN_MS = 24 * 60 * 60 * 1000;
  const MIN_Y_SPAN = 1;

  let pendingDelta = 0;
  let pendingPointer = null;
  let pendingFrame = null;

  function clamp(value, lower, upper) {
    return Math.min(Math.max(value, lower), upper);
  }

  function plotRect() {
    const dragLayer = graph.querySelector(".nsewdrag");
    const rect = (dragLayer || graph).getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) {
      return rect;
    }
    return graph.getBoundingClientRect();
  }

  function normalizeWheelDelta(event) {
    let delta = event.deltaY;
    if (!Number.isFinite(delta) || delta === 0) {
      return 0;
    }
    if (event.deltaMode === WheelEvent.DOM_DELTA_LINE) {
      delta *= 16;
    } else if (event.deltaMode === WheelEvent.DOM_DELTA_PAGE) {
      delta *= window.innerHeight || 800;
    }
    return delta;
  }

  function axisValue(axis, value) {
    if (axis.type === "date") {
      const parsed = Date.parse(value);
      return Number.isFinite(parsed) ? parsed : null;
    }
    const numericValue = Number(value);
    return Number.isFinite(numericValue) ? numericValue : null;
  }

  function plotlyValue(axis, value) {
    if (axis.type === "date") {
      return new Date(value).toISOString();
    }
    return value;
  }

  function axisRange(axis) {
    if (!axis || !Array.isArray(axis.range) || axis.range.length < 2) {
      return null;
    }
    const start = axisValue(axis, axis.range[0]);
    const end = axisValue(axis, axis.range[1]);
    if (start === null || end === null || start === end) {
      return null;
    }
    return start < end ? [start, end] : [end, start];
  }

  function pointerState(event) {
    const fullLayout = graph._fullLayout || {};
    const xAxis = fullLayout.xaxis;
    const yAxis = fullLayout.yaxis;
    const xRange = axisRange(xAxis);
    const yRange = axisRange(yAxis);
    const rect = plotRect();
    if (!xRange || !yRange || rect.width <= 0 || rect.height <= 0) {
      return null;
    }

    const xRatio = clamp((event.clientX - rect.left) / rect.width, 0, 1);
    const yRatioFromTop = clamp((event.clientY - rect.top) / rect.height, 0, 1);
    const yRatio = 1 - yRatioFromTop;

    return {
      xAxis,
      yAxis,
      xRange,
      yRange,
      xRatio,
      yRatio,
      xCenter: xRange[0] + (xRange[1] - xRange[0]) * xRatio,
      yCenter: yRange[0] + (yRange[1] - yRange[0]) * yRatio,
    };
  }

  function scaledRange(range, center, ratio, factor, minimumSpan) {
    const span = range[1] - range[0];
    const nextSpan = Math.max(span * factor, minimumSpan);
    const boundedRatio = clamp(ratio, 0, 1);
    return [
      center - nextSpan * boundedRatio,
      center + nextSpan * (1 - boundedRatio),
    ];
  }

  function applyZoom() {
    pendingFrame = null;
    const pointer = pendingPointer;
    const delta = clamp(pendingDelta, -MAX_FRAME_DELTA, MAX_FRAME_DELTA);
    pendingDelta = 0;
    if (!pointer || delta === 0) {
      return;
    }

    const factor = clamp(Math.exp(delta * ZOOM_SPEED), 0.82, 1.22);
    const nextXRange = scaledRange(
      pointer.xRange,
      pointer.xCenter,
      pointer.xRatio,
      factor,
      MIN_X_SPAN_MS,
    );
    const nextYRange = scaledRange(
      pointer.yRange,
      pointer.yCenter,
      pointer.yRatio,
      factor,
      MIN_Y_SPAN,
    );

    window.Plotly.relayout(graph, {
      "xaxis.range[0]": plotlyValue(pointer.xAxis, nextXRange[0]),
      "xaxis.range[1]": plotlyValue(pointer.xAxis, nextXRange[1]),
      "yaxis.range[0]": plotlyValue(pointer.yAxis, nextYRange[0]),
      "yaxis.range[1]": plotlyValue(pointer.yAxis, nextYRange[1]),
    });
  }

  function scheduleZoom() {
    if (pendingFrame !== null) {
      return;
    }
    pendingFrame = window.requestAnimationFrame(applyZoom);
  }

  graph.addEventListener(
    "wheel",
    (event) => {
      const delta = normalizeWheelDelta(event);
      if (delta === 0) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      pendingDelta = clamp(pendingDelta + delta, -MAX_FRAME_DELTA, MAX_FRAME_DELTA);
      pendingPointer = pointerState(event) || pendingPointer;
      scheduleZoom();
    },
    { passive: false },
  );
})();
"""


def plotly_chart_with_smooth_trackpad_zoom(figure: go.Figure, *, height: int) -> None:
    """Render Plotly in Streamlit with smoother high-resolution touchpad zooming."""

    components.html(
        _plotly_html(figure, height=height),
        height=height,
        scrolling=False,
    )


def _plotly_html(figure: go.Figure, *, height: int) -> str:
    plot_html = pio.to_html(
        figure,
        config=dict(_PLOTLY_CONFIG),
        default_height=f"{height}px",
        default_width="100%",
        full_html=False,
        include_plotlyjs=True,
        post_script=_SMOOTH_TRACKPAD_ZOOM_SCRIPT,
    )
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    html,
    body {{
      background: #000;
      height: 100%;
      margin: 0;
      overflow: hidden;
      padding: 0;
      width: 100%;
    }}

    .plotly-graph-div {{
      height: {int(height)}px !important;
      width: 100% !important;
    }}
  </style>
</head>
<body>
  {plot_html}
</body>
</html>
"""
