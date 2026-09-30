"""Shared SSE framing and terminal-run events (issue #6 phase 1).

Before this module each workflow defined its own ``_sse`` and ``_finish``: nine
byte-identical copies of each. They had already drifted - ``react`` framed without
``default=str`` while the other eight did not - and nothing could catch it, because
there was no shared thing to test. These are that shared thing.
"""

from __future__ import annotations

import json
import re
from datetime import UTC
from datetime import datetime as dt
from pathlib import Path

import pytest

from apps.llm_analysis import _events, store
from apps.llm_analysis.meta_spec import MetaValidationError
from apps.llm_analysis.models import AgentRun

# Run kind -> the module that streams it. ``router`` and ``browser`` are included: they
# frame events like the rest even though they sit outside the step-span mechanisms tested
# in core/tests/test_tracing_spans.py. Only ``plan_exec`` needs an entry that is not just
# the kind; the completeness test below is what stops a new workflow being omitted.
MODULE_FOR_KIND = {"plan_exec": "plan_execute", "route": "router", "chat": "chat_agent"}
WORKFLOW_MODULES = tuple(MODULE_FOR_KIND.get(kind, kind) for kind, _ in AgentRun.Kind.choices)

MODULE_DIR = Path(_events.__file__).parent


def _payload(frame: str) -> dict:
    assert frame.startswith("data: ") and frame.endswith("\n\n")
    return json.loads(frame[len("data: ") : -2])


class TestFraming:
    def test_sse_frames_one_data_line(self):
        assert _events.sse({"a": 1}) == 'data: {"a": 1}\n\n'

    def test_sse_survives_values_json_cannot_encode(self):
        """The drift that motivated this module: react framed without ``default=str``.

        A datetime or UUID in a payload would raise TypeError mid-stream and kill the
        run, rather than degrading the one field.
        """
        frame = _events.sse({"when": dt(2026, 1, 1, tzinfo=UTC)})

        assert _payload(frame)["when"].startswith("2026-01-01")

    def test_event_puts_the_name_first_and_keeps_the_fields(self):
        assert _payload(_events.event("plan", steps=[1, 2])) == {
            "event": "plan",
            "steps": [1, 2],
        }

    def test_event_with_no_fields(self):
        assert _payload(_events.event("started")) == {"event": "started"}


@pytest.mark.django_db
class TestTerminalEvents:
    def _run(self, user):
        return store.create_run(user, query="q", model="m", kind="react", max_steps=3)

    def test_succeed_writes_the_row_and_yields_result(self, user):
        run = self._run(user)

        frames = list(_events.succeed(run, "the answer"))

        run.refresh_from_db()
        assert run.status == AgentRun.Status.DONE
        assert run.output == "the answer"
        assert run.error == ""
        assert run.completed_at is not None
        assert _payload(frames[0]) == {
            "event": "result",
            "output": "the answer",
            "run_id": str(run.id),
        }

    def test_fail_writes_the_row_and_yields_error(self, user):
        run = self._run(user)

        frames = list(_events.fail(run, "ollama exploded"))

        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR
        assert run.error == "ollama exploded"
        assert run.completed_at is not None
        assert _payload(frames[0]) == {"event": "error", "error": "ollama exploded"}

    def test_fail_can_keep_a_partial_output(self, user):
        """eval_opt keeps its best-scoring draft on a run that then failed to revise."""
        run = self._run(user)

        list(_events.fail(run, "boom", output="best draft so far"))

        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR
        assert run.output == "best draft so far"

    def test_meta_goes_to_the_row_and_kwargs_go_to_the_event(self, user):
        """They are separate arguments because several workflows persist a value
        without streaming it (autonomous's stop_reason on one of its error paths)."""
        run = store.create_run(user, query="q", model="m", kind="parallel", strategy="voting")
        tally = {"buy": 2, "hold": 1, "sell": 0}

        frames = list(_events.succeed(run, "out", meta={"tally": tally}, strategy="voting"))

        run.refresh_from_db()
        assert run.meta["tally"] == tally
        payload = _payload(frames[0])
        assert payload["strategy"] == "voting"
        assert "tally" not in payload

    def test_meta_is_validated_by_store(self, user):
        """``store`` is still the only meta writer - these helpers do not bypass it."""
        run = self._run(user)

        with pytest.raises(MetaValidationError):
            list(_events.succeed(run, "out", meta={"not_a_react_key": 1}))


def test_every_run_kind_maps_to_a_module_on_disk():
    """The guard list is DERIVED from ``AgentRun.Kind``, not hand-maintained - a twelfth
    workflow is covered by every structural test below the moment its kind exists, rather
    than whenever someone remembers to add it here."""
    missing = [name for name in WORKFLOW_MODULES if not (MODULE_DIR / f"{name}.py").exists()]

    assert not missing, (
        f"no module for these kinds: {missing} - add an entry to MODULE_FOR_KIND if the "
        "file is named differently from the kind"
    )


class TestNoWorkflowRedefinesTheHelpers:
    """Structural guard. Nine copies of ``_sse`` and nine of ``_finish`` is how the
    ``default=str`` divergence happened; a tenth copy would reintroduce the class.
    """

    @pytest.mark.parametrize("name", WORKFLOW_MODULES)
    def test_module_defines_no_local_framing_helper(self, name):
        source = (MODULE_DIR / f"{name}.py").read_text()

        assert not re.search(r"^def _sse\b", source, re.M), (
            f"{name}.py defines its own SSE framing - import it from _events instead"
        )
        assert not re.search(r"^def _finish\b", source, re.M), (
            f"{name}.py defines its own _finish - use _events.succeed / _events.fail"
        )

    @pytest.mark.parametrize("name", WORKFLOW_MODULES)
    def test_module_does_not_hand_roll_an_sse_data_line(self, name):
        """``_events.sse`` is the only place that knows the wire format."""
        source = (MODULE_DIR / f"{name}.py").read_text()

        assert '"data: ' not in source and "'data: " not in source, (
            f"{name}.py frames an SSE line by hand - call _events.sse"
        )

    @pytest.mark.parametrize("name", WORKFLOW_MODULES)
    def test_module_does_not_call_finish_run_directly(self, name):
        """A run must end through ``succeed``/``fail`` so the DB write and the terminal
        event can never disagree about what happened."""
        source = (MODULE_DIR / f"{name}.py").read_text()

        assert "store.finish_run(" not in source, (
            f"{name}.py calls store.finish_run directly - use _events.succeed / fail"
        )
