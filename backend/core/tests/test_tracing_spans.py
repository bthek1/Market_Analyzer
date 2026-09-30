"""Manual spans for the LLM and agent workflows (issue #5 phase 4).

These assert against a REAL in-memory span exporter rather than mocks, because the
thing most likely to break here is not whether a span is created but whether it lands
in the right PLACE in the tree. Two of the seams instrumented below hand work to
another thread, and OTel context rides a ContextVar that a bare thread does not
inherit - so a regression does not fail loudly, it silently reparents the work into its
own root trace and the waterfall quietly stops showing the fan-out.

That exact failure already happened twice on this issue (the wsgi ordering bug and the
4xx log lines), both times invisible to config review.
"""

import json
from unittest.mock import patch

import pytest

from core import tracing

# The `spans` fixture lives in backend/conftest.py - the agent-runtime tests need it too.


def names(exporter):
    return [s.name for s in exporter.get_finished_spans()]


def by_name(exporter, name):
    return next(s for s in exporter.get_finished_spans() if s.name == name)


class TestSpanHelper:
    def test_span_records_attributes(self, spans):
        with tracing.span("unit.test", **{"a.b": 1, "a.c": "x"}):
            pass

        span = by_name(spans, "unit.test")
        assert span.attributes["a.b"] == 1
        assert span.attributes["a.c"] == "x"

    def test_none_attributes_are_dropped_not_stringified(self, spans):
        """A missing temperature must not render as the string 'None' in Tempo."""
        with tracing.span("unit.test", present=1, absent=None):
            pass

        assert "absent" not in by_name(spans, "unit.test").attributes

    def test_an_unserialisable_attribute_does_not_break_the_caller(self, spans):
        with tracing.span("unit.test", weird=object()):
            pass

        assert "unit.test" in names(spans)

    def test_span_is_inert_when_the_sdk_is_missing(self):
        """Instrumentation must never become an application failure."""
        with patch.object(tracing, "_IMPORT_ERROR", RuntimeError("no sdk")):
            with tracing.span("unit.test") as span:
                assert span is None

    def test_record_error_marks_the_span_failed(self, spans):
        with tracing.span("unit.test") as span:
            tracing.record_error(span, ValueError("boom"))

        assert by_name(spans, "unit.test").status.status_code.name == "ERROR"


class TestOllamaSpans:
    """The spans that close the documented 'no per-call Ollama latency metric' gap."""

    def test_chat_emits_a_span_with_model_and_token_counts(self, spans, llm_settings):
        from apps.llm_analysis import services

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "message": {"content": "hi"},
                    "prompt_eval_count": 11,
                    "eval_count": 7,
                }

        with patch("apps.llm_analysis.services.httpx.post", return_value=FakeResponse()):
            services.chat([{"role": "user", "content": "q"}], model="m1")

        span = by_name(spans, "ollama.chat")
        assert span.attributes["llm.model"] == "m1"
        # Token counts are the closest thing to a cost signal, and they are free -
        # already in the response body we were parsing anyway.
        assert span.attributes["llm.tokens.prompt"] == 11
        assert span.attributes["llm.tokens.completion"] == 7

    def test_chat_marks_the_span_on_failure(self, spans, llm_settings):
        import httpx

        from apps.llm_analysis import services

        with patch(
            "apps.llm_analysis.services.httpx.post",
            side_effect=httpx.ConnectError("refused"),
        ):
            with pytest.raises(services.OllamaServiceError):
                services.chat([{"role": "user", "content": "q"}])

        assert by_name(spans, "ollama.chat").status.status_code.name == "ERROR"

    def test_chat_many_children_are_siblings_under_one_parent(self, spans, llm_settings):
        """THE fan-out assertion. ThreadPoolExecutor workers do not inherit the OTel
        context, so without explicit propagation each call becomes its own ROOT trace
        and the concurrency - the only reason to instrument this - is invisible."""
        from apps.llm_analysis import services

        with patch("apps.llm_analysis.services.httpx.post") as post:
            post.return_value.raise_for_status.return_value = None
            post.return_value.json.return_value = {"message": {"content": "ok"}}
            services.chat_many([[{"role": "user", "content": str(i)}] for i in range(3)])

        parent = by_name(spans, "ollama.chat_many")
        assert parent.attributes["llm.batches"] == 3
        assert parent.attributes["llm.failures"] == 0

        # THE assertion this test originally lacked. Checking only the parent's
        # attributes let a real defect through to prod: ctx was captured BEFORE the
        # chat_many span, so the workers attached to the CALLER and the fan-out calls
        # came out as siblings of chat_many instead of children - the grouping span
        # contained none of the work it existed to group.
        children = [s for s in spans.get_finished_spans() if s.name == "ollama.chat"]
        assert len(children) == 3, f"expected 3 fan-out spans, got {len(children)}"
        for child in children:
            assert child.parent is not None, "fan-out call became its own root trace"
            assert child.parent.span_id == parent.context.span_id, (
                "fan-out call is a SIBLING of ollama.chat_many, not a child"
            )

    def test_chat_many_counts_failures(self, spans, llm_settings):
        from apps.llm_analysis import services

        def flaky(messages, **kwargs):
            if messages[0]["content"] == "1":
                raise services.OllamaServiceError("nope")
            return "ok"

        with patch("apps.llm_analysis.services.chat", side_effect=flaky):
            results = services.chat_many([[{"role": "user", "content": str(i)}] for i in range(3)])

        assert by_name(spans, "ollama.chat_many").attributes["llm.failures"] == 1
        assert sum(1 for r in results if r["error"]) == 1


class TestStreamingAndEmbedSpans:
    """The two instrumented calls that are not plain request/response."""

    def test_chat_stream_counts_chunks(self, spans, llm_settings):
        # The span is still `ollama.chat_stream` although the function is `chat_tokens`: it
        # names the OPERATION, and renaming it would empty the tracing dashboard panels and
        # span metrics that key on it (issue #8 phase 6).
        """For a streaming call the interesting duration is time-to-LAST-token, so the
        span must cover the whole generator rather than just the request. The chunk
        count is what separates a stream that died early from one that simply had
        little to say - identical durations, very different meanings."""
        from apps.llm_analysis import services

        class FakeStream:
            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

            def raise_for_status(self):
                return None

            def iter_lines(self):
                yield json.dumps({"message": {"content": "a"}})
                yield json.dumps({"message": {"content": "b"}})
                yield json.dumps({"done": True})

        with patch("apps.llm_analysis.services.httpx.stream", return_value=FakeStream()):
            list(services.chat_tokens([{"role": "user", "content": "q"}], model="m1"))

        span = by_name(spans, "ollama.chat_stream")
        assert span.attributes["llm.model"] == "m1"
        assert span.attributes["llm.chunks"] == 2

    def test_chat_stream_records_chunks_seen_before_a_failure(self, spans, llm_settings):
        """A stream that dies mid-flight is the case worth debugging, so the count must
        survive the error path rather than being lost with the exception."""
        import httpx

        from apps.llm_analysis import services

        class DyingStream:
            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

            def raise_for_status(self):
                return None

            def iter_lines(self):
                yield json.dumps({"message": {"content": "a"}})
                raise httpx.ReadError("connection dropped")

        with patch("apps.llm_analysis.services.httpx.stream", return_value=DyingStream()):
            with pytest.raises(services.OllamaServiceError):
                list(services.chat_tokens([{"role": "user", "content": "q"}]))

        span = by_name(spans, "ollama.chat_stream")
        assert span.attributes["llm.chunks"] == 1
        assert span.status.status_code.name == "ERROR"

    def test_embed_records_model_and_input_count(self, spans, llm_settings):
        from apps.llm_analysis import services

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"embeddings": [[0.1], [0.2]]}

        with patch("apps.llm_analysis.services.httpx.post", return_value=FakeResponse()):
            services.embed(["a", "b"], model="embed-1")

        span = by_name(spans, "ollama.embed")
        assert span.attributes["llm.model"] == "embed-1"
        assert span.attributes["llm.inputs"] == 2

    def test_embed_short_circuits_without_a_span(self, spans, llm_settings):
        """No inputs means no call, so it must not leave an empty span behind either."""
        from apps.llm_analysis import services

        assert services.embed([]) == []
        assert "ollama.embed" not in names(spans)

    def test_missing_token_counts_are_omitted_not_zeroed(self, spans, llm_settings):
        """Ollama does not always report token counts. A zero would read as a real
        measurement; absence is the honest representation."""
        from apps.llm_analysis import services

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"message": {"content": "hi"}}

        with patch("apps.llm_analysis.services.httpx.post", return_value=FakeResponse()):
            services.chat([{"role": "user", "content": "q"}])

        attributes = by_name(spans, "ollama.chat").attributes
        assert "llm.tokens.prompt" not in attributes
        assert "llm.tokens.completion" not in attributes


class TestThreadPropagation:
    """Both seams where work crosses a thread boundary and context must be carried."""

    def test_context_survives_a_plain_thread(self, spans):
        """The mechanism behind both stream_in_background and chat_many."""
        import threading

        def work(ctx):
            with tracing.attached(ctx), tracing.span("child"):
                pass

        with tracing.span("parent"):
            thread = threading.Thread(target=work, args=(tracing.current_context(),))
            thread.start()
            thread.join()

        parent, child = by_name(spans, "parent"), by_name(spans, "child")
        assert child.parent is not None, "child became its own root trace"
        assert child.parent.span_id == parent.context.span_id

    def test_without_propagation_the_child_is_orphaned(self, spans):
        """The bug this guards against, demonstrated - so the test above cannot pass
        vacuously if propagation silently stops working."""
        import threading

        def work():
            with tracing.span("orphan"):
                pass

        with tracing.span("parent"):
            thread = threading.Thread(target=work)
            thread.start()
            thread.join()

        assert by_name(spans, "orphan").parent is None


@pytest.mark.django_db
class TestAgentRunSpan:
    def test_stream_in_background_wraps_the_run_in_one_span(self, spans, django_user_model):
        """One span per run, so a fan-out workflow reads as a single waterfall rather
        than a pile of unrelated traces."""
        from apps.llm_analysis import services

        user = django_user_model.objects.create_user(email="s@e.com", password="x")
        run = services.create_agent_run(user, "q", "m1", kind="react", max_steps=2)

        def gen():
            yield "data: one\n\n"
            yield "data: two\n\n"

        list(services.stream_in_background(gen(), run))

        span = by_name(spans, "agent.run")
        assert span.attributes["agent.run_id"] == str(run.pk)
        assert span.attributes["agent.kind"] == "react"

    def test_llm_calls_inside_a_run_nest_under_it(self, spans, django_user_model, llm_settings):
        """The daemon thread is the second propagation seam - the same gap that forced
        agent runs to be correlated by AgentRun.id instead of request_id."""
        from apps.llm_analysis import services

        user = django_user_model.objects.create_user(email="s2@e.com", password="x")
        run = services.create_agent_run(user, "q", "m1", kind="react", max_steps=2)

        def gen():
            with patch("apps.llm_analysis.services.httpx.post") as post:
                post.return_value.raise_for_status.return_value = None
                post.return_value.json.return_value = {"message": {"content": "hi"}}
                services.chat([{"role": "user", "content": "q"}])
            yield "data: done\n\n"

        list(services.stream_in_background(gen(), run))

        run_span, chat_span = by_name(spans, "agent.run"), by_name(spans, "ollama.chat")
        assert chat_span.parent is not None, "the LLM call escaped the run's trace"
        assert chat_span.parent.span_id == run_span.context.span_id


class TestToolSpan:
    def test_run_tool_emits_a_span(self, spans):
        from apps.llm_analysis import tools

        tools.run_tool("list_sectors", {})

        assert by_name(spans, "agent.tool").attributes["tool.name"] == "list_sectors"

    def test_a_failing_tool_is_marked_but_still_returns_an_observation(self, spans):
        """run_tool's contract is that it NEVER raises - the agent loops treat a tool
        error as data to reason about on the next turn."""
        import dataclasses

        from apps.llm_analysis import tools

        def boom(**_kwargs):
            raise RuntimeError("boom")

        # Tool is a frozen dataclass, so swap the whole entry rather than its attribute.
        broken = dataclasses.replace(tools.TOOLS["list_sectors"], run=boom)
        with patch.dict(tools.TOOLS, {"list_sectors": broken}):
            result = tools.run_tool("list_sectors", {})

        assert "error" in result
        assert by_name(spans, "agent.tool").status.status_code.name == "ERROR"


class TestStepSpans:
    """Per-step spans (issue #5 phase 4, the deliverable left open until now).

    Two mechanisms, because the ten workflow modules do not share one shape:

    * modules whose step loop is in one place wrap it with `step_span`
    * modules that mark a step running and then done/error wrap NOTHING - the recorded
      timestamps are replayed as a span from `store.update_step`, which is both simpler
      and more accurate, since the duration is the step's own rather than a wrapper's
    """

    def test_step_span_nests_under_the_run(self, spans):
        class FakeRun:
            pk = "run-1"
            kind = "react"

        with tracing.span("agent.run"):
            with tracing.step_span(FakeRun(), 2, key="k", label="Step three"):
                pass

        step = by_name(spans, "agent.step")
        assert step.attributes["agent.run_id"] == "run-1"
        assert step.attributes["agent.kind"] == "react"
        assert step.attributes["agent.step_order"] == 2
        assert step.attributes["agent.step_key"] == "k"
        assert step.parent.span_id == by_name(spans, "agent.run").context.span_id

    def test_replayed_span_uses_the_recorded_duration(self, spans):
        """The point of replaying rather than wrapping: the span is the STEP's duration,
        not the duration of whatever code happened to surround the DB write."""
        from datetime import UTC
        from datetime import datetime as dt

        started = dt(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

        class FakeStep:
            order = 1
            key = "worker-a"
            label = "Worker A"
            status = "done"
            error = ""
            started_at = started
            completed_at = dt(2026, 1, 1, 12, 0, 4, tzinfo=UTC)

        class FakeRun:
            pk = "run-2"
            kind = "orchestrator"

        tracing.record_completed_step(FakeRun(), FakeStep())

        span = by_name(spans, "agent.step")
        assert (span.end_time - span.start_time) == 4_000_000_000
        assert span.attributes["agent.step_key"] == "worker-a"

    def test_a_failed_step_is_marked_on_the_span(self, spans):
        from datetime import UTC
        from datetime import datetime as dt

        class FakeStep:
            order = 0
            key = ""
            label = ""
            status = "error"
            error = "worker exploded"
            started_at = dt(2026, 1, 1, tzinfo=UTC)
            completed_at = dt(2026, 1, 1, 0, 0, 1, tzinfo=UTC)

        class FakeRun:
            pk = "run-3"
            kind = "dag"

        tracing.record_completed_step(FakeRun(), FakeStep())

        assert by_name(spans, "agent.step").status.status_code.name == "ERROR"

    def test_no_span_without_timestamps(self, spans):
        """Not every step records them; a zero-duration span would be noise, not data."""

        class FakeStep:
            order = 0
            key = ""
            label = ""
            status = "done"
            error = ""
            started_at = None
            completed_at = None

        class FakeRun:
            pk = "run-4"
            kind = "chain"

        tracing.record_completed_step(FakeRun(), FakeStep())

        assert "agent.step" not in names(spans)

    def test_recording_never_raises_into_the_write_path(self, spans):
        """It runs inside store.update_step, immediately after step.save().

        It also must not be SILENT about failing: a bare `pass` here hid a real bug
        during development (dotted attribute keys passed as **kwargs), leaving the
        function emitting nothing while looking healthy. It warns once and no more,
        because it runs per step.
        """

        class Exploding:
            order = 0

            @property
            def started_at(self):
                raise RuntimeError("boom")

        # Asserted on the logger rather than caplog: the "core" logger is configured
        # with propagate=False, so caplog's root handler never sees these records.
        tracing._RECORD_STEP_WARNED = False
        try:
            with patch.object(tracing, "logger") as log:
                tracing.record_completed_step(object(), Exploding())
                tracing.record_completed_step(object(), Exploding())

            assert log.warning.call_count == 1, "the warning must fire once per process"
            assert "agent.step" in log.warning.call_args[0][0]
        finally:
            tracing._RECORD_STEP_WARNED = False

    def test_every_workflow_module_has_step_spans_by_one_mechanism_or_the_other(self):
        """Structural guard. A new workflow added without a mechanism would produce a run
        span with no steps inside it - a waterfall that looks like one long opaque block,
        with nothing anywhere reporting a problem.

        THREE mechanisms now, since issue #6 phase 3 moved the sequential workflows' loops
        into `_runtime.drive`, which opens the span itself. A module that delegates to the
        driver contains no `step_span(` of its own and must not read as uncovered.
        """
        from pathlib import Path

        workflows = Path(tracing.__file__).resolve().parents[1] / "apps" / "llm_analysis"
        modules = [
            "chain",
            "parallel",
            "react",
            "eval_opt",
            "plan_execute",
            "orchestrator",
            "multiagent",
            "dag",
            "autonomous",
            "chat_agent",
        ]

        for name in modules:
            source = (workflows / f"{name}.py").read_text()
            wrapped = "step_span(" in source
            # store.update_step replays the recorded timestamps as a span.
            replayed = "update_step(" in source and "completed_at" in source
            # _runtime.drive opens the span around every step it performs.
            driven = "drive(" in source
            assert wrapped or replayed or driven, f"{name} emits no agent.step spans"

    def test_the_driver_is_the_one_that_opens_the_span_for_driven_modules(self):
        """The `driven` allowance above is only honest if the driver really does wrap the
        step - otherwise it silently excuses three workflows from having spans at all."""
        from pathlib import Path

        app = Path(tracing.__file__).resolve().parents[1] / "apps" / "llm_analysis"
        runtime = (app / "_runtime.py").read_text()

        assert "step_span(" in runtime
        # Every workflow on the SEQUENTIAL driver. The fan-out three use drive_waves, which
        # deliberately does not open a per-step span - see the wave test below.
        for name in ("react", "eval_opt", "plan_execute", "multiagent", "autonomous", "chat_agent"):
            source = (app / f"{name}.py").read_text()
            assert "drive(" in source, f"{name} no longer uses the driver"
            assert "step_span(" not in source, (
                f"{name} opens its own span as well as the driver's - steps would nest twice"
            )

    def test_the_wave_driver_wraps_the_wave_not_the_step(self):
        """`drive_waves` must NOT open a per-step span: one `chat_many` covers every step
        in the wave, so a per-step span could not contain the call that produced it. It
        wraps the wave instead, and the steps stay replayed from their timestamps."""
        from pathlib import Path

        app = Path(tracing.__file__).resolve().parents[1] / "apps" / "llm_analysis"
        runtime = (app / "_runtime.py").read_text()
        wave_driver = runtime[runtime.index("def drive_waves(") :]

        assert "step_span(" not in wave_driver
        assert '"agent.wave"' in wave_driver
        for name in ("parallel", "orchestrator", "dag"):
            source = (app / f"{name}.py").read_text()
            assert "drive_waves(" in source, f"{name} no longer uses the wave driver"

    def test_every_workflow_is_driven_except_the_two_documented_exemptions(self):
        """The simplification the driver earns: a workflow either goes through a driver or
        is one of two recorded exceptions. A twelfth arriving with its own hand-rolled loop
        fails here rather than quietly re-growing the duplication this issue removed."""
        from pathlib import Path

        from apps.llm_analysis.models import AgentRun

        app = Path(tracing.__file__).resolve().parents[1] / "apps" / "llm_analysis"
        module_for_kind = {"plan_exec": "plan_execute", "route": "router", "chat": "chat_agent"}
        # chain: its payload has no `event` discriminator and it ends with a step-shaped
        # __done__ rather than a `result` event, so the drivers' terminal path cannot apply.
        # router: persists no AgentStep rows at all.
        exempt = {"chain", "route"}

        undriven = []
        for kind, _ in AgentRun.Kind.choices:
            if kind in exempt:
                continue
            name = module_for_kind.get(kind, kind)
            source = (app / f"{name}.py").read_text()
            if "drive(" not in source and "drive_waves(" not in source:
                undriven.append(name)

        assert not undriven, f"workflows with a hand-rolled loop: {sorted(undriven)}"

    def test_router_is_deliberately_exempt(self):
        """router persists no AgentStep rows at all - it classifies, then spawns a chain
        run which carries the steps. Pinned so its absence above reads as a decision."""
        from pathlib import Path

        workflows = Path(tracing.__file__).resolve().parents[1] / "apps" / "llm_analysis"
        source = (workflows / "router.py").read_text()

        assert "create_step(" not in source
        assert "seed_steps(" not in source


@pytest.mark.django_db
class TestStepSpansEndToEnd:
    """Runs real workflows and asserts the SPAN TREE, not the source text.

    The structural test above only greps for a mechanism being present. These drive the
    generators and check the shape that actually reaches Tempo - which is the only thing
    that has reliably caught defects on this issue.
    """

    def make_user(self, django_user_model, email):
        return django_user_model.objects.create_user(email=email, password="x")

    def test_chain_emits_one_step_span_per_step_under_the_run(
        self, spans, django_user_model, llm_settings
    ):
        """chain uses the step_span WRAPPER: its loop body is in one place."""
        from apps.llm_analysis.chain import CHAIN_STEPS, run_chain
        from apps.llm_analysis.services import create_chain_run

        user = self.make_user(django_user_model, "chain-span@e.com")
        run = create_chain_run(user, "q", "m1")

        handlers = {
            "classify": lambda q, c, m: '{"intent":"analyse","tickers":[],"time_horizon":"annual"}',
            "research": lambda q, c, m: "[]",
            "synthesise": lambda q, c, m: "ok",
            "format": lambda q, c, m: "# Report",
        }
        with patch("apps.llm_analysis.chain._STEP_HANDLERS", handlers):
            with tracing.span("agent.run") as run_span:
                list(run_chain(run, model=None))

        steps = [s for s in spans.get_finished_spans() if s.name == "agent.step"]
        assert len(steps) == len(CHAIN_STEPS)
        for step in steps:
            assert step.parent is not None, "a step span escaped the run's trace"
            assert step.parent.span_id == run_span.context.span_id
        assert {s.attributes["agent.step_key"] for s in steps} == {d.id for d in CHAIN_STEPS}

    def test_eval_opt_emits_a_span_per_iteration(self, spans, django_user_model, llm_settings):
        from apps.llm_analysis.eval_opt import run_eval_opt
        from apps.llm_analysis.services import create_agent_run

        user = self.make_user(django_user_model, "eval-span@e.com")
        run = create_agent_run(
            user, "q", "m1", kind="eval_opt", max_iterations=2, threshold=8, best_score=0
        )

        # Draft, then an evaluation that passes on the first iteration.
        replies = ["a draft", '{"score": 9, "feedback": "good", "pass": true}']
        with patch("apps.llm_analysis.services.chat", side_effect=replies):
            with tracing.span("agent.run"):
                list(run_eval_opt(run, model=""))

        steps = [s for s in spans.get_finished_spans() if s.name == "agent.step"]
        assert steps, "no agent.step span emitted for an eval_opt iteration"
        assert steps[0].attributes["agent.kind"] == "eval_opt"

    def test_the_store_replay_path_fires_for_a_terminal_step(
        self, spans, django_user_model, llm_settings
    ):
        """The other mechanism: parallel/orchestrator/multiagent/dag/autonomous never
        call step_span - store.update_step replays their recorded timestamps."""
        from datetime import UTC
        from datetime import datetime as dt

        from apps.llm_analysis import store
        from apps.llm_analysis.models import AgentStep
        from apps.llm_analysis.services import create_agent_run

        user = self.make_user(django_user_model, "store-span@e.com")
        run = create_agent_run(user, "q", "m1", kind="orchestrator", max_workers=2)
        step = store.create_step(
            run, 0, key="worker-1", label="Worker 1", status=AgentStep.Status.RUNNING
        )
        store.update_step(step, started_at=dt.now(UTC))

        assert "agent.step" not in names(spans), "a running step must not close a span yet"

        store.update_step(
            step, status=AgentStep.Status.DONE, output="done", completed_at=dt.now(UTC)
        )

        span = by_name(spans, "agent.step")
        assert span.attributes["agent.step_key"] == "worker-1"
        assert span.attributes["agent.kind"] == "orchestrator"
        assert span.attributes["agent.step_status"] == AgentStep.Status.DONE

    def test_llm_calls_nest_inside_the_step_that_made_them(
        self, spans, django_user_model, llm_settings
    ):
        """The whole point of the step layer: run -> step -> LLM call, so a waterfall
        attributes latency to a step rather than to one opaque block."""
        from apps.llm_analysis.chain import run_chain
        from apps.llm_analysis.services import create_chain_run

        user = self.make_user(django_user_model, "nest-span@e.com")
        run = create_chain_run(user, "q", "m1")

        def handler(query, context, model):
            from apps.llm_analysis import services

            with patch("apps.llm_analysis.services.httpx.post") as post:
                post.return_value.raise_for_status.return_value = None
                post.return_value.json.return_value = {"message": {"content": "{}"}}
                services.chat([{"role": "user", "content": "q"}])
            return "{}"

        handlers = dict.fromkeys(["classify", "research", "synthesise", "format"], handler)
        with patch("apps.llm_analysis.chain._STEP_HANDLERS", handlers):
            with tracing.span("agent.run"):
                list(run_chain(run, model=None))

        chat_spans = [s for s in spans.get_finished_spans() if s.name == "ollama.chat"]
        step_ids = {s.context.span_id for s in spans.get_finished_spans() if s.name == "agent.step"}
        assert chat_spans, "no LLM span recorded"
        for chat in chat_spans:
            assert chat.parent is not None
            assert chat.parent.span_id in step_ids, "an LLM call escaped its step span"
