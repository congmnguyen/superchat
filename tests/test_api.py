"""
Tests for nl_explorer.api
"""

from __future__ import annotations


def test_build_chat_messages_appends_current_user_turn_once():
    """The current message should be appended when conversation only contains prior turns."""
    from nl_explorer.api import _build_chat_messages

    messages = _build_chat_messages(
        system_prompt="system",
        conversation=[{"role": "assistant", "content": "How can I help?"}],
        message="Show me revenue by month",
    )

    assert messages == [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "How can I help?"},
        {"role": "user", "content": "Show me revenue by month"},
    ]


def test_build_chat_messages_avoids_duplicate_current_user_turn():
    """Clients that already appended the current user turn should not cause a duplicate LLM input."""
    from nl_explorer.api import _build_chat_messages

    messages = _build_chat_messages(
        system_prompt="system",
        conversation=[
            {"role": "assistant", "content": "How can I help?"},
            {"role": "user", "content": "Show me revenue by month"},
        ],
        message="Show me revenue by month",
    )

    assert messages == [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "How can I help?"},
        {"role": "user", "content": "Show me revenue by month"},
    ]


def test_build_retry_instruction_includes_repair_guidance():
    """Retry instructions should tell the model to repair once, not loop blindly."""
    from nl_explorer.api import _build_retry_instruction

    instruction = _build_retry_instruction(
        [
            {
                "tool_name": "run_sql",
                "error": "column revenue_total does not exist",
                "hint": "Inspect the dataset schema and correct the column name.",
            }
        ]
    )

    assert "retryable" in instruction
    assert "Do not repeat the same invalid arguments." in instruction
    assert "run_sql: column revenue_total does not exist" in instruction
