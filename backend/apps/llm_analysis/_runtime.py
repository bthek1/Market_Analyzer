"""The shared agent loop (issue #6 phase 3).

``drive(run, strategy)`` owns the MECHANISM every workflow repeated by hand: the budget,
the per-step span, error isolation, persisting the step, emitting it, and writing the
terminal status. A ``Strategy`` contributes only the POLICY - what one step is, what to do
with its result, and what the run's answer is.

The pairing inside the loop is the point. ``store.create_step`` and ``step_event`` are two
adjacent lines *here*, so a workflow cannot write a step and forget to stream it - which is
exactly the defect that shipped as issue #7 and had to be fixed by hand in ``react``.

``intro`` and ``result`` are GENERATORS: they may need to emit events of their own (a plan,
a draft, react's forced final step) before the loop starts or after it ends. ``result``
returns its ``Outcome`` through ``return``, which ``yield from`` hands back to the driver.

``perform_streaming`` extends that to the step itself, for the one workflow that needs events
DURING the work rather than after it (``chat``, streaming a reply as it is written). It is
opt-in: ``BaseStrategy`` returns None and the driver falls back to ``perform``, so no other
workflow changes shape.

Not every workflow fits, and forcing one that doesn't would make both worse:

* ``chain`` frames a payload with no ``event`` discriminator and signals completion with a
  step-shaped ``__done__`` rather than a ``result`` event, so the driver's terminal path
  does not apply to it. It keeps its own loop.
* ``router`` persists no ``AgentStep`` rows at all - it classifies and spawns a chain run.
* The five fan-out workflows need a wave/batch step (issue #6 phase 4).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Protocol

from core.tracing import step_span

from ._events import fail, step_event, succeed

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator

    from .models import AgentRun, AgentStep


class AbortedError(Exception):
    """A strategy ending the run with an error that is not an Ollama failure.

    ``drive`` turns it into the terminal ``error`` event, so a strategy never has to know
    how a run is finished.
    """


@dataclass(frozen=True)
class StepSpec:
    """The identity of one step. Everything else is decided in ``perform``.

    ``order`` is stamped by the driver, so ``perform`` never has to infer its own position
    from accumulated state - which is how a strategy ends up silently one step out.
    """

    label: str = ""
    key: str = ""
    order: int = 0


@dataclass(frozen=True)
class Outcome:
    """A finished run: the answer, what to persist on the row, what to stream."""

    output: str
    meta: dict[str, Any] = field(default_factory=dict)
    fields: dict[str, Any] = field(default_factory=dict)


class Strategy(Protocol):
    """One workflow's policy. Instantiated per run, and free to hold mutable state -
    there is no separate context object to thread through every hook."""

    #: ``AgentRun.kind``, used to pick the step serializer.
    kind: str
    #: The SSE event name for this workflow's steps ("step" / "iteration" / ...).
    event: str
    #: Hard cap on iterations. ``drive`` enforces it; the strategy never counts.
    budget: int

    def intro(self) -> Generator[str]:
        """Events before the first step (started / plan / draft). May raise."""

    def next(self, order: int) -> StepSpec | None:
        """The next step, or None when this run is done stepping."""

    def pre_step(self, spec: StepSpec) -> AgentStep | None:
        """Optionally persist the step BEFORE its work, already marked running.

        Return None (the default) to let the driver create the row once the work is done.
        Returning a row is what keeps a mid-run refresh able to show the stage in flight -
        ``multiagent`` and ``autonomous`` both rely on it. The driver then UPDATES that row
        instead of creating one, and suppresses ``store``'s replayed span, because it is
        already holding an open one for this step.
        """

    def perform(self, spec: StepSpec) -> dict[str, Any]:
        """Do the step's work and return the kwargs to persist it with."""

    def perform_streaming(self, spec: StepSpec) -> Generator[str, None, dict[str, Any]] | None:
        """Optionally do the step's work as a GENERATOR, emitting events while it runs.

        Return None (the default) to use ``perform``. Returning a generator lets a step emit
        events WHILE its work happens rather than only after it - which ``after`` cannot do,
        because by then the work is finished and the events would arrive in one burst.

        This mirrors ``intro`` and ``result``, which are generators for the same reason. Only
        ``chat`` uses it: it is the one INTERACTIVE workflow, where a reply rendering as it
        is written is the difference between the feature working and not. A batch run gains
        nothing from it, so nothing else pays for it.
        """

    def after(self, step: AgentStep) -> Iterator[str]:
        """React to the persisted step: update state, emit extra events (replan)."""

    def result(self) -> Generator[str, None, Outcome]:
        """The run's answer. May emit further events first, and may raise."""

    def failure(self) -> dict[str, Any]:
        """Extra kwargs for ``fail`` - the partial output or meta to keep on a failed run."""


class BaseStrategy:
    """No-op defaults so a strategy writes only the hooks it actually needs."""

    def pre_step(self, spec: StepSpec) -> AgentStep | None:
        return None

    def perform_streaming(self, spec: StepSpec) -> Generator[str, None, dict[str, Any]] | None:
        return None

    def after(self, step: AgentStep) -> Iterator[str]:
        return iter(())

    def failure(self) -> dict[str, Any]:
        return {}


def drive(run: AgentRun, strategy: Strategy) -> Generator[str]:
    """Run ``strategy`` to completion as an SSE generator."""
    from . import services, store

    def _failed(exc: Exception) -> Generator[str]:
        yield from fail(run, str(exc), **strategy.failure())

    try:
        yield from strategy.intro()
    except (services.OllamaServiceError, AbortedError) as exc:
        yield from _failed(exc)
        return

    # EVERY hook is guarded, not just `perform`: `next` and `after` make LLM calls too
    # (eval_opt revises between iterations), and an escaping error would abandon the run
    # at `status="running"` with no terminal event - the exact failure stream_in_background
    # exists to prevent.
    order = 0
    while order < strategy.budget:
        try:
            spec = strategy.next(order)
        except (services.OllamaServiceError, AbortedError) as exc:
            yield from _failed(exc)
            return
        if spec is None:
            break
        spec = replace(spec, order=order)

        with step_span(run, order, key=spec.key, label=spec.label):
            try:
                row = strategy.pre_step(spec)
                # A streaming step emits its own events as it works and RETURNS the persist
                # kwargs through `yield from`, exactly as `result` returns its Outcome.
                streaming = strategy.perform_streaming(spec)
                if streaming is None:
                    fields = strategy.perform(spec)
                else:
                    fields = yield from streaming
            except (services.OllamaServiceError, AbortedError) as exc:
                yield from _failed(exc)
                return

            # Persisted and streamed together, once, for every workflow. Issue #7 was a
            # branch that did the first and not the second.
            #
            # `replay_span=False` on the update path: this block already holds an open
            # agent.step span, and store would otherwise replay a second one.
            step = (
                store.create_step(run, order, key=spec.key, label=spec.label, **fields)
                if row is None
                else store.update_step(row, kind=strategy.kind, replay_span=False, **fields)
            )
            yield step_event(step, strategy.event, kind=strategy.kind)

            try:
                yield from strategy.after(step)
            except (services.OllamaServiceError, AbortedError) as exc:
                yield from _failed(exc)
                return

        order += 1

    try:
        outcome = yield from strategy.result()
    except (services.OllamaServiceError, AbortedError) as exc:
        yield from _failed(exc)
        return

    yield from succeed(run, outcome.output, meta=outcome.meta, **outcome.fields)


# --- Fan-out workflows ----------------------------------------------------------------------


@dataclass(frozen=True)
class Wave:
    """One concurrent batch: N persisted steps whose LLM calls go out together.

    ``prompts`` is positional against ``rows`` - ``services.chat_many`` preserves order and
    isolates per-call errors, so result ``i`` belongs to row ``i``.
    """

    rows: list[AgentStep]
    prompts: list[list[dict[str, Any]]]
    temperatures: list[float] | None = None
    #: Emitted before the wave runs (dag announces which nodes are about to go).
    events: tuple[str, ...] = ()


class WaveStrategy(Protocol):
    """A workflow whose steps are decided together and executed concurrently."""

    kind: str
    event: str

    def intro(self) -> Generator[str]:
        """Decompose, persist the step rows, and emit the plan. May raise."""

    def next_wave(self, index: int) -> Wave | None:
        """The next batch, or None when the graph is exhausted."""

    def absorb(self, row: AgentStep, result: dict[str, Any]) -> None:
        """Fold one ``chat_many`` result into its row: mark it done or errored."""

    def result(self) -> Generator[str, None, Outcome]:
        """The run's answer. May raise ``AbortedError`` when every step failed."""

    def failure(self) -> dict[str, Any]:
        """Extra kwargs for ``fail``."""


def drive_waves(run: AgentRun, strategy: WaveStrategy, model: str | None = None) -> Generator[str]:
    """Run a fan-out ``strategy``: waves in order, steps within a wave concurrently.

    The per-step spans stay REPLAYED (``store.update_step`` -> ``record_completed_step``)
    rather than wrapped, and that is inherent rather than a shortcut: one ``chat_many``
    covers every step in the wave, so no per-step span can contain the call that produced
    it. What the driver can do is wrap the wave, which is why ``ollama.chat_many`` nests
    under ``agent.wave`` and the grouping is visible in the waterfall.
    """
    from core import tracing

    from . import services

    def _failed(exc: Exception) -> Generator[str]:
        yield from fail(run, str(exc), **strategy.failure())

    try:
        yield from strategy.intro()
    except (services.OllamaServiceError, AbortedError) as exc:
        yield from _failed(exc)
        return

    index = 0
    while True:
        try:
            wave = strategy.next_wave(index)
        except (services.OllamaServiceError, AbortedError) as exc:
            yield from _failed(exc)
            return
        if wave is None:
            break

        yield from wave.events

        # `**` unpacking, not a positional dict: `span` takes **attributes, and these keys
        # contain dots so they cannot be written as keyword arguments directly.
        with tracing.span(
            "agent.wave",
            **{
                "agent.kind": strategy.kind,
                "agent.wave": index,
                "agent.wave_size": len(wave.rows),
            },
        ):
            # `temperatures` is omitted rather than passed as None when a workflow does
            # not spread them - only `parallel`'s voting strategy does, and passing the
            # keyword unconditionally would change the call every other workflow makes.
            extra = {"temperatures": wave.temperatures} if wave.temperatures else {}
            results = services.chat_many(wave.prompts, model=model, **extra)
            for row, result in zip(wave.rows, results, strict=True):
                # Per-call error isolation is chat_many's: one failure never drops the rest.
                strategy.absorb(row, result)
                yield step_event(row, strategy.event, kind=strategy.kind)

        index += 1

    try:
        outcome = yield from strategy.result()
    except (services.OllamaServiceError, AbortedError) as exc:
        yield from _failed(exc)
        return

    yield from succeed(run, outcome.output, meta=outcome.meta, **outcome.fields)
