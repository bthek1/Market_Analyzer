import json
from unittest.mock import patch

import pytest

from apps.llm_analysis.chain import (
    CHAIN_STEPS,
    _classify,
    _format_report,
    _synthesise,
    run_chain,
)
from apps.llm_analysis.models import AgentRun
from apps.llm_analysis.services import create_chain_run

CHAIN_RUN_URL = "/api/llm/chain/run/"
CHAIN_LIST_URL = "/api/llm/chain/"


# ---------------------------------------------------------------------------
# Step handler model selection
# ---------------------------------------------------------------------------


class TestStepModelSelection:
    def test_classify_uses_classifier_model(self, llm_settings):
        llm_settings.classifier_model = "qwen3:1.7b"
        with patch("apps.llm_analysis.services.chat", return_value="{}") as mock_chat:
            _classify("Analyse AAPL", [], model="qwen3:70b")  # main override ignored
        assert mock_chat.call_args.kwargs["model"] == "qwen3:1.7b"

    def test_synthesise_uses_main_model_override(self):
        with patch("apps.llm_analysis.services.chat", return_value="out") as mock_chat:
            _synthesise("q", [], model="qwen3:70b")
        assert mock_chat.call_args.kwargs["model"] == "qwen3:70b"

    def test_format_report_uses_main_model_override(self):
        with patch("apps.llm_analysis.services.chat", return_value="out") as mock_chat:
            _format_report("q", [], model="qwen3:70b")
        assert mock_chat.call_args.kwargs["model"] == "qwen3:70b"


# ---------------------------------------------------------------------------
# create_chain_run
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCreateChainRun:
    def test_creates_run_and_steps(self, user):
        run = create_chain_run(user=user, query="Analyse AAPL", model="")
        assert AgentRun.objects.filter(kind="chain").filter(pk=run.pk).exists()
        assert run.status == "running"
        assert run.query == "Analyse AAPL"
        steps = list(run.steps.order_by("order"))
        assert len(steps) == len(CHAIN_STEPS)
        for i, (step, defn) in enumerate(zip(steps, CHAIN_STEPS)):
            assert step.key == defn.id
            assert step.label == defn.label
            assert step.order == i
            assert step.status == "pending"

    def test_atomic_rollback(self, user):
        with patch(
            "apps.llm_analysis.models.AgentStep.objects.bulk_create",
            side_effect=RuntimeError("db boom"),
        ):
            with pytest.raises(RuntimeError):
                create_chain_run(user=user, query="test", model="")
        assert AgentRun.objects.filter(kind="chain").count() == 0


# ---------------------------------------------------------------------------
# run_chain
# ---------------------------------------------------------------------------


def _mock_chat_side_effect(*args, **kwargs):
    return '{"intent": "analyse", "tickers": ["AAPL"], "time_horizon": "annual"}'


@pytest.mark.django_db
class TestRunChain:
    def _make_run(self, user):
        return create_chain_run(user=user, query="Analyse AAPL", model="")

    def test_happy_path_all_steps_done(self, user):
        run = self._make_run(user)
        with (
            patch("apps.llm_analysis.services.chat", return_value="ok"),
            patch(
                "apps.llm_analysis.chain._STEP_HANDLERS",
                {
                    "classify": lambda q, c, m: (
                        '{"intent":"analyse","tickers":[],"time_horizon":"annual"}'
                    ),
                    "research": lambda q, c, m: "[]",
                    "synthesise": lambda q, c, m: "ok",
                    "format": lambda q, c, m: "# Report",
                },
            ),
        ):
            events = list(run_chain(run, model=None))

        # first event is __init__
        first = json.loads(events[0][len("data: ") :].strip())
        assert first["step_id"] == "__init__"
        assert first["status"] == "running"
        assert first["run_id"] == str(run.id)

        # last event is __done__ done
        last = json.loads(events[-1][len("data: ") :].strip())
        assert last["step_id"] == "__done__"
        assert last["status"] == "done"

        run.refresh_from_db()
        assert run.status == "done"
        assert run.completed_at is not None

        for step in run.steps.all():
            assert step.status == "done"
            assert step.started_at is not None
            assert step.completed_at is not None

    def test_error_path_marks_run_and_step_error(self, user):
        run = self._make_run(user)
        with (
            patch("apps.llm_analysis.services.chat", side_effect=RuntimeError("LLM down")),
        ):
            events = list(run_chain(run, model=None))

        run.refresh_from_db()
        assert run.status == "error"

        last = json.loads(events[-1][len("data: ") :].strip())
        assert last["step_id"] == "__done__"
        assert last["status"] == "error"

        classify_step = run.steps.get(key="classify")
        assert classify_step.status == "error"
        assert "LLM down" in classify_step.error

    def test_events_carry_run_id(self, user):
        run = self._make_run(user)
        with (
            patch("apps.llm_analysis.services.chat", return_value="ok"),
            patch(
                "apps.llm_analysis.chain._STEP_HANDLERS",
                {
                    "classify": lambda q, c, m: (
                        '{"intent":"analyse","tickers":[],"time_horizon":"annual"}'
                    ),
                    "research": lambda q, c, m: "[]",
                    "synthesise": lambda q, c, m: "ok",
                    "format": lambda q, c, m: "# Report",
                },
            ),
        ):
            events = list(run_chain(run, model=None))

        for raw in events:
            payload = json.loads(raw[len("data: ") :].strip())
            assert payload["run_id"] == str(run.id)


# ---------------------------------------------------------------------------
# PromptChainView  POST /api/llm/chain/run/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPromptChainView:
    def test_unauthenticated_returns_401(self, api_client):
        response = api_client.post(CHAIN_RUN_URL, {"query": "test"}, format="json")
        assert response.status_code == 401

    def test_streams_sse_content_type(self, auth_client):
        with (
            patch("apps.llm_analysis.services.chat", return_value="ok"),
            patch(
                "apps.llm_analysis.chain._STEP_HANDLERS",
                {
                    "classify": lambda q, c, m: (
                        '{"intent":"analyse","tickers":[],"time_horizon":"annual"}'
                    ),
                    "research": lambda q, c, m: "[]",
                    "synthesise": lambda q, c, m: "ok",
                    "format": lambda q, c, m: "# Report",
                },
            ),
        ):
            response = auth_client.post(CHAIN_RUN_URL, {"query": "test"}, format="json")
        assert response.status_code == 200
        assert "text/event-stream" in response.get("Content-Type", "")

    def test_first_event_has_run_id(self, auth_client):
        with (
            patch("apps.llm_analysis.services.chat", return_value="ok"),
            patch(
                "apps.llm_analysis.chain._STEP_HANDLERS",
                {
                    "classify": lambda q, c, m: (
                        '{"intent":"analyse","tickers":[],"time_horizon":"annual"}'
                    ),
                    "research": lambda q, c, m: "[]",
                    "synthesise": lambda q, c, m: "ok",
                    "format": lambda q, c, m: "# Report",
                },
            ),
        ):
            response = auth_client.post(CHAIN_RUN_URL, {"query": "test"}, format="json")
        content = b"".join(response.streaming_content).decode()
        first_line = next(line for line in content.splitlines() if line.startswith("data:"))
        first_event = json.loads(first_line[len("data: ") :])
        assert "run_id" in first_event
        assert first_event["step_id"] == "__init__"

    def test_invalid_payload_returns_400(self, auth_client):
        response = auth_client.post(CHAIN_RUN_URL, {}, format="json")
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# ChainRunListView  GET /api/llm/chain/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestChainRunListView:
    def test_unauthenticated_returns_401(self, api_client):
        assert api_client.get(CHAIN_LIST_URL).status_code == 401

    def test_returns_only_own_runs(self, auth_client, user):
        from django.contrib.auth import get_user_model

        other = get_user_model().objects.create_user(email="other@x.com", password="pass")
        create_chain_run(user=user, query="mine", model="")
        create_chain_run(user=other, query="theirs", model="")

        response = auth_client.get(CHAIN_LIST_URL)
        assert response.status_code == 200
        results = response.data["results"]
        assert len(results) == 1
        assert results[0]["query"] == "mine"


# ---------------------------------------------------------------------------
# ChainRunDetailView  GET /api/llm/chain/<uuid>/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestChainRunDetailView:
    def test_returns_run_with_steps(self, auth_client, user):
        run = create_chain_run(user=user, query="detail test", model="")
        response = auth_client.get(f"/api/llm/chain/{run.pk}/")
        assert response.status_code == 200
        assert response.data["id"] == str(run.pk)
        assert len(response.data["steps"]) == len(CHAIN_STEPS)

    def test_other_user_returns_404(self, auth_client):
        from django.contrib.auth import get_user_model

        other = get_user_model().objects.create_user(email="other2@x.com", password="pass")
        run = create_chain_run(user=other, query="secret", model="")
        response = auth_client.get(f"/api/llm/chain/{run.pk}/")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# research_tickers - the chain/route side of snapshot_metrics (issue #11)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestResearchTickers:
    """`research_tickers` is patched out everywhere else, yet its output is JSON-dumped
    straight into the chain's and the router's synthesis prompts - the same LLM-facing path
    as the tools, so it must carry the same percent units."""

    @pytest.fixture
    def nvda(self, db):
        from apps.companies.models import Company, CompanySnapshot, Sector

        company = Company.objects.create(
            symbol="NVDA", name="NVIDIA", sector=Sector.objects.create(name="Technology")
        )
        CompanySnapshot.objects.create(
            company=company,
            trailing_pe=28.49,
            debt_to_equity=0.17,
            return_on_equity=1.17211,
            profit_margins=0.63663,
            dividend_yield=0.0044,
            raw={},
        )
        return company

    def test_found_company_carries_percent_fields(self, nvda):
        from apps.llm_analysis.chain import research_tickers

        (entry,) = research_tickers(["NVDA"])
        assert entry["found"] is True
        assert entry["sector"] == "Technology"
        snap = entry["snapshot"]
        assert snap["return_on_equity_pct"] == 117.21
        assert snap["profit_margins_pct"] == 63.66
        assert snap["dividend_yield_pct"] == 0.44
        assert snap["debt_to_equity"] == pytest.approx(0.17)

    def test_no_bare_fraction_names_reach_the_prompt(self, nvda):
        from apps.llm_analysis.chain import research_tickers
        from apps.llm_analysis.tools import PERCENT_FIELDS

        snap = research_tickers(["NVDA"])[0]["snapshot"]
        for field in PERCENT_FIELDS:
            assert field not in snap
            assert f"{field}_pct" in snap

    def test_matches_the_company_snapshot_tool(self, nvda):
        """One extraction, two LLM-facing callers - they must agree field for field."""
        from apps.llm_analysis.chain import research_tickers
        from apps.llm_analysis.tools import run_tool

        tool = json.loads(run_tool("company_snapshot", {"symbol": "NVDA"}))
        snap = research_tickers(["NVDA"])[0]["snapshot"]
        assert {k: tool[k] for k in snap} == snap

    def test_unknown_symbol_is_not_found(self, db):
        from apps.llm_analysis.chain import research_tickers

        assert research_tickers(["ZZZZ"]) == [{"symbol": "ZZZZ", "found": False}]

    def test_company_without_a_snapshot(self, db):
        from apps.companies.models import Company
        from apps.llm_analysis.chain import research_tickers

        Company.objects.create(symbol="BARE")
        entry = research_tickers(["bare"])[0]
        assert entry["found"] is True
        assert entry["snapshot"] is None
        assert entry["financials"] == []

    def test_caps_at_five_tickers(self, db):
        from apps.llm_analysis.chain import research_tickers

        assert len(research_tickers([f"T{i}" for i in range(8)])) == 5

    def test_research_step_feeds_percent_units_into_the_chain(self, nvda):
        """The step that JSON-dumps the research into the synthesis prompt."""
        from apps.llm_analysis.chain import StepResult, _research

        context = [StepResult("classify", json.dumps({"tickers": ["NVDA"]}))]
        out = json.loads(_research("is NVDA cheap?", context, model=None))
        assert out[0]["snapshot"]["profit_margins_pct"] == 63.66

    @pytest.mark.parametrize("classify_output", ["{}", "not json", '{"tickers": []}'])
    def test_research_step_without_tickers(self, db, classify_output):
        from apps.llm_analysis.chain import StepResult, _research

        out = json.loads(_research("hi", [StepResult("classify", classify_output)], model=None))
        assert out == {"message": "No tickers identified.", "companies": []}
