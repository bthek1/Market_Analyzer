import json
from unittest.mock import patch

import pytest

from apps.llm_analysis.eval_opt import run_eval_opt
from apps.llm_analysis.models import AgentRun, AgentStep
from apps.llm_analysis.services import OllamaServiceError, create_eo_run

EVAL_URL = "/api/llm/evaluate/"
EVAL_LIST_URL = "/api/llm/evaluate/history/"


def _events(generator):
    return [json.loads(e[len("data: ") :].strip()) for e in generator]


def _verdict(score, feedback="", passed=False):
    return json.dumps({"score": score, "feedback": feedback, "pass": passed})


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEvalOptLoop:
    def _run(self, user, query="Is AAPL cheap?", max_iterations=3, threshold=8):
        return create_eo_run(
            user=user, query=query, model="", max_iterations=max_iterations, threshold=threshold
        )

    def test_passes_first_eval_no_revision(self, user):
        run = self._run(user)
        with patch(
            "apps.llm_analysis.services.chat",
            side_effect=["draft1", _verdict(9, "great")],
        ) as chat:
            events = _events(run_eval_opt(run, model=""))

        assert events[0]["event"] == "started"
        assert events[1]["event"] == "draft"
        iters = [e for e in events if e["event"] == "iteration"]
        assert len(iters) == 1
        assert events[-1]["event"] == "result"
        assert events[-1]["output"] == "draft1"
        assert events[-1]["best_score"] == 9
        # generate + 1 evaluate only - no revise call.
        assert chat.call_count == 2

    def test_revises_until_threshold(self, user):
        run = self._run(user)
        with patch(
            "apps.llm_analysis.services.chat",
            side_effect=["draft1", _verdict(5, "add FCF"), "draft2", _verdict(9)],
        ) as chat:
            events = _events(run_eval_opt(run, model=""))

        iters = [e for e in events if e["event"] == "iteration"]
        assert len(iters) == 2
        assert events[-1]["output"] == "draft2"
        assert events[-1]["best_score"] == 9
        # generate + evaluate + revise + evaluate.
        assert chat.call_count == 4

    def test_exhausts_budget_returns_best(self, user):
        run = self._run(user, max_iterations=2, threshold=10)
        with patch(
            "apps.llm_analysis.services.chat",
            side_effect=["draft1", _verdict(4), "draft2", _verdict(6)],
        ):
            events = _events(run_eval_opt(run, model=""))

        iters = [e for e in events if e["event"] == "iteration"]
        assert len(iters) == 2
        assert events[-1]["output"] == "draft2"
        assert events[-1]["best_score"] == 6
        run.refresh_from_db()
        assert run.status == AgentRun.Status.DONE

    def test_best_draft_not_necessarily_last(self, user):
        run = self._run(user, max_iterations=3, threshold=10)
        with patch(
            "apps.llm_analysis.services.chat",
            side_effect=["d1", _verdict(7), "d2", _verdict(9), "d3", _verdict(6)],
        ):
            events = _events(run_eval_opt(run, model=""))

        # Highest score was the middle draft (d2, score 9), not the final one (d3, score 6).
        assert events[-1]["output"] == "d2"
        assert events[-1]["best_score"] == 9

    def test_pass_flag_short_circuits(self, user):
        run = self._run(user, threshold=8)
        with patch(
            "apps.llm_analysis.services.chat",
            side_effect=["d1", _verdict(5, passed=True)],
        ) as chat:
            events = _events(run_eval_opt(run, model=""))

        iters = [e for e in events if e["event"] == "iteration"]
        assert len(iters) == 1
        assert iters[0]["passed"] is True
        assert chat.call_count == 2  # no revision

    def test_unparseable_eval_is_recoverable(self, user):
        run = self._run(user, max_iterations=2)
        with patch(
            "apps.llm_analysis.services.chat",
            side_effect=["d1", "not json at all", "d2", _verdict(9)],
        ):
            events = _events(run_eval_opt(run, model=""))

        assert events[-1]["event"] == "result"
        assert events[-1]["output"] == "d2"
        error_iters = run.steps.filter(status=AgentStep.Status.ERROR)
        assert error_iters.count() == 1
        assert error_iters.first().meta["score"] == 0

    def test_feedback_fed_into_revision(self, user):
        run = self._run(user, max_iterations=2)
        seen = []

        def fake_chat(messages, model=None):
            seen.append(messages[-1]["content"])
            if len(seen) == 1:
                return "draft1"
            if len(seen) == 2:
                return _verdict(4, "ADD FREE CASH FLOW")
            if len(seen) == 3:
                return "draft2"
            return _verdict(9)

        with patch("apps.llm_analysis.services.chat", side_effect=fake_chat):
            _events(run_eval_opt(run, model=""))

        # The 3rd call is the revise turn - it must carry the feedback and the prior draft.
        revise_prompt = seen[2]
        assert "ADD FREE CASH FLOW" in revise_prompt
        assert "draft1" in revise_prompt

    def test_run_and_iterations_persisted(self, user):
        run = self._run(user)
        with patch(
            "apps.llm_analysis.services.chat",
            side_effect=["draft1", _verdict(6), "draft2", _verdict(9)],
        ):
            _events(run_eval_opt(run, model=""))

        run.refresh_from_db()
        assert run.output == "draft2"
        assert run.meta["best_score"] == 9
        orders = list(run.steps.values_list("order", flat=True))
        assert orders == [0, 1]
        assert run.steps.get(order=0).meta["draft"] == "draft1"
        assert run.steps.get(order=1).meta["passed"] is True

    def test_generate_error_finishes_run_error(self, user):
        run = self._run(user)
        with patch("apps.llm_analysis.services.chat", side_effect=OllamaServiceError("down")):
            events = _events(run_eval_opt(run, model=""))

        assert events[-1]["event"] == "error"
        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR

    def test_evaluate_error_finishes_run_error(self, user):
        run = self._run(user)
        with patch(
            "apps.llm_analysis.services.chat",
            side_effect=["draft1", OllamaServiceError("down")],
        ):
            events = _events(run_eval_opt(run, model=""))

        assert events[-1]["event"] == "error"
        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR

    def test_revise_error_keeps_best_draft(self, user):
        run = self._run(user, max_iterations=2, threshold=10)
        with patch(
            "apps.llm_analysis.services.chat",
            side_effect=["draft1", _verdict(5), OllamaServiceError("down")],
        ):
            events = _events(run_eval_opt(run, model=""))

        assert events[-1]["event"] == "error"
        run.refresh_from_db()
        assert run.status == AgentRun.Status.ERROR
        # The best draft seen so far is still recorded.
        assert run.output == "draft1"
        assert run.meta["best_score"] == 5


# ---------------------------------------------------------------------------
# EvaluatorOptimizerView  POST /api/llm/evaluate/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEvalOptView:
    def test_evaluate_view_unauthenticated(self, api_client):
        response = api_client.post(EVAL_URL, {"query": "test"}, format="json")
        assert response.status_code == 401

    def test_evaluate_view_missing_query(self, auth_client):
        response = auth_client.post(EVAL_URL, {}, format="json")
        assert response.status_code == 400

    def test_evaluate_view_threshold_out_of_range(self, auth_client):
        response = auth_client.post(EVAL_URL, {"query": "x", "threshold": 99}, format="json")
        assert response.status_code == 400

    def test_evaluate_view_max_iterations_out_of_range(self, auth_client):
        response = auth_client.post(EVAL_URL, {"query": "x", "max_iterations": 99}, format="json")
        assert response.status_code == 400

    @pytest.mark.django_db(transaction=True)
    def test_evaluate_view_streams_sse(self, auth_client):
        with patch(
            "apps.llm_analysis.services.chat",
            side_effect=["draft1", _verdict(9, "good")],
        ):
            response = auth_client.post(EVAL_URL, {"query": "test"}, format="json")
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
        assert "draft" in kinds
        assert "iteration" in kinds
        assert kinds[-1] == "result"
        assert events[-1]["output"] == "draft1"


# ---------------------------------------------------------------------------
# History + detail
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEvalOptHistory:
    def test_eo_run_list_filtered_to_user(self, auth_client, user):
        from django.contrib.auth import get_user_model

        other = get_user_model().objects.create_user(email="eother@x.com", password="pass")
        create_eo_run(user=user, query="mine", model="", max_iterations=3, threshold=8)
        create_eo_run(user=other, query="theirs", model="", max_iterations=3, threshold=8)

        response = auth_client.get(EVAL_LIST_URL)
        assert response.status_code == 200
        queries = [r["query"] for r in response.data["results"]]
        assert "mine" in queries
        assert "theirs" not in queries

    def test_eo_run_detail_404_other_user(self, auth_client, user):
        from django.contrib.auth import get_user_model

        other = get_user_model().objects.create_user(email="eother2@x.com", password="pass")
        run = create_eo_run(user=other, query="theirs", model="", max_iterations=3, threshold=8)

        response = auth_client.get(f"/api/llm/evaluate/{run.id}/")
        assert response.status_code == 404
