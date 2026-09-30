"""Evaluator-Optimizer (Reflection / Self-Critique) agent.

A generator LLM produces a draft answer; an evaluator LLM scores it against an explicit rubric and
returns actionable feedback; the generator revises. The loop repeats until the evaluator's score
clears a quality bar (``run.threshold``) or a bounded iteration budget (``run.max_iterations``) is
exhausted, returning the best-scoring draft seen. Unlike chain/route/parallel (where our code fixes
the path) the *number* of iterations is data-dependent - the evaluator's verdict decides when to
stop. Each iteration is surfaced as an SSE ``iteration`` event and persisted as an
``AgentStep``. Strictly sequential (revision depends on the prior critique) - no fan-out.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._events import event
from ._json import parse_json_object
from ._runtime import BaseStrategy, Outcome, StepSpec, drive

if TYPE_CHECKING:
    from collections.abc import Generator

    from .models import AgentRun

GENERATE_SYSTEM = (
    "You are a stock-market analyst. Answer the question directly and concretely, citing specific "
    "numbers where relevant. Do not hedge or pad. Return your answer in markdown."
)

EVALUATE_SYSTEM = (
    "You are a strict editor grading a stock-market analyst's answer. Score it 0-10 against these "
    "criteria: (1) directly answers the question; (2) factually grounded with no invented figures; "
    "(3) complete - covers the key angles; (4) concise, no hedging or filler. "
    "Respond with ONLY a single JSON object, nothing else:\n"
    '  {"score": <integer 0-10>, "feedback": "<one paragraph of concrete, actionable fixes>", '
    '"pass": <true|false>}\n'
    "Set pass=true only when the answer needs no further improvement."
)

REVISE_SYSTEM = (
    "You are a stock-market analyst revising your previous answer. Rewrite it to address the "
    "editor's feedback. Keep everything that was already correct. Return the full revised answer "
    "in markdown."
)


def _eval_user(query: str, draft: str) -> str:
    return f"Question:\n{query}\n\nAnswer to grade:\n{draft}"


def _revise_user(query: str, draft: str, feedback: str) -> str:
    return f"Question:\n{query}\n\nYour previous answer:\n{draft}\n\nEditor feedback:\n{feedback}"


class EvalOptStrategy(BaseStrategy):
    """Policy only: generate a draft, grade it, revise. The loop belongs to the driver."""

    kind = "eval_opt"
    event = "iteration"

    def __init__(self, run: AgentRun, model: str = ""):
        from . import store

        cfg = store.run_meta(run)
        self.run = run
        self.model = model or None
        self.budget = cfg.max_iterations
        self.threshold = cfg.threshold
        self.draft = ""
        self.best_draft, self.best_score = "", -1
        self.feedback = ""
        self.passed = False

    # --- lifecycle ------------------------------------------------------------------

    def intro(self) -> Generator[str]:
        yield event("started", max_iterations=self.budget, threshold=self.threshold)
        self.draft = self._call(GENERATE_SYSTEM, self.run.query)
        yield event("draft", draft=self.draft)

    def next(self, order: int) -> StepSpec | None:
        if self.passed:
            return None
        if order > 0:
            # Revise with the previous iteration's feedback before grading again. This is
            # the one workflow whose LLM call happens BETWEEN steps rather than inside one.
            self.draft = self._call(
                REVISE_SYSTEM, _revise_user(self.run.query, self.draft, self.feedback)
            )
        return StepSpec(label=f"iteration {order + 1}")

    def perform(self, spec: StepSpec) -> dict:
        raw = self._call(EVALUATE_SYSTEM, _eval_user(self.run.query, self.draft))

        try:
            verdict = parse_json_object(raw)
            score = max(0, min(10, int(verdict.get("score", 0))))
            feedback = str(verdict.get("feedback", ""))
            passed = bool(verdict.get("pass", False)) or score >= self.threshold
            status, error = "done", ""
        except (ValueError, TypeError):
            # Unparseable verdict: score 0 so the loop keeps refining, but flag it.
            score, feedback, passed = 0, "", False
            status, error = "error", "Could not parse evaluator output as JSON."

        self.feedback, self.passed = feedback, passed
        if score > self.best_score:
            self.best_draft, self.best_score = self.draft, score

        return {
            "status": status,
            "error": error,
            "draft": self.draft,
            "score": score,
            "feedback": feedback,
            "passed": passed,
        }

    def result(self) -> Generator[str, None, Outcome]:
        # The BEST draft, not the last - a revision can score worse than what it replaced.
        return Outcome(
            self.best_draft,
            meta={"best_score": self.best_score},
            fields={"iterations": self.run.steps.count(), "best_score": self.best_score},
        )
        yield  # pragma: no cover - makes this a generator; the return above always wins

    def failure(self) -> dict:
        # Keep the best draft seen so far on a run that died mid-refinement.
        return {"output": self.best_draft, "meta": {"best_score": self.best_score or None}}

    # --- helpers --------------------------------------------------------------------

    def _call(self, system: str, user: str) -> str:
        from . import services

        return services.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            model=self.model,
        )


def run_eval_opt(run: AgentRun, model: str = "") -> Generator[str]:
    """SSE generator. Generate -> Evaluate -> Revise loop, gated by the evaluator's score."""
    return drive(run, EvalOptStrategy(run, model))
