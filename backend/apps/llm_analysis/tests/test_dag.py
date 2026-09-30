import json
from unittest.mock import patch

import pytest

from apps.llm_analysis.dag import (
    Node,
    parse_nodes,
    run_dag,
    topological_waves,
)
from apps.llm_analysis.models import AgentRun, AgentStep
from apps.llm_analysis.services import OllamaServiceError, create_dag_run

DAG_URL = "/api/llm/dag/"
DAG_LIST_URL = "/api/llm/dag/history/"


def _events(generator):
    return [json.loads(e[len("data: ") :].strip()) for e in generator]


def _node(node_id, task="t", focus=None, tool=None, args=None, depends_on=None):
    return {
        "id": node_id,
        "task": task,
        "focus": focus or node_id,
        "tool": tool,
        "args": args,
        "depends_on": depends_on or [],
    }


def _decompose(*nodes):
    return json.dumps({"nodes": list(nodes)})


def _many(*outputs):
    """Build a chat_many side-effect returning one ok result per node in a wave."""

    def fake_chat_many(batches, model=None):
        return [
            {"ok": outputs[i] if i < len(outputs) else "out", "error": None}
            for i in range(len(batches))
        ]

    return fake_chat_many


# ---------------------------------------------------------------------------
# topological_waves (pure)
# ---------------------------------------------------------------------------


class TestTopologicalWaves:
    def test_independent_nodes_single_wave(self):
        nodes = [Node("a", "t", "a"), Node("b", "t", "b"), Node("c", "t", "c")]
        waves = topological_waves(nodes)
        assert len(waves) == 1
        assert {n.id for n in waves[0]} == {"a", "b", "c"}

    def test_linear_chain_three_waves(self):
        nodes = [
            Node("a", "t", "a"),
            Node("b", "t", "b", depends_on=["a"]),
            Node("c", "t", "c", depends_on=["b"]),
        ]
        waves = topological_waves(nodes)
        assert [[n.id for n in w] for w in waves] == [["a"], ["b"], ["c"]]

    def test_diamond(self):
        nodes = [
            Node("a", "t", "a"),
            Node("b", "t", "b", depends_on=["a"]),
            Node("c", "t", "c", depends_on=["a"]),
            Node("d", "t", "d", depends_on=["b", "c"]),
        ]
        waves = topological_waves(nodes)
        assert [n.id for n in waves[0]] == ["a"]
        assert {n.id for n in waves[1]} == {"b", "c"}
        assert [n.id for n in waves[2]] == ["d"]

    def test_preserves_creation_order_within_wave(self):
        nodes = [Node("z", "t", "z"), Node("a", "t", "a")]
        waves = topological_waves(nodes)
        assert [n.id for n in waves[0]] == ["z", "a"]

    def test_residual_cycle_does_not_loop_forever(self):
        # Hand-crafted cycle (bypassing parse_nodes) -> defensive final wave.
        nodes = [
            Node("a", "t", "a", depends_on=["b"]),
            Node("b", "t", "b", depends_on=["a"]),
        ]
        waves = topological_waves(nodes)
        assert sum(len(w) for w in waves) == 2


# ---------------------------------------------------------------------------
# parse_nodes (pure)
# ---------------------------------------------------------------------------


class TestParseNodes:
    def test_basic(self):
        nodes = parse_nodes(_decompose(_node("n1", task="do x", focus="X")), 6)
        assert len(nodes) == 1
        assert nodes[0].id == "n1"
        assert nodes[0].focus == "X"

    def test_assigns_missing_ids(self):
        raw = json.dumps({"nodes": [{"task": "a"}, {"task": "b"}]})
        nodes = parse_nodes(raw, 6)
        assert [n.id for n in nodes] == ["n1", "n2"]

    def test_edges_resolve_to_assigned_ids(self):
        nodes = parse_nodes(_decompose(_node("a"), _node("b", depends_on=["a"])), 6)
        assert nodes[1].depends_on == ["a"]

    def test_prunes_unknown_deps(self):
        nodes = parse_nodes(_decompose(_node("a", depends_on=["ghost"])), 6)
        assert nodes[0].depends_on == []

    def test_drops_self_loop(self):
        nodes = parse_nodes(_decompose(_node("a", depends_on=["a"])), 6)
        assert nodes[0].depends_on == []

    def test_breaks_cycles(self):
        nodes = parse_nodes(
            _decompose(
                _node("a", depends_on=["b"]),
                _node("b", depends_on=["a"]),
            ),
            6,
        )
        # One of the two back-edges is removed -> the graph is acyclic.
        total_edges = sum(len(n.depends_on) for n in nodes)
        assert total_edges == 1
        # And it lays out into ordered waves.
        waves = topological_waves(nodes)
        assert sum(len(w) for w in waves) == 2

    def test_caps_at_max_nodes_and_prunes_edges_to_dropped(self):
        many = [_node(f"n{i}") for i in range(1, 9)]
        many.append(_node("late", depends_on=["n1"]))
        nodes = parse_nodes(json.dumps({"nodes": many}), 3)
        assert len(nodes) == 3
        assert all("late" not in n.depends_on for n in nodes)

    def test_tool_null_normalised(self):
        nodes = parse_nodes(_decompose(_node("a", tool="null")), 6)
        assert nodes[0].tool is None

    def test_bare_list_tolerated(self):
        nodes = parse_nodes(json.dumps([_node("a")]), 6)
        assert nodes[0].id == "a"

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            parse_nodes('{"nodes": []}', 6)

    def test_unparseable_raises(self):
        with pytest.raises(ValueError):
            parse_nodes("no json here", 6)


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDagLoop:
    def _run(self, user, query="Compare AAPL and MSFT", max_nodes=6):
        return create_dag_run(user=user, query=query, model="", max_nodes=max_nodes)

    def test_runs_waves_in_order_concurrent_within_wave(self, user):
        run = self._run(user)
        decompose = _decompose(
            _node("a"),
            _node("b"),
            _node("c", depends_on=["a", "b"]),
        )
        many_calls = []

        def fake_many(batches, model=None):
            many_calls.append([m for m in batches])
            return [{"ok": f"out{i}", "error": None} for i in range(len(batches))]

        with (
            patch("apps.llm_analysis.services.chat", side_effect=[decompose, "## Final"]),
            patch("apps.llm_analysis.services.chat_many", side_effect=fake_many),
        ):
            events = _events(run_dag(run, model=""))

        # Two waves -> two chat_many calls; first wave fans out 2, second 1.
        assert len(many_calls) == 2
        assert len(many_calls[0]) == 2
        assert len(many_calls[1]) == 1
        plan = next(e for e in events if e["event"] == "plan")
        assert plan["waves"] == [["a", "b"], ["c"]]
        assert events[-1]["event"] == "result"
        assert events[-1]["output"] == "## Final"
        assert events[-1]["waves"] == 2

    def test_downstream_node_sees_upstream_output(self, user):
        run = self._run(user)
        decompose = _decompose(_node("a"), _node("b", depends_on=["a"]))
        captured = {}

        def fake_many(batches, model=None):
            # wave 0 = node a; wave 1 = node b (its prompt must contain a's output).
            user_text = batches[0][1]["content"]
            captured.setdefault("order", []).append(user_text)
            return [{"ok": "AAA_OUTPUT", "error": None}]

        with (
            patch("apps.llm_analysis.services.chat", side_effect=[decompose, "final"]),
            patch("apps.llm_analysis.services.chat_many", side_effect=fake_many),
        ):
            _events(run_dag(run, model=""))

        assert "AAA_OUTPUT" in captured["order"][1]

    def test_node_tool_observation_fed_to_node(self, user):
        run = self._run(user)
        decompose = _decompose(_node("a", tool="company_snapshot", args={"symbol": "AAPL"}))
        captured = {}

        def fake_many(batches, model=None):
            captured["prompt"] = batches[0][1]["content"]
            return [{"ok": "out", "error": None}]

        with (
            patch("apps.llm_analysis.services.chat", side_effect=[decompose, "final"]),
            patch("apps.llm_analysis.services.chat_many", side_effect=fake_many),
            patch("apps.llm_analysis.tools.run_tool", return_value='{"pe": 30}') as run_tool,
        ):
            _events(run_dag(run, model=""))

        run_tool.assert_called_once_with("company_snapshot", {"symbol": "AAPL"})
        assert '{"pe": 30}' in captured["prompt"]

    def test_reasoning_node_makes_no_tool_call(self, user):
        run = self._run(user)
        decompose = _decompose(_node("a", tool=None))
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[decompose, "final"]),
            patch("apps.llm_analysis.services.chat_many", side_effect=_many("out")),
            patch("apps.llm_analysis.tools.run_tool") as run_tool,
        ):
            _events(run_dag(run, model=""))
        run_tool.assert_not_called()

    def test_one_node_fails_others_proceed(self, user):
        run = self._run(user)
        decompose = _decompose(_node("a"), _node("b"))

        def fake_many(batches, model=None):
            return [
                {"ok": None, "error": "boom"},
                {"ok": "ok_b", "error": None},
            ]

        with (
            patch("apps.llm_analysis.services.chat", side_effect=[decompose, "final"]),
            patch("apps.llm_analysis.services.chat_many", side_effect=fake_many),
        ):
            events = _events(run_dag(run, model=""))

        node_events = [e for e in events if e["event"] == "node"]
        # "id" is the AgentStep row UUID; the graph node key is "node_id" - the same
        # names the detail endpoint uses, since both now share one serialisation.
        statuses = {e["node_id"]: e["status"] for e in node_events}
        assert statuses == {"a": "error", "b": "done"}
        assert events[-1]["event"] == "result"

    def test_all_nodes_fail_finishes_error(self, user):
        run = self._run(user)
        decompose = _decompose(_node("a"))

        def fake_many(batches, model=None):
            return [{"ok": None, "error": "boom"}]

        with (
            patch("apps.llm_analysis.services.chat", side_effect=[decompose, "final"]),
            patch("apps.llm_analysis.services.chat_many", side_effect=fake_many),
        ):
            events = _events(run_dag(run, model=""))

        assert events[-1]["event"] == "error"
        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR

    def test_unparseable_decomposition_finishes_error(self, user):
        run = self._run(user)
        with patch("apps.llm_analysis.services.chat", side_effect=["not json", "x"]):
            events = _events(run_dag(run, model=""))
        assert events[-1]["event"] == "error"
        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR

    def test_decompose_error_finishes_run_error(self, user):
        run = self._run(user)
        with patch("apps.llm_analysis.services.chat", side_effect=OllamaServiceError("down")):
            events = _events(run_dag(run, model=""))
        assert events[-1]["event"] == "error"
        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR

    def test_synthesis_sees_terminal_outputs(self, user):
        run = self._run(user)
        decompose = _decompose(_node("a"), _node("b", depends_on=["a"]))
        captured = {}

        def fake_chat(messages, model=None):
            system = messages[0]["content"]
            if "orchestrator" in system:
                return decompose
            captured["synth"] = messages[1]["content"]
            return "## Final"

        def fake_many(batches, model=None):
            # Both waves produce node b's output last.
            return [
                {
                    "ok": "B_TERMINAL" if "depend" in batches[0][1]["content"] else "A_INNER",
                    "error": None,
                }
            ]

        with (
            patch("apps.llm_analysis.services.chat", side_effect=fake_chat),
            patch("apps.llm_analysis.services.chat_many", side_effect=fake_many),
        ):
            _events(run_dag(run, model=""))

        # b is the only sink -> its output is in the synthesis prompt.
        assert "B_TERMINAL" in captured["synth"]

    def test_run_and_nodes_persisted(self, user):
        run = self._run(user)
        decompose = _decompose(_node("a"), _node("b", depends_on=["a"]))
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[decompose, "## Final"]),
            patch("apps.llm_analysis.services.chat_many", side_effect=_many("oa", "ob")),
        ):
            _events(run_dag(run, model=""))

        run.refresh_from_db()
        assert run.status == AgentRun.Status.DONE
        assert run.meta["plan"]["waves"] == [["a"], ["b"]]
        nodes = list(AgentStep.objects.filter(run=run).order_by("order"))
        assert [n.key for n in nodes] == ["a", "b"]
        assert nodes[0].meta["wave"] == 0
        assert nodes[1].meta["wave"] == 1
        assert nodes[1].meta["depends_on"] == ["a"]


# ---------------------------------------------------------------------------
# Integration: real tools driven through the loop (only the LLM is mocked)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDagWithRealTools:
    @pytest.fixture
    def tech_sector(self):
        from apps.companies.models import Company, CompanySnapshot, Sector

        sector = Sector.objects.create(name="Technology")
        aapl = Company.objects.create(symbol="AAPL", name="Apple", sector=sector)
        msft = Company.objects.create(symbol="MSFT", name="Microsoft", sector=sector)
        CompanySnapshot.objects.create(company=aapl, trailing_pe=30.0, market_cap=3000, raw={})
        CompanySnapshot.objects.create(company=msft, trailing_pe=20.0, market_cap=2000, raw={})
        return sector

    def test_real_tool_observation_flows_into_node(self, user, tech_sector):
        run = create_dag_run(user=user, query="Is AAPL cheap vs its sector?", model="", max_nodes=6)
        decompose = _decompose(
            _node("a", tool="sector_analysis", args={"sector": "Technology"}),
        )
        captured = {}

        def fake_many(batches, model=None):
            captured["prompt"] = batches[0][1]["content"]
            return [{"ok": "node out", "error": None}]

        # tools.run_tool is NOT mocked - the real sector aggregation runs against the DB.
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[decompose, "## Final"]),
            patch("apps.llm_analysis.services.chat_many", side_effect=fake_many),
        ):
            events = _events(run_dag(run, model=""))

        node = next(e for e in events if e["event"] == "node")
        observation = json.loads(node["observation"])
        assert observation["sector"] == "Technology"
        assert observation["companies"] == 2
        assert observation["metrics"]["trailing_pe"]["median"] == 25.0
        assert '"sector": "Technology"' in captured["prompt"]
        assert events[-1]["event"] == "result"


# ---------------------------------------------------------------------------
# DagView  POST /api/llm/dag/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDagView:
    def test_dag_view_unauthenticated(self, api_client):
        response = api_client.post(DAG_URL, {"query": "test"}, format="json")
        assert response.status_code == 401

    def test_dag_view_missing_query(self, auth_client):
        response = auth_client.post(DAG_URL, {}, format="json")
        assert response.status_code == 400

    def test_dag_view_max_nodes_out_of_range(self, auth_client):
        response = auth_client.post(DAG_URL, {"query": "x", "max_nodes": 99}, format="json")
        assert response.status_code == 400

    @pytest.mark.django_db(transaction=True)
    def test_dag_view_streams_sse(self, auth_client):
        decompose = _decompose(_node("a"))
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[decompose, "## Done"]),
            patch("apps.llm_analysis.services.chat_many", side_effect=_many("out")),
        ):
            response = auth_client.post(DAG_URL, {"query": "test"}, format="json")
            assert response.status_code == 200
            assert "text/event-stream" in response.get("Content-Type", "")
            content = b"".join(response.streaming_content).decode()

        events = [
            json.loads(line[len("data: ") :])
            for line in content.splitlines()
            if line.startswith("data:")
        ]
        kinds = [e["event"] for e in events]
        assert kinds[0] == "plan"
        assert "wave" in kinds
        assert "node" in kinds
        assert kinds[-1] == "result"


# ---------------------------------------------------------------------------
# History + detail
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDagHistory:
    def test_dag_run_list_filtered_to_user(self, auth_client, user):
        from django.contrib.auth import get_user_model

        other = get_user_model().objects.create_user(email="dagother@x.com", password="pass")
        create_dag_run(user=user, query="mine", model="", max_nodes=6)
        create_dag_run(user=other, query="theirs", model="", max_nodes=6)

        response = auth_client.get(DAG_LIST_URL)
        assert response.status_code == 200
        queries = [r["query"] for r in response.data["results"]]
        assert "mine" in queries
        assert "theirs" not in queries

    def test_dag_run_detail_404_other_user(self, auth_client, user):
        from django.contrib.auth import get_user_model

        other = get_user_model().objects.create_user(email="dagother2@x.com", password="pass")
        run = create_dag_run(user=other, query="theirs", model="", max_nodes=6)

        response = auth_client.get(f"/api/llm/dag/{run.id}/")
        assert response.status_code == 404
