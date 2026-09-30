# Market Analyzer

A self-hosted stock-market analysis platform that pairs classic fundamentals with
local, open-source LLMs. It ingests market data from Yahoo Finance, computes valuation
and profitability metrics, and layers a suite of AI agents on top — from a one-shot
"is this stock cheap?" summary to autonomous, tool-using research workflows — all running
against a **local Ollama** instance so no market data or prompts leave your network.

> Full-stack reference project: Django + DRF, React + Vite, PostgreSQL + pgvector,
> Celery, and a local LLM stack, deployed to Proxmox LXC via Pulumi + Ansible with a
> Grafana/Prometheus/Loki/Tempo observability stack.

## Features

- **Market data ingestion** — S&P 500 / NASDAQ-100 constituents, daily OHLCV price bars,
  point-in-time valuation snapshots, three-statement financials, and dividends, pulled
  from `yfinance` and refreshed incrementally by Celery.
- **AI company summary** — a single grounded LLM verdict (buy/hold/sell + confidence,
  drivers, and risks) per company, benchmarked against industry/sector peers, with a
  freshness gate that skips the model when the underlying data is stale.
- **Agent harness** — twelve LLM workflow types over a shared, durable run/step model:
  prompt chaining, routing, parallelization (sectioning + voting), ReAct, evaluator-
  optimizer, plan-and-execute, orchestrator-workers, sequential and DAG multi-agent,
  an autonomous long-horizon agent, a conversational chat agent, and a headless-browser
  agent. All stream over SSE and survive a page refresh.
- **Knowledge graph** — a topic-agnostic, self-expanding concept graph with LLM expansion,
  trigram/alias de-duplication, homonym sense-splitting, and offline hub reranking.
- **Code graph** — a read-only viewer over a tree-sitter AST index of this repo's own
  source (via [graphify](https://pypi.org/project/graphifyy/)).
- **Observability** — structured JSON logs, Prometheus metrics (app, Celery, and domain),
  and OpenTelemetry traces with per-agent-run waterfalls and LLM token counts.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Django 5 + Django REST Framework, Python 3.13, `uv` |
| Frontend | React 19 + TypeScript, Vite, TanStack Query/Router, Tailwind CSS v4, shadcn (base-nova) |
| Database | PostgreSQL 16 + `pgvector` |
| Async | Celery + Redis |
| LLM | [Ollama](https://ollama.com) (local) — `qwen3:8b`, `qwen3-vl:8b` (vision), `nomic-embed-text`; Anthropic selectable per browser run |
| Infra | Pulumi + Proxmox LXC, Ansible, GitHub Actions CI/CD |
| Observability | Grafana + Prometheus + Loki + Tempo + Alloy |

## Architecture

```
backend/            Django REST API (Python 3.13, uv)
  core/             settings, Celery, structured logging, tracing, middleware
  apps/
    accounts/       JWT auth (email login, UUID PKs)
    companies/      Company/Sector CRUD + yfinance ingestion + AI company summary
    llm_analysis/   Ollama wrapper + the 12-workflow agent harness (shared runtime,
                    two polymorphic models: AgentRun + AgentStep)
    knowledge_graph/ self-expanding concept graph
    codegraph/      read-only API over the graphify code graph
    tasks/          Celery Beat schedule + metrics exporter + domain collectors
    redis_monitor/  read-only Redis introspection
frontend/           React SPA (TypeScript, Vite)
infra/              Pulumi (containers), Ansible (bootstrap), observability stack
loadtest/           k6 read-only load tests
docs/               project docs + design + AI memory
```

## Quick Start

Requires [`just`](https://github.com/casey/just), [`uv`](https://docs.astral.sh/uv/),
Node.js, Docker (for Postgres + Redis), and a reachable [Ollama](https://ollama.com)
instance.

```bash
just env-init          # copy .env.example -> .env, then edit it
just install           # backend (uv) + frontend (npm) deps
just db-up             # start PostgreSQL + Redis containers
just dev               # start everything: DB, Redis, Django, Vite, Celery
```

- Backend API: http://localhost:8004
- Frontend: http://localhost:5173

### Common commands

```bash
just be-test           # backend pytest suite
just be-lint           # ruff check
just fe-test           # frontend vitest suite
just fe-build          # production build
just be-migrate        # apply migrations
just be-celery         # start a Celery worker
```

See the [`justfile`](justfile) for the full command set (infra, observability,
load testing, and Ansible recipes).

## Configuration

All configuration lives in a single **`.env` at the repo root** (template:
[`.env.example`](.env.example)), read by Django, Vite, docker-compose, and — in
production — the systemd units. Only `VITE_`-prefixed keys reach the browser bundle,
which keeps `SECRET_KEY` and `ANTHROPIC_API_KEY` server-side.

The LLM stack is driven by `OLLAMA_*` keys (base URL, models, context window, per-workflow
budgets) and, at runtime, an editable `LLMSettings` singleton exposed at
`/api/llm/settings/` and in the frontend LLM Settings page.

## Documentation

- [`docs/project_docs/`](docs/project_docs/) — design records for the agent harness,
  AI summary pipeline, chat agent, observability, load testing, and production infra.
- [`docs/LLM/llm_workflows.md`](docs/LLM/llm_workflows.md) — the LLM workflow catalogue.
- [`docs/Market_Research/`](docs/Market_Research/) — the financial concepts the app models.
- [`CLAUDE.md`](CLAUDE.md) — the full architecture, conventions, and operational notes
  (written for AI coding assistants, but the most complete single reference).

## License

Released under the [MIT License](LICENSE).
