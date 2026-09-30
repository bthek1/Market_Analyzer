# Agent Harness - Consolidating the Control Loop

Design record for [issue #6](https://github.com/bthek1/Market_Analyzer/issues/6), which moves the
seam in `backend/apps/llm_analysis/` so that one runtime owns the mechanism and each workflow
contributes only its policy.

**Status as of 2026-09-25: all six phases built. NOT COMMITTED, NOT DEPLOYED.**

## What "harness" means here

`agent = model + harness`. An **agent harness** (also "scaffolding") is the runtime *around* the
model - orchestration and tool use, context management, memory, state and persistence, runtime
isolation, feedback and recovery, observability, evals. You **change** a runtime harness to get
better results.

This is a different thing from an **evaluation harness** (EleutherAI's `lm-evaluation-harness`),
which is a fixed dataset plus a scorer that you **freeze** so results stay comparable. One runs,
one scores. `TODO.md`'s "setup llm harness" line was ambiguous between the two; this issue is the
runtime sense. The eval sense remains entirely unbuilt - see *Not in scope* below.

## Where the seam was

Two-thirds of a harness already existed, and was good:

| Layer | Implementation |
|---|---|
| Tool interface | `tools.run_tool` - one entry point, contractually never raises |
| State + persistence | `store.py` + `meta_spec.py` - the sole validated meta writer |
| Durable execution | `services.stream_in_background` - daemon thread, cooperative stop via the DB |
| Observability | `core.tracing` - `agent.run` / `agent.step` / `agent.tool` / `ollama.*` spans |
| Runtime isolation | `browser.py` - incognito profile, host allow-list, deadline, semaphore |

The **control loop** was not. Eleven workflow modules each hand-rolled the loop, the SSE framing,
the terminal-status write and the error handling. Measured on the working tree before phase 1:

```
_sse     defined 9 times   - bodies byte-identical
_finish  defined 9 times   - bodies byte-identical
react.py's _sse            - json.dumps(payload)              <- the copies had ALREADY drifted
everything else            - json.dumps(payload, default=str)
```

Two costs had already been paid for this, both real:

1. **Split-brain step spans.** Because the modules share no loop shape, per-step spans needed *two*
   mechanisms - `core.tracing.step_span()` wrapping the loop body for the four workflows whose loop
   is in one place, and `store.update_step` replaying stored timestamps via `record_completed_step`
   for the five that mark running-then-done. They are **not equivalent**: a wrapper span is open
   while the step runs so `ollama.chat` / `agent.tool` nest inside it; a replayed span has the right
   duration but nothing nests in it. Confirmed in prod on an orchestrator run. Five of eleven
   workflows cannot show which step an LLM call belongs to.

   **Corrected 2026-09-25 (phase 4):** for `parallel`, `orchestrator` and `dag` this is
   **inherent, not a symptom of duplication**. One `services.chat_many` covers every step in a
   wave, so no per-step span can contain the call that produced it - the replayed mechanism exists
   *because of* the fan-out shape. Only the two strictly sequential fan-out-family workflows
   (`multiagent`, `autonomous`) could gain real wrapper spans. What the wave driver can do is wrap
   the WAVE, so the fan-out is at least visible as a group.
2. **A step had three representations.** The DB row, the hand-built SSE payload, and the DRF
   serializer output, written independently. Covered below.

## Phase 1 - shared event primitives (done)

`apps/llm_analysis/_events.py`:

| Function | Role |
|---|---|
| `sse(payload)` | the only place that knows the wire format |
| `event(name, **fields)` | `sse({"event": name, **fields})` |
| `succeed(run, output, *, meta=None, **fields)` | generator: `store.finish_run` + the `result` event |
| `fail(run, error, *, output="", meta=None, **fields)` | generator: `store.finish_run` + the `error` event |

`succeed` / `fail` are **generators** so a caller writes `yield from fail(run, str(exc))` and cannot
get the DB write and the terminal event out of order, or emit one without the other.

`meta` (persisted to `AgentRun.meta`, validated by `store`) and `**fields` (streamed on the event)
are deliberately separate arguments: several workflows persist a value without streaming it.
`autonomous` is the clearest case - one error path streams `stop_reason`, the other does not.

Result: 18 duplicate definitions deleted, workflow modules **+253 / -470, net -217 lines**.
`autonomous`'s `_finish` had real logic (the `stop_reason` fallback), which became the pure
`_stop_reason(run, stop_reason, *, errored)` helper with no persistence in it. `browser.py` called
`store.finish_run` directly at four sites and now does not.

`chain.py` keeps its own `_sse_event`: its payload carries **no `event` discriminator at all** (the
frontend keys off `step_id`), so only the framing is shared.

## Phase 2 - one serialisation of a step (done)

### The audit

Every workflow's SSE step payload against its DRF step serializer, before the change:

| kind | SSE only | serializer only | verdict |
|---|---|---|---|
| parallel | - | `order` | additive |
| react | `args`, `answer` | `tool_args`, `is_answer`, `error`, `created_at` | **2 renames** |
| eval_opt | - | `error`, `created_at` | additive |
| plan_exec | `args` | `tool_args`, `error`, `created_at` | **rename** |
| orchestrator | `args` | `tool_args` | **rename** |
| multiagent | - | - | clean |
| dag | `id`, `args` | `node_id`, `tool_args` | **2 renames** |
| autonomous | `args` | `tool_args` | **rename** |
| browser | `args`, `goal` | `action_args`, `memory`, `output`, `error`, `created_at` | **2 renames** |
| chain | `run_id` | `id`, `order`, `started_at`, `completed_at` | **omissions** |

**Seven of ten diverged.** Whether a divergence was user-visible depended on an accident: which name
the frontend state type happened to use.

- `react` / `plan_exec` / `orchestrator` typed the field `tool_args` (the DRF name), so the hook's
  SSE branch remapped and both paths worked.
- `dag` / `autonomous` typed it `args` (the SSE name). Every hook's `loadFromDetail` assigns
  `detail.steps` straight into state, so after a refresh-restore `node.args` was `undefined` and
  `agents.tsx` rendered `tool()` with no arguments - while the live stream rendered them fine.
  TypeScript could not catch it: the type is asserted at the API boundary, not validated.

### Chain, which the first pass wrongly wrote off

`chain` was initially recorded as "n/a - no `event` key" and skipped. That was wrong: the absence of
a discriminator makes it *unable to use `step_event`*, not exempt from sharing the serialisation.
Its hand-built payload carried `step_id`/`label`/`status`/`output`/`error` and **omitted `id`,
`order` and both timestamps**; `usePromptChain` merges each event into a client-side template
(chain's steps are pre-seeded), and it merged only `status`/`output`/`error`. So during a live run
`id` and the timestamps stayed at the template defaults - and `ChainStepCard` renders a **duration
label** computed from `started_at`/`completed_at`, which therefore appeared only after a reload.

Fixed by `_events.step_payload(step, kind=...)` - the same serialisation as a dict, for the one
caller that has to frame its own line. `chain.py` now emits `sse({"run_id": ..., **step_payload(...)})`
for real steps, with the two run-level signals (`__init__` / `__done__`) kept as an explicit
`_signal()` helper, since neither corresponds to a row.

### A second divergence, same class

`null` vs `""` for an absent value. The SSE payloads normalised with `or None`; the serializers
default to `""`. `agents.tsx` tested `step.observation !== null` - a **strict** null check - at two
sites, so a tool-less step rendered an empty "Observation" block after a refresh but not during the
live stream. Both paths now send `""` and both checks are truthy.

### The fix

```python
# serializers.py - the ONE kind -> step-representation mapping
STEP_SERIALIZERS = {"chain": ChainStepResultSerializer, "parallel": ..., "dag": DagNodeSerializer, ...}

# _events.py - the payload IS the serializer's output
def step_event(step, name, *, kind=None, **extra):
    data = step_serializer_for(kind or step.run.kind)(step).data
    return event(name, **data, **extra)
```

All nine step-persisting workflows emit through it. Five had a
`_worker_event` / `_node_event` / ... wrapper that collapsed to one line and was inlined.
`plan_execute` / `eval_opt` / `react` previously built their payload from **local variables** rather
than the row they had just written; they now emit the row, so the stream is literally what was
persisted.

Frontend: every hook's hand-written step-event interface became `type StepEvent = { event: "step" }
& XState`, and every mapper became a destructure that drops `event`. About 120 lines of adapter
deleted. `DagNodeState.args` and `AutonomousCycleState.args` renamed to `tool_args`, with their two
render sites.

### The subtle break

`dag`'s `id` did not disappear - it **changed meaning**, from the graph node key to the `AgentStep`
row UUID, with the key now in `node_id`. `useDag`'s upsert still read `event.id`, and **tsc could
not see it** because both are `string`. Caught by a failing test.

## How this is guarded

Structural tests, with their module lists **derived from `AgentRun.Kind`** rather than hand-written
literals - a twelfth workflow is covered the moment its kind exists, instead of whenever someone
remembers to extend a tuple. (Deriving immediately caught that kind `route` lives in `router.py`.)

**Amended 2026-09-28, when the twelfth workflow actually arrived** (`chat`, issue #8): the claim
held for `test_events.py` and the span guards, and did NOT hold for `test_step_payload.py`. That
module derives `STEP_MODULES` from `STEP_KINDS`, which is itself a **hand-written literal** giving
each kind a sample step. So `test_every_run_kind_has_a_step_serializer` went green as soon as the
serializer was registered, while the per-kind parity test and the `tool_args`-never-streamed-as-
`args` guard silently did not run for `chat` at all - they passed **vacuously**. Deriving from a
literal is not deriving from `AgentRun.Kind`; the guard is only as complete as the seed. A kind
missing from `STEP_KINDS` still dodges everything downstream of it, and nothing fails.

**Added 2026-09-29 (issue #9): the grounding rule.** `tools.GROUNDING_RULE` is appended by
`tool_catalogue()` rather than pasted into each prompt, so it holds only while every prompt
builds its tool list through that function. `test_grounding_rule.py` derives the set of modules
that call `tool_catalogue` from the AST (really derived this time - no seed literal), and requires
it to EQUAL the set of modules whose rendered prompts are checked. Every one of those prompts must
carry the rule exactly once. A workflow that starts embedding the catalogue fails until its prompt
is added, and a hand-pasted second copy fails too. multiagent's Analyst and Writer have no tools,
so their empty catalogue stays empty rather than becoming a lone rule about tools they cannot call.

No workflow module may:

1. define a local `_sse` or `_finish`
2. hand-roll a `data: ` line
3. call `store.finish_run` directly
4. hand-build a step payload (AST check for `event("node", ...)` and friends)
5. stream a bare `args` field (AST, because `args=` is also a legitimate dataclass argument)

6. hand-build a chain step payload (`chain.py` may only build the two `__`-prefixed signals)

Plus, per kind, `step_event(step) == StepSerializer(step).data`; and on the frontend, for all **ten**
workflows, a run driven by SSE and the same run loaded via `loadFromDetail` produce **equal state**.

**Every parity test was mutation-checked** against the shape it exists to catch. Re-pointed at the
pre-fix wire shapes they fail: `dag` produces two nodes instead of one with `tool_args` undefined
after restore; `browser` fails against its old mapper; `react` fails on LENGTH when the error step
is filtered out of the stream (issue #7); `chain` fails with `id: ''` against the three-field merge;
and the chain structural guard fails against a hand-built payload. A parity test that passes before
the fix is worthless.

Payload equivalence for phase 1 was proven the same way: an **AST diff of every SSE call site
against the pre-change sources** - 42 event sites across the 6 machine-rewritten modules, key sets
identical. Key *order* changed where a dict literal became kwargs, which is immaterial since tests
and the browser both `json.loads`.

## Verification

| | Phase 1 | Phase 2 | Phase 3 |
|---|---|---|---|
| Backend | 2167 passed, 96.63% | 2209 passed, 96.62% | 2236 passed, 96.52% |
| Frontend | unchanged | 820 passed | 821 passed |
| Lint | `ruff` clean | + `tsc` clean, eslint 0 errors | unchanged |

Phase 3's evidence is that **every per-workflow test passes unmodified** - react 25, eval_opt 18,
plan_exec 35. New `test_runtime.py` (21) covers the driver directly with a strategy that makes no
LLM calls: the budget being the driver's rather than the strategy's, a strategy that never
terminates, zero budget, every hook raising both failure types, partial output kept on failure, and
that an unexpected exception is *not* swallowed. A trace test asserts
`agent.run > agent.step > ollama.chat` nesting; the `spans` fixture moved to `backend/conftest.py`
so both suites can use it. The structural step-span guard gained a third mechanism (`drive`) plus a
test that the driver really opens the span - without which the new allowance would silently excuse
three workflows from having spans at all.

Every pre-existing backend workflow test passed **unmodified** through phase 1 - they are the
contract. Phase 2 changed six of them, each an assertion that encoded the old SSE-only
normalisation (`observation is None` -> `== ""`, `e["id"]` -> `e["node_id"]`, `answer` ->
`is_answer`).

## Phase 3 - the shared loop (done)

`_runtime.py`. `drive(run, strategy)` owns the budget, the per-step span, error isolation, the
step write, the emission and the terminal status. A `Strategy` contributes only policy.

```python
def drive(run, strategy):
    yield from strategy.intro()                      # guarded
    order = 0
    while order < strategy.budget:                   # the budget is the DRIVER's
        spec = strategy.next(order)                  # guarded; None ends the loop
        if spec is None:
            break
        with step_span(run, order, key=spec.key, label=spec.label):
            fields = strategy.perform(spec)          # guarded
            step = store.create_step(run, order, ..., **fields)
            yield step_event(step, strategy.event, kind=strategy.kind)
            yield from strategy.after(step)          # guarded
        order += 1
    outcome = yield from strategy.result()           # guarded
    yield from succeed(run, outcome.output, meta=outcome.meta, **outcome.fields)
```

Three things the plan's sketch did not anticipate:

1. **`intro` and `result` must be generators.** They emit - a plan, a draft, react's forced final
   step. `result` returns its `Outcome` through `return`, which `yield from` hands back.
2. **Every hook is guarded, not just `perform`.** `next` makes an LLM call in eval_opt (the revise
   happens *between* steps) and `after` does in plan_execute (the replan). An escaping error would
   leave the run at `status="running"` with no terminal event - the exact orphaning
   `stream_in_background` exists to prevent.
3. **Only `OllamaServiceError` and `AbortedError` become a terminal error event.** Anything else
   propagates: a genuine bug must not be reported to the user as a failed LLM call.
4. **`StepSpec.order` is stamped by the driver**, not supplied by the strategy. `plan_execute`
   indexes into a plan that a replan rewrites *mid-loop*, so a position inferred from accumulated
   state (the first cut used `len(self.results)`) is one bug away from reading the wrong step.

### What the migration surfaced

Driving the three loops left `_save_action_step`, `_save_iteration` and `_save_step` **orphaned** -
the strategies return persist-kwargs and the driver calls `store.create_step`. Coverage found them
(three modules at 96-97% with the dead functions as the only gap); all three are deleted.

It also exposed a genuinely unreachable branch that predates this work: the replan path's
`if not tail: return`. `parse_plan` **raises** on an empty or unusable plan in both of its exit
paths, so it never returns `[]` and the guard could not fire. The branch is gone and the contract
that makes it unnecessary is now pinned by a test - better protection than an untestable guard,
because if `parse_plan` ever softens to returning `[]`, the replan path would truncate the plan
rather than keep it.

All five modules (`_events`, `_runtime`, `react`, `eval_opt`, `plan_execute`) now sit at **100%**.

`drive` does **not** own stop-checking, contrary to the original plan - `stream_in_background`
already does it at event boundaries, and two mechanisms for one concern is what this issue exists
to remove.

**Exemptions.** `chain` frames a payload with no `event` discriminator and signals completion with
a step-shaped `__done__` rather than a `result` event, so the driver's terminal path does not apply
without adding terminal-override hooks to the protocol; it keeps its own loop. `router` persists no
steps at all.

### Phase 3 costs lines

| | lines |
|---|---|
| `_runtime.py` (new) | +148 |
| react + eval_opt + plan_execute | +342 / -289 = **net +53** |
| **total** | **~+200** |

Phases 1 and 2 removed 217 and ~120 lines. Phase 3 **adds** about 200: the `Strategy` class
overhead (class, `__init__`, six hooks with docstrings) exceeds the ~12 lines of mechanism removed
per module. The win is that the mechanism exists once and the invariants are structural - not that
the code is smaller. This is the number to weigh before committing five more modules to the same
trade in phase 4.

## Phase 4 - the fan-out driver (done)

`drive_waves(run, strategy, model)`: waves in order, steps within a wave concurrently through one
`chat_many`. `orchestrator` (single wave), `dag` (one wave per topological layer) and `parallel`
(one wave, sectioning or voting) are migrated, every per-workflow test passing unmodified.
`orchestrator` now reads as the single-wave special case of `dag`, which is what it always was.

Per-step spans stay **replayed**; the driver wraps the wave instead, emitting `agent.wave` with
`agent.wave` / `agent.wave_size`, under which `ollama.chat_many` nests.

Two gotchas paid for:

- `tracing.span()` takes `**attributes`, and these keys contain dots, so they must be
  `**`-unpacked from a dict rather than passed positionally - the same trap already recorded for
  `_set_attributes`.
- `temperatures` must be **omitted**, not passed as `None`, when a workflow does not spread them.
  Only parallel's voting does; passing it unconditionally changed the call every other workflow
  makes, and broke a test's `fake_chat_many` signature.

### `multiagent` and `autonomous`: the `pre_step` hook

Both are strictly *sequential* (neither uses `chat_many`), so they are the two that genuinely gain
real wrapper spans - `agent.run > agent.step > ollama.chat`. They go through `drive`, not
`drive_waves`.

Both create their step rows `PENDING` and mark them `RUNNING` **before** doing the work, so a
mid-run refresh shows the in-flight stage. `drive` creates the row only *after* `perform` returns,
which would have lost that - a live-vs-restored regression, the exact class phase 2 removed.

`Strategy.pre_step(spec) -> AgentStep | None` resolves it: return a row and the driver UPDATES it
instead of creating one. That exposed a second interaction - `store.update_step` replays a span on
terminal status, and the driver already holds an open one, so a pre-persisted step would emit
**two** `agent.step` spans. Hence `store.update_step(..., replay_span=True)`, which the driver
passes as `False`.

`BaseStrategy` supplies no-op `pre_step` / `after` / `failure`, so a strategy writes only the hooks
it actually needs - which also shrank the six existing strategies.

**Ten of eleven workflows are now driven** (eleven of twelve since `chat` landed in issue #8).
Only `chain` and `router` remain exempt, for the reasons recorded above - and that is now a **structural test**, derived from `AgentRun.Kind`: a
twelfth workflow arriving with its own hand-rolled loop fails rather than quietly re-growing the
duplication this issue removed. Two more guards sit beside it: every sequentially-driven module
must contain no `step_span(` of its own (or its steps would nest twice), and `drive_waves` must
contain none at all (a per-step span there could not hold the `chat_many` that produced it).

After phase 4 every workflow module in `apps/llm_analysis/` sits at **100% coverage**, which is
how the migration's leftovers kept surfacing - three `_save_*` helpers in phase 3, then
`multiagent`'s `_mark_done`/`_mark_error`, then two untested `autonomous` stall paths and the
sub-agent's tolerant-parse branches.

## Phase 5 - context management (done)

### The premise was wrong, and the correction found a live defect

This phase said "every workflow hand-builds its `messages` list" and needed shared trimming. A
survey said otherwise: **only two loops accumulate** - `react` and `autonomous.run_subagent`. The
other nine build a one-shot `system + user` per call, where there is nothing to trim.

The survey found something worse, and it belongs here because it IS context management:
**`services.chat` sent no `num_ctx`**, so every main-model call ran at Ollama's default 4096.
`num_ctx` was set in exactly one place in the repo - `browser.py` - where `base.py` already
recorded *"browser-use never sets num_ctx itself, so we must."* That reasoning was never extended
to anything else.

**Measured against the live host, 2026-09-25** - with a SYNTHETIC prompt built to exceed the
window, which turned out to matter (see the correction below):

| | `prompt_eval_count` | answer |
|---|---|---|
| default (what `services.chat` sent) | **4,095** of 12,052 | `MARKER` (wrong) |
| `num_ctx: 16384` | **12,052** | `MARKER-ALPHA-7719` (correct) |

A marker placed in the system prompt, ~12k tokens of filler after it, and a question asking for
the marker back. **66% of the prompt was silently discarded** and the model answered from what
survived, with no error anywhere - so the symptom is quietly degraded answers, not an exception.
That is why it could have been live indefinitely without anyone noticing.

Re-verified through the real code path after the fix: `options: {'num_ctx': 16384}`,
`prompt_eval_count: 12052`, correct answer. Then a full `manage.py run_llm_live react` run against
live Ollama completed normally on real data.

### Correction: the severity was overstated, and the first fix regressed prod

The truncation mechanism is real and the measurement above is sound. But it was demonstrated with
a **synthetic 12k-token prompt**, and the follow-up question - *does any real prompt in this app
get truncated?* - was not asked until after the change had shipped at `num_ctx=16384`. It should
have been.

The answer is no. Measured from persisted data: a full ReAct scratchpad peaks at **1,108 tokens**,
and the AI company summary - the largest single prompt in the app - at **~1,100**. Nothing came
close to 4096.

Meanwhile the fix caused a real regression. On the live host (RTX 3060, 12 GB):

| num_ctx | qwen3:8b VRAM | models resident |
|---|---|---|
| 4096 (before) | 6.25 GB | **3 of 3** |
| 8192 | 7.54 GB | 2 of 3 |
| 16384 (shipped, reverted) | 10.11 GB | 2 of 3 |

Above 4096 the main model crowds the CLASSIFIER out of VRAM, breaking the
`OLLAMA_MAX_LOADED_MODELS>=3` invariant CLAUDE.md records - so every routed query pays a model
swap. A theoretical fix bought at the cost of a measurable regression.

Reverted to **4096**. What is kept is the part that has value regardless: the window is now
DECLARED rather than defaulted, so `Scratchpad` has something real to budget against and raising
it later is one setting plus a residency re-measurement.

### What shipped

- `OLLAMA_NUM_CTX` (default **4096**, see the correction above) -> `LLMSettings.num_ctx` -> `services.chat` **and**
  `chat_stream` (separate payloads, so separately wired). Editable from the LLM Settings page like
  every other knob; `required=False` so an old full PUT still validates.
- `_context.Scratchpad` for the two accumulating loops. Budget is `num_ctx` minus
  `RESPONSE_RESERVE` (25%) - a prompt filling the whole window leaves nowhere for the reply, which
  is how the browser agent came to return empty strings.
- **Trim policy, stated rather than clever**: drop the OLDEST tool observation first; never the
  system prompt, never the most recent exchange; WARN on every trim. With nothing droppable left
  it logs and gives up rather than mangling the conversation. A trim we chose beats a trim
  discovered months later.
- Token counting is `len // 4` on purpose. A tokenizer would add a model-specific dependency to a
  budget that only has to be roughly right and conservative.
- `browser.py` is deliberately NOT a user - browser-use owns its own message construction and
  `BROWSER_NUM_CTX` already sizes its window. Pinned by a test so the absence reads as a decision.

## Phase 6 - the workflow registry (done)

`registry.py` holds one `WorkflowSpec` per workflow: `kind`, URL `slug`, run serializer, and a
`list_at_root` flag for chain's irregular path. `views.py`'s 22 hand-written list/detail classes
collapse to one generic pair plus a `run_views(spec)` factory, and `urls.py` generates both routes
per workflow from the registry. **Net -253 lines across the two files.**

Two irregularities are now data rather than special cases: the slug is not always the kind
(`eval_opt` -> `/evaluate/`, `plan_exec` -> `/plan/`, `orchestrator` -> `/orchestrate/`), and
`chain` lists at `/chain/` rather than `/chain/history/`. Both predate the kind consolidation and
the frontend still calls them.

**The route table is pinned EXACTLY** in `test_registry.py`, frozen rather than recomputed from
the registry the code uses - a derived expectation would agree with any mistake. That matters more
here than elsewhere, because a wrong slug does not raise: it 404s somewhere far away.

### Not done, deliberately

The **POST views stay hand-written**. Each has its own request serializer and its own mapping from
request fields to `LLMSettings` defaults (`max_steps` -> `react_max_steps`, `threshold` ->
`eval_threshold`, and so on), so a registry entry covering them would carry a callable and a
defaults map per workflow - more machinery than the eleven ~15-line classes it would replace, for
a shape that genuinely differs per workflow. The issue's "serializers.py shrinks to the per-kind
field maps" is likewise not done: those per-kind serializers encode real field renames the
frontend depends on, so there is nothing left to remove.

## Remaining phases

none - all six are built. What is left is **committing, deploying and verifying against a real
trace**, which the Definition of Done requires and which has not happened.

Historical numbering, for reference:
6. **Migrate the five fan-out workflows** (parallel / orchestrator / multiagent / dag / autonomous),
   which needs a wave/batch step type in `drive`. This also **retires `record_completed_step`** for
   those kinds: they get real wrapper spans, so LLM and tool calls nest correctly. Must be verified
   against a real Grafana trace, not only the suite - three defects on issue #5 were tested,
   reviewed and still wrong, and all three were obvious in one prod waterfall.
7. **Collapse the view and serializer triples** into a kind registry; `urls.py` generated from it.

`browser.py` is exempt from phases 3-5 (its loop lives inside browser-use's async callback on
another thread) and `router.py` from 3-4 (it persists no `AgentStep` rows).

## Not in scope

- **Evals.** The other sense of "harness" - a fixed dataset, a scorer, a baseline. Entirely absent:
  `run_llm_live` runs every workflow against live Ollama and *prints*, nothing asserts; `eval_opt`'s
  evaluator is an in-loop control signal, not an offline measurement; the observability stack
  measures cost, not quality. An agent that got 40% faster and 40% dumber looks like a pure win on
  every dashboard we have. The AI summary's unmeasured 60% buy / 1% sell skew is the obvious first
  eval - see `ai-summary-pipeline.md`.
- **Adopting an external framework** (LangGraph, Pydantic AI, Agents SDK). The eleven patterns were
  built to be legible; this keeps them legible and stops copying the plumbing.

## Follow-up: issue #7 (fixed 2026-09-25)

The audit turned up one more instance of the same live-vs-restored class, from a **missing event**
rather than a renamed field: `react.py` persisted an `AgentStep` for an unparseable model turn but
streamed nothing for it, so the live list showed one card fewer than the same run after a reload.
It was left out of phase 2 because emitting the event is a behaviour change, not a shape change,
and fixed immediately after as [issue #7](https://github.com/bthek1/Market_Analyzer/issues/7).

A static audit of every workflow's `create_step`/`seed_steps`/`update_step` call sites against its
`step_event` calls found no other module where a persisted step never reaches the client. The
fan-out workflows do not stream the intermediate *running* transition per step, but that is by
design - the `plan` / `wave` / `started` events carry it, and every step is streamed on completion.

This class stops being possible in phase 3: under `drive()` the persist and the emit are the same
two lines of the driver, so a workflow cannot write a step and forget to stream it.
