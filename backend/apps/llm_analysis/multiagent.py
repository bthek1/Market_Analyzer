"""Multi-Agent (Sequential / Hierarchical) agent.

A lead supervisor routes the user's question to a fixed roster of role-specialised sub-agents -
Researcher -> Analyst -> Writer - that run as a SEQUENTIAL hand-off pipeline (each stage consumes
only the prior stage's curated output, never a shared scratchpad), then the supervisor folds every
stage's output into the final answer.

What makes this distinct from the other agents:
  * role specialisation - each sub-agent has its OWN system prompt and its OWN allow-listed tool
    subset (only the Researcher gets tools), declared once in ``ROSTER``.
  * sequential hand-off + isolated context - stage N+1 sees only stage N's output plus the original
    query. Unlike ReAct's single shared scratchpad, downstream agents do not see raw observations.
  * the supervisor only *routes* (selects an ordered subset of the fixed roster); it cannot invent
    agents. Distinct from orchestrator-workers (homogeneous, dynamic, parallel) and plan-execute
    (one generic executor, dynamic plan, all tools).

Tools are the same read-only DB lookups ReAct / plan-execute / orchestrator use (see ``tools.py``).
This agent is strictly sequential - it does NOT use ``chat_many``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime as dt
from typing import TYPE_CHECKING

from . import tools
from ._events import event
from ._json import parse_json_object
from ._runtime import AbortedError, BaseStrategy, Outcome, StepSpec, drive

if TYPE_CHECKING:
    from collections.abc import Generator

    from .models import AgentRun, AgentStep


# --- Roster (declarative; specialisation lives here only) ----------------------------------


@dataclass(frozen=True)
class SubAgent:
    id: str
    label: str
    system: str
    tools: tuple[str, ...] = ()  # allow-listed tool names; () => reasoning-only agent

    @property
    def uses_tools(self) -> bool:
        return bool(self.tools)


# All read-only data tools the Researcher is permitted to call.
_RESEARCHER_TOOLS: tuple[str, ...] = (
    "company_profile",
    "company_snapshot",
    "peer_comparison",
    "company_financials",
    "recent_price",
    "list_sectors",
    "sector_analysis",
    "industry_analysis",
    "current_time",
    "weather",
)

ROSTER: tuple[SubAgent, ...] = (
    SubAgent(
        id="researcher",
        label="Researcher",
        system=(
            "You are a financial RESEARCHER. Gather only the raw facts the question needs from the "
            "tool observations you are given. Report figures plainly; do NOT interpret, rate, or "
            "recommend - that is the Analyst's job. If no observations are given, state what data "
            "would be needed."
        ),
        tools=_RESEARCHER_TOOLS,
    ),
    SubAgent(
        id="analyst",
        label="Analyst",
        system=(
            "You are a financial ANALYST. You receive the Researcher's raw findings. Interpret "
            "them: read the ratios, weigh valuation, profitability, and risk, and state what they "
            "imply. Do not fetch data and do not write the final report - reason."
        ),
    ),
    SubAgent(
        id="writer",
        label="Writer",
        system=(
            "You are a financial WRITER. You receive the Analyst's interpretation. Produce a "
            "clear, well-structured markdown report for the user. Do not add new facts or "
            "analysis; present what you were given cleanly."
        ),
    ),
)

_ROSTER_BY_ID: dict[str, SubAgent] = {a.id: a for a in ROSTER}
_ROSTER_ORDER: list[str] = [a.id for a in ROSTER]


ROUTE_SYSTEM = (
    "You are a supervisor coordinating a fixed roster of specialised financial sub-agents. "
    "Decide which sub-agents the user's question needs and in what order. Respond with ONLY a "
    'single JSON object, nothing else:\n  {"agents": ["researcher", "analyst", "writer"], '
    '"reason": "<one sentence>"}\n\n'
    "Available sub-agents (run strictly in this order):\n"
    "- researcher: looks up raw company/sector data via read-only tools.\n"
    "- analyst: interprets findings (valuation, profitability, risk). No tools.\n"
    "- writer: writes the final user-facing report. No tools.\n\n"
    "Rules: pick a subset in the listed order. Skip 'researcher' only for pure-opinion questions "
    "needing no data lookup. The 'writer' is always required."
)

SYNTH_SYSTEM = (
    "Several specialised sub-agents each handled one stage of answering the user's question. "
    "Synthesise their outputs into one coherent, structured final answer; resolve any overlaps or "
    "contradictions and highlight the key takeaways. Write clean markdown."
)


def _tool_plan_system(agent: SubAgent, max_tools: int) -> str:
    return (
        f"You are the {agent.label} sub-agent. Choose up to {max_tools} read-only tools to fetch "
        "the data your task needs. Respond with ONLY a single JSON object, nothing else:\n"
        '  {"tools": [{"tool": "<tool name>", "args": {<arguments>}}]}\n\n'
        "Available tools:\n" + tools.tool_catalogue(only=agent.tools) + "\n\n"
        "Use an empty list if no data lookup is needed. Tickers are uppercase."
    )


# --- Parsing ------------------------------------------------------------------------------


def parse_route(raw: str) -> tuple[list[str], str]:
    """Parse the supervisor routing response into (ordered agent ids, reason).

    Keeps only known roster ids, preserves roster order, dedupes, and always includes ``writer``.
    Falls back to the full roster on empty / unparseable output (never raises).
    """
    agents = None
    reason = ""
    try:
        data = parse_json_object(raw)
        reason = str(data.get("reason", "")).strip()
        if isinstance(data.get("agents"), list):
            agents = data["agents"]
    except ValueError:
        pass

    if agents is None:
        # Tolerate a bare JSON list of agent ids.
        text = raw.strip()
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end > start:
            try:
                agents = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                agents = None

    chosen = [a for a in _ROSTER_ORDER if isinstance(agents, list) and a in agents]
    if not chosen:
        chosen = list(_ROSTER_ORDER)  # fall back to the full roster
    if "writer" not in chosen:
        chosen.append("writer")
    # Re-sort into the canonical roster order so the pipeline always flows the right way.
    chosen = [a for a in _ROSTER_ORDER if a in chosen]
    return chosen, reason


def parse_tool_plan(raw: str, agent: SubAgent, max_tools: int) -> list[dict]:
    """Parse a Researcher tool-plan into a capped list of ``{tool, args}`` dicts.

    Drops any tool not in ``agent.tools`` (per-agent allow-list enforcement). Tolerant of a bare
    list and a missing ``args``. Returns an empty list when no usable/allowed tool remains.
    """
    items = None
    try:
        data = parse_json_object(raw)
        if isinstance(data.get("tools"), list):
            items = data["tools"]
    except ValueError:
        pass

    if items is None:
        text = raw.strip()
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end > start:
            try:
                items = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                items = None

    if not isinstance(items, list):
        return []

    allowed = set(agent.tools)
    normalised: list[dict] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("tool", "")).strip()
        if name not in allowed:
            continue
        args = entry.get("args")
        normalised.append({"tool": name, "args": args if isinstance(args, dict) else {}})
        if len(normalised) >= max_tools:
            break
    return normalised


# --- Prompts ------------------------------------------------------------------------------


def _agent_user(query: str, handoff: str, tool_calls: list[dict]) -> str:
    parts = [f"User's question: {query}"]
    if handoff:
        parts.append(f"Input from the previous stage:\n{handoff}")
    if tool_calls:
        obs = "\n".join(
            f"- {c['tool']}({json.dumps(c['args'])}): {c['observation']}" for c in tool_calls
        )
        parts.append(f"Tool observations:\n{obs}")
    return "\n\n".join(parts)


# --- Persistence helpers ------------------------------------------------------------------


def _mark_running(step: AgentStep, *, input_text: str) -> None:
    from . import store
    from .models import AgentStep

    store.update_step(
        step,
        status=AgentStep.Status.RUNNING,
        started_at=dt.now(UTC),
        kind="multiagent",
        input=input_text,
    )


# --- Public entrypoint --------------------------------------------------------------------


class MultiAgentStrategy(BaseStrategy):
    """Policy only: a supervisor routes a fixed roster, then a sequential hand-off.

    Each stage's output is the next stage's only input besides the query - isolated
    context, unlike ReAct's shared scratchpad. A failing stage degrades the hand-off but
    never aborts the run, so ``perform`` returns error fields rather than raising.
    """

    kind = "multiagent"
    event = "step"

    def __init__(self, run: AgentRun, model: str = ""):
        from . import store

        self.run = run
        self.model = model or None
        self.max_tools = store.run_meta(run).max_tools
        self.agent_ids: list[str] = []
        self.handoff = run.query
        self.stage_outputs: list[tuple[str, str]] = []
        self.budget = 0

    def intro(self) -> Generator[str]:
        from . import store

        raw = self._call(ROUTE_SYSTEM, self.run.query)
        self.agent_ids, reason = parse_route(raw)
        self.budget = len(self.agent_ids)
        store.update_run(self.run, agents=self.agent_ids, route_reason=reason)
        yield event("route", agents=self.agent_ids, reason=reason or None)

    def next(self, order: int) -> StepSpec | None:
        if order >= len(self.agent_ids):
            return None
        agent = _ROSTER_BY_ID[self.agent_ids[order]]
        return StepSpec(key=agent.id, label=agent.label)

    def pre_step(self, spec: StepSpec) -> AgentStep:
        """The row exists, running, BEFORE the stage works - so a mid-run refresh shows
        which agent is currently in flight rather than a gap."""
        from . import store
        from .models import AgentStep

        step = store.create_step(
            self.run,
            spec.order,
            key=spec.key,
            label=spec.label,
            status=AgentStep.Status.PENDING,
        )
        _mark_running(step, input_text=self.handoff)
        return step

    def perform(self, spec: StepSpec) -> dict:
        from . import services
        from .models import AgentStep

        agent = _ROSTER_BY_ID[spec.key]

        tool_calls: list[dict] | None = None
        if agent.uses_tools:
            try:
                plan_raw = self._call(_tool_plan_system(agent, self.max_tools), self.handoff)
            except services.OllamaServiceError as exc:
                return self._stage_error(exc, tool_calls=None)
            planned = parse_tool_plan(plan_raw, agent, self.max_tools)
            tool_calls = [
                {
                    "tool": c["tool"],
                    "args": c["args"],
                    "observation": tools.run_tool(c["tool"], c["args"]),
                }
                for c in planned
            ]

        try:
            output = self._call(
                agent.system, _agent_user(self.run.query, self.handoff, tool_calls or [])
            )
        except services.OllamaServiceError as exc:
            return self._stage_error(exc, tool_calls=tool_calls)

        self.stage_outputs.append((agent.label, output))
        self.handoff = output  # feed forward to the next stage
        return {
            "status": AgentStep.Status.DONE,
            "output": output,
            "completed_at": dt.now(UTC),
            "tool_calls": tool_calls,
        }

    def result(self) -> Generator[str, None, Outcome]:
        if not self.stage_outputs:
            raise AbortedError("All sub-agents failed.")

        synth_user = f'The user asked: "{self.run.query}"\n\n' + "\n\n".join(
            f"### {label}\n{out}" for label, out in self.stage_outputs
        )
        answer = self._call(SYNTH_SYSTEM, synth_user)
        return Outcome(answer, fields={"agents": len(self.stage_outputs)})
        yield  # pragma: no cover - makes this a generator; the return above always wins

    # --- helpers --------------------------------------------------------------------

    @staticmethod
    def _stage_error(exc: Exception, *, tool_calls: list[dict] | None) -> dict:
        """A failed stage is DATA, not a failed run - the hand-off degrades and continues."""
        from .models import AgentStep

        return {
            "status": AgentStep.Status.ERROR,
            "error": str(exc),
            "completed_at": dt.now(UTC),
            "tool_calls": tool_calls,
        }

    def _call(self, system: str, user: str) -> str:
        from . import services

        return services.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            model=self.model,
        )


def run_multiagent(run: AgentRun, model: str = "") -> Generator[str]:
    """SSE generator. Route the roster, run sub-agents sequentially with hand-off, synthesise."""
    return drive(run, MultiAgentStrategy(run, model))
