# LLM Workflow Patterns

The most useful organizing split (Anthropic's "Building Effective Agents" framing) is **workflows** — orchestration logic lives in your code, paths are predictable — versus **agents**, where the LLM itself directs control flow and tool use. Most real systems mix both.

> **Persistence (2026-06-13):** every workflow below persists to TWO unified, typed, polymorphic
> Django models — `AgentRun` (discriminated by `kind`) + its child `AgentStep` — not the 19
> per-workflow models the prose names. The per-workflow `*_id` columns live in `AgentStep.key`;
> route's `chain_run` link is now `AgentRun.parent`. Per-kind DRF serializers reproduce the legacy
> JSON field names (`step_id`/`task_id`/`worker_id`/`node_id`/`agent_id` <- `key`;
> `iterations`/`tasks`/`workers`/`nodes`/`cycles` <- `steps`; `index` <- `order`;
> `chain_run` <- `parent`), so the API/SSE contract is unchanged. Read "persists `XRun`/`XStep`"
> below as `AgentRun(kind=...)` + `AgentStep`.

---

## Ordered by Complexity

### 1. Single Prompt
One call. Question in, answer out. No memory, no tools, no loops. Starting point for any task.

### 2. Prompt Chaining (Pipeline)
Linear sequence of LLM calls — each step's output feeds the next, often with gates between steps. Best when a task decomposes into fixed, predictable subtasks. Trades latency for accuracy.
```
Scrape → Summarise → Translate → Format
```

### 3. Routing
Classify the input first, then dispatch to a specialised prompt, model, or code path. Good for separating concerns (easy queries → cheap model, hard → strong model). No loops.

**This project implements Routing** in `apps/llm_analysis/router.py` (`POST /api/llm/route/`, history at `/api/llm/route/history/` + `/<uuid>/`). Each query resolves to one of `simple` / `analysis` / `comparison` / `deep_research`:
- *simple* → one direct Ollama call.
- *analysis* → fans out 3 concurrent aspect calls (Valuation / Profitability / Risk) via `parallel.section_batches`, then aggregates (the sectioning logic is shared with the observable parallel agent).
- *comparison* → concurrent per-ticker narration (`chain.research_tickers`) then a single synthesis call; degrades to *analysis* if fewer than 2 tickers resolve.
- *deep_research* → spins up a full prompt chain (`ChainRun`) and streams its steps.

Route selection runs two ways, set by `OLLAMA_ROUTE_MODE`: the LLM classifier (`llm`, default — one call on the cheap `OLLAMA_CLASSIFIER_MODEL`) or semantic embedding (`semantic` — embeds the query against per-route exemplars, 0 LLM calls above `OLLAMA_ROUTE_THRESHOLD`, falls back to the LLM classifier below it). `route_method` and `route_confidence` are persisted on each `RouteRun`. Classification always uses the classifier model; a per-run `model` override only swaps the MAIN model.

### 4. Parallelization
Either *sectioning* (independent subtasks run concurrently, then aggregated) or *voting* (same task run N times, take consensus/majority). Useful for latency or raising confidence.

**This project implements Parallelization** as a first-class, observable agent (`apps/llm_analysis/parallel.py`, `POST /api/llm/parallel/`). Both strategies fan out via `services.chat_many` (bounded by `OLLAMA_NUM_PARALLEL`) and aggregate with one main-model call:
- *Sectioning* reuses `router.ANALYSIS_ASPECTS` (Valuation / Profitability / Risk) — the same logic the `analysis` route uses internally, extracted into `parallel.section_batches` / `parallel.aggregate_sections` so there is one copy.
- *Voting* runs N identical buy/hold/sell verdict prompts with spread temperatures (`VOTING_TEMPS`, via `chat_many(temperatures=...)`), tallies the majority (ties → `hold`), and writes a consensus rationale.

Unlike the `analysis`/`comparison` routes (where the fan-out is an invisible optimization emitting a single `result`), the `parallel` agent surfaces each sub-call as a live SSE `task` event and persists `ParallelRun` / `ParallelTaskResult`. The Agents UI exposes it as a selectable workflow panel (sectioning grid / voting cards + tally) in the unified Agents workspace, where it can run side by side against any number of other workflow panels on the same query.

### 5. ReAct (Reasoning + Acting)
The default single-agent loop. LLM interleaves Thought → Tool Call → Observation, repeating until it decides it has enough information to answer. Dynamic tool selection, bounded loop.
```
Question → [Thought] → [Tool Call] → [Observation] → repeat → [Answer]
```

**This project implements ReAct** as the first *true agent* (`apps/llm_analysis/react.py`, `POST /api/llm/react/`, history at `/api/llm/react/history/` + `/<uuid>/`). Unlike chain / route / parallel (where our code fixes the control flow), here the LLM itself picks the next tool each turn:
- The loop seeds a scratchpad (`system` tool-catalogue + `user` query) and, each turn, asks the MAIN model for ONE JSON object - either an action `{"thought", "tool", "args"}` or a terminal answer `{"thought", "answer"}` (tolerant parsing via `parse_react_output`, mirroring the router classifier).
- Tools (`apps/llm_analysis/tools.py`: per company `company_profile`, `company_snapshot`, `peer_comparison`, `company_financials`, `recent_price`; per group `list_sectors`, `sector_analysis`, `industry_analysis`; generic `current_time`, `weather`) are **read-only DB lookups** - no LLM call, no network, no writes. They never raise: a bad symbol / bad args / unknown tool returns a `{"error": ...}` observation the loop can recover from. The query logic is shared with `chain._research_company` via `chain.snapshot_metrics` / `chain.annual_financials`.
- **Units in observations (issue #11).** Return on equity, profit margins and dividend yield are stored as FRACTIONS but reach the model in PERCENT, named `*_pct` (`return_on_equity_pct: 23.26`), in `company_snapshot`, `sector_analysis`/`industry_analysis` and chain research alike. Given bare fractions, the model converted some to percent and not others within a single answer. The unit lives in the field NAME because an observation can be truncated (chat carries 600 chars into the next turn) and a name cannot be cut away from its value. Valuation multiples (P/E, P/B, D/E) are unchanged.
- **`peer_comparison(symbol, scope?)` (issue #13)** puts a company beside its peers with the RELATION computed in code: for each metric, the company value, the peer median, `vs_median` ("18% below"), a quartile `band` and a `reading` in that metric's own vocabulary. P/E and P/B read as cheap/expensive, ROE and margins as more/less profitable ("not a price measure"), yield as higher/lower and D/E as more/less leveraged. Given both numbers, the model wrote "28.49 is above 34.30" in 9/10 runs. Comparing two floats is arithmetic, so the tool does it. The group is `tools.peer_group`: the industry, falling back to the sector below 3 peers, and always excluding the company itself. The AI summary uses the same rule. A gap under 1% reads "under 1% below", never the self-contradicting "0% below".
- The loop is **bounded** by `run.max_steps` (default `OLLAMA_REACT_MAX_STEPS = 6`). Exhausting the budget forces exactly one final-answer call; unparseable output is nudged and the turn is retried within the cap. It is strictly **sequential** (each tool call depends on the prior observation) - no `chat_many` fan-out.
- Each turn is surfaced as a live SSE `step` event and persisted as `ReactRun` / `ReactStep`. The Agents UI exposes it as a selectable workflow panel (numbered Thought -> Action -> Observation cards + final answer) in the unified Agents workspace, where it can run side by side against any number of other workflow panels on the same query.

All eleven patterns are now implemented: Single Prompt, Prompt Chaining, Routing, Parallelization, ReAct, Evaluator-Optimizer, Plan-and-Execute, Orchestrator-Workers, Multi-Agent Sequential/Hierarchical, Multi-Agent Parallel/DAG, and Autonomous / Long-Horizon (all in `apps/llm_analysis/`); there is no separate `agent` app.

### 6. Evaluator-Optimizer (Reflection / Self-Critique)
Generator LLM produces a draft; evaluator LLM critiques it; generator revises. Loops until a quality bar is met. Works when you have clear eval criteria and iteration measurably helps (code that must pass tests, translations, formal writing).

**This project implements Evaluator-Optimizer** as an observable agent (`apps/llm_analysis/eval_opt.py`, `POST /api/llm/evaluate/`, history at `/api/llm/evaluate/history/` + `/<uuid>/`). Three prompt roles on the MAIN model drive a quality-gated loop:
- *generate* produces an initial markdown draft.
- *evaluate* scores the draft 0-10 against a fixed rubric (directly answers / factually grounded / complete / concise) and returns ONE JSON object `{"score", "feedback", "pass"}` (tolerant parse via the shared `parse_json_object` helper, reused by ReAct).
- *revise* rewrites the draft to address the feedback.

Unlike chain/route/parallel (fixed paths) the *number* of iterations is data-dependent: the loop stops when `score >= run.threshold` (default `OLLAMA_EVAL_THRESHOLD = 8`) or `pass` is true, else after `run.max_iterations` (default `OLLAMA_EVAL_MAX_ITERATIONS = 3`), returning the **best-scoring** draft seen (not necessarily the last). Unparseable verdicts are treated as score 0 so the loop keeps refining without crashing. It is strictly **sequential** (revision depends on the prior critique) - no `chat_many` fan-out. Each iteration streams an `iteration` SSE event (after an initial `draft` event) and persists `EvalOptRun` / `EvalOptIteration`. The Agents UI exposes it as a selectable workflow panel (numbered Draft/Score/Feedback cards + best final answer) in the unified Agents workspace, where it can run side by side against any number of other workflow panels on the same query.

### 7. Plan-and-Execute
Planner LLM produces a full multi-step plan upfront; executor LLM runs each step in order, optionally replanning when reality diverges. Fewer mid-run planning calls than ReAct, better long-horizon coherence. Failure mode: stale plans.

**This project implements Plan-and-Execute** as an observable agent (`apps/llm_analysis/plan_execute.py`, `POST /api/llm/plan/`, history at `/api/llm/plan/history/` + `/<uuid>/`). Four MAIN-model roles:
- *plan* returns ONE JSON object `{"plan": [{"task", "tool", "args"}, ...]}` capped at `run.max_steps` (default `OLLAMA_PLAN_MAX_STEPS = 6`); the tool catalogue is embedded so the planner picks valid tools (or `null` for a pure-reasoning step). Tolerant parse via the shared `_json.parse_json_object` (also tolerates a bare list).
- *execute* runs each step in order: the planner-chosen tool is run via the **same read-only `tools.run_tool`** ReAct uses (no LLM), then one executor call interprets the observation + earlier results.
- *replan* (only when `run.allow_replan` and a step's tool observation is an `{"error"}` - the "reality diverged" signal) revises the remaining steps; hard-capped by `OLLAMA_PLAN_MAX_REPLANS` (default 2).
- *synthesise* folds all step results into the final markdown answer.

Unlike ReAct (which picks the next tool reactively each turn) the plan is committed upfront in one planning call - trading adaptivity for long-horizon coherence; the failure mode (a stale plan) is mitigated by the bounded replan. Strictly **sequential** - no `chat_many` fan-out. Streams a `plan` event, then a per-step `step` event (task + tool + observation + result), an optional `replan` event, and a final `result`; persists `PlanExecRun` / `PlanExecStep`. The Agents UI exposes it as a selectable workflow panel (upfront plan list + numbered Task/Tool/Observation/Result cards + a "replanned" badge) in the unified Agents workspace, where it can run side by side against any number of other workflow panels on the same query.

### 8. Orchestrator-Workers
A lead LLM dynamically decomposes a task and delegates subtasks to worker LLMs (or tool-calling agents), then synthesises results. Like parallelization but the subtasks aren't known upfront.

**This project implements Orchestrator-Workers** as an observable agent (`apps/llm_analysis/orchestrator.py`, `POST /api/llm/orchestrate/`, history at `/api/llm/orchestrate/history/` + `/<uuid>/`). Three MAIN-model roles:
- *orchestrate* returns ONE JSON object `{"subtasks": [{"task", "focus", "tool", "args"}, ...]}` capped at `run.max_workers` (default `OLLAMA_ORCH_MAX_WORKERS = 4`); the tool catalogue is embedded so the orchestrator picks valid tools (or `null` for a pure-reasoning subtask). Tolerant parse via the shared `_json.parse_json_object` (`parse_subtasks`, also tolerates a bare list).
- *worker* runs once per subtask: any planner-chosen tool is run synchronously via the **same read-only `tools.run_tool`** ReAct/plan-execute use (no LLM), then the worker calls fan out **concurrently** via `services.chat_many` (bounded by `OLLAMA_NUM_PARALLEL`, per-call error isolation).
- *synthesise* folds all worker outputs into the final markdown answer (mirrors `parallel.aggregate_sections`).

The crucial difference from Parallelization/sectioning: there the sections are a **fixed, hard-coded** list (`ANALYSIS_ASPECTS`) chosen by our code; here the orchestrator **invents the subtasks at runtime from the query**, so their number, focus, and chosen tools vary per question. Distinct from Plan-and-Execute too: that commits an ordered plan run **sequentially** (each step depends on the prior), whereas orchestrator-workers decomposes into **independent** subtasks run **in parallel** then synthesises (the independence assumption is load-bearing - dependent/ordered work is plan-execute's job). Worker rows are created **after** the decomposition (not pre-seeded). Streams a `started`, a `plan` (the dynamic subtask list), one `worker` event per subtask (task + tool + observation + output), and a final `result`; persists `OrchestratorRun` / `OrchestratorWorker`. A failed worker emits `status: "error"` but never drops the others; if all fail the run finishes with an error. The Agents UI exposes it as a selectable workflow panel (decomposition list + concurrent worker card grid + final answer) in the unified Agents workspace, where it can run side by side against any number of other workflow panels on the same query.

### 9. Multi-Agent (Sequential / Hierarchical)
Supervisor routes to specialised sub-agents (e.g. Researcher → Analyst → Writer), each with their own tools and prompts. Results passed back to orchestrator for synthesis. Worth the overhead only when subtasks genuinely need isolated context or tools.

**This project implements Multi-Agent (Sequential/Hierarchical)** as an observable agent (`apps/llm_analysis/multiagent.py`, `POST /api/llm/multiagent/`, history at `/api/llm/multiagent/history/` + `/<uuid>/`). A lead **supervisor** (two MAIN-model roles) routes the query to a fixed, role-specialised roster and synthesises:
- *route* returns ONE JSON object `{"agents": ["researcher", "analyst", "writer"], "reason": "..."}` - an ordered **subset** of the fixed roster (tolerant `parse_route` via the shared `_json.parse_json_object`; keeps known ids in roster order, dedupes, always force-includes `writer`, falls back to the full roster on unparseable output). The supervisor can only subset the roster, never invent agents.
- The roster is a declarative `ROSTER` registry of `SubAgent`s, each with its **own system prompt** and its **own allow-listed tool subset**: *Researcher* (the data tools), *Analyst* (none), *Writer* (none).
- The sub-agents run as a strictly **sequential hand-off pipeline** (no `chat_many`): each stage's output becomes the next stage's only input (plus the original query) - **isolated context**, unlike ReAct's single shared scratchpad. The *Researcher* is a plan-then-fetch tool agent (one tool-selection call -> `tools.run_tool` x K, capped at `run.max_tools` and filtered to its allow-list via `parse_tool_plan` -> one findings call); *Analyst*/*Writer* are single reasoning calls with no tools.
- *synthesise* folds every completed stage's output into the final markdown answer (reuses `orchestrator`'s aggregation prompt).

The crucial differences from the cousins: unlike `chain` (plain prompts, no tools, no agent identity) each stage is a bona-fide specialised agent; unlike `orchestrator-workers` (homogeneous generic workers, dynamic decomposition, parallel) the roster is fixed, role-specialised, and sequential; unlike `plan-execute` (one generic executor with all tools) tool access is allow-listed per agent. A failing stage degrades the handoff but does not abort the run; if all stages fail the run finishes with an error. Streams `route` -> per-stage `step` (input + tool_calls + output) -> `result`, persists `MultiAgentRun`/`MultiAgentStep`. The Agents UI exposes it as a selectable workflow panel (roster + stacked sequential stage cards with the Researcher's tool calls + final answer) in the unified Agents workspace, where it can run side by side against any number of other workflow panels on the same query.

### 10. Multi-Agent (Parallel / DAG)
Multiple agents run concurrently on independent subtasks. Orchestrator fans out, waits, then synthesises.

**This project implements Multi-Agent (Parallel/DAG)** as an observable agent (`apps/llm_analysis/dag.py`, `POST /api/llm/dag/`, history at `/api/llm/dag/history/` + `/<uuid>/`). A lead **orchestrator** (two MAIN-model roles) dynamically decomposes the query into a **dependency graph** and synthesises:
- *decompose* returns ONE JSON object `{"nodes": [{"id", "task", "focus", "tool", "args", "depends_on": ["<id>", ...]}, ...]}` capped at `run.max_nodes` (default `OLLAMA_DAG_MAX_NODES = 6`); the tool catalogue is embedded so each node picks a valid read-only tool (or `null`). Tolerant parse via the shared `_json.parse_json_object` (`parse_nodes`, also tolerates a bare list); `parse_nodes` also performs **graph hygiene** - assigns missing ids, prunes `depends_on` edges to unknown ids / self-loops, and **breaks cycles** (drops the DFS back-edge) so the result is always a valid DAG.
- `topological_waves` (the only new primitive, pure code, no LLM) layers the graph Kahn-style: wave 0 = nodes with no deps, wave k = nodes whose deps all sit in earlier waves. Nodes within a wave are independent and run **concurrently** via `services.chat_many` (bounded by `OLLAMA_NUM_PARALLEL`, per-call error isolation); waves run **in order**, and each downstream node's prompt is injected with its upstream nodes' outputs.
- *synthesise* folds the **terminal (sink) node** outputs into the final markdown answer (reuses `orchestrator`'s aggregation prompt).

The crucial difference from Orchestrator-Workers (section 8): there the subtasks are **independent by contract** (a single parallel fan-out); here nodes carry explicit `depends_on` edges, so the graph runs in **waves** and dependents consume upstream outputs - Orchestrator-Workers is exactly this pattern restricted to a single wave. Distinct from Plan-and-Execute (a strictly sequential ordered plan; here the partial order lets independent branches parallelise) and from Multi-Agent Sequential (a fixed, role-specialised, width-1 pipeline; here the graph is dynamic and arbitrary-width). Node rows are created **after** decomposition (not pre-seeded). A failing node emits `status: "error"` with a placeholder output so dependents still receive input; if **all** nodes fail the run finishes with an error. Streams `plan` (the graph + computed waves) -> per-wave `wave` -> per-node `node` -> `result`; persists `DagRun`/`DagNode`. The Agents UI exposes it as a selectable **DAG** mode (wave-layered node-card rows with `depends_on` chips + per-node tool calls + final answer) in the unified Agents workspace, where it can run side by side against any number of other workflow panels on the same query.

### 11. Autonomous / Long-Horizon Agent
Agent maintains long-term goals, self-assigns tasks, spawns sub-agents, reflects on failures, and replans indefinitely until the goal is achieved. (AutoGPT-style.) Very hard to make reliable.

**This project implements Autonomous / Long-Horizon** as the final observable agent (`apps/llm_analysis/autonomous.py`, `POST /api/llm/autonomous/`, history at `/api/llm/autonomous/history/` + `/<uuid>/`). The agent holds a long-term **goal** (the query), maintains a self-managed task **backlog**, and runs a bounded **controller loop**:
- *bootstrap* restates the goal and seeds an initial backlog (one MAIN call; tolerant `parse_bootstrap`, falls back to the raw query as the goal).
- each *cycle* the controller returns ONE JSON object that REFLECTS on progress and the prior cycle's failures, SELF-ASSIGNS the next task, rewrites the backlog, and picks an `action`: `tool` (run one read-only `tools.run_tool` lookup, then interpret it), `subagent` (delegate a self-contained sub-goal to a bounded, **non-recursive** sub-agent - a small ReAct-style tool loop capped at `OLLAMA_AUTO_SUBAGENT_STEPS`, gated by `run.max_subagents`), or `reason` (pure reasoning over working memory). Tolerant `parse_controller` via the shared `_json.parse_json_object`; an unknown action degrades to `reason`.
- each cycle's output is folded into **working memory**, injected into the next controller call. The number of cycles is data-dependent: the loop stops when the controller sets `goal_complete`, when the cycle budget (`run.max_cycles`, default `OLLAMA_AUTO_MAX_CYCLES = 8`) is exhausted, or when a **no-progress** detector trips (`OLLAMA_AUTO_NO_PROGRESS` consecutive cycles add nothing). On every termination path a final *synthesise* call folds working memory into the answer, so a run is never blank.

The documented hard part - reliability ("replans indefinitely... very hard to make reliable") - is handled by hard-bounding everything: a hard cycle cap, a hard sub-agent cap with non-recursive bounded sub-agents, the no-progress detector, tolerant parsing with deterministic fallbacks, read-only tools that never raise, and per-call error isolation (a failed tool/sub-agent/LLM call marks that cycle `error`, feeds the error into the next cycle's reflection, but never aborts the run; only an all-failed run finishes with an error). Distinct from **ReAct** (section 5): ReAct answers a *single* question in one shared scratchpad with a fixed tool menu and ends when it can answer; the autonomous agent pursues a *goal* across cycles, keeps an explicit mutable backlog, can *spawn sub-agents*, reflects on failure, and OWNS the termination decision. Distinct from **plan-execute** (commits a plan once) and **orchestrator/dag** (decompose once and fan out): here decomposition is *continuous and adaptive* - the next task depends on what prior cycles discovered. Streams `goal` -> per-cycle `cycle` -> `result`; persists `AutonomousRun`/`AutonomousCycle`. The Agents UI exposes it as a selectable workflow panel (goal + live backlog + numbered cycle cards with reflection/action/tool-or-sub-agent/result + a terminal stop-reason badge + final answer) in the unified Agents workspace, where it can run side by side against any number of other workflow panels on the same query.

---

## Cross-Cutting: RAG

RAG is a retrieval axis you bolt onto any pattern above:

- **Naive** — retrieve-then-read (one fixed retrieval step)
- **Advanced** — query rewriting, reranking, pre/post-retrieval steps
- **Agentic RAG** — LLM decides when and what to retrieve, multi-hop reasoning
- **GraphRAG** — retrieval over a knowledge graph for relational/global questions

---

## Practical Heuristic

Start with the simplest thing that works (often a single augmented LLM call with tools + retrieval). Only add agentic autonomy when the task genuinely cannot be expressed as a fixed path. Each level up adds debugging surface area and latency.

LangGraph maps onto all of this directly — workflows are static edges, agents are conditional edges / cycles back into a node.

