from io import StringIO
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.llm_analysis.management.commands.run_llm_live import (
    EXAMPLE_QUERIES,
    _get_or_create_system_user,
)
from apps.llm_analysis.models import (
    AgentRun,
)
from apps.llm_analysis.services import OllamaServiceError

# Step handlers that keep the real run_chain happy without touching Ollama.
FAKE_STEP_HANDLERS = {
    "classify": lambda q, c, m: '{"intent":"analyse","tickers":[],"time_horizon":"annual"}',
    "research": lambda q, c, m: "[]",
    "synthesise": lambda q, c, m: "Synthesised analysis.",
    "format": lambda q, c, m: "## Summary\nLooks solid.",
}


def _run(*args):
    out = StringIO()
    call_command("run_llm_live", *args, stdout=out, stderr=StringIO())
    return out.getvalue()


def _classification(route: str, tickers: list[str] | None = None, complexity: str = "low") -> str:
    import json as _json

    return _json.dumps(
        {
            "route": route,
            "reason": f"{route} query",
            "tickers": tickers or [],
            "complexity": complexity,
        }
    )


def _plan_json(*steps) -> str:
    """Build a planner JSON response from (task, tool, args) tuples."""
    import json as _json

    return _json.dumps(
        {"plan": [{"task": t, "tool": tool, "args": args} for (t, tool, args) in steps]}
    )


def _orch_json(*subtasks) -> str:
    """Build an orchestrator JSON response from (task, focus, tool, args) tuples."""
    import json as _json

    return _json.dumps(
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


def _ma_route_json(*agent_ids, reason="because") -> str:
    """Build a multi-agent supervisor routing JSON response."""
    import json as _json

    return _json.dumps({"agents": list(agent_ids), "reason": reason})


def _ma_tools_json(*calls) -> str:
    """Build a Researcher tool-plan JSON response from (tool, args) tuples."""
    import json as _json

    return _json.dumps({"tools": [{"tool": t, "args": args} for (t, args) in calls]})


def _dag_json(*nodes) -> str:
    """Build a DAG decomposition JSON from (id, task, focus, tool, args, depends_on) tuples."""
    import json as _json

    return _json.dumps(
        {
            "nodes": [
                {
                    "id": nid,
                    "task": task,
                    "focus": focus,
                    "tool": tool,
                    "args": args,
                    "depends_on": list(deps),
                }
                for (nid, task, focus, tool, args, deps) in nodes
            ]
        }
    )


def _auto_bootstrap(goal="Analyse AAPL", *backlog) -> str:
    """Build an autonomous bootstrap JSON (restated goal + seed backlog)."""
    import json as _json

    return _json.dumps({"goal": goal, "backlog": list(backlog) or ["a task"]})


def _auto_controller(
    *,
    goal_complete=False,
    next_task="do the thing",
    action="reason",
    tool=None,
    args=None,
    subagent_goal="",
    backlog=("do the thing",),
) -> str:
    """Build an autonomous controller-cycle JSON decision."""
    import json as _json

    return _json.dumps(
        {
            "reflection": "reflecting",
            "goal_complete": goal_complete,
            "next_task": next_task,
            "backlog": list(backlog),
            "action": action,
            "tool": tool,
            "args": args,
            "subagent_goal": subagent_goal,
        }
    )


# ---------------------------------------------------------------------------
# _get_or_create_system_user
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSystemUser:
    def test_creates_system_user_once(self):
        user = _get_or_create_system_user()
        assert user.email == "llm-live@system.local"
        assert not user.has_usable_password()
        # Idempotent: a second call reuses the same row.
        again = _get_or_create_system_user()
        assert again.pk == user.pk
        assert get_user_model().objects.filter(email="llm-live@system.local").count() == 1


# ---------------------------------------------------------------------------
# chat subcommand
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestChatSubcommand:
    def test_chat_with_query_prints_result(self):
        with patch(
            "apps.llm_analysis.services.chat", return_value="AAPL looks strong."
        ) as mock_chat:
            output = _run("chat", "How is AAPL doing?")
        mock_chat.assert_called_once()
        assert "AAPL looks strong." in output
        assert "Done." in output

    def test_chat_with_example_uses_example_query(self):
        with patch("apps.llm_analysis.services.chat", return_value="ok") as mock_chat:
            output = _run("chat", "--example", "0")
        # The first example query was forwarded to the model.
        sent_messages = mock_chat.call_args.args[0]
        assert sent_messages[0]["content"] == EXAMPLE_QUERIES[0]
        assert EXAMPLE_QUERIES[0] in output

    def test_chat_forwards_model_override(self):
        with patch("apps.llm_analysis.services.chat", return_value="ok") as mock_chat:
            _run("chat", "q", "--model", "llama3.2")
        assert mock_chat.call_args.kwargs["model"] == "llama3.2"

    def test_chat_ollama_error_raises_command_error(self):
        with patch("apps.llm_analysis.services.chat", side_effect=OllamaServiceError("down")):
            with pytest.raises(CommandError, match="Ollama error"):
                _run("chat", "q")

    def test_chat_requires_query_or_example(self):
        with pytest.raises(CommandError):
            _run("chat")


# ---------------------------------------------------------------------------
# chain subcommand
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestChainSubcommand:
    def test_chain_persists_run_and_reports_complete(self):
        with (
            patch("apps.llm_analysis.services.chat", return_value="ok"),
            patch("apps.llm_analysis.chain._STEP_HANDLERS", FAKE_STEP_HANDLERS),
        ):
            output = _run("chain", "Analyse AAPL")

        assert AgentRun.objects.filter(kind="chain").count() == 1
        run = AgentRun.objects.filter(kind="chain").first()
        assert run.status == "done"
        assert run.query == "Analyse AAPL"
        assert "Chain complete" in output
        assert str(run.pk) in output

    def test_chain_with_example(self):
        with (
            patch("apps.llm_analysis.services.chat", return_value="ok"),
            patch("apps.llm_analysis.chain._STEP_HANDLERS", FAKE_STEP_HANDLERS),
        ):
            _run("chain", "--example", "1")
        run = AgentRun.objects.filter(kind="chain").get()
        assert run.query == EXAMPLE_QUERIES[1]

    def test_chain_all_examples_runs_each(self):
        with (
            patch("apps.llm_analysis.services.chat", return_value="ok"),
            patch("apps.llm_analysis.chain._STEP_HANDLERS", FAKE_STEP_HANDLERS),
        ):
            _run("chain", "--all-examples")
        assert AgentRun.objects.filter(kind="chain").count() == len(EXAMPLE_QUERIES)
        assert {r.query for r in AgentRun.objects.filter(kind="chain").all()} == set(
            EXAMPLE_QUERIES
        )

    def test_chain_reuses_single_system_user(self):
        with (
            patch("apps.llm_analysis.services.chat", return_value="ok"),
            patch("apps.llm_analysis.chain._STEP_HANDLERS", FAKE_STEP_HANDLERS),
        ):
            _run("chain", "--all-examples")
        # All runs are attributed to the one shared system user.
        assert get_user_model().objects.filter(email="llm-live@system.local").count() == 1
        assert {r.user.email for r in AgentRun.objects.filter(kind="chain").all()} == {
            "llm-live@system.local"
        }

    def test_chain_step_error_reports_failure(self):
        def boom(q, c, m):
            raise RuntimeError("LLM exploded")

        handlers = {**FAKE_STEP_HANDLERS, "synthesise": boom}
        with (
            patch("apps.llm_analysis.services.chat", return_value="ok"),
            patch("apps.llm_analysis.chain._STEP_HANDLERS", handlers),
        ):
            output = _run("chain", "Analyse AAPL")

        run = AgentRun.objects.filter(kind="chain").get()
        assert run.status == "error"
        assert "Chain failed" in output
        assert "LLM exploded" in output

    def test_chain_requires_query_example_or_all(self):
        with pytest.raises(CommandError):
            _run("chain")


# ---------------------------------------------------------------------------
# parallel subcommand
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestParallelSubcommand:
    def test_parallel_sectioning_persists_run_and_reports_complete(self):
        aspects = [{"ok": "body", "error": None}] * 3
        with (
            patch("apps.llm_analysis.services.chat_many", return_value=aspects),
            patch("apps.llm_analysis.services.chat", return_value="final synthesis"),
        ):
            output = _run("parallel", "Analyse AAPL")

        run = AgentRun.objects.filter(kind="parallel").get()
        assert run.meta["strategy"] == "sectioning"
        assert run.status == "done"
        assert "Valuation" in output
        assert "Parallel complete" in output
        assert "final synthesis" in output

    def test_parallel_voting_reports_tally(self):
        import json as _json

        votes = [
            {"ok": _json.dumps({"verdict": v, "reason": "r"}), "error": None}
            for v in ("buy", "buy", "sell")
        ]
        with (
            patch("apps.llm_analysis.services.chat_many", return_value=votes),
            patch("apps.llm_analysis.services.chat", return_value="consensus"),
        ):
            output = _run("parallel", "Buy AAPL?", "--strategy", "voting", "--n", "3")

        run = AgentRun.objects.filter(kind="parallel").get()
        assert run.meta["strategy"] == "voting"
        assert run.meta["n"] == 3
        assert run.meta["tally"] == {"buy": 2, "hold": 0, "sell": 1}
        assert "tally:" in output
        assert "Parallel complete" in output

    def test_parallel_with_example(self):
        aspects = [{"ok": "body", "error": None}] * 3
        with (
            patch("apps.llm_analysis.services.chat_many", return_value=aspects),
            patch("apps.llm_analysis.services.chat", return_value="final"),
        ):
            _run("parallel", "--example", "0")
        assert AgentRun.objects.filter(kind="parallel").get().query == EXAMPLE_QUERIES[0]

    def test_parallel_reuses_single_system_user(self):
        aspects = [{"ok": "body", "error": None}] * 3
        with (
            patch("apps.llm_analysis.services.chat_many", return_value=aspects),
            patch("apps.llm_analysis.services.chat", return_value="final"),
        ):
            _run("parallel", "--all-examples")
        assert AgentRun.objects.filter(kind="parallel").count() == len(EXAMPLE_QUERIES)
        assert {r.user.email for r in AgentRun.objects.filter(kind="parallel").all()} == {
            "llm-live@system.local"
        }

    def test_parallel_requires_query_example_or_all(self):
        with pytest.raises(CommandError):
            _run("parallel")


# ---------------------------------------------------------------------------
# react subcommand
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReactSubcommand:
    def test_react_persists_run_and_reports_answer(self):
        import json as _json

        action = _json.dumps(
            {"thought": "need data", "tool": "company_snapshot", "args": {"symbol": "AAPL"}}
        )
        answer = _json.dumps({"thought": "done", "answer": "AAPL is fairly valued."})
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[action, answer]),
            patch("apps.llm_analysis.tools.run_tool", return_value='{"trailing_pe": 31}'),
        ):
            output = _run("react", "Is AAPL cheap?")

        run = AgentRun.objects.filter(kind="react").get()
        assert run.status == "done"
        assert run.output == "AAPL is fairly valued."
        assert run.steps.count() == 2
        assert "company_snapshot" in output
        assert "ReAct complete" in output
        assert "AAPL is fairly valued." in output

    def test_react_respects_max_steps(self):
        import json as _json

        # Never answers -> budget exhausted -> forced final answer.
        action = _json.dumps(
            {"thought": "loop", "tool": "company_snapshot", "args": {"symbol": "AAPL"}}
        )
        forced = _json.dumps({"answer": "forced answer"})
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[action, action, forced]),
            patch("apps.llm_analysis.tools.run_tool", return_value="{}"),
        ):
            output = _run("react", "Loop forever", "--max-steps", "2")

        run = AgentRun.objects.filter(kind="react").get()
        assert run.meta["max_steps"] == 2
        assert run.status == "done"
        assert "forced answer" in output

    def test_react_with_example(self):
        import json as _json

        with patch(
            "apps.llm_analysis.services.chat",
            return_value=_json.dumps({"answer": "ok"}),
        ):
            _run("react", "--example", "1")
        assert AgentRun.objects.filter(kind="react").get().query == EXAMPLE_QUERIES[1]

    def test_react_reuses_single_system_user(self):
        import json as _json

        with patch(
            "apps.llm_analysis.services.chat",
            return_value=_json.dumps({"answer": "ok"}),
        ):
            _run("react", "--all-examples")
        assert AgentRun.objects.filter(kind="react").count() == len(EXAMPLE_QUERIES)
        assert {r.user.email for r in AgentRun.objects.filter(kind="react").all()} == {
            "llm-live@system.local"
        }

    def test_react_requires_query_example_or_all(self):
        with pytest.raises(CommandError):
            _run("react")


# ---------------------------------------------------------------------------
# evaluate subcommand (Evaluator-Optimizer)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEvaluateSubcommand:
    def test_evaluate_passes_first_iteration(self):
        import json as _json

        # generate -> draft; evaluate -> high score with pass=true (loop stops).
        verdict = _json.dumps({"score": 9, "feedback": "great", "pass": True})
        with patch(
            "apps.llm_analysis.services.chat",
            side_effect=["My draft answer.", verdict],
        ):
            output = _run("evaluate", "Is AAPL a buy?")

        run = AgentRun.objects.filter(kind="eval_opt").get()
        assert run.status == "done"
        assert run.query == "Is AAPL a buy?"
        assert run.output == "My draft answer."
        assert run.meta["best_score"] == 9
        assert run.steps.count() == 1
        iteration = run.steps.get()
        assert iteration.order == 0
        assert iteration.meta["score"] == 9
        assert iteration.meta["passed"] is True
        assert iteration.status == "done"
        assert "score=9" in output
        assert "PASS" in output
        assert "Evaluator-Optimizer complete" in output
        assert "My draft answer." in output

    def test_evaluate_revises_then_returns_best(self):
        import json as _json

        low = _json.dumps({"score": 5, "feedback": "add numbers", "pass": False})
        high = _json.dumps({"score": 9, "feedback": "good", "pass": True})
        # generate -> draft1; eval(5); revise -> draft2; eval(9) pass.
        with patch(
            "apps.llm_analysis.services.chat",
            side_effect=["draft one", low, "draft two", high],
        ):
            output = _run("evaluate", "Assess Tesla debt", "--max-iterations", "3")

        run = AgentRun.objects.filter(kind="eval_opt").get()
        assert run.status == "done"
        assert run.steps.count() == 2
        assert run.meta["best_score"] == 9
        # Best-scoring draft is the revised one, not necessarily the last graded.
        assert run.output == "draft two"
        assert [it.meta["score"] for it in run.steps.order_by("order")] == [5, 9]
        assert "revise" in output
        assert "PASS" in output

    def test_evaluate_exhausts_budget_returns_best_seen(self):
        import json as _json

        # Never passes; max_iterations=2 -> two evaluations, returns highest score draft.
        first = _json.dumps({"score": 6, "feedback": "more", "pass": False})
        second = _json.dumps({"score": 4, "feedback": "worse", "pass": False})
        with patch(
            "apps.llm_analysis.services.chat",
            side_effect=["draft one", first, "draft two", second],
        ):
            output = _run("evaluate", "Hard question", "--max-iterations", "2")

        run = AgentRun.objects.filter(kind="eval_opt").get()
        assert run.status == "done"
        assert run.steps.count() == 2
        assert run.meta["best_score"] == 6
        assert run.output == "draft one"
        assert "Evaluator-Optimizer complete" in output

    def test_evaluate_threshold_override(self):
        import json as _json

        # threshold=5 means a score of 6 passes immediately even without pass=true.
        verdict = _json.dumps({"score": 6, "feedback": "ok", "pass": False})
        with patch(
            "apps.llm_analysis.services.chat",
            side_effect=["draft", verdict],
        ):
            _run("evaluate", "q", "--threshold", "5")

        run = AgentRun.objects.filter(kind="eval_opt").get()
        assert run.meta["threshold"] == 5
        assert run.steps.count() == 1
        assert run.meta["best_score"] == 6

    def test_evaluate_unparseable_verdict_flagged(self):
        # Bad evaluator output -> score 0, iteration flagged error, loop still finishes.
        # generate -> draft; eval(bad); revise -> draft2; eval(bad).
        with patch(
            "apps.llm_analysis.services.chat",
            side_effect=["draft", "not json", "draft two", "still not json"],
        ):
            output = _run("evaluate", "q", "--max-iterations", "2")

        run = AgentRun.objects.filter(kind="eval_opt").get()
        assert run.status == "done"
        assert run.output == "draft"
        assert run.steps.filter(status="error").count() == 2
        assert "unparseable verdict" in output

    def test_evaluate_generate_error_reports_failure(self):
        with patch(
            "apps.llm_analysis.services.chat",
            side_effect=OllamaServiceError("ollama down"),
        ):
            output = _run("evaluate", "q")

        run = AgentRun.objects.filter(kind="eval_opt").get()
        assert run.status == "error"
        assert "ollama down" in run.error
        assert "error" in output

    def test_evaluate_with_example(self):
        import json as _json

        verdict = _json.dumps({"score": 9, "feedback": "ok", "pass": True})
        with patch(
            "apps.llm_analysis.services.chat",
            side_effect=["draft", verdict],
        ):
            _run("evaluate", "--example", "2")
        assert AgentRun.objects.filter(kind="eval_opt").get().query == EXAMPLE_QUERIES[2]

    def test_evaluate_reuses_single_system_user(self):
        import json as _json

        verdict = _json.dumps({"score": 9, "feedback": "ok", "pass": True})
        with patch(
            "apps.llm_analysis.services.chat",
            side_effect=["draft", verdict] * len(EXAMPLE_QUERIES),
        ):
            _run("evaluate", "--all-examples")
        assert AgentRun.objects.filter(kind="eval_opt").count() == len(EXAMPLE_QUERIES)
        assert {r.user.email for r in AgentRun.objects.filter(kind="eval_opt").all()} == {
            "llm-live@system.local"
        }

    def test_evaluate_requires_query_example_or_all(self):
        with pytest.raises(CommandError):
            _run("evaluate")


# ---------------------------------------------------------------------------
# route subcommand
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRouteSubcommand:
    def test_route_simple_persists_run_and_reports_result(self):
        # First chat classifies (route=simple); second answers the query directly.
        with patch(
            "apps.llm_analysis.services.chat",
            side_effect=[_classification("simple"), "AAPL trades around $190."],
        ):
            output = _run("route", "What is AAPL's price?")

        run = AgentRun.objects.filter(kind="route").get()
        assert run.meta["route"] == "simple"
        assert run.status == "done"
        assert run.output == "AAPL trades around $190."
        assert run.parent is None
        assert "route=simple" in output
        assert "Route complete" in output
        assert "AAPL trades around $190." in output

    def test_route_deep_research_runs_nested_chain(self):
        # deep_research dispatches to the full chain; nested chain events are printed.
        with (
            patch(
                "apps.llm_analysis.services.chat",
                return_value=_classification("deep_research", ["AAPL"], "high"),
            ),
            patch("apps.llm_analysis.chain._STEP_HANDLERS", FAKE_STEP_HANDLERS),
        ):
            output = _run("route", "Give an AAPL investment thesis")

        run = AgentRun.objects.filter(kind="route").get()
        assert run.meta["route"] == "deep_research"
        assert run.status == "done"
        assert run.parent is not None
        # The format step's output becomes the route output.
        assert run.output == "## Summary\nLooks solid."
        assert "[chain:" in output
        assert "Route complete" in output

    def test_route_with_example(self):
        with patch(
            "apps.llm_analysis.services.chat",
            side_effect=[_classification("simple"), "answer"],
        ):
            _run("route", "--example", "0")
        assert AgentRun.objects.filter(kind="route").get().query == EXAMPLE_QUERIES[0]

    def test_route_error_reports_failure(self):
        with patch(
            "apps.llm_analysis.services.chat",
            side_effect=OllamaServiceError("ollama down"),
        ):
            output = _run("route", "q")

        run = AgentRun.objects.filter(kind="route").get()
        assert run.status == "error"
        assert "ollama down" in run.error
        assert "error" in output

    def test_route_reuses_single_system_user(self):
        with patch(
            "apps.llm_analysis.services.chat",
            side_effect=[_classification("simple"), "answer"] * len(EXAMPLE_QUERIES),
        ):
            _run("route", "--all-examples")
        assert AgentRun.objects.filter(kind="route").count() == len(EXAMPLE_QUERIES)
        assert {r.user.email for r in AgentRun.objects.filter(kind="route").all()} == {
            "llm-live@system.local"
        }

    def test_route_requires_query_example_or_all(self):
        with pytest.raises(CommandError):
            _run("route")


# ---------------------------------------------------------------------------
# plan subcommand (Plan-and-Execute)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPlanSubcommand:
    def test_plan_persists_run_and_reports_answer(self):
        # plan -> execute step 0 (tool) -> execute step 1 (reason) -> synthesise.
        chat = [
            _plan_json(
                ("Fetch AAPL snapshot", "company_snapshot", {"symbol": "AAPL"}),
                ("Write the verdict", None, None),
            ),
            "AAPL trades at 31x earnings.",
            "Fairly valued.",
            "## Verdict\nFairly valued.",
        ]
        with (
            patch("apps.llm_analysis.services.chat", side_effect=chat),
            patch("apps.llm_analysis.tools.run_tool", return_value='{"trailing_pe": 31}'),
        ):
            output = _run("plan", "Is AAPL cheap?")

        run = AgentRun.objects.filter(kind="plan_exec").get()
        assert run.status == "done"
        assert run.meta["allow_replan"] is True
        assert run.steps.count() == 2
        assert run.output == "## Verdict\nFairly valued."
        assert "company_snapshot" in output
        assert "Plan-and-Execute complete" in output

    def test_plan_no_replan_flag_disables_replanning(self):
        chat = [
            _plan_json(("Fetch profile", "company_profile", {"symbol": "NOPE"})),
            "step result",
            "## Done.",
        ]
        with (
            patch("apps.llm_analysis.services.chat", side_effect=chat),
            patch("apps.llm_analysis.tools.run_tool", return_value='{"error": "no company"}'),
        ):
            output = _run("plan", "Look at NOPE", "--no-replan")

        run = AgentRun.objects.filter(kind="plan_exec").get()
        assert run.meta["allow_replan"] is False
        assert run.meta["replans"] == 0
        assert "REPLAN" not in output

    def test_plan_respects_max_steps(self):
        chat = [_plan_json(("Only step", None, None)), "result", "## Final."]
        with patch("apps.llm_analysis.services.chat", side_effect=chat):
            _run("plan", "q", "--max-steps", "3")
        assert AgentRun.objects.filter(kind="plan_exec").get().meta["max_steps"] == 3

    def test_plan_with_example(self):
        chat = [_plan_json(("Think", None, None)), "result", "## Final."]
        with patch("apps.llm_analysis.services.chat", side_effect=chat):
            _run("plan", "--example", "2")
        assert AgentRun.objects.filter(kind="plan_exec").get().query == EXAMPLE_QUERIES[2]

    def test_plan_reuses_single_system_user(self):
        chat = [_plan_json(("Think", None, None)), "result", "## Final."] * len(EXAMPLE_QUERIES)
        with patch("apps.llm_analysis.services.chat", side_effect=chat):
            _run("plan", "--all-examples")
        assert AgentRun.objects.filter(kind="plan_exec").count() == len(EXAMPLE_QUERIES)
        assert {r.user.email for r in AgentRun.objects.filter(kind="plan_exec").all()} == {
            "llm-live@system.local"
        }

    def test_plan_requires_query_example_or_all(self):
        with pytest.raises(CommandError):
            _run("plan")


# ---------------------------------------------------------------------------
# orchestrate subcommand (Orchestrator-Workers)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestOrchestrateSubcommand:
    def test_orchestrate_persists_run_and_reports_answer(self):
        # orchestrate (decompose) -> workers fan out via chat_many -> synthesise.
        orchestrate = _orch_json(
            (
                "Aggregate sector valuation",
                "valuation",
                "sector_analysis",
                {"sector": "Technology"},
            ),
            ("Assess balance-sheet risk", "risk", None, None),
        )
        with (
            patch(
                "apps.llm_analysis.services.chat",
                side_effect=[orchestrate, "## Verdict\nFairly valued."],
            ),
            patch("apps.llm_analysis.tools.run_tool", return_value='{"metrics": {}}'),
            patch(
                "apps.llm_analysis.services.chat_many",
                return_value=_ok_many("valuation output", "risk output"),
            ),
        ):
            output = _run("orchestrate", "Give me a full picture of AAPL")

        run = AgentRun.objects.filter(kind="orchestrator").get()
        assert run.status == "done"
        assert run.steps.count() == 2
        assert run.output == "## Verdict\nFairly valued."
        assert run.meta["plan"] is not None and len(run.meta["plan"]) == 2
        assert "Decomposition:" in output
        assert "sector_analysis" in output
        assert "Orchestrator-Workers complete" in output
        assert "Fairly valued." in output

    def test_orchestrate_respects_max_workers(self):
        orchestrate = _orch_json(("Only subtask", "focus", None, None))
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[orchestrate, "## Final."]),
            patch("apps.llm_analysis.services.chat_many", return_value=_ok_many("out")),
        ):
            _run("orchestrate", "q", "--max-workers", "3")
        assert AgentRun.objects.filter(kind="orchestrator").get().meta["max_workers"] == 3

    def test_orchestrate_failed_worker_reported_others_survive(self):
        orchestrate = _orch_json(
            ("a", "fa", None, None),
            ("b", "fb", None, None),
        )
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[orchestrate, "## Done."]),
            patch(
                "apps.llm_analysis.services.chat_many",
                return_value=[
                    {"ok": "good", "error": None},
                    {"ok": None, "error": "worker boom"},
                ],
            ),
        ):
            output = _run("orchestrate", "q")

        run = AgentRun.objects.filter(kind="orchestrator").get()
        assert run.status == "done"
        assert run.steps.filter(status="error").count() == 1
        assert "worker boom" in output
        assert "Orchestrator-Workers complete" in output

    def test_orchestrate_unparseable_decomposition_reports_error(self):
        with patch("apps.llm_analysis.services.chat", side_effect=["not a decomposition"]):
            output = _run("orchestrate", "q")

        run = AgentRun.objects.filter(kind="orchestrator").get()
        assert run.status == "error"
        assert "error" in output

    def test_orchestrate_with_example(self):
        orchestrate = _orch_json(("Think", "focus", None, None))
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[orchestrate, "## Final."]),
            patch("apps.llm_analysis.services.chat_many", return_value=_ok_many("out")),
        ):
            _run("orchestrate", "--example", "2")
        assert AgentRun.objects.filter(kind="orchestrator").get().query == EXAMPLE_QUERIES[2]

    def test_orchestrate_reuses_single_system_user(self):
        orchestrate = _orch_json(("Think", "focus", None, None))
        chat = [orchestrate, "## Final."] * len(EXAMPLE_QUERIES)
        with (
            patch("apps.llm_analysis.services.chat", side_effect=chat),
            patch("apps.llm_analysis.services.chat_many", return_value=_ok_many("out")),
        ):
            _run("orchestrate", "--all-examples")
        assert AgentRun.objects.filter(kind="orchestrator").count() == len(EXAMPLE_QUERIES)
        assert {r.user.email for r in AgentRun.objects.filter(kind="orchestrator").all()} == {
            "llm-live@system.local"
        }

    def test_orchestrate_requires_query_example_or_all(self):
        with pytest.raises(CommandError):
            _run("orchestrate")


@pytest.mark.django_db
class TestMultiAgentSubcommand:
    def test_multiagent_persists_run_and_reports_answer(self):
        # route -> researcher tool-plan -> researcher write -> analyst -> writer -> synth
        chats = [
            _ma_route_json("researcher", "analyst", "writer"),
            _ma_tools_json(("company_snapshot", {"symbol": "AAPL"})),
            "research findings",
            "analysis",
            "writer draft",
            "## Verdict\nFairly valued.",
        ]
        with (
            patch("apps.llm_analysis.services.chat", side_effect=chats),
            patch("apps.llm_analysis.tools.run_tool", return_value='{"trailing_pe": 30}'),
        ):
            output = _run("multiagent", "Is AAPL cheap relative to its sector?")

        run = AgentRun.objects.filter(kind="multiagent").get()
        assert run.status == "done"
        assert run.meta["agents"] == ["researcher", "analyst", "writer"]
        assert run.steps.count() == 3
        assert run.output == "## Verdict\nFairly valued."
        assert "roster :" in output
        assert "Researcher" in output
        assert "company_snapshot" in output
        assert "Multi-Agent complete" in output
        assert "Fairly valued." in output

    def test_multiagent_respects_max_tools(self):
        chats = [_ma_route_json("writer"), "writer draft", "## Final."]
        with patch("apps.llm_analysis.services.chat", side_effect=chats):
            _run("multiagent", "q", "--max-tools", "2")
        assert AgentRun.objects.filter(kind="multiagent").get().meta["max_tools"] == 2

    def test_multiagent_supervisor_can_skip_researcher(self):
        chats = [_ma_route_json("writer"), "writer draft", "## Final."]
        with (
            patch("apps.llm_analysis.services.chat", side_effect=chats),
            patch("apps.llm_analysis.tools.run_tool") as run_tool,
        ):
            output = _run("multiagent", "Explain value investing.")

        run_tool.assert_not_called()
        run = AgentRun.objects.filter(kind="multiagent").get()
        assert run.meta["agents"] == ["writer"]
        assert run.steps.count() == 1
        assert "Multi-Agent complete" in output

    def test_multiagent_stage_failure_reported_pipeline_continues(self):
        chats = [
            _ma_route_json("analyst", "writer"),
            OllamaServiceError("analyst boom"),
            "writer draft",
            "## Done.",
        ]
        with patch("apps.llm_analysis.services.chat", side_effect=chats):
            output = _run("multiagent", "q")

        run = AgentRun.objects.filter(kind="multiagent").get()
        assert run.status == "done"
        assert run.steps.filter(status="error").count() == 1
        assert "analyst boom" in output
        assert "Multi-Agent complete" in output

    def test_multiagent_route_error_reports_failure(self):
        with patch("apps.llm_analysis.services.chat", side_effect=OllamaServiceError("down")):
            output = _run("multiagent", "q")

        run = AgentRun.objects.filter(kind="multiagent").get()
        assert run.status == "error"
        assert "error" in output

    def test_multiagent_with_example(self):
        chats = [_ma_route_json("writer"), "writer draft", "## Final."]
        with patch("apps.llm_analysis.services.chat", side_effect=chats):
            _run("multiagent", "--example", "2")
        assert AgentRun.objects.filter(kind="multiagent").get().query == EXAMPLE_QUERIES[2]

    def test_multiagent_reuses_single_system_user(self):
        chats = [_ma_route_json("writer"), "writer draft", "## Final."] * len(EXAMPLE_QUERIES)
        with patch("apps.llm_analysis.services.chat", side_effect=chats):
            _run("multiagent", "--all-examples")
        assert AgentRun.objects.filter(kind="multiagent").count() == len(EXAMPLE_QUERIES)
        assert {r.user.email for r in AgentRun.objects.filter(kind="multiagent").all()} == {
            "llm-live@system.local"
        }

    def test_multiagent_requires_query_example_or_all(self):
        with pytest.raises(CommandError):
            _run("multiagent")


# ---------------------------------------------------------------------------
# dag subcommand (Multi-Agent Parallel/DAG)
# ---------------------------------------------------------------------------


def _dag_many(batches, model=None):
    """chat_many side-effect: one ok output per node in the wave."""
    return [{"ok": f"node out {i}", "error": None} for i in range(len(batches))]


@pytest.mark.django_db
class TestDagSubcommand:
    def test_dag_persists_run_and_reports_answer(self):
        # decompose -> 2 nodes (b depends on a) -> two waves -> synthesise.
        decompose = _dag_json(
            ("a", "Fetch AAPL snapshot", "valuation", "company_snapshot", {"symbol": "AAPL"}, []),
            ("b", "Write the verdict", "verdict", None, None, ["a"]),
        )
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[decompose, "## Verdict\nFair."]),
            patch("apps.llm_analysis.services.chat_many", side_effect=_dag_many),
            patch("apps.llm_analysis.tools.run_tool", return_value='{"trailing_pe": 31}'),
        ):
            output = _run("dag", "Compare AAPL valuation then a verdict")

        run = AgentRun.objects.filter(kind="dag").get()
        assert run.status == "done"
        assert run.steps.count() == 2
        assert run.output == "## Verdict\nFair."
        assert run.meta["plan"]["waves"] == [["a"], ["b"]]
        assert "Graph:" in output
        assert "company_snapshot" in output
        assert "Multi-Agent DAG complete" in output
        assert "Fair." in output

    def test_dag_respects_max_nodes(self):
        decompose = _dag_json(("a", "Only node", "focus", None, None, []))
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[decompose, "## Final."]),
            patch("apps.llm_analysis.services.chat_many", side_effect=_dag_many),
        ):
            _run("dag", "q", "--max-nodes", "3")
        assert AgentRun.objects.filter(kind="dag").get().meta["max_nodes"] == 3

    def test_dag_failed_node_reported_others_survive(self):
        decompose = _dag_json(
            ("a", "node a", "fa", None, None, []),
            ("b", "node b", "fb", None, None, []),
        )

        def fake_many(batches, model=None):
            return [
                {"ok": None, "error": "node boom"},
                {"ok": "good b", "error": None},
            ]

        with (
            patch("apps.llm_analysis.services.chat", side_effect=[decompose, "## Done."]),
            patch("apps.llm_analysis.services.chat_many", side_effect=fake_many),
        ):
            output = _run("dag", "q")

        run = AgentRun.objects.filter(kind="dag").get()
        assert run.status == "done"
        assert run.steps.filter(status="error").count() == 1
        assert "node boom" in output
        assert "Multi-Agent DAG complete" in output

    def test_dag_unparseable_decomposition_reports_error(self):
        with patch("apps.llm_analysis.services.chat", side_effect=["not a graph"]):
            output = _run("dag", "q")

        run = AgentRun.objects.filter(kind="dag").get()
        assert run.status == "error"
        assert "error" in output

    def test_dag_with_example(self):
        decompose = _dag_json(("a", "Think", "focus", None, None, []))
        with (
            patch("apps.llm_analysis.services.chat", side_effect=[decompose, "## Final."]),
            patch("apps.llm_analysis.services.chat_many", side_effect=_dag_many),
        ):
            _run("dag", "--example", "1")
        assert AgentRun.objects.filter(kind="dag").get().query == EXAMPLE_QUERIES[1]

    def test_dag_reuses_single_system_user(self):
        decompose = _dag_json(("a", "Think", "focus", None, None, []))
        chat = [decompose, "## Final."] * len(EXAMPLE_QUERIES)
        with (
            patch("apps.llm_analysis.services.chat", side_effect=chat),
            patch("apps.llm_analysis.services.chat_many", side_effect=_dag_many),
        ):
            _run("dag", "--all-examples")
        assert AgentRun.objects.filter(kind="dag").count() == len(EXAMPLE_QUERIES)
        assert {r.user.email for r in AgentRun.objects.filter(kind="dag").all()} == {
            "llm-live@system.local"
        }

    def test_dag_requires_query_example_or_all(self):
        with pytest.raises(CommandError):
            _run("dag")


# ---------------------------------------------------------------------------
# autonomous subcommand (Autonomous / Long-Horizon)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAutonomousSubcommand:
    def test_autonomous_persists_run_and_reports_answer(self):
        # bootstrap -> cycle0 (reason+execute) -> cycle1 (goal_complete) -> synthesise.
        chat = [
            _auto_bootstrap("Analyse AAPL", "gather data", "form a view"),
            _auto_controller(action="reason", next_task="gather data"),
            "cycle result",
            _auto_controller(goal_complete=True),
            "## Verdict\nFairly valued.",
        ]
        with patch("apps.llm_analysis.services.chat", side_effect=chat):
            output = _run("autonomous", "Build an AAPL thesis")

        run = AgentRun.objects.filter(kind="autonomous").get()
        assert run.status == "done"
        assert run.meta["stop_reason"] == "complete"
        assert run.steps.count() == 2
        assert run.output == "## Verdict\nFairly valued."
        assert "Goal :" in output
        assert "Autonomous complete" in output
        assert "Fairly valued." in output

    def test_autonomous_tool_cycle_reports_tool(self):
        chat = [
            _auto_bootstrap(),
            _auto_controller(action="tool", tool="company_snapshot", args={"symbol": "AAPL"}),
            "interpreted snapshot",
            _auto_controller(goal_complete=True),
            "## Final.",
        ]
        with (
            patch("apps.llm_analysis.services.chat", side_effect=chat),
            patch("apps.llm_analysis.tools.run_tool", return_value='{"trailing_pe": 30}') as rt,
        ):
            output = _run("autonomous", "Is AAPL cheap?")

        rt.assert_called_once_with("company_snapshot", {"symbol": "AAPL"})
        run = AgentRun.objects.filter(kind="autonomous").get()
        assert run.status == "done"
        assert "company_snapshot" in output

    def test_autonomous_spawns_subagent(self):
        import json as _json

        chat = [
            _auto_bootstrap(),
            _auto_controller(action="subagent", subagent_goal="deep dive AAPL"),
            _json.dumps({"answer": "sub findings"}),  # sub-agent answers immediately
            _auto_controller(goal_complete=True),
            "## Final.",
        ]
        with patch("apps.llm_analysis.services.chat", side_effect=chat):
            output = _run("autonomous", "Deep dive AAPL", "--max-subagents", "2")

        run = AgentRun.objects.filter(kind="autonomous").get()
        assert run.status == "done"
        cycle = run.steps.get(order=0)
        assert cycle.meta["spawned"] is True
        assert "subagent" in output

    def test_autonomous_respects_max_cycles(self):
        # Controller never completes -> budget stops the loop after 2 cycles.
        chat = [
            _auto_bootstrap(),
            _auto_controller(action="reason", next_task="a"),
            "result a",
            _auto_controller(action="reason", next_task="b"),
            "result b",
            "## Final.",
        ]
        with patch("apps.llm_analysis.services.chat", side_effect=chat):
            output = _run("autonomous", "q", "--max-cycles", "2")

        run = AgentRun.objects.filter(kind="autonomous").get()
        assert run.meta["max_cycles"] == 2
        assert run.meta["stop_reason"] == "budget"
        assert run.steps.count() == 2
        assert "Autonomous complete" in output

    def test_autonomous_bootstrap_error_reports_failure(self):
        with patch(
            "apps.llm_analysis.services.chat", side_effect=OllamaServiceError("ollama down")
        ):
            output = _run("autonomous", "q")

        run = AgentRun.objects.filter(kind="autonomous").get()
        assert run.status == "error"
        assert "ollama down" in run.error
        assert "error" in output

    def test_autonomous_with_example(self):
        chat = [
            _auto_bootstrap(),
            _auto_controller(action="reason", next_task="a"),
            "result",
            _auto_controller(goal_complete=True),
            "## Final.",
        ]
        with patch("apps.llm_analysis.services.chat", side_effect=chat):
            _run("autonomous", "--example", "2")
        assert AgentRun.objects.filter(kind="autonomous").get().query == EXAMPLE_QUERIES[2]

    def test_autonomous_reuses_single_system_user(self):
        chat = [
            _auto_bootstrap(),
            _auto_controller(action="reason", next_task="a"),
            "result",
            _auto_controller(goal_complete=True),
            "## Final.",
        ] * len(EXAMPLE_QUERIES)
        with patch("apps.llm_analysis.services.chat", side_effect=chat):
            _run("autonomous", "--all-examples")
        assert AgentRun.objects.filter(kind="autonomous").count() == len(EXAMPLE_QUERIES)
        assert {r.user.email for r in AgentRun.objects.filter(kind="autonomous").all()} == {
            "llm-live@system.local"
        }

    def test_autonomous_requires_query_example_or_all(self):
        with pytest.raises(CommandError):
            _run("autonomous")


def _chat_action(tool, **args):
    import json as _json

    return _json.dumps({"thought": f"calling {tool}", "tool": tool, "args": args})


def _chat_answer(text="hello there"):
    """Since phase 5 an ANSWER is plain prose - that is what makes it streamable."""
    return text


def _patch_chat_tokens(*replies):
    """Patch the chat agent's token stream, chunked so the command's delta rendering runs."""
    queue = list(replies)

    def side_effect(*_args, **_kwargs):
        item = queue.pop(0)
        return iter([item[i : i + 8] for i in range(0, len(item), 8)] or [""])

    return patch("apps.llm_analysis.services.chat_tokens", side_effect=side_effect)


@pytest.mark.django_db
class TestChatAgentSubcommand:
    """`chatagent` exists so the live verification is REPEATABLE. The one defect a live run
    found on issue #8 was budget arithmetic that every unit test agreed with, so the command
    prints the budget alongside the conversation."""

    def test_a_single_turn_creates_a_session_and_persists_the_run(self):
        with _patch_chat_tokens(_chat_answer("hi there")):
            out = _run("chatagent", "hello")

        run = AgentRun.objects.get(kind="chat")
        assert run.output == "hi there"
        assert run.session_id is not None
        assert "hi there" in out
        assert str(run.session_id) in out

    def test_continues_an_existing_session(self):
        from apps.llm_analysis.models import ChatSession

        session = ChatSession.objects.create(user=_get_or_create_system_user())
        with _patch_chat_tokens(_chat_answer()):
            _run("chatagent", "hello", "--session", str(session.id))

        assert AgentRun.objects.get(kind="chat").session_id == session.id

    def test_smoke_runs_every_scripted_turn_in_one_session(self):
        replies = [
            _chat_answer("I help with research."),
            _chat_action("company_snapshot", symbol="AAPL"),
            _chat_answer("39.07"),
            _chat_action("company_snapshot", symbol="AAPL"),
            _chat_answer("forward is lower"),
        ]
        with (
            _patch_chat_tokens(*replies),
            patch("apps.llm_analysis.tools.run_tool", return_value='{"trailing_pe": 39.07}'),
        ):
            out = _run("chatagent", "--smoke")

        runs = AgentRun.objects.filter(kind="chat")
        assert runs.count() == 3
        assert len({r.session_id for r in runs}) == 1
        assert [r.meta["turn"] for r in runs.order_by("created_at")] == [0, 1, 2]
        assert "Transcript" in out

    def test_prints_the_tool_arguments_it_was_given(self):
        """Regression guard. Every step printer here read `args`, which issue #6 renamed to
        `tool_args` on the wire - so the live command had been printing `{}` for every tool
        call since. Cosmetic, but it is the output a live verification is READ from."""
        with (
            _patch_chat_tokens(_chat_action("company_snapshot", symbol="AAPL"), _chat_answer("ok")),
            patch("apps.llm_analysis.tools.run_tool", return_value="{}"),
        ):
            out = _run("chatagent", "what is AAPL's PE?")

        assert 'company_snapshot({"symbol": "AAPL"})' in out
        assert "company_snapshot({})" not in out

    def test_prints_the_context_budget(self):
        with _patch_chat_tokens(_chat_answer()):
            out = _run("chatagent", "hi")

        assert "budget:" in out and "history=" in out and "turn_reserve=" in out

    def test_requires_a_message_or_smoke(self):
        out = _run("chatagent")

        assert "Give a message" in out
        assert not AgentRun.objects.filter(kind="chat").exists()


class TestStepPrintersUseTheSerializerNames:
    """A structural guard for the whole command, not just chat.

    `_events.step_event` made the SSE payload the serializer's output in issue #6, which
    renamed `args` to `tool_args` on the wire. The structural test in test_step_payload.py
    covers the workflow MODULES - nothing covered the CONSUMERS, and five printers here had
    been reading the old key ever since, silently rendering `{}` for every tool call.
    """

    def _source(self) -> str:
        from pathlib import Path

        from apps.llm_analysis.management.commands import run_llm_live

        return Path(run_llm_live.__file__).read_text()

    def test_no_printer_reads_a_bare_args_key_off_an_event(self):
        assert 'event.get("args")' not in self._source(), (
            "a step event carries `tool_args`, not `args` - see issue #6 phase 2"
        )

    def test_the_nested_tool_calls_shape_is_untouched(self):
        """multiagent's `tool_calls` really is a list of {'tool', 'args', 'observation'}, so
        `call.get("args")` is correct. Pinned so a future sweep does not 'fix' it."""
        assert 'call.get("args")' in self._source()

    def test_dag_prints_the_graph_node_key_not_the_row_uuid(self):
        """`id` changed MEANING in issue #6 - row UUID - with the graph key in `node_id`.
        The frontend hit this and so had the command."""
        source = self._source()
        assert "event.get('node_id')" in source or 'event.get("node_id")' in source


@pytest.mark.django_db
class TestChatAgentStreamsInTheCommand:
    def test_the_reply_is_written_as_it_arrives(self):
        """A live smoke of a streaming feature that renders nothing streaming is not a smoke
        test of it. The deltas must reach stdout, not just the final `result`."""
        with _patch_chat_tokens("AAPL trades at 39.07x trailing earnings."):
            out = _run("chatagent", "what is AAPL's PE?")

        assert "AAPL trades at 39.07x trailing earnings." in out
        # Printed once - from the deltas - not once from the deltas and again from `result`.
        assert out.count("39.07x trailing earnings") == 1
