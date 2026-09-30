"""Orchestrator-Workers agent.

A lead orchestrator LLM dynamically decomposes the user's question into a set of independent
subtasks (each an instruction plus an optional read-only tool). The subtasks fan out concurrently
to worker LLMs (via ``services.chat_many``), and a final synthesis call folds the worker outputs
into the answer.

Unlike ``parallel``/sectioning (whose sections are a fixed, hard-coded ``ANALYSIS_ASPECTS``
list) the orchestrator invents the subtasks at runtime from the query, so their number, focus,
and chosen tools vary per question. Unlike ``plan_execute`` (an ordered, sequential plan where
each step depends on the prior) the subtasks here are independent and run in parallel. Tools are
the same read-only DB lookups ReAct/plan-execute use (see ``tools.py``); the decomposition is
hard-capped by ``run.max_workers``. Each subtask is surfaced as an SSE ``worker`` event and
persisted as an ``AgentStep``.
"""

from __future__ import annotations

import json
from datetime import UTC
from datetime import datetime as dt
from typing import TYPE_CHECKING

from . import tools
from ._events import event
from ._json import parse_json_object
from ._runtime import AbortedError, BaseStrategy, Outcome, Wave, drive_waves

if TYPE_CHECKING:
    from collections.abc import Generator

    from .models import AgentRun, AgentStep


def _orchestrate_system(max_workers: int) -> str:
    return (
        "You are a research orchestrator. Break the user's question into a set of at most "
        f"{max_workers} INDEPENDENT subtasks that can be worked on in parallel. For each subtask "
        "optionally pick ONE tool that fetches the data it needs (or use null for a "
        "pure-reasoning subtask). Respond with ONLY a single JSON object, nothing else:\n"
        '  {"subtasks": [{"task": "<what the worker should produce>", '
        '"focus": "<short label>", "tool": "<tool name or null>", "args": {<arguments>}}]}\n\n'
        "Available tools:\n" + tools.tool_catalogue() + "\n\n"
        "Rules: subtasks MUST be independent - no subtask may depend on another's result. "
        "For dependent or ordered work, prefer fewer, broader subtasks. Tickers are uppercase."
    )


WORKER_SYSTEM = (
    "You are a focused financial-analysis worker handling ONE subtask. Use the tool observation "
    "(if given) to produce a concise, factual result for your subtask only. Do not answer the "
    "whole question; do not invent data."
)

SYNTH_SYSTEM = (
    "Several workers each handled one subtask. Synthesise their outputs into one coherent, "
    "structured analysis; resolve overlaps and highlight the key takeaways. Write clean markdown."
)


def _slug(focus: str, i: int, seen: set[str]) -> str:
    """Lowercased, deduped worker_id from the focus label (fallback ``worker_{i}``)."""
    base = "".join(c if c.isalnum() else "_" for c in str(focus).strip().lower()).strip("_")
    base = base or f"worker_{i}"
    base = base[:50]
    candidate = base
    n = 1
    while candidate in seen:
        candidate = f"{base[:46]}_{n}"
        n += 1
    seen.add(candidate)
    return candidate


def parse_subtasks(raw: str, max_workers: int) -> list[dict]:
    """Parse an orchestrator response into a normalised, capped list of subtask dicts.

    Each entry is ``{"task", "focus", "tool", "args"}``. Tolerant of a bare list, a missing
    ``args``/``focus``, and a ``tool`` of ``""``/``"null"``/``"none"`` (-> None). Raises ValueError
    when no usable subtask remains.
    """
    subtasks = None
    try:
        data = parse_json_object(raw)
        if isinstance(data.get("subtasks"), list):
            subtasks = data["subtasks"]
    except ValueError:
        pass

    if subtasks is None:
        # Tolerate a bare JSON list of subtasks (no wrapping {"subtasks": ...} object).
        text = raw.strip()
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end > start:
            try:
                subtasks = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                subtasks = None

    if not isinstance(subtasks, list) or not subtasks:
        raise ValueError("decomposition was empty")

    normalised: list[dict] = []
    for entry in subtasks[:max_workers]:
        if not isinstance(entry, dict):
            continue
        task = str(entry.get("task", "")).strip()
        if not task:
            continue
        tool = entry.get("tool")
        if tool in ("", "null", "none", "None"):
            tool = None
        args = entry.get("args")
        focus = str(entry.get("focus", "")).strip() or task[:40]
        normalised.append(
            {
                "task": task,
                "focus": focus,
                "tool": tool,
                "args": args if isinstance(args, dict) else None,
            }
        )
    if not normalised:
        raise ValueError("decomposition had no usable subtasks")
    return normalised


def _worker_prompt(query: str, subtask: dict, observation: str) -> list[dict]:
    user = f"Overall question (for context only): {query}\n\nYour subtask: {subtask['task']}\n" + (
        f"Tool observation: {observation}\n" if observation else ""
    )
    return [
        {"role": "system", "content": WORKER_SYSTEM},
        {"role": "user", "content": user},
    ]


# --- Persistence helpers ------------------------------------------------------------------


def _mark_running(worker: AgentStep) -> None:
    from . import store
    from .models import AgentStep

    store.update_step(worker, status=AgentStep.Status.RUNNING, started_at=dt.now(UTC))


def _mark_done(worker: AgentStep, *, output: str) -> None:
    from . import store
    from .models import AgentStep

    store.update_step(worker, status=AgentStep.Status.DONE, output=output, completed_at=dt.now(UTC))


def _mark_error(worker: AgentStep, *, error: str) -> None:
    from . import store
    from .models import AgentStep

    store.update_step(worker, status=AgentStep.Status.ERROR, error=error, completed_at=dt.now(UTC))


# --- Public entrypoint --------------------------------------------------------------------


class OrchestratorStrategy(BaseStrategy):
    """Policy only: decompose into independent subtasks, then one concurrent wave.

    A single wave by construction - the subtasks are independent by contract, which is
    precisely what distinguishes this workflow from ``dag``.
    """

    kind = "orchestrator"
    event = "worker"

    def __init__(self, run: AgentRun, model: str = ""):
        from . import store

        self.run = run
        self.model = model or None
        self.max_workers = store.run_meta(run).max_workers
        self.subtasks: list[dict] = []
        self.workers: list[AgentStep] = []
        self.outputs: list[str] = []
        self.any_ok = False

    def intro(self) -> Generator[str]:
        from . import store
        from .models import AgentStep

        yield event("started", max_workers=self.max_workers)

        raw = self._call(_orchestrate_system(self.max_workers), self.run.query)
        try:
            self.subtasks = parse_subtasks(raw, self.max_workers)
        except ValueError:
            raise AbortedError("Orchestrator did not return a usable decomposition.") from None

        store.update_run(self.run, plan=self.subtasks)

        # Worker rows are created AFTER the decomposition - the run does not know how many
        # there will be until the orchestrator says so.
        seen: set[str] = set()
        self.workers = [
            store.create_step(
                self.run,
                i,
                status=AgentStep.Status.PENDING,
                key=_slug(st["focus"], i, seen),
                label=st["focus"],
                task=st["task"],
                tool=st["tool"] or "",
                tool_args=st["args"],
            )
            for i, st in enumerate(self.subtasks)
        ]
        yield event("plan", subtasks=self.subtasks)

    def next_wave(self, index: int) -> Wave | None:
        from . import store

        if index > 0:
            return None

        # Tool lookups are synchronous read-only DB reads; they never raise.
        observations = [
            tools.run_tool(st["tool"], st["args"] or {}) if st["tool"] else ""
            for st in self.subtasks
        ]
        for worker, obs in zip(self.workers, observations, strict=True):
            store.update_step(worker, kind=self.kind, observation=obs)
            _mark_running(worker)

        return Wave(
            rows=self.workers,
            prompts=[
                _worker_prompt(self.run.query, st, obs)
                for st, obs in zip(self.subtasks, observations, strict=True)
            ],
        )

    def absorb(self, row: AgentStep, result: dict) -> None:
        if result["ok"] is not None:
            self.any_ok = True
            _mark_done(row, output=result["ok"])
            self.outputs.append(result["ok"])
        else:
            _mark_error(row, error=result["error"])
            self.outputs.append(f"(worker failed: {result['error']})")

    def result(self) -> Generator[str, None, Outcome]:
        if not self.any_ok:
            raise AbortedError("All workers failed.")

        synth_user = f'The user asked: "{self.run.query}"\n\n' + "\n\n".join(
            f"### {st['focus']}\n{out}" for st, out in zip(self.subtasks, self.outputs, strict=True)
        )
        answer = self._call(SYNTH_SYSTEM, synth_user)
        return Outcome(answer, fields={"workers": len(self.workers)})
        yield  # pragma: no cover - makes this a generator; the return above always wins

    def _call(self, system: str, user: str) -> str:
        from . import services

        return services.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            model=self.model,
        )


def run_orchestrator(run: AgentRun, model: str = "") -> Generator[str]:
    """SSE generator. Decompose dynamically, run tool lookups, fan out workers, synthesise."""
    strategy = OrchestratorStrategy(run, model)
    return drive_waves(run, strategy, model=strategy.model)
