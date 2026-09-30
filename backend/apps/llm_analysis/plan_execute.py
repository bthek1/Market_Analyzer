"""Plan-and-Execute agent.

A planner LLM produces a full multi-step plan upfront; an executor then runs each step in order
(calling a read-only tool the planner chose for that step, then interpreting the result), optionally
replanning the remaining steps when reality diverges (a tool lookup fails). A final synthesis call
folds the step results into the answer.

Unlike ReAct (which picks the next tool reactively each turn) the plan is committed upfront in one
planning call - trading adaptivity for long-horizon coherence and fewer planning calls. The failure
mode is a stale plan, mitigated by the optional bounded replan-on-divergence. Tools are the same
read-only DB lookups ReAct uses (see ``tools.py``); the loop is hard-capped by ``run.max_steps`` and
``OLLAMA_PLAN_MAX_REPLANS``. Each step is surfaced as an SSE ``step`` event and persisted as a
``AgentStep``. Strictly sequential - no fan-out.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from . import tools
from ._events import event
from ._json import parse_json_object
from ._runtime import AbortedError, BaseStrategy, Outcome, StepSpec, drive
from .config import get_llm_config

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator

    from .models import AgentRun, AgentStep


def _plan_system(max_steps: int) -> str:
    return (
        "You are a financial research planner. Break the user's question into an ordered list "
        f"of at most {max_steps} concrete steps. For each step, optionally pick ONE tool that "
        "fetches the data that step needs (or use null for a pure-reasoning step). "
        "Respond with ONLY a single JSON object, nothing else:\n"
        '  {"plan": [{"task": "<what to do>", "tool": "<tool name or null>", '
        '"args": {<arguments>}}]}\n\n'
        "Available tools:\n" + tools.tool_catalogue() + "\n\n"
        "Rules: order the steps so each builds on the previous; pick a tool only when it directly "
        "supplies the step's data; the final step should produce the answer. Tickers are uppercase."
    )


EXECUTE_SYSTEM = (
    "You are executing one step of a research plan. Use the tool observation (if given) and the "
    "results of earlier steps to produce this step's result. Be concise and factual; do not invent "
    "data."
)

REPLAN_SYSTEM = (
    "A step's data lookup failed, so the original plan is stale. Given the goal, the steps "
    "already completed, and their results, produce a revised plan for the REMAINING work only. "
    "Respond with ONLY a JSON object in the same format: "
    '{"plan": [{"task": ..., "tool": ..., "args": {...}}]}.'
)

SYNTH_SYSTEM = (
    "You are a senior financial analyst. Using the plan and the per-step results below, write the "
    "final answer to the user's question in clean, well-structured markdown."
)


def parse_plan(raw: str, max_steps: int) -> list[dict]:
    """Parse a planner response into a normalised, capped list of ``{task, tool, args}`` steps.

    Tolerant of a bare list, a missing ``args``, and a ``tool`` of ``""``/``"null"`` (-> None).
    Raises ValueError when no usable plan can be extracted.
    """
    steps = None
    try:
        data = parse_json_object(raw)
        if isinstance(data.get("plan"), list):
            steps = data["plan"]
    except ValueError:
        pass

    if steps is None:
        # Tolerate a bare JSON list of steps (no wrapping {"plan": ...} object).
        text = raw.strip()
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end > start:
            try:
                steps = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                steps = None

    if not isinstance(steps, list) or not steps:
        raise ValueError("plan was empty")

    normalised: list[dict] = []
    for step in steps[:max_steps]:
        if not isinstance(step, dict):
            continue
        tool = step.get("tool")
        if tool in ("", "null", "none", "None"):
            tool = None
        args = step.get("args")
        normalised.append(
            {
                "task": str(step.get("task", "")),
                "tool": tool,
                "args": args if isinstance(args, dict) else None,
            }
        )
    if not normalised:
        raise ValueError("plan had no usable steps")
    return normalised


def _diverged(observation: str) -> bool:
    """Reality diverged from the plan: a tool observation parsed to an ``{"error": ...}`` object."""
    if not observation:
        return False
    try:
        return "error" in parse_json_object(observation)
    except ValueError:
        return False


def _format_results(plan: list[dict], results: list[str]) -> str:
    return "\n\n".join(f"Step {i + 1} ({plan[i]['task']}):\n{res}" for i, res in enumerate(results))


class PlanExecStrategy(BaseStrategy):
    """Policy only: plan upfront, execute each step, replan on divergence, synthesise."""

    kind = "plan_exec"
    event = "step"

    def __init__(self, run: AgentRun, model: str = ""):
        from . import store

        cfg = store.run_meta(run)
        self.run = run
        self.model = model or None
        self.budget = cfg.max_steps
        self.allow_replan = cfg.allow_replan
        self.plan: list[dict] = []
        self.results: list[str] = []
        self.replans = 0
        self.observation = ""
        self.tool_name: str | None = None

    # --- lifecycle ------------------------------------------------------------------

    def intro(self) -> Generator[str]:
        from . import store

        yield event("started", max_steps=self.budget, allow_replan=self.allow_replan)

        raw = self._call(_plan_system(self.budget), self.run.query)
        try:
            self.plan = parse_plan(raw, self.budget)
        except ValueError:
            raise AbortedError("Planner did not return a usable plan.") from None

        store.update_run(self.run, plan=self.plan)
        yield event("plan", steps=self.plan)

    def next(self, order: int) -> StepSpec | None:
        # The plan can GROW on a replan, so its length is re-read every iteration; the
        # driver's budget is the hard cap.
        return None if order >= len(self.plan) else StepSpec(label=f"step {order + 1}")

    def perform(self, spec: StepSpec) -> dict:
        step = self.plan[spec.order]
        self.tool_name = step.get("tool")
        args = step.get("args") or {}
        self.observation = tools.run_tool(self.tool_name, args) if self.tool_name else ""

        user = (
            f"User question: {self.run.query}\n\n"
            f"Current step: {step['task']}\n"
            + (f"Tool observation: {self.observation}\n" if self.observation else "")
            + (
                f"\nResults of earlier steps:\n{_format_results(self.plan, self.results)}"
                if self.results
                else ""
            )
        )
        result = self._call(EXECUTE_SYSTEM, user)
        self.results.append(result)

        return {
            "status": "done",
            "task": step["task"],
            "tool": self.tool_name or "",
            "tool_args": args,
            "observation": self.observation,
            "result": result,
        }

    def after(self, step: AgentStep) -> Iterator[str]:
        """Replan the REMAINING steps when a tool lookup failed - the divergence signal."""
        from . import services, store

        max_replans = get_llm_config().plan_max_replans
        if not (self.allow_replan and _diverged(self.observation) and self.replans < max_replans):
            return

        done = len(self.results)
        replan_user = (
            f"Goal: {self.run.query}\n\n"
            f"Steps completed so far:\n{_format_results(self.plan, self.results)}\n\n"
            f"The step '{self.plan[done - 1]['task']}' hit a failed lookup: {self.observation}"
        )
        try:
            tail = parse_plan(self._call(REPLAN_SYSTEM, replan_user), self.budget - done)
        except (services.OllamaServiceError, ValueError):
            # A failed replan is not a failed run - keep going with the plan we have. An
            # EMPTY replan arrives here too: parse_plan raises rather than returning [],
            # which is why there is no separate falsy-tail guard (pinned by a test).
            return

        self.plan = self.plan[:done] + tail
        self.replans += 1
        store.update_run(self.run, plan=self.plan, replans=self.replans)
        yield event(
            "replan",
            reason=f"{self.tool_name} returned an error; revised the remaining steps.",
            steps=self.plan,
        )

    def result(self) -> Generator[str, None, Outcome]:
        synth_user = (
            f"User question: {self.run.query}\n\n"
            f"Plan and per-step results:\n{_format_results(self.plan, self.results)}"
        )
        answer = self._call(SYNTH_SYSTEM, synth_user)
        return Outcome(answer, fields={"steps": len(self.results), "replans": self.replans})
        yield  # pragma: no cover - makes this a generator; the return above always wins

    # --- helpers --------------------------------------------------------------------

    def _call(self, system: str, user: str) -> str:
        from . import services

        return services.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            model=self.model,
        )


def run_plan(run: AgentRun, model: str = "") -> Generator[str]:
    """SSE generator. Plan upfront, execute each step, optionally replan on divergence."""
    return drive(run, PlanExecStrategy(run, model))
