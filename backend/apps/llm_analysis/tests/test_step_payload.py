"""One serialisation of a step (issue #6 phase 2).

A step used to be described twice - once by the hand-built SSE payload in the workflow
module, once by the DRF serializer behind the detail endpoint. They drifted: ``dag``
streamed ``id``/``args`` while its detail endpoint returned ``node_id``/``tool_args``,
so a refresh-restore silently dropped the tool arguments out of the UI.

``_events.step_event`` now derives the payload from the step serializer, so the two
cannot disagree. These tests pin that, and pin that no workflow goes around it.
"""

from __future__ import annotations

import ast
import json
from datetime import UTC
from datetime import datetime as dt
from pathlib import Path

import pytest

from apps.llm_analysis import _events, store
from apps.llm_analysis.models import AgentRun, AgentStep
from apps.llm_analysis.serializers import STEP_SERIALIZERS, step_serializer_for

MODULE_DIR = Path(_events.__file__).parent

# Every kind that persists AgentStep rows, mapped to its SSE event name and the meta a
# realistic step carries. ``chain`` is absent: its payload has no ``event`` discriminator
# at all (the frontend keys off step_id), so it is not a step_event caller. ``route``
# persists no steps. Both absences are asserted below.
STEP_KINDS = {
    "parallel": ("task", {"vote": "buy"}),
    "react": ("step", {"thought": "t", "tool": "company_profile", "tool_args": {"symbol": "AAPL"}}),
    "eval_opt": ("iteration", {"draft": "d", "score": 7, "feedback": "f", "passed": False}),
    "plan_exec": ("step", {"task": "t", "tool": "recent_price", "tool_args": {"symbol": "KO"}}),
    "orchestrator": ("worker", {"task": "t", "tool": "company_snapshot", "tool_args": {"a": 1}}),
    "multiagent": ("step", {"input": "i", "tool_calls": [{"tool": "x", "args": {}}]}),
    "dag": ("node", {"task": "t", "tool": "sector_analysis", "tool_args": {"b": 2}, "wave": 1}),
    "autonomous": ("cycle", {"reflection": "r", "action": "tool", "tool_args": {"c": 3}}),
    "browser": ("step", {"action": "click", "action_args": {"index": 2}, "url": "https://x.test"}),
    "chat": ("step", {"thought": "t", "tool": "company_snapshot", "tool_args": {"symbol": "KO"}}),
}


# Derived from STEP_KINDS rather than hand-listed, so a workflow cannot dodge the
# structural guards by being left out of a literal.
MODULE_FOR_KIND = {"plan_exec": "plan_execute", "chat": "chat_agent"}
STEP_MODULES = tuple(sorted(MODULE_FOR_KIND.get(k, k) for k in STEP_KINDS))


def _payload(frame: str) -> dict:
    return json.loads(frame[len("data: ") : -2])


@pytest.mark.django_db
class TestStepEventIsTheSerializer:
    @pytest.mark.parametrize(("kind", "spec"), STEP_KINDS.items())
    def test_payload_equals_the_detail_representation(self, user, kind, spec):
        """The guard that would have caught the ``args``/``tool_args`` defect."""
        name, meta = spec
        run = store.create_run(user, query="q", model="m", kind=kind)
        step = store.create_step(
            run, 0, key="k0", label="Step", status=AgentStep.Status.DONE, output="out", **meta
        )

        streamed = _payload(_events.step_event(step, name, kind=kind))
        detail = json.loads(json.dumps(step_serializer_for(kind)(step).data, default=str))

        assert streamed.pop("event") == name
        assert streamed == detail, (
            f"{kind}: the live step event and the detail endpoint describe the same row "
            f"differently - {set(streamed) ^ set(detail) or 'same keys, different values'}"
        )

    @pytest.mark.parametrize(("kind", "spec"), STEP_KINDS.items())
    def test_tool_args_is_never_streamed_as_args(self, user, kind, spec):
        """The specific regression: ``args`` on the wire, ``tool_args`` on the row."""
        name, meta = spec
        run = store.create_run(user, query="q", model="m", kind=kind)
        step = store.create_step(run, 0, key="k0", status=AgentStep.Status.DONE, **meta)

        payload = _payload(_events.step_event(step, name, kind=kind))

        assert "args" not in payload, f"{kind} still streams the short name"
        if "tool_args" in meta:
            assert payload["tool_args"] == meta["tool_args"]

    def test_extra_fields_ride_alongside_the_serialised_row(self, user):
        run = store.create_run(user, query="q", model="m", kind="dag")
        step = store.create_step(run, 0, key="n1", status=AgentStep.Status.DONE)

        payload = _payload(_events.step_event(step, "node", kind="dag", replan=True))

        assert payload["replan"] is True
        assert payload["node_id"] == "n1"

    def test_kind_is_read_off_the_run_when_not_given(self, user):
        run = store.create_run(user, query="q", model="m", kind="dag")
        step = store.create_step(run, 0, key="n1", status=AgentStep.Status.DONE)

        assert _payload(_events.step_event(step, "node"))["node_id"] == "n1"


@pytest.mark.django_db
class TestChainSharesTheSerialisation:
    """``chain`` cannot use ``step_event`` - its payload carries no ``event`` discriminator
    (the frontend keys off ``step_id``). It must still share the SERIALISATION, or it drifts
    the same way the other eight did."""

    def test_step_payload_equals_the_detail_representation(self, user):
        run = store.create_run(user, query="q", model="m", kind="chain")
        step = store.create_step(
            run,
            0,
            key="classify",
            label="Classify Query",
            status=AgentStep.Status.DONE,
            output="{}",
        )

        payload = _events.step_payload(step, kind="chain")
        detail = step_serializer_for("chain")(step).data

        assert payload == detail

    def test_payload_carries_the_id_and_timestamps(self, user):
        """The fields chain's old hand-built payload omitted. The frontend merges the event
        into a client-side template, so anything missing stayed at the template default
        during a live run and only appeared after a reload - the chain card renders a
        duration from started_at/completed_at, so the label was missing live."""
        run = store.create_run(user, query="q", model="m", kind="chain")
        step = store.create_step(
            run,
            0,
            key="classify",
            status=AgentStep.Status.DONE,
            started_at=dt(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
            completed_at=dt(2026, 1, 1, 12, 0, 2, tzinfo=UTC),
        )

        payload = _events.step_payload(step, kind="chain")

        assert set(payload) >= {"id", "step_id", "order", "started_at", "completed_at"}
        assert payload["step_id"] == "classify"

    def test_chain_module_uses_the_shared_payload(self):
        """Structural: chain frames its own line, but must not build the dict by hand."""
        source = (MODULE_DIR / "chain.py").read_text()

        assert "step_payload(" in source, (
            "chain.py must derive its step payload from the serializer"
        )
        for node in ast.walk(ast.parse(source)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "sse"
                and node.args
                and isinstance(node.args[0], ast.Dict)
                and any(
                    isinstance(k, ast.Constant) and k.value == "label" for k in node.args[0].keys
                )
                and not any(isinstance(k, ast.Constant) is False for k in node.args[0].keys)
            ):
                # The run-level signals (__init__ / __done__) are NOT steps and legitimately
                # build their own dict - they are allowed, and are the only allowance.
                ids = [
                    v.value
                    for k, v in zip(node.args[0].keys, node.args[0].values)
                    if isinstance(k, ast.Constant)
                    and k.value == "step_id"
                    and isinstance(v, ast.Constant)
                ]
                assert ids == [] or all(i.startswith("__") for i in ids), (
                    f"chain.py hand-builds a step payload at line {node.lineno}"
                )


class TestRegistryCoverage:
    def test_every_run_kind_has_a_step_serializer(self):
        """A new workflow must declare how its steps are represented. Without this, the
        first thing anyone notices is an empty panel on the live stream."""
        missing = {k for k, _ in AgentRun.Kind.choices} - set(STEP_SERIALIZERS) - {"route"}

        assert not missing, f"kinds with no step serializer: {sorted(missing)}"

    def test_route_is_deliberately_absent(self):
        """``route`` persists no AgentStep rows - it classifies and spawns a chain run."""
        assert "route" not in STEP_SERIALIZERS

    def test_unregistered_kind_raises_rather_than_guessing(self):
        with pytest.raises(KeyError):
            step_serializer_for("not_a_workflow")


class TestNoWorkflowHandBuildsAStepPayload:
    """Structural guard. Hand-building the payload beside the serializer is what let the
    two drift in the first place."""

    STEP_EVENT_NAMES = ("task", "step", "iteration", "worker", "node", "cycle")

    @pytest.mark.parametrize("module", STEP_MODULES)
    def test_step_events_go_through_step_event(self, module):
        source = (MODULE_DIR / f"{module}.py").read_text()

        for node in ast.walk(ast.parse(source)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "event"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value in self.STEP_EVENT_NAMES
            ):
                pytest.fail(
                    f"{module}.py builds a '{node.args[0].value}' payload by hand at line "
                    f"{node.lineno} - use _events.step_event so it stays one serialisation"
                )

    @pytest.mark.parametrize("module", STEP_MODULES)
    def test_no_sse_event_streams_a_short_args_key(self, module):
        """AST, not grep: `args=` is also a legitimate dataclass argument in these
        modules (dag's Node). Only the wire field is forbidden."""
        source = (MODULE_DIR / f"{module}.py").read_text()

        for node in ast.walk(ast.parse(source)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in ("event", "step_event")
                and any(k.arg == "args" for k in node.keywords)
            ):
                pytest.fail(
                    f"{module}.py streams a bare `args` field at line {node.lineno} - "
                    "the row stores tool_args / action_args"
                )
