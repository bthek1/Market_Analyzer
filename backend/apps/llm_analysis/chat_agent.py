"""Conversational chat agent (issue #8 phase 1).

Chat was the one LLM surface outside the harness: a raw ``fetch`` to ``/api/llm/chat/stream/``
piped straight to Ollama, with no ``AgentRun``, no history, no Stop, no durability - and no
access to ``tools.py``, because nothing advertised the tools and there was no loop to run one
in. This module makes a chat TURN an ordinary driven workflow.

The shape is deliberately ReAct's: a bounded Thought -> Tool -> Observation loop ending in an
answer. That is not imitation for its own sake - the tool loop is precisely what makes
``tools.run_tool`` reachable from chat, which is the capability the old path lacked. The
differences from ``react.py`` are the ones that matter for a conversation:

* The system prompt permits answering IMMEDIATELY. ReAct exists to research, so every one of
  its queries wants a tool; most chat turns ("hello", "what did you just say?") want none, and
  a prompt that pushes toward tool use would make the agent fetch a company snapshot to say
  good morning.
* The budget is per TURN, not per conversation - four tool calls, against ReAct's six. A turn
  is interactive, so latency is worth more than exhaustiveness.
* ``tools_used`` accumulates on the run, so the UI can show what a turn touched without
  walking its steps.

A turn's memory of the conversation comes from ``_rehydrate``: the prior turns of its
``ChatSession``, replayed into the scratchpad oldest-first. That is cheap because a turn's
``query``/``output`` ARE the transcript - there is nothing to reconstruct.

A long session does NOT go in verbatim. At num_ctx=4096 the Scratchpad budget is ~3,000
tokens, and a chat session is the first workload in this app that exceeds it - every other
prompt here peaks around 1,100. Worse, Scratchpad's trim policy cannot help: it drops the
oldest tool OBSERVATION, and a transcript is user/assistant entries, so it would reach
"nothing droppable left", log, and hand Ollama an oversized prompt to truncate silently.

So the conversation is COMPACTED instead: the oldest turns are folded into a rolling
``ChatSession.summary`` and the recent ones stay verbatim. See
docs/project_docs/chat-agent.md.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from . import tools
from ._context import RESPONSE_RESERVE, Scratchpad, estimate_tokens
from ._events import event
from ._json import parse_json_object
from ._runtime import AbortedError, BaseStrategy, Outcome, StepSpec, drive

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Generator

    from .models import AgentRun


def _system_prompt() -> str:
    return (
        "You are a helpful financial research assistant having a conversation with a user. "
        "You have access to tools that read this application's own stock market database.\n\n"
        "To ANSWER the user, just write the answer as ordinary text. No JSON, no wrapper - "
        "write it exactly as you want the user to read it, in markdown.\n"
        "To LOOK SOMETHING UP first, respond with ONLY a single JSON object and nothing else:\n"
        '  {"thought": "<your reasoning>", "tool": "<tool_name>", "args": {<arguments>}}\n\n'
        "Available tools:\n" + tools.tool_catalogue() + "\n\n"
        "Rules: call one tool at a time and use the observation returned to you. Do NOT call a "
        "tool for small talk, for a question about the conversation itself, or for anything you "
        "can already answer - answer directly instead. Tickers are uppercase symbols. Never "
        "begin an answer with a { character.\n"
        "NEVER state a number, ranking or comparison you were not given. You can see the TEXT "
        "of earlier messages in this conversation, but NOT the tool results behind them - so if "
        "the user asks about a figure that is not written out in the conversation above, you do "
        "not have it. Call the tool again. Estimating or recalling a figure is the worst thing "
        "you can do here."
    )


NUDGE = (
    "That looked like a tool call but was not valid JSON. Either answer the user in plain "
    'text, or respond with ONLY {"thought": ..., "tool": ..., "args": {...}}.'
)

FORCE_ANSWER = (
    "You have used all your tool calls for this turn. Answer the user NOW with what you have, "
    "in plain text. Do not call any more tools."
)


def looks_like_tool_call(text: str) -> bool:
    """Whether a partial response is opening a JSON tool call rather than an answer.

    The whole streaming design rests on this: an answer is prose, so it can be forwarded to
    the user token by token, while a tool call is JSON that means nothing until it is
    complete. One character decides it, which is why the system prompt forbids opening an
    answer with ``{``.

    A misjudgement degrades rather than breaks: prose mistaken for JSON is simply buffered
    and delivered whole (what every other workflow does anyway), and JSON mistaken for prose
    is streamed as text and then parsed from the same buffer regardless.
    """
    stripped = text.lstrip()
    return stripped.startswith("{") or stripped.startswith("```")


def parse_chat_output(raw: str) -> dict:
    """Tolerantly parse one chat turn into a dict. Raises ValueError on unrecoverable output.

    Thin wrapper over the shared ``parse_json_object`` helper, as in ``react``.
    """
    return parse_json_object(raw)


#: Tokens held back for the turn's OWN work: the current message, the model's JSON turns,
#: and above all its tool observations.
#:
#: MEASURED against the live tools rather than guessed, because the first version of this
#: was a flat 50% share and it was wrong. Observation sizes: company_financials **1,181**
#: tokens, sector_analysis 315, list_sectors 131, company_snapshot 72, company_profile 48,
#: recent_price 25. At num_ctx=4096 the pad budget is 3,072 and the system prompt (which
#: carries the whole tool catalogue) is ~620, so a 50% history share left 915 - LESS than a
#: single company_financials call. The model would fetch the financials and Scratchpad would
#: drop an observation to stay in budget, so the turn answered without the data it had just
#: asked for. Silent, and invisible to every test that does not measure the real tools.
TURN_RESERVE = 1400

#: Turns always kept verbatim, however long they are. Summarising the exchange the user is
#: replying to is how an assistant starts answering a question nobody asked.
KEEP_VERBATIM = 2

#: Characters of each tool observation carried into the NEXT turn's prompt, per tool.
#:
#: Rehydration replays `query`/`output`, which is the conversation as the user saw it - and
#: NOT the tool results behind it. That gap is invisible until a follow-up asks about a
#: figure the previous turn fetched but did not write out ("and its forward P/E?"): the
#: model cannot see the number, and rather than calling the tool again it ESTIMATES one.
#: Measured on qwen3:8b, that happened in 2 of 3 runs, giving a confident wrong answer with
#: no error anywhere. Hardening the prompt alone fixed 1 of 3, which is not a fix.
#:
#: So the most recent turn's observations ride along, truncated. Truncation matters: a
#: `company_financials` observation is ~1,180 tokens and would eat the turn's whole reserve
#: (see TURN_RESERVE), while a `company_snapshot` - the one this actually bites on - is 72.
#: They enter the pad as OBSERVATIONS, so Scratchpad drops them first if it must.
CARRY_OBSERVATION_CHARS = 600

#: Most tickers fetched up front for one message (issue #10). Two covers "is X cheap?" and
#: "X vs Y"; beyond that the model can still call the tool itself.
MAX_PREFETCH = 2

#: Real symbols that are also words people write in capitals in THIS domain ("the IT
#: sector", "D/E" typed as "DE"). They are prefetched only when written with a ``$``.
#: Everyday caps words that are also tickers (ALL, NOW, ON, SO, KEY...) are handled by the
#: shouting rule in ``named_tickers`` instead of being listed here.
AMBIGUOUS_TICKERS = frozenset({"IT", "DE", "TECH"})

_TICKER_TOKEN = re.compile(r"(?<![\w$])(\$?)([A-Za-z]{1,5}(?:[.\-][A-Za-z]{1,2})?)(?![\w])")


def named_tickers(text: str, limit: int = MAX_PREFETCH) -> list[str]:
    """Tickers the user NAMED in ``text``, as stored symbols, in order of mention.

    Candidates: ``$nvda`` in any case, or a word written in capitals (NVDA, BRK.B) of at
    least two letters. Lowercase words are never candidates - "so", "now", "all", "on" and
    "key" are all real symbols. A message written ENTIRELY in capitals is shouting, not
    naming, so there only ``$``-prefixed words count. Every candidate must exist in the
    Company table, which is what keeps "USA" or "EPS" out.
    """
    from apps.companies.models import Company

    shouting = not any(ch.islower() for ch in text)
    candidates: list[str] = []
    for dollar, word in _TICKER_TOKEN.findall(text):
        symbol = word.upper().replace(".", "-")
        named = word == word.upper() and len(word) >= 2 and symbol not in AMBIGUOUS_TICKERS
        if not dollar and (shouting or not named):
            continue
        if symbol not in candidates:
            candidates.append(symbol)
    if not candidates:
        return []
    known = set(Company.objects.filter(symbol__in=candidates).values_list("symbol", flat=True))
    return [s for s in candidates if s in known][:limit]


#: What the prefetch runs for a named ticker.
PREFETCH_TOOL = "peer_comparison"

_SCOPE_WORD = re.compile(r"\b(sector|industr)", re.IGNORECASE)


def comparison_scope(text: str) -> str | None:
    """'sector' or 'industry' when the user said which, else None (the tool's default).

    It matters more than it looks: NVDA is 18% BELOW the Technology sector's median P/E and
    42% below Semiconductors', so answering "vs the sector" from the industry group gives
    right numbers for a question nobody asked. The first word mentioned wins.
    """
    match = _SCOPE_WORD.search(text)
    if match is None:
        return None
    return "sector" if match.group(1).lower() == "sector" else "industry"


SUMMARY_PROMPT = (
    "Below is the earlier part of a conversation between a user and a financial research "
    "assistant, and optionally a summary of what came before it. Write a single compact "
    "summary of the WHOLE thing: what the user is trying to find out, what has been "
    "established, and any figures already quoted. Keep concrete numbers and tickers - they "
    "are the part that cannot be recovered. Aim for under 150 words. Reply with the summary "
    "and nothing else.\n\n"
)


def _prior_turns(run: AgentRun) -> list[AgentRun]:
    """This run's session's earlier turns, oldest first. Empty when there is no session."""
    if run.session_id is None:
        return []
    return list(
        run.session.turns.filter(kind="chat", created_at__lt=run.created_at)
        .exclude(pk=run.pk)
        .order_by("created_at")
    )


def _turn_text(turn: AgentRun) -> str:
    return f"User: {turn.query}\nAssistant: {turn.output}"


def _history_budget() -> int:
    """What the CONVERSATION may occupy, after the system prompt and the turn's own work.

    Derived rather than a fraction: the system prompt grows every time a tool is added, and
    a share-of-the-window would let it quietly eat the room the turn needs to think in.
    """
    from .config import get_llm_config

    pad = int(get_llm_config().num_ctx * (1 - RESPONSE_RESERVE))
    return max(0, pad - estimate_tokens(_system_prompt()) - TURN_RESERVE)


def _verbatim(session, turns: list[AgentRun]) -> list[AgentRun]:
    """The tail of ``turns`` that has not been folded into ``session.summary``."""
    return [t for t in turns if t.meta.get("turn", 0) >= session.summarised_upto]


def _needs_compaction(session, turns: list[AgentRun]) -> bool:
    kept = _verbatim(session, turns)
    if len(kept) <= KEEP_VERBATIM:
        return False
    used = estimate_tokens(session.summary) + sum(estimate_tokens(_turn_text(t)) for t in kept)
    return used > _history_budget()


def compact(session, turns: list[AgentRun], model: str | None = None) -> int:
    """Fold the oldest un-summarised turns into ``session.summary``. Returns how many.

    ONE call, on the CLASSIFIER model: this is summarisation, the classifier is already
    resident, and making a chat turn wait on a second main-model call would double its
    latency for something the user did not ask for.

    Persisted on the session, so it is computed once and every later turn reuses it rather
    than re-summarising the same history on every message.
    """
    from . import services

    kept = _verbatim(session, turns)
    fold = kept[:-KEEP_VERBATIM]
    if not fold:
        return 0

    body = "\n\n".join(_turn_text(t) for t in fold)
    previous = f"Summary so far: {session.summary}\n\n" if session.summary else ""
    raw = services.chat(
        [{"role": "user", "content": SUMMARY_PROMPT + previous + body}],
        model=model or services._classifier_model(),
    )

    summary = raw.strip()
    if not summary:
        return 0

    # `summarised_upto` is the turn index of the first entry still held verbatim. It only
    # ever moves FORWARD, and that is structural rather than defended: `fold` comes from
    # `_verbatim`, which yields only turns at or after the current value, so the new value
    # is always greater. A `max()` here would be unreachable code guarding an invariant the
    # caller already enforces - see the test that pins it.
    session.summary = summary
    session.summarised_upto = fold[-1].meta.get("turn", 0) + 1
    session.save(update_fields=["summary", "summarised_upto", "updated_at"])
    return len(fold)


def _rehydrate(pad: Scratchpad, run: AgentRun) -> int:
    """Replay the conversation so far into ``pad``. Returns the number of turns replayed.

    A turn with no ``output`` (one that errored before answering) still contributes its USER
    message: the user did say it, and dropping it would make the model answer a question that
    appears never to have been asked. A ``stopped`` turn contributes its PARTIAL output -
    that is what the user saw on screen, so it is what the model should believe it said.
    """
    session = run.session
    if session is None:
        return 0

    if session.summary:
        pad.user("Summary of earlier messages in this conversation:\n" + session.summary)

    # Only the turns not already represented by the summary, or the folded ones would be
    # told to the model twice - once compressed and once in full.
    turns = _verbatim(session, _prior_turns(run))
    for turn in turns:
        pad.user(turn.query)
        if turn.output:
            pad.assistant(turn.output)

    # Only the LAST turn's data comes along: a follow-up is nearly always about what was
    # just looked up, and carrying every turn's observations would spend the conversation
    # budget on numbers nobody asked about again.
    if turns:
        carried = _carried_observations(turns[-1])
        if carried:
            pad.observation(carried)
    return len(turns)


def _carried_observations(turn: AgentRun) -> str:
    """The tool results behind ``turn``'s reply, truncated, as one prompt block."""
    lines = []
    for step in turn.steps.order_by("order"):
        tool = step.meta.get("tool") or ""
        observation = step.meta.get("observation") or ""
        if tool and observation:
            lines.append(f"{tool} returned: {observation[:CARRY_OBSERVATION_CHARS]}")
    if not lines:
        return ""
    return "Data you looked up for the previous message:\n" + "\n".join(lines)


def _compact_for(run: AgentRun, model: str | None) -> int:
    """Compact this run's session if the transcript has outgrown its share. Never raises.

    A failed compaction degrades to sending the conversation uncompacted - Scratchpad will
    then warn and Ollama may truncate, which is worse than a summary but far better than
    refusing to answer. The user asked a question; a housekeeping failure must not eat it.
    """
    session = run.session
    if session is None:
        return 0

    turns = _prior_turns(run)
    if not _needs_compaction(session, turns):
        return 0

    try:
        return compact(session, turns, model=model if model else None)
    except Exception:
        # Deliberately broad. Anything at all here - a dead Ollama, a malformed row, a bug
        # in the policy - must cost the user a summary, never their answer.
        logger.warning("Could not compact chat session %s", session.id, exc_info=True)
        return 0


class ChatStrategy(BaseStrategy):
    """Policy only. The loop, the budget, the span, persistence, emission and the terminal
    status all belong to ``_runtime.drive``."""

    kind = "chat"
    event = "step"

    def __init__(self, run: AgentRun, model: str = ""):
        from . import store

        self.run = run
        self.model = model or None
        self.budget = store.run_meta(run).max_steps
        # Bounded, with a declared trim policy: Ollama truncates silently past num_ctx.
        self.compacted = _compact_for(run, self.model)
        self.pad = Scratchpad(_system_prompt())
        self.replayed = _rehydrate(self.pad, run)
        self.pad.user(run.query)
        self.answer: str | None = None
        self.tools_used: list[str] = []
        # Issue #10: a ticker the user NAMES is looked up by code before the model's first
        # call, so its own figures are in THIS turn. Without it, "is NVDA cheap vs the
        # sector?" called no tool in 8/8 live runs and read NVDA's "figures" off other rows
        # of the carried sector observation (AVGO's P/E, the sector's max margin). A prompt
        # rule did not move it; this is code, so it cannot be talked out of. One call is
        # always left for the model when the budget allows.
        self.prefetch_scope = comparison_scope(run.query)
        self.prefetch = named_tickers(run.query, limit=min(MAX_PREFETCH, max(1, self.budget - 1)))

    # --- lifecycle ------------------------------------------------------------------

    def intro(self) -> Generator[str]:
        # `run_id` on STARTED, not just on the terminal `result` event (which `succeed`
        # adds for every workflow). Stopping a half-written reply is the single most used
        # control in a chat UI, and `StopRunView` needs the row id - waiting for the result
        # would mean Stop only works once there is nothing left to stop.
        yield event(
            "started",
            run_id=str(self.run.id),
            session_id=str(self.run.session_id) if self.run.session_id else None,
            max_steps=self.budget,
            tools=list(tools.TOOLS),
            history=self.replayed,
            compacted=self.compacted,
        )

    def next(self, order: int) -> StepSpec | None:
        # The model ends the turn by answering. Exhausting the budget is the driver's
        # business and lands in ``result`` as the forced final answer.
        return None if self.answer is not None else StepSpec(label=f"step {order + 1}")

    def perform_streaming(self, spec: StepSpec) -> Generator[str, None, dict] | None:
        # A prefetch is a plain DB lookup with nothing to stream, so it takes `perform`.
        return None if self.prefetch else self._stream_turn(spec)

    def perform(self, spec: StepSpec) -> dict:
        """A code-initiated ``peer_comparison`` for a ticker the user named (issues #10, #13).

        ``peer_comparison`` rather than ``company_snapshot``: it carries the company's own
        figures (#10) AND the relation to its peers already computed (#13 - with both numbers
        correct, the model still wrote "28.49 is above 34.30" in 2 of 5 runs). Its output is a
        superset of what the snapshot told the model, so nothing a follow-up needs is lost.

        Written into the pad exactly as if the model had asked for it - an assistant tool
        call followed by its observation - because that is the shape the model already
        knows how to read as "data I fetched for this question".
        """
        from .models import AgentStep

        symbol = self.prefetch.pop(0)
        args = {"symbol": symbol}
        if self.prefetch_scope:
            args["scope"] = self.prefetch_scope
        observation = tools.run_tool(PREFETCH_TOOL, args)
        thought = (
            f"You named {symbol}, so its own figures and how they compare with its peers are "
            f"fetched first - not taken from other rows in the conversation."
        )
        if PREFETCH_TOOL not in self.tools_used:
            self.tools_used.append(PREFETCH_TOOL)

        self.pad.assistant(json.dumps({"thought": thought, "tool": PREFETCH_TOOL, "args": args}))
        self.pad.observation("Observation: " + observation)
        return {
            "status": AgentStep.Status.DONE,
            "thought": thought,
            "tool": PREFETCH_TOOL,
            "tool_args": args,
            "observation": observation,
            "is_answer": False,
        }

    def _stream_turn(self, spec: StepSpec) -> Generator[str, None, dict]:
        """One turn of the loop, streaming the reply if this turn is the reply.

        The classification happens on the FIRST non-blank character (see
        ``looks_like_tool_call``): prose is forwarded token by token, JSON is buffered
        because half a tool call means nothing. That is the whole reason chat opts into
        ``perform_streaming`` while every other workflow uses ``perform``.
        """
        from ._events import delta
        from .models import AgentStep

        buffer = ""
        emitted = ""
        streaming = False

        for chunk in self._chat_tokens():
            buffer += chunk
            if streaming:
                emitted += chunk
                yield delta(chunk)
                continue
            if not buffer.strip():
                continue  # only whitespace so far - nothing to classify yet
            if looks_like_tool_call(buffer):
                continue  # a tool call: buffer it, the user must not see raw JSON
            # Prose. Emit what has accumulated, minus the leading whitespace, then stream.
            streaming = True
            emitted = buffer.lstrip()
            yield delta(emitted)

        if streaming:
            # `emitted` IS the answer: concatenating the deltas a client received and the
            # text persisted on the run must give the same string, or a reload changes it.
            self.answer = emitted
            self.pad.assistant(emitted)
            return {"status": AgentStep.Status.DONE, "thought": "", "is_answer": True}

        return self._tool_turn(buffer, AgentStep)

    def _tool_turn(self, raw: str, AgentStep: type) -> dict:  # noqa: N803 - injected type
        """A buffered, JSON-shaped turn: a tool call, or a model still using the old format."""
        try:
            parsed = parse_chat_output(raw)
        except ValueError:
            # Recorded as a step, nudged, retried within the budget. Persisting it is what
            # keeps the live stream and a reloaded transcript the same length (issue #7).
            self.pad.assistant(raw)
            self.pad.user(NUDGE)
            return {
                "status": AgentStep.Status.ERROR,
                "error": "Could not parse model output as JSON.",
                "thought": "",
                "observation": raw[:500],
            }

        thought = str(parsed.get("thought", ""))

        if "answer" in parsed and not parsed.get("tool"):
            # The pre-streaming format. Tolerated rather than nudged: a small model will
            # sometimes wrap an answer in JSON anyway, and the user wants the answer, not a
            # lecture about the protocol. It arrives whole, so no deltas.
            self.answer = str(parsed["answer"])
            self.pad.assistant(self.answer)
            return {"status": AgentStep.Status.DONE, "thought": thought, "is_answer": True}

        tool_name = str(parsed.get("tool", ""))
        args = parsed.get("args") or {}
        observation = tools.run_tool(tool_name, args)
        if tool_name and tool_name not in self.tools_used:
            self.tools_used.append(tool_name)

        self.pad.assistant(raw)
        self.pad.observation("Observation: " + observation)
        return {
            "status": AgentStep.Status.DONE,
            "thought": thought,
            "tool": tool_name,
            "tool_args": args,
            "observation": observation,
            "is_answer": False,
        }

    def result(self) -> Generator[str, None, Outcome]:
        from . import store
        from ._events import step_event
        from .models import AgentStep

        meta = {"tools_used": self.tools_used, "compacted": self.compacted}

        if self.answer is not None:
            return Outcome(self.answer, meta=meta)

        # Budget exhausted with no answer - force one, so a turn never ends blank. Streamed
        # like any other reply: this is the text the user reads, and it is usually the
        # slowest one to arrive.
        from ._events import delta

        self.pad.user(FORCE_ANSWER)
        answer = ""
        try:
            for chunk in self._chat_tokens():
                answer += chunk
                yield delta(chunk)
        except Exception:
            # A failure HERE still produces the step below, so the transcript shows why the
            # turn ended rather than stopping silently one step short. Whatever arrived
            # before the failure is kept - a partial answer beats none.
            logger.warning("Forced answer failed for chat run %s", self.run.id)
        answer = answer.strip()

        step = store.create_step(
            self.run,
            self.budget,
            status=AgentStep.Status.DONE,
            thought="Tool budget exhausted; forced an answer.",
            is_answer=True,
        )
        yield step_event(step, self.event, kind=self.kind)

        if not answer:
            raise AbortedError("The assistant ran out of tool calls without answering.")
        return Outcome(answer, meta=meta)

    def failure(self) -> dict:
        return {"meta": {"tools_used": self.tools_used, "compacted": self.compacted}}

    # --- helpers --------------------------------------------------------------------

    def _chat_tokens(self):
        from . import services

        return services.chat_tokens(self.pad.messages, model=self.model)


def run_chat(run: AgentRun, model: str = "") -> Generator[str]:
    """SSE generator. Runs one conversational turn: tools if needed, then an answer."""
    return drive(run, ChatStrategy(run, model))
