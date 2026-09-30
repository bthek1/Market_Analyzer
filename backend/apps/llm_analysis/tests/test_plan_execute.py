import json
from unittest.mock import patch

import pytest

from apps.llm_analysis.models import AgentRun
from apps.llm_analysis.plan_execute import run_plan
from apps.llm_analysis.services import OllamaServiceError, create_plan_run

PLAN_URL = "/api/llm/plan/"
PLAN_LIST_URL = "/api/llm/plan/history/"


def _events(generator):
    return [json.loads(e[len("data: ") :].strip()) for e in generator]


def _plan(*steps):
    """Build a planner JSON response from (task, tool, args) tuples."""
    return json.dumps(
        {"plan": [{"task": t, "tool": tool, "args": args} for (t, tool, args) in steps]}
    )


# ---------------------------------------------------------------------------
# parse_plan (pure)
# ---------------------------------------------------------------------------


class TestParsePlan:
    def test_object_with_plan_key(self):
        from apps.llm_analysis.plan_execute import parse_plan

        out = parse_plan(_plan(("do x", "company_snapshot", {"symbol": "AAPL"})), 6)
        assert out == [{"task": "do x", "tool": "company_snapshot", "args": {"symbol": "AAPL"}}]

    def test_bare_list_tolerated(self):
        from apps.llm_analysis.plan_execute import parse_plan

        out = parse_plan('[{"task": "think", "tool": null}]', 6)
        assert out == [{"task": "think", "tool": None, "args": None}]

    def test_null_string_tool_becomes_none(self):
        from apps.llm_analysis.plan_execute import parse_plan

        out = parse_plan(_plan(("t", "null", None)), 6)
        assert out[0]["tool"] is None

    def test_capped_at_max_steps(self):
        from apps.llm_analysis.plan_execute import parse_plan

        out = parse_plan(_plan(*[(f"s{i}", None, None) for i in range(10)]), 3)
        assert len(out) == 3

    def test_unparseable_raises(self):
        from apps.llm_analysis.plan_execute import parse_plan

        with pytest.raises(ValueError):
            parse_plan("not a plan at all", 6)

    def test_empty_plan_raises(self):
        from apps.llm_analysis.plan_execute import parse_plan

        with pytest.raises(ValueError):
            parse_plan('{"plan": []}', 6)

    def test_malformed_bare_list_raises(self):
        from apps.llm_analysis.plan_execute import parse_plan

        with pytest.raises(ValueError):
            parse_plan("[this is, not json]", 6)

    def test_non_dict_steps_skipped(self):
        from apps.llm_analysis.plan_execute import parse_plan

        out = parse_plan('{"plan": ["junk", {"task": "real", "tool": null}]}', 6)
        assert out == [{"task": "real", "tool": None, "args": None}]

    def test_all_non_dict_steps_raises(self):
        from apps.llm_analysis.plan_execute import parse_plan

        with pytest.raises(ValueError):
            parse_plan('{"plan": ["a", "b"]}', 6)


class TestDiverged:
    def test_error_observation_diverged(self):
        from apps.llm_analysis.plan_execute import _diverged

        assert _diverged('{"error": "no company"}') is True

    def test_ok_observation_not_diverged(self):
        from apps.llm_analysis.plan_execute import _diverged

        assert _diverged('{"trailing_pe": 31}') is False

    def test_empty_observation_not_diverged(self):
        from apps.llm_analysis.plan_execute import _diverged

        assert _diverged("") is False

    def test_non_json_observation_not_diverged(self):
        from apps.llm_analysis.plan_execute import _diverged

        assert _diverged("plain text observation") is False


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPlanExecLoop:
    def _run(self, user, query="Is AAPL cheap?", max_steps=6, allow_replan=True):
        return create_plan_run(
            user=user, query=query, model="", max_steps=max_steps, allow_replan=allow_replan
        )

    def test_plans_then_executes_each_step(self, user):
        run = self._run(user)
        chat = [
            _plan(("step one", None, None), ("step two", None, None)),
            "result one",
            "result two",
            "## Final\nDone.",
        ]
        with patch("apps.llm_analysis.services.chat", side_effect=chat):
            events = _events(run_plan(run, model=""))

        assert events[0]["event"] == "started"
        assert events[1]["event"] == "plan"
        steps = [e for e in events if e["event"] == "step"]
        assert [s["order"] for s in steps] == [0, 1]
        assert [s["result"] for s in steps] == ["result one", "result two"]
        assert events[-1]["event"] == "result"
        assert events[-1]["output"] == "## Final\nDone."
        assert events[-1]["steps"] == 2

    def test_tool_step_runs_tool_then_executes(self, user):
        run = self._run(user)
        chat = [
            _plan(("fetch", "company_snapshot", {"symbol": "AAPL"})),
            "interpreted",
            "final",
        ]
        with (
            patch("apps.llm_analysis.services.chat", side_effect=chat),
            patch(
                "apps.llm_analysis.tools.run_tool", return_value='{"trailing_pe": 31}'
            ) as run_tool,
        ):
            events = _events(run_plan(run, model=""))

        run_tool.assert_called_once_with("company_snapshot", {"symbol": "AAPL"})
        step = next(e for e in events if e["event"] == "step")
        assert step["observation"] == '{"trailing_pe": 31}'

    def test_pure_reasoning_step_no_tool(self, user):
        run = self._run(user)
        chat = [_plan(("just think", None, None)), "thought result", "final"]
        with (
            patch("apps.llm_analysis.services.chat", side_effect=chat),
            patch("apps.llm_analysis.tools.run_tool") as run_tool,
        ):
            events = _events(run_plan(run, model=""))

        run_tool.assert_not_called()
        step = next(e for e in events if e["event"] == "step")
        # Empty rather than None: the step event is now the step's DRF representation,
        # so an absent value reads the same live as it does on a refresh-restore.
        assert step["observation"] == ""
        assert step["tool"] == ""

    def test_no_replan_when_allow_replan_false(self, user):
        run = self._run(user, allow_replan=False)
        chat = [_plan(("fetch", "company_profile", {"symbol": "NOPE"})), "result", "final"]
        with (
            patch("apps.llm_analysis.services.chat", side_effect=chat),
            patch("apps.llm_analysis.tools.run_tool", return_value='{"error": "no company"}'),
        ):
            events = _events(run_plan(run, model=""))

        assert not [e for e in events if e["event"] == "replan"]

    def test_replan_on_tool_error(self, user):
        run = self._run(user)
        chat = [
            _plan(("fetch", "company_profile", {"symbol": "NOPE"}), ("write", None, None)),
            "step result",  # execute step 0
            _plan(("retry differently", None, None)),  # replan tail
            "step result 2",  # execute revised step 1
            "final answer",  # synthesis
        ]
        with (
            patch("apps.llm_analysis.services.chat", side_effect=chat),
            patch("apps.llm_analysis.tools.run_tool", return_value='{"error": "no company"}'),
        ):
            events = _events(run_plan(run, model=""))

        replans = [e for e in events if e["event"] == "replan"]
        assert len(replans) == 1
        run.refresh_from_db()
        assert run.meta["replans"] == 1
        assert events[-1]["replans"] == 1

    def test_replan_budget_capped(self, user, llm_settings):
        llm_settings.plan_max_replans = 2
        run = self._run(user, max_steps=8)

        # Every execute step's tool errors, and every replan adds one more erroring step.
        def chat_side_effect(messages, model=None):
            system = messages[0]["content"]
            if "planner" in system:
                return _plan(("fetch", "company_profile", {"symbol": "X"}))
            if "revised plan" in system or "REMAINING" in system:
                return _plan(("fetch again", "company_profile", {"symbol": "X"}))
            if "final answer" in system or "senior financial analyst" in system:
                return "final"
            return "step result"

        with (
            patch("apps.llm_analysis.services.chat", side_effect=chat_side_effect),
            patch("apps.llm_analysis.tools.run_tool", return_value='{"error": "no company"}'),
        ):
            events = _events(run_plan(run, model=""))

        replans = [e for e in events if e["event"] == "replan"]
        assert len(replans) == 2  # capped at llm_settings.plan_max_replans
        run.refresh_from_db()
        assert run.meta["replans"] == 2

    def test_plan_capped_at_max_steps(self, user):
        run = self._run(user, max_steps=2)
        chat = [
            _plan(("a", None, None), ("b", None, None), ("c", None, None), ("d", None, None)),
            "ra",
            "rb",
            "final",
        ]
        with patch("apps.llm_analysis.services.chat", side_effect=chat):
            events = _events(run_plan(run, model=""))

        plan_event = next(e for e in events if e["event"] == "plan")
        assert len(plan_event["steps"]) == 2
        assert len([e for e in events if e["event"] == "step"]) == 2

    def test_unparseable_plan_finishes_error(self, user):
        run = self._run(user)
        with patch("apps.llm_analysis.services.chat", side_effect=["I cannot plan this"]):
            events = _events(run_plan(run, model=""))

        assert events[-1]["event"] == "error"
        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR

    def test_synthesis_sees_all_step_results(self, user):
        run = self._run(user)
        seen = []

        def fake_chat(messages, model=None):
            seen.append(messages)
            system = messages[0]["content"]
            if "planner" in system:
                return _plan(("a", None, None), ("b", None, None))
            if "senior financial analyst" in system:
                return "synthesised"
            return f"result-{len(seen)}"

        with patch("apps.llm_analysis.services.chat", side_effect=fake_chat):
            _events(run_plan(run, model=""))

        synth_user = seen[-1][1]["content"]
        assert "result-2" in synth_user  # step 0 result
        assert "result-3" in synth_user  # step 1 result

    def test_run_and_steps_persisted(self, user):
        run = self._run(user)
        chat = [_plan(("a", None, None), ("b", None, None)), "ra", "rb", "done"]
        with patch("apps.llm_analysis.services.chat", side_effect=chat):
            _events(run_plan(run, model=""))

        run.refresh_from_db()
        assert run.output == "done"
        assert run.meta["plan"] is not None and len(run.meta["plan"]) == 2
        orders = list(run.steps.values_list("order", flat=True))
        assert orders == [0, 1]
        assert run.steps.get(order=0).meta["result"] == "ra"

    def test_chat_error_finishes_run_error(self, user):
        run = self._run(user)
        with patch("apps.llm_analysis.services.chat", side_effect=OllamaServiceError("down")):
            events = _events(run_plan(run, model=""))

        assert events[-1]["event"] == "error"
        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR

    def test_executor_error_finishes_run(self, user):
        run = self._run(user)
        chat = [_plan(("a", None, None)), OllamaServiceError("exec down")]
        with patch("apps.llm_analysis.services.chat", side_effect=chat):
            events = _events(run_plan(run, model=""))

        assert events[-1]["event"] == "error"
        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR

    def test_synthesis_error_finishes_run(self, user):
        run = self._run(user)
        chat = [_plan(("a", None, None)), "ra", OllamaServiceError("synth down")]
        with patch("apps.llm_analysis.services.chat", side_effect=chat):
            events = _events(run_plan(run, model=""))

        assert events[-1]["event"] == "error"
        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR

    def test_empty_replan_keeps_the_original_plan(self, user):
        """A replan that yields NOTHING must leave the plan alone. Truncating it to the
        steps already done would end the run early and silently."""
        run = self._run(user, max_steps=4)
        chat_outputs = [
            _plan(("lookup", "company_snapshot", {"symbol": "NOPE"}), ("write it up", None, None)),
            "executed",
            _plan(),  # replan -> parses fine, but has no steps
            "executed",
            "final",
        ]
        with (
            patch("apps.llm_analysis.services.chat", side_effect=chat_outputs),
            patch("apps.llm_analysis.tools.run_tool", return_value='{"error": "no company"}'),
        ):
            events = _events(run_plan(run, model=""))

        assert not [e for e in events if e["event"] == "replan"]
        assert len([e for e in events if e["event"] == "step"]) == 2
        run.refresh_from_db()
        assert run.meta["replans"] == 0
        assert run.status == AgentRun.Status.DONE

    def test_step_reads_its_own_plan_entry_after_a_replan(self, user):
        """The step's position comes from the DRIVER (`spec.order`), not from how much
        state the strategy has accumulated - a replan rewrites the tail of the plan while
        the loop is mid-flight, so an inferred index is one bug away from off-by-one."""
        run = self._run(user, max_steps=4)
        chat_outputs = [
            _plan(
                ("lookup", "company_snapshot", {"symbol": "NOPE"}), ("original tail", None, None)
            ),
            "executed step 0",
            _plan(("revised tail", None, None)),  # replaces the tail after step 0
            "executed step 1",
            "final",
        ]
        with (
            patch("apps.llm_analysis.services.chat", side_effect=chat_outputs),
            patch("apps.llm_analysis.tools.run_tool", return_value='{"error": "no company"}'),
        ):
            events = _events(run_plan(run, model=""))

        steps = [e for e in events if e["event"] == "step"]
        assert [e["task"] for e in steps] == ["lookup", "revised tail"]
        assert [e["order"] for e in steps] == [0, 1]

    def test_parse_plan_never_returns_an_empty_list(self):
        """The contract that makes a falsy-tail guard in the replan path unnecessary -
        parse_plan RAISES on an empty or unusable plan in both of its exit paths, so the
        caller only ever has to handle ValueError. If this ever softens to returning [],
        the replan path would truncate the plan instead of keeping it."""
        from apps.llm_analysis.plan_execute import parse_plan

        for raw in ('{"plan": []}', "[]", '{"plan": [1, 2, 3]}', "not json", ""):
            with pytest.raises(ValueError):
                parse_plan(raw, 6)

    def test_replan_parse_failure_skips_replan(self, user):
        run = self._run(user)
        chat = [
            _plan(("fetch", "company_profile", {"symbol": "NOPE"})),
            "step result",  # execute step 0
            "garbage replan output",  # replan -> unparseable -> no replan
            "final",  # synthesis
        ]
        with (
            patch("apps.llm_analysis.services.chat", side_effect=chat),
            patch("apps.llm_analysis.tools.run_tool", return_value='{"error": "no company"}'),
        ):
            events = _events(run_plan(run, model=""))

        assert not [e for e in events if e["event"] == "replan"]
        assert events[-1]["event"] == "result"
        run.refresh_from_db()
        assert run.meta["replans"] == 0


# ---------------------------------------------------------------------------
# Integration: real tools driven through the loop (only the LLM is mocked)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPlanExecWithRealTools:
    """End-to-end loop with the actual ``run_tool`` (not mocked) against the DB, proving the
    planner-chosen tools are wired into the executor and yield real observations."""

    @pytest.fixture
    def tech_sector(self):
        from apps.companies.models import Company, CompanySnapshot, Sector

        sector = Sector.objects.create(name="Technology")
        aapl = Company.objects.create(symbol="AAPL", name="Apple", sector=sector)
        msft = Company.objects.create(symbol="MSFT", name="Microsoft", sector=sector)
        CompanySnapshot.objects.create(company=aapl, trailing_pe=30.0, market_cap=3000, raw={})
        CompanySnapshot.objects.create(company=msft, trailing_pe=20.0, market_cap=2000, raw={})
        return sector

    def test_real_tool_observation_flows_to_executor(self, user, tech_sector):
        run = create_plan_run(
            user=user,
            query="Is AAPL cheap vs its sector?",
            model="",
            max_steps=6,
            allow_replan=True,
        )
        seen = []

        def fake_chat(messages, model=None):
            seen.append(messages)
            system = messages[0]["content"]
            if "planner" in system:
                return _plan(
                    (
                        "Aggregate the Technology sector",
                        "sector_analysis",
                        {"sector": "Technology"},
                    ),
                    ("Write the verdict", None, None),
                )
            if "senior financial analyst" in system:
                return "## Verdict\nAAPL is above the sector median."
            return "step result"

        # tools.run_tool is NOT mocked - the real sector aggregation runs against the DB.
        with patch("apps.llm_analysis.services.chat", side_effect=fake_chat):
            events = _events(run_plan(run, model=""))

        tool_step = next(e for e in events if e["event"] == "step" and e["tool"])
        observation = json.loads(tool_step["observation"])
        assert tool_step["tool"] == "sector_analysis"
        assert observation["sector"] == "Technology"
        assert observation["companies"] == 2
        assert observation["metrics"]["trailing_pe"]["median"] == 25.0
        # That real observation was passed into the executor call for that step.
        execute_user = seen[1][1]["content"]
        assert '"median": 25.0' in execute_user
        # No divergence -> no replan; the run completed.
        assert not [e for e in events if e["event"] == "replan"]
        assert events[-1]["event"] == "result"

    def test_real_unknown_sector_triggers_replan(self, user, tech_sector):
        run = create_plan_run(
            user=user, query="Analyse the Banana sector", model="", max_steps=6, allow_replan=True
        )

        def fake_chat(messages, model=None):
            system = messages[0]["content"]
            if "REMAINING" in system:
                return _plan(("Reason about available sectors instead", None, None))
            if "planner" in system:
                return _plan(("Aggregate Banana", "sector_analysis", {"sector": "Banana"}))
            if "senior financial analyst" in system:
                return "No such sector exists."
            return "step result"

        with patch("apps.llm_analysis.services.chat", side_effect=fake_chat):
            events = _events(run_plan(run, model=""))

        # The real tool returned an {"error"} observation for the bogus sector...
        tool_step = next(e for e in events if e["event"] == "step" and e["tool"])
        assert "error" in json.loads(tool_step["observation"])
        # ...which the loop detected as divergence and replanned the remaining work.
        assert len([e for e in events if e["event"] == "replan"]) == 1
        run.refresh_from_db()
        assert run.meta["replans"] == 1
        assert events[-1]["event"] == "result"


# ---------------------------------------------------------------------------
# PlanExecuteView  POST /api/llm/plan/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPlanExecView:
    def test_plan_view_unauthenticated(self, api_client):
        response = api_client.post(PLAN_URL, {"query": "test"}, format="json")
        assert response.status_code == 401

    def test_plan_view_missing_query(self, auth_client):
        response = auth_client.post(PLAN_URL, {}, format="json")
        assert response.status_code == 400

    def test_plan_view_max_steps_out_of_range(self, auth_client):
        response = auth_client.post(PLAN_URL, {"query": "x", "max_steps": 99}, format="json")
        assert response.status_code == 400

    @pytest.mark.django_db(transaction=True)
    def test_plan_view_streams_sse(self, auth_client):
        chat = [_plan(("step", None, None)), "result", "## Done"]
        with patch("apps.llm_analysis.services.chat", side_effect=chat):
            response = auth_client.post(PLAN_URL, {"query": "test"}, format="json")
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
        assert "step" in kinds
        assert kinds[-1] == "result"


# ---------------------------------------------------------------------------
# History + detail
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPlanExecHistory:
    def test_plan_run_list_filtered_to_user(self, auth_client, user):
        from django.contrib.auth import get_user_model

        other = get_user_model().objects.create_user(email="pother@x.com", password="pass")
        create_plan_run(user=user, query="mine", model="", max_steps=6, allow_replan=True)
        create_plan_run(user=other, query="theirs", model="", max_steps=6, allow_replan=True)

        response = auth_client.get(PLAN_LIST_URL)
        assert response.status_code == 200
        queries = [r["query"] for r in response.data["results"]]
        assert "mine" in queries
        assert "theirs" not in queries

    def test_plan_run_detail_404_other_user(self, auth_client, user):
        from django.contrib.auth import get_user_model

        other = get_user_model().objects.create_user(email="pother2@x.com", password="pass")
        run = create_plan_run(user=other, query="theirs", model="", max_steps=6, allow_replan=True)

        response = auth_client.get(f"/api/llm/plan/{run.id}/")
        assert response.status_code == 404
