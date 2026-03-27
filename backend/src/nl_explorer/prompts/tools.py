"""
LLM tool definitions (function calling) passed to the LLM alongside user messages.

Each tool maps to an action that the NL Explorer backend can execute.
create_chart and preview_chart accept high-level parameters; the backend
builds the correct Superset formData internally.
"""

from __future__ import annotations

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "list_datasets",
            "description": (
                "List Superset datasets available to the current user. "
                "Returns dataset IDs, names, and column summaries."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "search": {
                        "type": "string",
                        "description": "Optional search term to filter datasets by name.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dataset_schema",
            "description": (
                "Get detailed schema for a specific dataset including all columns, "
                "data types, and available metrics."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset_id": {
                        "type": "integer",
                        "description": "Numeric Superset dataset ID.",
                    }
                },
                "required": ["dataset_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_sql",
            "description": (
                "Execute a SQL query against a Superset database and return sample results. "
                "Use for data exploration and to verify column values before chart creation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "SQL query to execute."},
                    "database_id": {
                        "type": "integer",
                        "description": "Superset database ID to run the query against.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum rows to return (default 100).",
                        "default": 100,
                    },
                },
                "required": ["sql", "database_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "describe_chart_types",
            "description": (
                "Return the list of supported Superset chart types with their "
                "required and optional parameters. Call this if you are unsure "
                "which chart_type to use or what parameters it needs."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "preview_chart",
            "description": (
                "Generate an Explore link (interactive chart builder URL) for a chart "
                "configuration without permanently saving it. Use this to let the user "
                "preview and refine a chart before saving. "
                "Pass high-level parameters — the backend builds the correct formData."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "dataset_id": {
                        "type": "integer",
                        "description": "Superset dataset ID.",
                    },
                    "chart_type": {
                        "type": "string",
                        "description": (
                            "Chart type. Friendly aliases: 'bar', 'line', 'area', 'kpi', 'big_number'. "
                            "Canonical types: 'echarts_timeseries_bar', 'echarts_timeseries_line', "
                            "'echarts_area', 'pie', 'table', 'scatter', 'big_number_total'. "
                            "Call describe_chart_types for the full list."
                        ),
                    },
                    "x_column": {
                        "type": "string",
                        "description": "Category or time axis column (required for bar, line, area, scatter).",
                    },
                    "metric_column": {
                        "type": "string",
                        "description": "Column to aggregate as the primary metric value.",
                    },
                    "aggregate": {
                        "type": "string",
                        "description": "Aggregation function: SUM, COUNT, AVG, MIN, MAX (default SUM).",
                        "default": "SUM",
                    },
                    "group_by": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Dimension columns to break down the chart by (series/slices).",
                    },
                    "columns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Column list for table charts.",
                    },
                    "time_range": {
                        "type": "string",
                        "description": "Superset time range filter, e.g. 'No filter', 'Last 7 days', 'Last 30 days'.",
                        "default": "No filter",
                    },
                },
                "required": ["dataset_id", "chart_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_chart",
            "description": (
                "Permanently create and save a chart in Superset. "
                "Use only after the user confirms they want to save the chart. "
                "Pass high-level parameters — the backend builds the correct formData."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slice_name": {
                        "type": "string",
                        "description": "Human-readable name for the chart.",
                    },
                    "dataset_id": {
                        "type": "integer",
                        "description": "Superset dataset ID.",
                    },
                    "chart_type": {
                        "type": "string",
                        "description": (
                            "Chart type. Friendly aliases: 'bar', 'line', 'area', 'kpi', 'big_number'. "
                            "Canonical types: 'echarts_timeseries_bar', 'echarts_timeseries_line', "
                            "'echarts_area', 'pie', 'table', 'scatter', 'big_number_total'. "
                            "Call describe_chart_types for the full list."
                        ),
                    },
                    "x_column": {
                        "type": "string",
                        "description": "Category or time axis column (required for bar, line, area, scatter).",
                    },
                    "metric_column": {
                        "type": "string",
                        "description": "Column to aggregate as the primary metric value.",
                    },
                    "aggregate": {
                        "type": "string",
                        "description": "Aggregation function: SUM, COUNT, AVG, MIN, MAX (default SUM).",
                        "default": "SUM",
                    },
                    "group_by": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Dimension columns to break down the chart by (series/slices).",
                    },
                    "columns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Column list for table charts.",
                    },
                    "time_range": {
                        "type": "string",
                        "description": "Superset time range filter, e.g. 'No filter', 'Last 7 days'.",
                        "default": "No filter",
                    },
                },
                "required": ["slice_name", "dataset_id", "chart_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_dashboard",
            "description": (
                "Create a new Superset dashboard from a list of existing chart IDs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Dashboard title.",
                    },
                    "chart_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": (
                            "List of chart IDs (the chart_id values returned by "
                            "create_chart) to include in the dashboard. "
                            "These are NOT dataset IDs."
                        ),
                    },
                },
                "required": ["title", "chart_ids"],
            },
        },
    },
]
