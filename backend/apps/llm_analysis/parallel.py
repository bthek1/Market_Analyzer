from __future__ import annotations

import json
from datetime import UTC
from datetime import datetime as dt
from typing import TYPE_CHECKING

from ._events import event
from ._runtime import AbortedError, BaseStrategy, Outcome, Wave, drive_waves
from .router import ANALYSIS_ASPECTS  # reuse the shipped sectioning aspects

if TYPE_CHECKING:
    from collections.abc import Generator

    from .models import AgentRun, AgentStep


VOTING_VERDICTS = ("buy", "hold", "sell")
VOTING_TEMPS = (0.3, 0.7, 1.0)  # cycled to length n for independent samples


# --- Shared sectioning logic (single source of truth for router + parallel) ---------------


def section_batches(query: str) -> list[list[dict]]:
    """Build one chat batch per ANALYSIS_ASPECTS entry (Parallelization / sectioning)."""
    return [
        [
            {
                "role": "system",
                "content": (
                    "You are a financial analyst. " + instruction + " Be precise and concise."
                ),
            },
            {"role": "user", "content": query},
        ]
        for _, instruction in ANALYSIS_ASPECTS
    ]


def aggregate_sections(query: str, sections: list[tuple[str, str]], model: str | None) -> str:
    """Synthesise per-aspect outputs into one analysis (single main-model call).

    ``sections`` is a list of ``(aspect_name, body)`` pairs.
    """
    from . import services

    aspect_text = "\n\n".join(f"### {name}\n{body}" for name, body in sections)
    agg_messages = [
        {
            "role": "user",
            "content": (
                'The user asked: "' + query + '"\n\n'
                "Three analysts each examined one aspect:\n\n" + aspect_text + "\n\n"
                "Synthesise these into one coherent, structured analysis. "
                "Resolve overlaps and highlight the key takeaways."
            ),
        }
    ]
    return services.chat(agg_messages, model=model)


# --- Voting helpers -----------------------------------------------------------------------


def _vote_prompt(query: str) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "You are an investment analyst on a panel. Based on the user's query, give a "
                "one-word verdict (buy, hold, or sell) and a one-sentence reason. "
                "Return ONLY valid JSON: "
                '{"verdict": "buy"|"hold"|"sell", "reason": "<one sentence>"}.'
            ),
        },
        {"role": "user", "content": query},
    ]


def _parse_vote(raw: str) -> tuple[str, str]:
    """Tolerantly parse a vote; unparseable / unknown verdict -> ('hold', reason)."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return "hold", raw.strip()[:200]

    verdict = str(data.get("verdict", "")).strip().lower()
    if verdict not in VOTING_VERDICTS:
        verdict = "hold"
    return verdict, str(data.get("reason", ""))


# --- Persistence helpers ------------------------------------------------------------------


def _mark_running(task: AgentStep) -> None:
    from . import store
    from .models import AgentStep

    store.update_step(task, status=AgentStep.Status.RUNNING, started_at=dt.now(UTC))


def _mark_done(task: AgentStep, *, output: str, vote: str = "") -> None:
    from . import store
    from .models import AgentStep

    store.update_step(
        task,
        status=AgentStep.Status.DONE,
        output=output,
        completed_at=dt.now(UTC),
        kind="parallel",
        vote=vote,
    )


def _mark_error(task: AgentStep, *, error: str, vote: str = "") -> None:
    from . import store
    from .models import AgentStep

    store.update_step(
        task,
        status=AgentStep.Status.ERROR,
        error=error,
        completed_at=dt.now(UTC),
        kind="parallel",
        vote=vote,
    )


# --- Public entrypoint --------------------------------------------------------------------


class ParallelStrategy(BaseStrategy):
    """Policy only: one wave, either sectioning or voting.

    The only workflow whose step rows are PRE-SEEDED at run creation - the aspects and the
    vote count are both known before any LLM call, so there is nothing to decompose.
    """

    kind = "parallel"
    event = "task"

    def __init__(self, run: AgentRun, model: str = ""):
        from . import store

        self.run = run
        self.model = model or None
        self.strategy = store.run_meta(run).strategy
        self.tasks: list[AgentStep] = []
        self.sections: list[tuple[str, str]] = []
        self.tally = dict.fromkeys(VOTING_VERDICTS, 0)
        self.any_ok = False

    @property
    def voting(self) -> bool:
        return self.strategy == self.run.Strategy.VOTING

    def intro(self) -> Generator[str]:
        self.tasks = list(self.run.steps.all())
        yield event(
            "started",
            strategy=self.strategy,
            tasks=[{"task_id": t.key, "label": t.label} for t in self.tasks],
        )

    def next_wave(self, index: int) -> Wave | None:
        if index > 0:
            return None

        for task in self.tasks:
            _mark_running(task)

        if self.voting:
            n = len(self.tasks)
            return Wave(
                rows=self.tasks,
                prompts=[_vote_prompt(self.run.query) for _ in range(n)],
                # Spread temperatures so the votes are independent samples rather than the
                # same answer N times.
                temperatures=[VOTING_TEMPS[i % len(VOTING_TEMPS)] for i in range(n)],
            )
        return Wave(rows=self.tasks, prompts=section_batches(self.run.query))

    def absorb(self, row: AgentStep, result: dict) -> None:
        if self.voting:
            if result["ok"] is not None:
                self.any_ok = True
                verdict, reason = _parse_vote(result["ok"])
                self.tally[verdict] += 1
                _mark_done(row, output=reason or result["ok"], vote=verdict)
            else:
                _mark_error(row, error=result["error"])
            return

        name = ANALYSIS_ASPECTS[self.tasks.index(row)][0]
        if result["ok"] is not None:
            self.any_ok = True
            _mark_done(row, output=result["ok"])
            self.sections.append((name, result["ok"]))
        else:
            _mark_error(row, error=result["error"])
            self.sections.append((name, f"(aspect failed: {result['error']})"))

    def result(self) -> Generator[str, None, Outcome]:
        if not self.any_ok:
            raise AbortedError(
                "All vote calls failed." if self.voting else "All aspect calls failed."
            )

        if self.voting:
            output = _aggregate_votes(
                self.run.query, self.tally, _consensus(self.tally), self.model
            )
            return Outcome(
                output,
                meta={"tally": self.tally},
                fields={"strategy": self.strategy, "tally": self.tally},
            )

        output = aggregate_sections(self.run.query, self.sections, self.model)
        return Outcome(
            output, meta={"tally": None}, fields={"strategy": self.strategy, "tally": None}
        )
        yield  # pragma: no cover - makes this a generator; the returns above always win

    def failure(self) -> dict:
        # The tally is only meaningful once votes have landed; sectioning never has one.
        return {"meta": {"tally": self.tally if (self.voting and self.any_ok) else None}}


def run_parallel(run: AgentRun, model: str = "") -> Generator[str]:
    """SSE generator. One concurrent wave: sectioning aspects, or N independent votes."""
    strategy = ParallelStrategy(run, model)
    return drive_waves(run, strategy, model=strategy.model)


def _consensus(tally: dict[str, int]) -> str:
    """Majority verdict; ties resolve conservatively to 'hold'."""
    top = max(tally.values())
    winners = [v for v in VOTING_VERDICTS if tally[v] == top]
    return winners[0] if len(winners) == 1 else "hold"


def _aggregate_votes(query: str, tally: dict[str, int], consensus: str, model: str | None) -> str:
    from . import services

    agg_messages = [
        {
            "role": "user",
            "content": (
                'The user asked: "' + query + '"\n\n'
                "An analyst panel voted: "
                + ", ".join(f"{v}={tally[v]}" for v in VOTING_VERDICTS)
                + f". The consensus recommendation is {consensus.upper()}.\n\n"
                "Write the consensus recommendation in a short paragraph and note any dissent."
            ),
        }
    ]
    return services.chat(agg_messages, model=model)
