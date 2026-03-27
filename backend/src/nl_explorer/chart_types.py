"""
Shared chart type metadata used by prompts and validation logic.
"""

from __future__ import annotations

# Friendly alias → canonical Superset viz_type
CHART_TYPE_ALIASES: dict[str, str] = {
    "bar": "echarts_timeseries_bar",
    "line": "echarts_timeseries_line",
    "area": "echarts_area",
    "kpi": "big_number_total",
    "big_number": "big_number_total",
}

# Per-type documentation used by the describe_chart_types tool and system prompt.
CHART_TYPE_INFO: dict[str, dict] = {
    "echarts_timeseries_bar": {
        "description": "Bar chart for time series or categorical comparisons",
        "required_params": ["x_column", "metric_column"],
        "optional_params": ["aggregate (default SUM)", "group_by", "time_range"],
        "notes": "x_column is the category/time axis; metric_column is the value to aggregate",
    },
    "echarts_timeseries_line": {
        "description": "Line chart for trends over time or ordered categories",
        "required_params": ["x_column", "metric_column"],
        "optional_params": ["aggregate (default SUM)", "group_by", "time_range"],
        "notes": "Best for time-series; x_column should be a date/datetime column",
    },
    "echarts_area": {
        "description": "Area chart for cumulative or stacked time series",
        "required_params": ["x_column", "metric_column"],
        "optional_params": ["aggregate (default SUM)", "group_by", "time_range"],
        "notes": "Like line chart but fills the area under the curve",
    },
    "pie": {
        "description": "Pie/donut chart for part-to-whole relationships",
        "required_params": ["group_by", "metric_column"],
        "optional_params": ["aggregate (default SUM)", "time_range"],
        "notes": "group_by is the dimension to slice by; metric_column is the value for each slice",
    },
    "table": {
        "description": "Tabular data display with sorting and filtering",
        "required_params": ["columns"],
        "optional_params": ["metric_column", "aggregate (default SUM)", "group_by", "time_range"],
        "notes": "columns lists the dimension columns to show; metric_column adds an aggregated metric column",
    },
    "scatter": {
        "description": "Scatter plot for correlation analysis between two metrics",
        "required_params": ["x_column", "metric_column"],
        "optional_params": ["group_by", "time_range"],
        "notes": "x_column and metric_column define the two axes",
    },
    "big_number_total": {
        "description": "Single large KPI metric display",
        "required_params": ["metric_column"],
        "optional_params": ["aggregate (default SUM)", "time_range"],
        "notes": "Displays one aggregated number; no x_column needed",
    },
    "echarts_box_plot": {
        "description": "Box-and-whisker plot for distributions",
        "required_params": ["x_column", "metric_column"],
        "optional_params": ["group_by"],
        "notes": "",
    },
    "big_number": {
        "description": "KPI with trend line",
        "required_params": ["metric_column"],
        "optional_params": ["aggregate (default SUM)", "time_range"],
        "notes": "",
    },
    "histogram": {
        "description": "Distribution histogram",
        "required_params": ["x_column"],
        "optional_params": ["group_by"],
        "notes": "",
    },
    "heatmap": {
        "description": "Heatmap for two-dimensional comparisons",
        "required_params": ["x_column", "metric_column"],
        "optional_params": ["group_by"],
        "notes": "",
    },
    "treemap_v2": {
        "description": "Treemap for hierarchical proportions",
        "required_params": ["group_by", "metric_column"],
        "optional_params": [],
        "notes": "",
    },
    "funnel": {
        "description": "Funnel chart for conversion analysis",
        "required_params": ["group_by", "metric_column"],
        "optional_params": [],
        "notes": "",
    },
}

# Flat description map kept for backward compatibility with existing code.
CHART_TYPES: dict[str, str] = {vt: info["description"] for vt, info in CHART_TYPE_INFO.items()}

# All canonical viz_types (aliases excluded).
SUPPORTED_VIZ_TYPES = frozenset(CHART_TYPES.keys())


def resolve_viz_type(chart_type: str) -> str | None:
    """Resolve a friendly alias or canonical viz_type to a supported viz_type.

    Returns None if chart_type is not recognised.
    """
    key = chart_type.lower()
    if key in CHART_TYPE_ALIASES:
        return CHART_TYPE_ALIASES[key]
    return key if key in SUPPORTED_VIZ_TYPES else None


def build_chart_type_guide() -> str:
    """Return a prompt-friendly guide of supported chart types."""
    alias_note = ", ".join(f"{a}={v}" for a, v in CHART_TYPE_ALIASES.items())
    lines = [
        f"Supported chart types (friendly aliases: {alias_note}):",
    ]
    for viz_type, info in CHART_TYPE_INFO.items():
        aliases = [a for a, v in CHART_TYPE_ALIASES.items() if v == viz_type]
        alias_str = f" [{', '.join(aliases)}]" if aliases else ""
        required = ", ".join(info.get("required_params", []))
        lines.append(
            f"  {viz_type}{alias_str}: {info['description']}. Required: {required}."
        )
    return "\n".join(lines)
