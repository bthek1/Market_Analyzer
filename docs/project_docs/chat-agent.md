# Chat Agent - bringing chat into the harness (issue #8)

Status: **all six phases done** (2026-09-28), **verified in the browser** against Ollama on
192.0.2.202 and the dev database. Not deployed.

This document grows one section per phase. It describes the design decisions and the things
that turned out differently from the plan; the plan itself lives in
[issue #8](https://github.com/bthek1/Market_Analyzer/issues/8).

## Why

Chat was the only LLM surface in the app outside the agent harness, and the gap was not
cosmetic. `ChatPanel` -> `useLLMChat` did a raw `fetch` to `/api/llm/chat/stream/` (not even
through the Axios client), and `ChatStreamView` piped `services.chat_stream` straight to the
response. That meant:

- no `AgentRun` / `AgentStep`, so no history endpoint and nothing to restore on reload
- no `stream_in_background`, so a disconnect killed the generation mid-answer
- no Stop button (`StopRunView` works off a run row; there was none)
- no `_events` - the view framed its own `data: {'error': ...}` line
- an orphan `ollama.chat_stream` span with no `agent.run` parent
- **no tools.** `tools.run_tool` had six callers and chat was not one; the payload advertised
  no tools, so the model was never told they existed. Asked for AAPL's P/E, chat invented one
  while the real snapshot sat in our own database.

And because `chat` was not an `AgentRun.Kind`, none of the structural tests that force a
workflow into the harness applied to it. It could not fail the tests that exist to stop
exactly this.

## Shape

```
ChatSession  1 --- *  AgentRun(kind="chat")  1 --- *  AgentStep
 (conversation)          (one turn)                    (one tool call)
```

**A turn is a run.** `AgentRun.query` is the user message and `AgentRun.output` the assistant
reply, so the transcript IS the ordered run list - no separate `Message` model to keep in
sync. `AgentStep` rows under a turn are its tool calls, which is what the UI renders as a
collapsed "used company_snapshot" block.

The per-turn budget bounds **tool calls within one turn**, not the conversation. This keeps
`_runtime.drive`'s contract intact: it still runs a bounded loop to a terminal status and
never suspends waiting on a human. A session open for days is a sequence of short,
individually-terminal runs.

### Why a `ChatSession` model rather than the `AgentRun.parent` chain

`parent` could thread turns together, and the first design sketch did exactly that. It stops
paying the moment sessions become a product object: a session needs a renameable title, a
cheap "list my conversations by recency", one delete that takes the whole thread, and
somewhere to hang the compaction summary. Walking `parent` backwards gives none of those
without an N-query traversal per sidebar row. `parent` stays what it is (route -> chain
lineage); `session` is the conversation grouping.

## The constraint that shapes everything: `num_ctx` is 4096

`Scratchpad` reserves 25% for the response, so the working budget is **~3,000 tokens**. Every
pre-existing workload fits comfortably - the largest real prompt in the app measures ~1,100
tokens (see the num_ctx history in `agent-harness.md`, where shipping 16384 evicted the
classifier from the 12 GB card and had to be reverted).

**A chat session is the first workload that does not fit.** Six to eight exchanges plus tool
observations exceeds 3,000, and `Scratchpad` then drops the oldest observations; once those
are gone it logs and gives up rather than mangling the conversation. In a workflow that
safety net never fires. In chat it becomes the normal operating condition by turn eight.

That is why compaction is its own phase (3) rather than a detail of the sessions phase, and
why "raise `num_ctx`" is an explicit non-goal: it has a measured residency cost that applies
process-wide, not just to chat.

## Phase 1 - the `chat` kind (done)

A tool-using chat turn running through `_runtime.drive`, with no session and no memory of
prior turns. The legacy path is untouched and stays until phase 6, so the app keeps working
while the new one is built beside it.

`chat_agent.py`'s `ChatStrategy` is deliberately ReAct's shape - a bounded
Thought -> Tool -> Observation loop ending in an answer. That is not imitation: the tool loop
is precisely what makes `tools.run_tool` reachable, which is the capability the old path
lacked. The differences are the ones that matter for a conversation:

- **The system prompt permits answering immediately.** ReAct exists to research, so every one
  of its queries wants a tool. Most chat turns want none, and a ReAct-style prompt would have
  the agent fetch a company snapshot to say good morning.
- **Budget 4, not 6.** A turn is interactive; latency is worth more than exhaustiveness.
- **`tools_used` accumulates on the run**, so a UI can show what a turn touched without
  walking its steps.

Endpoint `POST /api/llm/chat-agent/`; history at `chat-agent/history/` and
`chat-agent/<uuid>/` from one `registry` entry.

### Naming forced by the legacy path

`/api/llm/chat/` and `ChatRequestSerializer` belong to the OLD non-harness chat, and
`/api/llm/chat/` still serves `useSinglePrompt`. So the new ones are `chat-agent`,
`ChatAgentRequestSerializer` and `ChatAgentView`. The asymmetry is recorded in `registry.py`
and in the frozen route table so it reads as a decision rather than a slip - the same
treatment as `eval_opt` -> `/evaluate/`.

### What phase 1 got wrong

- **`.env.example`.** The plan said to document `OLLAMA_CHAT_MAX_STEPS` there. The file states
  outright that the `OLLAMA_*` agent caps are deliberately unlisted, and
  `OLLAMA_REACT_MAX_STEPS` is absent for that reason. The deliverable was written without
  checking, and following it would have broken the file's own convention.
- **A declared serializer field is not a serialized field.** `LLMSettingsSerializer` lists its
  fields in `Meta.fields` as well as declaring them; adding `chat_max_steps` to only the
  declaration made DRF raise at field-resolution time and every settings endpoint 500'd. 32
  tests caught it, which is the system working.
- **A structural guard passed vacuously.** See the amendment in `agent-harness.md`:
  `test_step_payload.STEP_KINDS` is a hand-written literal, so registering the step serializer
  satisfied the completeness test while the parity test never ran for `chat` at all.

## Phase 2 - sessions (done)

`ChatSession` + `AgentRun.session` (nullable, CASCADE, `related_name="turns"`), session CRUD
at `/api/llm/chat/sessions/`, and `chat_agent._rehydrate` replaying prior turns oldest-first.
Indexes on `(session, created_at)` for the transcript and `(user, -updated_at)` for the
sidebar.

Three decisions worth keeping:

- **The title is queued on the FIRST turn, not after it.** It depends only on the first user
  message, so waiting for the reply would serialise two things that can overlap. It runs on
  the classifier model (already resident; a four-word summary is not worth a model swap) and
  is fire-and-forget - a blank title is a supported state and the UI falls back to the
  truncated first message.
- **`turn` is derived inside `create_chat_run`**, not passed by the caller. A caller counting
  turns itself is how an off-by-one gets written.
- **A turn that errored without answering still contributes its user message** to the next
  prompt; dropping it makes the model answer a question that appears never to have been
  asked. A `stopped` turn contributes its PARTIAL output, because that is what the user saw.

### The concurrency guard is not optional

Two turns in one session fork the transcript: the second rehydrates without the first's
reply, then both write. The endpoint returns **409** rather than queueing - a client should
not have two composers open, and silently serialising would hide that it does.

### What phase 2 got wrong

- **Eager Celery made the title task eat the turn's own LLM response.**
  `CELERY_TASK_ALWAYS_EAGER` is on in tests, so `.delay()` ran INLINE inside the turn request
  and consumed the single `side_effect` queued for `services.chat`. The turn then failed with
  `generator raised StopIteration`, three frames from the cause, in a phase-1 test phase 2 had
  not touched. Fixed with an autouse fixture plus a `title_task` opt-out marker. The prod
  corollary: **with no Celery worker running, the first turn of every conversation pays the
  title call inline.**
- **A DRF annotation does not exist on a freshly created instance.** `turn_count` and
  `last_message_at` are annotated onto the list queryset, so `POST /sessions/` returned a row
  missing the two fields every list row has. They are `SerializerMethodField`s now, preferring
  the annotation and falling back to a query - annotated lists stay free, bare instances are
  still correct.
- **`AgentRun.Meta.ordering` is newest-first**, which is right for a history list and
  backwards for a transcript. `ChatSessionDetailSerializer` sorts explicitly.
- **The frozen route table catches hand-written routes too.** `test_registry`'s collector
  matches any `llm-*-list`/`llm-*-detail`, and `chat/sessions/` fits that shape without being
  registry-generated. Added to `EXPECTED_ROUTES` rather than narrowing the collector: freezing
  them costs nothing and catches a future workflow slug colliding with them.

## Phase 3 - compaction (done)

The conversation gets whatever is left after the system prompt and the turn's own work:

```
_history_budget() = pad_budget - estimate_tokens(system_prompt) - TURN_RESERVE
                  = 3072      - 621                             - 1400        = 1051
```

`KEEP_VERBATIM = 2` turns are never folded - summarising the exchange the user is replying to
is how an assistant starts answering a question nobody asked.

### Why the budget is derived rather than a share (a live run found this)

The first version was `HISTORY_SHARE = 0.5`, and it was wrong in a way no unit test could see.
At `num_ctx=4096` the pad budget is 3,072 and the system prompt - which carries the whole tool
catalogue - is ~621, so a 50% history share left **915 tokens** for the turn's own work.

Measured against the real tools: **`company_financials` returns 1,181 tokens**,
`sector_analysis` 315, `list_sectors` 131, `company_snapshot` 72, `company_profile` 48,
`recent_price` 25.

So a single `company_financials` call did not fit. The model would fetch the financials,
Scratchpad would drop an observation to stay inside the budget, and the turn would answer
without the data it had just asked for - no error, no failing test, just a worse answer. The
same silent-degradation class as the `num_ctx` truncation in `agent-harness.md`.

`TURN_RESERVE = 1400` is sized from that measurement, and the history budget is what remains.
Derived rather than a percentage because the system prompt grows every time a tool is added,
and a share would let it quietly eat the room the turn needs to think in. Two tests pin it:
one asserting the leftover still exceeds the largest real observation, one asserting the
budget shrinks when the system prompt grows.

When the verbatim tail outgrows that share, `compact()` makes **one call on the classifier
model** folding the oldest un-summarised turns into `ChatSession.summary` and advancing
`summarised_upto`. It is persisted, so later turns reuse it instead of re-summarising the same
history on every message, and `_rehydrate` honours the marker so a folded turn is never also
sent verbatim.

`_compact_for` **never raises**. A dead Ollama, a malformed row, a bug in the policy - all of
it costs the user a summary, never their answer.

### Compaction is visible, but it is not an `AgentStep`

The plan called for a step. Two reasons it is not one:

1. `intro()` runs before `drive`'s loop, which stamps step orders from 0, so a step created
   there collides with the first real step.
2. `STEP_META["chat"]` defines a step as one TOOL CALL. A summarisation is not one, and
   forcing it into that shape muddies the only definition the serializers and the UI have.

Instead compaction reports a `compacted` count on the `started` event and on the run's meta,
backed by `ChatSession.summarised_upto`. That serves the intent better than a step would:
compaction is a property of the CONVERSATION, and the session state survives a reload.

### A mutation check found a vacuous test and an unreachable guard

Three mutations. Disabling the trigger killed 8 tests; ignoring `summarised_upto` killed 4;
**letting `summarised_upto` regress killed none.**

The test set the marker to 99 and asserted it stayed - which made `_verbatim` return nothing,
so `compact` returned early and never reached the line the test was named for. The mutation
also showed the `max()` guarding it was **unreachable**: `fold` comes from `_verbatim`, which
yields only turns at or after the current value, so the new value is always greater.

The `max()` is gone and the contract is pinned instead - the same call issue #6 made when it
deleted the unreachable `if not tail` in the replan path. Two tests now cover it: one driving
three successive compactions and asserting strict advance, one pinning `_verbatim` directly.

**Coverage said nothing about any of this.** The `max()` sat on the happy path, so it was
100% covered while being both unreachable as a guard and untested as a rule.

## Live verification (2026-09-28)

Against qwen3:8b (main) and qwen2.5:3b (classifier) with 530 companies / 19,789 snapshots:

- a conversational turn takes **no tool** - the difference from ReAct holds in practice
- "What is AAPL's trailing P/E right now?" -> `company_snapshot` -> *"39.07"*, read from our
  own database. The legacy chat answered this by inventing a number
- "And how does that compare to its forward P/E?" resolved *that* correctly from the
  transcript -> trailing 39.07 vs forward 35.58
- compaction fired for real: 1,370 tokens of history against the 1,051 budget folded 8 turns,
  leaving a 1,187-token prompt
- **summary fidelity**, the piece flagged as most likely to need tuning: a session carrying
  six concrete facts compacted to four sentences keeping all six (39.07, 2.94, 33.4, AAPL,
  KO, MSFT). The "keep concrete numbers and tickers" instruction survives a 3B model

### Repeating it

```bash
python manage.py run_llm_live chatagent "What is AAPL's trailing P/E?"
python manage.py run_llm_live chatagent "And its forward P/E?" --session <uuid>
python manage.py run_llm_live chatagent --smoke     # the scripted three-turn conversation
```

`--smoke` runs the three turns above, each chosen to prove one thing a unit test cannot, and
prints the context budget first - the one defect a live run caught here was budget arithmetic
that every unit test agreed with.

### A pre-existing bug this surfaced

Writing the chat printer meant reading the six already in `run_llm_live`, and **five had been
broken since issue #6 phase 2**, which renamed `args` to `tool_args` on the wire.
`test_step_payload.py` guards the workflow MODULES against streaming a bare `args`; nothing
guarded the CONSUMERS, so `react`, `plan`, `orchestrate`, `dag` and `autonomous` had been
printing `{}` for every tool call. The dag printer also labelled nodes with the row UUID,
because `id` changed meaning in the same phase - the same defect the frontend hit, in a place
nobody looked. `call.get("args")` in the multiagent printer is correct and untouched.

Now guarded by `TestStepPrintersUseTheSerializerNames`.

### Known wart

Titling from the first message alone yields **"Help With What?"** when the conversation opens
with a greeting - accurate and useless. Phase 4 should not assume the title is meaningful.
Fixes for later: title from the first substantial message, or re-title once at turn 3.

## Backend gaps phase 4 surfaced

Wiring the Stop button and the run-id plumbing turned up two more:

- **`chat` was missing from `STOPPABLE_RUN_MODELS`**, the allow-list behind
  `POST /api/llm/runs/stop/`. A workflow omitted from it is silently **unstoppable**: the
  button posts, gets `Invalid run type or id`, and the run carries on. Nothing tested that map
  at all. Its keys are the registry SLUGS (`evaluate`, `plan`, `orchestrate`, and now
  `chat-agent`), so it is now pinned by a test derived from `registry.WORKFLOWS`.
- **`run_id` arrived too late.** `_events.succeed` adds it to the terminal `result` event for
  every workflow, which is fine for a batch run and useless for chat: Stop would only work
  once there was nothing left to stop. `ChatStrategy.intro` now puts `run_id` and `session_id`
  on `started`.

That makes **three** literals-nothing-checked found on this issue, all the same shape - see
the amendment in `agent-harness.md`. Issue #6 derived the PRODUCER guards from
`AgentRun.Kind` and left every CONSUMER allow-list hand-written.

## Phase 4 - the `/chat` page (done)

`types/chat.ts`, `api/chat.ts`, `hooks/useChatAgent.ts`,
`components/chat/{SessionSidebar,Transcript,Composer}.tsx`, `routes/chat.tsx`, nav + MSW.

Standalone, like `/browse`, and for the same reason: `/agents` compares one-shot workflows
over a single query, and a conversation is not comparable to a one-shot run. It stays out of
`COMPARABLE_TYPES` and `fetchAllRuns()`.

### Decisions

- **Only the session ID is persisted locally.** The transcript is always re-fetched, because
  the server owns it - `AgentRun.query`/`output` ARE the messages. A local copy would be a
  second source of truth drifting from what the model is actually sent. Kept in the hook
  rather than a `lib/chatSession.ts`: one string, one key, one reader.
  `agentsSession.ts` earns a module because it holds a multi-field workspace across panels.
- **A 409 removes the optimistic turn**, it does not just show an error. Leaving it would put
  a message in the transcript that was never sent and that the next turn will not follow on
  from.
- **A stopped turn stays visible and labelled.** The backend replays its partial output into
  the next prompt, so hiding it makes the model's memory and the screen disagree.
- **The compaction summary renders once at the top**, not against the turn that triggered it -
  compaction is a property of the conversation.
- **The parity test lives in `useChatAgent.test.ts`**, not the shared
  `sseMatchesDetail.test.ts`: chat's unit of restore is a SESSION, so the shared harness's
  "select the step list" shape does not fit. Same invariant, mutation-checked against both
  historical shapes (reading `args`; a streamed step never appended). `CASES` in the shared
  file is itself a hand-written literal with no completeness check - the fourth instance of
  this issue's pattern - but the frontend has no enum to derive from, so it carries a pointer
  rather than a fix.

### End-to-end, against the live stack

```
POST /api/llm/chat-agent/ -> 200 ['started','step','step','result']
answer                    : "The dividend yield for KO is 2.41%."
GET  /chat/sessions/      -> 200, turn_count 1
GET  /chat/sessions/<id>/ -> turns [(0, "What is KO's dividend yie", ['company_snapshot'])]
POST /runs/stop/          -> 200      (400 before the STOPPABLE_RUN_MODELS fix)
```

## Phase 5 - token streaming (done)

**Measured live: first token at 0.19s against 1.26s for the whole reply.**

- `services.chat_tokens` is the raw primitive; `chat_stream` is now a thin wrapper that
  frames it, so one place knows how to stream from Ollama rather than two that can drift.
- `_events.delta(text)`, because a workflow may not hand-roll a `data:` line.
- `_runtime.Strategy.perform_streaming` - opt-in, returns a generator that emits events while
  the step works and returns the persist kwargs via `yield from`, mirroring `result`.
  `BaseStrategy` returns None so nothing else changes shape. `after` could not do this: by
  then the work is finished and the events arrive in one burst.

### The protocol changed

An answer is **plain prose**; only a tool call is JSON. Half a JSON object means nothing, so
only prose can be forwarded token by token - and it incidentally kills the wart where the
agent answered "hello" with a JSON envelope. One character decides it
(`looks_like_tool_call`), hence the system prompt forbidding an answer that opens with `{`.
Misjudgement degrades rather than breaks, and a JSON-wrapped answer is still accepted.

### The regression it caused, and the root cause

The phase-4 smoke's third turn ("and how does that compare to its forward P/E?") had answered
correctly by calling the tool again. After the protocol change it answered **33.95 - a
fabricated number** (the real value is 35.58), with no error anywhere.

The root cause predates the phase: **`_rehydrate` replays `query`/`output`, the conversation
as the USER saw it, and NOT the tool observations behind it.** A follow-up about a figure the
previous turn fetched but did not write out cannot see the number. Under the JSON protocol
the model had to commit to an explicit choice each turn and re-fetched; under prose it simply
starts talking, and talking means guessing.

Prompt hardening fixed **1 of 3** runs. Not a fix. `CARRY_OBSERVATION_CHARS = 600` carries the
most recent turn's observations forward, truncated, entering the pad as OBSERVATIONS so
Scratchpad sheds them first and they can never displace the conversation. Truncation is
load-bearing: `company_financials` is ~1,180 tokens and would eat the whole `TURN_RESERVE`,
while `company_snapshot` - the one this bites on - is 72. Only the LAST turn carries data,
because a follow-up is nearly always about what was just looked up.

**5 of 5 correct afterwards**, and it answers directly rather than re-fetching, so it is
faster too.

This is the second time on this issue that something passed every test and failed against the
real model. Four tests now pin that the carried data is present, truncated, droppable and
last-turn-only - but nothing in a suite could have predicted that the model would invent a
P/E.

## Phase 6 - retiring the legacy path (done)

Removed: `ChatPanel.tsx`, `useLLMChat.ts` and their tests; the `mode` toggle on `/agents` and
its two tests; `mode` from `agentsSession`; `ChatStreamView`, the `chat/stream/` route, and
`services.chat_stream`.

Kept: `/api/llm/chat/` (`ChatView`), which still serves `useSinglePrompt` for the Agents
page's `single` type - pinned by a test so the next tidy-up does not take it too.

```
POST /api/llm/chat/stream/  -> 404   (retired)
POST /api/llm/chat-agent/   -> 200, 25 deltas, real reply
POST /api/llm/chat/         -> 200   (still serving useSinglePrompt)
```

### `services.chat_stream` went too, against the plan

Phase 5 had turned it into a thin framing wrapper over `chat_tokens`, so once the view was
gone it was dead code. Its four tests moved to `chat_tokens` rather than being deleted - they
cover `num_ctx` on the streaming payload, keep-alive blanks, a truncated line on a dropped
connection, and connection errors, none of which is about framing.

The span keeps the name **`ollama.chat_stream`** although the function is now `chat_tokens`:
it names the operation, and renaming it would silently empty the tracing dashboard panels and
Tempo span metrics that key on it.

### What phase 6 got wrong

- **I filtered out the error that was preventing my own check from running.** `tsc` aborts on
  a pre-existing `TS5101` deprecation in `tsconfig.app.json`; I grepped that line out of the
  output, saw nothing else, and called the typecheck clean while a `{mode === "chat" ? ...}`
  block still referenced a deleted variable. `npm run build` caught it, as did 61 route tests.
  Filtering an error out of a tool's output is not the same as fixing it.
- **A duplicated test shim had drifted.** Ten test files carry their own `vi.mock` of
  `@tanstack/react-router`. `Sidebar.test.tsx`'s `Link` maps `to` -> `href`; `agents.test.tsx`'s
  spread props onto an `<a>` and dropped the destination, so every link on that page was
  invisible to `getByRole("link")`. Aligned. The same literal-drift pattern as this issue's
  backend instances, in the test harness this time.
- **The stale-key migration needed no code**, because `loadAgentsSession` parses field by
  field and an unknown key is never read. Two tests pin it: "happens to work" and "guaranteed
  to work" look identical until someone rewrites the parser.

## The workspace switch

`/agents` and `/chat` are separate routes because they have genuinely different shapes - a
session sidebar and a transcript against a workflow grid and run panels - but they are one
click apart via `components/layout/WorkspaceSwitch.tsx`, rendered on both.

Links, not a mode: the old `ModeToggle` swapped a `useState` inside `/agents`, which is what
made the chat panel a second-class citizen there in the first place.

**Never disabled while something is running.** The old mode toggle disabled itself during a
run, which made sense when leaving meant losing it. It no longer does: `stream_in_background`
drives a run on a daemon thread and both pages reconnect to an unfinished one on arrival, so
navigating away costs nothing.

`active` is passed in rather than read from the router - each page knows which one it is, and
it keeps the component testable without mounting a router. The current entry carries
`aria-current="page"`, so the state is not colour-only.

Note for tests: the AppShell sidebar carries its own "Chat" nav link, so an unscoped
`getByRole("link", { name: "Chat" })` matches two elements. Scope to
`getByRole("navigation", { name: "Workspace" })`.

## Two bugs that only the browser found (2026-09-28)

Reported as "No reply." against every message, then "The server rejected the message
(HTTP 400)" once the first fix made failures visible. Both had full test coverage around them.

### 1. A failed request was indistinguishable from an empty reply

The SSE helpers use raw `fetch`, because axios cannot stream a response body. Two consequences
neither of which was handled:

- **They never reach the axios 401 interceptor**, so chat was the only surface in the app that
  did NOT silently refresh an expired access token. Everything else kept working, which is why
  it looked like a chat bug.
- **`readSSE` finds no `data:` lines in a JSON error body**, so it yielded zero events and
  returned normally. The hook marked the turn finished with an empty reply and the transcript
  rendered its last-resort "No reply." A 401, a 500 and a dead Ollama all looked identical.

Fixes: `refreshAccessToken()` exported from `api/client.ts` (one place that knows how to
refresh, now reachable from the streaming paths); `streamChatTurn` retries once on 401 and
**throws on any non-OK response**; and the hook reports a stream that ends without a
`result`/`stopped`/`error`. `api/browser.ts` had the identical gap and was fixed with it.

### 2. `required=False, default=None` does not accept an explicit null

DRF lets such a field be OMITTED; it rejects `null` with "This field may not be null."
`useChatAgent` sends `session: null` for the first message of a new conversation - exactly what
`ChatTurnRequest` declares - so **every first message 400'd**.

It was invisible because the backend view tests posted only the keys they cared about
(`{"message": "hi"}`) and the frontend tests mocked `fetch`, so nothing ever put the real
payload through the real serializer.

An audit found the same trap on **25 fields across 12 request serializers**, and
`useBrowserAgent` already sends `provider`/`max_steps` as `?? null`, so `/browse` had it live
too. All widened with `allow_null=True`, and pinned by a DERIVED invariant
(`TestOptionalRequestFieldsAcceptNull`) rather than another example - plus a view test posting
the exact body the client builds.

**The lesson worth keeping**: a mocked transport tests the caller, not the contract. Both of
these lived precisely in the seam the mocks replaced.

## Verified in the browser (2026-09-28)

A real session, end to end, after the two bugs above were fixed:

- **Tool use with disclosure**: "whats the time?" -> `used 1 tool` ->
  `current_time({"timezone":"America/New_York"})`, expandable to the thought and the raw
  observation, then the prose answer.
- **Conversation memory**: "what did i ask just then?" -> *"You asked, 'whats the time?'"* -
  rehydration working from `query`/`output`, not from anything client-side.
- **Typo tolerance**: "explose the tech industry" -> `used 2 tools` -> sector aggregates.
- **Refusal**: "what stock should i buy?" -> declines a recommendation and offers analysis
  instead, which is the behaviour the system prompt asks for.

### Two quality problems this exposed, both in the TOOLS rather than the agent

Neither is a chat bug. Both are now fixed by
[issue #9](https://github.com/bthek1/Market_Analyzer/issues/9); see "Issue #9: the fix, measured"
below. They affected six workflows plus the AI summary, not just chat.

**1. `aggregate_snapshots` hands the model a mean that should not exist.** The Technology
sector came back with `Trailing P/E: Average 160.95, Median 34.61, Max 8,404.33` and
`Price-to-Book: Min -306.86, Max 1,832.83`. The mean of a ratio across 92 companies is
destroyed by a handful of outliers, and the model duly reasoned *"the high average trailing P/E
(160.95) suggests investors are willing to pay a premium"* and then *"NVDA's 28.49 is lower
than the sector average, suggesting it might be undervalued"* - a conclusion drawn from a
meaningless statistic. `CLAUDE.md`'s own domain guidance says peer comparison uses the MEDIAN,
and `companies.services` deliberately uses the peer median for the AI summary. The tool should
either stop returning `avg` for ratios, or label it as unreliable so the model stops reasoning
from it.

**2. The model ranked companies on data it had not been given.** It suggested *"companies with
higher dividend yields, such as MSFT or AVGO"* when the only per-company fields in the
observation were market cap, trailing P/E and price-to-book. The system prompt forbids stating
a NUMBER it was not given, and it obeyed that literally - it stated a RANKING instead. The rule
needs widening to cover comparative claims, not just figures.

## Left undone, deliberately

- **Lowercase tickers and company names.** "is nvda cheap?" and "is nvidia cheap?" get no
  prefetch (see #10 below). Resolving company names would close both.
- **The AI summary has not been measured for backwards comparisons.** It hands the model two
  numbers per peer metric, the same shape #13 fixed for chat. `tools.compare_metric` is the
  ready-made fix if it shows up there.
- **The title wart.** A conversation opening with a greeting is titled "Help With What?" -
  accurate and useless. The sidebar falls back to "Untitled conversation" for a BLANK title,
  but there is no fallback for a bad one. Fixes for later: title from the first substantial
  message, or re-title once at turn 3.
- **Native Ollama tool-calling.** `services.chat` supports `format` but not `tools`, and it is
  shared by every workflow, so it needs its own issue and its own blast radius.
- **A per-session `num_ctx` override.** Needs a residency re-measurement on the live host
  first - see the num_ctx history in `agent-harness.md`.
- **Deployment.** Committed, not deployed.


## Issue #9: the fix, measured (2026-09-28)

What changed is described in `CLAUDE.md` (the `tools.py` bullet) and `ai-summary-pipeline.md`.
In short: no mean, `median/p25/p75/min/max/n` instead; negative P/E and P/B are excluded and
counted; a `how_to_read` legend; and `GROUNDING_RULE` on every tool catalogue. This section
records what the live model did with it. Everything ran on `qwen3:8b` at `num_ctx=4096` against
the local DB.

The harness patched the OLD behaviour back in for a baseline arm: the old `_stats` with `avg`, no
legend, the old tool description, and the old prompt rule. Both arms saw the same data and the
same model.

**The exact session from issue #8 does not reproduce on its own.** "explose the tech industry"
called no tool in 0/5 runs under the new prompt and 0/5 under the old prompt. It answers from
general knowledge. The browser session that produced the original quotes had earlier tool-using
turns, which evidently primed it. So the prompt change did not suppress tool use; the bare
message never triggered it. The measured session therefore opens with "explore the Technology
sector valuations using your tools".

| turn | old (`avg` present) | new |
|---|---|---|
| 1. explore the sector | "average" 7x per answer, 4/4 runs | 0 mentions, 4/4 anchor on median + p25/p75 |
| 2. is NVDA cheap vs the sector? | reasons from the average in 3/4; run 2 calls NVDA "undervalued" because P/B 23.73 < avg 42.10 | 0/4 use a mean; all compare against the median |
| 3. so what should i buy? | refuses, 4/4, no ranking | refuses, 4/4, no ranking |

So the thing the issue set out to fix is fixed: the model stopped reasoning from the mean
**because it no longer has one**, and it anchors on the median without being told twice.

**A negative result, recorded as the issue asked: turn 2 is still wrong, in BOTH arms.** In 8/8
runs the model called **no tool** for "is NVDA cheap?". It read NVDA's "figures" off OTHER rows
of the carried observation: AVGO's trailing P/E 45.06 became NVDA's forward P/E (6 of 8 runs),
and the sector's MAX margin 72.95% became NVDA's margin. One run invented every number. The widened
grounding rule did not move this. The model believes it WAS given those figures, because they sit
in the transcript beside NVDA's name. Tightening the prompt until one transcript looks right
is exactly what the issue warned against, so this is now
[issue #10](https://github.com/bthek1/Market_Analyzer/issues/10), with a structural direction to
evaluate: force a `company_snapshot` when a named ticker has no observation in the turn.

**A second, smaller finding:** the observation's ratios are FRACTIONS and the model scales them
inconsistently within one answer. `profit_margins.min=-2.301` became "-230.10%" (right) while
`return_on_equity.min=-2.4003` became "-2.40%" (wrong, 2 of 4 runs). That is
[issue #11](https://github.com/bthek1/Market_Analyzer/issues/11).

**Tests** added for it: `test_react_tools.py` (the distribution shape, n=1/n=2, the outlier
property, negatives per valuation ratio, all-negative -> None, the legend placed LAST, and a
worst-case observation pinned under `TURN_RESERVE // 2`), `test_grounding_rule.py` (structural,
see `agent-harness.md`), and `test_chat_agent.py::TestGroundingPrompt`. The live A/B harness is
NOT a test. It needs Ollama, and prompt effect is not deterministic. Its method is recorded above so
issue #10 can reuse it.

**Cost:** the `sector_analysis` observation went from 315 to 441 tokens, still well under
`company_financials` (~1,181), which is what `TURN_RESERVE` is sized against. The chat system
prompt is now 755 tokens, leaving a history budget of 917 at `num_ctx=4096`.


## Issues #10 and #11: named tickers and percent units, measured (2026-09-29)

Both came out of issue #9's live A/B and read the same observation, so one harness measured
both. It was a scratch script, not a test: the #9 session shape, `qwen3:8b` at `num_ctx=4096`,
the local DB, N=5 fresh sessions per arm, and three turns each ("explore the Technology sector
valuations using your tools" / "is NVDA cheap compared to the sector?" / "so what should i buy?").
Per turn it recorded the tools called, the answer, and every `n%` the answer stated.

### #10: the model read NVDA's figures off other rows

| turn 2, "is NVDA cheap?" | before | after |
|---|---|---|
| NVDA's own data fetched this turn | 0/5 | 5/5 |
| a figure taken from another row or invented | 4/5 (forward P/E "45.1" = AVGO's trailing P/E; one invented D/E 0.33) | 0/5 |
| forward P/E stated | 45.1 in 4/5 (wrong) | 14.35 or 14.4 in 5/5 (right) |

**The fix is code, not prompt.** `chat_agent.named_tickers` finds tickers the user NAMED, and
`ChatStrategy` runs `company_snapshot` for each one as an ordinary step BEFORE the model's first
call. (Since issue #13 the prefetch runs `peer_comparison` instead, a superset; see below.) The pad receives an assistant tool call and then its observation, the same shape as a lookup
the model asked for itself. The step persists, streams, appears in the UI's tool disclosure and
carries into the next turn, all without special cases. `perform_streaming` returns None for it,
so the driver falls through to `perform`.

Decisions:

- **Prefetch, not an answer-time gate.** The alternative was to notice an answer about a ticker
  with no lookup behind it and force a retry. A chat answer streams token by token, though, so by
  the time the gap is detectable the user has already read the wrong number.
- **Only capitalised words or a `$` prefix count.** 15 symbols in the local DB are everyday words:
  `A ALL ARE BE DE FAST HAS IT KEY LOW NOW ON SO TECH WELL`. Matching case-insensitively would
  prefetch Southern Co and ServiceNow for "so what should i buy now?". Single letters never count.
  A message written entirely in capitals is shouting, and there only `$` counts. `IT`, `DE` and
  `TECH` are common capitalised domain words ("the IT sector"), so they need `$` everywhere.
  Every candidate must exist in `Company`, which is what keeps `EPS`/`USA` out.
- **Bounded:** `MAX_PREFETCH=2`, and never the whole budget when it is >1, so the model always
  keeps a call. At `max_steps=1` the single step is the prefetch, followed by the forced answer.
- **Known gap:** lowercase "is nvda cheap?" is not detected. The grounding prompt still applies
  there, and that is exactly the mechanism shown not to work. Resolving company NAMES ("nvidia")
  would close the gap; it is not built.

### #11: fractions misread as percent

The observation now carries `return_on_equity_pct`, `profit_margins_pct` and
`dividend_yield_pct` in PERCENT, with the bare fraction names gone. Three representations were
considered:

| option | why not / why |
|---|---|
| a `units` map beside the numbers | the carried observation is truncated at 600 chars, and a map at the end is lost first |
| percent STRINGS ("23.26%") | loses the number for `plan_exec`/`dag` downstream steps |
| **`*_pct` name, percent number** | the unit is in the one place truncation cannot separate from the value |

Conversion happens at the LLM boundary only: `chain.snapshot_metrics` (whose two callers both
serialise into a prompt) and `tools._agent_units` for the aggregates. `aggregate_snapshots`
still returns fractions because it is also the AI summary's peer benchmark, whose formatter
renders its own percents. Converting there would print 2,326%. D/E stays a multiple.

**Cost (phase 1):** the live `sector_analysis` observation grows from 441 to 463 tokens,
`company_snapshot` from 71 to 72, and the system prompt from 755 to 764. The history budget
drops from 917 to 908, and everything stays far inside `TURN_RESERVE=1400`.

**Live (phase 3):** before the change, 1/5 runs stated the ROE minimum as "-2.40%" (the true
value is -240.03%). After it, 0 misreads across every percent stated in 5 runs. That includes
"-240.03%" and "-230.10%" in the run that quoted the extremes, and NVDA's 63.66% margin and
117.21% ROE in turn 2. At this error rate N=5 is weak evidence on its own. The stronger argument
is structural: no conversion is left for the model to do.

### Tests

- `test_chat_agent.py::TestNamedTickers` covers the detector: capitalised symbols, order and
  dedupe, the limit, lowercase words never counting, `$` in any case, the ambiguous domain words,
  shouting, single letters, unknown caps words and dotted share classes.
- `TestPrefetch` covers the lookup happening before the first model call and the model seeing
  its figures. It checks the step is persisted and carried forward, the model keeps at least one
  call, a budget of one ends in the forced answer, and there is no prefetch without a named ticker.
  It also checks the model can still call a tool afterwards, a ticker with no snapshot becomes an
  observation rather than a crash, two tickers are fetched in order, the carried slice keeps its
  `_pct` names within 600 chars, and the thought names the ticker.
- `test_react_tools.py::TestPercentUnits` pins the rendered units per field, including the exact
  misread value, alongside the untouched multiples and the unscaled `n`. It adds a check derived
  from `PERCENT_FIELDS` across all three tools, and pins that the summary benchmark still gets
  fractions.
- `test_chain.py::TestResearchTickers` covers chain's copy. `research_tickers` is patched out in
  every router test, and yet its output is written straight into a prompt.
- Mutation-checked: removing the scaling, bypassing `_agent_units`, disabling the prefetch,
  letting it take the whole budget and dropping the shouting rule each fail at least one test.

### Found, not fixed at the time

With every figure correct, 2/5 runs still stated the relation backwards: "28.49 is slightly
**above** the sector median of 34.30". That became
[issue #13](https://github.com/bthek1/Market_Analyzer/issues/13), fixed below.


## Issue #13: the comparison direction, computed (2026-09-29)

After #10 every figure was right, but the model still got the RELATION between them wrong: "NVDA's
trailing P/E of 28.5 is slightly above the sector median of 34.30", often followed by "indicating
it is cheap". The earlier N=5 said 2/5. **A proper N=10 baseline said 9/10**, always that same
sentence. Comparing two floats is arithmetic, and #9 and #10 had both shown that a prompt rule does
not move this model. So the relation is now computed in code.

**`tools.peer_comparison(symbol, scope?)`** returns, per metric (P/E, forward P/E, P/B, ROE,
margins, dividend yield, D/E), the company's value, the peer median, `vs_median` ("18% below"), a
quartile `band` and a `reading`. The maths is the pure `compare_metric`. The peer group is
`tools.peer_group`: the industry, else the sector below `MIN_PEERS=3`, with the company always
excluded from its own median. It is the AI summary's rule, and the summary now delegates to it. A
negative P/E or P/B gets no comparison, as in the summary. The valuation ratios come first, so
chat's 600-char carry keeps them. The tool costs 410 tokens on live data. Because it is a superset
of `company_snapshot` (market cap and EPS ride along after the comparisons), it replaced the
snapshot as #10's prefetch. `comparison_scope` scopes the prefetch to the group the user NAMED.
That matters: NVDA is 18% below its SECTOR's median P/E and 42% below its INDUSTRY's.

**The first version introduced a regression, found only by reading the answers.** Only P/E and P/B
carried a `reading` ("cheaper/more expensive than the typical peer"). ROE and margins shared P/B's
band, "top quarter", and the model borrowed P/B's words for them: "more expensive than the typical
peer based on price-to-book, **return on equity, and profit margins**" (4/10), and in one run
"overvalued in terms of ... profitability metrics". A fifth run called a yield 60% BELOW the median
"significantly higher". The number-pair direction checker scored v1 perfect, because the answers
no longer paired two numbers at all. So now EVERY metric has a reading in its own vocabulary
(`METRIC_READINGS`). P/E and P/B say cheap/expensive, ROE and margins say "more/less profitable
... (not a price measure)", the yield says higher/lower, and D/E says more/less leveraged.

| turn 2, N=10 each | baseline | v1: reading on P/E, P/B | v2: reading on every metric |
|---|---|---|---|
| comparison stated backwards | 9/10 | 0/10 | 0/10 |
| ROE/margins called expensive/overvalued | 0/10 | 4/10 | 0/10 |
| other direction errors | - | 1/10 (yield "higher") | 0/10 |
| turn 3 still refuses to recommend | 10/10 | 10/10 | 10/10 |

The answers now copy the computed words ("cheaper than the typical peer based on its trailing P/E
and forward P/E ... more expensive ... based on its price-to-book ... more profitable ... based on
return on equity and profit margins"). They are right in 10/10, though they read more mechanically.

**Method.** The harness is the #10 one plus two scratch checkers:

- `direction.py`: for each sentence stating NVDA's value and a median for the same metric, it
  takes the first direction word after the company's number and compares it to the real sign. It
  matched the hand count on the earlier N=5 exactly.
- `misread.py`: flags a valuation word (expensive/overvalued/premium) in a sentence about
  profitability, and every flag is then read by hand. In v2 all three flags were correct
  sentences that named both ("more expensive ... price-to-book, and more profitable ... return on
  equity").

**Lesson worth keeping:** a checker built for the old failure can score a new one as a pass. v1
looked perfect to `direction.py`, and only reading all ten answers found the regression.

**Tests:**

- `test_react_tools.py::TestCompareMetric` pins the exact strings the model copies: the live
  28.49-vs-34.30 case, every band edge, equality, a zero median, and percent fields in percent.
  Every metric must have a distinct reading both ways, only valuation ratios may speak of price,
  and the profitability readings disclaim price. It also pins the dividend-yield misread case and
  the negative-ratio rule.
- `TestPeerComparisonTool` covers the industry default, the company excluded from its own median,
  explicit and too-small scopes, the sector fallback, `_pct` names, key order, errors, the token
  ceiling (two prefetches within half of `TURN_RESERVE`) and that the summary picks the same group.
- `test_chat_agent.py::TestComparisonScope` covers the scope detection.
- `test_chat_agent.py::TestPrefetchWithAPeerGroup` covers the prefetch against a real peer group.
  Every other prefetch test uses companies with no sector, so it only reached the no-benchmark
  branch. It checks the relation handed over, the user's scope word changing the group, and the
  600-char carry keeping BOTH P/E relations. That last point is what the metric order exists for,
  and moving `forward_pe` last fails it.
- `test_multiagent.py::TestResearcherAllowList` derives the Researcher's tool list from `TOOLS`.
  `peer_comparison` had to be added to the literal by hand, and a forgotten tool would otherwise
  be silently unreachable.
- **"under 1% below", never "0% below".** A sub-1% gap used to render as "0% below", which
  contradicts itself, and the model copies these strings verbatim. The cut is `< 1` rather than
  `< 0.5` because `format()` rounds half to EVEN, so an exact 0.5% gap still printed "0%". The
  first test for this used 34.47 vs 34.30, which is a 0.496% gap, and the `< 0.5` mutation SURVIVED
  it. The test now uses median 100 vs 100.5, where the float arithmetic is exact.
- Mutation-checked: flipping the direction, a reading that is always "expensive", a band edge off
  by one, the company left in its own median, negatives compared, the prefetch reverted to the
  snapshot, the scope ignored and the valuation-only reading each fail at least one test.

