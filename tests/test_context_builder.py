"""
Tests for nl_explorer.context_builder
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _make_mock_dataset(id_: int, name: str, columns: list[dict]) -> MagicMock:
    ds = MagicMock()
    ds.id = id_
    ds.table_name = name
    ds.description = None
    ds.schema = "analytics"
    ds.database = MagicMock(id=3, database_name="warehouse")
    col_mocks = []
    for c in columns:
        col = MagicMock()
        col.column_name = c["name"]
        col.type = c.get("type", "VARCHAR")
        col.description = c.get("description", None)
        col_mocks.append(col)
    ds.columns = col_mocks
    metric = MagicMock()
    metric.metric_name = "sum__amount"
    metric.expression = "SUM(amount)"
    ds.metrics = [metric]
    return ds


@patch("nl_explorer.context_builder.DatasetDAO")
def test_get_user_context_returns_datasets(mock_dao):
    """get_user_context should return serialized datasets."""
    from nl_explorer.context_builder import get_user_context

    mock_dao.find_all.return_value = [
        _make_mock_dataset(1, "orders", [{"name": "order_id"}, {"name": "amount"}]),
        _make_mock_dataset(2, "customers", [{"name": "customer_id"}, {"name": "country"}]),
    ]

    result = get_user_context(max_datasets=10)

    assert len(result["datasets"]) == 2
    assert result["datasets"][0]["id"] == 1
    assert result["datasets"][0]["name"] == "orders"
    assert result["datasets"][0]["database_id"] == 3
    assert result["datasets"][0]["metrics"][0]["name"] == "sum__amount"
    assert any(c["name"] == "amount" for c in result["datasets"][0]["columns"])


@patch("nl_explorer.context_builder.DatasetDAO")
def test_get_user_context_adds_column_hints(mock_dao):
    """Context should expose useful charting hints for the prompt."""
    from nl_explorer.context_builder import get_user_context

    mock_dao.find_all.return_value = [
        _make_mock_dataset(
            1,
            "orders",
            [
                {"name": "order_date", "type": "TIMESTAMP"},
                {"name": "country", "type": "VARCHAR"},
                {"name": "amount", "type": "DECIMAL"},
            ],
        )
    ]

    result = get_user_context()

    dataset = result["datasets"][0]
    assert dataset["time_columns"] == ["order_date"]
    assert "country" in dataset["dimension_columns"]
    assert "amount" in dataset["measure_columns"]


@patch("nl_explorer.context_builder.DatasetDAO")
def test_get_user_context_specific_dataset(mock_dao):
    """When dataset_id is provided, only that dataset should be fetched."""
    from nl_explorer.context_builder import get_user_context

    mock_dao.find_by_ids.return_value = [
        _make_mock_dataset(42, "revenue", [{"name": "date"}, {"name": "total"}])
    ]

    result = get_user_context(dataset_id=42)

    mock_dao.find_by_ids.assert_called_once_with([42])
    assert result["datasets"][0]["id"] == 42


@patch("nl_explorer.context_builder.DatasetDAO")
def test_get_user_context_handles_dao_error(mock_dao):
    """If DAO raises, context should return empty datasets without crashing."""
    from nl_explorer.context_builder import get_user_context

    mock_dao.find_all.side_effect = RuntimeError("DB error")

    result = get_user_context()
    assert result == {"datasets": []}
