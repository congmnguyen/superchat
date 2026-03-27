"""
LiteLLM-based LLM service for NL Explorer.

Handles:
- Non-streaming chat completions
- SSE streaming completions
- LLM tool/function call dispatch
- Config from Flask app config (NL_EXPLORER_CONFIG)
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Generator
from typing import Any

from nl_explorer.chart_types import CHART_TYPE_ALIASES, CHART_TYPE_INFO, SUPPORTED_VIZ_TYPES, resolve_viz_type

# Module-level import so tests can patch nl_explorer.llm_service.litellm
try:
    import litellm
except ImportError:
    litellm = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)
RETRYABLE_SQL_ERROR_PATTERNS = (
    "syntax",
    "parse",
    "column",
    "relation",
    "table",
    "invalid identifier",
    "unknown column",
    "not found",
)
RETRYABLE_CHART_ERROR_PATTERNS = (
    "viz",
    "metric",
    "column",
    "datasource",
    "form_data",
    "params",
    "groupby",
)


def _get_config() -> dict[str, Any]:
    """Read NL_EXPLORER_CONFIG from the Flask app config."""
    from flask import current_app

    return current_app.config.get("NL_EXPLORER_CONFIG", {})


def chat(
    messages: list[dict[str, Any]],
    tools: list[dict] | None = None,
    stream: bool = False,
) -> dict[str, Any] | Generator[str, None, None]:
    """
    Send a chat request to the configured LLM via LiteLLM.

    Args:
        messages: List of OpenAI-format message dicts (role + content).
        tools: Optional list of tool definitions for function calling.
        stream: If True, returns a generator of SSE-formatted strings.

    Returns:
        If stream=False: dict with "message" and "tool_calls" keys.
        If stream=True: generator of SSE event strings.
    """
    cfg = _get_config()
    model = cfg.get("model", "gpt-4o")
    api_key = cfg.get("api_key")
    api_base = cfg.get("api_base")  # For Ollama / custom endpoints
    max_tokens = cfg.get("max_tokens", 4096)

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": stream,
    }
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["api_base"] = api_base
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    if stream:
        return _stream_response(litellm.completion(**kwargs))

    response = litellm.completion(**kwargs)
    choice = response.choices[0]
    msg = choice.message

    tool_calls = []
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        for tc in msg.tool_calls:
            tool_calls.append(
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": json.loads(tc.function.arguments or "{}"),
                }
            )

    return {
        "message": msg.content or "",
        "tool_calls": tool_calls,
    }


def _stream_response(response: Any) -> Generator[str, None, None]:
    """Convert a LiteLLM streaming response to SSE-formatted strings."""
    for chunk in response:
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta and delta.content:
            data = json.dumps({"type": "text", "content": delta.content})
            yield f"data: {data}\n\n"
    yield "data: [DONE]\n\n"


def dispatch_tool_call(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """
    Dispatch a tool call from the LLM to the appropriate executor.

    Returns a dict suitable for appending to the conversation as a tool message.
    """
    from nl_explorer import chart_creator, context_builder

    validation_error = _validate_tool_call(tool_name, arguments)
    if validation_error:
        return {
            "role": "tool",
            "name": tool_name,
            "content": json.dumps(validation_error),
        }

    try:
        if tool_name == "list_datasets":
            ctx = context_builder.get_user_context()
            result = ctx["datasets"]
        elif tool_name == "get_dataset_schema":
            ctx = context_builder.get_user_context(dataset_id=arguments["dataset_id"], max_columns=200)
            result = ctx["datasets"][0] if ctx["datasets"] else {}
        elif tool_name == "run_sql":
            result = _run_sql(arguments)
        elif tool_name == "describe_chart_types":
            result = _describe_chart_types()
        elif tool_name == "preview_chart":
            result = chart_creator.preview_chart(
                dataset_id=arguments["dataset_id"],
                chart_type=arguments["chart_type"],
                x_column=arguments.get("x_column"),
                metric_column=arguments.get("metric_column"),
                aggregate=arguments.get("aggregate", "SUM"),
                group_by=arguments.get("group_by"),
                columns=arguments.get("columns"),
                time_range=arguments.get("time_range", "No filter"),
            )
        elif tool_name == "create_chart":
            result = chart_creator.create_chart(
                slice_name=arguments["slice_name"],
                dataset_id=arguments["dataset_id"],
                chart_type=arguments["chart_type"],
                x_column=arguments.get("x_column"),
                metric_column=arguments.get("metric_column"),
                aggregate=arguments.get("aggregate", "SUM"),
                group_by=arguments.get("group_by"),
                columns=arguments.get("columns"),
                time_range=arguments.get("time_range", "No filter"),
            )
        elif tool_name == "create_dashboard":
            result = chart_creator.create_dashboard(
                title=arguments["title"],
                chart_ids=arguments["chart_ids"],
            )
        else:
            result = _tool_error(tool_name, f"Unknown tool: {tool_name}", retryable=False)
    except Exception as exc:
        logger.exception("Tool call %s failed", tool_name)
        result = _tool_error(
            tool_name,
            str(exc),
            **_classify_tool_error(tool_name, str(exc)),
        )

    result = _normalize_tool_result(tool_name, result)

    return {
        "role": "tool",
        "name": tool_name,
        "content": json.dumps(result),
    }


def _describe_chart_types() -> dict[str, Any]:
    """Return supported chart types with their required/optional parameters."""
    chart_types = {}
    # Build reverse alias map once
    aliases_reversed: dict[str, list[str]] = {}
    for alias, viz in CHART_TYPE_ALIASES.items():
        aliases_reversed.setdefault(viz, []).append(alias)

    for viz_type, info in CHART_TYPE_INFO.items():
        entry = dict(info)
        entry["viz_type"] = viz_type
        entry["aliases"] = aliases_reversed.get(viz_type, [])
        chart_types[viz_type] = entry

    return {"chart_types": chart_types, "total": len(chart_types)}


def _run_sql(arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute SQL directly via the database engine."""
    from superset.daos.database import DatabaseDAO

    database_id = arguments["database_id"]
    sql = arguments["sql"]
    limit = int(arguments.get("limit", 100))

    database = DatabaseDAO.find_by_id(database_id)
    if not database:
        return _tool_error(
            "run_sql",
            f"Database {database_id} not found",
            retryable=True,
            hint="Use the database_id from dataset context or inspect the dataset schema first.",
        )

    # Append a LIMIT clause if not already present
    if "limit" not in sql.lower():
        sql = f"{sql.rstrip(';')} LIMIT {limit}"

    try:
        df = database.get_df(sql)
        return {
            "columns": list(df.columns),
            "rows": df.head(limit).values.tolist(),
            "row_count": len(df),
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("SQL execution failed: %s", exc)
        return _tool_error("run_sql", str(exc), **_classify_tool_error("run_sql", str(exc)))


def _normalize_tool_result(tool_name: str, result: Any) -> Any:
    if not isinstance(result, dict) or "error" not in result:
        return result

    normalized = dict(result)
    normalized.setdefault("tool_name", tool_name)
    if "retryable" not in normalized or "hint" not in normalized:
        classification = _classify_tool_error(tool_name, str(normalized["error"]))
        normalized.setdefault("retryable", classification["retryable"])
        normalized.setdefault("hint", classification["hint"])
    return normalized


def _validate_chart_required_fields(
    tool_name: str, viz_type: str, arguments: dict[str, Any]
) -> dict[str, Any] | None:
    """Return a retryable validation error if chart-type-specific required fields are missing."""
    metric_col = arguments.get("metric_column")
    x_col = arguments.get("x_column")
    group_by = arguments.get("group_by")
    columns = arguments.get("columns")

    # Charts that need both an axis column and a metric
    if viz_type in ("echarts_timeseries_bar", "echarts_timeseries_line", "echarts_area", "scatter"):
        if not x_col:
            return _tool_error(
                tool_name,
                f"{viz_type} requires x_column (the category or time axis column).",
                retryable=True,
                hint="Inspect the dataset schema and pick a suitable column for the x axis.",
                kind="validation_error",
            )
        if not metric_col:
            return _tool_error(
                tool_name,
                f"{viz_type} requires metric_column (the column to aggregate).",
                retryable=True,
                hint="Inspect the dataset schema and pick a numeric column to aggregate.",
                kind="validation_error",
            )

    # Pie needs at least one group_by dimension and a metric
    if viz_type == "pie":
        if not group_by:
            return _tool_error(
                tool_name,
                "pie requires group_by (the dimension to slice by).",
                retryable=True,
                hint="Pass group_by as a list with at least one categorical column.",
                kind="validation_error",
            )
        if not metric_col:
            return _tool_error(
                tool_name,
                "pie requires metric_column (the value for each slice).",
                retryable=True,
                hint="Inspect the dataset schema and pick a numeric column to aggregate.",
                kind="validation_error",
            )

    # Table needs explicit column list
    if viz_type == "table":
        if not columns:
            return _tool_error(
                tool_name,
                "table requires columns (list of columns to display).",
                retryable=True,
                hint="Pass columns as a list of column names from the dataset schema.",
                kind="validation_error",
            )

    # KPI / big number needs a metric
    if viz_type in ("big_number_total", "big_number"):
        if not metric_col:
            return _tool_error(
                tool_name,
                f"{viz_type} requires metric_column (the KPI metric to display).",
                retryable=True,
                hint="Pick a numeric column to aggregate as the KPI value.",
                kind="validation_error",
            )

    return None


def _validate_tool_call(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    if tool_name == "get_dataset_schema":
        if not _is_positive_int(arguments.get("dataset_id")):
            return _tool_error(
                tool_name,
                "dataset_id must be a positive integer.",
                retryable=True,
                hint="Pick a dataset_id from the dataset context or call list_datasets first.",
                kind="validation_error",
            )

    if tool_name == "run_sql":
        sql = str(arguments.get("sql", "")).strip()
        if not _is_positive_int(arguments.get("database_id")):
            return _tool_error(
                tool_name,
                "database_id must be a positive integer.",
                retryable=True,
                hint="Use the database_id shown in dataset context.",
                kind="validation_error",
            )
        if not sql:
            return _tool_error(
                tool_name,
                "SQL query must not be empty.",
                retryable=True,
                hint="Provide a read-only SELECT or WITH query.",
                kind="validation_error",
            )
        if _has_multiple_sql_statements(sql):
            return _tool_error(
                tool_name,
                "Only a single SQL statement is allowed.",
                retryable=True,
                hint="Send one SELECT or WITH query without extra statements.",
                kind="validation_error",
            )
        if not _is_read_only_sql(sql):
            return _tool_error(
                tool_name,
                "Only read-only SQL is allowed.",
                retryable=True,
                hint="Rewrite the query as a SELECT or WITH statement.",
                kind="validation_error",
            )

    if tool_name in {"preview_chart", "create_chart"}:
        if not _is_positive_int(arguments.get("dataset_id")):
            return _tool_error(
                tool_name,
                "dataset_id must be a positive integer.",
                retryable=True,
                hint="Use the dataset ID from the current context.",
                kind="validation_error",
            )
        chart_type = arguments.get("chart_type")
        viz_type = resolve_viz_type(str(chart_type)) if chart_type else None
        if not chart_type or viz_type is None:
            supported_aliases = ", ".join(sorted(CHART_TYPE_ALIASES.keys()))
            supported_types = ", ".join(sorted(SUPPORTED_VIZ_TYPES))
            return _tool_error(
                tool_name,
                f"Unsupported chart_type: {chart_type!r}.",
                retryable=True,
                hint=(
                    f"Aliases: {supported_aliases}. "
                    f"Canonical types: {supported_types}. "
                    "Call describe_chart_types for details."
                ),
                kind="validation_error",
            )
        # Enforce chart-type-specific required fields so the LLM gets immediate
        # feedback instead of a silent empty-metrics chart.
        required_field_err = _validate_chart_required_fields(tool_name, viz_type, arguments)
        if required_field_err:
            return required_field_err
        if tool_name == "create_chart" and not str(arguments.get("slice_name", "")).strip():
            return _tool_error(
                tool_name,
                "slice_name must not be empty.",
                retryable=True,
                hint="Provide a concise human-readable chart name.",
                kind="validation_error",
            )

    if tool_name == "create_dashboard":
        title = str(arguments.get("title", "")).strip()
        chart_ids = arguments.get("chart_ids")
        if not title:
            return _tool_error(
                tool_name,
                "title must not be empty.",
                retryable=True,
                hint="Provide a concise dashboard title.",
                kind="validation_error",
            )
        if not isinstance(chart_ids, list) or not chart_ids or not all(_is_positive_int(cid) for cid in chart_ids):
            return _tool_error(
                tool_name,
                "chart_ids must be a non-empty list of positive integers.",
                retryable=True,
                hint="Only pass saved chart IDs that already exist.",
                kind="validation_error",
            )

    return None


def _tool_error(
    tool_name: str,
    error: str,
    retryable: bool,
    hint: str | None = None,
    kind: str = "execution_error",
) -> dict[str, Any]:
    return {
        "tool_name": tool_name,
        "error": error,
        "retryable": retryable,
        "hint": hint,
        "kind": kind,
    }


def _classify_tool_error(tool_name: str, error_message: str) -> dict[str, Any]:
    normalized = error_message.lower()
    if "permission" in normalized or "access denied" in normalized or "not authorized" in normalized:
        return {
            "retryable": False,
            "hint": "Do not retry automatically. Explain the permission issue and ask the user for another path.",
        }

    if tool_name == "run_sql" and any(pattern in normalized for pattern in RETRYABLE_SQL_ERROR_PATTERNS):
        return {
            "retryable": True,
            "hint": "Correct the SQL using the available schema and retry once. If the schema is unclear, inspect the dataset first.",
        }

    if tool_name in {"preview_chart", "create_chart"} and any(
        pattern in normalized for pattern in RETRYABLE_CHART_ERROR_PATTERNS
    ):
        return {
            "retryable": True,
            "hint": "Correct the chart config using known columns and a supported chart_type, then retry once.",
        }

    if tool_name == "create_dashboard" and "chart" in normalized:
        return {
            "retryable": True,
            "hint": "Retry only if you can correct the chart IDs. Otherwise ask the user to confirm which saved charts to include.",
        }

    return {
        "retryable": False,
        "hint": "Do not blindly retry. Ask a clarifying question or explain the failure.",
    }


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _has_multiple_sql_statements(sql: str) -> bool:
    stripped = sql.strip()
    normalized = stripped[:-1] if stripped.endswith(";") else stripped
    return ";" in normalized


def _is_read_only_sql(sql: str) -> bool:
    stripped = sql.strip().lower()
    if not stripped:
        return False
    if re.match(r"^(select|with)\b", stripped) is None:
        return False
    return not re.search(r"\b(insert|update|delete|drop|alter|truncate|create|grant|revoke)\b", stripped)
