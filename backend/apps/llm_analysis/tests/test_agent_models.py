"""Tests for the unified AgentRun / AgentStep models (llm_analysis model consolidation).

These cover the invariants that are specific to the consolidation itself - the things the
per-workflow test files do not exercise:

* the unified model schema (kind discriminator, parent self-FK, step uniqueness),
* the generic ``services.create_agent_run`` helper,
* cross-kind query isolation now that all ten workflows share one table, and
* the per-kind serializers that rename the new columns back to the legacy JSON field
  names so the frontend/API contract is preserved.
"""

import pytest
from django.db import IntegrityError

from apps.llm_analysis import serializers as ser
from apps.llm_analysis import services
from apps.llm_analysis.models import AgentRun, AgentStep

# ---------------------------------------------------------------------------
# Model schema
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAgentRunModel:
    def test_create_agent_run_sets_kind_and_fields(self, user):
        run = services.create_agent_run(user, "Analyse AAPL", "", kind="react", max_steps=5)
        assert isinstance(run, AgentRun)
        assert run.kind == "react"
        assert run.meta["max_steps"] == 5  # kind-specific config lives in meta now
        assert run.status == AgentRun.Status.RUNNING  # default
        assert run.query == "Analyse AAPL"

    def test_all_workflow_kinds_are_valid_choices(self):
        expected = {
            "chain",
            "route",
            "parallel",
            "react",
            "eval_opt",
            "plan_exec",
            "orchestrator",
            "multiagent",
            "dag",
            "autonomous",
            "browser",
            "chat",
        }
        assert set(AgentRun.Kind.values) == expected

    def test_parent_self_fk_links_route_to_chain(self, user):
        chain = services.create_agent_run(user, "q", "", kind="chain")
        route = services.create_agent_run(user, "q", "", kind="route")
        route.parent = chain
        route.save(update_fields=["parent"])

        route.refresh_from_db()
        assert route.parent_id == chain.id
        # reverse accessor
        assert list(chain.children.all()) == [route]

    def test_deleting_chain_nulls_route_parent(self, user):
        chain = services.create_agent_run(user, "q", "", kind="chain")
        route = services.create_agent_run(user, "q", "", kind="route")
        route.parent = chain
        route.save(update_fields=["parent"])

        chain.delete()  # on_delete=SET_NULL
        route.refresh_from_db()
        assert route.parent_id is None

    def test_str(self, user):
        run = services.create_agent_run(user, "q", "", kind="dag")
        assert "dag" in str(run)


@pytest.mark.django_db
class TestAgentStepModel:
    def test_step_order_unique_per_run(self, user):
        run = services.create_agent_run(user, "q", "", kind="react")
        AgentStep.objects.create(run=run, order=0)
        with pytest.raises(IntegrityError):
            AgentStep.objects.create(run=run, order=0)

    def test_same_order_allowed_across_runs(self, user):
        a = services.create_agent_run(user, "q", "", kind="react")
        b = services.create_agent_run(user, "q", "", kind="react")
        AgentStep.objects.create(run=a, order=0)
        AgentStep.objects.create(run=b, order=0)  # no clash - scoped to run
        assert AgentStep.objects.filter(order=0).count() == 2

    def test_meta_defaults_to_empty_dict(self, user):
        run = services.create_agent_run(user, "q", "", kind="dag")
        step = AgentStep.objects.create(run=run, order=0)
        step.refresh_from_db()
        assert step.meta == {}

    def test_steps_related_name(self, user):
        run = services.create_agent_run(user, "q", "", kind="chain")
        AgentStep.objects.create(run=run, order=0, key="classify")
        AgentStep.objects.create(run=run, order=1, key="research")
        assert [s.key for s in run.steps.order_by("order")] == ["classify", "research"]


# ---------------------------------------------------------------------------
# Cross-kind query isolation (all kinds share one table now)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCrossKindIsolation:
    def test_history_endpoints_filter_by_kind(self, auth_client, user):
        services.create_agent_run(user, "react one", "", kind="react", max_steps=6)
        services.create_agent_run(user, "chain one", "", kind="chain")

        react = auth_client.get("/api/llm/react/history/")
        chain = auth_client.get("/api/llm/chain/")
        assert react.status_code == 200
        assert chain.status_code == 200

        react_queries = [r["query"] for r in react.data["results"]]
        chain_queries = [r["query"] for r in chain.data["results"]]
        assert react_queries == ["react one"]
        assert chain_queries == ["chain one"]

    def test_detail_404_for_wrong_kind(self, auth_client, user):
        # A chain run must not be reachable through the react detail endpoint.
        chain = services.create_agent_run(user, "q", "", kind="chain")
        response = auth_client.get(f"/api/llm/react/{chain.id}/")
        assert response.status_code == 404

    def test_detail_200_for_matching_kind(self, auth_client, user):
        react = services.create_agent_run(user, "q", "", kind="react", max_steps=6)
        response = auth_client.get(f"/api/llm/react/{react.id}/")
        assert response.status_code == 200
        assert response.data["id"] == str(react.id)


# ---------------------------------------------------------------------------
# Per-kind serializers preserve the legacy JSON field names
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSerializerFieldAliasing:
    """Each kind serializer must rename the unified columns back to the field names the
    frontend already consumes: ``key`` -> step_id/task_id/worker_id/node_id/agent_id,
    ``order`` -> index, ``parent`` -> chain_run, and the ``steps`` collection ->
    iterations/tasks/workers/nodes/cycles."""

    def _run(self, user, kind, **fields):
        return services.create_agent_run(user, "q", "", kind=kind, **fields)

    def test_chain_step_id_from_key(self, user):
        run = self._run(user, "chain")
        AgentStep.objects.create(run=run, order=0, key="classify", label="Classify")
        data = ser.ChainRunSerializer(run).data
        assert data["steps"][0]["step_id"] == "classify"
        assert "key" not in data["steps"][0]

    def test_route_chain_run_from_parent(self, user):
        chain = self._run(user, "chain")
        route = self._run(user, "route")
        route.parent = chain
        route.save(update_fields=["parent"])
        data = ser.RouteRunSerializer(route).data
        assert data["chain_run"] == chain.id

    def test_parallel_task_id_from_key_and_tasks_from_steps(self, user):
        run = self._run(user, "parallel", strategy="voting", n=2)
        AgentStep.objects.create(run=run, order=0, key="vote_0", meta={"vote": "buy"})
        data = ser.ParallelRunSerializer(run).data
        assert data["tasks"][0]["task_id"] == "vote_0"
        assert data["tasks"][0]["vote"] == "buy"

    def test_eval_iterations_from_steps(self, user):
        run = self._run(user, "eval_opt", max_iterations=3, threshold=8)
        AgentStep.objects.create(run=run, order=0, meta={"draft": "d", "score": 7})
        data = ser.EvalOptRunSerializer(run).data
        assert data["iterations"][0]["score"] == 7

    def test_orchestrator_worker_id_from_key_and_workers_from_steps(self, user):
        run = self._run(user, "orchestrator", max_workers=4)
        AgentStep.objects.create(run=run, order=0, key="valuation", label="Valuation")
        data = ser.OrchestratorRunSerializer(run).data
        assert data["workers"][0]["worker_id"] == "valuation"

    def test_multiagent_agent_id_from_key(self, user):
        run = self._run(user, "multiagent", max_tools=4)
        AgentStep.objects.create(run=run, order=0, key="researcher", label="Researcher")
        data = ser.MultiAgentRunSerializer(run).data
        assert data["steps"][0]["agent_id"] == "researcher"

    def test_dag_node_id_from_key_and_nodes_from_steps(self, user):
        run = self._run(user, "dag", max_nodes=6)
        AgentStep.objects.create(run=run, order=0, key="a", meta={"wave": 0, "depends_on": []})
        data = ser.DagRunSerializer(run).data
        assert data["nodes"][0]["node_id"] == "a"
        assert data["nodes"][0]["wave"] == 0

    def test_autonomous_index_from_order_and_cycles_from_steps(self, user):
        run = self._run(user, "autonomous", max_cycles=8, max_subagents=3)
        AgentStep.objects.create(run=run, order=2, meta={"action": "tool", "reflection": "r"})
        data = ser.AutonomousRunSerializer(run).data
        assert data["cycles"][0]["index"] == 2
        assert data["cycles"][0]["action"] == "tool"

    def test_react_steps_keep_step_shape(self, user):
        run = self._run(user, "react", max_steps=6)
        AgentStep.objects.create(run=run, order=0, meta={"thought": "t", "tool": "recent_price"})
        data = ser.ReactRunSerializer(run).data
        assert data["steps"][0]["thought"] == "t"
        assert data["steps"][0]["tool"] == "recent_price"
