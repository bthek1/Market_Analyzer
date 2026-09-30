import json
from unittest.mock import patch

import pytest

from apps.llm_analysis.models import AgentRun
from apps.llm_analysis.orchestrator import parse_subtasks, run_orchestrator
from apps.llm_analysis.services import OllamaServiceError, create_orchestrator_run

ORCH_URL = "/api/llm/orchestrate/"
ORCH_LIST_URL = "/api/llm/orchestrate/history/"


def _events(generator):
    return [json.loads(e[len("data: ") :].strip()) for e in generator]


def _orch(*subtasks):
    """Build an orchestrator JSON response from (task, focus, tool, args) tuples."""
    return json.dumps(
        {
            "subtasks": [
                {"task": t, "focus": focus, "tool": tool, "args": args}
                for (t, focus, tool, args) in subtasks
            ]
        }
    )


def _ok_many(*outputs):
    """Build a chat_many return value (one {"ok"/"error"} dict per output)."""
    return [{"ok": o, "error": None} for o in outputs]


# ---------------------------------------------------------------------------
# parse_subtasks (pure)
# ---------------------------------------------------------------------------


class TestParseSubtasks:
    def test_object_with_subtasks_key(self):
        out = parse_subtasks(
            _orch(("do x", "valuation", "company_snapshot", {"symbol": "AAPL"})), 4
        )
        assert out == [
            {
                "task": "do x",
                "focus": "valuation",
                "tool": "company_snapshot",
                "args": {"symbol": "AAPL"},
            }
        ]

    def test_bare_list_tolerated(self):
        out = parse_subtasks('[{"task": "think", "focus": "risk", "tool": null}]', 4)
        assert out == [{"task": "think", "focus": "risk", "tool": None, "args": None}]

    def test_null_string_tool_becomes_none(self):
        out = parse_subtasks(_orch(("t", "f", "null", None)), 4)
        assert out[0]["tool"] is None

    def test_missing_focus_derived_from_task(self):
        out = parse_subtasks('{"subtasks": [{"task": "analyse the balance sheet"}]}', 4)
        assert out[0]["focus"] == "analyse the balance sheet"[:40]

    def test_capped_at_max_workers(self):
        out = parse_subtasks(_orch(*[(f"s{i}", f"f{i}", None, None) for i in range(10)]), 3)
        assert len(out) == 3

    def test_unparseable_raises(self):
        with pytest.raises(ValueError):
            parse_subtasks("not a decomposition at all", 4)

    def test_empty_subtasks_raises(self):
        with pytest.raises(ValueError):
            parse_subtasks('{"subtasks": []}', 4)

    def test_non_dict_entries_skipped(self):
        out = parse_subtasks('{"subtasks": ["junk", {"task": "real", "focus": "f"}]}', 4)
        assert out == [{"task": "real", "focus": "f", "tool": None, "args": None}]

    def test_entries_without_task_skipped(self):
        out = parse_subtasks('{"subtasks": [{"focus": "f"}, {"task": "real"}]}', 4)
        assert len(out) == 1
        assert out[0]["task"] == "real"

    def test_all_unusable_raises(self):
        with pytest.raises(ValueError):
            parse_subtasks('{"subtasks": ["a", "b"]}', 4)


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestOrchestratorLoop:
    def _run(self, user, query="Give me a full picture of AAPL", max_workers=4):
        return create_orchestrator_run(user=user, query=query, model="", max_workers=max_workers)

    def test_decomposes_then_fans_out(self, user):
        run = self._run(user)
        orchestrate = _orch(
            ("Summarise valuation", "valuation", None, None),
            ("Assess risk", "risk", None, None),
            ("Note momentum", "momentum", None, None),
        )
        with (
            patch(
                "apps.llm_analysis.services.chat",
                side_effect=[orchestrate, "## Final\nDone."],
            ),
            patch(
                "apps.llm_analysis.services.chat_many",
                return_value=_ok_many("val out", "risk out", "mom out"),
            ),
        ):
            events = _events(run_orchestrator(run, model=""))

        assert events[0]["event"] == "started"
        assert events[1]["event"] == "plan"
        workers = [e for e in events if e["event"] == "worker"]
        assert [w["order"] for w in workers] == [0, 1, 2]
        assert [w["output"] for w in workers] == ["val out", "risk out", "mom out"]
        assert events[-1]["event"] == "result"
        assert events[-1]["output"] == "## Final\nDone."
        assert events[-1]["workers"] == 3

    def test_worker_with_tool_runs_tool_then_worker(self, user):
        run = self._run(user)
        orchestrate = _orch(
            ("Aggregate sector", "valuation", "sector_analysis", {"sector": "Technology"})
        )
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[orchestrate, "final"]),
            patch("apps.llm_analysis.tools.run_tool", return_value='{"metrics": {}}') as run_tool,
            patch(
                "apps.llm_analysis.services.chat_many", return_value=_ok_many("w out")
            ) as chat_many,
        ):
            events = _events(run_orchestrator(run, model=""))

        run_tool.assert_called_once_with("sector_analysis", {"sector": "Technology"})
        # The observation was fed into that worker's chat_many batch.
        batches = chat_many.call_args.args[0]
        assert '{"metrics": {}}' in batches[0][1]["content"]
        worker = next(e for e in events if e["event"] == "worker")
        assert worker["observation"] == '{"metrics": {}}'

    def test_pure_reasoning_subtask_no_tool(self, user):
        run = self._run(user)
        orchestrate = _orch(("Just reason", "thesis", None, None))
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[orchestrate, "final"]),
            patch("apps.llm_analysis.tools.run_tool") as run_tool,
            patch("apps.llm_analysis.services.chat_many", return_value=_ok_many("reasoned")),
        ):
            events = _events(run_orchestrator(run, model=""))

        run_tool.assert_not_called()
        worker = next(e for e in events if e["event"] == "worker")
        # Empty rather than None: the step event is now the step's DRF representation,
        # so an absent meta value reads the same live as it does on a refresh-restore.
        assert worker["observation"] == ""
        assert worker["tool"] == ""
        assert worker["output"] == "reasoned"

    def test_workers_run_concurrently_via_chat_many(self, user):
        run = self._run(user)
        orchestrate = _orch(
            ("a", "fa", None, None), ("b", "fb", None, None), ("c", "fc", None, None)
        )
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[orchestrate, "final"]),
            patch(
                "apps.llm_analysis.services.chat_many",
                return_value=_ok_many("oa", "ob", "oc"),
            ) as chat_many,
        ):
            _events(run_orchestrator(run, model=""))

        chat_many.assert_called_once()
        batches = chat_many.call_args.args[0]
        assert len(batches) == 3  # one batch per subtask

    def test_one_worker_fails_others_survive(self, user):
        run = self._run(user)
        orchestrate = _orch(("a", "fa", None, None), ("b", "fb", None, None))
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[orchestrate, "final"]),
            patch(
                "apps.llm_analysis.services.chat_many",
                return_value=[
                    {"ok": "good", "error": None},
                    {"ok": None, "error": "boom"},
                ],
            ),
        ):
            events = _events(run_orchestrator(run, model=""))

        workers = [e for e in events if e["event"] == "worker"]
        assert workers[0]["status"] == "done"
        assert workers[1]["status"] == "error"
        assert workers[1]["error"] == "boom"
        assert events[-1]["event"] == "result"  # still synthesised

    def test_all_workers_fail_finishes_error(self, user):
        run = self._run(user)
        orchestrate = _orch(("a", "fa", None, None), ("b", "fb", None, None))
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[orchestrate, "final"]),
            patch(
                "apps.llm_analysis.services.chat_many",
                return_value=[
                    {"ok": None, "error": "boom1"},
                    {"ok": None, "error": "boom2"},
                ],
            ),
        ):
            events = _events(run_orchestrator(run, model=""))

        assert events[-1]["event"] == "error"
        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR

    def test_subtasks_capped_at_max_workers(self, user):
        run = self._run(user, max_workers=2)
        orchestrate = _orch(
            ("a", "fa", None, None),
            ("b", "fb", None, None),
            ("c", "fc", None, None),
            ("d", "fd", None, None),
        )
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[orchestrate, "final"]),
            patch("apps.llm_analysis.services.chat_many", return_value=_ok_many("oa", "ob")),
        ):
            events = _events(run_orchestrator(run, model=""))

        plan_event = next(e for e in events if e["event"] == "plan")
        assert len(plan_event["subtasks"]) == 2
        assert len([e for e in events if e["event"] == "worker"]) == 2

    def test_unparseable_decomposition_finishes_error(self, user):
        run = self._run(user)
        with patch("apps.llm_analysis.services.chat", side_effect=["I cannot decompose this"]):
            events = _events(run_orchestrator(run, model=""))

        assert events[-1]["event"] == "error"
        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR

    def test_synthesis_sees_all_worker_outputs(self, user):
        run = self._run(user)
        seen = []

        def fake_chat(messages, model=None):
            seen.append(messages)
            system = messages[0]["content"]
            if "orchestrator" in system:
                return _orch(("a", "fa", None, None), ("b", "fb", None, None))
            return "synthesised"

        with (
            patch("apps.llm_analysis.services.chat", side_effect=fake_chat),
            patch(
                "apps.llm_analysis.services.chat_many",
                return_value=_ok_many("alpha-out", "beta-out"),
            ),
        ):
            _events(run_orchestrator(run, model=""))

        synth_user = seen[-1][1]["content"]
        assert "alpha-out" in synth_user
        assert "beta-out" in synth_user

    def test_run_and_workers_persisted(self, user):
        run = self._run(user)
        orchestrate = _orch(("a", "fa", None, None), ("b", "fb", None, None))
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[orchestrate, "done"]),
            patch("apps.llm_analysis.services.chat_many", return_value=_ok_many("oa", "ob")),
        ):
            _events(run_orchestrator(run, model=""))

        run.refresh_from_db()
        assert run.output == "done"
        assert run.meta["plan"] is not None and len(run.meta["plan"]) == 2
        orders = list(run.steps.values_list("order", flat=True))
        assert orders == [0, 1]
        assert run.steps.get(order=0).output == "oa"

    def test_orchestrate_error_finishes_run_error(self, user):
        run = self._run(user)
        with patch("apps.llm_analysis.services.chat", side_effect=OllamaServiceError("down")):
            events = _events(run_orchestrator(run, model=""))

        assert events[-1]["event"] == "error"
        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR

    def test_synthesis_error_finishes_run(self, user):
        run = self._run(user)
        orchestrate = _orch(("a", "fa", None, None))
        with (
            patch(
                "apps.llm_analysis.services.chat",
                side_effect=[orchestrate, OllamaServiceError("synth down")],
            ),
            patch("apps.llm_analysis.services.chat_many", return_value=_ok_many("oa")),
        ):
            events = _events(run_orchestrator(run, model=""))

        assert events[-1]["event"] == "error"
        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR

    def test_duplicate_focus_labels_get_unique_worker_ids(self, user):
        run = self._run(user)
        orchestrate = _orch(("a", "risk", None, None), ("b", "risk", None, None))
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[orchestrate, "final"]),
            patch("apps.llm_analysis.services.chat_many", return_value=_ok_many("oa", "ob")),
        ):
            _events(run_orchestrator(run, model=""))

        ids = list(run.steps.order_by("order").values_list("key", flat=True))
        assert len(set(ids)) == 2


# ---------------------------------------------------------------------------
# Integration: real tools driven through the loop (only the LLM is mocked)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestOrchestratorWithRealTools:
    @pytest.fixture
    def tech_sector(self):
        from apps.companies.models import Company, CompanySnapshot, Sector

        sector = Sector.objects.create(name="Technology")
        aapl = Company.objects.create(symbol="AAPL", name="Apple", sector=sector)
        msft = Company.objects.create(symbol="MSFT", name="Microsoft", sector=sector)
        CompanySnapshot.objects.create(company=aapl, trailing_pe=30.0, market_cap=3000, raw={})
        CompanySnapshot.objects.create(company=msft, trailing_pe=20.0, market_cap=2000, raw={})
        return sector

    def test_real_tool_observation_flows_to_worker(self, user, tech_sector):
        run = create_orchestrator_run(
            user=user, query="Is AAPL cheap vs its sector?", model="", max_workers=4
        )
        captured = {}

        def fake_chat_many(batches, model=None):
            captured["batches"] = batches
            return _ok_many(*["worker out" for _ in batches])

        orchestrate = _orch(
            (
                "Aggregate the Technology sector",
                "valuation",
                "sector_analysis",
                {"sector": "Technology"},
            )
        )
        # tools.run_tool is NOT mocked - the real sector aggregation runs against the DB.
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[orchestrate, "## Verdict"]),
            patch("apps.llm_analysis.services.chat_many", side_effect=fake_chat_many),
        ):
            events = _events(run_orchestrator(run, model=""))

        worker = next(e for e in events if e["event"] == "worker")
        observation = json.loads(worker["observation"])
        assert worker["tool"] == "sector_analysis"
        assert observation["sector"] == "Technology"
        assert observation["companies"] == 2
        assert observation["metrics"]["trailing_pe"]["median"] == 25.0
        # That real observation was passed into the worker's prompt.
        assert '"median": 25.0' in captured["batches"][0][1]["content"]
        assert events[-1]["event"] == "result"


# ---------------------------------------------------------------------------
# OrchestratorView  POST /api/llm/orchestrate/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestOrchestratorView:
    def test_orchestrate_view_unauthenticated(self, api_client):
        response = api_client.post(ORCH_URL, {"query": "test"}, format="json")
        assert response.status_code == 401

    def test_orchestrate_view_missing_query(self, auth_client):
        response = auth_client.post(ORCH_URL, {}, format="json")
        assert response.status_code == 400

    def test_orchestrate_view_max_workers_out_of_range(self, auth_client):
        response = auth_client.post(ORCH_URL, {"query": "x", "max_workers": 99}, format="json")
        assert response.status_code == 400

    @pytest.mark.django_db(transaction=True)
    def test_orchestrate_view_streams_sse(self, auth_client):
        orchestrate = _orch(("step", "focus", None, None))
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[orchestrate, "## Done"]),
            patch("apps.llm_analysis.services.chat_many", return_value=_ok_many("w")),
        ):
            response = auth_client.post(ORCH_URL, {"query": "test"}, format="json")
            assert response.status_code == 200
            assert "text/event-stream" in response.get("Content-Type", "")
            content = b"".join(response.streaming_content).decode()

        events = [
            json.loads(line[len("data: ") :])
            for line in content.splitlines()
            if line.startswith("data:")
        ]
        kinds = [e["event"] for e in events]
        assert kinds[0] == "started"
        assert "plan" in kinds
        assert "worker" in kinds
        assert kinds[-1] == "result"


# ---------------------------------------------------------------------------
# History + detail
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestOrchestratorHistory:
    def test_orchestrate_run_list_filtered_to_user(self, auth_client, user):
        from django.contrib.auth import get_user_model

        other = get_user_model().objects.create_user(email="oother@x.com", password="pass")
        create_orchestrator_run(user=user, query="mine", model="", max_workers=4)
        create_orchestrator_run(user=other, query="theirs", model="", max_workers=4)

        response = auth_client.get(ORCH_LIST_URL)
        assert response.status_code == 200
        queries = [r["query"] for r in response.data["results"]]
        assert "mine" in queries
        assert "theirs" not in queries

    def test_orchestrate_run_detail_404_other_user(self, auth_client, user):
        from django.contrib.auth import get_user_model

        other = get_user_model().objects.create_user(email="oother2@x.com", password="pass")
        run = create_orchestrator_run(user=other, query="theirs", model="", max_workers=4)

        response = auth_client.get(f"/api/llm/orchestrate/{run.id}/")
        assert response.status_code == 404
