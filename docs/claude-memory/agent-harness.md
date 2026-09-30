---
name: agent-harness
description: "llm_analysis agent harness (issue #6, CLOSED - all six phases done and deployed): shared SSE events, one step serialisation, the shared loop + wave driver, context management (which found every Ollama call was truncating silently at 4096), and the workflow registry."
metadata:
  type: project
---

## Agent harness — `llm_analysis` (issue #6, started 2026-09-25)

`agent = model + harness`. A harness is the runtime AROUND the model — orchestration, tool
interface, context management, state, isolation, feedback/recovery, observability, evals. It is
NOT the same thing as an *evaluation* harness (`lm-evaluation-harness`); one runs, one scores.
`TODO.md`'s "setup llm harness" line was ambiguous between the two — the user meant the **runtime**
sense.

### What was already a harness (do not rebuild these)

`tools.run_tool` (one entry point, contractually never raises), `store.py` + `meta_spec.py` (sole
validated meta writer), `services.stream_in_background` (durable runs, cooperative stop through the
DB), `core.tracing` (run/step/tool spans), browser.py's isolation. All shared, one implementation.

### What was NOT: the control loop

Eleven workflow modules each hand-rolled the loop, the SSE framing, the terminal write and the
error handling. Measured before phase 1: **`_sse` defined 9 times, `_finish` 9 times**, bodies
byte-identical, and `react.py` had already drifted (no `default=str`).

### Phases 1-3 — DONE

- **`_events.py`** — `sse` / `event` / `succeed` / `fail` / `step_event`. `succeed` and `fail` are
  GENERATORS so the `store.finish_run` write and the terminal SSE event happen together.
  18 duplicate definitions deleted; workflow modules net **−217 lines**.
- **`serializers.STEP_SERIALIZERS`** + `step_event` — the SSE step payload IS
  `step_serializer_for(kind)(step).data`. One serialisation, not two.
- Frontend: every hook's step-event interface became `{ event: "x" } & XState` and every mapper a
  destructure dropping `event`; ~120 lines of adapter deleted.
- **`_runtime.py`** — `drive(run, strategy)` owns budget / span / error isolation / persist / emit /
  terminal status; a `Strategy` gives only policy. `react`, `eval_opt`, `plan_exec` driven. `chain`
  and `router` EXEMPT (chain has no `event` discriminator and ends with a step-shaped `__done__`).

### The defect this fixed (the reason phase 2 was worth doing)

**Seven of ten** workflows described a step differently on the two paths. Visibility depended on an
accident — which name the frontend state type used:

- `react`/`plan_exec`/`orchestrator` typed it `tool_args` (the DRF name) → both paths worked
- `dag`/`autonomous` typed it `args` (the SSE name) → `loadFromDetail` assigns `detail.steps`
  straight into state, so **the tool arguments vanished on every refresh-restore**

`chain` was first written off as "n/a - no `event` key". **Wrong**: having no discriminator makes it
unable to use `step_event`, not exempt from sharing the serialisation. Its payload omitted `id`,
`order` and both timestamps, and `usePromptChain` merges into a client-side template, so the chain
card's duration label (computed from `started_at`/`completed_at`) appeared only after a reload.
`_events.step_payload` exists for exactly this caller.

A second divergence in the same class: SSE normalised absent values to `null`, serializers to
`""`, and two UI sites tested `observation !== null` **strictly** — so a tool-less step rendered an
empty "Observation" block after a reload but not live. Both now send `""`.

### Gotchas paid for

- **`dag`'s `id` changed MEANING**, not presence: graph node key → `AgentStep` row UUID, with the
  key now in `node_id`. `useDag`'s upsert still read `event.id` and **tsc could not see it** —
  both are `string`. Caught by a failing test, not the compiler.
  **AMENDED 2026-09-28 (issue #8):** the frontend was not the only reader. `run_llm_live`'s dag
  printer had the same `id` defect, and FIVE of its step printers still read `args` after the
  rename to `tool_args` — so the live command had been showing `{}` for every tool call in
  react/plan/orchestrate/dag/autonomous ever since. The structural guard covers PRODUCERS
  (no module may stream a bare `args`); nothing covered CONSUMERS. Found only by writing a
  sixth printer beside them. Note `call.get("args")` in the multiagent printer is CORRECT —
  `tool_calls` really is `{"tool","args","observation"}` — so a blind sweep breaks it.
- Converging on the serializer means `""` where the stream used to send `null`. Falsy-equivalent
  in JS *except* against a strict `!== null`.
- Guard lists must be **derived from `AgentRun.Kind`**, not hand-written literals — a twelfth
  workflow would otherwise dodge every structural test by omission. Deriving immediately caught
  that kind `route` lives in `router.py`.
- Payload equivalence was proven by an **AST diff against the pre-change sources** (42 event
  sites, key sets identical), not by trusting the suite. Key *order* changed; immaterial, both
  sides `json.loads`.
- **Phase 3 ADDED ~200 lines** (+148 `_runtime.py`, +53 net across three modules) where phases 1-2
  removed 337. Strategy boilerplate exceeds the mechanism it replaces. The win is one
  implementation and structural invariants, NOT smaller code — weigh this before phase 4.
- **Let the driver stamp the step's position** (`StepSpec.order`). plan_execute indexes into a
  plan a replan rewrites mid-loop; the first cut inferred the index from `len(self.results)`, which
  works only by accident.
- **Coverage is how you find what a refactor orphaned.** Driving three loops left three `_save_*`
  helpers dead; they showed up as the only gap in otherwise-100% modules. It also exposed a
  pre-existing unreachable branch (`if not tail` in the replan path - `parse_plan` raises rather
  than returning `[]`). Deleting it and pinning the contract beats keeping an untestable guard.
- **Freeze a generated contract; never recompute it from the generator.** The route table in
  `test_registry.py` is written out literally, because an expectation derived from the same
  registry would agree with any mistake - and a wrong slug does not raise, it 404s elsewhere.
- **A regex guard that strips string literals cannot see f-strings.** The
  `settings.OLLAMA_*` guard passed while `f"{settings.OLLAMA_BASE_URL}/api/tags"` sat in
  `core/views.py` - blanking quotes to skip prose also blanked the interpolation. Rewritten
  with AST. Found by mutating the fix, not by review.
- **A reverted code default does NOT reach an existing deployment.** `LLMSettings` is seeded once;
  a migration adding a field bakes the default into the row at migration time. The num_ctx revert
  changed `settings.OLLAMA_NUM_CTX` to 4096 while the prod ROW still said 16384 - and the row wins.
  Verify `get_llm_config()` on the target, not the setting.
- **Verify the layer that actually serves traffic.** I "confirmed" the revert by measuring the
  Ollama host's residency with num_ctx I sent myself - which proved 4096 works, not that prod was
  sending it. It wasn't.
- **`manage.py` produces no traces.** Tracing starts only in `wsgi.py`/`celery.py`. A prod span
  check has to go through gunicorn (POST the API) or Celery.
- **Prove the bug BITES, not just that it exists.** A synthetic prompt showed truncation is real;
  it took a deployed regression to ask whether any REAL prompt was affected. None was. Measure the
  workload before sizing for it.
- **On a 12GB card, num_ctx above 4096 evicts the classifier.** 4096->6.25GB (3 of 3 resident),
  8192->7.54GB (2 of 3), 16384->10.11GB (2 of 3). Re-measure residency before ever raising it.
- **Ollama TRUNCATES SILENTLY at num_ctx; it does not error.** The default is 4096 and it applies
  to every call that does not set it. Check `prompt_eval_count` in the response to see what was
  actually evaluated - that is how this was proven. The browser agent had already paid for this
  lesson and nobody generalised it.
- **A survey before building beats an abstraction built on an assumption.** Phase 5 was specified
  as "shared trimming for eleven workflows"; nine of them had nothing to trim, and the real bug
  was one line in `services.chat`.
- **`tracing.span()` takes `**attributes` and agent keys contain dots** — `**`-unpack a dict,
  never pass one positionally. Same trap as `_set_attributes`.
- **A mutation check found a VACUOUS test.** The double-span test passed without the fix because
  the fake step never set `completed_at`, which `record_completed_step` requires - so the replay
  was a no-op for the wrong reason. Always mutate the fix and watch the test fail.
- **Omit an optional kwarg rather than passing None.** `temperatures=None` changed the `chat_many`
  call every non-voting workflow makes and broke a test's fake signature.
- **`intro`/`result` must be generators** (they emit a plan/draft/forced-step; `result` returns its
  `Outcome` via `return`, captured by `yield from`), and **every hook needs guarding**, not just
  `perform` — eval_opt calls the LLM in `next`, plan_execute in `after`.
- **Only `OllamaServiceError`/`AbortedError` become a terminal error event.** Anything else
  propagates: a real bug must not be reported to the user as a failed LLM call.
- A structural guard that gains an allowance needs a test that the allowance is REAL — the
  step-span guard's new `drive` branch would otherwise silently excuse three workflows.
- **Mutation-check every parity test.** All five historical shapes were replayed and all five fail:
  dag's wire shape, browser's old mapper, react's missing error step, chain's three-field merge, and
  a hand-built chain payload. A parity test that passes before the fix is worthless.
- **"No `event` key" is not the same as "exempt".** That reasoning is what made me skip `chain` on
  the first pass and miss a real defect.

### Phases 4-6 — DONE

4. **3 of 5 DONE** — `drive_waves` + orchestrator/dag/parallel. **The phase's trace premise was
   WRONG**: `parallel`/`orchestrator`/`dag` each make ONE `chat_many` covering every step in a
   wave, so no per-step span can contain it — the replayed spans are inherent to fan-out, not a
   symptom of duplication. The driver wraps the WAVE instead (`agent.wave`, with
   `ollama.chat_many` nested under it). `multiagent`/`autonomous` are BLOCKED: both mark rows
   RUNNING before working (so a mid-run refresh shows the in-flight stage) and `drive` creates the
   row only after `perform`; creating-then-`update_step` would double-span. **RESOLVED** with
   `Strategy.pre_step(spec)` (return a row -> the driver updates instead of creating) plus
   `store.update_step(..., replay_span=False)` so the pre-persisted step does not emit TWO spans.
   Both migrated; they DO get real wrapper spans since neither uses `chat_many`. `BaseStrategy`
   now supplies the no-op hooks. TEN of eleven workflows driven; only `chain`/`router` exempt.
   See [[observability]]
5. **DONE, and its premise was wrong too.** Only TWO loops accumulate (`react`,
   `autonomous.run_subagent`); the other nine are one-shot `system + user`. The survey found a
   LIVE DEFECT instead: `services.chat` sent no `num_ctx`, so every main-model call ran at
   Ollama's default **4096** and **truncated silently**. MEASURED on the live host: a 12,052-token
   prompt reported `prompt_eval_count=4095` (66% discarded) and answered wrong; with
   `num_ctx=16384` it evaluated all 12,052 and answered correctly. **BUT the prompt was SYNTHETIC
   and the severity was overstated**: real prompts here peak at ~1,100 tokens (ReAct scratchpad,
   AI summary), so nothing was actually being truncated. Shipping 16384 CAUSED a regression -
   qwen3:8b goes 6.25GB -> 10.11GB and evicts the CLASSIFIER from the 12GB card (3-of-3 resident
   becomes 2-of-3), so every routed query pays a model swap. **Reverted to 4096.** Kept the part
   that has value: the window is DECLARED, so Scratchpad has something to budget against. `_context.Scratchpad`
   bounds the two accumulating loops: budget = num_ctx - 25% reserve, drop OLDEST observation
   first, never the system prompt or latest turn, warn every time. `browser.py` exempt
   (`BROWSER_NUM_CTX` already covers it)
6. **DONE.** `registry.py` = one `WorkflowSpec` per workflow (kind, URL slug, run serializer).
   22 hand-written list/detail view classes -> one generic pair + a `run_views(spec)` factory;
   `urls.py` generates both routes per workflow. **Net -253 lines.** The slug is NOT the kind
   (`eval_opt`->`/evaluate/`, `plan_exec`->`/plan/`, `orchestrator`->`/orchestrate/`) and `chain`
   lists at `/chain/`; both predate the consolidation and the frontend still calls them.
   **POST views stay hand-written** - each has its own request serializer and per-kind config
   defaults, more machinery to registry-ise than it would save.

### Deferred / known

- **issue #7 (FIXED 2026-09-25)** — `react.py` persisted an `AgentStep` for an unparseable turn but
  streamed no event, so the live list was one card shorter than the restored one. Same
  live-vs-restored class as the `args` defect, from a missing event rather than a renamed field.
  A static audit found no other module with a persisted-but-never-streamed step. Phase 3's
  `drive()` makes the class impossible (persist and emit become the same two driver lines).
- The **eval** harness (fixed dataset + scorer + baseline) remains entirely absent. The AI summary's
  60% buy / 1% sell skew is the obvious first eval — see [[ai-summary]].

Related: [[project_state]], [[observability]], [[ollama-api-reference]]

**Issue #9 (2026-09-29): `GROUNDING_RULE` rides on `tool_catalogue()`**, so every agent shown
tools gets it exactly once. `test_grounding_rule.py` derives the catalogue callers by AST and
requires them to equal the checked-prompt map.
**How to apply:** a new workflow that embeds the tool list must use `tool_catalogue()`, never its
own rendering, and must add its prompt builder to `PROMPTS` in that test, or the suite fails.
