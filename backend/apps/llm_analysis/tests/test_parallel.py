import json
from unittest.mock import patch

import pytest

from apps.llm_analysis.models import AgentRun, AgentStep
from apps.llm_analysis.parallel import _parse_vote, run_parallel
from apps.llm_analysis.services import OllamaServiceError, create_parallel_run

PARALLEL_URL = "/api/llm/parallel/"
PARALLEL_LIST_URL = "/api/llm/parallel/history/"


def _events(generator):
    return [json.loads(e[len("data: ") :].strip()) for e in generator]


def _vote(verdict):
    return {"ok": json.dumps({"verdict": verdict, "reason": f"{verdict} reason"}), "error": None}


# ---------------------------------------------------------------------------
# _parse_vote (pure, no DB)
# ---------------------------------------------------------------------------


class TestParseVote:
    def test_parses_plain_json(self):
        verdict, reason = _parse_vote('{"verdict": "buy", "reason": "cheap"}')
        assert verdict == "buy"
        assert reason == "cheap"

    def test_strips_code_fences(self):
        raw = '```json\n{"verdict": "sell", "reason": "overvalued"}\n```'
        verdict, reason = _parse_vote(raw)
        assert verdict == "sell"
        assert reason == "overvalued"

    def test_uppercase_verdict_normalised(self):
        verdict, _ = _parse_vote('{"verdict": "BUY", "reason": "x"}')
        assert verdict == "buy"

    def test_unknown_verdict_defaults_hold(self):
        verdict, _ = _parse_vote('{"verdict": "maybe", "reason": "unsure"}')
        assert verdict == "hold"

    def test_unparseable_defaults_hold(self):
        verdict, reason = _parse_vote("not json at all")
        assert verdict == "hold"
        assert reason == "not json at all"


# ---------------------------------------------------------------------------
# Sectioning
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSectioning:
    def _run(self, user, query="analyse AAPL"):
        return create_parallel_run(user=user, query=query, model="", strategy="sectioning", n=3)

    def test_sectioning_fans_out_three_aspects(self, user):
        run = self._run(user)
        aspects = [{"ok": "body", "error": None}] * 3
        with (
            patch("apps.llm_analysis.services.chat_many", return_value=aspects),
            patch("apps.llm_analysis.services.chat", return_value="final"),
        ):
            events = _events(run_parallel(run, model=""))

        assert events[0]["event"] == "started"
        task_events = [e for e in events if e["event"] == "task"]
        assert len(task_events) == 3
        assert {e["task_id"] for e in task_events} == {"valuation", "profitability", "risk"}
        assert events[-1]["event"] == "result"
        assert events[-1]["output"] == "final"
        assert events[-1]["tally"] is None

    def test_sectioning_aggregates_sections(self, user):
        run = self._run(user)
        aspects = [
            {"ok": "VAL-BODY", "error": None},
            {"ok": "PROF-BODY", "error": None},
            {"ok": "RISK-BODY", "error": None},
        ]
        captured = {}

        def fake_chat(messages, model=None, think=False, temperature=None):
            captured["content"] = messages[0]["content"]
            return "final"

        with (
            patch("apps.llm_analysis.services.chat_many", return_value=aspects),
            patch("apps.llm_analysis.services.chat", side_effect=fake_chat),
        ):
            _events(run_parallel(run, model=""))

        for body in ("VAL-BODY", "PROF-BODY", "RISK-BODY"):
            assert body in captured["content"]

    def test_partial_failure_continues(self, user):
        run = self._run(user)
        aspects = [
            {"ok": "VAL-BODY", "error": None},
            {"ok": None, "error": "boom"},
            {"ok": "RISK-BODY", "error": None},
        ]
        with (
            patch("apps.llm_analysis.services.chat_many", return_value=aspects),
            patch("apps.llm_analysis.services.chat", return_value="final"),
        ):
            events = _events(run_parallel(run, model=""))

        task_events = {e["task_id"]: e for e in events if e["event"] == "task"}
        assert task_events["profitability"]["status"] == "error"
        assert task_events["valuation"]["status"] == "done"
        assert events[-1]["event"] == "result"

        failed = AgentStep.objects.get(run=run, key="profitability")
        assert failed.status == "error"
        assert failed.error == "boom"

    def test_all_failures_error(self, user):
        run = self._run(user)
        aspects = [{"ok": None, "error": "boom"}] * 3
        with (
            patch("apps.llm_analysis.services.chat_many", return_value=aspects),
            patch("apps.llm_analysis.services.chat", return_value="final"),
        ):
            events = _events(run_parallel(run, model=""))

        assert events[-1]["event"] == "error"
        run.refresh_from_db()
        assert run.status == "error"

    def test_aggregation_failure_errors(self, user):
        run = self._run(user)
        aspects = [{"ok": "body", "error": None}] * 3
        with (
            patch("apps.llm_analysis.services.chat_many", return_value=aspects),
            patch(
                "apps.llm_analysis.services.chat",
                side_effect=OllamaServiceError("aggregation down"),
            ),
        ):
            events = _events(run_parallel(run, model=""))

        # All aspects done, but the aggregation call failed -> error event.
        assert events[-1]["event"] == "error"
        assert "aggregation down" in events[-1]["error"]
        run.refresh_from_db()
        assert run.status == "error"


# ---------------------------------------------------------------------------
# Voting
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestVoting:
    def _run(self, user, query="should I buy AAPL", n=3):
        return create_parallel_run(user=user, query=query, model="", strategy="voting", n=n)

    def test_voting_passes_spread_temperatures(self, user):
        run = self._run(user)
        votes = [_vote("buy")] * 3
        with (
            patch("apps.llm_analysis.services.chat_many", return_value=votes) as mock_many,
            patch("apps.llm_analysis.services.chat", return_value="consensus"),
        ):
            _events(run_parallel(run, model=""))

        temps = mock_many.call_args.kwargs["temperatures"]
        assert temps == [0.3, 0.7, 1.0]

    def test_voting_tally_majority(self, user):
        run = self._run(user)
        votes = [_vote("buy"), _vote("buy"), _vote("hold")]
        with (
            patch("apps.llm_analysis.services.chat_many", return_value=votes),
            patch("apps.llm_analysis.services.chat", return_value="consensus"),
        ):
            events = _events(run_parallel(run, model=""))

        result = events[-1]
        assert result["event"] == "result"
        assert result["tally"] == {"buy": 2, "hold": 1, "sell": 0}
        run.refresh_from_db()
        assert run.meta["tally"] == {"buy": 2, "hold": 1, "sell": 0}

    def test_voting_tie_defaults_hold(self, user):
        run = self._run(user)
        votes = [_vote("buy"), _vote("sell")]
        captured = {}

        def fake_chat(messages, model=None, think=False, temperature=None):
            captured["content"] = messages[0]["content"]
            return "consensus"

        with (
            patch("apps.llm_analysis.services.chat_many", return_value=votes),
            patch("apps.llm_analysis.services.chat", side_effect=fake_chat),
        ):
            run = self._run(user, n=2)
            events = _events(run_parallel(run, model=""))

        assert events[-1]["tally"] == {"buy": 1, "hold": 0, "sell": 1}
        # Tie resolves to HOLD in the consensus prompt.
        assert "HOLD" in captured["content"]

    def test_voting_unparseable_vote_defaults_hold(self, user):
        run = self._run(user)
        votes = [
            {"ok": "not json at all", "error": None},
            _vote("buy"),
            _vote("buy"),
        ]
        with (
            patch("apps.llm_analysis.services.chat_many", return_value=votes),
            patch("apps.llm_analysis.services.chat", return_value="consensus"),
        ):
            events = _events(run_parallel(run, model=""))

        assert events[-1]["tally"] == {"buy": 2, "hold": 1, "sell": 0}

    def test_voting_task_events_carry_vote(self, user):
        run = self._run(user)
        votes = [_vote("buy"), _vote("hold"), _vote("sell")]
        with (
            patch("apps.llm_analysis.services.chat_many", return_value=votes),
            patch("apps.llm_analysis.services.chat", return_value="consensus"),
        ):
            events = _events(run_parallel(run, model=""))

        task_events = [e for e in events if e["event"] == "task"]
        assert {e["vote"] for e in task_events} == {"buy", "hold", "sell"}

    def test_voting_partial_failure_continues(self, user):
        run = self._run(user)
        votes = [_vote("buy"), {"ok": None, "error": "boom"}, _vote("buy")]
        with (
            patch("apps.llm_analysis.services.chat_many", return_value=votes),
            patch("apps.llm_analysis.services.chat", return_value="consensus"),
        ):
            events = _events(run_parallel(run, model=""))

        # Failed vote is excluded from the tally; survivors still aggregate.
        assert events[-1]["event"] == "result"
        assert events[-1]["tally"] == {"buy": 2, "hold": 0, "sell": 0}
        failed = AgentStep.objects.get(run=run, key="vote_1")
        assert failed.status == "error"
        assert failed.error == "boom"

    def test_voting_all_failures_error(self, user):
        run = self._run(user)
        votes = [{"ok": None, "error": "boom"}] * 3
        with (
            patch("apps.llm_analysis.services.chat_many", return_value=votes),
            patch("apps.llm_analysis.services.chat", return_value="consensus"),
        ):
            events = _events(run_parallel(run, model=""))

        assert events[-1]["event"] == "error"
        run.refresh_from_db()
        assert run.status == "error"

    def test_voting_aggregation_failure_persists_tally(self, user):
        run = self._run(user)
        votes = [_vote("buy"), _vote("buy"), _vote("sell")]
        with (
            patch("apps.llm_analysis.services.chat_many", return_value=votes),
            patch(
                "apps.llm_analysis.services.chat",
                side_effect=OllamaServiceError("consensus down"),
            ),
        ):
            events = _events(run_parallel(run, model=""))

        # Votes tallied, but the consensus write failed -> error, yet tally is persisted.
        assert events[-1]["event"] == "error"
        assert "consensus down" in events[-1]["error"]
        run.refresh_from_db()
        assert run.status == "error"
        assert run.meta["tally"] == {"buy": 2, "hold": 0, "sell": 1}


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPersistence:
    def test_parallel_run_persisted(self, user):
        run = create_parallel_run(user=user, query="vote", model="", strategy="voting", n=3)
        votes = [_vote("buy"), _vote("buy"), _vote("sell")]
        with (
            patch("apps.llm_analysis.services.chat_many", return_value=votes),
            patch("apps.llm_analysis.services.chat", return_value="consensus rationale"),
        ):
            _events(run_parallel(run, model=""))

        saved = AgentRun.objects.get(pk=run.pk)
        assert saved.meta["strategy"] == "voting"
        assert saved.status == "done"
        assert saved.output == "consensus rationale"
        assert saved.meta["tally"] == {"buy": 2, "hold": 0, "sell": 1}
        assert saved.steps.count() == 3
        assert all(t.meta.get("vote") for t in saved.steps.all())

    def test_create_parallel_run_seeds_sectioning_tasks(self, user):
        run = create_parallel_run(user=user, query="x", model="", strategy="sectioning", n=3)
        labels = list(run.steps.values_list("label", flat=True))
        assert labels == ["Valuation", "Profitability", "Risk"]


# ---------------------------------------------------------------------------
# ParallelView  POST /api/llm/parallel/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestParallelView:
    def test_parallel_view_unauthenticated(self, api_client):
        response = api_client.post(PARALLEL_URL, {"query": "test"}, format="json")
        assert response.status_code == 401

    def test_parallel_view_missing_query(self, auth_client):
        response = auth_client.post(PARALLEL_URL, {}, format="json")
        assert response.status_code == 400

    def test_parallel_view_invalid_strategy(self, auth_client):
        response = auth_client.post(
            PARALLEL_URL, {"query": "x", "strategy": "magic"}, format="json"
        )
        assert response.status_code == 400

    def test_parallel_view_n_out_of_range(self, auth_client):
        response = auth_client.post(
            PARALLEL_URL, {"query": "x", "strategy": "voting", "n": 9}, format="json"
        )
        assert response.status_code == 400

    @pytest.mark.django_db(transaction=True)
    def test_parallel_view_streams_sse(self, auth_client):
        aspects = [{"ok": "body", "error": None}] * 3
        with (
            patch("apps.llm_analysis.services.chat_many", return_value=aspects),
            patch("apps.llm_analysis.services.chat", return_value="final"),
        ):
            response = auth_client.post(PARALLEL_URL, {"query": "test"}, format="json")
            assert response.status_code == 200
            assert "text/event-stream" in response.get("Content-Type", "")
            content = b"".join(response.streaming_content).decode()

        first = json.loads(
            next(line for line in content.splitlines() if line.startswith("data:"))[len("data: ") :]
        )
        assert first["event"] == "started"


# ---------------------------------------------------------------------------
# History + detail
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestParallelHistory:
    def test_parallel_run_list_filtered_to_user(self, auth_client, user):
        from django.contrib.auth import get_user_model

        other = get_user_model().objects.create_user(email="pother@x.com", password="pass")
        create_parallel_run(user=user, query="mine", model="", strategy="sectioning", n=3)
        create_parallel_run(user=other, query="theirs", model="", strategy="sectioning", n=3)

        response = auth_client.get(PARALLEL_LIST_URL)
        assert response.status_code == 200
        results = response.data["results"]
        assert len(results) == 1
        assert results[0]["query"] == "mine"

    def test_parallel_run_detail_404_other_user(self, auth_client):
        from django.contrib.auth import get_user_model

        other = get_user_model().objects.create_user(email="pother2@x.com", password="pass")
        run = create_parallel_run(user=other, query="secret", model="", strategy="sectioning", n=3)
        response = auth_client.get(f"/api/llm/parallel/{run.pk}/")
        assert response.status_code == 404
