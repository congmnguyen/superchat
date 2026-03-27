"""
Builds LLM context (system prompt payload) from Superset datasets and schemas
visible to the currently authenticated user.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Lazy import with fallback so the module can be imported without Superset installed.
# Tests patch nl_explorer.context_builder.DatasetDAO directly.
try:
    from superset.daos.dataset import DatasetDAO
except ImportError:
    DatasetDAO = None  # type: ignore[assignment,misc]

# Maximum number of datasets to include in the LLM context window.
# Operators can override via NL_EXPLORER_CONFIG["max_datasets_in_context"].
DEFAULT_MAX_DATASETS = 20
# Maximum columns per dataset included in context.
DEFAULT_MAX_COLUMNS = 50
DEFAULT_MAX_METRICS = 20


def get_user_context(
    dataset_id: int | None = None,
    max_datasets: int = DEFAULT_MAX_DATASETS,
    max_columns: int = DEFAULT_MAX_COLUMNS,
    max_metrics: int = DEFAULT_MAX_METRICS,
) -> dict[str, Any]:
    """
    Return a structured context dict describing datasets available to the
    current user. Used to build the LLM system prompt.

    Args:
        dataset_id: If provided, only include this specific dataset (for
            Explore/Dashboard panel context).
        max_datasets: Maximum number of datasets to include.
        max_columns: Maximum columns per dataset.
        max_metrics: Maximum saved metrics per dataset.

    Returns:
        Dict with "datasets" key containing summarised dataset info.
    """
    try:
        if dataset_id is not None:
            datasets = DatasetDAO.find_by_ids([dataset_id])
        else:
            # Fetch all datasets; DatasetDAO respects current user's permissions
            datasets = DatasetDAO.find_all()[:max_datasets]
    except Exception:
        logger.exception("Failed to fetch datasets for NL Explorer context")
        return {"datasets": []}

    result = []
    for ds in datasets:
        try:
            columns = []
            for col in (ds.columns or [])[:max_columns]:
                col_type = str(col.type) if col.type else "unknown"
                columns.append(
                    {
                        "name": col.column_name,
                        "type": col_type,
                        "description": col.description or None,
                    }
                )
            metrics = []
            for metric in (getattr(ds, "metrics", None) or [])[:max_metrics]:
                metric_name = (
                    getattr(metric, "metric_name", None)
                    or getattr(metric, "verbose_name", None)
                    or getattr(metric, "label", None)
                    or "unnamed_metric"
                )
                expression = getattr(metric, "expression", None) or getattr(metric, "sqlExpression", None)
                metrics.append({"name": metric_name, "expression": expression or None})

            database = getattr(ds, "database", None)
            database_id = getattr(database, "id", None)
            database_name = getattr(database, "database_name", None)
            time_columns = [col["name"] for col in columns if _is_temporal_column(col["type"])]
            dimension_columns = [col["name"] for col in columns if _is_dimension_column(col["type"])]
            measure_columns = [col["name"] for col in columns if _is_numeric_column(col["type"])]
            result.append(
                {
                    "id": ds.id,
                    "name": ds.table_name,
                    "description": getattr(ds, "description", None),
                    "schema": getattr(ds, "schema", None),
                    "database_id": database_id,
                    "database_name": database_name,
                    "columns": columns,
                    "metrics": metrics,
                    "time_columns": time_columns[:10],
                    "dimension_columns": dimension_columns[:10],
                    "measure_columns": measure_columns[:10],
                }
            )
        except Exception:
            logger.exception("Failed to serialize dataset %s for context", getattr(ds, "id", "?"))

    return {"datasets": result}


def _is_temporal_column(column_type: str) -> bool:
    normalized = column_type.lower()
    return any(token in normalized for token in ("date", "time"))


def _is_numeric_column(column_type: str) -> bool:
    normalized = column_type.lower()
    return any(token in normalized for token in ("int", "float", "double", "decimal", "numeric", "number"))


def _is_dimension_column(column_type: str) -> bool:
    if _is_temporal_column(column_type) or _is_numeric_column(column_type):
        return False
    normalized = column_type.lower()
    return any(
        token in normalized
        for token in ("char", "text", "string", "bool", "categor", "enum", "object", "unknown")
    )
