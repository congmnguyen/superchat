"""
Chart and dashboard creation for NL Explorer.

Provides high-level helpers so the LLM only needs to pass column names and
a chart type — this module builds the correct Superset formData internally.

Ported AdhocMetric format and per-type formData builders from superset-mcp,
adapted to use Superset's internal CreateChartCommand/CreateDashboardCommand
instead of the REST API.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from flask import current_app

from nl_explorer.chart_types import resolve_viz_type

logger = logging.getLogger(__name__)

# Module-level imports with fallback so tests can patch directly.
try:
    from superset.utils.core import get_user
except ImportError:
    get_user = None  # type: ignore[assignment]

try:
    from superset.commands.chart.create import CreateChartCommand
except ImportError:
    try:
        from superset.charts.commands.create import CreateChartCommand  # Superset <5
    except ImportError:
        CreateChartCommand = None  # type: ignore[assignment]

try:
    from superset.commands.dashboard.create import CreateDashboardCommand
except ImportError:
    try:
        from superset.dashboards.commands.create import CreateDashboardCommand  # Superset <5
    except ImportError:
        CreateDashboardCommand = None  # type: ignore[assignment]



# ---------------------------------------------------------------------------
# Low-level formData builders (ported from superset-mcp)
# ---------------------------------------------------------------------------

def _build_adhoc_metric(metric_column: str, aggregate: str = "SUM") -> dict[str, Any]:
    """Build an AdhocMetric dict in the format Superset 5.0 expects."""
    agg = aggregate.upper()
    return {
        "expressionType": "SIMPLE",
        "column": {"column_name": metric_column},
        "aggregate": agg,
        "label": f"{agg}({metric_column})",
        "optionName": f"metric_{agg.lower()}_{metric_column}",
    }


def _build_chart_form_data(
    viz_type: str,
    dataset_id: int,
    metric_column: str | None = None,
    aggregate: str = "SUM",
    x_column: str | None = None,
    group_by: list[str] | None = None,
    columns: list[str] | None = None,
    time_range: str = "No filter",
) -> dict[str, Any]:
    """Build the formData (params) dict for the given viz_type.

    Args:
        viz_type: Canonical Superset viz_type (e.g. 'echarts_timeseries_bar').
        dataset_id: Integer dataset ID.
        metric_column: Column to aggregate as the chart's primary metric.
        aggregate: SQL aggregate function (SUM, COUNT, AVG, MIN, MAX).
        x_column: Category/time axis column (bar, line, area, scatter).
        group_by: List of dimension columns for grouping/series breakdown.
        columns: Explicit column list for 'table' charts.
        time_range: Superset time range string (e.g. 'No filter', 'Last 7 days').
    """
    group_by = group_by or []
    datasource = f"{dataset_id}__table"

    if viz_type in ("echarts_timeseries_bar", "echarts_timeseries_line", "echarts_area"):
        metrics = [_build_adhoc_metric(metric_column, aggregate)] if metric_column else []
        return {
            "viz_type": viz_type,
            "datasource": datasource,
            "x_axis": x_column,
            "metrics": metrics,
            "groupby": group_by,
            "time_range": time_range,
            "row_limit": 1000,
            "x_axis_sort_asc": True,
            "x_axis_sort_series": "name",
            "x_axis_sort_series_ascending": True,
        }

    if viz_type == "pie":
        metric = _build_adhoc_metric(metric_column, aggregate) if metric_column else None
        return {
            "viz_type": viz_type,
            "datasource": datasource,
            "groupby": group_by,
            "metric": metric,
            "time_range": time_range,
            "row_limit": 100,
            "donut": False,
            "show_labels_threshold": 5,
        }

    if viz_type == "table":
        all_columns: list[str] = list(columns or [])
        if x_column and x_column not in all_columns:
            all_columns = [x_column] + all_columns
        for col in group_by:
            if col not in all_columns:
                all_columns.append(col)
        metrics = [_build_adhoc_metric(metric_column, aggregate)] if metric_column else []
        return {
            "viz_type": viz_type,
            "datasource": datasource,
            "all_columns": all_columns,
            "metrics": metrics,
            "time_range": time_range,
            "row_limit": 1000,
            "order_desc": True,
        }

    if viz_type == "scatter":
        return {
            "viz_type": viz_type,
            "datasource": datasource,
            "x": _build_adhoc_metric(x_column, "COUNT") if x_column else None,
            "y": _build_adhoc_metric(metric_column, aggregate) if metric_column else None,
            "groupby": group_by,
            "time_range": time_range,
            "row_limit": 1000,
        }

    if viz_type == "big_number_total":
        metric = _build_adhoc_metric(metric_column, aggregate) if metric_column else None
        return {
            "viz_type": viz_type,
            "datasource": datasource,
            "metric": metric,
            "time_range": time_range,
        }

    # Generic fallback for any other viz_type
    metrics = [_build_adhoc_metric(metric_column, aggregate)] if metric_column else []
    return {
        "viz_type": viz_type,
        "datasource": datasource,
        "metrics": metrics,
        "groupby": group_by,
        "time_range": time_range,
        "row_limit": 1000,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def preview_chart(
    dataset_id: int,
    chart_type: str,
    x_column: str | None = None,
    metric_column: str | None = None,
    aggregate: str = "SUM",
    group_by: list[str] | None = None,
    columns: list[str] | None = None,
    time_range: str = "No filter",
) -> dict[str, Any]:
    """Generate a Superset Explore URL for previewing a chart without saving it.

    Accepts high-level parameters and builds the correct formData internally.

    Returns a dict with an "explore_url" key.
    """
    viz_type = resolve_viz_type(chart_type)
    if viz_type is None:
        return {
            "error": f"Unsupported chart_type: {chart_type!r}",
            "retryable": True,
            "hint": "Call describe_chart_types to see supported types.",
        }

    form_data = _build_chart_form_data(
        viz_type=viz_type,
        dataset_id=dataset_id,
        metric_column=metric_column,
        aggregate=aggregate,
        x_column=x_column,
        group_by=group_by,
        columns=columns,
        time_range=time_range,
    )

    params = json.dumps(form_data)
    base_url = current_app.config.get("WEBDRIVER_BASEURL", "http://localhost:8088/")
    explore_url = (
        f"{base_url.rstrip('/')}/explore/"
        f"?datasource_type=table&datasource_id={dataset_id}"
        f"&form_data={params}"
    )
    return {
        "type": "explore_link",
        "explore_url": explore_url,
        "dataset_id": dataset_id,
        "viz_type": viz_type,
    }


def create_chart(
    slice_name: str,
    dataset_id: int,
    chart_type: str,
    x_column: str | None = None,
    metric_column: str | None = None,
    aggregate: str = "SUM",
    group_by: list[str] | None = None,
    columns: list[str] | None = None,
    time_range: str = "No filter",
) -> dict[str, Any]:
    """Permanently create and save a chart in Superset.

    Accepts high-level parameters and builds the correct formData internally.

    Returns a dict with the created chart's ID and a link to view it.
    """
    viz_type = resolve_viz_type(chart_type)
    if viz_type is None:
        return {
            "error": f"Unsupported chart_type: {chart_type!r}",
            "retryable": True,
            "hint": "Call describe_chart_types to see supported types.",
        }

    form_data = _build_chart_form_data(
        viz_type=viz_type,
        dataset_id=dataset_id,
        metric_column=metric_column,
        aggregate=aggregate,
        x_column=x_column,
        group_by=group_by,
        columns=columns,
        time_range=time_range,
    )

    user = get_user()
    command = CreateChartCommand(
        data={
            "slice_name": slice_name,
            "datasource_id": dataset_id,
            "datasource_type": "table",
            "viz_type": viz_type,
            "params": json.dumps(form_data),
            "owners": [user.id] if user else [],
        },
    )
    chart = command.run()
    logger.info("Created chart id=%s name=%s", chart.id, slice_name)

    base_url = current_app.config.get("WEBDRIVER_BASEURL", "http://localhost:8088/")
    return {
        "type": "chart_created",
        "chart_id": chart.id,
        "chart_name": chart.slice_name,
        "chart_url": f"{base_url.rstrip('/')}/explore/?slice_id={chart.id}",
    }


def create_dashboard(
    title: str,
    chart_ids: list[int],
) -> dict[str, Any]:
    """Create a new Superset dashboard containing the specified charts.

    Returns a dict with the created dashboard's ID and URL.
    """
    user = get_user()

    position_json = _build_position_json(chart_ids)

    command = CreateDashboardCommand(
        data={
            "dashboard_title": title,
            "slug": None,
            "owners": [user.id] if user else [],
            "position_json": json.dumps(position_json),
            "css": "",
            "json_metadata": "{}",
            "published": False,
        },
    )
    dashboard = command.run()

    # Populate the dashboard_slices M2M table so charts actually appear on
    # the dashboard. In Superset 5.x, position_json alone doesn't do this;
    # we must link Slice objects directly via the ORM relationship.
    from superset.extensions import db
    from superset.models.slice import Slice

    slices = db.session.query(Slice).filter(Slice.id.in_(chart_ids)).all()
    dashboard.slices = slices
    db.session.commit()

    logger.info("Created dashboard id=%s title=%s", dashboard.id, title)

    base_url = current_app.config.get("WEBDRIVER_BASEURL", "http://localhost:8088/")
    return {
        "type": "dashboard_created",
        "dashboard_id": dashboard.id,
        "dashboard_title": dashboard.dashboard_title,
        "dashboard_url": f"{base_url.rstrip('/')}/superset/dashboard/{dashboard.id}/",
    }


def _build_position_json(chart_ids: list[int], columns_per_row: int = 2) -> dict[str, Any]:
    """Build a Superset 5.x-compatible position_json for a set of chart IDs.

    Lays charts out in rows with `columns_per_row` charts per row (default 2).
    Includes the mandatory `parents` arrays required by Superset 5.x.
    """
    cols = max(1, min(columns_per_row, 4))
    width = 12 // cols  # Superset uses a 12-column grid

    rows = [chart_ids[i: i + cols] for i in range(0, len(chart_ids), cols)]
    row_ids = [f"ROW_{i + 1}" for i in range(len(rows))]

    components: dict[str, Any] = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {
            "type": "GRID",
            "id": "GRID_ID",
            "children": row_ids,
            "parents": ["ROOT_ID"],
        },
    }

    for row_id, row_charts in zip(row_ids, rows):
        chart_comp_ids = [f"CHART_{cid}" for cid in row_charts]
        components[row_id] = {
            "type": "ROW",
            "id": row_id,
            "children": chart_comp_ids,
            "parents": ["ROOT_ID", "GRID_ID"],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }
        for cid in row_charts:
            comp_id = f"CHART_{cid}"
            components[comp_id] = {
                "type": "CHART",
                "id": comp_id,
                "children": [],
                "parents": ["ROOT_ID", "GRID_ID", row_id],
                "meta": {"chartId": cid, "width": width, "height": 50},
            }

    return components
