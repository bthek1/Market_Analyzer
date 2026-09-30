"""Autonomous / Long-Horizon (AutoGPT-style) agent.

The agent holds a long-term GOAL (the query), maintains a self-managed task BACKLOG, and runs a
bounded controller loop. Each cycle the controller LLM returns ONE JSON object that REFLECTS on
progress (and the prior cycle's failures), SELF-ASSIGNS the next task, rewrites the backlog, and
chooses how to act:

  * ``tool``     - run one read-only DB tool (see ``tools.py``), then interpret the observation.
  * ``subagent`` - delegate a sub-goal to a bounded, NON-recursive sub-agent (a small ReAct-style
                   tool loop); gated by ``run.max_subagents``.
  * ``reason``   - a pure reasoning step over working memory (no tool, no spawn).

Each cycle's output is folded into WORKING MEMORY, which is injected into the next controller call.
The loop stops when the controller signals ``goal_complete``, when the cycle budget is exhausted, or
when a NO-PROGRESS detector trips (consecutive cycles that add nothing). On every termination path a
final synthesis call folds working memory into the answer, so a run is never left blank.

What makes this distinct from its cousins:
  * vs ``react``: ReAct answers a SINGLE question in one shared scratchpad with a fixed tool menu.
    Here the agent pursues a GOAL across cycles, keeps an explicit mutable backlog, can SPAWN
    sub-agents, reflects on failure, and OWNS the termination decision. A cycle's "execute" step is
    essentially one ReAct turn; the autonomous loop wraps planning + reflection + replanning on top.
  * vs ``plan_execute``: that commits an ordered plan ONCE. Here the backlog is re-derived every
    cycle from accumulated memory - the plan is never fixed.
  * vs ``orchestrator`` / ``dag``: those decompose ONCE and fan out. Here decomposition is
    continuous and adaptive - the next task depends on what prior cycles discovered.

Reliability (the documented hard part) rests on: a hard cycle cap, a hard sub-agent cap with
non-recursive bounded sub-agents, a no-progress detector, tolerant JSON parsing with deterministic
fallbacks, read-only tools that never raise, per-call error isolation, and an always-synthesise end.
"""

from __future__ import annotations

from datetime import UTC
from datetime import datetime as dt
from typing import TYPE_CHECKING

from . import tools
from ._context import Scratchpad
from ._events import event
from ._json import parse_json_object
from ._runtime import AbortedError, BaseStrategy, Outcome, StepSpec, drive

if TYPE_CHECKING:
    from collections.abc import Generator

    from .models import AgentRun, AgentStep

_VALID_ACTIONS = ("tool", "subagent", "reason")


# --- Prompts -------------------------------------------------------------------------------


def _bootstrap_system() -> str:
    return (
        "You are an autonomous research agent. Restate the user's request as a clear long-term "
        "GOAL, then seed an initial task BACKLOG: a short ordered list of concrete subtasks that, "
        "once all done, achieve the goal. Respond with ONLY a single JSON object, nothing else:\n"
        '  {"goal": "<one-sentence restatement>", "backlog": ["<task>", "<task>", ...]}\n\n'
        "Available tools the agent can use later:\n" + tools.tool_catalogue() + "\n\n"
        "Keep the backlog focused (3-6 tasks). Tickers are uppercase symbols."
    )


def _controller_system() -> str:
    return (
        "You are the controller of an autonomous agent working toward a fixed GOAL over multiple "
        "cycles. You are given the goal, the current backlog, and the working memory of results so "
        "far. REFLECT on progress and on any errors from the previous cycle, then decide the "
        "SINGLE next task to do now and how to act on it. Respond with ONLY a single JSON object:\n"
        '  {"reflection": "<progress + failures so far>", '
        '"goal_complete": <true|false>, '
        '"next_task": "<the one task to do this cycle>", '
        '"backlog": ["<remaining/added tasks>"], '
        '"action": "tool" | "subagent" | "reason", '
        '"tool": "<tool name or null>", "args": {<arguments>}, '
        '"subagent_goal": "<sub-goal to delegate, only when action is subagent>"}\n\n'
        "Available tools:\n" + tools.tool_catalogue() + "\n\n"
        "Rules: set goal_complete=true ONLY when the working memory already answers the goal - "
        "then no further task is needed. Use action 'tool' to fetch one piece of data, 'subagent' "
        "to delegate a self-contained multi-step sub-goal, 'reason' to think over what you have. "
        "Do not invent data; do not repeat a task already completed. Tickers are uppercase."
    )


CYCLE_SYSTEM = (
    "You are an autonomous agent executing ONE self-assigned task toward a larger goal. Use the "
    "tool observation and/or your working memory to produce a concise, factual result for THIS "
    "task only. Do not answer the whole goal; do not invent data."
)

SUBAGENT_SYSTEM_TEMPLATE = (
    "You are a focused sub-agent delegated ONE self-contained sub-goal. Answer it by calling "
    "tools in a loop. On every turn respond with ONLY a single JSON object, nothing else.\n"
    "To call a tool:\n"
    '  {{"thought": "<reasoning>", "tool": "<tool_name>", "args": {{<arguments>}}}}\n'
    "To finish with your findings:\n"
    '  {{"thought": "<reasoning>", "answer": "<concise findings in markdown>"}}\n\n'
    "Available tools:\n{catalogue}\n\n"
    "Rules: call one tool at a time; use the observations; stop and answer once you have enough. "
    "Tickers are uppercase symbols."
)

SYNTH_SYSTEM = (
    "An autonomous agent worked toward a goal over several cycles. Synthesise its accumulated "
    "results into one coherent, structured analysis that answers the goal; resolve overlaps and "
    "highlight the key takeaways. Write clean markdown."
)


# --- Parsing -------------------------------------------------------------------------------


def parse_bootstrap(raw: str) -> tuple[str, list[str]]:
    """Parse the bootstrap response into ``(goal, backlog)``. Tolerant; falls back to empty."""
    try:
        data = parse_json_object(raw)
    except ValueError:
        return "", []
    goal = str(data.get("goal", "")).strip()
    backlog = data.get("backlog")
    tasks = [str(t).strip() for t in backlog if str(t).strip()] if isinstance(backlog, list) else []
    return goal, tasks


def parse_controller(raw: str) -> dict:
    """Parse a controller turn into a normalised decision dict.

    Always returns a dict with keys ``reflection``, ``goal_complete``, ``next_task``, ``backlog``,
    ``action`` (one of tool/subagent/reason), ``tool``, ``args``, ``subagent_goal``. Tolerant of
    noise; unparseable output yields ``action='reason'`` with empty fields (a no-progress cycle).
    """
    try:
        data = parse_json_object(raw)
    except ValueError:
        data = {}

    action = str(data.get("action", "")).strip().lower()
    if action not in _VALID_ACTIONS:
        action = "reason"

    tool = data.get("tool")
    if tool in ("", "null", "none", "None"):
        tool = None
    if action != "tool":
        tool = None  # tool only meaningful for a tool action

    args = data.get("args")
    backlog = data.get("backlog")
    tasks = [str(t).strip() for t in backlog if str(t).strip()] if isinstance(backlog, list) else []

    next_task = str(data.get("next_task", "")).strip()
    if not next_task and tasks:
        next_task = tasks[0]  # fall back to the head of the backlog

    return {
        "reflection": str(data.get("reflection", "")).strip(),
        "goal_complete": bool(data.get("goal_complete", False)),
        "next_task": next_task,
        "backlog": tasks,
        "action": action,
        "tool": tool,
        "args": args if isinstance(args, dict) else None,
        "subagent_goal": str(data.get("subagent_goal", "")).strip(),
    }


# --- Persistence helpers -------------------------------------------------------------------


def _stop_reason(run: AgentRun, stop_reason: str, *, errored: bool) -> str:
    """Resolve the run's terminal stop_reason, falling back to the stored one."""
    from . import store

    return stop_reason or ("error" if errored else store.run_meta(run).stop_reason or "")


# --- Bounded, non-recursive sub-agent ------------------------------------------------------


def run_subagent(goal: str, max_steps: int, model: str | None) -> tuple[str, list[dict]]:
    """Run a bounded ReAct-style tool loop for one delegated sub-goal. Never recurses (no spawning).

    Returns ``(findings, steps)`` where ``steps`` is ``[{thought, tool, args, observation}, ...]``.
    Bounded by ``max_steps``; on budget exhaustion forces one final-answer call. Per-call errors are
    swallowed into the findings string so a failed sub-agent never aborts the parent loop.
    """
    from . import services
    from .react import parse_react_output

    # Accumulating, so it is budgeted and trimmed rather than left to Ollama's silent
    # truncation - the same treatment the top-level ReAct loop gets.
    pad = Scratchpad(SUBAGENT_SYSTEM_TEMPLATE.format(catalogue=tools.tool_catalogue()))
    pad.user(goal)
    steps: list[dict] = []

    for _ in range(max(1, max_steps)):
        try:
            raw = services.chat(pad.messages, model=model)
        except services.OllamaServiceError as exc:
            return f"(sub-agent failed: {exc})", steps
        try:
            parsed = parse_react_output(raw)
        except ValueError:
            pad.assistant(raw)
            pad.user("That was not valid JSON. Respond with ONLY a JSON object.")
            continue

        if "answer" in parsed and not parsed.get("tool"):
            return str(parsed["answer"]), steps

        tool_name = str(parsed.get("tool", ""))
        args = parsed.get("args") or {}
        observation = tools.run_tool(tool_name, args)
        steps.append(
            {
                "thought": str(parsed.get("thought", "")),
                "tool": tool_name,
                "args": args,
                "observation": observation,
            }
        )
        pad.assistant(raw)
        pad.observation("Observation: " + observation)

    # Budget exhausted - force one final answer.
    pad.user(
        "You have used all your steps. Give your best concise findings NOW as a JSON "
        'object: {"answer": "<findings in markdown>"}.'
    )
    try:
        raw = services.chat(pad.messages, model=model)
        findings = str(parse_react_output(raw).get("answer", raw))
    except (services.OllamaServiceError, ValueError):
        findings = "(sub-agent produced no findings)"
    return findings, steps


# --- Public entrypoint ---------------------------------------------------------------------


class AutonomousStrategy(BaseStrategy):
    """Policy only: a goal-driven controller loop that owns its own termination.

    Unlike every other driven workflow, a failed cycle is NOT a failed run - the error is
    fed into the next cycle's reflection. The loop stops on ``goal_complete``, on the
    driver's cycle budget, or on the no-progress detector, and every path still
    synthesises, so a run is never blank.
    """

    kind = "autonomous"
    event = "cycle"

    def __init__(self, run: AgentRun, model: str = ""):
        from . import config, store

        cfg = config.get_llm_config()
        run_cfg = store.run_meta(run)

        self.run = run
        self.model = model or None
        self.budget = run_cfg.max_cycles
        self.max_subagents = run_cfg.max_subagents
        self.subagent_steps = max(1, cfg.auto_subagent_steps)
        self.no_progress_limit = max(1, cfg.auto_no_progress)

        self.goal = run.query
        self.backlog: list[str] = []
        self.memory: list[tuple[str, str]] = []  # (task, result), folded into each prompt
        self.subagents_used = 0
        self.no_progress = 0
        self.prev_error = ""
        self.stop_reason = "budget"
        self.stopped = False

    # --- lifecycle ------------------------------------------------------------------

    def intro(self) -> Generator[str]:
        from . import store

        raw = self._call(_bootstrap_system(), self.run.query)
        goal, backlog = parse_bootstrap(raw)
        self.goal = goal or self.run.query
        self.backlog = backlog
        store.update_run(self.run, goal=self.goal, backlog=self.backlog)
        yield event("goal", goal=self.goal, backlog=self.backlog, max_cycles=self.budget)

    def next(self, order: int) -> StepSpec | None:
        return None if self.stopped else StepSpec()

    def pre_step(self, spec: StepSpec) -> AgentStep:
        """Running BEFORE the cycle works, so a mid-run refresh shows it in flight."""
        from . import store
        from .models import AgentStep

        return store.create_step(
            self.run, spec.order, status=AgentStep.Status.RUNNING, started_at=dt.now(UTC)
        )

    def perform(self, spec: StepSpec) -> dict:
        from . import services
        from .models import AgentStep

        try:
            raw = self._call(
                _controller_system(),
                _controller_user(self.goal, self.backlog, self.memory, self.prev_error),
            )
        except services.OllamaServiceError as exc:
            # A failed controller call is data for the NEXT reflection, not a failed run.
            self._stall(str(exc))
            return {
                "status": AgentStep.Status.ERROR,
                "error": str(exc),
                "completed_at": dt.now(UTC),
            }

        decision = parse_controller(raw)
        self.backlog = decision["backlog"] or self.backlog
        cmeta = {
            "reflection": decision["reflection"],
            "task": decision["next_task"],
            "action": decision["action"],
            "backlog": self.backlog,
            "goal_complete": decision["goal_complete"],
        }

        if decision["goal_complete"]:
            self._stop("complete")
            return {"status": AgentStep.Status.DONE, "completed_at": dt.now(UTC), **cmeta}

        # An empty task with no action to take is a stall, not progress.
        if not decision["next_task"] and decision["action"] == "reason":
            self._stall("")
            return {"status": AgentStep.Status.DONE, "completed_at": dt.now(UTC), **cmeta}

        result, ok, cerr = self._act(decision, cmeta)

        if ok and result.strip():
            self.memory.append((decision["next_task"], result))
            self.no_progress = 0
            self.prev_error = ""
            status = AgentStep.Status.DONE
        else:
            self._stall(cerr or "the previous task produced no usable result")
            status = AgentStep.Status.ERROR

        return {
            "status": status,
            "output": result,
            "error": cerr,
            "completed_at": dt.now(UTC),
            **cmeta,
        }

    def result(self) -> Generator[str, None, Outcome]:
        from . import store

        store.update_run(self.run, backlog=self.backlog, stop_reason=self.stop_reason)

        if not self.memory:
            raise AbortedError("Autonomous agent produced no usable results.")

        synth_user = f'The goal was: "{self.goal}"\n\n' + "\n\n".join(
            f"### {task}\n{result}" for task, result in self.memory
        )
        answer = self._call(SYNTH_SYSTEM, synth_user)
        return Outcome(
            answer,
            meta={"stop_reason": _stop_reason(self.run, self.stop_reason, errored=False)},
            fields={"cycles": len(self.memory), "stop_reason": self.stop_reason},
        )
        yield  # pragma: no cover - makes this a generator; the return above always wins

    def failure(self) -> dict:
        return {"meta": {"stop_reason": _stop_reason(self.run, self.stop_reason, errored=True)}}

    # --- helpers --------------------------------------------------------------------

    def _stop(self, reason: str) -> None:
        self.stop_reason = reason
        self.stopped = True

    def _stall(self, error: str) -> None:
        """No progress this cycle. Enough of them in a row and the run gives up."""
        self.prev_error = error
        self.no_progress += 1
        if self.no_progress >= self.no_progress_limit:
            self._stop("no_progress")

    def _act(self, decision: dict, cmeta: dict) -> tuple[str, bool, str]:
        """Run the self-assigned task: a sub-agent, a read-only tool, or pure reasoning."""
        from . import services

        action = decision["action"]
        # A sub-agent request beyond budget degrades to a tool/reason action.
        if action == "subagent" and self.subagents_used >= self.max_subagents:
            action = "tool" if decision["tool"] else "reason"
        cmeta["action"] = action

        if action == "subagent":
            sub_goal = decision["subagent_goal"] or decision["next_task"]
            findings, steps = run_subagent(sub_goal, self.subagent_steps, self.model)
            self.subagents_used += 1
            cmeta["spawned"] = True
            cmeta["subagent_steps"] = steps
            return findings, not findings.startswith("(sub-agent failed"), ""

        observation = ""
        if action == "tool" and decision["tool"]:
            observation = tools.run_tool(decision["tool"], decision["args"] or {})
            cmeta["tool"] = decision["tool"]
            cmeta["tool_args"] = decision["args"]
            cmeta["observation"] = observation

        cycle_user = _cycle_user(self.goal, decision["next_task"], observation, self.memory)
        try:
            return self._call(CYCLE_SYSTEM, cycle_user), True, ""
        except services.OllamaServiceError as exc:
            return "", False, str(exc)

    def _call(self, system: str, user: str) -> str:
        from . import services

        return services.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            model=self.model,
        )


def run_autonomous(run: AgentRun, model: str = "") -> Generator[str]:
    """SSE generator. Bootstrap a goal+backlog, run the bounded controller loop, synthesise."""
    return drive(run, AutonomousStrategy(run, model))


def _controller_user(goal: str, backlog: list[str], memory: list[tuple[str, str]], prev_error: str):
    parts = [f"GOAL: {goal}"]
    parts.append("BACKLOG:\n" + ("\n".join(f"- {t}" for t in backlog) if backlog else "(empty)"))
    if memory:
        done = "\n\n".join(f"[{task}]\n{result}" for task, result in memory)
        parts.append(f"WORKING MEMORY (results so far):\n{done}")
    else:
        parts.append("WORKING MEMORY: (empty - nothing done yet)")
    if prev_error:
        parts.append(f"PREVIOUS CYCLE ERROR (reflect and adapt): {prev_error}")
    return "\n\n".join(parts)


def _cycle_user(goal: str, task: str, observation: str, memory: list[tuple[str, str]]) -> str:
    parts = [f"Overall goal (for context only): {goal}", f"Your task this cycle: {task}"]
    if observation:
        parts.append(f"Tool observation: {observation}")
    if memory:
        recent = "\n\n".join(f"[{t}]\n{r}" for t, r in memory[-3:])
        parts.append(f"Relevant earlier results:\n{recent}")
    return "\n\n".join(parts)
