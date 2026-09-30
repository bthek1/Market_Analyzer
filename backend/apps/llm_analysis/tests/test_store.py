"""Tests for the meta persistence service layer (``store.py``).

``store`` is the ONLY writer of ``AgentRun.meta`` / ``AgentStep.meta`` and the gate that
validates every meta write against ``meta_spec``. These cover the service contract directly
(validation on write, merge semantics, read defaults, terminal status, seeding) independent
of any workflow.
"""

from datetime import UTC
from datetime import datetime as dt

import pytest

from apps.llm_analysis import store
from apps.llm_analysis.meta_spec import MetaValidationError
from apps.llm_analysis.models import AgentRun, AgentStep


@pytest.mark.django_db
class TestCreateRun:
    def test_validates_and_stores_meta(self, user):
        run = store.create_run(user, "q", "", kind="react", max_steps=6)
        run.refresh_from_db()
        assert run.kind == "react"
        assert run.meta == {"max_steps": 6}
        assert run.status == AgentRun.Status.RUNNING

    def test_rejects_unknown_meta_key(self, user):
        with pytest.raises(MetaValidationError, match="Unknown run meta key 'bogus'"):
            store.create_run(user, "q", "", kind="react", bogus=1)

    def test_rejects_wrong_type(self, user):
        with pytest.raises(MetaValidationError, match="expects"):
            store.create_run(user, "q", "", kind="react", max_steps="six")

    def test_rejects_cross_kind_key(self, user):
        # max_workers belongs to orchestrator, not react.
        with pytest.raises(MetaValidationError):
            store.create_run(user, "q", "", kind="react", max_workers=4)

    def test_parent_link(self, user):
        chain = store.create_run(user, "q", "", kind="chain")
        route = store.create_run(user, "q", "", kind="route", parent=chain)
        assert route.parent_id == chain.id

    def test_chain_has_empty_meta(self, user):
        run = store.create_run(user, "q", "", kind="chain")
        assert run.meta == {}


@pytest.mark.django_db
class TestUpdateRun:
    def test_merges_meta_not_replace(self, user):
        run = store.create_run(user, "q", "", kind="plan_exec", max_steps=6, replans=0)
        store.update_run(run, plan=[{"task": "x"}])
        run.refresh_from_db()
        # existing keys preserved, new key merged in
        assert run.meta == {"max_steps": 6, "replans": 0, "plan": [{"task": "x"}]}

    def test_updates_spine_fields(self, user):
        run = store.create_run(user, "q", "", kind="react", max_steps=6)
        store.update_run(run, status="done", output="ans", completed_at=dt.now(UTC))
        run.refresh_from_db()
        assert run.status == "done"
        assert run.output == "ans"
        assert run.completed_at is not None

    def test_validates_meta_on_update(self, user):
        run = store.create_run(user, "q", "", kind="react", max_steps=6)
        with pytest.raises(MetaValidationError):
            store.update_run(run, bogus=1)

    def test_only_saves_changed_fields(self, user):
        run = store.create_run(user, "q", "", kind="react", max_steps=6)
        # mutate a column in the DB behind the instance's back...
        AgentRun.objects.filter(pk=run.pk).update(query="changed-in-db")
        # ...then update only status; query must NOT be clobbered by the stale instance.
        store.update_run(run, status="done")
        run.refresh_from_db()
        assert run.status == "done"
        assert run.query == "changed-in-db"

    def test_parent_assignment(self, user):
        chain = store.create_run(user, "q", "", kind="chain")
        route = store.create_run(user, "q", "", kind="route")
        store.update_run(route, parent=chain)
        route.refresh_from_db()
        assert route.parent_id == chain.id


@pytest.mark.django_db
class TestFinishRun:
    def test_done_when_no_error(self, user):
        run = store.create_run(user, "q", "", kind="react", max_steps=6)
        store.finish_run(run, output="answer")
        run.refresh_from_db()
        assert run.status == AgentRun.Status.DONE
        assert run.output == "answer"
        assert run.completed_at is not None

    def test_error_sets_error_status(self, user):
        run = store.create_run(user, "q", "", kind="react", max_steps=6)
        store.finish_run(run, error="boom")
        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR
        assert run.error == "boom"

    def test_finish_can_write_terminal_meta(self, user):
        run = store.create_run(user, "q", "", kind="eval_opt", max_iterations=3, threshold=8)
        store.finish_run(run, output="best", best_score=9)
        run.refresh_from_db()
        assert run.meta["best_score"] == 9


@pytest.mark.django_db
class TestSteps:
    def test_seed_steps_bulk_creates_with_meta(self, user):
        run = store.create_run(user, "q", "", kind="parallel", strategy="voting", n=2)
        store.seed_steps(
            run,
            [
                {"order": 0, "key": "vote_0", "label": "Vote 1"},
                {"order": 1, "key": "vote_1", "label": "Vote 2"},
            ],
        )
        steps = list(run.steps.order_by("order"))
        assert [s.key for s in steps] == ["vote_0", "vote_1"]
        assert steps[0].status == AgentStep.Status.PENDING

    def test_seed_steps_validates_meta(self, user):
        run = store.create_run(user, "q", "", kind="parallel", strategy="voting", n=1)
        with pytest.raises(MetaValidationError):
            store.seed_steps(run, [{"order": 0, "key": "v", "bogus": 1}])

    def test_create_step_stores_meta(self, user):
        run = store.create_run(user, "q", "", kind="react", max_steps=6)
        step = store.create_step(
            run, 0, status=AgentStep.Status.DONE, thought="t", tool="recent_price"
        )
        step.refresh_from_db()
        assert step.meta == {"thought": "t", "tool": "recent_price"}
        assert step.status == AgentStep.Status.DONE

    def test_create_step_defaults_to_done(self, user):
        run = store.create_run(user, "q", "", kind="react", max_steps=6)
        step = store.create_step(run, 0, thought="t")
        assert step.status == AgentStep.Status.DONE

    def test_create_step_rejects_cross_kind_meta(self, user):
        run = store.create_run(user, "q", "", kind="react", max_steps=6)
        with pytest.raises(MetaValidationError):
            store.create_step(run, 0, vote="buy")  # vote belongs to parallel

    def test_update_step_merges_meta(self, user):
        run = store.create_run(user, "q", "", kind="dag", max_nodes=4)
        step = store.create_step(
            run, 0, status=AgentStep.Status.PENDING, key="a", task="t", depends_on=[]
        )
        store.update_step(
            step, status=AgentStep.Status.DONE, output="node out", kind="dag", observation="{}"
        )
        step.refresh_from_db()
        assert step.status == AgentStep.Status.DONE
        assert step.output == "node out"  # spine column
        # merge: original task/depends_on kept, observation added
        assert step.meta["task"] == "t"
        assert step.meta["observation"] == "{}"

    def test_update_step_sets_timestamps_and_error(self, user):
        run = store.create_run(user, "q", "", kind="react", max_steps=6)
        step = store.create_step(run, 0, status=AgentStep.Status.RUNNING)
        now = dt.now(UTC)
        store.update_step(
            step,
            status=AgentStep.Status.ERROR,
            error="boom",
            started_at=now,
            completed_at=now,
        )
        step.refresh_from_db()
        assert step.status == AgentStep.Status.ERROR
        assert step.error == "boom"
        assert step.started_at is not None
        assert step.completed_at is not None

    def test_update_step_kind_arg_avoids_run_lookup(self, user):
        run = store.create_run(user, "q", "", kind="parallel", strategy="voting", n=1)
        step = store.create_step(run, 0, status=AgentStep.Status.RUNNING, key="vote_0")
        # passing kind avoids touching step.run; meta still validated against parallel.
        store.update_step(step, status=AgentStep.Status.DONE, kind="parallel", vote="hold")
        step.refresh_from_db()
        assert step.meta["vote"] == "hold"


@pytest.mark.django_db
class TestAccessors:
    def test_run_meta_layers_defaults_under_stored(self, user):
        run = store.create_run(user, "q", "", kind="plan_exec", max_steps=6)
        m = store.run_meta(run)
        assert m.max_steps == 6  # stored
        assert m.replans == 0  # declared default, not stored
        assert m.allow_replan is None  # declared default None
        assert m.get("nonexistent", "fb") == "fb"

    def test_step_meta_uses_run_kind_when_omitted(self, user):
        run = store.create_run(user, "q", "", kind="react", max_steps=6)
        step = store.create_step(run, 0, thought="t")
        m = store.step_meta(step)  # no kind -> resolves via step.run.kind
        assert m.thought == "t"
        assert m.is_answer is False  # default
        assert m.tool == ""  # default

    def test_step_meta_with_explicit_kind(self, user):
        run = store.create_run(user, "q", "", kind="dag", max_nodes=4)
        step = store.create_step(run, 0, key="a", task="t", depends_on=["x"])
        m = store.step_meta(step, kind="dag")
        assert m.depends_on == ["x"]
        assert m.wave is None  # default

    def test_metaview_as_dict(self):
        view = store.MetaView({"a": 1})
        assert view.as_dict() == {"a": 1}
