import json
from unittest.mock import patch

import pytest

from apps.llm_analysis.autonomous import (
    parse_bootstrap,
    parse_controller,
    run_autonomous,
    run_subagent,
)
from apps.llm_analysis.models import AgentRun, AgentStep
from apps.llm_analysis.services import OllamaServiceError, create_autonomous_run

AUTO_URL = "/api/llm/autonomous/"
AUTO_LIST_URL = "/api/llm/autonomous/history/"


def _events(generator):
    return [json.loads(e[len("data: ") :].strip()) for e in generator]


def _bootstrap(goal="Analyse AAPL", backlog=("get profile", "get snapshot")):
    return json.dumps({"goal": goal, "backlog": list(backlog)})


def _controller(
    *,
    reflection="r",
    goal_complete=False,
    next_task="do the thing",
    backlog=None,
    action="reason",
    tool=None,
    args=None,
    subagent_goal="",
):
    return json.dumps(
        {
            "reflection": reflection,
            "goal_complete": goal_complete,
            "next_task": next_task,
            "backlog": list(backlog) if backlog is not None else ["do the thing"],
            "action": action,
            "tool": tool,
            "args": args,
            "subagent_goal": subagent_goal,
        }
    )


def chat_router(
    *, bootstrap, controllers, executes=None, synth="## Final", subagents=None, captured=None
):
    """Dispatch a mocked services.chat by the system prompt of each call.

    ``executes``/``subagents`` entries may be ``Exception`` instances to simulate failures.
    """
    controllers = list(controllers)
    executes = list(executes) if executes is not None else None
    subagents = list(subagents) if subagents is not None else None

    def fake(messages, model=None):
        system = messages[0]["content"]
        user = messages[1]["content"] if len(messages) > 1 else ""
        if "research agent" in system:
            return bootstrap
        if "controller of an autonomous agent" in system:
            return controllers.pop(0)
        if "focused sub-agent" in system:
            val = subagents.pop(0) if subagents else json.dumps({"answer": "sub findings"})
            if isinstance(val, Exception):
                raise val
            return val
        if "executing ONE self-assigned task" in system:
            if captured is not None:
                captured.setdefault("execute_user", []).append(user)
            if executes is not None:
                v = executes.pop(0)
                if isinstance(v, Exception):
                    raise v
                return v
            return "result"
        if "worked toward a goal" in system:
            if captured is not None:
                captured["synth_user"] = user
            return synth
        return "result"

    return fake


# ---------------------------------------------------------------------------
# parse_bootstrap (pure)
# ---------------------------------------------------------------------------


class TestParseBootstrap:
    def test_basic(self):
        goal, backlog = parse_bootstrap(_bootstrap("G", ["a", "b"]))
        assert goal == "G"
        assert backlog == ["a", "b"]

    def test_unparseable_falls_back_to_empty(self):
        assert parse_bootstrap("not json") == ("", [])

    def test_drops_blank_tasks(self):
        _goal, backlog = parse_bootstrap(json.dumps({"goal": "G", "backlog": ["a", "", "  "]}))
        assert backlog == ["a"]

    def test_non_list_backlog(self):
        _goal, backlog = parse_bootstrap(json.dumps({"goal": "G", "backlog": "nope"}))
        assert backlog == []


# ---------------------------------------------------------------------------
# parse_controller (pure)
# ---------------------------------------------------------------------------


class TestParseController:
    def test_basic_tool(self):
        d = parse_controller(
            _controller(action="tool", tool="company_profile", args={"symbol": "AAPL"})
        )
        assert d["action"] == "tool"
        assert d["tool"] == "company_profile"
        assert d["args"] == {"symbol": "AAPL"}

    def test_unknown_action_defaults_to_reason(self):
        assert parse_controller(_controller(action="explode"))["action"] == "reason"

    def test_tool_ignored_when_not_tool_action(self):
        d = parse_controller(_controller(action="reason", tool="company_profile"))
        assert d["tool"] is None

    def test_null_tool_normalised(self):
        d = parse_controller(_controller(action="tool", tool="null"))
        assert d["tool"] is None

    def test_next_task_falls_back_to_backlog_head(self):
        d = parse_controller(_controller(next_task="", backlog=["first", "second"]))
        assert d["next_task"] == "first"

    def test_unparseable_is_empty_reason(self):
        d = parse_controller("garbage")
        assert d["action"] == "reason"
        assert d["next_task"] == ""
        assert d["goal_complete"] is False

    def test_goal_complete_flag(self):
        assert parse_controller(_controller(goal_complete=True))["goal_complete"] is True


# ---------------------------------------------------------------------------
# run_subagent (bounded, non-recursive)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRunSubagent:
    def test_answers_immediately(self):
        answer = json.dumps({"thought": "t", "answer": "## Found"})
        with patch("apps.llm_analysis.services.chat", side_effect=[answer]):
            findings, steps = run_subagent("research AAPL", max_steps=3, model=None)
        assert findings == "## Found"
        assert steps == []

    def test_runs_a_tool_then_answers(self):
        tool_turn = json.dumps(
            {"thought": "look", "tool": "company_profile", "args": {"symbol": "AAPL"}}
        )
        answer = json.dumps({"answer": "done"})
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[tool_turn, answer]),
            patch("apps.llm_analysis.tools.run_tool", return_value='{"name": "Apple"}') as rt,
        ):
            findings, steps = run_subagent("research AAPL", max_steps=3, model=None)
        rt.assert_called_once_with("company_profile", {"symbol": "AAPL"})
        assert findings == "done"
        assert len(steps) == 1
        assert steps[0]["observation"] == '{"name": "Apple"}'

    def test_budget_exhausted_forces_final_answer(self):
        tool_turn = json.dumps({"tool": "company_profile", "args": {"symbol": "AAPL"}})
        forced = json.dumps({"answer": "forced"})
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[tool_turn, forced]),
            patch("apps.llm_analysis.tools.run_tool", return_value="{}"),
        ):
            findings, _steps = run_subagent("g", max_steps=1, model=None)
        assert findings == "forced"

    def test_service_error_swallowed(self):
        with patch("apps.llm_analysis.services.chat", side_effect=OllamaServiceError("down")):
            findings, _steps = run_subagent("g", max_steps=2, model=None)
        assert findings.startswith("(sub-agent failed")

    def test_unparseable_turn_is_nudged_and_retried(self):
        """The sub-agent is tolerant in the same way the top-level ReAct loop is: junk
        costs a step and a nudge, not the whole delegation."""
        answer = json.dumps({"answer": "recovered"})
        with patch(
            "apps.llm_analysis.services.chat", side_effect=["not json at all", answer]
        ) as chat:
            findings, steps = run_subagent("g", max_steps=3, model=None)

        assert findings == "recovered"
        assert steps == []
        # The nudge is appended to the SAME conversation, so the retry sees the bad turn.
        retry_messages = chat.call_args_list[1].args[0]
        assert retry_messages[-2]["content"] == "not json at all"
        assert "ONLY a JSON object" in retry_messages[-1]["content"]

    def test_forced_final_answer_that_also_fails_degrades_to_a_message(self):
        """Every path returns findings - a sub-agent never hands back None or raises into
        the controller loop."""
        tool_turn = json.dumps({"tool": "company_profile", "args": {"symbol": "AAPL"}})
        with (
            patch(
                "apps.llm_analysis.services.chat",
                side_effect=[tool_turn, OllamaServiceError("down")],
            ),
            patch("apps.llm_analysis.tools.run_tool", return_value="{}"),
        ):
            findings, steps = run_subagent("g", max_steps=1, model=None)

        assert findings == "(sub-agent produced no findings)"
        assert len(steps) == 1

    def test_forced_final_answer_that_is_unparseable_degrades_too(self):
        tool_turn = json.dumps({"tool": "company_profile", "args": {"symbol": "AAPL"}})
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[tool_turn, "still not json"]),
            patch("apps.llm_analysis.tools.run_tool", return_value="{}"),
        ):
            findings, _steps = run_subagent("g", max_steps=1, model=None)

        assert findings == "(sub-agent produced no findings)"


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAutonomousLoop:
    def _run(self, user, query="Analyse AAPL", max_cycles=8, max_subagents=3):
        return create_autonomous_run(
            user=user, query=query, model="", max_cycles=max_cycles, max_subagents=max_subagents
        )

    def test_happy_path_completes_and_synthesises(self, user):
        run = self._run(user)
        fake = chat_router(
            bootstrap=_bootstrap(),
            controllers=[
                _controller(action="reason", next_task="analyse"),
                _controller(goal_complete=True),
            ],
            executes=["analysis done"],
        )
        with patch("apps.llm_analysis.services.chat", side_effect=fake):
            events = _events(run_autonomous(run, model=""))

        assert events[0]["event"] == "goal"
        assert events[-1]["event"] == "result"
        assert events[-1]["output"] == "## Final"
        assert events[-1]["stop_reason"] == "complete"
        run.refresh_from_db()
        assert run.status == AgentRun.Status.DONE
        assert run.meta["stop_reason"] == "complete"

    def test_tool_action_runs_tool_and_feeds_observation(self, user):
        run = self._run(user)
        captured = {}
        fake = chat_router(
            bootstrap=_bootstrap(),
            controllers=[
                _controller(action="tool", tool="company_snapshot", args={"symbol": "AAPL"}),
                _controller(goal_complete=True),
            ],
            executes=["interpreted"],
            captured=captured,
        )
        with (
            patch("apps.llm_analysis.services.chat", side_effect=fake),
            patch("apps.llm_analysis.tools.run_tool", return_value='{"pe": 30}') as rt,
        ):
            events = _events(run_autonomous(run, model=""))

        rt.assert_called_once_with("company_snapshot", {"symbol": "AAPL"})
        cycle = next(e for e in events if e["event"] == "cycle")
        assert cycle["observation"] == '{"pe": 30}'
        assert '{"pe": 30}' in captured["execute_user"][0]

    def test_reasoning_cycle_makes_no_tool_call(self, user):
        run = self._run(user)
        fake = chat_router(
            bootstrap=_bootstrap(),
            controllers=[
                _controller(action="reason", next_task="think"),
                _controller(goal_complete=True),
            ],
            executes=["thought"],
        )
        with (
            patch("apps.llm_analysis.services.chat", side_effect=fake),
            patch("apps.llm_analysis.tools.run_tool") as rt,
        ):
            _events(run_autonomous(run, model=""))
        rt.assert_not_called()

    def test_subagent_spawned_when_budget_available(self, user):
        run = self._run(user, max_subagents=2)
        fake = chat_router(
            bootstrap=_bootstrap(),
            controllers=[
                _controller(action="subagent", subagent_goal="deep dive AAPL"),
                _controller(goal_complete=True),
            ],
            subagents=[json.dumps({"answer": "sub findings"})],
        )
        with patch("apps.llm_analysis.services.chat", side_effect=fake):
            events = _events(run_autonomous(run, model=""))

        cycle = next(e for e in events if e["event"] == "cycle")
        assert cycle["spawned"] is True
        assert cycle["action"] == "subagent"
        assert cycle["output"] == "sub findings"

    def test_subagent_over_budget_degrades_to_reason(self, user):
        run = self._run(user, max_subagents=0)
        fake = chat_router(
            bootstrap=_bootstrap(),
            controllers=[
                _controller(action="subagent", subagent_goal="x", next_task="fallback task"),
                _controller(goal_complete=True),
            ],
            executes=["reasoned result"],
        )
        with patch("apps.llm_analysis.services.chat", side_effect=fake):
            events = _events(run_autonomous(run, model=""))

        cycle = next(e for e in events if e["event"] == "cycle")
        assert cycle["spawned"] is False
        assert cycle["action"] == "reason"

    def test_budget_cap_forces_synthesis(self, user):
        run = self._run(user, max_cycles=2)
        # Controller never signals goal_complete -> loop hits the cycle cap.
        fake = chat_router(
            bootstrap=_bootstrap(),
            controllers=[
                _controller(action="reason", next_task="a"),
                _controller(action="reason", next_task="b"),
            ],
            executes=["ra", "rb"],
        )
        with patch("apps.llm_analysis.services.chat", side_effect=fake):
            events = _events(run_autonomous(run, model=""))

        assert events[-1]["event"] == "result"
        assert events[-1]["stop_reason"] == "budget"
        assert len([e for e in events if e["event"] == "cycle"]) == 2

    def test_no_progress_terminates_after_some_success(self, user):
        run = self._run(user, max_cycles=6)
        # cycle 0 succeeds; cycles 1 and 2 fail -> no_progress hits the default limit (2).
        fake = chat_router(
            bootstrap=_bootstrap(),
            controllers=[
                _controller(action="reason", next_task="a"),
                _controller(action="reason", next_task="b"),
                _controller(action="reason", next_task="c"),
            ],
            executes=["good", OllamaServiceError("boom"), OllamaServiceError("boom")],
        )
        with patch("apps.llm_analysis.services.chat", side_effect=fake):
            events = _events(run_autonomous(run, model=""))

        assert events[-1]["event"] == "result"
        assert events[-1]["stop_reason"] == "no_progress"
        run.refresh_from_db()
        assert run.status == AgentRun.Status.DONE

    def test_controller_failure_is_a_stall_not_a_failed_run(self, user):
        """A controller call that cannot be reached counts as no progress and feeds its
        error into the NEXT reflection - the loop keeps going rather than aborting."""
        run = self._run(user, max_cycles=2)
        controllers = [
            OllamaServiceError("controller down"),
            _controller(action="reason", next_task="recovered"),
        ]

        def fake(messages, model=None):
            system = messages[0]["content"]
            if "research agent" in system:
                return _bootstrap()
            if "controller of an autonomous agent" in system:
                v = controllers.pop(0)
                if isinstance(v, Exception):
                    raise v
                return v
            if "executing ONE self-assigned task" in system:
                return "did the thing"
            return "## Final"

        with patch("apps.llm_analysis.services.chat", side_effect=fake):
            events = _events(run_autonomous(run, model=""))

        cycles = [e for e in events if e["event"] == "cycle"]
        assert cycles[0]["status"] == "error"
        assert cycles[0]["error"] == "controller down"
        assert cycles[1]["status"] == "done"
        assert events[-1]["event"] == "result"
        run.refresh_from_db()
        assert run.status == AgentRun.Status.DONE

    def test_empty_task_with_nothing_to_do_is_a_stall(self, user):
        """A controller that assigns no task and picks no action has not moved the run
        forward; two in a row trip the no-progress detector.

        The backlog must be empty too: `parse_controller` falls back to the head of the
        backlog when `next_task` is blank, so a blank task alone is not a stall.
        """
        run = self._run(user, max_cycles=2)
        fake = chat_router(
            bootstrap=_bootstrap(),
            controllers=[
                _controller(action="reason", next_task="", backlog=[]),
                _controller(action="reason", next_task="", backlog=[]),
            ],
        )
        with patch("apps.llm_analysis.services.chat", side_effect=fake):
            events = _events(run_autonomous(run, model=""))

        cycles = [e for e in events if e["event"] == "cycle"]
        assert len(cycles) == 2
        assert all(c["status"] == "done" for c in cycles)
        # No usable results were ever produced, so the run ends as an error.
        assert events[-1]["event"] == "error"
        run.refresh_from_db()
        assert run.meta["stop_reason"] == "no_progress"

    def test_no_usable_results_finishes_error(self, user):
        run = self._run(user, max_cycles=2)
        fake = chat_router(
            bootstrap=_bootstrap(),
            controllers=[
                _controller(action="reason", next_task="a"),
                _controller(action="reason", next_task="b"),
            ],
            executes=[OllamaServiceError("boom"), OllamaServiceError("boom")],
        )
        with patch("apps.llm_analysis.services.chat", side_effect=fake):
            events = _events(run_autonomous(run, model=""))

        assert events[-1]["event"] == "error"
        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR

    def test_bootstrap_service_error_finishes_error(self, user):
        run = self._run(user)
        with patch("apps.llm_analysis.services.chat", side_effect=OllamaServiceError("down")):
            events = _events(run_autonomous(run, model=""))
        assert events[-1]["event"] == "error"
        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR

    def test_bootstrap_falls_back_to_query_goal(self, user):
        run = self._run(user, query="My raw goal")
        fake = chat_router(
            bootstrap="not json at all",
            controllers=[
                _controller(action="reason", next_task="a"),
                _controller(goal_complete=True),
            ],
            executes=["r"],
        )
        with patch("apps.llm_analysis.services.chat", side_effect=fake):
            events = _events(run_autonomous(run, model=""))
        assert events[0]["goal"] == "My raw goal"

    def test_synthesis_sees_working_memory(self, user):
        run = self._run(user)
        captured = {}
        fake = chat_router(
            bootstrap=_bootstrap(),
            controllers=[
                _controller(action="reason", next_task="analyse"),
                _controller(goal_complete=True),
            ],
            executes=["MEMORY_MARKER"],
            captured=captured,
        )
        with patch("apps.llm_analysis.services.chat", side_effect=fake):
            _events(run_autonomous(run, model=""))
        assert "MEMORY_MARKER" in captured["synth_user"]

    def test_run_and_cycles_persisted(self, user):
        run = self._run(user)
        fake = chat_router(
            bootstrap=_bootstrap(),
            controllers=[
                _controller(action="reason", next_task="analyse"),
                _controller(goal_complete=True),
            ],
            executes=["analysis"],
        )
        with patch("apps.llm_analysis.services.chat", side_effect=fake):
            _events(run_autonomous(run, model=""))

        run.refresh_from_db()
        assert run.meta["goal"] == "Analyse AAPL"
        cycles = list(AgentStep.objects.filter(run=run).order_by("order"))
        assert [c.order for c in cycles] == [0, 1]
        assert cycles[0].output == "analysis"
        assert cycles[1].meta["goal_complete"] is True


# ---------------------------------------------------------------------------
# Integration: real tools driven through the loop (only the LLM is mocked)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAutonomousWithRealTools:
    @pytest.fixture
    def tech_sector(self):
        from apps.companies.models import Company, CompanySnapshot, Sector

        sector = Sector.objects.create(name="Technology")
        aapl = Company.objects.create(symbol="AAPL", name="Apple", sector=sector)
        CompanySnapshot.objects.create(company=aapl, trailing_pe=30.0, market_cap=3000, raw={})
        return sector

    def test_real_tool_observation_flows_into_cycle(self, user, tech_sector):
        run = create_autonomous_run(
            user=user, query="Is AAPL cheap?", model="", max_cycles=4, max_subagents=1
        )
        captured = {}
        fake = chat_router(
            bootstrap=_bootstrap(),
            controllers=[
                _controller(action="tool", tool="sector_analysis", args={"sector": "Technology"}),
                _controller(goal_complete=True),
            ],
            executes=["interpreted"],
            captured=captured,
        )
        # tools.run_tool is NOT mocked - the real sector aggregation runs against the DB.
        with patch("apps.llm_analysis.services.chat", side_effect=fake):
            events = _events(run_autonomous(run, model=""))

        cycle = next(e for e in events if e["event"] == "cycle")
        observation = json.loads(cycle["observation"])
        assert observation["sector"] == "Technology"
        assert observation["companies"] == 1
        assert events[-1]["event"] == "result"


# ---------------------------------------------------------------------------
# AutonomousView  POST /api/llm/autonomous/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAutonomousView:
    def test_unauthenticated(self, api_client):
        response = api_client.post(AUTO_URL, {"query": "test"}, format="json")
        assert response.status_code == 401

    def test_missing_query(self, auth_client):
        response = auth_client.post(AUTO_URL, {}, format="json")
        assert response.status_code == 400

    def test_max_cycles_out_of_range(self, auth_client):
        response = auth_client.post(AUTO_URL, {"query": "x", "max_cycles": 99}, format="json")
        assert response.status_code == 400

    @pytest.mark.django_db(transaction=True)
    def test_streams_sse(self, auth_client):
        fake = chat_router(
            bootstrap=_bootstrap(),
            controllers=[
                _controller(action="reason", next_task="a"),
                _controller(goal_complete=True),
            ],
            executes=["r"],
        )
        with patch("apps.llm_analysis.services.chat", side_effect=fake):
            response = auth_client.post(AUTO_URL, {"query": "test"}, format="json")
            assert response.status_code == 200
            assert "text/event-stream" in response.get("Content-Type", "")
            content = b"".join(response.streaming_content).decode()

        events = [
            json.loads(line[len("data: ") :])
            for line in content.splitlines()
            if line.startswith("data:")
        ]
        kinds = [e["event"] for e in events]
        assert kinds[0] == "goal"
        assert "cycle" in kinds
        assert kinds[-1] == "result"


# ---------------------------------------------------------------------------
# History + detail
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAutonomousHistory:
    def test_run_list_filtered_to_user(self, auth_client, user):
        from django.contrib.auth import get_user_model

        other = get_user_model().objects.create_user(email="autoother@x.com", password="pass")
        create_autonomous_run(user=user, query="mine", model="", max_cycles=8, max_subagents=3)
        create_autonomous_run(user=other, query="theirs", model="", max_cycles=8, max_subagents=3)

        response = auth_client.get(AUTO_LIST_URL)
        assert response.status_code == 200
        queries = [r["query"] for r in response.data["results"]]
        assert "mine" in queries
        assert "theirs" not in queries

    def test_run_detail_404_other_user(self, auth_client, user):
        from django.contrib.auth import get_user_model

        other = get_user_model().objects.create_user(email="autoother2@x.com", password="pass")
        run = create_autonomous_run(
            user=other, query="theirs", model="", max_cycles=8, max_subagents=3
        )

        response = auth_client.get(f"/api/llm/autonomous/{run.id}/")
        assert response.status_code == 404
