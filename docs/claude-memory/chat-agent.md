---
name: chat-agent
description: "Chat as a harness workflow (issue #8). A turn IS a run, sessions group them; num_ctx=4096 makes a chat session the first workload here needing COMPACTION, and the twelfth workflow proved one structural guard passes vacuously."
metadata:
  type: project
---

## Chat agent - `llm_analysis` (issue #8, started 2026-09-28)

Chat was the ONE LLM surface outside the harness: a raw `fetch` to `/api/llm/chat/stream/`,
`ChatStreamView` piping `services.chat_stream` straight out. No `AgentRun`, no history, no
Stop, no durability, an orphan span - and **no tools**, because nothing advertised them and
there was no loop to run one in. It invented figures that were sitting in our own DB.

The deeper point: `chat` was not an `AgentRun.Kind`, and **every structural guard is derived
from that enum**, so chat could not fail the tests that exist to stop exactly this. Being
outside the taxonomy is what made it invisible, not an oversight in any one test.

### Design decisions worth keeping

- **A turn IS a run.** `AgentRun.query` = user message, `output` = reply, `AgentStep` rows =
  that turn's tool calls. So the transcript is the ordered run list and there is NO separate
  Message model to keep in sync. This fell out of the existing columns; it was not designed in.
- **Sessions are a `ChatSession` model, not an `AgentRun.parent` chain.** The first sketch used
  `parent` (already used for route -> chain). It stops paying the moment a session is a product
  object: renameable title, "list my conversations by recency", one cascading delete, a place
  for the compaction summary. `parent` backwards is an N-query traversal per sidebar row.
- **The budget is per TURN, not per session.** That is what keeps `drive`'s contract intact -
  it runs a bounded loop to a terminal status and never suspends waiting on a human. A session
  open for days is a sequence of short, individually-terminal runs.
- **ReAct's loop shape, deliberately.** The tool loop is precisely what makes `tools.run_tool`
  reachable; that is the capability the old path lacked. But three differences matter: the
  prompt must PERMIT ANSWERING IMMEDIATELY (a research-shaped prompt makes the agent fetch a
  company snapshot to say hello), the budget is lower (4 vs 6 - interactive, latency beats
  exhaustiveness), and `tools_used` accumulates on the run.

### `num_ctx=4096` is the constraint that shapes the whole feature

Scratchpad budget = num_ctx - 25% reserve = **~3,000 tokens**. Every pre-existing workload fits
(largest real prompt ~1,100). **A chat SESSION is the first workload in this app that does
not** - six to eight exchanges plus observations exceeds it, and Scratchpad's policy (drop the
oldest observation, then log and give up) is a never-fired safety net in a workflow but the
NORMAL operating condition in chat by turn eight.

So sessions need **compaction, not trimming**: a rolling summary on the CLASSIFIER model
(already resident; the main model would double turn latency), persisted on the session so it is
computed once, and emitted as a VISIBLE step - a model that suddenly forgets should be
explainable from the timeline. Raising `num_ctx` is a non-goal: the cost is process-wide
residency, see [[agent-harness]].

### Gotchas paid for

- **A structural guard derived from a LITERAL is not derived from the enum.**
  `test_step_payload.py` builds `STEP_MODULES` from `STEP_KINDS`, a hand-written dict of sample
  steps per kind. Registering the step serializer satisfied
  `test_every_run_kind_has_a_step_serializer`, while the per-kind parity test and the
  `tool_args`-never-streamed-as-`args` guard **never ran for `chat` at all** - green, vacuous.
  `agent-harness.md`'s claim that "a twelfth workflow is covered the moment its kind exists"
  held for `test_events.py` and the span guards and NOT for this one. The twelfth workflow
  arriving is what tested the claim.
- **Declaring a DRF serializer field is not adding it.** `LLMSettingsSerializer` lists fields in
  `Meta.fields` too; declaring `chat_max_steps` without listing it made DRF raise at
  field-resolution time and every settings endpoint 500'd (32 tests caught it).
- **Check the file's own stated convention before following a plan that touches it.** The plan
  said to document `OLLAMA_CHAT_MAX_STEPS` in `.env.example`; that file says outright the
  `OLLAMA_*` agent caps are deliberately unlisted, and `OLLAMA_REACT_MAX_STEPS` is absent for
  the reason. Writing the deliverable without reading the file was the error.
- **A new kind cannot reuse the legacy name.** `/api/llm/chat/` and `ChatRequestSerializer`
  belong to the old non-harness path, which still serves `useSinglePrompt` - hence slug
  `chat-agent`, `ChatAgentRequestSerializer`, `ChatAgentView`.
- **Two concurrent turns in one session fork the transcript** (B rehydrates without A's reply,
  then both write). Needs a 409 guard, not optimism.
- **The harness streams STEPS, not tokens.** `chat_stream` is the only streaming path in the
  codebase; every driven workflow uses blocking `services.chat`. So moving chat into the
  harness LOSES token-by-token rendering unless `result()` is made to yield deltas - which it
  can, being a generator. Sequencing matters: that lands BEFORE the legacy path is retired, or
  the switch ships a visible downgrade.

### More gotchas, from phase 2 (sessions)

- **Eager Celery makes a fire-and-forget task run INSIDE the request.**
  `CELERY_TASK_ALWAYS_EAGER` is on in tests, so `generate_chat_title.delay(...)` executed
  inline, called the patched `services.chat` and ate the single `side_effect` queued for the
  TURN. The turn died with `generator raised StopIteration` - three frames from the cause, in
  a phase-1 test phase 2 had not touched. Autouse fixture patching `.delay` + a `title_task`
  opt-out marker. **Prod corollary: with no Celery worker, the first turn of every
  conversation pays the title call inline.**
- **A DRF annotation does not exist on a freshly created instance.** `turn_count` /
  `last_message_at` are annotated onto the LIST queryset, so `POST /sessions/` returned a row
  missing the fields every list row has. `SerializerMethodField` preferring the annotation and
  falling back to a query keeps lists free and bare instances correct.
- **`AgentRun.Meta.ordering` is newest-first** - right for a history list, backwards for a
  transcript. Sort explicitly when rendering a conversation.
- **`test_registry`'s frozen route table collects ANY `llm-*-list`/`-detail`**, including
  hand-written non-registry routes. Freezing them too is the right call - it catches a future
  workflow slug colliding with `chat/sessions/`.
- **Derive the turn index in the creator, not the caller.** One indexed query beats a caller
  counting turns, which is how an off-by-one gets written.

### More gotchas, from phase 3 (compaction)

- **A mutation check found a VACUOUS test AND unreachable code that coverage called 100%.**
  `test_summarised_upto_never_regresses` set the marker to 99 and asserted it stayed - which
  made `_verbatim` return nothing, so `compact` returned early and never reached the line the
  test was named for. The same mutation showed the `max()` guarding it was UNREACHABLE (`fold`
  comes from `_verbatim`, which yields only turns at or after the current value). Deleted the
  guard, pinned the contract - the same call issue #6 made on the `if not tail` replan branch.
  **Coverage cannot see this class**: the line was on the happy path, so 100% covered while
  being both unreachable as a guard and untested as a rule. Only mutation finds it.
- **Not everything visible belongs in a step.** Compaction was specced as an `AgentStep` and
  should not be one: `intro()` runs before `drive` stamps orders from 0 (so it collides with
  the first real step), and `STEP_META["chat"]` defines a step as one TOOL CALL. A `compacted`
  count on the event + `ChatSession.summarised_upto` serves the intent BETTER, because
  compaction is a property of the conversation and survives a reload.
- **Housekeeping must never eat the answer.** `_compact_for` catches bare `Exception` on
  purpose: a dead Ollama, a bad row or a policy bug costs the user a summary, not their reply.
- **Summarise on the CLASSIFIER model.** It is already resident, and making a chat turn wait
  on a second main-model call doubles its latency for something the user did not ask for.
  Same reasoning as the title task.

### What the LIVE run found that no unit test could

**Probe the CONFIGURED host, not localhost.** I reported "Ollama unreachable, cannot verify
live" after curling `localhost:11434`. Ollama is on **192.0.2.202** (see
[[ollama-api-reference]]). A whole phase went undemonstrated because of a wrong hostname in a
one-line check.

**A context budget expressed as a SHARE was wrong, and only measurement showed it.**
`HISTORY_SHARE = 0.5` at num_ctx=4096: pad budget 3,072, system prompt (the tool catalogue)
621, history 1,536 -> **915 tokens left for the turn's own work**. Measured observation sizes:
**company_financials 1,181**, sector_analysis 315, list_sectors 131, company_snapshot 72,
company_profile 48, recent_price 25. So one `company_financials` call did not fit: the model
fetched the financials, Scratchpad dropped an observation to stay in budget, and the turn
answered without the data it had just asked for. **No error, no failing test, just a worse
answer** - the same silent class as the num_ctx truncation in [[agent-harness]].
Fix: `TURN_RESERVE = 1400` sized from the measurement, history = whatever remains
(`pad - system_prompt - TURN_RESERVE` = 1,051). DERIVED, not a fraction, because the system
prompt grows with every tool added and a percentage lets it quietly eat the turn's room.

**Measure the tools, not the prose.** Every earlier estimate in this project sized prompts by
the conversation. The dominant term is the TOOL OUTPUT: one financials call is bigger than ten
turns of chat.

**A structural guard on PRODUCERS says nothing about CONSUMERS.** Issue #6 phase 2 renamed
`args` -> `tool_args` on the wire, and `test_step_payload.py` guards every workflow MODULE
against streaming a bare `args`. Nothing guarded the readers: **five printers in
`run_llm_live` had been rendering `{}` for every tool call ever since**, and the dag printer
labelled nodes with the row UUID because `id` changed meaning in the same phase - the exact
defect [[agent-harness]] records for the frontend, sitting unnoticed in a second place. Found
only by writing a sixth printer beside them. `call.get("args")` in the multiagent printer IS
correct (`tool_calls` really is `{"tool","args","observation"}`), so a blind sweep would have
broken it. Now pinned by `TestStepPrintersUseTheSerializerNames`.

**THE pattern of this issue: issue #6 derived the PRODUCER guards from `AgentRun.Kind` and
left every CONSUMER allow-list a hand-written literal.** Three found, all silent:

1. `test_step_payload.STEP_KINDS` - chat's parity test passed VACUOUSLY until added to it.
2. `run_llm_live`'s step printers - five read `args` after the rename to `tool_args`.
3. **`STOPPABLE_RUN_MODELS`** - `chat` was missing, and a workflow omitted from that map is
   silently UNSTOPPABLE: the Stop button posts, gets `Invalid run type or id`, and the run
   carries on. **No test touched that map at all.** Its keys are the registry SLUGS
   (`evaluate`, `plan`, `orchestrate`, `chat-agent`), so it is now derived from
   `registry.WORKFLOWS`.

When adding a workflow, the question is not "does a guard exist" but "is that guard's SEED
derived or typed out". Search for literals keyed by kind or slug.

**`run_id` on the terminal event is too late for an interactive surface.** `_events.succeed`
gives every workflow `run_id` on `result`; for chat that means Stop only works once there is
nothing left to stop. `ChatStrategy.intro` puts `run_id`/`session_id` on `started`.

**Make the live check repeatable the first time.** `manage.py run_llm_live chatagent --smoke`
runs three turns, each proving one thing a unit test cannot (no tool for small talk, a real DB
figure, a pronoun resolved from the transcript), and prints the context budget first - because
the defect it caught was arithmetic, not logic.

### Live behaviour confirmed (2026-09-28, qwen3:8b + qwen2.5:3b, 530 companies)

- conversational turns take NO tool; the difference from ReAct holds in practice
- "AAPL's trailing P/E?" -> `company_snapshot` -> 39.07, from our own DB (the legacy chat
  invented this number)
- a follow-up resolved "that" from the transcript (trailing 39.07 vs forward 35.58)
- compaction fired: 1,370 tokens of history vs 1,051 budget -> folded 8, prompt 1,187/3,072
- **summary fidelity is fine on a 3B model**: six concrete facts in, all six kept out
  (39.07, 2.94, 33.4, AAPL, KO, MSFT). "Keep concrete numbers and tickers" is doing work
- **wart**: titling from the first message gives "Help With What?" when it is a greeting

### More gotchas, from phase 4 (the `/chat` page)

- **A 409 must REMOVE the optimistic turn**, not just surface an error. Leaving it puts a
  message in the transcript that was never sent and that the next turn will not follow on
  from - the screen and the model's memory disagree.
- **A stopped turn stays visible and labelled.** Same reason inverted: the backend DOES
  replay its partial output into the next prompt, so hiding it creates the same disagreement.
- **Persist the session ID, never the transcript.** `AgentRun.query`/`output` ARE the
  messages, so a local copy is a second source of truth that drifts from what the model is
  actually sent. One string under one key needs no `lib/` module - `agentsSession.ts` earns
  one because it holds a multi-field workspace shared across panels.
- **`CASES` in `sseMatchesDetail.test.ts` is a hand-written literal too** (the fourth
  instance of this issue's pattern), but the frontend has no `AgentRun.Kind` to derive from.
  Chat's parity test lives in `useChatAgent.test.ts` because its unit of restore is a SESSION,
  not a run; the shared file carries a pointer so "every workflow" stays honest.
- **`nav.test.ts` freezes the route list** and fails on a new page - same
  freeze-don't-derive discipline as the backend route table. Working as designed.

### More gotchas, from phase 5 (token streaming)

- **THE lesson of this issue, now twice over: a suite cannot tell you what the MODEL will
  do.** Making an answer prose instead of JSON (so it can stream) made the model stop
  re-calling tools and start ESTIMATING figures - wrong in **2 of 3** measured runs, stated
  confidently, no error anywhere, every test green. Found by running it, not by review.
- **Root cause, which predates the phase: `_rehydrate` replays `query`/`output` - the
  conversation as the USER saw it - and NOT the tool observations behind it.** A follow-up
  about a figure the previous turn fetched but did not write out cannot see the number. Under
  JSON the model had to commit to an explicit choice each turn and re-fetched; under prose it
  just starts talking, and talking means guessing.
- **Prompt hardening fixed 1 of 3. That is not a fix.** `CARRY_OBSERVATION_CHARS=600` carries
  the LAST turn's observations forward, truncated, entering the pad as OBSERVATIONS so
  Scratchpad sheds them first and they can never displace the conversation. 5 of 5 after -
  and faster, because it answers instead of re-fetching. Truncation is load-bearing:
  company_financials is ~1,180 tokens and would eat the whole TURN_RESERVE.
- **`perform_streaming` is the shape to copy for "emit while working".** `after` cannot do
  it - by then the work is done and events arrive in a burst. Opt-in via a `BaseStrategy`
  default of None, so a driver change costs the other eleven workflows nothing.
- **One primitive per external call.** `services.chat_tokens` yields raw content;
  `chat_stream` became a thin framing wrapper over it. Two independent Ollama streaming call
  sites is how `_sse` drifted nine ways in the first place.

### More gotchas, from phase 6 (retiring the legacy path)

- **Filtering an error out of a tool's output is not the same as fixing it.** `tsc` aborts on
  a pre-existing `TS5101` deprecation in `tsconfig.app.json`; I grepped that line away, saw
  nothing else and reported "typecheck clean" - while a `{mode === "chat" ? ...}` block still
  referenced a deleted variable. `npm run build` (vite) is the check that actually runs here;
  61 route tests caught it too. **Use `npm run build`, not `npx tsc`, on this repo.**
- **The `vi.mock` of `@tanstack/react-router` is duplicated in ten test files and had
  drifted.** `Sidebar.test.tsx`'s `Link` maps `to` -> `href`; `agents.test.tsx`'s spread props
  onto an `<a>` and dropped the destination, so every link on that page was invisible to
  `getByRole("link")`. Same literal-drift pattern as this issue's backend instances, in the
  test harness this time.
- **A field-by-field parser makes a key removal a no-op migration.** `loadAgentsSession` reads
  named fields, so a pre-#8 payload carrying `mode: "chat"` is simply not read. Pinned by two
  tests, because "happens to work" and "guaranteed to work" look identical until the parser is
  rewritten.
- **Keep a span's name when the function under it is renamed.** `ollama.chat_stream` now lives
  in `chat_tokens`. The name describes the OPERATION, and renaming it would silently empty the
  tracing dashboard panels and Tempo span metrics keyed on it - see [[observability]].

### The workspace switch (post-phase-6)

`components/layout/WorkspaceSwitch.tsx` puts `/agents` and `/chat` one click apart, on both
pages. LINKS, not a mode - the old `ModeToggle` flipped a `useState` inside `/agents`, which
is what made the chat panel a second-class citizen there.

- **Never disabled mid-run.** The old toggle disabled itself while running, correct only when
  leaving meant losing the run. `stream_in_background` makes runs durable and both pages
  reconnect on arrival, so there is nothing to protect against. Pinned by a test.
- **`active` is a PROP, not router state** - each page knows which it is, and the component
  stays testable without mounting a router. `aria-current="page"` so the state is not
  colour-only.
- **Trap**: the AppShell sidebar has its own "Chat" nav link, so an unscoped
  `getByRole("link", { name: "Chat" })` matches TWO elements. Scope to
  `getByRole("navigation", { name: "Workspace" })`.

### The two bugs OPENING THE PAGE found, after all six phases "passed"

**A mocked transport tests the caller, not the contract.** Both of these lived exactly in the
seam the mocks replaced, and both had full test coverage around them.

- **`required=False, default=None` does NOT accept an explicit null.** DRF lets the key be
  OMITTED and rejects `null` with "This field may not be null." `useChatAgent` sends
  `session: null` for the first message of a new conversation, so **every first message 400'd**.
  Invisible because the view tests posted `{"message": "hi"}` and the frontend tests mocked
  `fetch` - nothing put the real payload through the real serializer. The same trap sat on **25
  fields across 12 request serializers**, and `useBrowserAgent` already sends
  `provider`/`max_steps` as `?? null`, so `/browse` had it live. Now a DERIVED invariant
  (`TestOptionalRequestFieldsAcceptNull`), with a guard that the audit examined something.
- **A raw `fetch` bypasses the axios 401 interceptor**, so the SSE paths were the only requests
  in the app that did not silently refresh an expired token - chat broke while everything else
  worked, which is why it read as a chat bug. `refreshAccessToken()` is now exported from
  `api/client.ts` so ONE place knows how to refresh.
- **`readSSE` finds no `data:` lines in a JSON error body**, so it yields zero events and
  returns normally: the turn ends "successfully" with an empty reply and the transcript shows a
  bare "No reply." A 401, a 500 and a dead Ollama were indistinguishable. **Every non-OK
  response must become an exception**, and a stream that ends with no terminal event must say
  so.

### What a real browser session then showed (2026-09-28)

Working: tool use with an expandable disclosure, conversation memory across turns
("what did i ask just then?" -> the previous question), typo tolerance, and a proper refusal
on "what stock should i buy?".

**Two quality problems, both in `tools.py` rather than the agent, both UNFIXED and both wider
than chat** (six workflows plus the AI summary):

- **`aggregate_snapshots` returns an AVG for ratios and the model reasons from it.** Technology
  sector: avg trailing P/E **160.95** vs median 34.61, max 8,404; P/B min -306.86, max 1,832.
  The mean of a ratio over 92 companies is destroyed by outliers, and the model concluded
  "investors are willing to pay a premium" and "NVDA's 28.49 is below the sector average, so
  possibly undervalued" - inferences from a meaningless statistic. This project's own domain
  guidance says peer comparison uses the MEDIAN, and `companies.services` uses the peer median
  deliberately for the AI summary. Either stop returning `avg` for ratios or label it. **Now issue #9**, with the measured
  distortion: the mean trailing P/E is ABOVE the p75, so three quarters of the sector sits
  below its own "average".
- **"Never invent data" covers NUMBERS, so the model invented a RANKING instead**: "companies
  with higher dividend yields, such as MSFT or AVGO", from an observation carrying only market
  cap, P/E and P/B. A prompt rule obeyed literally is a prompt rule too narrow. Widen it to
  comparative claims.

Generalisable: **an agent is only as honest as the statistics its tools hand it.** A tool that
returns a technically-correct but misleading aggregate will get that aggregate reasoned from.

### Phase status

1. **DONE.** `kind="chat"`, `meta_spec`, `registry`, serializers, `chat_agent.ChatStrategy` on
   `drive`, `ChatAgentView`, migration `0039`.
2. **DONE.** `ChatSession` + `AgentRun.session`, session CRUD, `_rehydrate`, 409 guard, title
   task, migration `0040`.
3. **DONE.** `TURN_RESERVE=1400`, `KEEP_VERBATIM=2`, `compact()` on the classifier model,
   `summarised_upto` honoured by `_rehydrate`, never-raising `_compact_for`.
4. **DONE.** `/chat` standalone page: `useChatAgent`, SessionSidebar/Transcript/Composer,
   nav + MSW. Verified end to end over HTTP against live Ollama (turn -> SSE -> sessions ->
   detail -> stop 200).
5. **DONE.** `chat_tokens` + `_events.delta` + `perform_streaming`; answers are prose, tool
   calls are JSON. First token 0.19s vs 1.26s for the full reply. Caused and then fixed the
   invented-figure regression above.
6. **DONE.** Legacy path removed: `ChatPanel`, `useLLMChat`, the `/agents` chat mode,
   `ChatStreamView`, `/api/llm/chat/stream/`, `services.chat_stream`. `/api/llm/chat/` stays
   for `useSinglePrompt`, pinned by a test.

**ALL SIX PHASES DONE and VERIFIED IN THE BROWSER.** Not deployed. Backend 2450 green, frontend 852 green.
Still open: the title wart ("Help With What?" from a greeting - the sidebar falls back for a
BLANK title but not a bad one), native Ollama tool-calling, per-session num_ctx.

Committed and pushed; NOT deployed. Backend 2445 green (`chat_agent.py` 100%, overall 97%); frontend 839 green, build clean.

**Issue #9 (2026-09-28)** fixed both tool-side problems above: no `avg` (median/p25/p75
instead), negative P/E and P/B excluded, and `GROUNDING_RULE` on every catalogue. Live A/B: the
old code says "average" 7x per answer, the new code 0x, and it anchors on the median. BUT it
exposed issue #10: on "is NVDA cheap vs the sector?" the model calls NO tool (8/8, both arms) and
reads NVDA's figures off other rows of the carried observation. A prompt rule did not move it,
so treat it as needing a STRUCTURAL fix. Also: the bare "explose the tech industry" calls no tool
at all (0/10). The original browser session was primed by earlier tool turns, so a live repro
must say "using your tools".

**Issues #10 + #11 (2026-09-29), both FIXED and closed.** #10: the fix is a code PREFETCH
(`named_tickers` -> a `company_snapshot` step before the model's first call; `peer_comparison`
since #13), measured 0/5
misattributed vs 4/5. Prefetch rather than an answer-time gate because the answer STREAMS: by the
time a gap is noticed, the user has read it. Ticker detection must stay case-sensitive, because 15
DB symbols are English words (SO/NOW/ALL/ON/KEY/A...). #11: LLM-facing ratios are `*_pct` in
percent. `aggregate_snapshots` stays in fractions because the AI summary reads it. The live
harness shape (N=5, 3 turns, a scratch script recording tools + every `n%`) is described in
docs/project_docs/chat-agent.md. Still open: the comparison DIRECTION is sometimes backwards (2/5):
issue #13, since FIXED: the prefetch is now `peer_comparison`, which hands over the relation
computed (9/10 backwards -> 0/10). Its v1 gave only P/E and P/B a cheap/expensive reading, and the
model borrowed it for ROE and margins (4/10), so every metric now has its own vocabulary.
**How to apply:** when a tool hands a model computed WORDS, give every field its own. A gap is
filled by analogy from a neighbouring field. And a checker written for the old failure can score
the new one as a pass, so read the answers. The same goes for tests: the first "0% below" test
used a 0.496% gap and let the `< 0.5` mutation survive. Mutation-check every new guard.
Gotcha: the local dev DB is the `stock_market` compose project (`just db-up`, port 5435). A
different project's `backend-db-1` on 5432 can be running and look like it.

Related: [[agent-harness]], [[ollama-api-reference]], [[project_state]]
