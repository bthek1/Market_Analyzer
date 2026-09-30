import json
from unittest.mock import patch

import pytest

from apps.llm_analysis.models import AgentRun
from apps.llm_analysis.router import (
    ROUTE_EXEMPLARS,
    _classify_route,
    _run_analysis,
    _run_comparison,
    resolve_route,
    run_route,
)
from apps.llm_analysis.services import create_route_run


def _embed_favoring(route_name):
    """Fake embed: query matches the given route's exemplars (cosine 1), others 0."""
    favored = set(ROUTE_EXEMPLARS[route_name])

    def fake_embed(texts, model=None):
        out = [[1.0, 0.0]]  # query vector
        out.extend([1.0, 0.0] if t in favored else [0.0, 1.0] for t in texts[1:])
        return out

    return fake_embed


# Routing reads the LLM config (route mode/threshold, classifier model) via
# get_llm_config(); the llm_settings fixture supplies an in-memory singleton.
pytestmark = pytest.mark.usefixtures("llm_settings")

ROUTE_URL = "/api/llm/route/"
ROUTE_LIST_URL = "/api/llm/route/history/"

CLASSIFY_HANDLERS = {
    "classify": lambda q, c, m: '{"intent":"analyse","tickers":[],"time_horizon":"annual"}',
    "research": lambda q, c, m: "[]",
    "synthesise": lambda q, c, m: "ok",
    "format": lambda q, c, m: "# Report",
}


def _events(generator):
    return [json.loads(e[len("data: ") :].strip()) for e in generator]


# ---------------------------------------------------------------------------
# _classify_route
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestClassifyRoute:
    def test_classify_route_simple(self):
        raw = (
            '{"route": "simple", "reason": "price check", "tickers": ["AAPL"], "complexity": "low"}'
        )
        with patch("apps.llm_analysis.services.chat", return_value=raw):
            result = _classify_route("What is AAPL price?")
        assert result["route"] == "simple"
        assert result["tickers"] == ["AAPL"]
        assert result["reason"] == "price check"

    def test_classify_route_analysis(self):
        raw = '{"route": "analysis", "reason": "margins", "tickers": ["MSFT"], "complexity": "medium"}'
        with patch("apps.llm_analysis.services.chat", return_value=raw):
            result = _classify_route("Compare MSFT margins")
        assert result["route"] == "analysis"

    def test_classify_route_deep_research(self):
        raw = (
            '{"route": "deep_research", "reason": "thesis", '
            '"tickers": ["aapl", "msft"], "complexity": "high"}'
        )
        with patch("apps.llm_analysis.services.chat", return_value=raw):
            result = _classify_route("Investment thesis for AAPL vs MSFT")
        assert result["route"] == "deep_research"
        assert result["tickers"] == ["AAPL", "MSFT"]

    def test_classify_route_strips_code_fences(self):
        raw = '```json\n{"route": "simple", "reason": "x", "tickers": [], "complexity": "low"}\n```'
        with patch("apps.llm_analysis.services.chat", return_value=raw):
            result = _classify_route("hi")
        assert result["route"] == "simple"

    def test_classify_route_invalid_json_raises(self):
        with patch("apps.llm_analysis.services.chat", return_value="not json at all"):
            with pytest.raises(ValueError, match="non-JSON"):
                _classify_route("hi")

    def test_classify_route_unknown_route_defaults_to_simple(self):
        raw = '{"route": "magic", "reason": "x", "tickers": [], "complexity": "low"}'
        with patch("apps.llm_analysis.services.chat", return_value=raw):
            result = _classify_route("hi")
        assert result["route"] == "simple"

    def test_classify_uses_classifier_model(self, llm_settings):
        llm_settings.classifier_model = "qwen3:1.7b"
        raw = '{"route": "simple", "reason": "x", "tickers": [], "complexity": "low"}'
        with patch("apps.llm_analysis.services.chat", return_value=raw) as mock_chat:
            _classify_route("hi")
        assert mock_chat.call_args.kwargs["model"] == "qwen3:1.7b"


# ---------------------------------------------------------------------------
# Sectioned analysis + comparison fan-out
# ---------------------------------------------------------------------------


class TestSectionedWorkflows:
    def test_analysis_fans_out_three_aspects(self):
        aspects = [{"ok": "x", "error": None}] * 3
        with (
            patch("apps.llm_analysis.services.chat_many", return_value=aspects) as mock_chat_many,
            patch("apps.llm_analysis.services.chat", return_value="final"),
        ):
            out = _run_analysis("q", None)
        assert out == "final"
        # Exactly 3 independent aspect prompts fanned out.
        assert len(mock_chat_many.call_args.args[0]) == 3

    def test_analysis_aggregation_receives_all_aspects(self):
        aspects = [
            {"ok": "VAL-BODY", "error": None},
            {"ok": "PROF-BODY", "error": None},
            {"ok": "RISK-BODY", "error": None},
        ]
        captured = {}

        def fake_chat(messages, model=None, think=False):
            captured["content"] = messages[0]["content"]
            return "final"

        with (
            patch("apps.llm_analysis.services.chat_many", return_value=aspects),
            patch("apps.llm_analysis.services.chat", side_effect=fake_chat),
        ):
            _run_analysis("q", None)
        for body in ("VAL-BODY", "PROF-BODY", "RISK-BODY"):
            assert body in captured["content"]

    def test_analysis_surfaces_failed_aspect_in_aggregation(self):
        aspects = [
            {"ok": "VAL-BODY", "error": None},
            {"ok": None, "error": "boom"},
            {"ok": "RISK-BODY", "error": None},
        ]
        captured = {}

        def fake_chat(messages, model=None, think=False):
            captured["content"] = messages[0]["content"]
            return "final"

        with (
            patch("apps.llm_analysis.services.chat_many", return_value=aspects),
            patch("apps.llm_analysis.services.chat", side_effect=fake_chat),
        ):
            _run_analysis("q", None)
        # Failed aspect is reported, not silently dropped.
        assert "boom" in captured["content"]
        assert "VAL-BODY" in captured["content"]
        assert "RISK-BODY" in captured["content"]

    def test_comparison_aggregation_receives_all_narrations(self):
        found = [
            {"symbol": "MSFT", "found": True},
            {"symbol": "GOOG", "found": True},
        ]
        narrations = [
            {"ok": "MSFT-NOTE", "error": None},
            {"ok": "GOOG-NOTE", "error": None},
        ]
        captured = {}

        def fake_chat(messages, model=None, think=False):
            captured["content"] = messages[0]["content"]
            return "final"

        with (
            patch("apps.llm_analysis.chain.research_tickers", return_value=found),
            patch("apps.llm_analysis.services.chat_many", return_value=narrations),
            patch("apps.llm_analysis.services.chat", side_effect=fake_chat),
        ):
            out = _run_comparison("q", ["MSFT", "GOOG"], None)
        assert out == "final"
        for body in ("MSFT-NOTE", "GOOG-NOTE"):
            assert body in captured["content"]

    def test_comparison_falls_back_to_analysis_under_two_found(self):
        found = [{"symbol": "MSFT", "found": True}]
        aspects = [{"ok": "x", "error": None}] * 3
        with (
            patch("apps.llm_analysis.chain.research_tickers", return_value=found),
            patch("apps.llm_analysis.services.chat_many", return_value=aspects) as mock_chat_many,
            patch("apps.llm_analysis.services.chat", return_value="final"),
        ):
            out = _run_comparison("q", ["MSFT"], None)
        assert out == "final"
        # Degraded to the 3-aspect analysis fan-out, not a comparison.
        assert len(mock_chat_many.call_args.args[0]) == 3


# ---------------------------------------------------------------------------
# resolve_route (semantic vs LLM)
# ---------------------------------------------------------------------------


class TestResolveRoute:
    def test_llm_mode_skips_embedding(self, llm_settings):
        llm_settings.route_mode = "llm"
        params = {"route": "simple", "reason": "x", "tickers": [], "complexity": "low"}
        with (
            patch("apps.llm_analysis.services.embed") as mock_embed,
            patch("apps.llm_analysis.router._classify_route", return_value=params),
        ):
            result = resolve_route("anything")
        mock_embed.assert_not_called()
        assert result["route_method"] == "llm"
        assert result["route_confidence"] is None

    def test_semantic_simple_routes_without_llm(self, llm_settings):
        llm_settings.route_mode = "semantic"
        llm_settings.route_threshold = 0.75
        with (
            patch("apps.llm_analysis.services.embed", side_effect=_embed_favoring("simple")),
            patch("apps.llm_analysis.router._classify_route") as mock_classify,
        ):
            result = resolve_route("what is the price of AAPL")
        assert result["route"] == "simple"
        assert result["route_method"] == "semantic"
        assert result["route_confidence"] == pytest.approx(1.0)
        mock_classify.assert_not_called()

    def test_semantic_low_confidence_falls_back_to_llm(self, llm_settings):
        llm_settings.route_mode = "semantic"
        llm_settings.route_threshold = 0.75
        params = {"route": "analysis", "reason": "x", "tickers": ["AAPL"], "complexity": "low"}

        def all_orthogonal(texts, model=None):
            return [[1.0, 0.0]] + [[0.0, 1.0]] * (len(texts) - 1)

        with (
            patch("apps.llm_analysis.services.embed", side_effect=all_orthogonal),
            patch("apps.llm_analysis.router._classify_route", return_value=params) as mock_classify,
        ):
            result = resolve_route("ambiguous query")
        assert result["route_method"] == "llm"
        assert result["route_confidence"] is None
        mock_classify.assert_called_once()

    def test_semantic_route_needing_params_extracts_tickers(self, llm_settings):
        llm_settings.route_mode = "semantic"
        llm_settings.route_threshold = 0.75
        params = {
            "route": "comparison",
            "reason": "x",
            "tickers": ["MSFT", "GOOG"],
            "complexity": "medium",
        }
        with (
            patch("apps.llm_analysis.services.embed", side_effect=_embed_favoring("comparison")),
            patch("apps.llm_analysis.router._classify_route", return_value=params) as mock_classify,
        ):
            result = resolve_route("compare them")
        assert result["route"] == "comparison"
        assert result["route_method"] == "semantic"
        assert result["tickers"] == ["MSFT", "GOOG"]
        mock_classify.assert_called_once()


# ---------------------------------------------------------------------------
# run_route
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRunRoute:
    def _run(self, user, query="test query"):
        return create_route_run(user=user, query=query, model="")

    def test_run_route_simple_yields_events(self, user):
        run = self._run(user)
        raw = '{"route": "simple", "reason": "price", "tickers": [], "complexity": "low"}'
        with patch("apps.llm_analysis.services.chat", side_effect=[raw, "Answer text"]):
            events = _events(run_route(run, model=""))

        assert events[0]["event"] == "classified"
        assert events[0]["route"] == "simple"
        assert events[-1]["event"] == "result"
        assert events[-1]["output"] == "Answer text"
        assert len(events) == 2

        run.refresh_from_db()
        assert run.meta["route"] == "simple"
        assert run.status == "done"
        assert run.output == "Answer text"
        assert run.parent is None
        # Default (llm) routing persists method=llm, no confidence.
        assert run.meta["route_method"] == "llm"
        assert run.meta.get("route_confidence") is None

    def test_run_route_semantic_persists_method_and_confidence(self, user, llm_settings):
        llm_settings.route_mode = "semantic"
        llm_settings.route_threshold = 0.75
        run = self._run(user, query="what is the price of AAPL")
        with (
            patch("apps.llm_analysis.services.embed", side_effect=_embed_favoring("simple")),
            patch("apps.llm_analysis.services.chat", return_value="Answer text"),
        ):
            events = _events(run_route(run, model=""))

        assert events[0]["route_method"] == "semantic"
        assert events[0]["route_confidence"] == pytest.approx(1.0)
        run.refresh_from_db()
        assert run.meta["route_method"] == "semantic"
        assert run.meta["route_confidence"] == pytest.approx(1.0)

    def test_run_route_analysis_yields_events(self, user):
        run = self._run(user)
        raw = '{"route": "analysis", "reason": "ratios", "tickers": [], "complexity": "medium"}'
        aspects = [{"ok": "x", "error": None}] * 3
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[raw, "Analysis text"]),
            patch("apps.llm_analysis.services.chat_many", return_value=aspects),
        ):
            events = _events(run_route(run, model=""))

        assert events[0]["event"] == "classified"
        assert events[0]["route"] == "analysis"
        assert events[-1]["event"] == "result"
        assert events[-1]["output"] == "Analysis text"
        assert len(events) == 2

        run.refresh_from_db()
        assert run.meta["route"] == "analysis"
        assert run.status == "done"

    def test_run_route_simple_dispatches_to_chat(self, user):
        run = self._run(user)
        raw = '{"route": "simple", "reason": "x", "tickers": [], "complexity": "low"}'
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[raw, "out"]),
            patch("apps.llm_analysis.services.analyse") as mock_analyse,
        ):
            list(run_route(run, model=""))
        mock_analyse.assert_not_called()

    def test_run_route_analysis_fans_out_aspects(self, user):
        run = self._run(user)
        raw = '{"route": "analysis", "reason": "ratios", "tickers": [], "complexity": "medium"}'
        aspects = [{"ok": "x", "error": None}] * 3
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[raw, "analysis out"]),
            patch("apps.llm_analysis.services.chat_many", return_value=aspects) as mock_chat_many,
        ):
            events = _events(run_route(run, model=""))
        # One fan-out of 3 aspect prompts, then a single aggregation chat call.
        mock_chat_many.assert_called_once()
        assert len(mock_chat_many.call_args.args[0]) == 3
        assert events[-1]["output"] == "analysis out"

    def test_run_route_comparison_fans_out_per_ticker(self, user):
        run = self._run(user, query="MSFT vs GOOG")
        raw = (
            '{"route": "comparison", "reason": "two tickers", '
            '"tickers": ["MSFT", "GOOG"], "complexity": "medium"}'
        )
        found = [
            {"symbol": "MSFT", "found": True},
            {"symbol": "GOOG", "found": True},
        ]
        narrations = [{"ok": "msft note", "error": None}, {"ok": "goog note", "error": None}]
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[raw, "comparison out"]),
            patch("apps.llm_analysis.chain.research_tickers", return_value=found),
            patch(
                "apps.llm_analysis.services.chat_many", return_value=narrations
            ) as mock_chat_many,
        ):
            events = _events(run_route(run, model=""))

        # Two found tickers -> two concurrent narration prompts.
        mock_chat_many.assert_called_once()
        assert len(mock_chat_many.call_args.args[0]) == 2
        assert events[0]["route"] == "comparison"
        assert events[-1]["output"] == "comparison out"

    def test_run_route_comparison_falls_back_when_under_two_found(self, user):
        run = self._run(user, query="MSFT vs UNKNOWN")
        raw = (
            '{"route": "comparison", "reason": "two tickers", '
            '"tickers": ["MSFT", "UNKNOWN"], "complexity": "medium"}'
        )
        found = [
            {"symbol": "MSFT", "found": True},
            {"symbol": "UNKNOWN", "found": False},
        ]
        aspects = [{"ok": "x", "error": None}] * 3
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[raw, "analysis out"]),
            patch("apps.llm_analysis.chain.research_tickers", return_value=found),
            patch("apps.llm_analysis.services.chat_many", return_value=aspects) as mock_chat_many,
        ):
            events = _events(run_route(run, model=""))

        # Falls back to the 3-aspect analysis fan-out, not a 2-ticker comparison.
        assert len(mock_chat_many.call_args.args[0]) == 3
        assert events[-1]["output"] == "analysis out"

    def test_run_route_deep_research_yields_chain_events(self, user):
        run = self._run(user)
        raw = (
            '{"route": "deep_research", "reason": "thesis", '
            '"tickers": ["AAPL"], "complexity": "high"}'
        )
        with (
            patch("apps.llm_analysis.services.chat", return_value=raw),
            patch("apps.llm_analysis.chain._STEP_HANDLERS", CLASSIFY_HANDLERS),
        ):
            events = _events(run_route(run, model=""))

        assert events[0]["event"] == "classified"
        assert events[0]["route"] == "deep_research"

        # chain step events are re-yielded verbatim (no "event" key, has step_id)
        chain_events = [e for e in events if "step_id" in e]
        assert any(e["step_id"] == "research" for e in chain_events)

        assert events[-1]["event"] == "result"
        assert events[-1]["output"] == "# Report"

        run.refresh_from_db()
        assert run.meta["route"] == "deep_research"
        assert run.status == "done"
        assert run.parent is not None
        assert AgentRun.objects.filter(pk=run.parent_id).exists()

    def test_run_route_classify_invalid_json_yields_error(self, user):
        run = self._run(user)
        with patch("apps.llm_analysis.services.chat", return_value="garbage"):
            events = _events(run_route(run, model=""))

        assert events[-1]["event"] == "error"
        run.refresh_from_db()
        assert run.status == "error"
        assert run.error

    def test_route_run_saved_to_db(self, user):
        run = self._run(user, query="save me")
        raw = '{"route": "simple", "reason": "x", "tickers": [], "complexity": "low"}'
        with patch("apps.llm_analysis.services.chat", side_effect=[raw, "out"]):
            list(run_route(run, model=""))

        saved = AgentRun.objects.get(pk=run.pk)
        assert saved.query == "save me"
        assert saved.meta["route"] == "simple"
        assert saved.meta["route_reason"] == "x"
        assert saved.status == "done"
        assert saved.completed_at is not None


# ---------------------------------------------------------------------------
# RouteView  POST /api/llm/route/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRouteView:
    def test_route_view_unauthenticated(self, api_client):
        response = api_client.post(ROUTE_URL, {"query": "test"}, format="json")
        assert response.status_code == 401

    def test_route_view_missing_query(self, auth_client):
        response = auth_client.post(ROUTE_URL, {}, format="json")
        assert response.status_code == 400

    @pytest.mark.django_db(transaction=True)
    def test_route_view_streams_sse(self, auth_client):
        raw = '{"route": "simple", "reason": "x", "tickers": [], "complexity": "low"}'
        with patch("apps.llm_analysis.services.chat", side_effect=[raw, "out"]):
            response = auth_client.post(ROUTE_URL, {"query": "test"}, format="json")
            assert response.status_code == 200
            assert "text/event-stream" in response.get("Content-Type", "")
            content = b"".join(response.streaming_content).decode()

        first = json.loads(
            next(line for line in content.splitlines() if line.startswith("data:"))[len("data: ") :]
        )
        assert first["event"] == "classified"


# ---------------------------------------------------------------------------
# RouteRunListView  GET /api/llm/route/history/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRouteRunListView:
    def test_unauthenticated_returns_401(self, api_client):
        assert api_client.get(ROUTE_LIST_URL).status_code == 401

    def test_route_run_list_filtered_to_user(self, auth_client, user):
        from django.contrib.auth import get_user_model

        other = get_user_model().objects.create_user(email="other@x.com", password="pass")
        create_route_run(user=user, query="mine", model="")
        create_route_run(user=other, query="theirs", model="")

        response = auth_client.get(ROUTE_LIST_URL)
        assert response.status_code == 200
        results = response.data["results"]
        assert len(results) == 1
        assert results[0]["query"] == "mine"


# ---------------------------------------------------------------------------
# RouteRunDetailView  GET /api/llm/route/<uuid>/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRouteRunDetailView:
    def test_returns_own_run(self, auth_client, user):
        run = create_route_run(user=user, query="detail", model="")
        response = auth_client.get(f"/api/llm/route/{run.pk}/")
        assert response.status_code == 200
        assert response.data["id"] == str(run.pk)

    def test_other_user_returns_404(self, auth_client):
        from django.contrib.auth import get_user_model

        other = get_user_model().objects.create_user(email="other2@x.com", password="pass")
        run = create_route_run(user=other, query="secret", model="")
        response = auth_client.get(f"/api/llm/route/{run.pk}/")
        assert response.status_code == 404
