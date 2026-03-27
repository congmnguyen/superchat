# superset-nl-explorer

A natural language LLM interface for [Apache Superset](https://superset.apache.org/), packaged as a deployable plugin.

Users type natural language queries in an embedded chat panel to explore data, preview charts, and create dashboards — without writing SQL or touching the chart builder.

---

## Features

- **Embedded chat UI** — dedicated "Ask Data" page + floating slide-in panel injected into every Superset page
- **Provider-agnostic LLM** — powered by [LiteLLM](https://github.com/BerriAI/litellm): OpenAI, Anthropic Claude, Ollama, AWS Bedrock, Azure, and more
- **Chart creation** — LLM generates Explore preview links or saves charts directly; supports bar, line, area, pie, scatter, table, and KPI (big number) chart types
- **Dashboard creation** — LLM creates dashboards and wires saved charts into them in one step
- **Validated tool calls** — per-chart-type required field validation catches malformed LLM requests before they hit Superset
- **Superset-native security** — all endpoints require Superset JWT auth; chart/dashboard creation runs through Superset's `CreateChartCommand` / `CreateDashboardCommand`
- **No core modifications** — deployed as a pip-installable package via `FLASK_APP_MUTATOR`; no patching of Superset source required
- **Superset 5.0 compatible** — uses the updated command paths and ORM relationships from Superset 5.x

---

## Quickstart (existing Superset Docker setup)

This is the fastest way to add the plugin to a running Superset instance.

### 1. Clone and build

```bash
git clone https://github.com/congmnguyen/superchat.git superset-nl-explorer
cd superset-nl-explorer

# Install uv if needed
curl -Lsf https://astral.sh/uv/install.sh | sh

# Build frontend assets
cd frontend && npm install && npm run build && cd ..

# Build the Python wheel
uv build
```

### 2. Place files in the Superset docker mount

Assuming your Superset repo uses the standard `docker/` volume layout:

```bash
# Copy the nl_explorer package to the PYTHONPATH mount
cp -r backend/src/nl_explorer /path/to/superset/docker/pythonpath_dev/nl_explorer

# Copy compiled frontend assets to a directory inside the docker mount
mkdir -p /path/to/superset/docker/nl-explorer-dist
cp dist/frontend/dist/* /path/to/superset/docker/nl-explorer-dist/
```

### 3. Add LiteLLM to requirements-local.txt

Create (or append to) `/path/to/superset/docker/requirements-local.txt`:

```
litellm>=1.40
```

### 4. Create superset_config_docker.py

Create `/path/to/superset/docker/pythonpath_dev/superset_config_docker.py`:

```python
import os

NL_EXPLORER_CONFIG = {
    "model": os.environ.get("NL_EXPLORER_MODEL", "gpt-4o-mini"),
    "api_key": os.environ.get("OPENAI_API_KEY", ""),
    "streaming": False,
    "max_datasets_in_context": 20,
}

def FLASK_APP_MUTATOR(app):
    from nl_explorer.entrypoint import register
    register(app)
```

### 5. Set environment variables

Add to your `docker/.env-local`:

```bash
OPENAI_API_KEY=sk-...
NL_EXPLORER_MODEL=gpt-4o-mini
NL_EXPLORER_STATIC_DIR=/app/docker/nl-explorer-dist
```

### 6. Restart Superset

```bash
docker compose -f docker-compose-non-dev.yml up -d --force-recreate superset superset-worker
```

Open `http://localhost:8088` — a chat button appears in the bottom-right corner of every page.

---

## Custom Docker image (production)

Use `Dockerfile.custom` to bake the plugin into a self-contained Superset image:

```dockerfile
FROM apache/superset:5.0.0

USER root
COPY dist/*.whl /tmp/
RUN pip install /tmp/*.whl

USER superset
COPY superset_config_custom.py /app/pythonpath/superset_config_docker.py
```

```bash
docker build -f Dockerfile.custom -t my-superset .
```

The `superset_config_custom.py` in this repo is a ready-to-use template — set `LLM_API_KEY` and `NL_EXPLORER_MODEL` as environment variables at runtime.

---

## Configuration reference

All settings go in `NL_EXPLORER_CONFIG` inside your Superset config file.

| Key | Default | Description |
|-----|---------|-------------|
| `model` | `"gpt-4o-mini"` | LiteLLM model string |
| `api_key` | `None` | LLM provider API key |
| `api_base` | `None` | Custom base URL (Ollama, vLLM, etc.) |
| `streaming` | `True` | Enable SSE streaming responses |
| `max_datasets_in_context` | `20` | Max datasets included in the system prompt |

### Model string examples

| Provider | Model string |
|----------|-------------|
| OpenAI | `"gpt-4o-mini"`, `"gpt-4o"` |
| Anthropic | `"claude-3-5-sonnet-20241022"` |
| Ollama (local) | `"ollama/llama3"` + `api_base="http://ollama:11434"` |
| AWS Bedrock | `"bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0"` |
| Azure OpenAI | `"azure/<deployment>"` + `api_base`, `api_key` |

---

## Supported chart types

The LLM selects a chart type by name; the backend resolves aliases and builds the correct Superset `formData`.

| Alias / name | Superset viz_type | Required fields |
|---|---|---|
| `bar` | `echarts_timeseries_bar` | `x_column`, `metric_column` |
| `line` | `echarts_timeseries_line` | `x_column`, `metric_column` |
| `area` | `echarts_area` | `x_column`, `metric_column` |
| `scatter` | `scatter` | `x_column`, `metric_column` |
| `pie` | `pie` | `group_by`, `metric_column` |
| `table` | `table` | `columns` |
| `kpi` / `big_number` | `big_number_total` | `metric_column` |

---

## API endpoints

All endpoints are under `/api/v1/nl_explorer/` and require a Superset JWT (`Authorization: Bearer <token>`).

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/config` | Non-sensitive plugin configuration |
| `GET` | `/context` | Datasets available to the current user |
| `POST` | `/chat` | Send a message, get LLM response + action cards |

### Chat request

```json
{
  "message": "Create a bar chart of customer count by Attrition_Flag from dataset 25",
  "conversation": [],
  "stream": false
}
```

### Chat response

```json
{
  "message": "I created the chart. Here's the link: ...",
  "actions": [
    {
      "type": "chart_created",
      "chart_id": 42,
      "chart_name": "Attrition Overview",
      "chart_url": "http://localhost:8088/explore/?slice_id=42"
    }
  ],
  "conversation": [...]
}
```

Action types: `explore_link`, `chart_created`, `dashboard_created`.

---

## Architecture

```
Every Superset page
  └── tail_js_custom_extra.html  ← floating "Ask Data" button + iframe drawer
          │
          ▼ (iframe src="/nl-explorer/")
      Flask Blueprint              ← serves compiled React SPA
          │
          ▼ (API calls)
POST /api/v1/nl_explorer/chat
          │
          ▼
NLExplorerRestApi._sync_chat()
  ├── context_builder.get_user_context()   ← DatasetDAO (datasets + schemas)
  ├── prompts/system.py                    ← system prompt with dataset context
  └── llm_service.chat()                   ← LiteLLM multi-turn tool loop
          │
          ▼ (tool calls, repeated until done)
llm_service.dispatch_tool_call()
  ├── list_datasets / get_dataset_schema   ← context_builder
  ├── preview_chart                        ← builds Explore URL (no DB write)
  ├── create_chart                         ← CreateChartCommand (Superset 5.x)
  ├── create_dashboard                     ← CreateDashboardCommand + ORM link
  └── describe_chart_types                 ← returns chart type guide
```

---

## Development

```bash
# Install dev dependencies
uv sync --group dev

# Run tests
uv run pytest

# Run with coverage
uv run pytest --cov=nl_explorer tests/

# Build frontend (outputs to dist/frontend/dist/)
cd frontend && npm install && npm run build

# Build the wheel
uv build
```

### Project layout

```
backend/src/nl_explorer/
  api.py             — REST endpoints (NLExplorerRestApi)
  llm_service.py     — LiteLLM tool loop, tool dispatch, validation
  chart_creator.py   — chart/dashboard creation via Superset commands
  chart_types.py     — CHART_TYPE_ALIASES, formData builders
  context_builder.py — dataset listing and schema fetching
  schemas.py         — Marshmallow request/response schemas
  entrypoint.py      — Flask blueprint + API registration
  blueprint.py       — SPA serving at /nl-explorer/
  prompts/
    system.py        — system prompt with few-shot examples
    tools.py         — LLM tool definitions

frontend/src/
  index.tsx          — SPA entry point
  ChatPage.tsx       — full-page chat UI
  ChatPanel.tsx      — floating panel chat UI

tests/
  test_chart_creator.py
  test_context_builder.py
  test_llm_service.py
  test_api.py
  test_system_prompt.py
```

---

## License

BSD-3-Clause
