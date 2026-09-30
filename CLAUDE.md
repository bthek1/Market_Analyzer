# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Memory

All persistent memory lives in `docs/claude-memory/`. The index is `docs/claude-memory/MEMORY.md`. Read and write memory files there — not in `~/.claude/projects/`.

## Project

Market Analyzer — Django + DRF backend, React + Vite frontend, PostgreSQL + pgvector for RAG, Ollama for local LLM, Celery for async tasks.

## Commands

```bash
just dev                          # Start all services (DB, Redis, Django, Vite, Celery)
just db-up                        # Start only PostgreSQL + Redis containers
just install                      # Install backend (uv) + frontend (npm) deps

# Backend
just be-dev                       # Django dev server on :8004 (runs migrations first)
just be-test                      # Run full pytest suite
just be-test-cov                  # Tests with coverage report
just be-lint                      # ruff check
just be-fmt                       # ruff format
just be-makemigrations [app]      # Generate migrations (app name optional)
just be-migrate                   # Apply migrations
just be-shell                     # Django interactive shell
just be-celery                    # Start Celery worker

# Frontend
just fe-dev                       # Vite dev server on :5173
just fe-test                      # Vitest suite
just fe-build                     # Production build
just fe-lint                      # ESLint

# Infrastructure (Pulumi + Proxmox)
just pu-preview                   # pulumi preview (preview changes)
just pu-up                        # pulumi up --yes (create/update LXC) - CAN REBOOT the containers
just pu-refresh                   # pulumi refresh (record out-of-band Proxmox changes)
just pu-stack                     # stack outputs (container ids + hostnames)
# No pu-destroy by design: both containers are protect=True.

# Load testing (k6, issue #12) - read-only traffic; results on Grafana `Load Testing`
just lt-install                   # pinned static k6 binary into ~/.local/bin
just lt-user                      # create/refresh the non-staff load-test user
just lt-smoke                     # 1 VU, 30 s, against local `just dev`
just lt PROFILE [TARGET]          # smoke|load|stress|spike|soak, local|prod
                                  #   (prod needs LOADTEST_ALLOW_PROD=1 for that one run)
just lt-inspect                   # parse every script x profile, send nothing

# Ansible (machine bootstrap only — app deploys happen via CI/CD)
just ansible-ping                 # connectivity check
just ansible-full                 # full first-time bootstrap (site.yml)
just deploy-log                   # tail /home/app/deploy.log on prod
```

Run a single test file: `pytest backend/apps/<app>/tests/test_<file>.py -v`

First-time setup: `just env-init` → edit `.env` (repo root) → `just install` → `just db-up` → `just dev`

## Architecture

```
backend/                Django REST API (Python 3.13, uv)
  core/settings/        base.py / dev.py / prod.py / test.py
  core/celery.py        Auto-discovers tasks.py in all apps
  core/logging.py       Structured JSON logging: a request-id ContextVar, a logging
                        Filter that stamps it on every record, and a JSONFormatter that
                        merges caller extra={} fields into the line. See "Observability"
  core/middleware.py    RequestIDMiddleware - binds the correlation id for the request
  apps/
    accounts/           Auth — CustomUser (email as USERNAME_FIELD, UUID PK), JWT
    companies/          Company + Sector CRUD + yfinance ingestion (price bars, snapshots,
                        financials, dividends) via Celery; yfinance_client.py wraps yfinance.
                        Also owns the AI COMPANY SUMMARY (services.generate_company_summary ->
                        CompanySummary, the AI Summary tab on /companies/$id) - see
                        "AI Company Summary" below
    llm_analysis/       Ollama LLM — routing (router.py: simple/analysis/comparison/
                        deep_research; LLM or semantic-embedding route selection),
                        prompt chaining (chain.py), observable parallelization
                        (parallel.py: sectioning + voting), a ReAct agent (react.py:
                        bounded Thought->Tool->Observation loop over read-only DB tools in
                        tools.py), an Evaluator-Optimizer agent (eval_opt.py: generate ->
                        evaluate -> revise loop gated by an evaluator score), and a
                        Plan-and-Execute agent (plan_execute.py: plan upfront -> execute each
                        step via the read-only tools -> optional bounded replan -> synthesise),
                        an Orchestrator-Workers agent (orchestrator.py: a lead LLM
                        dynamically decomposes the query into independent subtasks -> fan out
                        concurrently to worker LLMs via chat_many -> synthesise), and a
                        Multi-Agent Sequential/Hierarchical agent (multiagent.py: a supervisor
                        routes a fixed, role-specialised roster (Researcher -> Analyst -> Writer,
                        each with its own prompt + allow-listed tools) run as a sequential
                        hand-off pipeline -> supervisor synthesises), and a Multi-Agent
                        Parallel/DAG agent (dag.py: an orchestrator dynamically decomposes the
                        query into a dependency graph -> topological_waves layers it Kahn-style
                        -> independent nodes in each wave fan out concurrently via chat_many,
                        dependents consume upstream outputs -> synthesise the sink outputs), and an
                        Autonomous / Long-Horizon agent (autonomous.py: a goal-driven, hard-bounded
                        controller loop -> each cycle reflect -> self-assign a task -> act via a
                        read-only tool / a bounded non-recursive spawned sub-agent / pure reasoning
                        -> fold into working memory -> replan the backlog, stopping on goal_complete /
                        cycle budget / a no-progress detector -> synthesise; AutoGPT-style);
                        every workflow shares ONE SSE + terminal-run layer (_events.py:
                        sse/event framing, succeed/fail generators that write the row and emit
                        the terminal event together, and step_event, whose payload IS the step
                        serializer's output so the live stream and the detail endpoint are one
                        serialisation - issue #6 phases 1-2; the control LOOP is still per-module,
                        phases 3-6) and persists to TWO unified, polymorphic models - AgentRun
                        (discriminated by `kind`: chain/route/parallel/react/eval_opt/plan_exec/
                        orchestrator/multiagent/dag/autonomous) + its child AgentStep. Each keeps
                        only the cross-cutting SPINE as real columns (run: id/user/query/model/
                        status/output/error/timestamps/parent; step: id/run/order/status/error/
                        timestamps/key/label/output); ALL workflow-specific fields live in a single
                        `meta` JSONField. `meta_spec.py` declares the per-kind allowed meta keys
                        (+ types/defaults/choices); `store.py` is the ONLY meta writer (validates
                        every write; read via `store.run_meta`/`step_meta`). Per-workflow `*_id`
                        collapse into AgentStep.key; route's old chain_run OneToOne is now
                        AgentRun.parent self-FK. Per-kind DRF serializers (via a `MetaField`)
                        reproduce the legacy JSON field names (e.g. step_id/task_id/worker_id/
                        node_id/agent_id <- key; iterations/tasks/workers/nodes/cycles <- steps;
                        index <- order; chain_run <- parent; thought/tool/score/vote/wave/etc <-
                        meta) so the frontend contract is unchanged; blocking + SSE streaming +
                        concurrent fan-out (chat_many) in services.py
                        BROWSER AGENT (browser.py, kind="browser"): the ONE agent that leaves our
                        network - an LLM driving a real headless Chromium via browser-use to answer
                        a question from the live web. Same runtime shape as the others (a sync SSE
                        generator under services.stream_in_background), but browser-use is async, so
                        an inner thread owns the event loop and hands step payloads back over a queue
                        while the generator thread does the DB writes. `build_agent` is the ONLY
                        place touching browser-use's API and the single seam tests patch - NO test
                        may launch a browser (a live one belongs behind the `browser_live` marker).
                        Bounded on every axis: `browser_enabled` ships OFF (view -> 503 + hint), a
                        host allow-list on the BrowserSession, `max_steps`, a wall-clock deadline
                        enforced via register_should_stop_callback, a process-wide
                        BoundedSemaphore(1) (a second caller gets 429 - one Chromium is ~400 MB on a
                        4 GB box), a DRF ScopedRateThrottle ("browser", 10/hour), a fresh incognito
                        profile per run (no cookies/credentials, no local file access), and
                        browser-use's telemetry + cloud sync forced off at import. Step SCREENSHOTS
                        are written to BROWSER_SCREENSHOT_ROOT as files with only the relative key
                        in meta (base64 in JSONB would be ~200 KB/step) and served by an
                        owner-checked view, never static/media; a daily Celery Beat sweep
                        (tasks.py: sweep_browser_screenshots) drops them past the retention window.
                        The driving LLM is OLLAMA by default (free/local), pinned to the VISION
                        model qwen3-vl:8b - browser-use sends a screenshot every step and a
                        text-only model 400s on every one of them, so this is not optional.
                        Anthropic is selectable per run and is far more reliable at browser-use's
                        strict per-step action JSON (local 8B models loop).
                        Endpoints: POST /api/llm/browser/, history/, <uuid>/,
                        <uuid>/screenshot/<order>/. Rendered at /browse (its own page).
                        CHAT AGENT (chat_agent.py, kind="chat"): conversational chat inside the
                        harness (issue #8, phase 1 of 6). A TURN IS A RUN - query = the user
                        message, output = the reply, steps = the turn's tool calls - so a
                        conversation is an ordered list of runs, not a Message model. ReAct's loop
                        shape, because that is what reaches tools.run_tool; prompt permits
                        answering with no tool at all. POST /api/llm/chat-agent/ (slug is
                        chat-agent because /api/llm/chat/ is the LEGACY non-harness endpoint,
                        still serving useSinglePrompt). Rendered at /chat (its own page, like /browse - a
                        conversation is not comparable to a one-shot run, so it is absent
                        from COMPARABLE_TYPES and fetchAllRuns). TOKEN STREAMING (phase 5): an ANSWER is
                        now PLAIN PROSE and only a tool call is JSON, because half a JSON
                        object cannot be forwarded token by token; `looks_like_tool_call`
                        decides on the first non-blank character (hence the prompt rule
                        against opening an answer with `{`). services.chat_tokens is the raw
                        primitive and chat_stream now just frames it; _events.delta frames
                        the slice; _runtime.Strategy.perform_streaming is an OPT-IN hook
                        (BaseStrategy returns None) returning a generator that emits while
                        the step works - `after` cannot, since by then the events arrive in a
                        burst. Measured live: first token 0.19s vs 1.26s for the full reply.
                        CARRY_OBSERVATION_CHARS=600 exists because the prose protocol caused
                        a REGRESSION: _rehydrate replays query/output, NOT the tool
                        observations behind them, so a follow-up about a just-fetched figure
                        could not see it and the model INVENTED one (wrong in 2 of 3 measured
                        runs; prompt hardening alone fixed 1 of 3). The last turn's
                        observations now ride along truncated, as OBSERVATIONS so Scratchpad
                        sheds them first - 5 of 5 correct after.
                        /agents and /chat are one click apart via
                        components/layout/WorkspaceSwitch.tsx (LINKS, not a mode; never
                        disabled mid-run, since runs are durable server-side and both pages
                        reconnect on arrival; `active` is a prop so it needs no router to
                        test; NB the AppShell sidebar has its own "Chat" link, so scope test
                        queries to role=navigation name=Workspace).
                        VERIFIED IN THE BROWSER (2026-09-28): tool use with disclosure,
                        conversation memory across turns, and an appropriate refusal on
                        "what should i buy?". It exposed two TOOL-side problems, both FIXED by
                        issue #9 (see tools.py below): an AVG of a ratio the model reasoned from
                        (Technology avg trailing P/E 160.95, ABOVE its own p75 of 62), and a
                        "never invent a NUMBER" rule obeyed literally, so the model invented a
                        RANKING instead. Issue #9's live A/B then found a third (issue #10,
                        FIXED): on "is NVDA cheap vs the sector?" the model called NO tool in
                        8/8 runs and read NVDA's "figures" off OTHER rows of the carried sector
                        observation (AVGO's P/E as NVDA's forward P/E). A prompt rule did not
                        move it, so the fix is CODE: `named_tickers` finds a ticker the user
                        NAMED and ChatStrategy runs `peer_comparison` for it as an ordinary
                        persisted step BEFORE the model's first call (0/5 misattributed after,
                        vs 4/5). Prefetch, not an answer-time gate, because an answer STREAMS -
                        by the time a missing lookup is noticed the user has read it. Only
                        capitalised words (or `$nvda`) count: SO/NOW/ALL/ON/KEY/A are all real
                        symbols. Issue #13 (FIXED) was the next layer down: with every figure
                        right, the model still wrote "28.49 is slightly above 34.30" in 9/10
                        runs, so the prefetch is now `peer_comparison`, which hands over the
                        RELATION computed ("18% below", a band, a reading) - 0/10 after. Its
                        first version gave only P/E and P/B a cheap/expensive `reading`, and the
                        model borrowed it for ROE and margins ("more expensive ... based on
                        return on equity", 4/10), so EVERY metric now has a reading in its own
                        vocabulary (profitable / yield / leveraged) - 0/10. See
                        docs/project_docs/chat-agent.md.
                        The LEGACY path is gone (phase 6): ChatPanel, useLLMChat, the
                        /agents chat MODE, ChatStreamView, /api/llm/chat/stream/ and
                        services.chat_stream are all removed; /api/llm/chat/ (ChatView)
                        STAYS because useSinglePrompt still uses it, pinned by a test. The
                        span is still named `ollama.chat_stream` though the function is
                        `chat_tokens` - it names the OPERATION, and renaming it would empty
                        the tracing panels and span metrics keyed on it.
    redis_monitor/      Read-only Redis introspection API (info, keys, values)
    tasks/              Celery Beat periodic-task management; SCHEDULED_TASKS in
                        scheduled_tasks.py is the source of truth, synced via management command
    knowledge_graph/    Topic-agnostic self-expanding concept graph. Three models - Concept
                        (node: name/slug/base_slug/description/negative_description/times_expanded;
                        UUID PK; no root-relative topic/depth - the start point is irrelevant in a
                        pure graph) + ConceptEdge (directed, typed, weighted; uniq
                        (source,target,relation)) + ConceptAlias (surface forms that MEAN a concept:
                        FK -> Concept related_name="aliases", globally-unique slug - one word cannot
                        point at two concepts). An LLM (llm.py: reuses llm_analysis.services.chat
                        with a structured `format` JSON schema; tolerant parse, never raises) expands
                        a concept into a description + a negative_description ("what it is NOT", the
                        homonym contrast signal) + neighbors; services.py resolves each neighbor with
                        base_slug/alias-exact + pg_trgm trigram dedup (PostgreSQL only - degrades to
                        slug-only on SQLite tests).
                        CONCEPT IDENTITY (aliases + senses; a node is a CONCEPT, not a word):
                        SYNONYMY (recall) - resolve_concept gathers candidates by base_slug OR an
                        owning alias slug; a trigram-near match records the surface form as a
                        permanent zero-cost alias via record_alias (the ONLY alias writer - no-op
                        when the slug is canonical / another concept's / an existing alias, never
                        raises). merge_concepts(canonical, [dups]) folds existing duplicates
                        (graph/graphs, node/nodes): re-points edges via _upsert_edge, moves/folds
                        aliases, carries description (no clobber), deletes dups - one transaction,
                        idempotent. HOMONYMY (precision) - each node has a `base_slug` (the shared
                        lexical key; slug is unique per sense) so homonyms coexist; when a name
                        collides with an already-DESCRIBED concept and KG_WSD_ENABLED is on
                        (default OFF), _pick_sense runs an LLM judge (llm.disambiguate_sense, fed the
                        usage context {domain,relation} AND each candidate sense's
                        {aliases, neighbors, negative_description} evidence) ruling same-sense
                        (reuse + record_alias fold) vs different (mint a disambiguated `name (domain)`
                        node) - so "pop" the genre and "pop" the stack op no longer merge; gated to
                        established-collision-only + degrades to legacy first-candidate reuse (no
                        alias) when off / judge raises / no context. So one resolution call BOTH folds
                        synonyms (alias) and splits homonyms (new sense) over the same candidate set.
                        Resolution feeds the LLM the node's existing neighbor
                        names as convergence feedback, accumulates edge evidence (running-mean
                        weight + times_seen) on repeats, and a single recursive Celery task
                        (tasks.py: expand_concept_task) fans out bounded by max_depth (a
                        remaining-hops budget passed down and decremented each level, NOT a stored
                        node field) + novelty termination (a branch with no new nodes spawns no
                        children) + a global KG_MAX_NODES cap.
                        AUTO-EXPAND (the primary growth driver): AutoExpandView
                        (POST /api/knowledge/expansion/auto/ {max_depth}) picks the top-N=5
                        highest-REACH hubs server-side (top_reach_concept_ids - recursive subfield +
                        prerequisite-for count via structure_reach_for, the same metric the graph
                        colours by; ties break by degree then name) and seeds one
                        crawl_hub_task per hub - a RING crawl that expands the hub's frontier
                        outward ring by ring (depth 1, then 2, then 3). Its INTERMEDIATE rings follow
                        all_neighbor_ids (traversing THROUGH already-expanded neighbours), and only
                        the FINAL ring restricts to unexpanded_neighbor_ids - so a deep crawl still
                        reaches the unexpanded frontier beyond an already-expanded inner ring; the
                        rings budget bounds it and expand_concept is idempotent, so revisiting a node
                        around a cycle is a cheap no-op. (NB the older expand_concept_task crawl that
                        follows only NEW nodes still backs the per-node Expand button / 1st degree.)
                        EXPAND-TO-DEGREE (ConceptExpandView, the per-concept 1st/2nd/3rd buttons):
                        degree 1 -> expand_concept_task (expand just the node); degree >= 2 ->
                        crawl_hub_task with rings = degree-1 (2nd expands the node's neighbours, 3rd
                        the ring beyond). The UI fades a degree button out once its whole ball (node +
                        everything within degree-1 hops) is already expanded.
                        HUB CONTROL keeps the graph sparse: a node over KG_RERANK_TRIGGER (30) edges
                        is queued for rerank_node_task -> rerank_and_prune, an offline LLM rerank
                        (llm.rerank_neighbors) that keeps the KG_RERANK_TARGET (15) strongest/most-
                        correct edges; structural prune_edges enforces a KG_MIN_EDGE_WEIGHT floor +
                        KG_MAX_DEGREE cap (never orphaning a node's single best link);
                        reduce_transitive_edges drops an A->C edge implied by a longer same-relation
                        A->B->C path. Two Celery Beat sweeps (apps/tasks/scheduled_tasks.py) decouple
                        clean-up from expansion: sweep_rerank_candidates (every 5 min, all nodes over
                        the trigger) and sweep_transitive_edges (every 15 min); both idempotent no-ops
                        when nothing is due. CANCELLATION: every queued task carries a cancel "epoch"
                        (a counter in the broker's Redis); ExpansionClearView
                        (POST /api/knowledge/expansion/clear/) -> clear_expansion_queue bumps the
                        epoch AND purges the broker, so a worker drops any task whose epoch is now
                        stale (expansion_cancelled) - catching BOTH broker-queued AND worker-prefetched
                        tasks a bare purge would miss; new expansions stamp the new epoch and run
                        normally. All Redis access degrades to "no cancellation" if Redis is down
                        (eager tests). NOTE: adding/renaming a Celery task (e.g. crawl_hub_task) needs
                        a worker restart - the worker registers tasks only at startup.
                        API (/api/knowledge/): create node + per-node expand are SEPARATE endpoints;
                        plus concept list/detail (filter ?search=, ordered by connections desc), a
                        {nodes,edges} subgraph for viz (each node carries `reach` = its recursive
                        structural reach via structure_reach_for - distinct concepts reachable by
                        outgoing has_subfield/prerequisite_for edges transitively, computed over the
                        WHOLE graph; the frontend colours/sizes nodes by this, NOT raw connections),
                        expansion/auto (top-N hub ring crawl),
                        expansion/clear (cancel + purge), per-node + graph-wide rerank (rerank/,
                        rerank-all/), and edges/reduce/ (synchronous transitive reduction). The
                        trigram GIN index is added Postgres-only via an AddIndexPostgresOnly migration
                        wrapper so SQLite test migrations pass. Caveat: alias/trigram dedup catches
                        lexical variants, not differently-worded synonyms (e.g. "QM" vs "quantum
                        mechanics") - manual merge_concepts covers those meanwhile; embedding sense
                        vectors (Phase 5, DEFERRED until the planned `embeddings` app) are the future
                        drop-in (cheap cosine over MEANING, would also replace the LLM sense judge).
                        Config seeds via KG_* env vars.
                        ADMIN: `manage.py clear_knowledge_graph` deletes ALL Concept + ConceptEdge rows
                        (rich table + confirm prompt; `--noinput` to skip) - a hard reset of the graph.
                        `manage.py merge_concepts <canonical> <dup>...` (slug/name args) folds
                        duplicate nodes into a canonical one (rich preview + confirm; `--noinput`).
    codegraph/          Read-only API over the graphify CODE graph (see "Code Graph" below).
                        NO models, no migrations - services.py is the only reader of
                        graphify-out/graph.json (path from GRAPHIFY_GRAPH_PATH, default
                        <repo>/graphify-out/graph.json), memoised on the file's mtime. It
                        NORMALISES graphify's raw schema (`links` -> edges, `file_type` -> kind,
                        `source_file`/`source_location` -> file/line) and derives `layer`
                        (backend/frontend/infra/other) + `module` from the path, so graphify
                        renaming a field is a one-file fix. Filters + a degree-ranked `limit`
                        prune SERVER-side (the full graph is ~5.5 MB - never ship it raw).
                        A missing file is a NORMAL state (the artefact is gitignored): 404 with
                        a `hint`, which the UI renders as an empty state; corrupt file -> 409.
    embeddings/         PLANNED (not yet built) — RAG pipeline: documents -> chunks ->
                        pgvector search -> Claude generation; embeds via Ollama nomic-embed-text
loadtest/k6/            k6 load tests (issue #12) - see "Load Testing (k6)" below
frontend/               React SPA (TypeScript, Vite)
  src/api/              Axios client (client.ts), domain API fns, queryKeys.ts
  src/components/       ui/ (shadcn/base-nova — see note), layout/, companies/
                        layout/ = AppShell (collapsible left Sidebar + slim topbar with the
                        user actions + StatusBar footer), Sidebar.tsx, nav.ts (NAV_LINKS +
                        icons, the single source of truth for nav), LogoMark.tsx,
                        FullBleed.tsx (breaks a page out of main's px-6/py-8 to fill the
                        content column — column-width, NOT w-screen, which would sit under
                        the sidebar)
  src/hooks/            Business logic only — useAuth.ts, useCompanies.ts
  src/routes/           TanStack Router file-based: /, /companies, /companies/$id, /login, /register,
                        /agents, /knowledge (concept-graph UI: create node, per-node + expand-to-degree
                        (1st/2nd/3rd) expand, ECharts graph in force/hierarchy/tree/sankey layouts -
                        nodes coloured/sized by recursive structural `reach` (not connections), frontier
                        nodes drawn as a pale tint (never invisible white); the selected-concept panel
                        shows its negative_description ("Not to be confused with: ..."); Build/Concept/
                        Auto-expand overlay panels; Auto-expand top 5, Clear queue (stop), Live polling,
                        Rerank & prune, Reduce edges controls),
                        /code-graph (the graphify CODE graph - ECharts force layout via
                        components/codegraph/CodeGraph.tsx; colour = LAYER not community
                        (~400 communities is unreadable as a categorical scale), size = degree,
                        edge dash = confidence (EXTRACTED solid / INFERRED dashed); filter row
                        + selected-node panel listing callers/callees with file:line; defaults
                        to EXTRACTED-only so guesses are opt-in),
                        /chat (the CHAT agent - a STANDALONE page: session sidebar with
                        rename/delete, transcript with collapsed per-turn tool calls, composer
                        with Stop. Only the SESSION ID is in localStorage (`chatSession`) - the
                        transcript is always re-fetched, because AgentRun.query/output ARE the
                        messages and a local copy would drift from what the model is sent. A 409
                        REMOVES the optimistic turn rather than just showing an error; a stopped
                        turn stays visible because the backend replays its partial output into
                        the next prompt; the compaction summary renders once at the top, being a
                        property of the conversation),
                        /browse (the BROWSER agent - a STANDALONE page, deliberately not a mode on
                        /agents: search box + live step timeline with screenshots + markdown answer
                        with a Sources list + its own history sidebar reading
                        /api/llm/browser/history/. Shares no state with the Agents workspace - its
                        own components/browser/*, its own `browseSession` localStorage key, and it
                        is absent from agents.tsx's COMPARABLE_TYPES and from fetchAllRuns())
  src/schemas/          Zod schemas — auth.ts, companies.ts
  src/store/            Zustand stores (immer middleware) — auth.ts
  src/types/            TypeScript types matching API shapes — auth.ts, companies.ts
  src/test/             MSW handlers, test server, renderWithQuery helper
```

## Backend Conventions

**Layer responsibilities** — views handle HTTP only (auth, parse, delegate); business logic and ORM queries go in `services.py`; serializers own field validation; Celery tasks call services.

**Always use class-based views** (`APIView` for actions, `generics.*` for CRUD). Never `JsonResponse` — always DRF `Response`.

**Models**: UUID PKs on all models (`models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)`). Use `get_user_model()`, never import `User` directly.

**N+1**: always use `select_related` / `prefetch_related` in views and services.

**Datetimes**: always timezone-aware — `from datetime import UTC, datetime as dt` → `dt.now(UTC)`. Never `datetime.now()` or `datetime.utcnow()`.

**ASCII only** in all code, docstrings, and comments (prevents RUF001/RUF002/RUF003).

All endpoints are prefixed `/api/`. Each app owns its own `urls.py`, included from `core/urls.py`.

Settings module for tests is set in `pyproject.toml` `[tool.pytest.ini_options]` (`core.settings.test`).

## Testing

- **NEVER** use `django.test.TestCase`, `unittest`, or `unittest.TestCase` inheritance
- **ALWAYS** use `@pytest.mark.django_db` and plain `pytest` classes
- Shared fixtures (`api_client`, `user`, `auth_client`) are in `backend/conftest.py`
- DRF pagination wraps list responses: use `response.data["count"]` and `response.data["results"]`, not `len(response.data)`
- Unauthenticated writes with JWT return **401**, not 403
- To send `None` values in DRF test client: use `format="json"` (multipart can't encode null)
- Coverage targets: 80% overall, 95% models, 85% views, 90% utilities
- Mock external services with `unittest.mock.patch`

## Frontend Conventions

**State**: server data → TanStack Query; global/UI state → Zustand; local → `useState`. Never put server-fetched data in Zustand. `src/store/ui.ts` holds the sidebar
collapse flag (persisted to `localStorage` by hand, like `store/auth.ts` — no `persist`
middleware); it must be a store, not `useState`, because every route renders its own
`<AppShell>` and so the shell remounts on navigation.

**API calls**: all HTTP through the Axios instance in `src/api/client.ts` (attaches JWT, handles silent 401 refresh). Centralize query keys in `src/api/queryKeys.ts`. Mutations must invalidate relevant queries on success.

**Forms**: Zod schema in `src/schemas/` → `zodResolver` with React Hook Form.

**Routing**: TanStack Router file-based routes under `src/routes/`. Loaders pre-fetch via `queryClient.ensureQueryData`.

**Imports**: always `@/` alias (resolves to `src/`). Never relative `../../` across feature boundaries.

**Styling**: Tailwind CSS v4 (CSS-first, no `tailwind.config.js`). `cn()` from `src/lib/utils.ts` for conditional class merging. Install shadcn components with `npx shadcn@latest add <component>` — never edit generated files in `src/components/ui/` unless they are broken (see below).

**shadcn / base-nova / @base-ui/react**: This project uses shadcn's "base-nova" style which uses `@base-ui/react` primitives (NOT Radix UI). Two known issues with generated components:
- `@base-ui/react/input`'s `Input` is actually `Field.Control` and requires a `Field.Root` context — it renders broken standalone. The generated `input.tsx` has been replaced with a plain `<input>` wrapped in `React.forwardRef`.
- Any shadcn `Input`-like component **must use `React.forwardRef`** so React Hook Form's `register` ref attaches to the DOM element. Without it, RHF cannot read field values and Zod returns "Required" for every field on submit.

## Code Graph (graphify)

A **developer tool**, unrelated to `apps/knowledge_graph/` despite the similar name:
`knowledge_graph` is this product's LLM concept graph; graphify indexes **our own source code**
by deterministic tree-sitter AST parsing. They share no code, models, or data.

```bash
graphify extract . --code-only     # full rebuild (AST only - no LLM, no API key, no tokens)
graphify update .                  # cheap incremental rebuild (~6 s)
graphify affected "chat_many"      # what breaks if this changes - the highest-value query
graphify explain "run_tool"        # call sites with file:line and EXTRACTED/INFERRED tags
graphify god-nodes --top 10        # architectural hubs by degree
```

**Backend only. Do not trust it on the frontend.** Graphify does not resolve `tsconfig.json`
path aliases, and this codebase mandates `@/` imports (467 on disk vs 30 relative), so the
TypeScript call graph is essentially absent: **0.26 real edges per node and 73% of TS nodes
isolated, against 1.85 and 24% for Python**. 76% of TS edges are just `contains`. A frontend
answer from graphify is not evidence - use grep. There are also ~2 cross-language edges total,
so it can never answer "which endpoint does this page call".

- Output lands in **`graphify-out/`** (gitignored, ~5.5 MB). A **post-commit git hook**
  (`graphify hook install`, local to `.git/hooks/`) rebuilds it on every commit.
- `--code-only` is deliberate: the doc/PDF/image pass sends file contents to an LLM. Keep it
  off unless you have reviewed what is in the corpus.
- Respects `.gitignore`, so `.venv/` and `node_modules/` stay out (413 indexed files, not 20k).
- Served to the SPA by `apps/codegraph` at `/api/codegraph/graph/` and
  `/api/codegraph/nodes/<id>/`, rendered at **`/code-graph`**. The frontend half of that page
  is a sparse dot cloud for the reason above - filter to `layer=backend` for a readable graph.
- **Access from Claude Code**: the Bash CLI always works and costs nothing. The `/graphify`
  skill and the MCP server (`claude mcp add graphify -- graphify-mcp`, needs
  `uv tool install "graphifyy[mcp]"`) both register only at **startup**. The MCP surface costs
  ~1,500 tokens per session and has **no `affected` tool** - its `get_neighbors` is depth-1 -
  so the best query still goes through Bash. It does add PR blast-radius tools
  (`list_prs` / `get_pr_impact` / `triage_prs`) that have no CLI equivalent.
- **Not built in CI or on deploy** - `deploy.sh` has no graphify step, so prod always shows the
  page's empty state. That is intended.

## Load Testing (k6)

Issue #12; full doc `docs/project_docs/load-testing.md`. `loadtest/k6/` holds plain-JS k6
scripts: `lib/` (config, auth, endpoints, checks, profiles, summary) + `scenarios/browse.js`
(one iteration = one weighted page view of an analyst's session). `just lt` remote-writes to
the Prometheus on `.208` (`-o experimental-prometheus-rw`), shown on dashboard `sm-loadtest`
beside the Django/worker/Postgres/Redis panels, and writes `loadtest/results/<testid>.json`.

- **Read-only only.** No `/api/llm/` (GPU-bound), `/sync/` or `/yf/` (Yahoo rate limit), or
  writes. `/api/health/` is called ONCE in `setup()` (it runs a Celery broadcast ping + an
  Ollama probe per call) and lives only in `lib/preflight.js`. `test_loadtest_contract.py`
  enforces all of this, and that every path RESOLVES in Django (a renamed endpoint would
  otherwise be a run of fast 404s passing a latency-only threshold).
- **Cardinality**: `url`/`vu`/`iter` are dropped from k6's `systemTags` and every request
  carries a templated `name` tag (`/api/companies/{id}/prices/`) that is also its path in
  `lib/endpoints.js`. A test fails any dashboard query using those labels.
- **Open model**: every profile but smoke is `ramping-arrival-rate` - a closed model slows
  its arrival rate as the server slows, hiding the knee. Rates are page views/s
  (`LOADTEST_RATE`). Every threshold is `abortOnFail`.
- **Prod guard is in the script** (`lib/config.js` throws in init context, by target name
  AND by prod host), not just the justfile, so a hand-typed `k6 run` is covered too.
- **Auth**: dj-rest-auth's `JWT_AUTH_HTTPONLY=True` puts the refresh token ONLY in the
  `refresh-token` cookie (body `refresh` is ""), so setup() reads it from the cookie; each VU
  refreshes its access token after 10 min (tokens last 15). `auth_refreshes` counts it.
- **`k6 inspect` ignores the system environment** (`k6 run` does not) - pass `-e`. An
  exported `LOADTEST_PROFILE` is silently ignored, which made the first `lt-inspect` check
  smoke five times.
- k6 trend stats (`_p95` etc.) are cumulative over the RUN, not windowed - read the knee off
  the windowed Django histogram. `k6_*` series exist only during/after a run and are
  declared by exact name in `verify_dashboards.py`'s `EXPECTED_MISSING`.
- Every dashboard carries a **"Load test" annotation** from `max by (testid) (k6_vus)` -
  no Grafana credential on the generator, and an aborted run is still marked.
- `manage.py ensure_loadtest_user` (LOADTEST_EMAIL/PASSWORD) refuses a staff account and any
  address whose local part does not start with `loadtest`, so it can never reset a real
  user's password.

## Browser Agent Deployment

`deploy.sh` deliberately has **no Chromium step** - a ~500 MB download on every deploy, for a
feature that ships off, is not worth it. Instead the provision role installs it, gated behind
`browser_agent_enabled` in `infra/ansible/group_vars/prod.yml` (default `false`):

```bash
just be-browser-setup             # local: apt shared libraries (sudo) + the Chromium binary
# prod: set browser_agent_enabled: true, re-run the provision role, then flip
#       browser_enabled on in LLM Settings (or BROWSER_ENABLED before the row exists)
```

**Never `playwright install --with-deps`**: it does two halves, an apt install needing root and a
binary download that does not, and when it cannot elevate it skips the apt half **silently** while
still reporting success. The result is a complete-looking `~/.cache/ms-playwright` whose chrome
dies at launch with `libnspr4.so: cannot open shared object file`. `just be-browser-setup` resolves
the package list as the calling user (`uvx` lives in `~/.local/bin`, which is NOT on sudo's
`secure_path`, so a bare `sudo uvx ...` is "command not found") and elevates only `apt-get`. The
Ansible provision role does the same split, and then VERIFIES by running `chrome --version` as the
app user, so a dep-less install fails at provision time instead of inside the first request.

The Ollama host is NOT in Ansible's inventory (only app `.200` and db `.201`), so the vision model
is pulled by hand: `ollama pull qwen3-vl:8b`.

Prod needs `ANTHROPIC_API_KEY` in the Ansible vault only if the provider is switched to Anthropic;
the default provider is Ollama. Until Chromium and `browser_enabled` are both done, `/browse`
renders its disabled empty state - the intended out-of-the-box state.

## AI Company Summary

`services.generate_company_summary(symbol)` -> a `CompanySummary` row. **ONE blocking LLM call**,
fire-and-forget through Celery (`tasks.generate_summary_single`, retries only on
`OllamaServiceError`); `tasks.tick_summary_generation` batches the stalest companies. Endpoints:
`GET/POST /api/companies/{symbol}/summaries/[latest/|generate/]`. Rewritten by
[issue #3](https://github.com/bthek1/Market_Analyzer/issues/3); the before/after record is
`docs/project_docs/ai-summary-pipeline.md`. It is deliberately NOT an `AgentRun` - a fixed
single-ticker report needs no run/step persistence, and `data_snapshot` already carries the inputs.

**UNIT CONVENTION (the bug that motivated the rewrite).** Every ratio on `CompanySnapshot` is a
**FRACTION** (0.0034 = 0.34%). yfinance is inconsistent: `profitMargins`/`returnOnEquity` arrive as
fractions, but `dividendYield`, `fiveYearAvgDividendYield` and `debtToEquity` arrive in **percent**,
so those three are divided by 100 **at ingestion** (`YFinanceClient.get_snapshot`, and the
raw-backfill path in `services.backfill_snapshot_fields`). Migration
`companies/0012_backfill_percent_to_fraction` rescales pre-existing rows (reversible). The one
deliberate exception is `EarningsDate.surprise_pct`, which stays in **percent** because the earnings
chart reads it directly - it renders through `_fmt_already_pct`, never `_fmt(pct=True)`. Before the
fix the model was told KO yielded 244% and AAPL carried 78x leverage, and it believed it (it
invented a special dividend to explain JPM's "171% yield"). `test_summary_inputs.py::
TestPromptUnitRegressions` pins the corrected strings. The AGENT tools use the opposite
representation since issue #11 (percent, `*_pct` names), converted at the tool boundary. So the
shared `aggregate_snapshots` stays in FRACTIONS for this pipeline, and it must not be converted there.

**Data flow**: `_assemble_company_data` stores raw **NUMBERS** (never pre-formatted strings) so
`data_snapshot` can be diffed and recomputed; `_build_prompt_text` is the only formatter, driven by
`_SECTION_SPECS` `(key, label, kind)` tuples with `kind` in money/num/pct/pct_raw/int/str. Inputs:
latest `PriceBar` close + position in the 52-week range + 50/200-day averages + 52w change vs the
S&P; **implied upside** vs `target_mean_price` computed in Python (`None`, never 0, when either side
is missing); a **peer benchmark** (company value beside the peer median for P/E, P/B, margins, ROE,
D/E) from `llm_analysis.tools.aggregate_snapshots` - public precisely so the peer maths has one
home - over the company's industry, falling back to the sector below 3 peers (the company is always
excluded from its own median) and omitted when neither group has peers with snapshots. Since issue
#9, NEGATIVE P/E and P/B peers (`tools.VALUATION_RATIOS`) are excluded from the median and counted as
`peer_negative`, and a company whose OWN P/E or P/B is negative is rendered "no meaningful peer
comparison" instead of beside a median - ROE, margins and D/E keep their negatives; the last 4
reported quarters + beat count; TTM dividends + EPS coverage; short-interest month-over-month; and
the valuation/profitability/growth/leverage snapshot fields.

**Structured verdict**: the call passes `_SUMMARY_FORMAT` as Ollama's `format` schema and
`_parse_summary_response` parses `{verdict, confidence, summary, key_drivers, key_risks}` tolerantly
via `llm_analysis._json.parse_json_object`. There is no `VERDICT:` line and no regex any more.
Non-JSON, a missing verdict or an out-of-choices verdict all degrade to `insufficient_data` without
raising; `confidence` is clamped into 0-1 or nulled, never persisted raw. The system prompt carries
explicit **sell criteria** (peer-relative valuation, margin compression, coverage below 1.5x,
deteriorating balance sheet, negative implied upside), requires every claim to cite a supplied
number, and forbids inventing a cause for an implausible value.

**Freshness gate**: `_stale_sync_reasons` checks `CompanySyncRecord` for `snapshot`/`price`/
`financials` against windows on the `LLMSettings` singleton (`summary_snapshot_max_age_days` 7,
`summary_price_max_age_days` 3, `summary_financials_max_age_days` 120, seeded from the
`SUMMARY_*_MAX_AGE_DAYS` env vars, exposed on `/api/llm/settings/` as `required=False` so an old
full PUT still validates). Stale **or never synced** -> an `insufficient_data` row naming the reason,
with **zero LLM calls**; the reasons also land in `data_snapshot["stale_data"]`.

`CompanySummarySerializer` additively exposes `confidence`, `key_risks`, `key_drivers` and
`data_snapshot`. The frontend `AiSummaryTab` renders the confidence beside the verdict chip, the
drivers/risks lists, an explicit stale-data panel and a collapsible "Data used" panel; the new fields
are optional in `types/companies.ts`, so pre-rewrite rows still render. Known follow-ups: the
60% buy / 1% sell skew has not been re-measured since (3-way voting on the verdict field is the next
increment if it survives), and `CompanySummary` still uses an auto-increment PK.

## RAG / Embeddings

> Status: the `embeddings` app is **planned, not yet built**. The points below are the
> intended design (see `.github/pgvector-rag-database-setup.instructions.md`).

- pgvector with HNSW index (`vector_cosine_ops`) on the `Chunk.embedding` field
- Embedding model: Ollama `nomic-embed-text` (768-dim), served by the same Ollama instance as the chat/LLM models. All embeddings go through Ollama's REST `/api/embed` endpoint — there is no local sentence-transformers / HuggingFace model. Configure via `OLLAMA_EMBED_MODEL` (default `nomic-embed-text`)
- `VectorField(dimensions=768)` must match the model output. Cosine distance (`vector_cosine_ops`) normalizes internally, so no manual vector normalization is required
- Use `bulk_create` for chunk insertion — never loop with `.save()`
- Migration order: `0001_enable_pgvector` (CREATE EXTENSION) → `0002_initial` → HNSW index migration

## Ollama / LLM

- `apps/llm_analysis/services.py` wraps the Ollama REST API (`chat` blocking, `chat_stream` SSE, `chat_many` concurrent fan-out, `embed` via `/api/embed`; `summarise`/`list_models` helpers). `chat`/`chat_stream` default to `think=False` (disables qwen3 thinking). `chat` takes an optional `temperature`; `chat_many` takes optional per-batch `temperatures` (used by voting) — omitting them leaves behaviour unchanged
- **Agent-run durability across refresh**: every workflow POST view wraps its SSE generator in `services.stream_in_background(gen, run)`, which drives the generator from a **daemon thread** bridged to the live client via an unbounded queue. The workflow drains to completion (persisting every step + terminal run status to the DB) even when the client disconnects — so a page refresh no longer orphans a run at `status="running"`. The frontend Agents page persists its workspace (mode, selected workflows, query, per-type run id) to `localStorage` (`agentsSession.ts`) and on reload restores it and **polls the detail endpoints** (reusing each hook's `loadFromDetail`) for any still-`running` run until it reaches a terminal status. Because the worker uses its own thread-local DB connection, the `*_view_streams_sse` view tests run under `@pytest.mark.django_db(transaction=True)` so the committed run row is visible across threads
- **Stopping a run**: `POST /api/llm/runs/stop/` (`StopRunView`, body `{type, id}` where `type` is the registry SLUG, not the kind - `evaluate`/`plan`/`orchestrate`/`chat-agent`) cooperatively cancels a workflow by flipping the run's DB `status` to `stopped` via `services.request_run_stop` (only affects a `running` row owned by the requester). `stream_in_background`'s worker polls the run status between events and, on `stopped`, closes the generator at the next step boundary (`GeneratorExit` is a `BaseException`, so it unwinds cleanly through the per-step `except Exception` guards), forces the terminal status to `stopped`, and ends the stream. Going through the DB (not an in-process flag) means the cancel works across processes/workers. `stopped` is written verbatim — it is intentionally NOT in the model `Status` choices, so there is no migration (the column has no DB-level constraint). Frontend: the Agents page shows a **Stop** button per running panel, a global Stop next to Run, and a Stop action on running history rows; stopping resets the live stream and reconnect-polls the detail until it settles on `stopped`. The history sidebar is **docked on the left and open by default**. `STOPPABLE_RUN_MODELS` is the allow-list behind the endpoint and is now pinned by a test DERIVED from `registry.WORKFLOWS` - it was a hand-written literal nothing checked, and `chat` shipped missing from it, which makes a workflow silently UNSTOPPABLE: the button posts, gets `Invalid run type or id`, and the run carries on
- Per-role models: classification runs on `OLLAMA_CLASSIFIER_MODEL` (cheap/fast), synthesis/analysis/format on `OLLAMA_MAIN_MODEL` (`OLLAMA_MODEL` is the back-compat default). A per-run `model` override selects the MAIN model only; classification always uses the classifier model
- **Run persistence is TWO unified, typed, polymorphic models** (not one pair per workflow): `AgentRun` discriminated by `kind` (`chain`/`route`/`parallel`/`react`/`eval_opt`/`plan_exec`/`orchestrator`/`multiagent`/`dag`/`autonomous`/`browser`/`chat`) + its child `AgentStep` (related name `steps`). All ten workflows create via `services.create_agent_run(user, query, model, kind, **fields)` (the per-workflow `create_*_run` helpers are thin wrappers) and query via `AgentRun.objects.filter(kind=..., user=...)`. The per-workflow `*_id` columns collapse into `AgentStep.key`; the per-cycle `index` is `AgentStep.order`; route's old `chain_run` OneToOne is now `AgentRun.parent` (self-FK to the spawned chain run). **The frontend/API contract is preserved by per-kind DRF serializers** that rename via `source=` (`step_id`/`task_id`/`worker_id`/`node_id`/`agent_id` <- `key`; `iterations`/`tasks`/`workers`/`nodes`/`cycles` <- `steps`; `index` <- `order`; `chain_run` <- `parent`), and the SSE **step** payloads come from those same serializers via `_events.step_event` (see "Agent runtime" below) - one serialisation, not two. The per-workflow "persists `XRun`/`XStep`" notes below mean `AgentRun(kind=...)` + `AgentStep`. `StopRunView` passes `AgentRun` to `request_run_stop` for every consolidated kind. Tests filter by `kind`; `LLMSettings` is the only other model. Schema history: migrations `0013` (additive create) -> `0014`-`0023` (one id-preserving data migration per workflow) -> `0024` (FK-safe `DeleteModel` of the 19 legacy tables)
- **Agent runtime: `_events.py` is the shared SSE + terminal-run layer** (issue #6 phases 1-2).
  Every workflow used to define its own `_sse` and `_finish` - nine byte-identical copies of
  each, and they HAD drifted (`react` framed without `default=str`). Now: `sse(payload)` is the
  only place that knows the wire format; `event(name, **fields)` frames a named event;
  `succeed(run, output, *, meta, **fields)` and `fail(run, error, *, output, meta, **fields)` are
  GENERATORS (`yield from fail(run, str(exc))`) that do the `store.finish_run` write and the
  terminal event together, so the row and the stream can never disagree about how a run ended.
  `meta` (persisted, validated by `store`) and `**fields` (streamed) are separate arguments
  because several workflows persist a value without streaming it. **`step_event(step, name,
  kind=...)` is the one that matters most**: the payload IS
  `serializers.step_serializer_for(kind)(step).data`, so the live stream and the detail endpoint
  are ONE serialisation of the row. They used to be written independently and SEVEN OF TEN
  diverged - `dag` streamed `id`/`args` while its detail endpoint returned `node_id`/`tool_args`,
  and since every hook's `loadFromDetail` assigns `detail.steps` straight into state, the tool
  arguments silently vanished from the UI on a refresh-restore. Consequences worth knowing: an
  absent value now reads `""` (the serializer default) rather than `null` on BOTH paths - two UI
  sites tested `observation !== null` and rendered an empty block after a reload; and `dag`'s
  `id` changed MEANING, from the graph node key to the `AgentStep` row UUID, with the key in
  `node_id` (TypeScript could not see that - both are `string`). `chain.py` cannot use `step_event` - its payload carries no
  `event` discriminator at all (the frontend keys off `step_id`) - so it frames its own line from
  `_events.step_payload(step, kind="chain")`, the same serialisation as a dict. That is NOT an
  exemption: chain's old hand-built payload omitted `id`, `order` and both timestamps, and since
  `usePromptChain` merges each event into a client-side template, the chain card's duration label
  (computed from `started_at`/`completed_at`) appeared only after a reload. Its two run-level
  SIGNALS (`__init__` / `__done__`) correspond to no row and stay hand-built, via `_signal()`. Guarded by structural tests derived from
  `AgentRun.Kind` - no module may define `_sse`/`_finish`, hand-roll a `data: ` line, call
  `store.finish_run` directly, hand-build a step payload, or stream a bare `args` - plus a
  per-kind backend parity test (`step_event == serializer.data`) and a frontend test that a run
  driven by SSE and the same run loaded via `loadFromDetail` produce EQUAL state, for all TEN
  workflows (every one mutation-checked against the shape it exists to catch). A related defect
  fixed alongside (issue #7): `react` persisted a step for an unparseable model turn but streamed
  no event for it, so the live list was one card SHORTER than the restored one - hence the length
  assertion in that test. **`_runtime.py` is the shared LOOP** (phase 3): `drive(run, strategy)` owns the
  budget, the `step_span`, error isolation ON EVERY HOOK, `store.create_step`, the emission and the
  terminal status; a `Strategy` contributes only policy (`intro`/`next`/`perform`/`after`/`result`/
  `failure`). `intro` and `result` are GENERATORS - they emit events of their own, and `result`
  returns its `Outcome` via `return`, which `yield from` hands back. Persist-and-emit are two
  adjacent lines in the driver, which is what makes issue #7's class (a step written but never
  streamed) impossible. Only `OllamaServiceError` and `AbortedError` become a terminal error event -
  anything else propagates, because a genuine bug must not be reported as a failed LLM call. It does
  NOT own stop-checking: `stream_in_background` already does that at event boundaries.
  `StepSpec.order` is stamped BY THE DRIVER, so a strategy never infers its own position from
  accumulated state - plan_execute indexes into a plan that a replan rewrites mid-loop, and an
  inferred index is one bug away from reading the wrong step.
  `react`/`eval_opt`/`plan_exec` are driven; `chain` is EXEMPT (no `event` discriminator, and it
  signals completion with a step-shaped `__done__` rather than a `result` event, so the driver's
  terminal path does not apply) and so is `router` (persists no steps). `drive_waves(run, strategy, model)` is the FAN-OUT driver (phase 4):
  waves in order, steps within a wave concurrently via ONE `chat_many`. `orchestrator` (single
  wave), `dag` (one wave per topological layer) and `parallel` (one wave, sectioning or voting)
  are driven by it. Its per-step spans stay REPLAYED rather than wrapped, and that is INHERENT,
  not a shortcut: one `chat_many` covers every step in the wave, so no per-step span can contain
  the call that produced it. What it can wrap is the WAVE - hence `agent.wave` (carrying
  `agent.wave`/`agent.wave_size`), under which `ollama.chat_many` nests. NB `span()` takes
  `**attributes` and these keys contain dots, so they must be `**`-unpacked from a dict, never
  passed positionally. `temperatures` is omitted rather than passed as None when a workflow does
  not spread them (only parallel's voting does) - passing it unconditionally changes the call
  every other workflow makes. `multiagent` and `autonomous` are driven by the SEQUENTIAL
  `drive` (neither uses `chat_many`), so they DO get real wrapper spans. Both need
  `Strategy.pre_step(spec)`, which persists the row already RUNNING before the work so a mid-run
  refresh shows the stage in flight; the driver then UPDATES that row instead of creating one, and
  passes `store.update_step(..., replay_span=False)` because it already holds an open `agent.step`
  span - without that flag every pre-persisted step would emit TWO spans. `BaseStrategy` supplies
  the no-op `pre_step`/`after`/`failure` so a strategy writes only the hooks it needs. Eleven of
  the twelve workflows are now driven; only `chain` and `router` are exempt, and a structural test
  asserts exactly that - a twelfth workflow arriving with its own hand-rolled loop fails rather
  than quietly re-growing the duplication this issue removed. NB phase 3 ADDED ~200 lines rather than removing them - the
  Strategy boilerplate exceeds the mechanism it replaces; the win is that the mechanism exists once,
  not that it is smaller. The step-span structural guard therefore has THREE mechanisms now
  (`step_span` wrapper / replayed `record_completed_step` / `drive`), with a test that the driver
  really opens the span so the third does not silently excuse a workflow.
- `router.py` resolves each query to `simple` / `analysis` / `comparison` / `deep_research`. Route selection is LLM-classifier (`OLLAMA_ROUTE_MODE=llm`, default) or semantic embedding (`OLLAMA_ROUTE_MODE=semantic`, 0 LLM calls above `OLLAMA_ROUTE_THRESHOLD`, falls back to LLM otherwise); `route_method`/`route_confidence` persisted on the `AgentRun(kind="route")` row. `analysis` fans out 3 concurrent aspect calls (valuation/profitability/risk) then aggregates; `comparison` fans out per-ticker narration then synthesises. `chain.py` runs prompt-chaining workflows. Runs persist as `AgentRun(kind="route")` and `AgentRun(kind="chain")` + `AgentStep` (route's `parent` self-FK links to the chain run it spawns)
- `parallel.py` is the **observable** Parallelization agent (`POST /api/llm/parallel/`, history at `/api/llm/parallel/history/` + `/<uuid>/`). Two user-selected strategies (no classifier): *sectioning* reuses the route's `ANALYSIS_ASPECTS` via shared `section_batches()`/`aggregate_sections()` helpers; *voting* runs N (2-5) buy/hold/sell verdicts with spread `VOTING_TEMPS`, tallies the majority (ties -> `hold`), then writes a consensus rationale. Unlike the `analysis`/`comparison` routes (fan-out invisible, single `result` event), `parallel` streams a per-sub-call `task` SSE event and persists `AgentRun(kind="parallel")` + `AgentStep` (task_id in `key`). Sectioning logic lives in exactly one place, shared with `router._run_analysis`
- `react.py` is the **ReAct** agent (`POST /api/llm/react/`, history at `/api/llm/react/history/` + `/<uuid>/`) - the first *true agent* where the LLM (not our code) picks the next tool each turn. A bounded loop (`run.max_steps`, default `OLLAMA_REACT_MAX_STEPS=6`) asks the MAIN model for ONE JSON object per turn (action `{thought,tool,args}` or answer `{thought,answer}`; tolerant `parse_react_output`); exhausting the budget forces one final-answer call, unparseable output is nudged and retried within the cap. Tools live in `tools.py` (per-company: `company_profile`/`company_snapshot`/`peer_comparison`/`company_financials`/`recent_price`; sector/industry: `list_sectors` for name discovery, `sector_analysis`/`industry_analysis` report the DISTRIBUTION - `{median, p25, p75, min, max, n}` and deliberately NO mean (issue #9: every aggregated field is a ratio, and a ratio's mean is owned by its outliers) - of the valuation metrics + largest constituents across a peer group via a portable latest-snapshot-per-company subquery, plus a `how_to_read` legend naming the median as the typical value (LAST key, so chat's 600-char carry-forward keeps the numbers). For `VALUATION_RATIOS` (trailing/forward P/E, P/B ONLY) negatives are EXCLUDED and counted as `negative` - losses/negative equity are not a low valuation; ROE/margins/D/E keep theirs, pinned by a test. UNITS (issue #11): `PERCENT_FIELDS` (ROE, profit margins, dividend yield) leave every LLM-facing observation IN PERCENT under `*_pct` names (`return_on_equity_pct: 23.26`) - via `chain.snapshot_metrics` for the snapshot and `_agent_units` at the tool boundary for the aggregates; handed bare fractions, the model scaled some and not others in one answer (ROE min -2.4003 -> "-2.40%"). The NAME is the unit label because it survives the 600-char carry-forward truncation; the value stays a number. `aggregate_snapshots` itself still returns FRACTIONS - it is also the AI summary's benchmark, whose formatter renders its own percents. D/E stays a multiple. `peer_comparison(symbol, scope?)` (issue #13) is the COMPUTED company-vs-peers tool: per metric the company value, the peer median, `vs_median` ("18% below"), a `band` (quartile in words) and a `reading` for EVERY metric in its own vocabulary (`METRIC_READINGS`: only P/E and P/B say cheap/expensive; ROE and margins say "more profitable ... (not a price measure)"; a test pins that only valuation ratios speak of price) - because with both numbers correct the model still wrote "28.49 is above 34.30" in 9/10 runs, and when only P/E and P/B had a reading it called high margins "more expensive" in 4/10. Pure `compare_metric` does the maths; valuation ratios come first so chat's 600-char carry keeps them; a negative P/E or P/B gets no comparison; a gap under 1% reads "under 1% below", never the self-contradicting "0% below" (cut at `< 1` because `format()` rounds half to even). Its group choice is `tools.peer_group` (industry, else sector below `MIN_PEERS=3`; the company always EXCLUDED from its own median), which `companies.services._peer_group` now delegates to - one home, like `aggregate_snapshots`. Their shared `aggregate_snapshots` helper is public because `companies.services` reuses it for the AI summary's peer benchmark, which therefore also excludes negative-P/E/P/B peers (`peer_negative`) and gives a company whose OWN P/E or P/B is negative "no meaningful peer comparison" rather than a median. `tool_catalogue()` appends `GROUNDING_RULE` (no number, RANKING, comparison or superlative about data not returned) to every non-empty catalogue, so every agent shown tools gets it once - `test_grounding_rule.py` DERIVES (by AST) every module calling `tool_catalogue` and fails if one has no prompt checked for the rule, or carries it twice; the observation's size is pinned under `TURN_RESERVE // 2` by `TestSectorObservationBudget`) and are **read-only DB lookups** that never raise (bad symbol/args -> `{"error"}` observation); query logic is shared with `chain._research_company` via `chain.snapshot_metrics`/`chain.annual_financials`. Strictly sequential (no `chat_many`); each turn streams a `step` SSE event and persists `AgentRun(kind="react")` + `AgentStep`
- `eval_opt.py` is the **Evaluator-Optimizer** (Reflection) agent (`POST /api/llm/evaluate/`, history at `/api/llm/evaluate/history/` + `/<uuid>/`). Three MAIN-model roles drive a quality-gated loop: *generate* a draft, *evaluate* it (returns ONE JSON `{score 0-10, feedback, pass}` against a fixed rubric, tolerant parse via the shared `_json.parse_json_object` helper that also backs `react.parse_react_output`), *revise* with the feedback. Loop stops when `score >= run.threshold` (default `OLLAMA_EVAL_THRESHOLD=8`) or `pass`, else after `run.max_iterations` (default `OLLAMA_EVAL_MAX_ITERATIONS=3`), returning the **best-scoring** draft (not necessarily the last). Unparseable verdicts -> score 0 (loop keeps refining, never crashes). Strictly sequential (no `chat_many`); streams an initial `draft` event then a per-iteration `iteration` SSE event, persists `AgentRun(kind="eval_opt")` + `AgentStep` (iterations serialized from `steps`)
- `plan_execute.py` is the **Plan-and-Execute** agent (`POST /api/llm/plan/`, history at `/api/llm/plan/history/` + `/<uuid>/`). Four MAIN-model roles: *plan* returns ONE JSON `{"plan": [{task, tool, args}, ...]}` capped at `run.max_steps` (default `OLLAMA_PLAN_MAX_STEPS=6`, tool catalogue embedded so the planner picks valid tools or `null`; tolerant `parse_plan` via shared `_json.parse_json_object`, also accepts a bare list); *execute* runs each step's planner-chosen tool via the **same read-only `tools.run_tool` as ReAct** then interprets it; *replan* (only when `run.allow_replan` and a step's tool obs is an `{"error"}` - the divergence signal) revises the remaining steps, hard-capped by `OLLAMA_PLAN_MAX_REPLANS` (default 2); *synthesise* folds step results into the answer. Unlike ReAct the plan is committed upfront (one planning call). Strictly sequential (no `chat_many`); streams `plan` -> per-step `step` -> optional `replan` -> `result`, persists `AgentRun(kind="plan_exec")` + `AgentStep`
- `orchestrator.py` is the **Orchestrator-Workers** agent (`POST /api/llm/orchestrate/`, history at `/api/llm/orchestrate/history/` + `/<uuid>/`). Three MAIN-model roles: *orchestrate* returns ONE JSON `{"subtasks": [{task, focus, tool, args}, ...]}` capped at `run.max_workers` (default `OLLAMA_ORCH_MAX_WORKERS=4`, tool catalogue embedded; tolerant `parse_subtasks` via shared `_json.parse_json_object`, also accepts a bare list, derives a missing focus, `tool` null -> pure-reasoning); *worker* runs each subtask's planner-chosen tool synchronously via the **same read-only `tools.run_tool` as ReAct/plan-execute** then the worker calls fan out **concurrently** via `services.chat_many` (bounded by `OLLAMA_NUM_PARALLEL`, per-call error isolation); *synthesise* folds worker outputs into the answer (reuses `parallel`'s aggregation prompt). Unlike `parallel`/sectioning (fixed `ANALYSIS_ASPECTS` chosen by our code) the subtasks are **invented at runtime per query**; unlike plan-execute the subtasks are **independent and run in parallel** (the independence assumption is load-bearing - dependent work is plan-execute's job). Worker rows are created **after** the decomposition (not pre-seeded by `create_orchestrator_run`); one failing worker never drops the others, all-fail finishes the run with an error. Streams `started` -> `plan` (dynamic subtask list) -> per-subtask `worker` -> `result`, persists `AgentRun(kind="orchestrator")` + `AgentStep` (worker_id in `key`)
- `multiagent.py` is the **Multi-Agent (Sequential/Hierarchical)** agent (`POST /api/llm/multiagent/`, history at `/api/llm/multiagent/history/` + `/<uuid>/`). A supervisor (two MAIN-model roles) routes a fixed, role-specialised roster and synthesises: *route* returns ONE JSON `{"agents": [...], "reason"}` - an ordered **subset** of the fixed `ROSTER` (tolerant `parse_route` via shared `_json.parse_json_object`, keeps known ids in roster order, dedupes, always force-includes `writer`, falls back to the full roster); the supervisor can only subset, never invent agents. The roster is a declarative `SubAgent` registry, each with its **own system prompt + own allow-listed tool subset**: *Researcher* (all read-only data tools - `TestResearcherAllowList` derives this from `tools.TOOLS`, so a new tool left out of the literal fails), *Analyst* (none), *Writer* (none). Sub-agents run as a strictly **sequential hand-off pipeline** (no `chat_many`) - each stage's output is the next stage's only input plus the query (**isolated context**, unlike ReAct's shared scratchpad). The *Researcher* is plan-then-fetch (one tool-selection call -> `tools.run_tool` x K capped at `run.max_tools` (default `OLLAMA_MULTIAGENT_MAX_TOOLS=4`) and filtered to its allow-list via `parse_tool_plan` -> one findings call); *Analyst*/*Writer* are single reasoning calls. *synthesise* folds the stage outputs into the answer (reuses `orchestrator`'s aggregation prompt). Unlike `chain` (plain prompts, no tools) each stage is a specialised agent; unlike `orchestrator-workers` (homogeneous, dynamic, parallel) the roster is fixed, role-specialised, sequential; unlike plan-execute (one generic executor, all tools) tool access is allow-listed per agent. A failing stage degrades the handoff but never aborts the run; all-fail finishes with an error. Step rows created **after** routing (not pre-seeded by `create_multiagent_run`). Streams `route` -> per-stage `step` (input + tool_calls + output) -> `result`, persists `AgentRun(kind="multiagent")` + `AgentStep` (agent_id in `key`)
- `dag.py` is the **Multi-Agent (Parallel/DAG)** agent (`POST /api/llm/dag/`, history at `/api/llm/dag/history/` + `/<uuid>/`). An orchestrator (two MAIN-model roles) dynamically decomposes the query into a **dependency graph** and synthesises: *decompose* returns ONE JSON `{"nodes": [{"id", "task", "focus", "tool", "args", "depends_on": [...]}]}` capped at `run.max_nodes` (default `OLLAMA_DAG_MAX_NODES=6`, tool catalogue embedded). `parse_nodes` (tolerant via shared `_json.parse_json_object`, also accepts a bare list) does **graph hygiene**: assigns missing ids, prunes edges to unknown ids / self-loops, and **breaks cycles** (drops the DFS back-edge) so the result is always a valid DAG. `topological_waves` (the only new primitive - pure code, no LLM) layers the graph Kahn-style; nodes within a wave are independent and fan out **concurrently** via `services.chat_many` (bounded by `OLLAMA_NUM_PARALLEL`, per-call error isolation), waves run **in order**, and each downstream node's prompt is injected with its upstream nodes' outputs. *synthesise* folds the **terminal (sink)** node outputs into the answer (reuses `orchestrator`'s aggregation prompt). Unlike `orchestrator-workers` (subtasks independent by contract, single wave) nodes carry `depends_on` edges so the graph runs in waves and dependents consume upstream outputs - orchestrator-workers is the single-wave special case; unlike `plan-execute` (strictly sequential) independent branches parallelise; unlike `multiagent` (fixed, role-specialised, width-1) the graph is dynamic and arbitrary-width. Node rows created **after** decomposition (not pre-seeded by `create_dag_run`). A failing node keeps a placeholder output so dependents still get input; all-fail finishes with an error. Streams `plan` (graph + waves) -> per-wave `wave` -> per-node `node` -> `result`, persists `AgentRun(kind="dag")` + `AgentStep` (node_id in `key`, plus `depends_on`/`wave`)
- `autonomous.py` is the **Autonomous / Long-Horizon (AutoGPT-style)** agent (`POST /api/llm/autonomous/`, history at `/api/llm/autonomous/history/` + `/<uuid>/`). The agent holds a long-term **goal** (the query), keeps a self-managed task **backlog**, and runs a **bounded controller loop**: *bootstrap* (one MAIN call) restates the goal + seeds the backlog (tolerant `parse_bootstrap`, falls back to the raw query); each *cycle* the controller returns ONE JSON `{reflection, goal_complete, next_task, backlog, action, tool, args, subagent_goal}` (tolerant `parse_controller` via shared `_json.parse_json_object`; unknown `action` -> `reason`) that REFLECTS on progress + the prior cycle's error, SELF-ASSIGNS the next task, rewrites the backlog, and picks an `action`: `tool` (run one read-only `tools.run_tool` then interpret it), `subagent` (delegate to a bounded **non-recursive** sub-agent - a small ReAct-style tool loop via `run_subagent`, capped at `OLLAMA_AUTO_SUBAGENT_STEPS=3`, gated by `run.max_subagents` (default `OLLAMA_AUTO_MAX_SUBAGENTS=3`); over-budget requests degrade to `tool`/`reason`), or `reason` (pure reasoning over working memory). Each cycle's output is folded into **working memory** injected into the next controller call. **Strictly sequential at the top level** (no `chat_many` - each cycle depends on the prior). The loop stops on `goal_complete`, on the cycle budget (`run.max_cycles`, default `OLLAMA_AUTO_MAX_CYCLES=8`), or on a **no-progress** detector (`OLLAMA_AUTO_NO_PROGRESS=2` consecutive cycles add nothing); every termination path ends with a *synthesise* call (reuses `orchestrator`'s aggregation prompt) so a run is never blank (`stop_reason` is `complete`/`budget`/`no_progress`/`error`). Reliability is hard-bounded throughout: hard cycle + sub-agent caps, no-progress detector, tolerant parsing, read-only tools that never raise, per-call error isolation (a failed cycle feeds its error into the next reflection but never aborts; only an all-failed run finishes with an error). Unlike `react` (single question, shared scratchpad, fixed tool menu, LLM ends when it can answer) the autonomous agent pursues a **goal** across cycles with a mutable backlog, can spawn sub-agents, and owns termination; unlike `plan-execute`/`orchestrator`/`dag` (decompose once) decomposition is **continuous and adaptive**. Cycle rows created **after** bootstrap (not pre-seeded by `create_autonomous_run`). Streams `goal` -> per-cycle `cycle` -> `result`, persists `AgentRun(kind="autonomous")` + `AgentStep` (cycle index in `order`)
- `browser.py` is the **Browser agent** (`POST /api/llm/browser/`, history at `/api/llm/browser/history/` + `/<uuid>/`, screenshots at `/<uuid>/screenshot/<order>/`) - the only agent that reaches the **public internet**. An LLM drives a real headless Chromium through **browser-use** (`uv add browser-use`; it launches Playwright's Chromium binary over CDP, auto-installing it on first run if absent). Same runtime shape as every other workflow (a sync SSE generator under `services.stream_in_background`), but browser-use is async: an inner thread runs `asyncio.run`, `register_new_step_callback` pushes each step onto a queue, and the generator thread does the DB writes and yields the SSE. `build_agent` is the ONLY function that touches browser-use's API and is the single seam the tests patch - **no test may launch a browser** (`browser_live` marker, excluded from `addopts` like `llm_live`). Bounds, all of them load-bearing: `browser_enabled` ships **off** (503 + `hint`, rendered as an empty state), a host allow-list on the `BrowserSession`, `run.max_steps`, a wall-clock deadline enforced through `register_should_stop_callback`, a process-wide `BoundedSemaphore(1)` (429 when busy - one Chromium is ~400 MB against the app container's 4 GB), a `ScopedRateThrottle` (`browser`, `BROWSER_THROTTLE_RATE=10/hour`), a fresh incognito profile per run (no cookies, no `sensitive_data`, no `available_file_paths`), and browser-use's telemetry + cloud sync forced off at import. Screenshots are written as **files** under `BROWSER_SCREENSHOT_ROOT` with only the relative key in `meta` (base64 in JSONB would be ~200 KB a step) and served by an owner-checked view - never static/media - with a daily Beat sweep (`tasks.py: sweep_browser_screenshots`) enforcing `BROWSER_SCREENSHOT_RETENTION_DAYS`. The driving LLM is **Ollama by default** (free, local, no API key - but small models are best-effort at browser-use's strict per-step action JSON), with **Anthropic** selectable per run for far more reliable tool-calling. It **MUST be a VISION model**: browser-use attaches a screenshot to every step, and a text-only model does not degrade, it returns `400 "Multimodal data provided, but model does not support multimodal requests"` on EVERY step, so the agent burns its whole budget without ever seeing a page. `BROWSER_MODEL` therefore defaults to **`qwen3-vl:8b`** (same family + Q4_K_M quantization as the `qwen3:8b` main model, ~0.9 GB larger on disk) rather than to blank, which would fall back to the text-only `OLLAMA_MAIN_MODEL`. It also needs a big CONTEXT WINDOW: Ollama defaults `num_ctx` to 4096, a browser-use step prompt (system prompt + serialised DOM + screenshot) measures ~15k tokens, and browser-use never sets `num_ctx` itself (`ChatOllama.ollama_options` is None) - at the default the model has no room to generate and returns an EMPTY string, which surfaces as `Invalid JSON: EOF while parsing a value at line 1 column 0`. `build_llm` therefore passes `ollama_options={'num_ctx': BROWSER_NUM_CTX}` (default 32768; costs KV-cache memory on the Ollama host). `provider_supports_vision` decides whether to send screenshots by asking Ollama's `/api/show` for the tag's `capabilities` (name-matching against `OLLAMA_VISION_MODELS` is the fallback when Ollama is unreachable - it cannot know that e.g. `mistral-small3.2` is multimodal). An explicit blank `browser_model` still means the provider's own default (`OLLAMA_MAIN_MODEL` / `claude-sonnet-5`); anthropic models are all multimodal. `stop_reason` is `complete`/`budget`/`timeout`/`error`; a run that produces no answer finishes as an error, never blank. Streams `started` -> per-action `step` -> `result` (with `sources`), persists `AgentRun(kind="browser")` + `AgentStep`. Rendered at **`/browse`**, a standalone page - *not* a mode on `/agents`. Live smoke test: `manage.py browse "<query>"`. **Prompt injection is the standing risk**: page content is untrusted input to an LLM that can click and type, which is what the allow-list and the credential-free profile are for
- `chat_agent.py` is the **Chat agent** (`POST /api/llm/chat-agent/`, history at
  `/api/llm/chat-agent/history/` + `/<uuid>/`) - conversational chat INSIDE the harness
  (issue #8; `docs/project_docs/chat-agent.md`). **A turn is a run**: `AgentRun.query` is the user
  message and `output` the assistant reply, so a conversation is just an ordered list of runs and
  there is no separate Message model; `AgentStep` rows under a turn are its TOOL CALLS. Driven by
  `_runtime.drive` with ReAct's loop shape, because the tool loop is exactly what makes
  `tools.run_tool` reachable from chat - the thing the legacy path could not do at all (it
  advertised no tools, so the model never knew they existed and invented figures that were sitting
  in our own DB). Three deliberate differences from `react`: the system prompt PERMITS ANSWERING
  IMMEDIATELY (most chat turns need no tool, and a research-shaped prompt makes the agent fetch a
  snapshot to say hello), the budget is per TURN and lower (`OLLAMA_CHAT_MAX_STEPS`, default 4 -
  interactive, so latency beats exhaustiveness), and `tools_used` accumulates on the run.
  **PREFETCH (issue #10):** a ticker the user names (`named_tickers`: capitalised or `$`-prefixed,
  must exist in `Company`, max `MAX_PREFETCH=2`, never the whole budget) gets a code-run
  `peer_comparison` step (issue #13; was `company_snapshot`, of which it is a superset) before the
  model is asked, scoped by `comparison_scope` to the group the user NAMED ("vs the sector" ->
  sector; NVDA is 18% below its sector's median P/E and 42% below its industry's) - `perform_streaming` returns None for it so
  the driver takes `perform`, and it persists, streams and carries forward like any tool call. The
  slug is **`chat-agent`, not `chat`**: `/api/llm/chat/` is the LEGACY non-harness endpoint and
  still serves `useSinglePrompt`, so the names could not collide (same class of irregularity as
  `eval_opt` -> `/evaluate/`, and recorded in `registry.py` for the same reason). **SESSIONS** (phase 2):
  `ChatSession` (title, `summary`/`summarised_upto`, archived, `-updated_at` ordering) +
  `AgentRun.session` (nullable, CASCADE, `related_name="turns"`) at
  `/api/llm/chat/sessions/`; `_rehydrate` replays prior turns oldest-first, a turn that
  errored without answering still contributes its USER message and a `stopped` turn its
  PARTIAL output (that is what the user saw). A second turn while one is running is **409** -
  two at once FORK the transcript. `turn` is derived inside `create_chat_run`, never passed.
  Titles come from `tasks.generate_chat_title` on the CLASSIFIER model, queued on the first
  turn from the first message alone and fire-and-forget (blank is a supported state) - note
  that with NO Celery worker running it executes inline and the first turn of every
  conversation pays for it. **COMPACTION** (phase 3): a chat SESSION is the first
  workload in this app to exceed the Scratchpad budget (~3,000 tokens at num_ctx=4096; every
  other prompt here peaks near 1,100), and Scratchpad CANNOT save it - its policy drops the
  oldest tool OBSERVATION and a transcript has none, so it would hit "nothing droppable left"
  and hand Ollama an oversized prompt to truncate silently. So the conversation is compacted:
  history gets `pad_budget - system_prompt - TURN_RESERVE` (=1051 at num_ctx 4096), DERIVED
  not a share - a flat 50% left 915 tokens for the turn's own work, less than the **1,181** a
  single `company_financials` observation costs, so the model fetched data Scratchpad then
  dropped before it could read it (found by a LIVE run, invisible to every unit test);
  `KEEP_VERBATIM=2` turns are never folded,
  and the rest go into `ChatSession.summary` via ONE CLASSIFIER call, advancing
  `summarised_upto` (which `_rehydrate` honours, so a folded turn is never also sent in full).
  Persisted, so later turns reuse it. `_compact_for` NEVER raises - a housekeeping failure
  must not eat the user's question. Compaction is reported as a `compacted` count on the
  `started` event and the run meta, deliberately NOT as an `AgentStep`: `intro` runs before
  the driver stamps orders from 0, and a step here means one TOOL CALL. Phases 1-3 of 6 done;
  **ALL SIX PHASES DONE** - the legacy path (`ChatPanel`, `useLLMChat`, the `/agents` chat
  mode, `ChatStreamView`, `/api/llm/chat/stream/`, `services.chat_stream`) is removed;
  `/api/llm/chat/` stays for `useSinglePrompt`. The `started` event carries `run_id` and `session_id` (every other workflow gets `run_id` only on the terminal `result` event, via `succeed`) because stopping a half-written reply is the most-used control in a chat UI and `StopRunView` needs the row id - waiting for the result means Stop only works once there is nothing left to stop. Live smoke:
  `manage.py run_llm_live chatagent --smoke` (scripted three-turn conversation + the context
  budget). NB writing its printer found that FIVE of the command's existing step printers had
  read `args` since issue #6 renamed it `tool_args` - the structural guard covered the
  workflow modules, not the consumers - and that the dag printer labelled nodes with the row
  UUID rather than `node_id`; all fixed and pinned by
  `TestStepPrintersUseTheSerializerNames`. **The constraint that shapes the
  rest**: at `num_ctx=4096` the Scratchpad budget is ~3,000 tokens, and a chat SESSION is the
  first workload in this app that exceeds it (every other prompt peaks at ~1,100), so sessions
  need COMPACTION rather than Scratchpad's trim-and-give-up policy
- Concurrent fan-out (`chat_many`) is capped at `OLLAMA_NUM_PARALLEL` to match the server's parallel slots — never oversubscribe
- **`num_ctx` is sent EXPLICITLY on every main-model call** (`services.chat` and `chat_stream`),
  seeded from `OLLAMA_NUM_CTX` via `LLMSettings.num_ctx`. The point is that the window is DECLARED
  - it is what `_context.Scratchpad`'s budget measures against, and it makes silent truncation a
  configuration choice rather than an accident. Ollama truncates past `num_ctx` without erroring
  (proved on the live host: a synthetic 12,052-token prompt reported `prompt_eval_count=4095` and
  the model answered from the surviving third).
  **The VALUE is 4096, and raising it is not free.** Measured on the live host (RTX 3060, 12 GB):
  `4096` -> qwen3:8b takes 6.25 GB and **all three models stay resident**; `8192` -> 7.54 GB,
  2 of 3; `16384` -> 10.11 GB, 2 of 3. Above 4096 the main model crowds the CLASSIFIER out, so
  every routed query pays a model swap - which breaks the `OLLAMA_MAX_LOADED_MODELS>=3` invariant
  below. It also buys nothing today: the largest REAL prompts in this app measure **~1,100 tokens**
  (a full ReAct scratchpad; the AI company summary). This was briefly shipped at 16384 and reverted
  - raise it only alongside a residency re-measurement
- **`_context.Scratchpad` bounds the two ACCUMULATING loops** - `react` and
  `autonomous.run_subagent`. Everything else sends a one-shot `system + user` per call and has
  nothing to accumulate, so nothing else uses it. Budget is `num_ctx` minus `RESPONSE_RESERVE`
  (25%) - a prompt that fills the whole window leaves nowhere for the reply, which is how the
  browser agent came to return empty strings. Trim policy, deliberately stated rather than clever:
  **drop the OLDEST tool observation first**, never the system prompt and never the most recent
  exchange, and WARN every time (a trim we chose beats a trim discovered months later). With
  nothing droppable left it logs and gives up rather than mangling the conversation. Token
  counting is a `len // 4` heuristic on purpose - a tokenizer would add a model-specific
  dependency to a budget that only has to be roughly right and conservative. `browser.py` is
  deliberately NOT a user: browser-use owns its own message construction and `BROWSER_NUM_CTX`
  already sizes its window (pinned by a test)
- **`registry.py` is the one entry per workflow** (issue #6 phase 6): `kind`, URL `slug` and run
  serializer. `views.py` carried a near-identical list/detail pair per workflow - 22 classes
  differing only in those values - and `urls.py` a hand-written route per view; both are now built
  from `WORKFLOWS`, net -253 lines. A twelfth workflow gets its history endpoints from ONE entry.
  **The slug is NOT the kind** (`eval_opt` -> `/evaluate/`, `plan_exec` -> `/plan/`,
  `orchestrator` -> `/orchestrate/`) and `chain` lists at `/chain/` rather than `/chain/history/` -
  those routes predate the kind consolidation and the frontend still calls them, so the
  irregularity lives in the registry rather than in a special case. The POST views are NOT
  collapsed: each has a distinct request serializer and its own per-kind config defaults, so they
  stay hand-written. Guarded by a test that pins the route table EXACTLY (frozen, not recomputed
  from the same registry - a derived expectation would agree with any mistake) plus per-kind
  scoping tests
- **`get_llm_config()` is the ONLY way to read LLM config** - a structural test
  (`test_settings.py::TestLLMSettingsIsTheOnlySourceOfTruth`) fails any module that touches
  `settings.OLLAMA_*`, exempting only `models.py` (which defines the seeding defaults) and
  `core/settings/`. It uses the AST, not grep, because a regex that strips string literals to
  avoid matching prose also blanks **f-strings** - and the offender it caught was written
  `f"{settings.OLLAMA_BASE_URL}/api/tags"` in `core/views.py`'s health probe, which would have
  reported health for whichever host was configured when the row was first created
- **Changing an `OLLAMA_*` code default does NOT change an existing deployment.** The env vars only
  SEED `LLMSettings` field defaults on first creation, and a migration that ADDS a field computes
  its callable default ONCE at migration time and writes that value to the existing row. Paid for
  on 2026-09-25: `OLLAMA_NUM_CTX` shipped at 16384, migration `0038` baked 16384 into the prod row,
  and the follow-up revert to 4096 changed only `settings.OLLAMA_NUM_CTX` - `get_llm_config()` kept
  returning 16384 and the regression stayed live. **After reverting or changing a default, check
  the ROW** (`LLMSettings.get_solo()`), not just the setting, and update it if it differs
- **A management command produces NO traces.** `configure_tracing()` is called only from
  `core/wsgi.py` and `core/celery.py`, deliberately never from `AppConfig.ready()`, so
  `manage.py run_llm_live ...` runs the agent with tracing entirely off. To verify span structure
  in prod the run must go through **gunicorn** (POST the API) or Celery
- Runtime config lives in a **`LLMSettings` singleton** (django-solo `SingletonModel`, app `solo` in `INSTALLED_APPS`) editable at `/api/llm/settings/` (GET/PUT/PATCH, `IsAuthenticated`) and from the frontend **LLM Settings** page, plus the Django admin. All readers go through `config.get_llm_config()` (`= LLMSettings.get_solo()`, with an unsaved-defaults fallback when the table is unavailable) - never `settings.OLLAMA_*` directly. The `OLLAMA_*` env vars (below) only **seed** the singleton's field defaults on first creation (via callable defaults that read `settings.OLLAMA_*`), so a fresh row mirrors the deployed `.env`; after that the row is the source of truth. Agent request bodies may still override `max_steps`/`threshold` per-call (serializer default `None` -> view falls back to the singleton). Tests use the `llm_settings` fixture (`conftest.py`) which patches `get_solo` to an in-memory instance
- Configured (seed defaults) via `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_MAIN_MODEL`, `OLLAMA_CLASSIFIER_MODEL`, `OLLAMA_EMBED_MODEL`, `OLLAMA_NUM_PARALLEL`, `OLLAMA_NUM_CTX`, `OLLAMA_ROUTE_MODE`, `OLLAMA_ROUTE_THRESHOLD`, `OLLAMA_REACT_MAX_STEPS`, `OLLAMA_CHAT_MAX_STEPS`, `OLLAMA_EVAL_MAX_ITERATIONS`, `OLLAMA_EVAL_THRESHOLD`, `OLLAMA_PLAN_MAX_STEPS`, `OLLAMA_PLAN_MAX_REPLANS`, `OLLAMA_ORCH_MAX_WORKERS`, `OLLAMA_MULTIAGENT_MAX_TOOLS`, `OLLAMA_DAG_MAX_NODES`, `OLLAMA_AUTO_MAX_CYCLES`, `OLLAMA_AUTO_MAX_SUBAGENTS`, `OLLAMA_AUTO_SUBAGENT_STEPS`, `OLLAMA_AUTO_NO_PROGRESS`, `OLLAMA_TIMEOUT`; AI company summary freshness gate: `SUMMARY_SNAPSHOT_MAX_AGE_DAYS`, `SUMMARY_PRICE_MAX_AGE_DAYS`, `SUMMARY_FINANCIALS_MAX_AGE_DAYS`; browser agent: `BROWSER_ENABLED`, `BROWSER_PROVIDER`, `BROWSER_MODEL`, `BROWSER_NUM_CTX`, `BROWSER_MAX_STEPS`, `BROWSER_TIMEOUT_S`, `BROWSER_HEADLESS`, `BROWSER_ALLOWED_DOMAINS`, `BROWSER_SCREENSHOT_ROOT`, `BROWSER_SCREENSHOT_RETENTION_DAYS`, `BROWSER_THROTTLE_RATE`
- One Ollama instance serves the classifier, main chat LLM, and the embedding model (`nomic-embed-text`). Set `OLLAMA_MAX_LOADED_MODELS>=3` on the server so all three stay resident

### Request serializers: optional fields MUST allow null

`required=False, default=None` lets a key be **omitted**; it does NOT let it be sent as `null`
- DRF rejects an explicit null with "This field may not be null." Every frontend stream helper
builds its payload with `?? null` (`useChatAgent` sends `session: null` on the first message of
a conversation, `useBrowserAgent` sends `provider`/`max_steps` the same way), so the gap is a
400 on the most common request rather than an edge case. It reached the browser on issue #8.
**`TestOptionalRequestFieldsAcceptNull` now derives the check** across every
`*RequestSerializer` rather than testing one example.

### The SSE paths bypass the axios interceptor

`streamChatTurn` / `streamBrowser` use raw `fetch` because axios cannot stream a response body,
so they never reach the 401-refresh interceptor in `api/client.ts` - they call the exported
`refreshAccessToken()` and retry once instead. They must also **throw on any non-OK response**:
`readSSE` finds no `data:` lines in a JSON error body, so it yields zero events and returns
normally, and the caller sees a run that finished with no output and no error. On /chat that
rendered as a bare "No reply." for a 401, a 500 and a dead Ollama alike.

## Environment Variables

Configuration is ONE file: **`.env` at the repo root** (template: `.env.example`), read by
Django (`core/settings/base.py` via `core/env.py`), Vite (`envDir: '..'`), docker compose
(`${VAR:-default}` interpolation, auto-loaded), `scripts/dev.sh`, VS Code (`.vscode/launch.json`
+ `settings.json` `envFile`) and, on prod, the systemd units' `EnvironmentFile` - rendered there
from the Ansible vault by `roles/deploy/templates/env.j2`. **There is no per-directory fallback**:
`backend/.env` and `frontend/.env` are gone (issue #4), and a missing root file means code
defaults, not a second lookup.

Keep it flat `KEY=value`: systemd has no shell, so `export`, `${VAR}` and `$(cmd)` are taken
literally - which is also why the prod `SECRET_KEY` is generated alphanumeric-only (Django's own
`get_random_secret_key` alphabet includes `#`, which truncates the value at a comment, and `$`).
`frontend/.env.test` is the one deliberate exception - vitest must not depend on local config.

`backend/core/tests/test_env_contract.py` is the guard, and it covers every consumer, not just
the file: a required key going undocumented, a key in the example that nothing reads, a line
that stops being systemd-safe, a hardcoded credential or port in `docker-compose.yml`, a compose
default drifting from `.env.example`, `DATABASE_URL` disagreeing with `POSTGRES_PORT`, `env.j2`
missing a key prod cannot default, a systemd unit pointing somewhere else, or `deploy.sh`
hardcoding the API base URL again. `frontend/src/test/env-contract.test.ts` covers the browser
half: `envDir` resolves to the repo root, `envPrefix` is never set (that prefix is the security
boundary keeping `SECRET_KEY` out of the bundle), and every `VITE_*` key the app reads is
declared in `.env.example`.

Keys: `SECRET_KEY`, `DATABASE_URL` (postgresql+psycopg://...), `CELERY_BROKER_URL`, `ANTHROPIC_API_KEY`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_MAIN_MODEL`, `OLLAMA_CLASSIFIER_MODEL`, `OLLAMA_EMBED_MODEL`, `OLLAMA_NUM_PARALLEL`, `OLLAMA_NUM_CTX`, `OLLAMA_ROUTE_MODE`; AI company summary freshness gate (optional, defaults shown): `SUMMARY_SNAPSHOT_MAX_AGE_DAYS=7`, `SUMMARY_PRICE_MAX_AGE_DAYS=3`, `SUMMARY_FINANCIALS_MAX_AGE_DAYS=120`; knowledge graph (optional, defaults shown): `KG_SIM_THRESHOLD=0.7`, `KG_MAX_DEPTH=2`, `KG_MAX_NEIGHBORS=8`, `KG_MAX_NODES=5000`, `KG_MIN_EDGE_WEIGHT=0.6`, `KG_MAX_DEGREE=20`, `KG_RERANK_TRIGGER=30`, `KG_RERANK_TARGET=15`, `KG_WSD_ENABLED=False`; browser agent (optional, defaults shown): `BROWSER_ENABLED=False`, `BROWSER_PROVIDER=ollama`, `BROWSER_MODEL=qwen3-vl:8b` (MUST be a vision model - a text-only one 400s every step), `BROWSER_NUM_CTX=32768` (4096 is too small - empty responses), `BROWSER_MAX_STEPS=15`, `BROWSER_TIMEOUT_S=300`, `BROWSER_HEADLESS=True` (a non-blank `BROWSER_ALLOWED_DOMAINS` default ships in `base.py`)

Logging/observability (optional, defaults shown): `LOG_LEVEL=INFO`, `LOG_FORMAT=json`
(`console` for a readable single line in development), `REQUEST_ID_HEADER=X-Request-ID`,
`PROMETHEUS_METRICS_PORT_ENABLED=False` (dev only - prod sets a port RANGE in `prod.py`,
one per gunicorn worker)

Frontend keys live in the same root file: `VITE_API_BASE_URL=http://localhost:8004`. All
frontend vars must be `VITE_`-prefixed - that prefix is what keeps `SECRET_KEY` and
`ANTHROPIC_API_KEY` out of the browser bundle, so never set `envPrefix` in `vite.config.ts`.
Compose reads `POSTGRES_DB`/`POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_PORT`/`REDIS_PORT`
from it too.

Docker DB runs on port **5435** and Redis on **6380** (mapped from the containers' 5432/6379).
Both are set once in the repo-root `.env` (`POSTGRES_PORT` / `REDIS_PORT`), which
`docker-compose.yml` interpolates - change them there, not in the compose file.

## Infrastructure

### Pulumi (container provisioning)

Manages two Proxmox LXC containers — app (VMID 200) and DB (VMID 201) — via
`pulumi-proxmoxve`, which bridges the same `bpg/proxmox` provider. **Python
program, `uv`-managed, local file state backend.** Migrated from Terraform in
Aug 2026 by importing the live containers (never recreating them).

```
infra/pulumi/
  __main__.py              # 2 LXC resources (Ubuntu 24.04): app 2 CPU / 4 GB / 40 GB,
                           #                                 db  2 CPU / 2 GB / 20 GB
  containers.py            # shared ContainerSpec + make_container helper
  Pulumi.yaml              # project (runtime python, toolchain uv)
  Pulumi.prod.yaml         # stack config; secrets encrypted, safe to commit
  state/ .passphrase       # local state + its decryption key — gitignored
```

**Container spec**: static IPs `192.0.2.200/24` (app) and `192.0.2.201/24`
(db), unprivileged with nesting. Both carry `protect=True`.

**Storage**: root disks live on the 4 TB NVMe SSD LVM-thin pool **`nvme4tb-lvm`**
(the `containerDatastore` stack config value), migrated off the old `local-lvm`.
The OS template still comes from the `local` dir storage. If containers are moved
between pools by hand in the Proxmox UI, update `containerDatastore` and run
`just pu-refresh` — a normal apply would see the changed `disk.datastoreId` and
try to **destroy/recreate** both containers (`protect=True` turns that into a
hard error rather than a wipe).

**Ignored fields**: `initialization.userAccount`, `operatingSystem` and
`features` are pinned via `ignore_changes` — the Proxmox API cannot read them
back, so after an import they read as empty and every preview would want to
replace (destroy) the containers. All three are ForceNew anyway.

**`pu-up` can reboot the containers**: an apply touching `console`/`startOnBoot`
restarted both (~10-15 s downtime) even writing already-matching values; a
tags-only apply did not. Check `pu-preview`'s field list before applying.

### Ansible (machine bootstrap only)

Runs once to configure the machine. **Never used for app deploys** — that is CI/CD's job.

```
infra/ansible/
  site.yml                 # Full bootstrap: provision + deploy + services + webhook
  inventory/hosts.yml      # prod: root@192.0.2.200
  group_vars/prod.yml      # non-secret vars (app_dir, container_ip, github_repo_url…)
  vault/prod.yml           # Ansible Vault encrypted secrets
  .vault_password          # gitignored
  roles/
    provision/             # OS packages, app user, Python/Node/PostgreSQL/Redis/Nginx/uv
    deploy/                # DB setup, .env from vault, initial git clone + dep install
    services/              # systemd units (stockmarket-api, stockmarket-celery) + Nginx
    webhook/               # adnanh/webhook listener on :9000 + deploy.sh script
```

### CI/CD Pipeline

```
push to main
  └─ version.yml — backend-tests + frontend-tests (self-hosted runners, LAN)
       └─ both pass → bump patch tag (v0.x.y)
            └─ deploy.yml triggered by "Auto Version" completing successfully
                 └─ self-hosted runner curls http://192.0.2.200:9000/hooks/deploy
                          └─ /home/app/deploy.sh on prod
                               ├─ git pull origin main
                               ├─ uv sync --no-dev
                               ├─ manage.py migrate + collectstatic
                               ├─ npm install + vite build
                               └─ systemctl restart stockmarket-api stockmarket-celery
                               log: /home/app/deploy.log
```

**Workflow files**:
- `.github/workflows/version.yml` — runs tests, bumps version tag on success
- `.github/workflows/deploy.yml` — triggered by the `workflow_run` of "Auto Version"
  completing successfully on `main`, fires prod webhook
- `.github/workflows/backend.yml` — backend tests (also used via `workflow_call`)
- `.github/workflows/frontend.yml` — frontend tests + build (also via `workflow_call`)

**Self-hosted runners**: VMID 111 (`gh-runner` LXC on Proxmox). Runners 6/7/8 serve this repo.

**Secrets required** (GitHub repo secrets):
- `WEBHOOK_SECRET` — HMAC secret for webhook signature validation

## Observability

Grafana + Prometheus + Loki + **Tempo** + Alloy (metrics, logs and traces). Metrics and
logs are **GitHub issue #2**, all four phases complete. Tracing is **GitHub issue #5**,
which SUPERSEDES issue #2's "no tracing" decision. Phases 1-2 (Tempo server + Alloy OTLP
pipeline) are DEPLOYED and verified end to end (2026-09-23). Phase 3 (OTel
instrumentation of Django/Celery/psycopg/redis/httpx in `core/tracing.py`, plus
`trace_id` in the JSON log body and bidirectional Grafana correlation) is BUILT and
tested but ships OFF (`OTEL_TRACES_ENABLED=False`) and is not deployed yet - it needs a
code push AND an Ansible run. Phase 4 (manual spans on the Ollama calls and agent runs) is BUILT,
DEPLOYED and verified against a live agent run. Phase 5 (Tempo span metrics -> a `Domain / Tracing`
dashboard + exemplars) is DEPLOYED and verified: ALL FIVE PHASES COMPLETE. Mimir stays
out of scope on purpose. Full design:
`docs/project_docs/observability.md`.

```
app/db host                                stockmarket-obs (.208, VMID 208)
  journald ----\                             +-> Loki       <- loki.write
  nginx logs ----> Grafana Alloy -------------|
  deploy.log --/                              +-> Prometheus <- prometheus.remote_write
  exporters ---/                              +-> Tempo      <- otelcol.exporter.otlp
  OTLP :4317 -/                              (Grafana provisions all three + dashboards)
```

- **Server**: `infra/observability/` (docker-compose + Prometheus/Loki config + Grafana
  provisioning), run on `.208` by `observability-stack.service`. Config and dashboards
  are checked into the repo and mounted read-only, so a rebuilt container comes back
  wired. See that directory's README.
- **Agent**: Grafana Alloy on every host, from `infra/ansible/roles/observability`. It
  **pushes** - Prometheus never scrapes outward - which keeps LAN traffic
  one-directional and leaves no server-side target list to drift.
- **Everything is gated** on `observability_enabled` in `group_vars/prod.yml`, the same
  opt-in pattern as `browser_agent_enabled` - now ON. `just obs-deploy`, `obs-check`,
  `obs-up/down/restart`, `obs-logs`, `obs-agents`, `obs-verify`.
- **DEPLOYED AND VERIFIED** (2026-09-22): all three hosts live, every target `up=1`
  (four `django` targets, one per gunicorn worker), 7 dashboards + 12 alert rules
  provisioned, and a 404 traced Django -> journal -> Loki with its `request_id` intact.
  Panels + alert delivery verified 2026-09-23: `obs-verify` reports 0 unexplained panels
  of 65, generated traffic summed EXACTLY across the four worker registries, the email
  contact point tested `ok`, and the host-down rule was fired for real (Alloy stopped on
  `.208`) and resolved. Redis was deliberately NOT stopped to fire an alert - it is the
  Celery broker.
- **`just obs-verify`** (`infra/observability/verify_dashboards.py`) runs every dashboard
  panel's query against the live Prometheus. It exists because the pytest metric-name
  check can only cover `django_*`/`celery_*`/`stockmarket_*` - the node/redis/postgres
  families come from Alloy's bundled exporters, which pytest cannot import. It found
  `pg_stat_database_rollback` (the real name is `pg_stat_database_xact_rollback`), a
  panel that had been drawing one line of two since phase 2. Legitimately-empty panels
  An EMPTY panel is NOT judged on its own - an idle system and a typo look identical
  (`topk(5, histogram_quantile(...))` over an idle histogram is empty, not NaN, because
  topk drops NaNs). On empty/NaN it asks WHICH OF THE EXPRESSION'S METRICS HAVE NO SERIES
  AT ALL, which idleness cannot explain, and names the culprit. Absent names must be
  declared in `EXPECTED_MISSING` with a reason (agent gauges; celery failure/retry
  counters; the three django-prometheus After-middleware families, which have no series
  until the first request after a worker restart). Declaring exact NAMES, not panels, is
  what keeps it honest: a misspelling is a different name, so an entry can never silence
  one. The script is itself pinned by pytest (extraction, token substitution, response
  classification, exit codes, stale entries) - a verifier that checks nothing is worse
  than none. Two extraction bugs were caught by those tests, not prod: a leaked grouping
  label (`sum`/`kind`) is queried as a metric and fails every panel it cannot parse, and
  a lowercase-only regex skipped `node_memory_MemAvailable_bytes`, silently "explaining"
  every empty host panel.
- **The metric-name test also covers the ALERT RULE expressions**, which matters more
  than the dashboard half: a panel on a misspelled metric at least reads as empty to
  whoever opens it, but a RULE on one evaluates cleanly, reports `health=ok` and stays
  inactive forever - indistinguishable from a healthy system.
- **Empty is not zero.** A counter with no observations has NO series, and a ratio over an
  empty vector is empty - so a 0% error rate rendered as "No data". The django 5xx and
  celery failure-rate panels wrap each counter in `or vector(0)` (same class as the Redis
  alert's `and redis_memory_max_bytes > 0`); the matching alert rules were already safe
  via `noDataState: OK`.
- **A `deploy.sh` change only takes effect on the NEXT deploy**: the webhook runs
  `infra/deploy.sh` from the working tree and bash reads a script as it executes, so the
  `git pull` inside it rewrites the already-running file. The metrics-exporter restart
  block shipped in the same commit as its own deploy, so `stockmarket-metrics` kept
  serving an 11-hour-old process with NO `DomainCollector` - `celery_*` present, every
  `stockmarket_*` silently absent. Check the exporter's start time before suspecting the
  query.
- **Alloy's `prometheus.exporter.*` attach their OWN job label** (`integrations/unix`,
  `integrations/redis`, `integrations/postgres`) and a target's existing `job` label BEATS
  `prometheus.scrape`'s `job_name` - setting `job_name` alone does NOT rename it. Each
  exporter is routed through a `discovery.relabel` that forces the short name. Found only
  in prod: the host-down alert selected `job="unix"`, matched nothing, and would have
  fired permanently.
- **nginx REPLACES any inbound `X-Request-ID`** (`proxy_set_header ... $request_id`), so
  behind nginx the middleware's honour-inbound path is never exercised - every id
  originates at the edge.
- **`--tags observability` spans FOUR roles**, and it must: `db` (the `postgres_exporter`
  role + `pg_monitor` grant + `pg_hba` entry), `observability`, `monitoring`, and four
  `services` tasks (api unit, celery unit, metrics unit, nginx). Two are load-bearing in a
  non-obvious way and both have tests: the **api unit** carries
  `Environment=PROMETHEUS_EXPORT_WORKER_PORTS=true`, without which the gated settings ship
  but gunicorn binds NO metrics ports and every Django metric silently vanishes (this
  reached prod once); and the **db exporter tasks**, without which the Postgres exporter
  installs with no role to authenticate as.
- **`obs-deploy` passes `--force-handlers`.** A FAILED play discards pending handlers, so
  a unit file can be rewritten on disk while the running process keeps its old command
  line - and the next run, seeing the file correct, notifies nothing and never fixes it.
  That happened with the celery `-E` flag. Also: `Environment=` only applies on a RESTART,
  never a daemon-reload, so the api/celery unit tasks notify a restart handler.
- **`obs-check` is a diff preview, not a gate.** On an unprovisioned host `--check` stops
  at the first task depending on a previous one's effect (no apt repo written -> `alloy`
  looks unavailable; no DB role created -> the grant looks impossible). Both are dry-run
  artifacts.
- **Logs are JSON on stdout** -> journal -> Alloy -> Loki. `core/logging.py` is the
  formatter; `LOG_FORMAT=console` swaps in a readable line locally.
- **Correlation ids**: nginx mints `$request_id`, logs it, and forwards it as
  `X-Request-ID`; `RequestIDMiddleware` adopts a well-formed inbound value (sanitized -
  it lands in both log lines and a response header, so it is an injection vector on two
  paths) or mints a uuid4. It rides a ContextVar, so a line logged deep in a service
  still correlates. **Two gaps**: `StreamingHttpResponse` bodies are consumed after
  middleware returns, and `services.stream_in_background` uses a daemon thread that does
  not inherit the context - so SSE agent runs are correlated by `AgentRun.id` instead.
- **Cardinality is the rule that matters**: Alloy labels stay at `{host, unit, job,
  level}`. Ticker symbols, user UUIDs, `AgentRun` ids and concept slugs go in the JSON
  body and are queried with `| json | field="x"` at zero index cost. An unbounded label
  value creates one Loki stream per value and is how a small Loki install dies.
- **Exporters**: `prometheus.exporter.unix` everywhere, `.redis` on the app host,
  `.postgres` on the db host. Postgres authenticates as a dedicated `postgres_exporter`
  role holding only **`pg_monitor`** (reads stats and settings, NOT table data); its DSN
  lives in `/etc/alloy/postgres.dsn` (0640, `no_log`) read via `local.file`
  `is_secret`, so the password is not in `config.alloy` and not in `--diff` output.
- **Celery queue depth** comes from the Redis exporter's `check_keys` -> `redis_key_size`.
  A Celery queue is a Redis LIST, so its length IS the backlog (`redis_db_keys` only
  tells you a queue exists). The live queue is literally named **`celery`**: nothing sets
  `task_default_queue`/`task_routes` and the prod worker unit passes no `-Q`, so the
  `-Q default`/`-Q heavy` names in the justfile recipes have no publisher.
- **Dashboards + alerts are code**, in `infra/observability/grafana/`. Three dashboards
  (host/postgres/redis/django/celery/ingestion/agents) and twelve rules in three groups
  - infrastructure
  (disk > 85%, PG connections > 80% of `max_connections`, Redis memory > 90% of
  `maxmemory`, fewer than 3 hosts reporting) and application (5xx > 5%, Celery failure
  rate > 10%, queue depth > 500 for 15m) and domain (price sync > 3 days stale, >2 runs
  stuck over an hour, Ollama unreachable, KG > 90% of cap, and a LOKI-backed deploy-failure
  rule - the only automated signal that a deploy failed, since the GitHub workflow reports
  success as soon as the webhook is accepted) -
  emailed via the LAN mail catcher at `192.0.2.207:1025` (plain SMTP, no auth, so no
  vault secret). **Two rules have load-bearing shapes**: the Redis rule carries
  `and redis_memory_max_bytes > 0` because Ubuntu sets no `maxmemory`, making the bare
  ratio `+Inf` (> 90, so it would fire forever) with `noDataState: OK`; the host-down
  rule COUNTS SURVIVORS (`< 3`) because push-based collection means a dead host stops
  sending rather than reporting 0 - update the 3 when a host is added.
- **Config is tested in pytest** (`core/tests/test_observability_assets.py`, `pyyaml` in
  the dev group) because all of it fails SILENTLY: a typo'd datasource uid is an empty
  panel, a mis-wired alert condition never evaluates, a renamed systemd unit just stops
  shipping logs. It pins uid references, alert conditions, panel layout (no overlap, no
  second y-axis), journal units vs the `services` role's unit files, `job=` labels vs the
  ones Alloy sets, and the host-down threshold vs the inventory.
- **Application metrics**: `django-prometheus` supplies request/latency/DB metrics. Its
  two middleware are the OUTERMOST `MIDDLEWARE` entries (Before first, After last) -
  anything outside them is not counted in the latency they report. The api unit runs
  `--workers 4` and each worker owns a SEPARATE registry, so `prod.py` sets
  `PROMETHEUS_METRICS_EXPORT_PORT_RANGE = range(8005, 8009)` (one port per worker, all
  scraped and summed) rather than a single `/metrics` URL, which would report whichever
  worker served the scrape. TWO settings must stay OUT of `base.py`: the port range
  (binding happens in `AppConfig.ready()`, so every management command and every pytest
  process would bind - `pytest -n auto` collides) and the
  `django_prometheus.db.backends.postgresql` engine swap (`core/settings/test.py` runs on
  SQLite). `core/tests/test_prometheus_wiring.py` pins all of it, including that the port
  range width matches `--workers` and Alloy's target list.
- **Celery metrics** are OUR OWN event consumer: `apps/tasks/metrics.py` +
  `manage.py run_metrics_exporter`, running as `stockmarket-metrics.service` on :8010.
  PyPI's `celery-exporter` (OvalMoney) was last released in 2021 and pins `celery>=4,<5`
  so it cannot install beside Celery 5.x, and danihodovic's is Docker-only while the app
  container has no Docker. Needs all three of: the worker's `-E` flag,
  `CELERY_WORKER_SEND_TASK_EVENTS` and `CELERY_TASK_SEND_SENT_EVENT` - miss any and the
  stream carries heartbeats but no task lifecycle, so every task metric reads zero. It is
  its own process (one broker connection, not four; and phase 4's DB gauges must be
  computed once). `handle_event` is separated from the connection loop so tests drive it
  without a broker, and NEVER raises. Only label is the task name; runtime buckets run to
  600s because prometheus_client's 10s default ceiling would put every real task in +Inf.
- **Domain metrics** are a prometheus_client CUSTOM COLLECTOR
  (`apps/tasks/collectors.py`) registered into the SAME `run_metrics_exporter` process:
  values are computed at scrape time, so they can never be stale relative to the scrape.
  It MUST be one process - "companies with a stale snapshot" is a property of the DB, and
  emitted from all four gunicorn workers it would be summed to 4x the truth. Covers
  ingestion (`stockmarket_companies*`, `_sync_fresh_companies{sync_type}`,
  `_sync_oldest_age_seconds{sync_type}` - the OLDEST company, not an average), agents
  (`_agent_runs{kind,status}`, `_agent_runs_stuck{kind}`, `_browser_runs{stop_reason}`),
  the KG (`_kg_concepts`, `_kg_edges`, `_kg_max_concepts`, `_kg_concepts_awaiting_rerank`)
  and `_ollama_up`. EVERY SECTION IS INDIVIDUALLY GUARDED: `REGISTRY.collect()` propagates
  an exception out of the WHOLE scrape, so one failing query would blank every other
  metric - and the guard's own logging must not raise either.
- **There is deliberately NO per-call Ollama latency metric.** LLM calls happen in both
  gunicorn workers AND Celery prefork CHILDREN, whose registries are unreachable without
  `PROMETHEUS_MULTIPROC_DIR`; a metric covering only the web half would look complete
  while missing the AI summaries and KG expansion. `stockmarket_ollama_up` is probed at
  scrape time instead (complete), and per-call cost shows through
  `celery_task_runtime_seconds`. The one runtime counter that IS instrumented is
  `stockmarket_browser_rejected_total` - a semaphore rejection creates no `AgentRun` row,
  so it leaves no other trace.
- **`PROMETHEUS_EXPORT_WORKER_PORTS` is set ONLY in the gunicorn unit** (via
  `Environment=`, NOT the shared `.env` every unit reads). Binding happens in
  `AppConfig.ready()`, which runs in every process calling `django.setup()` - the Celery
  worker, beat, the metrics exporter, each `manage.py` during a deploy. Ungated, whichever
  started first claims 8005 and Alloy scrapes a Celery worker's registry believing it to
  be a web worker. Exhaustion only WARNS, so it fails silently.
- **Vault keys** (both present): `vault_grafana_admin_password` and
  `vault_postgres_exporter_password`. Generated from a URL-safe alphabet on purpose - the
  exporter password is interpolated into a DSN where `@ : / ? # %` would break parsing,
  and the Grafana one lands in an env file where `$` risks interpolation.
- **pg_hba changes RELOAD, they do not restart** - PostgreSQL re-reads it on SIGHUP, and a
  restart would drop every app connection for an auth-rules change (`listen_addresses`
  does need a restart, which is why that handler stays).
- **TRACING (issue #5, phases 1-2 live).** Tempo `2.10.8` on `.208`, single-binary and
  filesystem-backed; Alloy on the APP HOST ONLY runs
  `otelcol.receiver.otlp` (127.0.0.1:4317/:4318) -> `processor.attributes` (stamps `host`,
  the traces equivalent of the other sinks' `external_labels`) -> `processor.batch` (2s,
  not optional - unbatched, a Celery prefork child does a network round trip per span) ->
  `otelcol.exporter.otlp` -> Tempo. Gated on `alloy_traces_enabled` (default OFF).
  `just obs-trace-test` pushes one span through and reads it back via Grafana, because
  EVERY hop fails silently (a wrong exporter port queues, retries and drops, logging
  nothing on either box).
- **Traces must NEVER be enabled on `.208`.** Tempo publishes `0.0.0.0:4317`/`:4318`
  there and `0.0.0.0` already covers `127.0.0.1`, so an Alloy receiver could not bind -
  and in Alloy a component that fails to start takes the WHOLE agent down, losing that
  host's logs and metrics too. Three tests pin which hosts enable it.
- **The Tempo image is DISTROLESS** (no shell, no wget/curl), so it deliberately has NO
  docker healthcheck: a Loki-style `["CMD", "wget", ...]` probe cannot execute and would
  pin the container at `unhealthy` while it serves fine. A test asserts its absence.
  Related: **Grafana's datasource health API does not work for Tempo**
  (`Method not implemented`); the Test button proxies `/api/echo`.
- **Tempo has no `--storage.tsdb.retention.size` equivalent**, so the disk guard is an
  INGESTION cap, and its 15d `block_retention` is pinned BY TEST to Prometheus'
  `retention.time` - if Tempo expired first, a click-through from a metric would land on
  a compacted-away trace. `max_block_duration: 5m` (vs a 30m default) because otherwise a
  finished trace sits unqueryable in the WAL for half an hour, which looks exactly like a
  broken pipeline while you are testing the pipeline.
- **`tracesToLogsV2` is deliberately NOT wired yet** - it needs `trace_id` in the JSON log
  body, which `core/logging.py` does not emit until phase 3. A test asserts its absence,
  to be replaced by its inverse when phase 3 lands.
- **Validate infra config against the REAL binaries** before deploying, and mutation-check
  the validator: `tempo -config.file=... -config.verify=true` (note `=true`; the bare flag
  prints usage and exits 2) and `alloy validate <file>`. Caveat for this dev box: the
  Docker daemon runs on another host and CANNOT see repo paths - `docker run -v` silently
  creates a DIRECTORY where the file should be, clobbering it. Bake config into a
  throwaway image (`docker build -` with a tar on stdin) instead.
- **TRACING, APP SIDE (`core/tracing.py`, phase 3, built + OFF).** `configure_tracing()`
  is called from EXPLICIT ENTRY POINTS - `core/wsgi.py` (gunicorn) and `core/celery.py`
  via `worker_process_init` (each prefork CHILD) - and NEVER from `AppConfig.ready()`,
  which fires in every process calling `django.setup()` (each `manage.py` in a deploy,
  every pytest worker). Per-CHILD is load-bearing: `BatchSpanProcessor` runs a thread and
  threads do not survive `fork()`, so a provider built in the parent leaves children
  queueing spans that never flush. Sampling is `ParentBased(TraceIdRatioBased(ratio))` -
  ParentBased matters more than the ratio, since without it a sampled parent can have
  unsampled children and the trace renders with holes that look like gaps in the SYSTEM.
  Every failure path (import, setup, one bad instrumentor) degrades to "no tracing";
  instrumentation must never take down a request. `core/settings/test.py` FORCES
  `OTEL_TRACES_ENABLED = False` so a developer's `.env` can never make the suite depend
  on a collector.
- **`OTEL_TRACES_ENABLED` MAY live in the shared `.env`** - the exact inverse of
  `PROMETHEUS_EXPORT_WORKER_PORTS`, which must stay in the gunicorn unit. The difference
  is the entry points: Prometheus binds ports from `AppConfig.ready()` in every process,
  whereas nothing tracing-related starts unless `wsgi.py`/`celery.py` call
  `configure_tracing()`. The `.env` task is TAGGED `observability` and NOTIFIES restart
  api + restart celery, because systemd reads `EnvironmentFile` at unit START - without
  that the file on disk is correct while both services run on the old environment.
- **`trace_id`/`span_id` go in the JSON LOG BODY, never a Loki label** (a trace id is the
  most unbounded value in the system). Grafana correlates BOTH ways: a `trace_id` derived
  field on the Loki datasource, and `tracesToLogsV2` on the Tempo one. `request_id` stays
  alongside - it is the pivot that ALWAYS exists, including on the SSE streaming paths
  that have no span.
- **The 4xx/5xx log lines need a trace-id RESCUE, exactly like the request id did.**
  `BaseHandler.get_response` logs every 4xx/5xx AFTER the middleware chain unwinds, so
  the OTel span has already ended and `get_current_span()` returns an invalid one -
  leaving the ERROR lines, the ones most worth correlating, as the only ones with no
  trace to click through to. `RequestIDMiddleware` therefore stamps
  `request.trace_id`/`span_id` while the span is live (the OTel middleware sits OUTSIDE
  it, so the span is readable there and nowhere later), and `RequestIDFilter` falls back
  to them. The ids are read in the FILTER, not the formatter, because they belong to the
  context that emitted the record - formatting can happen later and on another thread.
- **Django instrumentation must run BEFORE `get_wsgi_application()`.** `DjangoInstrumentor`
  does not wrap a handler, it INSERTS middleware into `settings.MIDDLEWARE`, and
  `WSGIHandler.__init__` calls `load_middleware()` which resolves that list exactly once.
  Instrumenting afterwards mutates a list nobody reads again - and it fails PARTIALLY, so
  it looks healthy: psycopg/redis/httpx spans still arrive, but with no request span above
  them, so every DB query becomes its own orphan ROOT trace. Seen in prod as 5 traces all
  rooted at `SELECT`. `core/wsgi.py` therefore does `django.setup()` ->
  `configure_tracing()` -> `get_wsgi_application()`, pinned by a test.
- **MANUAL SPANS (phase 4).** `core/tracing.py` exposes `span()` / `set_attributes()` /
  `record_error()` / `current_context()` / `attached()`, all no-ops when tracing is off and
  none of which ever raise. Instrumented: `agent.run` (in `stream_in_background`, carrying
  `agent.run_id`/`kind`/`model` - ONE span per run, so a fan-out workflow reads as a single
  waterfall), `ollama.chat` (with `llm.tokens.prompt`/`completion`, free from the response
  body Ollama already returns - this is what closes the "no per-call Ollama latency" gap in
  BOTH the web and Celery halves), `ollama.chat_stream` (`llm.chunks` - for a stream the
  interesting duration is time-to-LAST-token, and the count separates a stream that died
  early from one with little to say), `ollama.chat_many`, `ollama.embed`, and `agent.tool`
  in `tools.run_tool` - a SINGLE choke point covering six workflows (react, plan_exec,
  orchestrator, multiagent, dag, autonomous), so one span replaces six edits. `summarise`
  and `analyse` are covered transitively via `chat`.
- **OTel context does NOT cross a thread boundary**, and the failure is SILENT: the work
  succeeds but reparents into its own ROOT trace, so the waterfall just stops showing the
  structure. Two seams both need `current_context()` + `attached(ctx)`:
  `stream_in_background`'s daemon thread (same gap that forced agent runs to be correlated
  by `AgentRun.id`) and `chat_many`'s ThreadPoolExecutor. **Capture the context INSIDE the
  span you want to be the parent** - captured outside, the workers attach to the CALLER and
  every fan-out call becomes a SIBLING of `ollama.chat_many` rather than a child, so the
  grouping span contains none of the work it exists to group. Found in PROD; the test had
  asserted only the parent's attributes, never that children nested under it.
- **`run_tool` must NEVER raise** - its docstring is the contract and the agent loops treat
  a tool error as data to reason about on the next turn. The tool span records the error and
  still RETURNS the `{"error": ...}` observation.
- **Verify tracing changes against a real trace, not just tests.** Three defects on issue #5
  were tested, reviewed and wrong: the wsgi instrumentation ordering, the 4xx/5xx trace ids,
  and the `chat_many` fan-out parenting. All three were invisible to the suite and obvious in
  a single prod waterfall.
- **SPAN METRICS (phase 5).** A trace store cannot answer "p95 over the last hour", so
  Tempo's `metrics_generator` derives RED metrics from the spans and remote-writes them to
  Prometheus as `traces_spanmetrics_*` / `traces_service_graph_*`, backing the
  `Domain / Tracing` dashboard (uid `sm-tracing`). **Dimensions must be BOUNDED** - only
  `llm.model` and `agent.kind`; `agent.run_id` must NEVER be one (a UUID per run would
  multiply every span name by every run ever executed - it belongs in a span attribute,
  which is free in Tempo). Dimension names arrive **dots-to-underscores**: query
  `llm_model`, never `llm.model`, or the label simply never exists.
- **Exemplars need THREE switches and each missing one fails silently**:
  `send_exemplars: true` (Tempo remote_write), `--enable-feature=exemplar-storage`
  (Prometheus - without it the write succeeds and only the trace id is dropped), and
  `exemplarTraceIdDestinations` (Grafana). The exemplar label is Tempo's, camelCase
  **`traceID`** - NOT the `trace_id` our log bodies use; with the wrong name Grafana still
  DRAWS the dot and the click does nothing.
- **PromQL regexes need TWO escaping layers and fail differently in each direction.** A
  PromQL string literal uses Go escaping, so `\.` is an INVALID escape and Prometheus
  returns **HTTP 400**, not an empty result. A panel needs `ollama\\..*` in PromQL text,
  which is `ollama\\\\..*` in the dashboard JSON. Too many backslashes is the opposite
  failure - a regex matching a literal backslash, which matches nothing and reads as an
  idle panel. `just obs-verify` is what catches the 400; a test covers both directions.
- **Alerting stays METRIC-based.** Span metrics could back an alert and deliberately do
  not: tracing ships off (the rule would sit in NoData), span metrics depend on the whole
  app -> Alloy -> Tempo -> generator -> remote_write chain (so it would fire for pipeline
  faults, not application ones), and the 12 existing rules already cover the same failures
  from a shorter causal chain. Traces are for DIAGNOSIS, metrics for alerting.
- **PER-STEP SPANS use TWO mechanisms**, because the ten workflow modules do not share
  one shape. `core.tracing.step_span()` wraps the loop body where the step loop is in one
  place (chain, react, eval_opt, plan_execute); everything else
  (parallel, orchestrator, multiagent, dag, autonomous) already marks a step RUNNING then
  DONE/ERROR with real timestamps, so `store.update_step` REPLAYS those as a span via
  `tracing.record_completed_step` - one edit covering five modules, and the duration is
  the STEP's own rather than a wrapper's. `router` is deliberately exempt (it persists no
  `AgentStep` rows - it classifies and spawns a chain run). A structural test asserts every
  workflow is covered by one mechanism or the other, so a new workflow cannot silently
  ship without step spans. **The two are NOT equivalent**: a WRAPPER span is open while
  the step runs, so its LLM/tool calls nest INSIDE it
  (`agent.run -> agent.step -> ollama.chat`); a REPLAYED span is built after the fact from
  stored timestamps, so its duration is right but NOTHING nests inside it - the step's LLM
  calls sit as siblings under `agent.run`. Confirmed in prod on an orchestrator run.
- **`_set_attributes` takes a POSITIONAL dict, never `**kwargs`** - the attribute keys
  contain dots (`agent.step_order`), so they cannot be keyword arguments. Passing them as
  kwargs raises `TypeError`, and a bare `except Exception: pass` swallows it, leaving the
  function emitting NOTHING while looking healthy. That is why the guard in
  `record_completed_step` now WARNS ONCE per process instead of staying silent - once, not
  per step, since it runs inside a DB write path.
- **`caplog` cannot see `core.*` log records**: the `core` logger is configured
  `propagate: False`, so pytest's root handler never receives them. Assert on the logger
  object (`patch.object(module, "logger")`) instead.
- **Not built in CI or on deploy**: this is machine bootstrap, like the rest of
  `infra/ansible`. `deploy.sh` is untouched - so a push updates the Django logging half
  only; nginx's JSON log format and Alloy need an Ansible run.

## Git Safety

**Do not run git write operations** (`add`, `commit`, `push`, `merge`, `checkout <branch>`). After making changes, tell the user what to commit and let them run git commands manually.

## Planning

**Plans live in GitHub Issues, not in the repo.** There is no `docs/Plans/` directory — never create plan markdown files.

- One GitHub issue per feature; the issue body IS the plan (phases, deliverables, tests as task-list checkboxes). Open it *before* starting implementation, labelled `enhancement` (or `bug`).
- Status is the issue state: open = active/queued, closed = complete. `gh issue list --label enhancement --state open` shows active plans.
- Each phase must be deployable independently with passing tests before the next begins. After every phase, tick its checkboxes (`gh issue edit <n> --body-file ...`) and add a comment recording what was actually built (deviations, decisions, follow-ups).
- **On completion, CLOSE THE ISSUE — do not ask first.** Closing is part of finishing the
  work, not a separate decision to hand back:
  `gh issue close <n> --comment "All phases complete."` An issue whose every checkbox is
  ticked but which is still open is a stale plan, and `gh issue list --state open` stops
  meaning anything. Close it once all of these hold:
  1. every checkbox ticked (or explicitly recorded as deferred, with the reason),
  2. the full test suite passes and `ruff check` is clean,
  3. the change is deployed and **verified against the running system** where it can be -
     see the Observability section for why a green suite is not sufficient evidence,
  4. affected `docs/project_docs/`, `CLAUDE.md` and `docs/claude-memory/` are updated,
  5. a final comment records what was built, what was deferred and any follow-ups.
  Work that turns out to be separate (an unrelated bug the change surfaced) belongs in a
  NEW issue - it is never a reason to hold the finished one open.
- Run `ruff check` on all modified files at the end of every plan.

Write long issue bodies to a scratch file and pass `--body-file` — do not inline multi-line markdown into `--body`. Full convention: `.github/planning.instructions.md`.

After completing a plan, update any affected `docs/project_docs/` files — do not leave docs out of sync.

## Stock Market Domain Knowledge

This section documents the financial concepts the app models, so Claude can reason correctly about domain logic when writing services, serializers, analytics, and UI.

### The Three Financial Statements

Every public company files three statements — they link together and the whole app is built around them (`StatementType` choices: `income`, `balance`, `cashflow`).

| Statement | What it shows | Key line items stored as `metric` |
|---|---|---|
| **Income Statement** | Revenue → profit over a period | `Total Revenue`, `Gross Profit`, `Operating Income`, `Net Income`, `EBITDA`, `EPS (Basic/Diluted)` |
| **Balance Sheet** | Assets = Liabilities + Equity at a point in time | `Total Assets`, `Total Liabilities`, `Total Debt`, `Cash And Cash Equivalents`, `Total Stockholder Equity`, `Retained Earnings` |
| **Cash Flow** | Cash in / out from operations, investing, financing | `Operating Cash Flow`, `Capital Expenditure`, `Free Cash Flow`, `Issuance Of Debt`, `Repurchase Of Capital Stock` |

Periods are `annual` (12-month fiscal year) or `quarterly` (3-month). Always prefer `annual` for trend analysis; `quarterly` for recent-quarter comparisons. `period_end` is the last day of that reporting period.

**How they link**: Net Income flows from Income Statement → Balance Sheet (retained earnings) → Cash Flow (starting point for operating activities). Free Cash Flow = Operating Cash Flow − Capital Expenditure.

---

### Valuation Metrics (stored in `CompanySnapshot`)

These are point-in-time market metrics fetched from yfinance `.info`.

| Field | Formula | Interpretation |
|---|---|---|
| `trailing_pe` | Price / Trailing-12-month EPS | Classic valuation; high = expensive or high-growth expected |
| `forward_pe` | Price / Analyst-estimated EPS | Forward-looking; lower than trailing PE implies expected earnings growth |
| `price_to_book` | Market Cap / Book Value of Equity | >1 means market values intangibles/growth above accounting value; key for banks/financials |
| `trailing_eps` | Net Income / Diluted Shares Outstanding (TTM) | Actual earnings power per share |
| `forward_eps` | Analyst consensus EPS estimate (next year) | Growth signal; compare to trailing_eps for expected growth rate |
| `market_cap` | Share Price × Shares Outstanding | Size classification (see below) |
| `debt_to_equity` | Total Debt / Total Stockholder Equity | Leverage; >2.0 is high risk in most sectors (except financials/utilities) |
| `return_on_equity` | Net Income / Shareholder Equity | Efficiency of equity; >15% is strong; Warren Buffett screens for >20% |
| `profit_margins` | Net Income / Revenue | Net profit margin; varies widely by sector (software ~25%, retail ~3%) |
| `dividend_yield` | Annual Dividend Per Share / Price | Income return; 2-4% is typical for dividend stocks |

**Snapshot semantics**: each sync creates a new `CompanySnapshot` row — they are immutable time-series records. Always query the latest snapshot with `.order_by('-fetched_at').first()` — do not update existing rows.

**Additional ratios derivable from financials** (not stored directly but computable):
- `EV/EBITDA` = (Market Cap + Total Debt − Cash) / EBITDA — preferred over P/E for capital-intensive or debt-heavy companies; <10 is value territory
- `Price/Sales` = Market Cap / Total Revenue — useful for pre-profit growth companies
- `FCF Yield` = Free Cash Flow / Market Cap — >5% considered attractive; harder to manipulate than earnings
- `ROIC` = Net Operating Profit After Tax / Invested Capital — best measure of capital efficiency; >10% is strong
- `PEG Ratio` = P/E / Annual EPS Growth Rate — normalises P/E for growth; PEG < 1 suggests undervaluation
- `Current Ratio` = Current Assets / Current Liabilities — liquidity; <1 means possible cash crunch
- `Quick Ratio` = (Current Assets − Inventory) / Current Liabilities — more conservative liquidity test
- `Interest Coverage` = Operating Income / Interest Expense — ability to service debt; <2 is danger zone

---

### Profitability Margin Tiers

Margin analysis always examines three layers from the Income Statement:

```
Revenue
  − COGS                    → Gross Profit      / Revenue = Gross Margin
  − Operating Expenses      → Operating Income  / Revenue = Operating Margin
  − Interest & Taxes        → Net Income        / Revenue = Net Margin (= profit_margins in snapshot)
```

Sector benchmarks differ significantly — always compare companies within the same sector/industry. Software: gross margin 70-80%. Retail: gross margin 25-35%, net margin 2-5%. Industrials: net margin 5-10%.

---

### Growth Metrics

Growth is computed across time-series `FinancialStatement` rows:
- **Revenue Growth YoY**: `(current_revenue − prior_revenue) / prior_revenue`
- **EPS Growth**: if `trailing_eps` rising faster than revenue → margin expansion (good); if EPS flat while revenue grows → margin compression (bad)
- **CAGR** (Compound Annual Growth Rate): `(end_value / start_value) ^ (1 / years) − 1` — use for multi-year trend normalisation
- Check 3-year, 5-year, 10-year periods for revenue, earnings, and dividends

---

### Dividend Metrics (stored in `Dividend` model)

| Metric | Formula | Signal |
|---|---|---|
| **Dividend Yield** | Annual Dividend / Price | Income return — high yield can signal distress, verify with payout ratio |
| **Payout Ratio** | Annual Dividend / EPS | <50% = safe and sustainable; >75% = cut risk; ~41% historically optimal |
| **Dividend Growth Rate (DGR)** | CAGR of dividends over 3/5/10 years | Rising DGR signals healthy earnings growth and management confidence |
| **Dividend Coverage Ratio** | EPS / DPS (or FCF / Dividends) | >2 = well-covered; <1.5 = at risk |

`Dividend` rows store individual payment dates and amounts. To compute trailing yield: sum dividends over past 12 months, divide by current price.

---

### Market Cap Classification

Used to categorise companies by `market_cap` from `CompanySnapshot`:

| Category | Market Cap Range | Characteristics |
|---|---|---|
| Mega-cap | > $200B | Blue chips, global brands (AAPL, MSFT) |
| Large-cap | $10B – $200B | Established, liquid, lower risk |
| Mid-cap | $2B – $10B | Growth + stability balance |
| Small-cap | $250M – $2B | Higher growth potential, higher volatility |
| Micro-cap | < $250M | Speculative, illiquid |

---

### GICS Sector Classification

The project uses GICS (Global Industry Classification Standard) sector/industry names as sourced from yfinance. The 11 GICS sectors are:

`Communication Services`, `Consumer Discretionary`, `Consumer Staples`, `Energy`, `Financials`, `Health Care`, `Industrials`, `Information Technology`, `Materials`, `Real Estate`, `Utilities`

Structure: **Sector → Industry Group → Industry → Sub-Industry** (4 tiers, 11 sectors, 25 industry groups, 74 industries). The `Sector` and `Industry` models in this project map to GICS tier 1 and tier 3 respectively. Classification is based on a company's principal revenue source.

Sector context matters for ratio benchmarking:
- **Financials**: P/B is the primary valuation metric (not P/E); D/E ratios are high by design
- **Utilities**: high D/E and dividend yield are normal; value via yield + regulated earnings
- **Technology**: P/E and EV/EBITDA can be high; focus on revenue growth + FCF
- **Energy**: cyclical earnings; EV/EBITDA preferred; track FCF yield and capex intensity
- **Consumer Staples**: stable margins, reliable dividends; screen for ROE and payout ratio

---

### Technical Analysis (Price Bars)

`PriceBar` stores daily OHLCV (Open, High, Low, Close, Volume). Common derived indicators:

| Indicator | How computed | Use |
|---|---|---|
| **SMA (Simple Moving Average)** | Mean of close over N days (e.g. 50, 200) | Trend direction; 50-day crossing 200-day = "golden cross" (bullish) or "death cross" (bearish) |
| **EMA (Exponential Moving Average)** | Weighted average giving more weight to recent closes | More responsive than SMA for short-term signals |
| **RSI (Relative Strength Index)** | Compares avg gains vs avg losses over 14 days; 0-100 scale | >70 = overbought (potential reversal); <30 = oversold (potential bounce) |
| **MACD** | EMA(12) − EMA(26); signal line = EMA(9) of MACD | Trend + momentum; MACD crossing above signal = bullish; below = bearish |
| **Bollinger Bands** | SMA ± 2 standard deviations | Volatility measure; price touching upper band = overbought; lower = oversold |
| **Volume** | Daily shares traded | Confirms price moves; breakout on high volume is more reliable |

Price bar computations should never be done in Python loops on large datasets — use pandas or SQL window functions.

---

### yfinance Data Sources

The `YFinanceClient` maps to these yfinance attributes:

| Service method | yfinance source | Notes |
|---|---|---|
| `get_profile()` | `Ticker.info` | `longName`, `exchange`, `currency`, `sector`, `industry`; `.info` can be inconsistent — always guard against missing keys |
| `get_price_history()` | `Ticker.history()` | Returns OHLCV DataFrame; use `start=` for incremental, `period="max"` for bootstrap |
| `get_snapshot()` | `Ticker.info` | Valuation fields: `marketCap`, `trailingPE`, `forwardPE`, `priceToBook`, `debtToEquity`, `returnOnEquity`, `profitMargins`, `dividendYield`, `trailingEps`, `forwardEps`; full raw dict also stored in `CompanySnapshot.raw` |
| `get_financials()` | `Ticker.income_stmt`, `.balance_sheet`, `.cashflow` + quarterly variants | Melted row format: one row per (statement_type, period, period_end, metric); NaN values stored as None |
| `get_dividends()` | `Ticker.dividends` | Series of (date, amount) |

Additional yfinance attributes available but not yet ingested: `Ticker.recommendations`, `Ticker.institutional_holders`, `Ticker.earnings_dates`, `Ticker.analyst_price_targets`, `Ticker.sustainability` (ESG scores), `Ticker.options`.

**Ticker discovery**: S&P 500 constituents from GitHub CSV (`datasets/s-and-p-500-companies`); NASDAQ-100 from NASDAQ API. Symbols are normalised (`.` → `-` for BRK.B style tickers). New symbols are created as un-bootstrapped stubs; `bootstrap_next_batch()` runs incrementally via Celery to fully ingest each one.

---

### Data Freshness Strategy

| Data type | Update frequency | Rationale |
|---|---|---|
| Company profile | On demand / weekly | Name, sector, industry rarely change |
| `PriceBar` | Daily (incremental) | Fetch only since `max(date)` in DB |
| `CompanySnapshot` | Daily | Point-in-time; never overwrite old rows |
| `FinancialStatement` | Quarterly (after earnings) | Statements update 4×/year; use `update_conflicts=True` |
| `Dividend` | On demand / monthly | `ignore_conflicts=True` is safe (amounts don't change retroactively) |

## End-of-Task Rules

Never create summary/explanation markdown files after completing tasks (`TASK-COMPLETE.md`, `SUMMARY.md`, progress trackers, etc.) unless explicitly requested.
