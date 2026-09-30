"""The shared agent loop (issue #6 phase 3).

The per-workflow suites are the behavioural contract and all pass unmodified through the
migration. These tests cover the DRIVER itself - the mechanism the four sequential
workflows used to each own a copy of - with a strategy that makes no LLM calls, so the
failure modes are visible rather than mocked around.
"""

from __future__ import annotations

import json
from datetime import UTC
from datetime import datetime as dt
from unittest.mock import patch

import pytest

from apps.llm_analysis import store
from apps.llm_analysis._runtime import (
    AbortedError,
    BaseStrategy,
    Outcome,
    StepSpec,
    Wave,
    drive,
    drive_waves,
)
from apps.llm_analysis.models import AgentRun, AgentStep
from apps.llm_analysis.services import OllamaServiceError


def _events(gen):
    return [json.loads(e[len("data: ") :].strip()) for e in gen]


class FakeStrategy(BaseStrategy):
    """A react-shaped strategy with every hook riggable. Defaults to a clean 2-step run."""

    event = "step"

    def __init__(
        self,
        run,
        *,
        kind="react",
        budget=3,
        steps=2,
        intro_raises=None,
        next_raises=None,
        perform_raises=None,
        after_raises=None,
        result_raises=None,
        after_events=0,
        result_events=0,
        failure=None,
        pre_row=None,
    ):
        self.run = run
        self.kind = kind
        self.budget = budget
        self.steps = steps
        self.performed = 0
        self.seen: list[AgentStep] = []
        self.orders: list[int] = []
        self._intro_raises = intro_raises
        self._next_raises = next_raises
        self._perform_raises = perform_raises
        self._after_raises = after_raises
        self._result_raises = result_raises
        self._after_events = after_events
        self._result_events = result_events
        self._failure = failure or {}
        self._pre_row = pre_row

    def intro(self):
        if self._intro_raises:
            raise self._intro_raises
        yield 'data: {"event": "started"}\n\n'

    def next(self, order):
        if self._next_raises and order == 1:
            raise self._next_raises
        self.orders.append(order)
        return None if self.performed >= self.steps else StepSpec(label=f"step {order + 1}")

    def perform(self, spec):
        if self._perform_raises:
            raise self._perform_raises
        self.performed += 1
        # `thought` is react meta; store validates per kind, so only send it for react.
        extra = {"thought": f"t{self.performed}"} if self.kind == "react" else {}
        # `completed_at` matters: the replayed span store would emit is a no-op without
        # it, which would make the double-span test below pass for the wrong reason.
        return {"status": AgentStep.Status.DONE, "completed_at": dt.now(UTC), **extra}

    def after(self, step):
        self.seen.append(step)
        if self._after_raises:
            raise self._after_raises
        for i in range(self._after_events):
            yield f'data: {{"event": "extra", "i": {i}}}\n\n'

    def pre_step(self, spec):
        return self._pre_row

    def result(self):
        if self._result_raises:
            raise self._result_raises
        for i in range(self._result_events):
            yield f'data: {{"event": "late", "i": {i}}}\n\n'
        return Outcome("the answer", meta={}, fields={"steps": self.performed})

    def failure(self):
        return self._failure


@pytest.fixture
def run(user):
    return store.create_run(user, query="q", model="m", kind="react", max_steps=3)


@pytest.mark.django_db
class TestHappyPath:
    def test_intro_steps_then_result(self, run):
        events = _events(drive(run, FakeStrategy(run)))

        assert [e["event"] for e in events] == ["started", "step", "step", "result"]
        assert events[-1]["output"] == "the answer"
        assert events[-1]["steps"] == 2

    def test_every_step_is_persisted_and_streamed(self, run):
        """The pairing that makes issue #7's class impossible: the driver writes the row
        and emits it as two adjacent lines, so no workflow can do one without the other."""
        events = _events(drive(run, FakeStrategy(run, steps=3)))

        streamed = [e for e in events if e["event"] == "step"]
        assert len(streamed) == run.steps.count() == 3
        assert [e["order"] for e in streamed] == [0, 1, 2]

    def test_run_finishes_done(self, run):
        list(drive(run, FakeStrategy(run)))
        run.refresh_from_db()

        assert run.status == AgentRun.Status.DONE
        assert run.output == "the answer"
        assert run.completed_at is not None

    def test_after_events_ride_between_steps(self, run):
        events = _events(drive(run, FakeStrategy(run, steps=2, after_events=1)))

        assert [e["event"] for e in events] == [
            "started",
            "step",
            "extra",
            "step",
            "extra",
            "result",
        ]

    def test_result_may_emit_before_finishing(self, run):
        """react's forced final step is emitted from `result`, after the loop has ended."""
        events = _events(drive(run, FakeStrategy(run, result_events=1)))

        assert [e["event"] for e in events][-2:] == ["late", "result"]

    def test_after_receives_the_persisted_row(self, run):
        strategy = FakeStrategy(run)
        list(drive(run, strategy))

        assert [s.pk for s in strategy.seen] == list(
            run.steps.order_by("order").values_list("pk", flat=True)
        )


@pytest.mark.django_db
class TestBudget:
    def test_driver_enforces_the_budget_not_the_strategy(self, run):
        """A strategy that never returns None still stops. The budget is the driver's."""
        events = _events(drive(run, FakeStrategy(run, budget=2, steps=99)))

        assert len([e for e in events if e["event"] == "step"]) == 2
        assert run.steps.count() == 2
        assert events[-1]["event"] == "result"

    def test_strategy_can_stop_early(self, run):
        events = _events(drive(run, FakeStrategy(run, budget=9, steps=1)))

        assert len([e for e in events if e["event"] == "step"]) == 1

    def test_zero_budget_still_produces_a_terminal_event(self, run):
        events = _events(drive(run, FakeStrategy(run, budget=0)))

        assert [e["event"] for e in events] == ["started", "result"]
        run.refresh_from_db()
        assert run.status == AgentRun.Status.DONE


@pytest.mark.django_db
class TestEveryHookIsGuarded:
    """`next` and `after` make LLM calls too (eval_opt revises between iterations). An
    escaping error would leave the run at status="running" with no terminal event - the
    exact orphaning that stream_in_background exists to prevent."""

    @pytest.mark.parametrize(
        ("hook", "exc"),
        [
            ("intro_raises", OllamaServiceError("boom")),
            ("intro_raises", AbortedError("no usable plan")),
            ("next_raises", OllamaServiceError("boom")),
            ("perform_raises", OllamaServiceError("boom")),
            ("perform_raises", AbortedError("gave up")),
            ("after_raises", OllamaServiceError("boom")),
            ("result_raises", OllamaServiceError("boom")),
            ("result_raises", AbortedError("no answer")),
        ],
    )
    def test_failure_in_any_hook_ends_the_run(self, run, hook, exc):
        events = _events(drive(run, FakeStrategy(run, **{hook: exc})))

        assert events[-1]["event"] == "error"
        assert events[-1]["error"] == str(exc)
        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR
        assert run.completed_at is not None

    def test_failure_keeps_the_strategys_partial_output(self, user):
        """eval_opt keeps its best-scoring draft on a run that died mid-refinement.

        Driven as an eval_opt run because `best_score` is only a valid meta key for that
        kind - `store` validates every write, and the driver does not bypass it."""
        run = store.create_run(user, query="q", model="m", kind="eval_opt", max_iterations=3)
        strategy = FakeStrategy(
            run,
            kind="eval_opt",
            perform_raises=OllamaServiceError("boom"),
            failure={"output": "best so far", "meta": {"best_score": 6}},
        )

        list(drive(run, strategy))

        run.refresh_from_db()
        assert run.output == "best so far"
        assert run.meta["best_score"] == 6

    def test_an_unexpected_exception_is_not_swallowed(self, run):
        """Only the two declared failure types become a terminal error event. A genuine
        bug must surface, not be reported to the user as a failed LLM call."""
        with pytest.raises(ZeroDivisionError):
            list(drive(run, FakeStrategy(run, perform_raises=ZeroDivisionError())))


@pytest.mark.django_db
class TestStepSpecOrder:
    def test_the_driver_stamps_the_order_on_the_spec(self, run):
        """A strategy must never infer its position from accumulated state - plan_execute
        indexes into a plan a replan can rewrite mid-loop, so an inferred index is one bug
        away from reading the wrong step."""
        seen = []

        class Recording(FakeStrategy):
            def perform(self, spec):
                seen.append(spec.order)
                return super().perform(spec)

        list(drive(run, Recording(run, steps=3)))

        assert seen == [0, 1, 2]

    def test_a_strategys_own_order_is_overwritten(self, run):
        """`next` may return a bare StepSpec; the driver owns the counter either way."""

        class Lying(FakeStrategy):
            def next(self, order):
                spec = super().next(order)
                return None if spec is None else StepSpec(label=spec.label, order=99)

        seen = []

        class Recording(Lying):
            def perform(self, spec):
                seen.append(spec.order)
                return super().perform(spec)

        list(drive(run, Recording(run, steps=2)))

        assert seen == [0, 1]


@pytest.mark.django_db
class TestSpans:
    def test_the_step_span_wraps_the_work(self, run, spans):
        """A WRAPPER span is open while the step runs, so the step's LLM and tool calls
        nest INSIDE it. That is the difference from the replayed spans the fan-out
        workflows still use, where the duration is right but nothing nests."""
        from core import tracing

        class Nesting(FakeStrategy):
            def perform(self, spec):
                with tracing.span("ollama.chat"):
                    pass
                return super().perform(spec)

        with tracing.span("agent.run"):
            list(drive(run, Nesting(run, steps=1)))

        by_name = {s.name: s for s in spans.get_finished_spans()}
        step, chat = by_name["agent.step"], by_name["ollama.chat"]
        assert step.parent.span_id == by_name["agent.run"].context.span_id
        assert chat.parent.span_id == step.context.span_id

    def test_one_span_per_step(self, run, spans):
        list(drive(run, FakeStrategy(run, steps=3)))

        recorded = [s for s in spans.get_finished_spans() if s.name == "agent.step"]
        assert len(recorded) == 3


class FakeWaveStrategy(BaseStrategy):
    """A fan-out strategy with every hook riggable. Defaults to two waves of two."""

    kind = "orchestrator"
    event = "worker"

    def __init__(
        self,
        run,
        *,
        waves=2,
        width=2,
        intro_raises=None,
        next_wave_raises=None,
        result_raises=None,
        temperatures=None,
    ):
        self.run = run
        self.waves = waves
        self.width = width
        self.rows: list[AgentStep] = []
        self.absorbed: list[tuple[str, dict]] = []
        self.wave_sizes: list[int] = []
        self._intro_raises = intro_raises
        self._next_wave_raises = next_wave_raises
        self._result_raises = result_raises
        self._temperatures = temperatures

    def intro(self):
        if self._intro_raises:
            raise self._intro_raises
        for i in range(self.waves * self.width):
            self.rows.append(
                store.create_step(
                    self.run, i, key=f"w{i}", label=f"W{i}", status=AgentStep.Status.PENDING
                )
            )
        yield 'data: {"event": "plan"}\n\n'

    def next_wave(self, index):
        if self._next_wave_raises and index == 1:
            raise self._next_wave_raises
        if index >= self.waves:
            return None
        rows = self.rows[index * self.width : (index + 1) * self.width]
        self.wave_sizes.append(len(rows))
        return Wave(
            rows=rows,
            prompts=[[{"role": "user", "content": r.key}] for r in rows],
            temperatures=self._temperatures,
            events=(f'data: {{"event": "wave", "index": {index}}}\n\n',),
        )

    def absorb(self, row, result):
        self.absorbed.append((row.key, result))
        store.update_step(
            row,
            kind=self.kind,
            status=AgentStep.Status.DONE if result["ok"] else AgentStep.Status.ERROR,
            output=result["ok"] or "",
            error=result["error"] or "",
            completed_at=dt.now(UTC),
        )

    def result(self):
        if self._result_raises:
            raise self._result_raises
        return Outcome("synthesised", fields={"workers": len(self.rows)})
        yield  # pragma: no cover

    def failure(self):
        return {}


def _ok_many(*outputs):
    return [{"ok": o, "error": None} if o else {"ok": None, "error": "boom"} for o in outputs]


@pytest.mark.django_db
class TestWaveDriver:
    @pytest.fixture
    def orch_run(self, user):
        return store.create_run(user, query="q", model="m", kind="orchestrator", max_workers=4)

    def test_waves_run_in_order_steps_within_a_wave_together(self, orch_run):
        strategy = FakeWaveStrategy(orch_run)
        with patch(
            "apps.llm_analysis.services.chat_many",
            side_effect=[_ok_many("a", "b"), _ok_many("c", "d")],
        ) as chat_many:
            events = _events(drive_waves(orch_run, strategy))

        # One chat_many per wave, each carrying the whole wave's prompts.
        assert chat_many.call_count == 2
        assert [len(c.args[0]) for c in chat_many.call_args_list] == [2, 2]
        assert [e["event"] for e in events] == [
            "plan",
            "wave",
            "worker",
            "worker",
            "wave",
            "worker",
            "worker",
            "result",
        ]

    def test_every_row_is_absorbed_and_streamed(self, orch_run):
        strategy = FakeWaveStrategy(orch_run)
        with patch(
            "apps.llm_analysis.services.chat_many",
            side_effect=[_ok_many("a", "b"), _ok_many("c", "d")],
        ):
            events = _events(drive_waves(orch_run, strategy))

        streamed = [e for e in events if e["event"] == "worker"]
        assert len(streamed) == orch_run.steps.count() == 4
        assert [k for k, _ in strategy.absorbed] == ["w0", "w1", "w2", "w3"]

    def test_one_failure_never_drops_the_rest_of_the_wave(self, orch_run):
        """Per-call error isolation is chat_many's; the driver must not short-circuit."""
        strategy = FakeWaveStrategy(orch_run, waves=1, width=3)
        with patch("apps.llm_analysis.services.chat_many", side_effect=[_ok_many("a", None, "c")]):
            events = _events(drive_waves(orch_run, strategy))

        streamed = [e for e in events if e["event"] == "worker"]
        assert [e["status"] for e in streamed] == ["done", "error", "done"]
        assert events[-1]["event"] == "result"

    def test_temperatures_are_omitted_when_unused(self, orch_run):
        """Only parallel's voting spreads them; passing the keyword unconditionally would
        change the call every other workflow makes."""
        with patch("apps.llm_analysis.services.chat_many", return_value=_ok_many("a", "b")) as cm:
            list(drive_waves(orch_run, FakeWaveStrategy(orch_run, waves=1)))

        assert "temperatures" not in cm.call_args.kwargs

    def test_temperatures_are_passed_when_present(self, orch_run):
        with patch("apps.llm_analysis.services.chat_many", return_value=_ok_many("a", "b")) as cm:
            list(
                drive_waves(orch_run, FakeWaveStrategy(orch_run, waves=1, temperatures=[0.3, 0.7]))
            )

        assert cm.call_args.kwargs["temperatures"] == [0.3, 0.7]

    @pytest.mark.parametrize(
        ("hook", "exc"),
        [
            ("intro_raises", OllamaServiceError("boom")),
            ("intro_raises", AbortedError("no usable decomposition")),
            ("next_wave_raises", OllamaServiceError("boom")),
            ("result_raises", AbortedError("All workers failed.")),
            ("result_raises", OllamaServiceError("boom")),
        ],
    )
    def test_failure_in_any_hook_ends_the_run(self, orch_run, hook, exc):
        with patch("apps.llm_analysis.services.chat_many", return_value=_ok_many("a", "b")):
            events = _events(drive_waves(orch_run, FakeWaveStrategy(orch_run, **{hook: exc})))

        assert events[-1]["event"] == "error"
        assert events[-1]["error"] == str(exc)
        orch_run.refresh_from_db()
        assert orch_run.status == AgentRun.Status.ERROR


@pytest.mark.django_db
class TestWaveSpans:
    """What the wave driver CAN do for traces, and what it cannot.

    One `chat_many` covers every step in the wave, so no per-step span can contain the
    call that produced it - the per-step spans stay replayed from stored timestamps. The
    wave itself IS wrappable, so the fan-out is at least visible as a group.
    """

    @pytest.fixture
    def orch_run(self, user):
        return store.create_run(user, query="q", model="m", kind="orchestrator", max_workers=4)

    def test_chat_many_nests_under_the_wave_span(self, orch_run, spans):
        from core import tracing

        def fake_chat_many(prompts, **kwargs):
            with tracing.span("ollama.chat_many"):
                pass
            return _ok_many("a", "b")

        with (
            patch("apps.llm_analysis.services.chat_many", side_effect=fake_chat_many),
            tracing.span("agent.run"),
        ):
            list(drive_waves(orch_run, FakeWaveStrategy(orch_run, waves=1)))

        by_name = {s.name: s for s in spans.get_finished_spans()}
        assert by_name["agent.wave"].parent.span_id == by_name["agent.run"].context.span_id
        assert by_name["ollama.chat_many"].parent.span_id == by_name["agent.wave"].context.span_id

    def test_one_wave_span_per_wave_carrying_its_width(self, orch_run, spans):
        with patch(
            "apps.llm_analysis.services.chat_many",
            side_effect=[_ok_many("a", "b"), _ok_many("c", "d")],
        ):
            list(drive_waves(orch_run, FakeWaveStrategy(orch_run, waves=2, width=2)))

        waves = [s for s in spans.get_finished_spans() if s.name == "agent.wave"]
        assert [s.attributes["agent.wave"] for s in waves] == [0, 1]
        assert [s.attributes["agent.wave_size"] for s in waves] == [2, 2]


@pytest.mark.django_db
class TestPreStep:
    """`pre_step` is what lets a workflow persist its step BEFORE the work, so a mid-run
    refresh shows the stage in flight. `multiagent` and `autonomous` both rely on it."""

    def test_the_prepersisted_row_is_updated_not_duplicated(self, run):
        row = store.create_step(run, 0, key="k0", status=AgentStep.Status.RUNNING)
        strategy = FakeStrategy(run, steps=1, pre_row=row)

        events = _events(drive(run, strategy))

        assert run.steps.count() == 1, "the driver created a second row"
        row.refresh_from_db()
        assert row.status == AgentStep.Status.DONE
        assert [e["event"] for e in events] == ["started", "step", "result"]

    def test_the_row_is_visible_while_the_step_runs(self, run):
        """The regression this hook exists to prevent: without it the row appears only
        once the step finishes, so a refresh mid-stage shows a gap instead of progress."""
        row = store.create_step(run, 0, key="k0", status=AgentStep.Status.RUNNING)

        class Checking(FakeStrategy):
            def perform(self, spec):
                # Mid-work: what a refresh-restore would read right now.
                assert self.run.steps.filter(status=AgentStep.Status.RUNNING).count() == 1
                return super().perform(spec)

        list(drive(run, Checking(run, steps=1, pre_row=row)))

        assert run.steps.get().status == AgentStep.Status.DONE

    def test_exactly_one_span_per_prepersisted_step(self, run, spans):
        """`store.update_step` replays a span on terminal status, and the driver already
        holds an open one - hence `replay_span=False`. Without it every driven step that
        pre-persists would emit TWO agent.step spans for one step."""
        row = store.create_step(
            run, 0, key="k0", status=AgentStep.Status.RUNNING, started_at=dt.now(UTC)
        )

        list(drive(run, FakeStrategy(run, steps=1, pre_row=row)))

        recorded = [s for s in spans.get_finished_spans() if s.name == "agent.step"]
        assert len(recorded) == 1

    def test_default_is_no_prepersisted_row(self, run):
        """Workflows that do not need it say nothing - BaseStrategy returns None."""
        strategy = FakeStrategy(run, steps=2)

        list(drive(run, strategy))

        assert run.steps.count() == 2


@pytest.mark.django_db
class TestStoreReplaySpanFlag:
    def test_update_step_replays_by_default(self, run, spans):
        # Both timestamps are needed: the replay reconstructs the step's own duration.
        step = store.create_step(
            run, 0, key="k", status=AgentStep.Status.RUNNING, started_at=dt.now(UTC)
        )

        store.update_step(step, status=AgentStep.Status.DONE, completed_at=dt.now(UTC))

        assert [s.name for s in spans.get_finished_spans()] == ["agent.step"]

    def test_update_step_can_suppress_the_replay(self, run, spans):
        step = store.create_step(
            run, 0, key="k", status=AgentStep.Status.RUNNING, started_at=dt.now(UTC)
        )

        store.update_step(
            step, status=AgentStep.Status.DONE, completed_at=dt.now(UTC), replay_span=False
        )

        assert [s.name for s in spans.get_finished_spans()] == []
