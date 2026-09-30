import json
from unittest.mock import patch

import pytest

from apps.llm_analysis.models import AgentRun, AgentStep
from apps.llm_analysis.react import parse_react_output, run_react
from apps.llm_analysis.services import OllamaServiceError, create_react_run

REACT_URL = "/api/llm/react/"
REACT_LIST_URL = "/api/llm/react/history/"


def _events(generator):
    return [json.loads(e[len("data: ") :].strip()) for e in generator]


def _action(tool, **args):
    return json.dumps({"thought": f"calling {tool}", "tool": tool, "args": args})


def _answer(text="final answer"):
    return json.dumps({"thought": "done", "answer": text})


# ---------------------------------------------------------------------------
# parse_react_output (pure)
# ---------------------------------------------------------------------------


class TestParse:
    def test_plain_action(self):
        out = parse_react_output('{"thought": "t", "tool": "company_profile", "args": {}}')
        assert out["tool"] == "company_profile"

    def test_strips_code_fences(self):
        out = parse_react_output('```json\n{"answer": "hi"}\n```')
        assert out["answer"] == "hi"

    def test_extracts_embedded_object(self):
        out = parse_react_output('Sure!\n{"answer": "x"}\nthanks')
        assert out["answer"] == "x"

    def test_raises_on_garbage(self):
        with pytest.raises(ValueError):
            parse_react_output("not json at all")

    def test_raises_on_non_object_json(self):
        # Valid JSON but not an object (e.g. a list) is unusable as a ReAct turn.
        with pytest.raises(ValueError):
            parse_react_output("[1, 2, 3]")


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReactLoop:
    def _run(self, user, query="Is AAPL cheap?", max_steps=6):
        return create_react_run(user=user, query=query, model="", max_steps=max_steps)

    def test_single_tool_then_answer(self, user):
        run = self._run(user)
        with (
            patch(
                "apps.llm_analysis.services.chat",
                side_effect=[_action("company_snapshot", symbol="AAPL"), _answer("cheap")],
            ),
            patch("apps.llm_analysis.tools.run_tool", return_value='{"trailing_pe": 31}'),
        ):
            events = _events(run_react(run, model=""))

        assert events[0]["event"] == "started"
        steps = [e for e in events if e["event"] == "step"]
        assert len(steps) == 2
        assert steps[0]["tool"] == "company_snapshot"
        assert steps[0]["is_answer"] is False
        assert steps[1]["is_answer"] is True
        assert events[-1]["event"] == "result"
        assert events[-1]["output"] == "cheap"

    def test_multi_tool_loop(self, user):
        run = self._run(user)
        with (
            patch(
                "apps.llm_analysis.services.chat",
                side_effect=[
                    _action("company_profile", symbol="AAPL"),
                    _action("company_snapshot", symbol="AAPL"),
                    _action("recent_price", symbol="AAPL"),
                    _answer(),
                ],
            ),
            patch("apps.llm_analysis.tools.run_tool", return_value="{}"),
        ):
            events = _events(run_react(run, model=""))

        tool_steps = [e for e in events if e["event"] == "step" and not e["is_answer"]]
        assert [s["tool"] for s in tool_steps] == [
            "company_profile",
            "company_snapshot",
            "recent_price",
        ]
        assert run.steps.count() == 4

    def test_observation_appended_to_scratchpad(self, user):
        run = self._run(user)
        seen_messages = []

        def fake_chat(messages, model=None):
            seen_messages.append([m["content"] for m in messages])
            if len(seen_messages) == 1:
                return _action("company_snapshot", symbol="AAPL")
            return _answer()

        with (
            patch("apps.llm_analysis.services.chat", side_effect=fake_chat),
            patch("apps.llm_analysis.tools.run_tool", return_value='{"pe": 31}'),
        ):
            _events(run_react(run, model=""))

        # Second LLM call must see the first observation in its scratchpad.
        assert any("Observation: " in c and '"pe": 31' in c for c in seen_messages[1])

    def test_unparseable_output_nudges_and_continues(self, user):
        run = self._run(user, max_steps=4)
        with (
            patch(
                "apps.llm_analysis.services.chat",
                side_effect=["I cannot comply", _answer("recovered")],
            ),
            patch("apps.llm_analysis.tools.run_tool", return_value="{}"),
        ):
            events = _events(run_react(run, model=""))

        assert events[-1]["event"] == "result"
        assert events[-1]["output"] == "recovered"
        error_steps = run.steps.filter(status=AgentStep.Status.ERROR)
        assert error_steps.count() == 1

    def test_unparseable_turn_streams_its_step(self, user):
        """Issue #7. The unparseable branch persisted a step but emitted no event, so the
        live run showed one card fewer than the same run does after a refresh-restore."""
        run = self._run(user, max_steps=4)
        with (
            patch(
                "apps.llm_analysis.services.chat",
                side_effect=["I cannot comply", _answer("recovered")],
            ),
            patch("apps.llm_analysis.tools.run_tool", return_value="{}"),
        ):
            events = _events(run_react(run, model=""))

        step_events = [e for e in events if e["event"] == "step"]
        assert len(step_events) == run.steps.count(), (
            "every persisted step must be streamed - the live view and a refresh-restore "
            "have to show the same list"
        )
        parse_error = next(e for e in step_events if e["status"] == "error")
        assert parse_error["error"] == "Could not parse model output as JSON."
        assert parse_error["observation"] == "I cannot comply"
        assert parse_error["is_answer"] is False
        assert parse_error["order"] == 0

    def test_every_persisted_step_is_streamed(self, user):
        """The invariant #7 broke, over a run that mixes all three step kinds:
        an unparseable turn, a tool call, and the final answer."""
        run = self._run(user, max_steps=4)
        with (
            patch(
                "apps.llm_analysis.services.chat",
                side_effect=[
                    "not json at all",
                    _action("company_snapshot", symbol="AAPL"),
                    _answer("done"),
                ],
            ),
            patch("apps.llm_analysis.tools.run_tool", return_value="{}"),
        ):
            events = _events(run_react(run, model=""))

        streamed = [e for e in events if e["event"] == "step"]
        assert [e["order"] for e in streamed] == list(
            run.steps.order_by("order").values_list("order", flat=True)
        )
        assert [e["status"] for e in streamed] == ["error", "done", "done"]

    def test_max_steps_forces_final_answer(self, user):
        run = self._run(user, max_steps=2)
        # Always returns an action -> never answers -> budget exhausted -> forced call.
        chat_outputs = [_action("company_snapshot", symbol="AAPL")] * 2 + [_answer("forced")]
        with (
            patch("apps.llm_analysis.services.chat", side_effect=chat_outputs),
            patch("apps.llm_analysis.tools.run_tool", return_value="{}"),
        ):
            events = _events(run_react(run, model=""))

        assert events[-1]["event"] == "result"
        assert events[-1]["output"] == "forced"
        run.refresh_from_db()
        assert run.status == AgentRun.Status.DONE

    def test_max_steps_forced_call_still_fails(self, user):
        run = self._run(user, max_steps=1)
        with (
            patch(
                "apps.llm_analysis.services.chat",
                side_effect=[_action("company_snapshot", symbol="AAPL"), "still not json"],
            ),
            patch("apps.llm_analysis.tools.run_tool", return_value="{}"),
        ):
            events = _events(run_react(run, model=""))

        assert events[-1]["event"] == "error"
        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR

    def test_tool_error_observation_is_recoverable(self, user):
        run = self._run(user)
        with (
            patch(
                "apps.llm_analysis.services.chat",
                side_effect=[_action("company_profile", symbol="NOPE"), _answer("ok")],
            ),
            patch(
                "apps.llm_analysis.tools.run_tool",
                return_value='{"error": "No company found for symbol \'NOPE\'."}',
            ),
        ):
            events = _events(run_react(run, model=""))

        assert events[-1]["event"] == "result"
        assert (
            run.steps.first().meta["observation"]
            == '{"error": "No company found for symbol \'NOPE\'."}'
        )

    def test_chat_error_finishes_run(self, user):
        run = self._run(user)
        with patch("apps.llm_analysis.services.chat", side_effect=OllamaServiceError("down")):
            events = _events(run_react(run, model=""))

        assert events[-1]["event"] == "error"
        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR

    def test_react_run_persisted(self, user):
        run = self._run(user)
        with (
            patch(
                "apps.llm_analysis.services.chat",
                side_effect=[_action("company_snapshot", symbol="AAPL"), _answer("done")],
            ),
            patch("apps.llm_analysis.tools.run_tool", return_value="{}"),
        ):
            _events(run_react(run, model=""))

        run.refresh_from_db()
        assert run.output == "done"
        orders = list(run.steps.values_list("order", flat=True))
        assert orders == [0, 1]
        assert run.steps.get(order=1).meta["is_answer"] is True


# ---------------------------------------------------------------------------
# Integration: real tools driven through the loop (only the LLM is mocked)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReactWithRealTools:
    """End-to-end loop with the actual ``run_tool`` (not mocked) against the DB, proving the
    sector/industry tools are wired into the agent and yield real observations."""

    @pytest.fixture
    def tech_sector(self):
        from apps.companies.models import Company, CompanySnapshot, Sector

        sector = Sector.objects.create(name="Technology")
        aapl = Company.objects.create(symbol="AAPL", name="Apple", sector=sector)
        msft = Company.objects.create(symbol="MSFT", name="Microsoft", sector=sector)
        CompanySnapshot.objects.create(company=aapl, trailing_pe=30.0, market_cap=3000, raw={})
        CompanySnapshot.objects.create(company=msft, trailing_pe=20.0, market_cap=2000, raw={})
        return sector

    def test_sector_analysis_observation_reaches_scratchpad(self, user, tech_sector):
        run = create_react_run(
            user=user, query="Is AAPL cheap vs its sector?", model="", max_steps=6
        )
        seen = []

        def fake_chat(messages, model=None):
            seen.append([m["content"] for m in messages])
            if len(seen) == 1:
                return _action("sector_analysis", sector="Technology")
            return _answer("AAPL P/E 30 is above the sector median 25 -> not cheap")

        with patch("apps.llm_analysis.services.chat", side_effect=fake_chat):
            events = _events(run_react(run, model=""))

        # The real tool ran: the first step's observation carries aggregated sector metrics.
        tool_step = next(e for e in events if e["event"] == "step" and not e["is_answer"])
        observation = json.loads(tool_step["observation"])
        assert tool_step["tool"] == "sector_analysis"
        assert observation["sector"] == "Technology"
        assert observation["companies"] == 2
        assert observation["metrics"]["trailing_pe"]["median"] == 25.0
        # And that observation was fed back into the second LLM call's scratchpad.
        assert any("Observation: " in c and '"median": 25.0' in c for c in seen[1])
        assert events[-1]["output"].startswith("AAPL")

    def test_unknown_sector_is_recoverable(self, user, tech_sector):
        run = create_react_run(user=user, query="Analyse the Banana sector", model="", max_steps=6)
        with patch(
            "apps.llm_analysis.services.chat",
            side_effect=[
                _action("sector_analysis", sector="Banana"),
                _answer("No such sector exists"),
            ],
        ):
            events = _events(run_react(run, model=""))

        tool_step = next(e for e in events if e["event"] == "step" and not e["is_answer"])
        assert "error" in json.loads(tool_step["observation"])
        assert events[-1]["event"] == "result"  # the loop recovered and answered

    def test_list_sectors_discovery_then_industry_analysis(self, user, tech_sector):
        from apps.companies.models import Company, CompanySnapshot, Industry

        software = Industry.objects.create(name="Software - Application", sector=tech_sector)
        crm = Company.objects.create(
            symbol="CRM", name="Salesforce", sector=tech_sector, industry=software
        )
        CompanySnapshot.objects.create(company=crm, trailing_pe=40.0, market_cap=500, raw={})

        run = create_react_run(
            user=user, query="Analyse the software industry", model="", max_steps=6
        )
        with patch(
            "apps.llm_analysis.services.chat",
            side_effect=[
                _action("list_sectors", sector="Technology"),
                _action("industry_analysis", industry="Software - Application"),
                _answer("Software industry median P/E is 40"),
            ],
        ):
            events = _events(run_react(run, model=""))

        tool_steps = [e for e in events if e["event"] == "step" and not e["is_answer"]]
        assert [s["tool"] for s in tool_steps] == ["list_sectors", "industry_analysis"]
        discovery = json.loads(tool_steps[0]["observation"])
        assert any(i["industry"] == "Software - Application" for i in discovery["industries"])
        industry = json.loads(tool_steps[1]["observation"])
        assert industry["companies"] == 1
        assert industry["metrics"]["trailing_pe"]["median"] == 40.0


# ---------------------------------------------------------------------------
# ReactView  POST /api/llm/react/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReactView:
    def test_react_view_unauthenticated(self, api_client):
        response = api_client.post(REACT_URL, {"query": "test"}, format="json")
        assert response.status_code == 401

    def test_react_view_missing_query(self, auth_client):
        response = auth_client.post(REACT_URL, {}, format="json")
        assert response.status_code == 400

    def test_react_view_max_steps_out_of_range(self, auth_client):
        response = auth_client.post(REACT_URL, {"query": "x", "max_steps": 99}, format="json")
        assert response.status_code == 400

    @pytest.mark.django_db(transaction=True)
    def test_react_view_streams_sse(self, auth_client):
        with (
            patch(
                "apps.llm_analysis.services.chat",
                side_effect=[_action("company_snapshot", symbol="AAPL"), _answer("hi")],
            ),
            patch("apps.llm_analysis.tools.run_tool", return_value="{}"),
        ):
            response = auth_client.post(REACT_URL, {"query": "test"}, format="json")
            assert response.status_code == 200
            assert "text/event-stream" in response.get("Content-Type", "")
            assert response["X-Accel-Buffering"] == "no"
            content = b"".join(response.streaming_content).decode()

        events = [
            json.loads(line[len("data: ") :])
            for line in content.splitlines()
            if line.startswith("data:")
        ]
        kinds = [e["event"] for e in events]
        # Full ReAct stream: started -> a tool step -> the answer step -> result.
        assert kinds[0] == "started"
        assert "step" in kinds
        assert kinds[-1] == "result"
        assert events[-1]["output"] == "hi"
        step_events = [e for e in events if e["event"] == "step"]
        assert step_events[0]["tool"] == "company_snapshot"
        assert step_events[-1]["is_answer"] is True


# ---------------------------------------------------------------------------
# History + detail
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReactHistory:
    def test_react_run_list_filtered_to_user(self, auth_client, user):
        from django.contrib.auth import get_user_model

        other = get_user_model().objects.create_user(email="rother@x.com", password="pass")
        create_react_run(user=user, query="mine", model="", max_steps=6)
        create_react_run(user=other, query="theirs", model="", max_steps=6)

        response = auth_client.get(REACT_LIST_URL)
        assert response.status_code == 200
        queries = [r["query"] for r in response.data["results"]]
        assert "mine" in queries
        assert "theirs" not in queries

    def test_react_run_detail_404_other_user(self, auth_client, user):
        from django.contrib.auth import get_user_model

        other = get_user_model().objects.create_user(email="rother2@x.com", password="pass")
        run = create_react_run(user=other, query="theirs", model="", max_steps=6)

        response = auth_client.get(f"/api/llm/react/{run.id}/")
        assert response.status_code == 404
