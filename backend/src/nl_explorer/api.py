"""
NL Explorer REST API.

Registered with Flask-AppBuilder via FLASK_APP_MUTATOR in superset_config.py.
Mounted at /api/v1/nl_explorer/ by FAB's add_api().
"""

from __future__ import annotations

import json
import logging
from typing import Any

from flask import current_app, request, Response, stream_with_context
from flask_appbuilder.api import BaseApi, expose, permission_name, protect, safe

from nl_explorer import context_builder, llm_service
from nl_explorer.prompts.system import build_system_prompt
from nl_explorer.prompts.tools import TOOLS
from nl_explorer.schemas import (
    ChatRequestSchema,
    ChatResponseSchema,
    ContextResponseSchema,
    ExecuteRequestSchema,
    ExecuteResponseSchema,
    PluginConfigResponseSchema,
)

logger = logging.getLogger(__name__)


def _build_chat_messages(
    system_prompt: str,
    conversation: list[dict[str, Any]],
    message: str,
) -> list[dict[str, Any]]:
    """Build the LLM message list and tolerate clients that already appended the latest user turn."""
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for turn in conversation:
        messages.append({"role": turn["role"], "content": turn["content"]})

    # Some clients optimistically append the current user message to the
    # conversation before POSTing. Avoid sending the same final turn twice.
    last_turn = conversation[-1] if conversation else None
    if not (
        last_turn
        and last_turn.get("role") == "user"
        and last_turn.get("content") == message
    ):
        messages.append({"role": "user", "content": message})

    return messages


def _build_retry_instruction(retryable_failures: list[dict[str, Any]]) -> str:
    """Tell the model when it should repair a failed tool call instead of repeating it blindly."""
    failure_lines = []
    for failure in retryable_failures:
        hint = failure.get("hint")
        line = f"- {failure['tool_name']}: {failure['error']}"
        if hint:
            line += f" Hint: {hint}"
        failure_lines.append(line)

    joined_failures = "\n".join(failure_lines)
    return (
        "A tool call failed in a retryable way.\n"
        "If the fix is clear from the existing context, issue one corrected tool call.\n"
        "Do not repeat the same invalid arguments.\n"
        "If required information is missing, ask a concise clarification question instead.\n"
        f"{joined_failures}"
    )


class NLExplorerRestApi(BaseApi):
    """NL Explorer REST API — registered via appbuilder.add_api()."""

    allow_browser_login = True
    resource_name = "nl_explorer"
    openapi_spec_tag = "NL Explorer"
    class_permission_name = "nl_explorer"

    # ------------------------------------------------------------------ #
    # GET /api/v1/nl_explorer/context
    # ------------------------------------------------------------------ #

    @expose("/context", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    def get_context(self) -> Response:
        """Return datasets available to the current user for the chat UI."""
        cfg = current_app.config.get("NL_EXPLORER_CONFIG", {})
        max_datasets = cfg.get("max_datasets_in_context", context_builder.DEFAULT_MAX_DATASETS)
        ctx = context_builder.get_user_context(max_datasets=max_datasets)
        return self.response(200, **ContextResponseSchema().dump(ctx))

    # ------------------------------------------------------------------ #
    # POST /api/v1/nl_explorer/chat
    # ------------------------------------------------------------------ #

    @expose("/chat", methods=("POST",))
    @protect()
    @safe
    @permission_name("read")
    def chat(self) -> Response:
        """Send a natural language message and receive an LLM response."""
        body = request.get_json(force=True) or {}
        req = ChatRequestSchema().load(body)

        cfg = current_app.config.get("NL_EXPLORER_CONFIG", {})
        max_datasets = cfg.get("max_datasets_in_context", context_builder.DEFAULT_MAX_DATASETS)

        ctx = context_builder.get_user_context(
            dataset_id=req.get("dataset_id"),
            max_datasets=max_datasets,
        )
        try:
            from superset.utils.core import get_user

            user = get_user()
            current_user_name = f"{user.first_name} {user.last_name}".strip() if user else None
        except Exception:
            current_user_name = None

        system_prompt = build_system_prompt(ctx, current_user=current_user_name, page_context=req.get("page_context", {}))

        messages = _build_chat_messages(
            system_prompt=system_prompt,
            conversation=req.get("conversation", []),
            message=req["message"],
        )

        if req.get("stream"):
            return self._stream_chat(messages, req)

        return self._sync_chat(messages, req)

    def _sync_chat(self, messages: list[dict], req: dict) -> Response:
        """Run a synchronous (non-streaming) chat turn with tool call loop."""
        MAX_TOOL_ROUNDS = 5
        # Collect actionable tool results (explore links, chart/dashboard URLs)
        # across all tool call rounds so the frontend can render them.
        all_actions: list[dict[str, Any]] = []
        _ACTIONABLE_TYPES = {"explore_link", "chart_created", "dashboard_created"}

        for _ in range(MAX_TOOL_ROUNDS):
            result = llm_service.chat(messages=messages, tools=TOOLS, stream=False)
            assert isinstance(result, dict)

            tool_calls = result.get("tool_calls", [])
            if not tool_calls:
                break

            retryable_failures: list[dict[str, Any]] = []
            # Build a properly-formatted OpenAI-style assistant message so that
            # LiteLLM can correctly translate it to Bedrock's converse format.
            messages.append({
                "role": "assistant",
                "content": result.get("message") or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"]),
                        },
                    }
                    for tc in tool_calls
                ],
            })
            # Each tool result must reference the matching tool_call_id so that
            # Bedrock receives exactly one toolResult per toolUse block.
            for tc in tool_calls:
                raw = llm_service.dispatch_tool_call(tc["name"], tc["arguments"])
                try:
                    payload = json.loads(raw["content"])
                except (TypeError, json.JSONDecodeError):
                    payload = {}
                if isinstance(payload, dict) and payload.get("error") and payload.get("retryable"):
                    retryable_failures.append(payload)
                # Collect actionable results so the frontend can render links/cards.
                if isinstance(payload, dict) and payload.get("type") in _ACTIONABLE_TYPES:
                    all_actions.append(payload)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": raw["content"],
                })
            if retryable_failures:
                messages.append({
                    "role": "system",
                    "content": _build_retry_instruction(retryable_failures),
                })

        conversation_out = [
            {"role": m["role"], "content": m.get("content") or ""}
            for m in messages
            if m["role"] in ("user", "assistant") and m.get("content")
        ]

        response_payload = {
            "message": result.get("message", ""),  # type: ignore[possibly-undefined]
            "actions": all_actions,
            "conversation": conversation_out,
        }
        return self.response(200, **ChatResponseSchema().dump(response_payload))

    def _stream_chat(self, messages: list[dict], req: dict) -> Response:
        """Return an SSE streaming response."""

        def generate():  # type: ignore[return]
            try:
                gen = llm_service.chat(messages=messages, tools=TOOLS, stream=True)
                for chunk in gen:  # type: ignore[union-attr]
                    yield chunk
            except Exception as exc:
                logger.exception("Streaming chat error")
                yield f'data: {json.dumps({"type": "error", "content": str(exc)})}\n\n'

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ------------------------------------------------------------------ #
    # POST /api/v1/nl_explorer/execute
    # ------------------------------------------------------------------ #

    @expose("/execute", methods=("POST",))
    @protect()
    @safe
    @permission_name("write")
    def execute(self) -> Response:
        """Execute a structured action (create chart, dashboard, run SQL)."""
        body = request.get_json(force=True) or {}
        req = ExecuteRequestSchema().load(body)
        action = req["action"]

        result = llm_service.dispatch_tool_call(action["type"], action.get("payload", {}))
        payload = json.loads(result.get("content", "{}"))

        response_payload = {
            "success": "error" not in payload,
            "result": payload,
            "error": payload.get("error"),
        }
        return self.response(200, **ExecuteResponseSchema().dump(response_payload))

    # ------------------------------------------------------------------ #
    # GET /api/v1/nl_explorer/config
    # ------------------------------------------------------------------ #

    @expose("/config", methods=("GET",))
    @protect()
    @safe
    @permission_name("read")
    def get_plugin_config(self) -> Response:
        """Return non-sensitive plugin configuration for the frontend."""
        cfg = current_app.config.get("NL_EXPLORER_CONFIG", {})
        payload = {
            "model": cfg.get("model", "gpt-4o"),
            "streaming_enabled": cfg.get("streaming", True),
            "max_datasets_in_context": cfg.get(
                "max_datasets_in_context", context_builder.DEFAULT_MAX_DATASETS
            ),
        }
        return self.response(200, **PluginConfigResponseSchema().dump(payload))
