"""
Marshmallow schemas for NL Explorer API request/response validation.
"""

from __future__ import annotations

from marshmallow import fields, Schema, validate, INCLUDE


class MessageSchema(Schema):
    role = fields.Str(required=True, validate=validate.OneOf(["user", "assistant", "system"]))
    content = fields.Str(required=True)


class ChatRequestSchema(Schema):
    message = fields.Str(required=True, metadata={"description": "User's natural language query"})
    conversation = fields.List(
        fields.Nested(MessageSchema),
        load_default=[],
        metadata={"description": "Prior conversation history"},
    )
    dataset_id = fields.Int(
        load_default=None,
        metadata={"description": "Optional dataset ID to scope the conversation"},
    )
    dashboard_id = fields.Int(
        load_default=None,
        metadata={"description": "Optional dashboard ID to scope the conversation"},
    )
    stream = fields.Bool(
        load_default=False,
        metadata={"description": "Whether to stream the response via SSE"},
    )
    page_context = fields.Dict(
        load_default={},
        metadata={"description": "Page context from the parent Superset frame (dashboard, datasource, org config)"},
    )


class ColumnInfoSchema(Schema):
    name = fields.Str()
    type = fields.Str()
    description = fields.Str(allow_none=True)


class DatasetContextSchema(Schema):
    id = fields.Int()
    name = fields.Str()
    description = fields.Str(allow_none=True)
    columns = fields.List(fields.Nested(ColumnInfoSchema))


class ContextResponseSchema(Schema):
    datasets = fields.List(fields.Nested(DatasetContextSchema))


class ActionSchema(Schema):
    """Pass all action fields through without stripping unknown keys.

    Actions carry type-specific fields (explore_url, chart_url, dashboard_url,
    chart_name, dashboard_title, chart_id, etc.) that vary by type. Marshmallow
    would silently drop them if they are not declared, so we use INCLUDE to
    preserve every field the backend sets.
    """

    class Meta:
        unknown = INCLUDE

    type = fields.Str(
        metadata={"description": "Action type: explore_link, chart_created, dashboard_created"}
    )


class ChatResponseSchema(Schema):
    message = fields.Str(metadata={"description": "LLM text response"})
    actions = fields.List(
        fields.Dict(),
        metadata={"description": "Structured actions for the frontend to render"},
    )
    conversation = fields.List(
        fields.Nested(MessageSchema),
        metadata={"description": "Updated conversation history including this turn"},
    )


class ExecuteRequestSchema(Schema):
    action = fields.Nested(ActionSchema, required=True)


class ExecuteResponseSchema(Schema):
    success = fields.Bool()
    result = fields.Dict()
    error = fields.Str(allow_none=True)


class PluginConfigResponseSchema(Schema):
    model = fields.Str()
    streaming_enabled = fields.Bool()
    max_datasets_in_context = fields.Int()
