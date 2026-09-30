import json
from unittest.mock import patch

import pytest

from apps.llm_analysis.models import AgentRun
from apps.llm_analysis.multiagent import (
    ROSTER,
    SubAgent,
    parse_route,
    parse_tool_plan,
    run_multiagent,
)
from apps.llm_analysis.services import OllamaServiceError, create_multiagent_run

MA_URL = "/api/llm/multiagent/"
MA_LIST_URL = "/api/llm/multiagent/history/"

RESEARCHER = next(a for a in ROSTER if a.id == "researcher")


def _events(generator):
    return [json.loads(e[len("data: ") :].strip()) for e in generator]


def _route(*agent_ids, reason="because"):
    return json.dumps({"agents": list(agent_ids), "reason": reason})


# ---------------------------------------------------------------------------
# parse_route (pure)
# ---------------------------------------------------------------------------


class TestParseRoute:
    def test_full_roster(self):
        agents, reason = parse_route(_route("researcher", "analyst", "writer", reason="r"))
        assert agents == ["researcher", "analyst", "writer"]
        assert reason == "r"

    def test_preserves_roster_order_not_input_order(self):
        agents, _ = parse_route(_route("writer", "researcher"))
        assert agents == ["researcher", "writer"]

    def test_writer_always_included(self):
        agents, _ = parse_route(_route("researcher"))
        assert agents == ["researcher", "writer"]

    def test_unknown_ids_dropped(self):
        agents, _ = parse_route(_route("hacker", "analyst"))
        assert agents == ["analyst", "writer"]

    def test_dedupes(self):
        agents, _ = parse_route(_route("analyst", "analyst", "writer"))
        assert agents == ["analyst", "writer"]

    def test_bare_list_tolerated(self):
        agents, _ = parse_route('["analyst", "writer"]')
        assert agents == ["analyst", "writer"]

    def test_unparseable_falls_back_to_full_roster(self):
        agents, _ = parse_route("I cannot decide")
        assert agents == ["researcher", "analyst", "writer"]

    def test_empty_agents_falls_back_to_full_roster(self):
        agents, _ = parse_route('{"agents": []}')
        assert agents == ["researcher", "analyst", "writer"]

    def test_malformed_bare_list_falls_back_to_full_roster(self):
        # Looks like a bare list (has [ and ]) but is not valid JSON -> full roster.
        agents, _ = parse_route("agents: [researcher, writer]")
        assert agents == ["researcher", "analyst", "writer"]


# ---------------------------------------------------------------------------
# parse_tool_plan (pure)
# ---------------------------------------------------------------------------


class TestParseToolPlan:
    def test_allowed_tools_kept(self):
        raw = json.dumps({"tools": [{"tool": "company_snapshot", "args": {"symbol": "AAPL"}}]})
        out = parse_tool_plan(raw, RESEARCHER, 4)
        assert out == [{"tool": "company_snapshot", "args": {"symbol": "AAPL"}}]

    def test_disallowed_tool_dropped(self):
        analyst = SubAgent(id="analyst", label="Analyst", system="x", tools=())
        raw = json.dumps({"tools": [{"tool": "company_snapshot", "args": {}}]})
        assert parse_tool_plan(raw, analyst, 4) == []

    def test_unknown_tool_dropped(self):
        raw = json.dumps({"tools": [{"tool": "rm_rf", "args": {}}]})
        assert parse_tool_plan(raw, RESEARCHER, 4) == []

    def test_capped_at_max_tools(self):
        raw = json.dumps(
            {"tools": [{"tool": "company_snapshot", "args": {"symbol": f"S{i}"}} for i in range(8)]}
        )
        assert len(parse_tool_plan(raw, RESEARCHER, 3)) == 3

    def test_missing_args_becomes_empty_dict(self):
        raw = json.dumps({"tools": [{"tool": "list_sectors"}]})
        assert parse_tool_plan(raw, RESEARCHER, 4) == [{"tool": "list_sectors", "args": {}}]

    def test_bare_list_tolerated(self):
        raw = '[{"tool": "recent_price", "args": {"symbol": "AAPL"}}]'
        assert parse_tool_plan(raw, RESEARCHER, 4) == [
            {"tool": "recent_price", "args": {"symbol": "AAPL"}}
        ]

    def test_malformed_bare_list_returns_empty(self):
        # Has [ and ] but is not valid JSON.
        assert parse_tool_plan("tools: [company_snapshot]", RESEARCHER, 4) == []

    def test_non_dict_entries_skipped(self):
        raw = json.dumps(
            {"tools": ["junk", {"tool": "company_snapshot", "args": {"symbol": "AAPL"}}]}
        )
        assert parse_tool_plan(raw, RESEARCHER, 4) == [
            {"tool": "company_snapshot", "args": {"symbol": "AAPL"}}
        ]

    def test_unparseable_returns_empty(self):
        assert parse_tool_plan("no tools needed", RESEARCHER, 4) == []


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMultiAgentLoop:
    def _run(self, user, query="Give me a full picture of AAPL", max_tools=4):
        return create_multiagent_run(user=user, query=query, model="", max_tools=max_tools)

    def test_routes_then_runs_full_pipeline(self, user):
        run = self._run(user)
        # route -> researcher tool-plan (empty) -> researcher write -> analyst -> writer -> synth
        chats = [
            _route("researcher", "analyst", "writer"),
            '{"tools": []}',
            "research out",
            "analysis out",
            "writer out",
            "## Final",
        ]
        with patch("apps.llm_analysis.services.chat", side_effect=chats):
            events = _events(run_multiagent(run, model=""))

        assert events[0]["event"] == "route"
        assert events[0]["agents"] == ["researcher", "analyst", "writer"]
        steps = [e for e in events if e["event"] == "step"]
        assert [s["agent_id"] for s in steps] == ["researcher", "analyst", "writer"]
        assert [s["order"] for s in steps] == [0, 1, 2]
        assert events[-1]["event"] == "result"
        assert events[-1]["output"] == "## Final"
        assert events[-1]["agents"] == 3

    def test_handoff_feeds_prior_output_forward(self, user):
        run = self._run(user)
        seen = []

        def fake_chat(messages, model=None):
            seen.append(messages)
            system = messages[0]["content"]
            user_text = messages[1]["content"]
            if "supervisor coordinating" in system:
                return _route("researcher", "analyst", "writer")
            if "RESEARCHER" in system and "Choose up to" in system:
                return '{"tools": []}'
            if "RESEARCHER" in system:
                return "RESEARCH_FINDINGS"
            if "ANALYST" in system:
                assert "RESEARCH_FINDINGS" in user_text
                return "ANALYSIS_RESULT"
            if "WRITER" in system:
                assert "ANALYSIS_RESULT" in user_text
                return "WRITER_DRAFT"
            return "final"

        with patch("apps.llm_analysis.services.chat", side_effect=fake_chat):
            _events(run_multiagent(run, model=""))

    def test_researcher_uses_only_allowlisted_tools(self, user):
        run = self._run(user)
        plan = json.dumps(
            {
                "tools": [
                    {"tool": "company_snapshot", "args": {"symbol": "AAPL"}},
                    {"tool": "definitely_not_a_tool", "args": {}},
                ]
            }
        )
        chats = [
            _route("researcher", "writer"),
            plan,
            "research out",
            "writer out",
            "## Final",
        ]
        with (
            patch("apps.llm_analysis.services.chat", side_effect=chats),
            patch(
                "apps.llm_analysis.tools.run_tool", return_value='{"trailing_pe": 30}'
            ) as run_tool,
        ):
            events = _events(run_multiagent(run, model=""))

        run_tool.assert_called_once_with("company_snapshot", {"symbol": "AAPL"})
        researcher = next(e for e in events if e.get("agent_id") == "researcher")
        assert len(researcher["tool_calls"]) == 1
        assert researcher["tool_calls"][0]["observation"] == '{"trailing_pe": 30}'

    def test_reasoning_agents_make_no_tool_calls(self, user):
        run = self._run(user)
        chats = [_route("analyst", "writer"), "analysis", "writer", "## Final"]
        with (
            patch("apps.llm_analysis.services.chat", side_effect=chats),
            patch("apps.llm_analysis.tools.run_tool") as run_tool,
        ):
            events = _events(run_multiagent(run, model=""))

        run_tool.assert_not_called()
        for e in events:
            if e["event"] == "step":
                assert e["tool_calls"] is None

    def test_supervisor_can_skip_an_agent(self, user):
        run = self._run(user)
        chats = [_route("writer"), "writer out", "## Final"]
        with patch("apps.llm_analysis.services.chat", side_effect=chats):
            events = _events(run_multiagent(run, model=""))

        steps = [e for e in events if e["event"] == "step"]
        assert [s["agent_id"] for s in steps] == ["writer"]
        assert events[-1]["event"] == "result"

    def test_writer_always_included(self, user):
        run = self._run(user)
        # route omits writer -> it is force-added
        chats = [_route("analyst"), "analysis", "writer out", "## Final"]
        with patch("apps.llm_analysis.services.chat", side_effect=chats):
            events = _events(run_multiagent(run, model=""))

        assert events[0]["agents"] == ["analyst", "writer"]

    def test_tool_calls_capped_at_max_tools(self, user):
        run = self._run(user, max_tools=2)
        plan = json.dumps(
            {"tools": [{"tool": "company_snapshot", "args": {"symbol": f"S{i}"}} for i in range(5)]}
        )
        chats = [_route("researcher", "writer"), plan, "research", "writer", "## Final"]
        with (
            patch("apps.llm_analysis.services.chat", side_effect=chats),
            patch("apps.llm_analysis.tools.run_tool", return_value="{}") as run_tool,
        ):
            events = _events(run_multiagent(run, model=""))

        assert run_tool.call_count == 2
        researcher = next(e for e in events if e.get("agent_id") == "researcher")
        assert len(researcher["tool_calls"]) == 2

    def test_one_stage_fails_pipeline_continues(self, user):
        run = self._run(user)
        # route -> analyst raises -> writer ok -> synth
        chats = [
            _route("analyst", "writer"),
            OllamaServiceError("analyst down"),
            "writer out",
            "## Final",
        ]
        with patch("apps.llm_analysis.services.chat", side_effect=chats):
            events = _events(run_multiagent(run, model=""))

        analyst = next(e for e in events if e.get("agent_id") == "analyst")
        assert analyst["status"] == "error"
        writer = next(e for e in events if e.get("agent_id") == "writer")
        assert writer["status"] == "done"
        assert events[-1]["event"] == "result"

    def test_researcher_tool_plan_error_marks_step_and_continues(self, user):
        run = self._run(user)
        # route -> researcher tool-plan call raises -> writer ok -> synth
        chats = [
            _route("researcher", "writer"),
            OllamaServiceError("plan down"),
            "writer out",
            "## Final",
        ]
        with (
            patch("apps.llm_analysis.services.chat", side_effect=chats),
            patch("apps.llm_analysis.tools.run_tool") as run_tool,
        ):
            events = _events(run_multiagent(run, model=""))

        run_tool.assert_not_called()  # we never got past the failed tool-plan call
        researcher = next(e for e in events if e.get("agent_id") == "researcher")
        assert researcher["status"] == "error"
        assert researcher["error"] == "plan down"
        writer = next(e for e in events if e.get("agent_id") == "writer")
        assert writer["status"] == "done"
        assert events[-1]["event"] == "result"

    def test_all_stages_fail_finishes_error(self, user):
        run = self._run(user)
        chats = [
            _route("analyst", "writer"),
            OllamaServiceError("a down"),
            OllamaServiceError("w down"),
        ]
        with patch("apps.llm_analysis.services.chat", side_effect=chats):
            events = _events(run_multiagent(run, model=""))

        assert events[-1]["event"] == "error"
        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR

    def test_unparseable_route_falls_back_to_full_roster(self, user):
        run = self._run(user)
        chats = [
            "I cannot decide the roster",
            '{"tools": []}',
            "research",
            "analysis",
            "writer",
            "## Final",
        ]
        with patch("apps.llm_analysis.services.chat", side_effect=chats):
            events = _events(run_multiagent(run, model=""))

        assert events[0]["agents"] == ["researcher", "analyst", "writer"]
        assert events[-1]["event"] == "result"

    def test_synthesis_sees_all_stage_outputs(self, user):
        run = self._run(user)
        seen = []

        def fake_chat(messages, model=None):
            seen.append(messages)
            system = messages[0]["content"]
            if "supervisor coordinating" in system:
                return _route("analyst", "writer")
            if "ANALYST" in system:
                return "ALPHA"
            if "WRITER" in system:
                return "BETA"
            return "synthesised"

        with patch("apps.llm_analysis.services.chat", side_effect=fake_chat):
            _events(run_multiagent(run, model=""))

        synth_user = seen[-1][1]["content"]
        assert "ALPHA" in synth_user
        assert "BETA" in synth_user

    def test_run_and_steps_persisted(self, user):
        run = self._run(user)
        plan = json.dumps({"tools": [{"tool": "recent_price", "args": {"symbol": "AAPL"}}]})
        chats = [
            _route("researcher", "analyst", "writer"),
            plan,
            "research",
            "analysis",
            "writer",
            "done",
        ]
        with (
            patch("apps.llm_analysis.services.chat", side_effect=chats),
            patch("apps.llm_analysis.tools.run_tool", return_value="{}"),
        ):
            _events(run_multiagent(run, model=""))

        run.refresh_from_db()
        assert run.output == "done"
        assert run.meta["agents"] == ["researcher", "analyst", "writer"]
        orders = list(run.steps.values_list("order", flat=True))
        assert orders == [0, 1, 2]
        researcher = run.steps.get(order=0)
        assert (
            researcher.meta["tool_calls"]
            and researcher.meta["tool_calls"][0]["tool"] == "recent_price"
        )
        assert run.steps.get(order=1).meta.get("tool_calls") is None

    def test_route_error_finishes_run_error(self, user):
        run = self._run(user)
        with patch("apps.llm_analysis.services.chat", side_effect=OllamaServiceError("down")):
            events = _events(run_multiagent(run, model=""))

        assert events[-1]["event"] == "error"
        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR

    def test_synthesis_error_finishes_run(self, user):
        run = self._run(user)
        chats = [_route("writer"), "writer out", OllamaServiceError("synth down")]
        with patch("apps.llm_analysis.services.chat", side_effect=chats):
            events = _events(run_multiagent(run, model=""))

        assert events[-1]["event"] == "error"
        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR


# ---------------------------------------------------------------------------
# Integration: real tools driven through the loop (only the LLM is mocked)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMultiAgentWithRealTools:
    @pytest.fixture
    def tech_sector(self):
        from apps.companies.models import Company, CompanySnapshot, Sector

        sector = Sector.objects.create(name="Technology")
        aapl = Company.objects.create(symbol="AAPL", name="Apple", sector=sector)
        msft = Company.objects.create(symbol="MSFT", name="Microsoft", sector=sector)
        CompanySnapshot.objects.create(company=aapl, trailing_pe=30.0, market_cap=3000, raw={})
        CompanySnapshot.objects.create(company=msft, trailing_pe=20.0, market_cap=2000, raw={})
        return sector

    def test_real_tool_observation_flows_down_pipeline(self, user, tech_sector):
        run = create_multiagent_run(
            user=user, query="Is AAPL cheap vs its sector?", model="", max_tools=4
        )
        seen = []

        def fake_chat(messages, model=None):
            seen.append(messages)
            system = messages[0]["content"]
            if "supervisor coordinating" in system:
                return _route("researcher", "analyst", "writer")
            if "Choose up to" in system:
                return json.dumps(
                    {"tools": [{"tool": "sector_analysis", "args": {"sector": "Technology"}}]}
                )
            return "stage output"

        # tools.run_tool is NOT mocked - the real sector aggregation runs against the DB.
        with patch("apps.llm_analysis.services.chat", side_effect=fake_chat):
            events = _events(run_multiagent(run, model=""))

        researcher = next(e for e in events if e.get("agent_id") == "researcher")
        observation = json.loads(researcher["tool_calls"][0]["observation"])
        assert observation["sector"] == "Technology"
        assert observation["companies"] == 2
        assert observation["metrics"]["trailing_pe"]["median"] == 25.0
        assert events[-1]["event"] == "result"


# ---------------------------------------------------------------------------
# MultiAgentView  POST /api/llm/multiagent/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMultiAgentView:
    def test_multiagent_view_unauthenticated(self, api_client):
        response = api_client.post(MA_URL, {"query": "test"}, format="json")
        assert response.status_code == 401

    def test_multiagent_view_missing_query(self, auth_client):
        response = auth_client.post(MA_URL, {}, format="json")
        assert response.status_code == 400

    def test_multiagent_view_max_tools_out_of_range(self, auth_client):
        response = auth_client.post(MA_URL, {"query": "x", "max_tools": 99}, format="json")
        assert response.status_code == 400

    @pytest.mark.django_db(transaction=True)
    def test_multiagent_view_streams_sse(self, auth_client):
        chats = [_route("writer"), "writer out", "## Done"]
        with patch("apps.llm_analysis.services.chat", side_effect=chats):
            response = auth_client.post(MA_URL, {"query": "test"}, format="json")
            assert response.status_code == 200
            assert "text/event-stream" in response.get("Content-Type", "")
            content = b"".join(response.streaming_content).decode()

        events = [
            json.loads(line[len("data: ") :])
            for line in content.splitlines()
            if line.startswith("data:")
        ]
        kinds = [e["event"] for e in events]
        assert kinds[0] == "route"
        assert "step" in kinds
        assert kinds[-1] == "result"


@pytest.mark.django_db
class TestMultiAgentStrategy:
    def test_next_stops_at_the_roster_end_independently_of_the_budget(self, user):
        """`budget` and the roster length are set in different places (`__init__` reads the
        run, `intro` reads the routing result), so `next` must not rely on them agreeing -
        an over-large budget would otherwise walk off the end of `agent_ids`."""
        from apps.llm_analysis.multiagent import MultiAgentStrategy

        run = create_multiagent_run(user=user, query="q", model="", max_tools=4)
        strategy = MultiAgentStrategy(run, "")
        strategy.agent_ids = ["researcher"]
        strategy.budget = 99  # deliberately out of step with the roster

        assert strategy.next(0) is not None
        assert strategy.next(1) is None


# ---------------------------------------------------------------------------
# History + detail
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMultiAgentHistory:
    def test_multiagent_run_list_filtered_to_user(self, auth_client, user):
        from django.contrib.auth import get_user_model

        other = get_user_model().objects.create_user(email="maother@x.com", password="pass")
        create_multiagent_run(user=user, query="mine", model="", max_tools=4)
        create_multiagent_run(user=other, query="theirs", model="", max_tools=4)

        response = auth_client.get(MA_LIST_URL)
        assert response.status_code == 200
        queries = [r["query"] for r in response.data["results"]]
        assert "mine" in queries
        assert "theirs" not in queries

    def test_multiagent_run_detail_404_other_user(self, auth_client, user):
        from django.contrib.auth import get_user_model

        other = get_user_model().objects.create_user(email="maother2@x.com", password="pass")
        run = create_multiagent_run(user=other, query="theirs", model="", max_tools=4)

        response = auth_client.get(f"/api/llm/multiagent/{run.id}/")
        assert response.status_code == 404


class TestResearcherAllowList:
    def test_the_researcher_may_call_every_registered_tool(self):
        """`_RESEARCHER_TOOLS` is a hand-written literal, and issue #13's `peer_comparison`
        had to be added to it by hand. Derived from the registry, so a new tool that is
        forgotten here fails rather than being silently unreachable by the Researcher."""
        from apps.llm_analysis.tools import TOOLS

        assert set(RESEARCHER.tools) == set(TOOLS)

    def test_the_researcher_catalogue_advertises_peer_comparison(self):
        from apps.llm_analysis.tools import tool_catalogue

        assert "peer_comparison(symbol, scope?)" in tool_catalogue(only=RESEARCHER.tools)
