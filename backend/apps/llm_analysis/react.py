"""ReAct (Reasoning + Acting) agent.

A bounded, LLM-driven loop: the model interleaves Thought -> Tool Call -> Observation, repeating
until it decides it has enough information to answer. Unlike chain/route/parallel (where our code
fixes the control flow), here the LLM picks the next tool each turn. Tools are read-only DB lookups
(see ``tools.py``); the loop is hard-capped at ``run.max_steps`` and forces a final answer when the
budget is exhausted. Each turn is surfaced as an SSE ``step`` event and persisted as a
``AgentStep``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import tools
from ._context import Scratchpad
from ._events import event
from ._json import parse_json_object
from ._runtime import AbortedError, BaseStrategy, Outcome, StepSpec, drive

if TYPE_CHECKING:
    from collections.abc import Generator

    from .models import AgentRun


def _system_prompt() -> str:
    return (
        "You are a financial research agent that answers questions by calling tools in a loop. "
        "On every turn respond with ONLY a single valid JSON object, nothing else. "
        "To call a tool:\n"
        '  {"thought": "<your reasoning>", "tool": "<tool_name>", "args": {<arguments>}}\n'
        "To give your final answer when you have enough information:\n"
        '  {"thought": "<your reasoning>", "answer": "<final answer in markdown>"}\n\n'
        "Available tools:\n" + tools.tool_catalogue() + "\n\n"
        "Rules: call one tool at a time; use the observations returned to you; do not invent data; "
        "when the data is sufficient, stop and return an answer. Tickers are uppercase symbols."
    )


NUDGE = (
    "Your last response was not valid JSON. Respond with ONLY a JSON object: "
    'either {"thought": ..., "tool": ..., "args": {...}} or '
    '{"thought": ..., "answer": ...}.'
)


def parse_react_output(raw: str) -> dict:
    """Tolerantly parse a ReAct turn into a dict. Raises ValueError on unrecoverable output.

    Thin wrapper over the shared ``parse_json_object`` helper.
    """
    return parse_json_object(raw)


class ReActStrategy(BaseStrategy):
    """Policy only. The loop, the budget, the span, persistence, emission and the terminal
    status all belong to ``_runtime.drive``."""

    kind = "react"
    event = "step"

    def __init__(self, run: AgentRun, model: str = ""):
        from . import store

        self.run = run
        self.model = model or None
        self.budget = store.run_meta(run).max_steps
        # An accumulating scratchpad: bounded, with a declared trim policy, because
        # Ollama truncates silently past num_ctx (see _context).
        self.pad = Scratchpad(_system_prompt())
        self.pad.user(run.query)
        self.answer: str | None = None

    # --- lifecycle ------------------------------------------------------------------

    def intro(self) -> Generator[str]:
        yield event("started", max_steps=self.budget, tools=list(tools.TOOLS))

    def next(self, order: int) -> StepSpec | None:
        # The LLM decides when to stop, by answering. Exhausting the budget is handled by
        # the driver, and lands in ``result`` as the forced final answer.
        return None if self.answer is not None else StepSpec(label=f"step {order + 1}")

    def perform(self, spec: StepSpec) -> dict:
        from .models import AgentStep

        raw = self._chat()

        try:
            parsed = parse_react_output(raw)
        except ValueError:
            # Unparseable turn: recorded as a step, nudged, and retried within the budget.
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
            self.answer = str(parsed["answer"])
            return {"status": AgentStep.Status.DONE, "thought": thought, "is_answer": True}

        tool_name = str(parsed.get("tool", ""))
        args = parsed.get("args") or {}
        observation = tools.run_tool(tool_name, args)

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

        if self.answer is not None:
            return Outcome(self.answer)

        # Budget exhausted without an answer - force one final answer call.
        self.pad.user(
            "You have used all your tool-call steps. Give your best final answer NOW as a "
            'JSON object: {"answer": "<final answer in markdown>"}. Do not call any more tools.'
        )
        try:
            raw = self._chat()
            answer = str(parse_react_output(raw).get("answer", raw))
        except Exception:
            # A failure HERE still produces the forced step below, so the timeline shows
            # why the run ended rather than stopping silently one step short.
            answer = ""

        step = store.create_step(
            self.run,
            self.budget,
            status=AgentStep.Status.DONE,
            thought="Step budget exhausted; forced final answer.",
            is_answer=True,
        )
        yield step_event(step, self.event, kind=self.kind)

        if not answer:
            raise AbortedError("Agent exhausted its step budget without producing an answer.")
        return Outcome(answer)

    # --- helpers --------------------------------------------------------------------

    def _chat(self) -> str:
        from . import services

        return services.chat(self.pad.messages, model=self.model)


def run_react(run: AgentRun, model: str = "") -> Generator[str]:
    """SSE generator. Runs the bounded Thought -> Tool -> Observation loop."""
    return drive(run, ReActStrategy(run, model))
