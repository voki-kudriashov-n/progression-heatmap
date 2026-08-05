"""Custom Streamlit component wrapper for the heatmap gradient range control."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st
import streamlit.components.v1 as components

_COMPONENT_DIR = Path(__file__).parent / "components" / "gradient_range"
_gradient_range_component = components.declare_component(
    "gradient_range",
    path=str(_COMPONENT_DIR),
)


def gradient_range(
    *,
    minimum: float,
    maximum: float,
    value: tuple[float, float],
    colorscale: tuple[tuple[float, str], ...],
    height: int,
    key: str,
) -> tuple[float, float]:
    """Render a vertical min/max gradient range component."""

    bounds = float(minimum), float(maximum)
    state_key = f"{key}_selection"
    stored_value = st.session_state.get(key, st.session_state.get(state_key, value))
    current_value = _normalize_range(stored_value, bounds)
    st.session_state[state_key] = current_value

    def sync_component_state() -> None:
        st.session_state[state_key] = _normalize_range(
            st.session_state.get(key, current_value),
            bounds,
        )

    component_value = _gradient_range_component(
        minimum=bounds[0],
        maximum=bounds[1],
        value=list(current_value),
        colorscale=[
            {"position": float(position), "color": color}
            for position, color in colorscale
        ],
        step=gradient_slider_step(bounds[0], bounds[1]),
        height=int(height),
        default=list(current_value),
        key=key,
        on_change=sync_component_state,
    )
    selected_value = _normalize_range(component_value, bounds)
    st.session_state[state_key] = selected_value
    return selected_value


def _normalize_range(value: Any, bounds: tuple[float, float]) -> tuple[float, float]:
    minimum, maximum = bounds
    if minimum > maximum:
        minimum, maximum = maximum, minimum

    if isinstance(value, dict):
        raw_minimum = value.get("minimum", minimum)
        raw_maximum = value.get("maximum", maximum)
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        raw_minimum, raw_maximum = value[0], value[1]
    else:
        raw_minimum, raw_maximum = minimum, maximum

    try:
        selected_minimum = float(raw_minimum)
        selected_maximum = float(raw_maximum)
    except (TypeError, ValueError):
        selected_minimum, selected_maximum = minimum, maximum

    selected_minimum = min(max(selected_minimum, minimum), maximum)
    selected_maximum = min(max(selected_maximum, minimum), maximum)
    if selected_minimum > selected_maximum:
        selected_minimum, selected_maximum = selected_maximum, selected_minimum
    return selected_minimum, selected_maximum


def gradient_slider_step(minimum: float, maximum: float) -> float:
    value_range = abs(maximum - minimum)
    if value_range >= 1000:
        return max(1.0, round(value_range / 200))
    if value_range >= 100:
        return 0.5
    if value_range >= 10:
        return 0.1
    if value_range >= 1:
        return 0.01
    return 0.001


def gradient_slider_format(minimum: float, maximum: float) -> str:
    value_range = abs(maximum - minimum)
    if value_range >= 100:
        return "%.0f"
    if value_range >= 10:
        return "%.1f"
    if value_range >= 1:
        return "%.2f"
    return "%.3f"
