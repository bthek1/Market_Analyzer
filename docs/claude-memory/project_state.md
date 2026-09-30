---
name: project-state
description: "Current build status of the Market Analyzer — which phases are complete, what's deployed, and key infrastructure facts"
metadata:
  type: project
---

## Market Analyzer — Project State (as of 2026-09-22)

### Completed Plans

- `SETUP_FRONTEND_BACKEND_PLAN.md` — Full-stack scaffold (accounts, JWT, React/Vite, TanStack)
- `TESTING_PLAN.md` — Backend 47/47 passing, 96% coverage; Frontend 20/20 passing
- `frontend-design-upgrade.md` — Upgraded UI to shadcn/base-nova, fixed Input forwardRef bug
- `companies_model_upgrade.md` — Company model overhaul (symbol, sector/industry FKs, yfinance sync)
- `fmp-removal.md` — FMP data source removed, yfinance-only
- `celery_periodic_sync.md` — Two-flow task hierarchy: bootstrap flow (discover stubs + bootstrap_tick) and periodic sync flow (dispatch tasks for price/snapshot/profile/financials/dividends)
- `yfinance_data_expansion.md` — Extended CompanySnapshot with 40+ fields (beta, 52-week, margins, growth, liquidity, ownership, ESG risk scores, analyst targets). Added models: ShortInterest, InstitutionalHolderSnapshot, EarningsDate, ESGScore, OptionsExpiry, OptionsContract
- `company-detail-ui-improvements.md` — Company detail tabs: Overview, Market Data, Financials, Dividends, ESG, Earnings, Options, Ownership
- `data-visualizations.md` — ECharts integration (echarts v6.1.0 + echarts-for-react), 5 chart components (PriceChart, MarketCapTreemap, etc.), builder pattern
- `sectors-industries-ui.md` — Dedicated /sectors and /industries routes with ECharts breakdown charts
- `sectors-industries-combined-ui.md` — Combined sector+industry explorer
- `market-map-chart-upgrades.md` — Enhanced market map treemap
- `company-ui-server-table.md` — Server-side table with filtering/sorting/pagination
- `redis-monitor-ui.md` — /redis route with Redis key browser
- `move-frontend-transforms-to-backend.md` — Pivoted financials endpoint (server-side pivot)
- `data_freshness_sync_ui.md` — SyncPanel in company detail with per-data-type trigger + status
- `celery_schedule_completion.md` — Beat schedule fully wired, management command sync_scheduled_tasks
- `company-summaries.md` — AI-generated buy/hold/sell summaries: CompanySummary model, generate_company_summary service, Celery batch dispatch, DRF endpoints (/api/companies/{symbol}/summaries/latest/), SummaryCard frontend component
- `prompt-chaining.md`, `routing-llm-workflow.md`, `parallelization-llm-workflow.md` — first LLM workflow patterns (chain / router / observable parallelization)
- `react-llm-workflow.md` — ReAct agent (bounded Thought->Tool->Observation loop over read-only DB tools)
- `evaluator-optimizer-llm-workflow.md` — Evaluator-Optimizer (generate -> evaluate -> revise, quality-gated)
- `plan-and-execute-llm-workflow.md` — Plan-and-Execute (plan upfront -> execute via tools -> optional replan -> synthesise)
- `llm-settings-singleton.md` — `LLMSettings` django-solo singleton replacing live `settings.OLLAMA_*` reads; runtime-editable via `/api/llm/settings/` + frontend LLM Settings page
- `sidebar-navigation.md` (2026-08-05) — nav moved from the topbar to a **collapsible left sidebar** (icon rail + mobile drawer); added `layout/nav.ts`, `Sidebar.tsx`, `LogoMark.tsx`, `FullBleed.tsx`, `store/ui.ts`
- **issue #3** (2026-09-16) — AI company summary rewrite: percent->fraction unit fix at ingestion (+ backfill migration), peer/price/technicals added to the prompt, structured verdict + `confidence`/`key_risks`/`key_drivers`, `CompanySyncRecord` freshness gate, UI surfacing. **Supersedes issue #1's Phases 3-5** (the `equity_report` pipeline was dropped). See [[ai-summary]]
- **issue #6** (2026-09-25, phases 1-2 of 6 BUILT, not committed or deployed) - Agent harness:
  consolidate the control loop into one runtime. `llm_analysis` already had the tool interface,
  the validated meta writer, durable runs and tracing as shared layers; the LOOP was eleven
  hand-rolled copies (`_sse` x9, `_finish` x9, one already drifted). Phase 1 added `_events.py`
  (sse/event framing + `succeed`/`fail` generators that write the row and emit the terminal event
  together) and deleted the 18 duplicates, net -217 lines in the workflow modules. Phase 2 added
  `serializers.STEP_SERIALIZERS` + `_events.step_event`, making the SSE step payload literally the
  step serializer's output - which FIXED real user-visible bugs: SEVEN OF TEN workflows described a
  step differently on the two paths - in `dag`/`autonomous` the tool arguments were lost on every
  refresh-restore, and in `chain` the step card's duration label only appeared after a reload.
  **issue #7** (closed same day) fixed a related one: `react` persisted a step for an unparseable
  model turn but streamed no event for it. **Phase 3** added `_runtime.py`: `drive(run, strategy)` owns the budget,
  the step span, error isolation on EVERY hook, the step write, the emission and the terminal
  status; `react`/`eval_opt`/`plan_exec` became Strategy classes of pure policy, `chain` and
  `router` are exempt. Note phase 3 ADDED ~200 lines where phases 1-2 removed 337 - the win is one
  implementation, not smaller code. **Phase 4** added `drive_waves` (orchestrator/dag/parallel) and the `pre_step` hook
  (multiagent/autonomous) - ten of eleven workflows driven, only `chain`/`router` exempt.
  **Phase 5** found a LIVE DEFECT: `services.chat` sent no `num_ctx`, so every main-model call ran
  at Ollama's 4096 default and truncated silently - measured on the live host, a 12,052-token
  prompt evaluated only 4,095 and answered wrong. Fixed (`OLLAMA_NUM_CTX=16384`) and verified
  end to end. **Phase 6** added `registry.py`, collapsing 22 view classes to one generic pair
  (net -253 lines). ALL SIX PHASES BUILT; backend 2330 passed / 97.17%, frontend 821.
  **NOT COMMITTED AND NOT DEPLOYED** - so #6 stays open, and the num_ctx fix in particular is
  still degrading answers in prod until it ships. See [[agent-harness]]
- **issue #5** (2026-09-23, phases 1-2 of 5 built and DEPLOYED) — Distributed tracing with
  Grafana Tempo, completing LGTM and SUPERSEDING issue #2's "no tracing" decision. Live:
  `grafana/tempo:2.10.8` on `.208` (filesystem-backed, 15d retention pinned by test to
  Prometheus') + an Alloy OTLP pipeline on the APP HOST ONLY (loopback receiver ->
  host attribute -> 2s batch -> export to `.208:4317`), verified end to end by pushing a
  span and reading it back through Grafana (`just obs-trace-test`). Phase 3 (OTel
  instrumentation of Django/Celery/psycopg/redis/httpx in `core/tracing.py`, `trace_id` in
  the JSON log body, bidirectional Grafana correlation) and phase 4 (manual spans:
  `agent.run`, `ollama.chat`/`chat_stream`/`chat_many`/`embed` with token counts,
  `agent.tool`) and phase 5 (Tempo span metrics -> a `Domain / Tracing` dashboard +
  exemplars) are BUILT, DEPLOYED and VERIFIED against live agent runs - a 48-span waterfall
  showing 8.8s of fan-out inside a 3.3s parent, and `obs-verify` reporting 0 unexplained of
  75 panel targets. **ALL FIVE PHASES COMPLETE**, including per-step `agent.step` spans across all ten
  workflow modules (two mechanisms: a loop-body wrapper, and timestamp replay from
  `store.update_step`). Ships OFF by default. NOT (spans around `chat`/`chat_many` + agent
  steps - this is what closes the "no per-call Ollama latency metric" and
  `stream_in_background` daemon-thread gaps), phase 5 (dashboard + docs). **Tempo is
  currently an empty but working store.** Mimir deliberately out of scope. See
  [[observability]]
- **issue #2** (2026-09-22, all 4 phases built and DEPLOYED) — Observability: Grafana + Prometheus + Loki intended for `stockmarket-obs` (VMID 208, `.208` - NOT `.203`, which is a Frigate NVR), Grafana Alloy agent on every host, structured JSON logging + request-id correlation, host/Redis/Postgres exporters, `django-prometheus` (one port per gunicorn worker, gated on `PROMETHEUS_EXPORT_WORKER_PORTS` set only in the api unit), a hand-rolled Celery event exporter and DB-derived domain gauges (`apps/tasks/` metrics.py + collectors.py, `stockmarket-metrics.service`), 7 dashboards, 12 alert rules emailing the LAN mail catcher (`.207:1025`). **LIVE on all three hosts and verified end to end** - panels checked against live Prometheus via `just obs-verify` (0 unexplained of 65) and the host-down rule fired for real and resolved (2026-09-23). Only box left open: firing the Ollama rule, which needs an outage on a host outside this stack's inventory. See [[observability]]
- **issue #4** (2026-09-21) — Config consolidation: ONE `.env` at the repo root replacing `backend/.env`, `frontend/.env`, hardcoded compose credentials/ports and a hardcoded `VITE_API_BASE_URL` in `deploy.sh`. No fallback anywhere; applied to prod (units repointed, legacy file deleted). Also rotated the prod `SECRET_KEY`, which had been the literal `REPLACE_ME` since bootstrap. See [[env-config]]
- `terraform-to-pulumi-migration.md` (2026-08-05) — container provisioning moved from Terraform to Pulumi (Python + uv, local file state); live containers **imported**, never recreated; `infra/proxmox/` deleted

### Backend Apps

- `accounts/` — CustomUser (email login, UUID PK), JWT auth
- `companies/` — Company, Sector, Industry, PriceBar, CompanySnapshot, FinancialStatement, Dividend, ShortInterest, InstitutionalHolderSnapshot, EarningsDate, ESGScore, OptionsExpiry, OptionsContract, CompanySummary
  - All models inherit from `TimeStampedModel` (created_at, updated_at)
  - TextChoices in `choices.py` (Exchange, Currency, StatementType, Period)
  - `is_bootstrapped` flag on Company for progressive ingest
  - Management command: `discover_new_symbols` (scrapes S&P 500 from GitHub CSV + NASDAQ-100 from api.nasdaq.com)
  - S&P 500 from GitHub CSV; NASDAQ-100 from api.nasdaq.com (Wikipedia IP-blocked on prod)
  - Celery tasks: `discover_new_symbols`, `bootstrap_tick` (every 20 min, 5 at a time), plus dispatch tasks for profile/price/snapshot/financial/dividend/short-interest/institutional/esg/options/earnings syncs
- `llm_analysis/` — Ollama LLM workflows + observable agents. `services.py` wraps the Ollama REST API (`chat` blocking, `chat_stream` SSE, `chat_many` concurrent fan-out bounded by `num_parallel`, `embed` via `/api/embed`, `summarise`/`analyse`/`list_models`). Per-role models: classification on the cheap classifier model, synthesis/analysis on the main model; per-run `model` override swaps the MAIN model only.
  - **Runtime config is a `LLMSettings` django-solo singleton** (app `solo` in `INSTALLED_APPS`), NOT live `settings.OLLAMA_*` reads. All readers go through `config.get_llm_config()` (`= LLMSettings.get_solo()`, with an unsaved-defaults fallback when the table is missing). The `OLLAMA_*` env vars only *seed* the row's field defaults on first creation (via callable defaults that read `settings.OLLAMA_*`), so a fresh row mirrors the deployed `.env`; after that the DB row is the source of truth. Editable at `/api/llm/settings/` (GET/PUT/PATCH, `IsAuthenticated`), Django admin (`SingletonModelAdmin`), and the frontend **LLM Settings** page. Agent request bodies still override `max_steps`/`threshold` per-call (serializer default `None` -> view falls back to the singleton). Tests use the `llm_settings` fixture in `backend/conftest.py` (patches `get_solo` to an in-memory instance).
  - **Model consolidation (2026-06-13):** all ten workflows now persist to TWO unified, polymorphic models instead of 19 per-workflow ones — `AgentRun` (discriminated by `kind`: chain/route/parallel/react/eval_opt/plan_exec/orchestrator/multiagent/dag/autonomous) + its child `AgentStep`. The per-workflow `*_id` columns collapse into `AgentStep.key`; route's old `chain_run` OneToOne is now `AgentRun.parent` (self-FK). `LLMSettings` is the only other model. Migrations `0013`-`0024` (additive create -> per-workflow data migration -> legacy `DeleteModel`).
  - **meta_json refactor (2026-06-13):** the unified models keep only the cross-cutting SPINE as real columns (run: id/user/query/model/status/output/error/timestamps/parent; step: id/run/order/status/error/timestamps/key/label/output); EVERY workflow-specific field now lives in a single `meta` JSONField on each model. `meta_spec.py` declares the per-kind allowed meta keys (+ types/defaults/choices) and `store.py` is the ONLY meta writer — it validates every write against the spec (`store.create_run`/`create_step`/`seed_steps`/`update_run`/`update_step`/`finish_run`) and reads via typed accessors `store.run_meta(run)`/`store.step_meta(step)`. Per-kind DRF serializers use a `MetaField` to reproduce the legacy JSON field names (e.g. `step_id`/`task_id`/`worker_id`/`node_id`/`agent_id` <- `key`; `iterations`/`tasks`/`workers`/`nodes`/`cycles` <- `steps`; `index` <- `order`; `chain_run` <- `parent`; `thought`/`tool`/`score`/`vote`/`wave`/`plan`/etc <- `meta`), so the frontend contract and SSE event shapes are unchanged. Migrations `0025` (add `meta`) -> `0026`-`0034` (per-kind backfill columns->meta) -> `0035` (drop the ~45 legacy columns). The "persists `XRun` + `XStep`" notes below describe the logical run/step rows, now `AgentRun(kind=...)` + `AgentStep` with kind-specific data in `meta`.
  - **Implemented workflow patterns** (all ten complete): Single Prompt, Prompt Chaining, Routing, Parallelization, ReAct, Evaluator-Optimizer, Plan-and-Execute, Orchestrator-Workers (`orchestrator.py`), Multi-Agent Sequential/Hierarchical (`multiagent.py`), Multi-Agent Parallel/DAG (`dag.py`), and Autonomous/Long-Horizon (`autonomous.py`). There is *no* separate `agent` app — everything lives in `llm_analysis`. See CLAUDE.md for per-workflow detail.
  - `react.py` — ReAct agent: bounded Thought->Tool->Observation loop (`react_max_steps`) where the LLM picks the next tool each turn; read-only DB tools in `tools.py`; persists `ReactRun` + `ReactStep`.
  - `eval_opt.py` — Evaluator-Optimizer: generate -> evaluate (JSON `{score,feedback,pass}`) -> revise, stops at `eval_threshold` or `eval_max_iterations`, returns best-scoring draft; persists `EvalOptRun` + `EvalOptIteration`.
  - `plan_execute.py` — Plan-and-Execute: plan upfront -> execute each step via the same read-only tools -> optional bounded replan on tool error (`plan_max_replans`) -> synthesise; persists `PlanExecRun` + `PlanExecStep`.
  - `chain.py` — prompt chaining: 4 fixed steps (`classify` -> `research` (DB lookup via `research_tickers`) -> `synthesise` -> `format`). Persists `ChainRun` + `ChainStepResult` per step.
  - `router.py` — Routing. Resolves each query to `simple`/`analysis`/`comparison`/`deep_research`. `OLLAMA_ROUTE_MODE`=`llm` (default, classifier call) or `semantic` (embedding vs per-route exemplars, 0 LLM calls above `OLLAMA_ROUTE_THRESHOLD`, falls back to LLM). `analysis` fans out 3 aspect calls (Valuation/Profitability/Risk) then aggregates; `comparison` does per-ticker narration then synthesis (degrades to analysis if <2 tickers); `deep_research` runs the chain. Persists `RouteRun` (with `route_method`/`route_confidence`).
  - `parallel.py` — the **observable** Parallelization agent (user picks strategy, no classifier). *Sectioning* reuses `router.ANALYSIS_ASPECTS` via shared `section_batches()`/`aggregate_sections()` (one copy, also used by the analysis route). *Voting* runs N (2-5) buy/hold/sell verdicts with spread `VOTING_TEMPS`, tallies majority (ties -> `hold`), writes a consensus rationale. Streams a per-sub-call `task` SSE event (unlike routes' invisible fan-out) and persists `ParallelRun` + `ParallelTaskResult`.
  - `browser.py` — the **Browser agent** (`kind="browser"`), the ONLY agent that leaves our network: an LLM drives a real headless Chromium via **browser-use** to answer from the live web. Same sync-SSE-generator shape as the others, but browser-use is async, so an inner thread owns the event loop and hands step payloads back over a queue. `build_agent` is the ONLY place touching browser-use's API and the single seam tests patch (no test may launch a browser — a live one belongs behind the `browser_live` marker). Bounded on every axis: `browser_enabled` ships OFF (503 + hint), host allow-list, `max_steps`, wall-clock deadline, a process-wide `BoundedSemaphore(1)` (429 when busy), a `10/hour` throttle, and a fresh credential-free incognito profile. Screenshots are written as FILES under `BROWSER_SCREENSHOT_ROOT` (only the key in `meta`) and served by an owner-checked view, swept daily by `sweep_browser_screenshots`.
    - **Two hard requirements on the Ollama model, both learned the hard way** (2026-08): it MUST have the `vision` capability — browser-use attaches a screenshot every step and a text-only model returns 400 on EVERY step rather than degrading (hence `BROWSER_MODEL=qwen3-vl:8b`, and `provider_supports_vision` asking `/api/show` for capabilities rather than guessing from the name); and it needs `BROWSER_NUM_CTX=32768`, because Ollama's 4096 default cannot hold a ~15.5k-token step prompt and the model then returns an EMPTY string, which browser-use reports as `Invalid JSON: EOF while parsing`. browser-use never sets `num_ctx` itself.
    - Endpoints: `POST /api/llm/browser/`, `history/`, `<uuid>/`, `<uuid>/screenshot/<order>/`. Rendered at `/browse`, a STANDALONE page — not a mode on `/agents` (its own components, its own `browseSession` key, absent from `fetchAllRuns`).
  - Endpoints: `/api/llm/chat/`, `/chat/stream/`, `/summarise/`, `/analyse/`, `/models/`, `/settings/` (GET/PUT/PATCH the singleton), `/chain/` (+ `/chain/run/`, `/chain/<uuid>/`), `/route/`, `/parallel/`, `/react/`, `/evaluate/`, `/plan/` (each + `/history/` and `/<uuid>/`).
  - Frontend: `/agents` route (`frontend/src/routes/agents.tsx`) is a **unified multi-workflow workspace** (no tabs/Compare mode): one query box fans out to N add/removable workflow panels (single / chain / route / parallel / react / evaluate / plan / orchestrate / multiagent / dag / autonomous), each picking its type via a dropdown, with a chip-row summary + aggregate status line. Run 1, 3, or all 11 on the same query side by side. History drawer aggregates runs across every persisted workflow (`fetchAllRuns`) and replays any of them into a single panel via each hook's `loadFromDetail`. `/llm-settings` route is the LLM Settings form (`useLLMSettings`/`useUpdateLLMSettings` hooks, Zod `llmSettingsSchema`).
- `redis_monitor/` — Redis key browser API (`/api/redis/info/`, `/api/redis/keys/`, `/api/redis/keys/<key>/value/`); services.py builds a Redis client from `CELERY_BROKER_URL`
- `tasks/` — PeriodicTask + TaskResult views; `sync_scheduled_tasks` management command
  - Scheduled tasks defined in `apps/tasks/scheduled_tasks.py` (single source of truth)
  - Management command `sync_scheduled_tasks` upserts PeriodicTask rows and prunes stale ones; called in deploy.sh after every deploy
  - API: `GET /api/tasks/results/`, `GET /api/tasks/results/<task_id>/`, `GET /api/tasks/scheduled/`, `PATCH /api/tasks/scheduled/<pk>/toggle/`, `POST /api/tasks/scheduled/<pk>/trigger/`
- `knowledge_graph/` — topic-agnostic self-expanding concept graph. Three models: `Concept` (node: name/slug/`base_slug`/description/`negative_description`/times_expanded; UUID PK) + `ConceptEdge` (directed, typed, weighted; uniq `(source,target,relation)`) + `ConceptAlias` (surface forms that mean a concept; FK -> Concept `related_name="aliases"`, globally-unique `slug`). An LLM (`llm.py`, reuses `llm_analysis.services.chat` with a structured `format` schema) expands a concept into description + `negative_description` ("what it's NOT") + neighbors; `services.py` resolves each neighbor with base_slug/alias-exact + pg_trgm trigram dedup (Postgres-only, degrades to slug-only on SQLite) and accumulates edge evidence on repeats.
  - **Concept identity** (aliases + senses): a node is a CONCEPT, not a word. **Synonymy** — `resolve_concept` gathers candidates by `base_slug` OR an owning alias slug; a trigram-near match records the surface form as a permanent zero-cost alias (`record_alias`, the only alias writer — skips when the slug is canonical / another concept's / an existing alias). `merge_concepts(canonical, [dups])` (+ `manage.py merge_concepts <canonical> <dup>...`, slug/name args, confirm + `--noinput`) folds existing duplicates: re-points edges via `_upsert_edge`, moves aliases, carries description, deletes dups. **Homonymy** — `base_slug` is the shared lexical key while `slug` is unique per sense, so homonyms coexist; gated by `KG_WSD_ENABLED` (default OFF), `_pick_sense` runs the `llm.disambiguate_sense` judge ONLY on an established same-key collision, fed each sense's `{aliases, neighbors, negative_description}` evidence; same-sense -> reuse + record alias (fold), different -> `_create_sense` mints a `name (domain)` node (split). Degrades to legacy first-candidate reuse (no alias) when off / judge raises / no context. Phase 5 (embedding sense vectors) deferred to the planned `embeddings` app.
  - **Growth**: `expand_concept_task` (recursive, follows only NEW nodes, bounded by `max_depth` remaining-hops budget + novelty termination + `KG_MAX_NODES` cap) backs the per-node Expand button / 1st-degree expand. **Auto-expand** (`AutoExpandView` -> `crawl_hub_task`) is the primary driver: picks the top-N=5 most-connected hubs server-side and ring-crawls each hub's frontier outward (depth 1, then 2, then 3), so it keeps growing even when the hubs themselves are already expanded.
  - **Expand-to-degree** (`ConceptExpandView`, the per-concept "1st / 2nd / 3rd degree" buttons): degree 1 -> `expand_concept_task` (expand just the node); degree >= 2 -> `crawl_hub_task` with `rings = degree - 1`, so "2nd degree" expands the selected node's neighbours and "3rd" the ring beyond. The ring crawl's INTERMEDIATE rings traverse through ALREADY-EXPANDED neighbours (`all_neighbor_ids`), only the final ring restricts to `unexpanded_neighbor_ids` — so a deep degree still reaches the unexpanded frontier even when the inner rings were already expanded by an earlier, shallower run (rings budget bounds it; `expand_concept` is idempotent so cycles/revisits are cheap no-ops). The UI fades out a degree button once its whole ball (the node + everything within `degree-1` hops) is already expanded.
  - **Edge hygiene** (keeps the graph sparse): (1) LLM rerank-and-prune (`rerank_node_task` -> `rerank_and_prune`) trims a hub past `KG_RERANK_TRIGGER` (~30) edges down to `KG_RERANK_TARGET` (~15) — fired automatically during expansion, per-node (`ConceptRerankView`), graph-wide (`RerankAllView`), or via the `sweep_rerank_candidates` beat task (every 5 min); (2) transitive reduction (`reduce_transitive_edges`) drops edges implied by a longer same-relation path (A->C when A->B->C exists) — pure DB, idempotent, run synchronously (`ReduceTransitiveEdgesView`) or via `sweep_transitive_edges` beat task (every 15 min).
  - **Cancellation**: every queued task carries a cancel `epoch` (Redis counter); `ExpansionClearView` ("Clear queue") bumps the epoch + purges the broker so queued AND worker-prefetched tasks self-drop. Degrades to no-cancellation if Redis is down. NOTE: adding/renaming a Celery task needs a worker restart.
  - API (`/api/knowledge/`): `concepts/` (list ?search= / create node), `concepts/<id>/` (detail / delete), `concepts/<id>/graph/` ({nodes,edges} subgraph), `concepts/<id>/expand/`, `concepts/<id>/rerank/`, `expansion/auto/`, `expansion/clear/`, `rerank-all/`, `edges/reduce/`. (Removed in current work: the `concepts/unexpanded/` frontier endpoint + `FrontierConceptSerializer` — auto-expand now picks hubs server-side.)
  - **Visualization** (`ConceptGraph.tsx`, ECharts; force/hierarchy/tree/sankey layouts): nodes are coloured + sized by **recursive structural reach** — `services.structure_reach_for` counts the distinct concepts reachable from a node via outgoing `has_subfield`/`prerequisite_for` edges transitively (its recursive subfields + everything it is a prerequisite for; the graph has exactly these two structural relations), computed over the WHOLE graph and attached to each subgraph node as `reach` (serializer field; null on list/detail). The legend reads "Reach". NOT raw neighbour count (`connections` still drives list ordering + hub selection). Frontier (un-expanded, `times_expanded==0`) nodes render as a pale TINT of their heat colour with a dashed ring (`frontierFill`) — never pure white, which was invisible on the canvas.
  - Frontend: `/knowledge` route — create node, per-node + expand-to-degree (1st/2nd/3rd) expand, ECharts graph, overlay panels; Auto-expand top 5 / Clear queue (stop) / Live polling / Rerank & prune / Reduce edges controls. Config seeds via `KG_*` env vars (`KG_SIM_THRESHOLD`, `KG_MAX_DEPTH`, `KG_MAX_NEIGHBORS`, `KG_MAX_NODES`, `KG_RERANK_TRIGGER`, `KG_RERANK_TARGET`).
  - Admin: `manage.py clear_knowledge_graph` hard-resets the graph — deletes ALL `Concept` + `ConceptEdge` rows (rich table + confirm prompt; `--noinput` skips). Tests: `tests/test_clear_command.py`. `manage.py merge_concepts <canonical> <dup>...` folds duplicates into a canonical node. Tests: `tests/test_merge_command.py`.

### Celery Architecture

**Infrastructure:**
- Broker: Redis (`CELERY_BROKER_URL`, default `redis://localhost:6379/0`)
- Result backend: `django-db` (via `django_celery_results`, stored in PostgreSQL)
- Beat scheduler: `django_celery_beat.schedulers:DatabaseScheduler` (schedule in DB)
- `core/celery.py` — creates app, `config_from_object("django.conf:settings", namespace="CELERY")`, `autodiscover_tasks()`
- All task code lives in `apps/companies/tasks.py` (only app with a tasks.py)

**Task hierarchy (3 layers):**

1. **Dispatchers** — read all `is_bootstrapped=True` symbols, chunk into batches of 50, fan out via Celery `group`. All are `@shared_task` (no retries).
   - `dispatch_profile_sync`, `dispatch_price_sync`, `dispatch_snapshot_sync`, `dispatch_financial_sync`, `dispatch_dividend_sync`, `dispatch_institutional_holders_sync`, `dispatch_earnings_dates_sync`, `dispatch_options_sync`

2. **Batch leaf tasks** — receive `list[str]` of symbols, loop and call the service function for each. All have `max_retries=3, default_retry_delay=60`.
   - `sync_profiles_batch`, `sync_prices_batch`, `sync_snapshots_batch`, `sync_financials_batch`, `sync_dividends_batch`, `sync_institutional_holders_batch`, `sync_earnings_dates_batch`, `sync_options_batch`

3. **Single-symbol tasks** — UI-triggered (one company at a time, no retry config):
   - `sync_profile_single`, `sync_prices_single`, `sync_snapshot_single`, `sync_financials_single`, `sync_dividends_single`, `sync_short_interest_single`, `sync_institutional_holders_single`, `sync_earnings_single`, `sync_options_single`

**Bootstrap flow (separate from periodic sync):**
- `discover_new_symbols` — scrapes S&P 500 (GitHub CSV) + NASDAQ-100 (api.nasdaq.com), creates un-bootstrapped stubs
- `bootstrap_tick` — processes next 5 un-bootstrapped companies sequentially (`max_retries=0`)

**Other tasks:**
- `backfill_snapshot_fields_task` — backfills new CompanySnapshot columns from `.raw` JSON (no API calls)
- `bulk_import_symbols(symbols)` — manual yfinance batch import
- `ingest_symbol_full(symbol)` — full ingest for one symbol (profile + prices + snapshot + financials + dividends)

**Beat schedule (all in `scheduled_tasks.py`):**

| Task name | Schedule | What it does |
|---|---|---|
| companies-discover-new-symbols-weekly | Sun 01:00 | Bootstrap: discover new symbols |
| companies-bootstrap-tick | Every 20 min | Bootstrap: ingest next 5 un-bootstrapped |
| companies-dispatch-profile-sync-weekly | Sun 02:00 | Sync company profiles |
| companies-dispatch-price-sync-daily | Daily 21:30 | Incremental price bars (after NYSE close) |
| companies-dispatch-snapshot-sync-daily | Daily 22:00 | Point-in-time snapshot |
| companies-dispatch-financial-sync-monthly | 1st of month 03:00 | Financial statements |
| companies-dispatch-dividend-sync-sunday | Sun 03:00 | Dividends |
| companies-dispatch-dividend-sync-wednesday | Wed 03:00 | Dividends |
| companies-backfill-snapshot-fields-weekly | Sun 01:30 | Backfill snapshot fields from .raw |
| companies-dispatch-institutional-holders-quarterly | 2nd Jan/Apr/Jul/Oct 04:00 | Institutional holders |
| companies-dispatch-earnings-dates-weekly | Sun 04:00 | Earnings dates |
| companies-dispatch-options-daily | Mon–Fri 22:00 | Options chains |
| knowledge-sweep-rerank-candidates | Every 5 min | KG: rerank-and-prune every node over the trigger |
| knowledge-sweep-transitive-edges | Every 15 min | KG: transitive reduction of the hierarchy |

### Frontend Shell

Navigation is a **collapsible left sidebar**, not a topbar (`sidebar-navigation.md`, 2026-08-05).
`components/layout/nav.ts` (`NAV_LINKS` + lucide icons + `isNavActive`) is the single source of
truth; `Sidebar.tsx` renders a `w-60` panel that collapses to a `w-14` icon rail and becomes an
overlay drawer below `md`. The collapse flag lives in `store/ui.ts` (Zustand + `localStorage`)
**because AppShell remounts on every navigation** — each route renders its own `<AppShell>`, so
`useState` would reset it. The topbar keeps only clock / email / Admin / Logout.
`FullBleed.tsx` replaced the old `left-1/2 -mx-[50vw] w-screen` hack in `/knowledge`: with a
sidebar, a viewport-width bleed sits under it, so the bleed is content-column width.

### Frontend Routes

- `/` — Dashboard (stats + quick nav)
- `/companies` — Server-side paginated + filtered company table
- `/companies/$id` — Company detail with CompanyTabs (Overview, Market Data, Financials, Dividends, ESG, Earnings, Options, Ownership)
- `/sectors` — Sector breakdown charts
- `/industries` — Industry breakdown charts
- `/market-map` — Market cap treemap (ECharts)
- `/tasks` — Task monitor (PeriodicTask + TaskResult)
- `/redis` — Redis key browser
- `/llm` — LLM playground (chat / summarise / analyse / models)
- `/agents` — Unified multi-workflow workspace: run one query across N add/removable workflow panels (single / chain / route / parallel / react / evaluate / plan / orchestrate / multiagent / dag / autonomous), compare side by side; cross-workflow history replay
- `/browse` — Browser agent: search box, live step timeline with screenshots, markdown answer with Sources, own history sidebar. Standalone; shares no state with `/agents`
- `/llm-settings` — LLM Settings form (runtime `LLMSettings` singleton editor)
- `/knowledge` — Self-expanding concept graph (ECharts; nodes coloured/sized by recursive structural **reach**, not connections): create node, per-node + expand-to-degree (1st/2nd/3rd) expand, Auto-expand top 5 hubs, Clear queue, Live polling, Rerank & prune, Reduce edges

### Test Counts (latest)

- Backend: **2589 tests passing**, 97.3% coverage (as of 2026-09-29, after issues #10/#11/#13)
- Frontend: **852 tests passing / 79 files** (as of 2026-09-29; stack upgraded 2026-06-15; stack upgraded 2026-06-15 — React 19 / Vite 8 / Vitest 4 / Zod 4 / TS 6 / ESLint 10; see [[frontend-stack]])

### Infrastructure

- **Provisioning is Pulumi** (`infra/pulumi/`, Python + `uv`, `pulumi-proxmoxve` bridging the same `bpg/proxmox` provider). Terraform (`infra/proxmox/`) was **removed** on 2026-08-05 — the live containers were imported into Pulumi state, never recreated. Three layers unchanged in principle: Pulumi (machines) -> Ansible (bootstrap, once) -> CI/CD webhook (app deploys, every push).
  - State: **local file backend** at `infra/pulumi/state/` (gitignored). Config secrets are encrypted in `infra/pulumi/Pulumi.prod.yaml` (committed) and decrypted by `infra/pulumi/.passphrase` (**gitignored and NOT backed up anywhere else** — losing it means re-entering all stack config).
  - Commands: `just pu-preview` / `pu-up` / `pu-refresh` / `pu-stack`. There is **no `pu-destroy`** by design; both containers carry `protect=True`.
  - Rollback artifact from the migration: `~/terraform.tfstate.pre-pulumi-migration`.
- **Prod server:** `192.0.2.200` (root@stockmarket), app at `/home/app/stock_market/`
- **DB server:** `192.0.2.201` (root@192.0.2.201, `su postgres` for superuser psql)
- **uv path on prod:** `/home/app/.local/bin/uv`
- **Deploy script:** `/home/app/stock_market/infra/deploy.sh` (this is what the webhook calls)
  - `/home/app/deploy.sh` was a stale leftover — now deleted
  - Steps: git pull → uv sync → migrate → sync_scheduled_tasks → collectstatic → npm build → restart services
- **pgvector extension** must be installed as postgres superuser before first migrate:
  `su -c "psql -d stockmarket -c 'CREATE EXTENSION IF NOT EXISTS vector;'" postgres`
- **Wikipedia is IP-blocked** on prod for both regular and REST API endpoints — use GitHub CSV / NASDAQ API instead

### Key justfile recipes

- `just pu-preview` / `just pu-up` — Pulumi container provisioning (see Known Gotchas: `pu-up` can reboot prod)
- `just prod-discover` — runs discover_new_symbols on prod via SSH
- `just prod-superuser` — creates default users on prod
- `just be-discover` — runs discover locally
- `just be-sync-tasks` — runs sync_scheduled_tasks (apply scheduled_tasks.py changes to DB)

### Known Gotchas

- shadcn base-nova Input requires `React.forwardRef` for RHF compatibility (still works under React 19, where `forwardRef` is deprecated but not removed)
- Wikipedia (en.wikipedia.org) blocks prod server IP — S&P 500 uses GitHub CSV, NASDAQ-100 uses api.nasdaq.com
- pgvector requires superuser to install; `stockmarket` DB user cannot do it
- DB is on a separate VM (192.0.2.201); can SSH as root but `psql` needs `su postgres`
- **`just pu-up` can reboot both prod containers.** Measured 2026-08-05: an apply touching `console`/`startOnBoot` restarted both (~10-15 s of API + DB downtime) even though every value written already matched the live Proxmox config. A later tags-only apply restarted nothing. A value-neutral diff is NOT automatically a no-op — read `pu-preview`'s field list and treat anything beyond tags/metadata as a planned outage.
- **Three container fields are pinned via `ignore_changes`** (`initialization.userAccount`, `operatingSystem`, `features`): the Proxmox API cannot read them back, so after an import they read as empty and Pulumi wants to REPLACE (destroy) the containers. All three are ForceNew anyway. `protect=True` is the backstop that turns such a replace into a hard error.
- **Pulumi is not on the non-interactive PATH** (`~/.pulumi/bin` is only in `~/.bashrc`); the justfile exports it explicitly.
- When editing container config, never `pulumi destroy` / never let a `disk.datastoreId` change apply — that replaces (wipes) production containers.

**Why:** Track infrastructure facts so future sessions don't re-diagnose the same issues.
**How to apply:** Use these facts for any prod debugging, deploy, or data-seeding tasks.
