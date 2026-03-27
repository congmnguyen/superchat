"""
Tests for nl_explorer.chart_creator
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_preview_chart_returns_explore_url(mock_flask_app):
    """preview_chart should return an explore URL with the correct dataset ID."""
    from nl_explorer.chart_creator import preview_chart

    with mock_flask_app.app_context():
        result = preview_chart(
            dataset_id=7,
            chart_type="bar",
            x_column="country",
            metric_column="revenue",
        )

    assert result["type"] == "explore_link"
    assert "datasource_id=7" in result["explore_url"]
    assert "echarts_timeseries_bar" in result["explore_url"]


@patch("nl_explorer.chart_creator.CreateChartCommand")
@patch("nl_explorer.chart_creator.get_user")
def test_create_chart_calls_command(mock_get_user, mock_cmd_cls, mock_flask_app):
    """create_chart should invoke CreateChartCommand and return chart metadata."""
    mock_user = MagicMock()
    mock_user.id = 1
    mock_get_user.return_value = mock_user

    mock_chart = MagicMock()
    mock_chart.id = 99
    mock_chart.slice_name = "Monthly Sales"
    mock_cmd_cls.return_value.run.return_value = mock_chart

    from nl_explorer.chart_creator import create_chart

    with mock_flask_app.app_context():
        result = create_chart(
            slice_name="Monthly Sales",
            dataset_id=5,
            chart_type="table",
            columns=["month", "revenue"],
        )

    assert result["type"] == "chart_created"
    assert result["chart_id"] == 99
    assert "chart_url" in result
