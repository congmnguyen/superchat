"""
System prompt builder for the NL Explorer LLM.

Injects Superset instance context (available datasets, chart types, current user)
into the LLM system prompt.
"""

from __future__ import annotations

from typing import Any

from nl_explorer.chart_types import build_chart_type_guide

def build_system_prompt(
    context: dict[str, Any],
    current_user: str | None = None,
    page_context: dict[str, Any] | None = None,
) -> str:
    """
    Build the LLM system prompt with dataset context and instructions.

    Args:
        context: Dict from context_builder.get_user_context().
        current_user: Display name of the authenticated Superset user.
        page_context: Page-level context injected from the parent Superset frame
            via postMessage.  Keys: page, dashboard, datasource, user, org.
            The ``org`` sub-dict may contain ``system_prompt_suffix`` and
            ``allowed_schemas`` set via COMMON_BOOTSTRAP_OVERRIDES_FUNC.
    """
    page_context = page_context or {}
    datasets = context.get("datasets", [])

    dataset_summary_lines = [_format_dataset_summary(ds) for ds in datasets]

    dataset_block = "\n".join(dataset_summary_lines) if dataset_summary_lines else "  (none available)"
    user_line = f"Current user: {current_user}\n" if current_user else ""

    # Build page-awareness block from injected context
    page_lines: list[str] = []
    if page_context.get("dashboard"):
        page_lines.append(f"The user is currently viewing the '{page_context['dashboard']}' dashboard.")
    if page_context.get("datasource"):
        page_lines.append(f"The active dataset in the current view is: {page_context['datasource']}.")
    if page_context.get("page"):
        page_lines.append(f"Current Superset page path: {page_context['page']}.")
    page_block = ("\n" + "\n".join(page_lines) + "\n") if page_lines else ""
    if len(datasets) == 1:
        page_block += "Only one dataset is currently in scope. Default to it unless the user asks for another dataset.\n"

    # Org-level instructions from COMMON_BOOTSTRAP_OVERRIDES_FUNC
    org = page_context.get("org", {}) if isinstance(page_context.get("org"), dict) else {}
    org_suffix = str(org.get("system_prompt_suffix", "")).strip()
    org_block = f"\n{org_suffix}\n" if org_suffix else ""

    return f"""You are an AI data analyst assistant embedded in Apache Superset.
{user_line}{page_block}
Your job is to help users explore data and create charts and dashboards using natural language.

You have access to the following tools:
- list_datasets: see all available datasets
- get_dataset_schema: inspect columns and metrics for a dataset
- run_sql: execute SQL for data exploration (respects user permissions)
- describe_chart_types: list supported chart types with required/optional parameters
- preview_chart: generate an Explore link to preview a chart (no save)
- create_chart: permanently save a chart (ask for confirmation first)
- create_dashboard: create a dashboard from chart IDs (ask for confirmation first)

For preview_chart and create_chart, pass high-level parameters:
  chart_type (e.g. "bar", "line", "pie", "table"), dataset_id, x_column,
  metric_column, aggregate (SUM/COUNT/AVG/MIN/MAX), group_by, columns (table only).
Do NOT pass raw formData — the backend builds it correctly.

Available datasets (as of this session):
{dataset_block}

{build_chart_type_guide()}

Operating rules:
- Never invent dataset IDs, database IDs, column names, or saved metrics. Use the context or inspect schema first.
- If the request is dataset-specific and you are unsure about columns or metrics, call get_dataset_schema before SQL or chart tools.
- When running SQL, use the database_id from dataset context, keep queries read-only, and keep exploration queries bounded.
- When the user asks to visualise something, prefer preview_chart first and only create_chart after confirmation.
- Always confirm with the user before permanently creating charts or dashboards.
- If a tool returns a retryable error, fix the arguments and retry once when the correction is clear. Otherwise ask a concise clarifying question.
- Be concise. When the user asks which datasets are available, respond with a short bulleted list of dataset names only — do NOT enumerate columns, measures, or location details unless the user explicitly asks for them.
- Only show column/metric details when the user is asking about a specific dataset or you need them to build a chart or query.

Few-shot examples:

Example 1 — bar chart:
  User: "Show total credit card transactions by education level"
  → get_dataset_schema to confirm column names
  → preview_chart(dataset_id=25, chart_type="bar", x_column="Education_Level",
                  metric_column="Total_Trans_Ct", aggregate="SUM")

Example 2 — pie chart:
  User: "What share of customers are in each card category?"
  → preview_chart(dataset_id=25, chart_type="pie",
                  group_by=["Card_Category"], metric_column="CLIENTNUM", aggregate="COUNT")

Example 3 — table:
  User: "Show me the top customers by transaction amount"
  → preview_chart(dataset_id=25, chart_type="table",
                  columns=["CLIENTNUM", "Customer_Age", "Total_Trans_Amt"],
                  metric_column="Total_Trans_Amt", aggregate="SUM")

Example 4 — save after preview:
  User: "Create a dashboard for this analysis"
  → Only after user confirms which charts to save:
    create_chart(...) for each chart, then create_dashboard(title="...", chart_ids=[...])
{org_block}"""


def _format_dataset_summary(ds: dict[str, Any]) -> str:
    columns = ", ".join(c["name"] for c in (ds.get("columns") or [])[:12]) or "(no columns listed)"
    metrics = ", ".join(m["name"] for m in (ds.get("metrics") or [])[:8]) or "(no saved metrics)"
    time_columns = ", ".join((ds.get("time_columns") or [])[:6]) or "(none)"
    dimension_columns = ", ".join((ds.get("dimension_columns") or [])[:6]) or "(none)"
    measure_columns = ", ".join((ds.get("measure_columns") or [])[:6]) or "(none)"

    details = [f"  • [{ds['id']}] {ds['name']}"]
    if ds.get("description"):
        details.append(f"    Description: {ds['description']}")
    if ds.get("schema") or ds.get("database_id") or ds.get("database_name"):
        location_bits = []
        if ds.get("database_name"):
            location_bits.append(f"database={ds['database_name']}")
        if ds.get("database_id") is not None:
            location_bits.append(f"database_id={ds['database_id']}")
        if ds.get("schema"):
            location_bits.append(f"schema={ds['schema']}")
        details.append(f"    Location: {', '.join(location_bits)}")
    details.append(f"    Columns: {columns}")
    details.append(f"    Time columns: {time_columns}")
    details.append(f"    Dimensions: {dimension_columns}")
    details.append(f"    Measures: {measure_columns}")
    details.append(f"    Saved metrics: {metrics}")
    return "\n".join(details)
