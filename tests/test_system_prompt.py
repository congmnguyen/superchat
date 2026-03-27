"""
Tests for nl_explorer.prompts.system
"""

from __future__ import annotations


def test_build_system_prompt_includes_enriched_dataset_context():
    """Prompt should include dataset context that helps the model pick tools correctly."""
    from nl_explorer.prompts.system import build_system_prompt

    prompt = build_system_prompt(
        context={
            "datasets": [
                {
                    "id": 7,
                    "name": "orders",
                    "description": "Customer orders",
                    "schema": "analytics",
                    "database_id": 3,
                    "database_name": "warehouse",
                    "columns": [{"name": "order_date"}, {"name": "country"}, {"name": "amount"}],
                    "metrics": [{"name": "sum__amount"}],
                    "time_columns": ["order_date"],
                    "dimension_columns": ["country"],
                    "measure_columns": ["amount"],
                }
            ]
        },
        current_user="Ada Lovelace",
        page_context={"page": "/superset/explore/7", "datasource": "orders"},
    )

    assert "database_id=3" in prompt
    assert "Saved metrics: sum__amount" in prompt
    assert "Few-shot examples" in prompt
    assert "If a tool returns a retryable error" in prompt
