"""
Run live LLM queries and prompt chains, persisting results to the database.

Usage:
    # Run a single chat query
    python manage.py run_llm_live chat "Analyse Apple's revenue growth over 5 years"

    # Run one of the built-in example queries by index (0-4)
    python manage.py run_llm_live chat --example 0

    # Run the full 4-step prompt chain for a query
    python manage.py run_llm_live chain "Compare MSFT vs GOOG on profitability"

    # Run all 5 example queries through the full chain
    python manage.py run_llm_live chain --all-examples

    # Route a query: classify then dispatch to simple/analysis/deep_research
    python manage.py run_llm_live route "What is Apple's stock price?"

    # Route all 5 example queries
    python manage.py run_llm_live route --all-examples

    # Observable parallelization: sectioning (default) or N-way voting
    python manage.py run_llm_live parallel "Analyse Apple's valuation and risk"
    python manage.py run_llm_live parallel "Is AAPL a buy?" --strategy voting --n 3

    # ReAct agent: bounded Thought -> Tool -> Observation loop over read-only DB tools
    python manage.py run_llm_live react "Is AAPL cheap relative to its sector?"
    python manage.py run_llm_live react "Compare AAPL and MSFT debt" --max-steps 8

    # Evaluator-Optimizer agent: generate -> evaluate -> revise loop gated by a quality score
    python manage.py run_llm_live evaluate "Is AAPL a buy at current prices?"
    python manage.py run_llm_live evaluate "Assess Tesla's debt" --max-iterations 4 --threshold 9

    # Plan-and-Execute agent: plan upfront -> execute each step -> optional replan -> synthesise
    python manage.py run_llm_live plan "Is AAPL cheap relative to its sector?"
    python manage.py run_llm_live plan "Compare AAPL and MSFT" --max-steps 8 --no-replan

    # Orchestrator-Workers agent: decompose dynamically -> fan out workers -> synthesise
    python manage.py run_llm_live orchestrate "Give me a full picture of AAPL"
    python manage.py run_llm_live orchestrate "Assess Tesla's outlook" --max-workers 5

    # Multi-Agent (sequential): supervisor routes Researcher -> Analyst -> Writer, then synthesises
    python manage.py run_llm_live multiagent "Is AAPL cheap relative to its sector?"
    python manage.py run_llm_live multiagent "Assess Tesla's outlook" --max-tools 6

    # Multi-Agent (parallel/DAG): decompose into a dependency graph -> run waves -> synthesise
    python manage.py run_llm_live dag "Compare AAPL and MSFT on valuation, then give a verdict"
    python manage.py run_llm_live dag "Give me a full picture of AAPL" --max-nodes 8

    # Autonomous / Long-Horizon: goal-driven bounded loop -> reflect, self-assign, act, replan
    python manage.py run_llm_live autonomous "Build an investment thesis for AAPL"
    python manage.py run_llm_live autonomous "Assess Tesla" --max-cycles 10 --max-subagents 2

    # Chat agent: one conversational TURN inside a session (issue #8)
    python manage.py run_llm_live chatagent "What is AAPL's trailing P/E?"
    python manage.py run_llm_live chatagent "And its forward P/E?" --session <uuid>

    # ... or the scripted multi-turn smoke: no-tool turn, tool turn, follow-up, compaction
    python manage.py run_llm_live chatagent --smoke

    # Use a specific Ollama model
    python manage.py run_llm_live chain "Tesla debt situation" --model llama3.2
"""

from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.llm_analysis import services
from apps.llm_analysis.autonomous import run_autonomous
from apps.llm_analysis.chain import run_chain
from apps.llm_analysis.chat_agent import run_chat
from apps.llm_analysis.dag import run_dag
from apps.llm_analysis.eval_opt import run_eval_opt
from apps.llm_analysis.multiagent import run_multiagent
from apps.llm_analysis.orchestrator import run_orchestrator
from apps.llm_analysis.parallel import run_parallel
from apps.llm_analysis.plan_execute import run_plan
from apps.llm_analysis.react import run_react
from apps.llm_analysis.router import run_route
from apps.llm_analysis.services import (
    create_autonomous_run,
    create_chain_run,
    create_chat_run,
    create_dag_run,
    create_eo_run,
    create_multiagent_run,
    create_orchestrator_run,
    create_parallel_run,
    create_plan_run,
    create_react_run,
    create_route_run,
)

EXAMPLE_QUERIES = [
    "Analyse Apple's revenue growth over the last 5 years",
    "Compare MSFT vs GOOG on profitability and valuation",
    "What is Tesla's current debt situation and can it service it?",
    "Which S&P 500 energy stocks have the highest FCF yield?",
    "Summarise NVIDIA's latest quarterly earnings and outlook",
]

"""
What is Tesla's current debt situation and can it service it? Give an investment recommendation.
Compare MSFT vs GOOG on profitability margins and valuation ratios

Whats the best sector and best company in that sector to invest in right now,
based on recent performance and future outlook?
"""

User = get_user_model()


def _get_or_create_system_user() -> User:
    user, created = User.objects.get_or_create(
        email="llm-live@system.local",
        defaults={"is_active": True},
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user


class Command(BaseCommand):
    help = "Run live LLM queries and prompt chains, persisting results to the DB."

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="action", required=True)

        # --- chat subcommand ---
        chat_p = sub.add_parser("chat", help="Single blocking chat round-trip.")
        chat_q = chat_p.add_mutually_exclusive_group(required=True)
        chat_q.add_argument("query", nargs="?", help="Free-form query string.")
        chat_q.add_argument(
            "--example",
            type=int,
            choices=range(len(EXAMPLE_QUERIES)),
            metavar=f"0-{len(EXAMPLE_QUERIES) - 1}",
            help="Run a built-in example query by index.",
        )
        chat_p.add_argument("--model", default=None, help="Ollama model override.")

        # --- chain subcommand ---
        chain_p = sub.add_parser("chain", help="Run the full 4-step prompt chain.")
        chain_q = chain_p.add_mutually_exclusive_group(required=True)
        chain_q.add_argument("query", nargs="?", help="Free-form query string.")
        chain_q.add_argument(
            "--example",
            type=int,
            choices=range(len(EXAMPLE_QUERIES)),
            metavar=f"0-{len(EXAMPLE_QUERIES) - 1}",
            help="Run a built-in example query by index.",
        )
        chain_q.add_argument(
            "--all-examples",
            action="store_true",
            help="Run all 5 example queries sequentially.",
        )
        chain_p.add_argument("--model", default=None, help="Ollama model override.")

        # --- route subcommand ---
        route_p = sub.add_parser(
            "route", help="Classify a query then dispatch to the chosen route."
        )
        route_q = route_p.add_mutually_exclusive_group(required=True)
        route_q.add_argument("query", nargs="?", help="Free-form query string.")
        route_q.add_argument(
            "--example",
            type=int,
            choices=range(len(EXAMPLE_QUERIES)),
            metavar=f"0-{len(EXAMPLE_QUERIES) - 1}",
            help="Run a built-in example query by index.",
        )
        route_q.add_argument(
            "--all-examples",
            action="store_true",
            help="Run all 5 example queries sequentially.",
        )
        route_p.add_argument("--model", default=None, help="Ollama model override.")

        # --- parallel subcommand ---
        parallel_p = sub.add_parser(
            "parallel", help="Observable parallelization: sectioning or N-way voting."
        )
        parallel_q = parallel_p.add_mutually_exclusive_group(required=True)
        parallel_q.add_argument("query", nargs="?", help="Free-form query string.")
        parallel_q.add_argument(
            "--example",
            type=int,
            choices=range(len(EXAMPLE_QUERIES)),
            metavar=f"0-{len(EXAMPLE_QUERIES) - 1}",
            help="Run a built-in example query by index.",
        )
        parallel_q.add_argument(
            "--all-examples",
            action="store_true",
            help="Run all 5 example queries sequentially.",
        )
        parallel_p.add_argument(
            "--strategy",
            choices=("sectioning", "voting"),
            default="sectioning",
            help="Fan-out strategy (default: sectioning).",
        )
        parallel_p.add_argument(
            "--n",
            type=int,
            default=3,
            choices=range(2, 6),
            metavar="2-5",
            help="Number of votes (voting strategy only; default 3).",
        )
        parallel_p.add_argument("--model", default=None, help="Ollama model override.")

        # --- chatagent subcommand ---
        chatagent_p = sub.add_parser(
            "chatagent",
            help="Chat agent: one conversational turn in a session (issue #8).",
        )
        chatagent_p.add_argument("query", nargs="?", help="The user's message.")
        chatagent_p.add_argument(
            "--session",
            default=None,
            help="Continue an existing ChatSession by id. Omitted, a new one is created.",
        )
        chatagent_p.add_argument(
            "--smoke",
            action="store_true",
            help="Run the scripted multi-turn conversation instead of a single message.",
        )
        chatagent_p.add_argument(
            "--max-steps", type=int, default=None, help="Tool calls allowed in this turn."
        )
        chatagent_p.add_argument("--model", default=None, help="Ollama model override.")

        # --- react subcommand ---
        react_p = sub.add_parser(
            "react", help="ReAct agent: bounded Thought -> Tool -> Observation loop."
        )
        react_q = react_p.add_mutually_exclusive_group(required=True)
        react_q.add_argument("query", nargs="?", help="Free-form query string.")
        react_q.add_argument(
            "--example",
            type=int,
            choices=range(len(EXAMPLE_QUERIES)),
            metavar=f"0-{len(EXAMPLE_QUERIES) - 1}",
            help="Run a built-in example query by index.",
        )
        react_q.add_argument(
            "--all-examples",
            action="store_true",
            help="Run all 5 example queries sequentially.",
        )
        react_p.add_argument(
            "--max-steps",
            type=int,
            default=6,
            choices=range(1, 11),
            metavar="1-10",
            help="Hard cap on Thought->Tool->Observation iterations (default 6).",
        )
        react_p.add_argument("--model", default=None, help="Ollama model override.")

        # --- evaluate subcommand ---
        eval_p = sub.add_parser(
            "evaluate",
            help="Evaluator-Optimizer agent: generate -> evaluate -> revise loop.",
        )
        eval_q = eval_p.add_mutually_exclusive_group(required=True)
        eval_q.add_argument("query", nargs="?", help="Free-form query string.")
        eval_q.add_argument(
            "--example",
            type=int,
            choices=range(len(EXAMPLE_QUERIES)),
            metavar=f"0-{len(EXAMPLE_QUERIES) - 1}",
            help="Run a built-in example query by index.",
        )
        eval_q.add_argument(
            "--all-examples",
            action="store_true",
            help="Run all 5 example queries sequentially.",
        )
        eval_p.add_argument(
            "--max-iterations",
            type=int,
            default=3,
            choices=range(1, 11),
            metavar="1-10",
            help="Hard cap on generate->evaluate->revise iterations (default 3).",
        )
        eval_p.add_argument(
            "--threshold",
            type=int,
            default=8,
            choices=range(0, 11),
            metavar="0-10",
            help="Evaluator score that ends the loop (default 8).",
        )
        eval_p.add_argument("--model", default=None, help="Ollama model override.")

        # --- plan subcommand ---
        plan_p = sub.add_parser(
            "plan",
            help="Plan-and-Execute agent: plan upfront -> execute each step -> optional replan.",
        )
        plan_q = plan_p.add_mutually_exclusive_group(required=True)
        plan_q.add_argument("query", nargs="?", help="Free-form query string.")
        plan_q.add_argument(
            "--example",
            type=int,
            choices=range(len(EXAMPLE_QUERIES)),
            metavar=f"0-{len(EXAMPLE_QUERIES) - 1}",
            help="Run a built-in example query by index.",
        )
        plan_q.add_argument(
            "--all-examples",
            action="store_true",
            help="Run all 5 example queries sequentially.",
        )
        plan_p.add_argument(
            "--max-steps",
            type=int,
            default=6,
            choices=range(1, 11),
            metavar="1-10",
            help="Hard cap on the number of plan steps (default 6).",
        )
        plan_p.add_argument(
            "--no-replan",
            action="store_true",
            help="Disable replanning when a step's tool lookup diverges.",
        )
        plan_p.add_argument("--model", default=None, help="Ollama model override.")

        # --- orchestrate subcommand ---
        orch_p = sub.add_parser(
            "orchestrate",
            help="Orchestrator-Workers agent: decompose -> fan out workers -> synthesise.",
        )
        orch_q = orch_p.add_mutually_exclusive_group(required=True)
        orch_q.add_argument("query", nargs="?", help="Free-form query string.")
        orch_q.add_argument(
            "--example",
            type=int,
            choices=range(len(EXAMPLE_QUERIES)),
            metavar=f"0-{len(EXAMPLE_QUERIES) - 1}",
            help="Run a built-in example query by index.",
        )
        orch_q.add_argument(
            "--all-examples",
            action="store_true",
            help="Run all 5 example queries sequentially.",
        )
        orch_p.add_argument(
            "--max-workers",
            type=int,
            default=4,
            choices=range(2, 9),
            metavar="2-8",
            help="Hard cap on the number of decomposed worker subtasks (default 4).",
        )
        orch_p.add_argument("--model", default=None, help="Ollama model override.")

        # --- multiagent subcommand ---
        ma_p = sub.add_parser(
            "multiagent",
            help="Multi-Agent (sequential): supervisor routes a role-specialised roster.",
        )
        ma_q = ma_p.add_mutually_exclusive_group(required=True)
        ma_q.add_argument("query", nargs="?", help="Free-form query string.")
        ma_q.add_argument(
            "--example",
            type=int,
            choices=range(len(EXAMPLE_QUERIES)),
            metavar=f"0-{len(EXAMPLE_QUERIES) - 1}",
            help="Run a built-in example query by index.",
        )
        ma_q.add_argument(
            "--all-examples",
            action="store_true",
            help="Run all 5 example queries sequentially.",
        )
        ma_p.add_argument(
            "--max-tools",
            type=int,
            default=4,
            choices=range(1, 11),
            metavar="1-10",
            help="Hard cap on the Researcher's read-only tool calls (default 4).",
        )
        ma_p.add_argument("--model", default=None, help="Ollama model override.")

        # --- dag subcommand ---
        dag_p = sub.add_parser(
            "dag",
            help="Multi-Agent (parallel/DAG): decompose into a graph -> run waves -> synthesise.",
        )
        dag_q = dag_p.add_mutually_exclusive_group(required=True)
        dag_q.add_argument("query", nargs="?", help="Free-form query string.")
        dag_q.add_argument(
            "--example",
            type=int,
            choices=range(len(EXAMPLE_QUERIES)),
            metavar=f"0-{len(EXAMPLE_QUERIES) - 1}",
            help="Run a built-in example query by index.",
        )
        dag_q.add_argument(
            "--all-examples",
            action="store_true",
            help="Run all 5 example queries sequentially.",
        )
        dag_p.add_argument(
            "--max-nodes",
            type=int,
            default=6,
            choices=range(2, 13),
            metavar="2-12",
            help="Hard cap on the number of decomposed graph nodes (default 6).",
        )
        dag_p.add_argument("--model", default=None, help="Ollama model override.")

        # --- autonomous subcommand ---
        auto_p = sub.add_parser(
            "autonomous",
            help="Autonomous / Long-Horizon: goal-driven bounded loop -> reflect, act, replan.",
        )
        auto_q = auto_p.add_mutually_exclusive_group(required=True)
        auto_q.add_argument("query", nargs="?", help="Free-form goal string.")
        auto_q.add_argument(
            "--example",
            type=int,
            choices=range(len(EXAMPLE_QUERIES)),
            metavar=f"0-{len(EXAMPLE_QUERIES) - 1}",
            help="Run a built-in example query by index.",
        )
        auto_q.add_argument(
            "--all-examples",
            action="store_true",
            help="Run all 5 example queries sequentially.",
        )
        auto_p.add_argument(
            "--max-cycles",
            type=int,
            default=8,
            choices=range(1, 21),
            metavar="1-20",
            help="Hard cap on controller cycles before forced synthesis (default 8).",
        )
        auto_p.add_argument(
            "--max-subagents",
            type=int,
            default=3,
            choices=range(0, 7),
            metavar="0-6",
            help="Hard cap on spawned sub-agents (default 3).",
        )
        auto_p.add_argument("--model", default=None, help="Ollama model override.")

    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        action = options["action"]
        if action == "chat":
            self._run_chat(options)
        elif action == "chain":
            self._run_chain(options)
        elif action == "route":
            self._run_route(options)
        elif action == "parallel":
            self._run_parallel(options)
        elif action == "chatagent":
            self._run_chat_agent(options)
        elif action == "react":
            self._run_react(options)
        elif action == "evaluate":
            self._run_eval_opt(options)
        elif action == "plan":
            self._run_plan(options)
        elif action == "orchestrate":
            self._run_orchestrate(options)
        elif action == "multiagent":
            self._run_multiagent(options)
        elif action == "dag":
            self._run_dag(options)
        elif action == "autonomous":
            self._run_autonomous(options)

    # ------------------------------------------------------------------
    # shared helpers
    # ------------------------------------------------------------------

    def _resolve_queries(self, options) -> list[str]:
        if options.get("all_examples"):
            return EXAMPLE_QUERIES
        if options.get("example") is not None:
            return [EXAMPLE_QUERIES[options["example"]]]
        return [options["query"]]

    # ------------------------------------------------------------------
    # chat
    # ------------------------------------------------------------------

    def _run_chat(self, options):
        query = options.get("query") or EXAMPLE_QUERIES[options["example"]]
        model = options.get("model")

        self.stdout.write(self.style.HTTP_INFO(f"\nQuery: {query}"))
        self.stdout.write(self.style.HTTP_INFO(f"Model: {model or 'default'}"))
        self.stdout.write("-" * 60)

        try:
            result = services.chat(
                [{"role": "user", "content": query}],
                model=model,
            )
        except services.OllamaServiceError as exc:
            raise CommandError(f"Ollama error: {exc}") from exc

        self.stdout.write(result)
        self.stdout.write(self.style.SUCCESS("\nDone."))

    # ------------------------------------------------------------------
    # chain
    # ------------------------------------------------------------------

    def _run_chain(self, options):
        queries: list[str]
        if options.get("all_examples"):
            queries = EXAMPLE_QUERIES
        elif options.get("example") is not None:
            queries = [EXAMPLE_QUERIES[options["example"]]]
        else:
            queries = [options["query"]]

        model = options.get("model") or ""
        user = _get_or_create_system_user()

        for query in queries:
            self._run_single_chain(query, model, user)

    def _run_single_chain(self, query: str, model: str, user: User) -> None:
        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write(self.style.HTTP_INFO(f"Query : {query}"))
        self.stdout.write(self.style.HTTP_INFO(f"Model : {model or 'default'}"))
        self.stdout.write("=" * 60)

        run = create_chain_run(user=user, query=query, model=model)
        self.stdout.write(f"Run ID: {run.pk}\n")

        for raw_event in run_chain(run, model=model or None):
            line = raw_event.strip()
            if not line.startswith("data: "):
                continue
            event = json.loads(line[len("data: ") :])
            step_id = event["step_id"]
            status = event["status"]

            if step_id == "__init__":
                continue

            if step_id == "__done__":
                run.refresh_from_db()
                if run.status == "done":
                    self.stdout.write(self.style.SUCCESS(f"\nChain complete  (run_id={run.pk})"))
                else:
                    self.stdout.write(self.style.ERROR(f"\nChain failed    (run_id={run.pk})"))
                continue

            if status == "running":
                self.stdout.write(f"  [{step_id}] running...")
            elif status == "done":
                output = event.get("output") or ""
                preview = output[:200].replace("\n", " ")
                ellipsis = "..." if len(output) > 200 else ""
                self.stdout.write(self.style.SUCCESS(f"  [{step_id}] done — {preview}{ellipsis}"))
            elif status == "error":
                self.stdout.write(self.style.ERROR(f"  [{step_id}] error — {event.get('error')}"))

    # ------------------------------------------------------------------
    # route
    # ------------------------------------------------------------------

    def _run_route(self, options):
        queries: list[str]
        if options.get("all_examples"):
            queries = EXAMPLE_QUERIES
        elif options.get("example") is not None:
            queries = [EXAMPLE_QUERIES[options["example"]]]
        else:
            queries = [options["query"]]

        model = options.get("model") or ""
        user = _get_or_create_system_user()

        for query in queries:
            self._run_single_route(query, model, user)

    def _run_single_route(self, query: str, model: str, user: User) -> None:
        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write(self.style.HTTP_INFO(f"Query : {query}"))
        self.stdout.write(self.style.HTTP_INFO(f"Model : {model or 'default'}"))
        self.stdout.write("=" * 60)

        run = create_route_run(user=user, query=query, model=model)
        self.stdout.write(f"Run ID: {run.pk}\n")

        for raw_event in run_route(run, model=model):
            line = raw_event.strip()
            if not line.startswith("data: "):
                continue
            event = json.loads(line[len("data: ") :])

            # Nested chain events (deep_research) carry step_id/status.
            if "step_id" in event:
                self._print_chain_event(event)
                continue

            kind = event.get("event")
            if kind == "classified":
                tickers = ", ".join(event.get("tickers") or []) or "-"
                self.stdout.write(
                    self.style.WARNING(
                        f"  route={event['route']}  complexity={event.get('complexity')}"
                    )
                )
                self.stdout.write(f"  reason : {event.get('reason')}")
                self.stdout.write(f"  tickers: {tickers}")
                self.stdout.write("-" * 60)
            elif kind == "result":
                output = event.get("output") or ""
                self.stdout.write("")
                self.stdout.write(self.style.SUCCESS(f"Result ({event['route']}):"))
                self.stdout.write(output)
                self.stdout.write(self.style.SUCCESS(f"\nRoute complete  (run_id={run.pk})"))
            elif kind == "error":
                self.stdout.write(self.style.ERROR(f"  error — {event.get('error')}"))

    def _print_chain_event(self, event: dict) -> None:
        step_id = event["step_id"]
        status = event["status"]
        if step_id in ("__init__", "__done__"):
            return
        if status == "running":
            self.stdout.write(f"  [chain:{step_id}] running...")
        elif status == "done":
            output = event.get("output") or ""
            preview = output[:200].replace("\n", " ")
            ellipsis = "..." if len(output) > 200 else ""
            self.stdout.write(self.style.SUCCESS(f"  [chain:{step_id}] done — {preview}{ellipsis}"))
        elif status == "error":
            self.stdout.write(self.style.ERROR(f"  [chain:{step_id}] error — {event.get('error')}"))

    # ------------------------------------------------------------------
    # parallel
    # ------------------------------------------------------------------

    def _run_parallel(self, options):
        queries = self._resolve_queries(options)
        model = options.get("model") or ""
        strategy = options["strategy"]
        n = options["n"]
        user = _get_or_create_system_user()

        for query in queries:
            self._run_single_parallel(query, model, strategy, n, user)

    def _run_single_parallel(
        self, query: str, model: str, strategy: str, n: int, user: User
    ) -> None:
        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write(self.style.HTTP_INFO(f"Query   : {query}"))
        self.stdout.write(self.style.HTTP_INFO(f"Model   : {model or 'default'}"))
        suffix = f" (n={n})" if strategy == "voting" else ""
        self.stdout.write(self.style.HTTP_INFO(f"Strategy: {strategy}{suffix}"))
        self.stdout.write("=" * 60)

        run = create_parallel_run(user=user, query=query, model=model, strategy=strategy, n=n)
        self.stdout.write(f"Run ID: {run.pk}\n")

        for raw_event in run_parallel(run, model=model):
            line = raw_event.strip()
            if not line.startswith("data: "):
                continue
            event = json.loads(line[len("data: ") :])
            kind = event.get("event")

            if kind == "started":
                labels = ", ".join(t["label"] for t in event.get("tasks", []))
                self.stdout.write(self.style.WARNING(f"  fan-out: {labels}"))
                self.stdout.write("-" * 60)
            elif kind == "task":
                vote = f" vote={event['vote']}" if event.get("vote") else ""
                body = event.get("output") or event.get("error") or ""
                preview = body[:160].replace("\n", " ")
                ellipsis = "..." if len(body) > 160 else ""
                style = self.style.ERROR if event["status"] == "error" else self.style.SUCCESS
                self.stdout.write(style(f"  [{event['label']}]{vote} — {preview}{ellipsis}"))
            elif kind == "result":
                tally = event.get("tally")
                if tally:
                    self.stdout.write(
                        self.style.WARNING(
                            "  tally: " + ", ".join(f"{k}={v}" for k, v in tally.items())
                        )
                    )
                self.stdout.write("")
                self.stdout.write(self.style.SUCCESS(f"Result ({event['strategy']}):"))
                self.stdout.write(event.get("output") or "")
                self.stdout.write(self.style.SUCCESS(f"\nParallel complete  (run_id={run.pk})"))
            elif kind == "error":
                self.stdout.write(self.style.ERROR(f"  error — {event.get('error')}"))

    # ------------------------------------------------------------------
    # chatagent (issue #8)
    # ------------------------------------------------------------------

    #: The scripted smoke conversation. Each turn is chosen to prove ONE thing the unit
    #: tests cannot: that the model really declines to call a tool for small talk, that it
    #: really reaches our database for a figure, and that a pronoun really resolves from
    #: the transcript rather than from the model guessing.
    SMOKE_TURNS = (
        ("no tool expected", "Hi! In one sentence, what can you help me with?"),
        ("tool expected", "What is AAPL's trailing P/E right now?"),
        ("needs the transcript", "And how does that compare to its forward P/E?"),
    )

    def _run_chat_agent(self, options):
        from apps.llm_analysis.config import get_llm_config
        from apps.llm_analysis.models import ChatSession

        model = options.get("model") or ""
        max_steps = options.get("max_steps") or get_llm_config().chat_max_steps
        user = _get_or_create_system_user()

        if options.get("session"):
            session = ChatSession.objects.get(pk=options["session"], user=user)
        else:
            session = ChatSession.objects.create(user=user)

        self._print_chat_budget()

        if options.get("smoke"):
            for label, message in self.SMOKE_TURNS:
                self._run_chat_turn(session, message, model, max_steps, label=label)
            self._print_chat_transcript(session)
            return

        if not options.get("query"):
            self.stdout.write(self.style.ERROR("Give a message, or pass --smoke."))
            return
        self._run_chat_turn(session, options["query"], model, max_steps)

    def _print_chat_budget(self) -> None:
        """The numbers that decide whether a long session degrades. Printed because the one
        defect a live run caught here was a budget arithmetic error, not a logic error."""
        from apps.llm_analysis._context import RESPONSE_RESERVE, estimate_tokens
        from apps.llm_analysis.chat_agent import TURN_RESERVE, _history_budget, _system_prompt
        from apps.llm_analysis.config import get_llm_config

        pad = int(get_llm_config().num_ctx * (1 - RESPONSE_RESERVE))
        system = estimate_tokens(_system_prompt())
        history = _history_budget()
        self.stdout.write(
            self.style.HTTP_INFO(
                f"budget: pad={pad}  system={system}  history={history}  "
                f"turn_reserve={TURN_RESERVE}"
            )
        )

    def _run_chat_turn(
        self, session, message: str, model: str, max_steps: int, label: str = ""
    ) -> None:
        self.stdout.write("")
        self.stdout.write("=" * 60)
        if label:
            self.stdout.write(self.style.WARNING(f"[{label}]"))
        self.stdout.write(self.style.HTTP_INFO(f"You      : {message}"))
        self.stdout.write("=" * 60)

        run = create_chat_run(
            user=session.user, query=message, model=model, max_steps=max_steps, session=session
        )

        streaming = False
        for raw_event in run_chat(run, model=model):
            line = raw_event.strip()
            if not line.startswith("data: "):
                continue
            event = json.loads(line[len("data: ") :])
            kind = event.get("event")

            if kind == "started":
                self.stdout.write(
                    f"  history replayed: {event.get('history')}  "
                    f"compacted: {event.get('compacted')}"
                )
            elif kind == "step":
                self._print_chat_step(event)
            elif kind == "delta":
                # Written without a newline so the reply appears as it is produced - the
                # point of phase 5, and invisible if the frames are only summarised.
                if not streaming:
                    self.stdout.write("")
                    self.stdout.write(self.style.SUCCESS("Assistant:"), ending="")
                    streaming = True
                self.stdout.write(event.get("text") or "", ending="")
                self.stdout.flush()
            elif kind == "result":
                if streaming:
                    self.stdout.write("")
                else:
                    self.stdout.write("")
                    self.stdout.write(self.style.SUCCESS("Assistant:"))
                    self.stdout.write(event.get("output") or "")
            elif kind == "error":
                self.stdout.write(self.style.ERROR(f"  error - {event.get('error')}"))

        run.refresh_from_db()
        self.stdout.write(
            self.style.SUCCESS(
                f"\n  turn={run.meta.get('turn')}  tools={run.meta.get('tools_used')}  "
                f"session={session.id}"
            )
        )

    def _print_chat_step(self, event: dict) -> None:
        order = event.get("order")
        thought = (event.get("thought") or "").replace("\n", " ")
        if event.get("status") == "error":
            self.stdout.write(self.style.ERROR(f"  [{order}] unparseable - {event.get('error')}"))
            return
        if event.get("is_answer"):
            # When the reply streamed, its text is already on screen and the step adds
            # nothing but a stray line in the middle of it.
            if not thought:
                return
            self.stdout.write(self.style.SUCCESS(f"  [{order}] answering - {thought[:140]}"))
            return
        # `tool_args`, not `args` - the serializer name IS the wire name since issue #6.
        args = json.dumps(event.get("tool_args") or {})
        observation = (event.get("observation") or "")[:160].replace("\n", " ")
        self.stdout.write(f"  [{order}] thought: {thought[:140]}")
        self.stdout.write(self.style.SUCCESS(f"        action : {event.get('tool')}({args})"))
        self.stdout.write(f"        observ.: {observation}")

    def _print_chat_transcript(self, session) -> None:
        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write(self.style.HTTP_INFO(f"Transcript (session {session.id})"))
        session.refresh_from_db()
        if session.summary:
            self.stdout.write(f"  [summary, {session.summarised_upto} turns folded]")
            self.stdout.write(f"    {session.summary[:300]}")
        for turn in session.turns.order_by("created_at"):
            self.stdout.write(f"  {turn.meta.get('turn')}. you: {turn.query[:70]}")
            self.stdout.write(f"     ai : {turn.output[:70]}")

    # ------------------------------------------------------------------
    # react
    # ------------------------------------------------------------------

    def _run_react(self, options):
        queries = self._resolve_queries(options)
        model = options.get("model") or ""
        max_steps = options["max_steps"]
        user = _get_or_create_system_user()

        for query in queries:
            self._run_single_react(query, model, max_steps, user)

    def _run_single_react(self, query: str, model: str, max_steps: int, user: User) -> None:
        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write(self.style.HTTP_INFO(f"Query    : {query}"))
        self.stdout.write(self.style.HTTP_INFO(f"Model    : {model or 'default'}"))
        self.stdout.write(self.style.HTTP_INFO(f"Max steps: {max_steps}"))
        self.stdout.write("=" * 60)

        run = create_react_run(user=user, query=query, model=model, max_steps=max_steps)
        self.stdout.write(f"Run ID: {run.pk}\n")

        for raw_event in run_react(run, model=model):
            line = raw_event.strip()
            if not line.startswith("data: "):
                continue
            event = json.loads(line[len("data: ") :])
            kind = event.get("event")

            if kind == "started":
                tools = ", ".join(event.get("tools", []))
                self.stdout.write(self.style.WARNING(f"  tools: {tools}"))
                self.stdout.write("-" * 60)
            elif kind == "step":
                self._print_react_step(event)
            elif kind == "result":
                self.stdout.write("")
                self.stdout.write(self.style.SUCCESS("Answer:"))
                self.stdout.write(event.get("output") or "")
                self.stdout.write(self.style.SUCCESS(f"\nReAct complete  (run_id={run.pk})"))
            elif kind == "error":
                self.stdout.write(self.style.ERROR(f"  error — {event.get('error')}"))

    def _print_react_step(self, event: dict) -> None:
        order = event.get("order")
        thought = (event.get("thought") or "").replace("\n", " ")
        if event.get("status") == "error":
            self.stdout.write(self.style.ERROR(f"  [{order}] unparseable — {event.get('error')}"))
            return
        if event.get("answer"):
            self.stdout.write(self.style.SUCCESS(f"  [{order}] answer — thought: {thought[:160]}"))
            return
        tool = event.get("tool")
        args = json.dumps(event.get("tool_args") or {})
        observation = (event.get("observation") or "")[:160].replace("\n", " ")
        self.stdout.write(f"  [{order}] thought: {thought[:160]}")
        self.stdout.write(self.style.SUCCESS(f"        action : {tool}({args})"))
        self.stdout.write(f"        observ.: {observation}")

    # ------------------------------------------------------------------
    # evaluate (Evaluator-Optimizer)
    # ------------------------------------------------------------------

    def _run_eval_opt(self, options):
        queries = self._resolve_queries(options)
        model = options.get("model") or ""
        max_iterations = options["max_iterations"]
        threshold = options["threshold"]
        user = _get_or_create_system_user()

        for query in queries:
            self._run_single_eval_opt(query, model, max_iterations, threshold, user)

    def _run_single_eval_opt(
        self, query: str, model: str, max_iterations: int, threshold: int, user: User
    ) -> None:
        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write(self.style.HTTP_INFO(f"Query     : {query}"))
        self.stdout.write(self.style.HTTP_INFO(f"Model     : {model or 'default'}"))
        self.stdout.write(self.style.HTTP_INFO(f"Max iters : {max_iterations}"))
        self.stdout.write(self.style.HTTP_INFO(f"Threshold : {threshold}"))
        self.stdout.write("=" * 60)

        run = create_eo_run(
            user=user,
            query=query,
            model=model,
            max_iterations=max_iterations,
            threshold=threshold,
        )
        self.stdout.write(f"Run ID: {run.pk}\n")

        for raw_event in run_eval_opt(run, model=model):
            line = raw_event.strip()
            if not line.startswith("data: "):
                continue
            event = json.loads(line[len("data: ") :])
            kind = event.get("event")

            if kind == "started":
                self.stdout.write(
                    self.style.WARNING(
                        f"  max_iterations={event['max_iterations']}  "
                        f"threshold={event['threshold']}"
                    )
                )
                self.stdout.write("-" * 60)
            elif kind == "draft":
                draft = (event.get("draft") or "")[:200].replace("\n", " ")
                ellipsis = "..." if len(event.get("draft") or "") > 200 else ""
                self.stdout.write(self.style.SUCCESS(f"  [draft] {draft}{ellipsis}"))
            elif kind == "iteration":
                self._print_eval_iteration(event)
            elif kind == "result":
                self.stdout.write("")
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Best answer (score={event.get('best_score')}, "
                        f"iterations={event.get('iterations')}):"
                    )
                )
                self.stdout.write(event.get("output") or "")
                self.stdout.write(
                    self.style.SUCCESS(f"\nEvaluator-Optimizer complete  (run_id={run.pk})")
                )
            elif kind == "error":
                self.stdout.write(self.style.ERROR(f"  error — {event.get('error')}"))

    def _print_eval_iteration(self, event: dict) -> None:
        order = event.get("order")
        score = event.get("score")
        passed = event.get("passed")
        if event.get("status") == "error":
            self.stdout.write(
                self.style.ERROR(f"  [iter {order}] score={score} (unparseable verdict)")
            )
            return
        feedback = (event.get("feedback") or "").replace("\n", " ")[:160]
        verdict = "PASS" if passed else "revise"
        style = self.style.SUCCESS if passed else self.style.WARNING
        self.stdout.write(style(f"  [iter {order}] score={score}  {verdict}"))
        if feedback:
            self.stdout.write(f"        feedback: {feedback}")

    # ------------------------------------------------------------------
    # plan (Plan-and-Execute)
    # ------------------------------------------------------------------

    def _run_plan(self, options):
        queries = self._resolve_queries(options)
        model = options.get("model") or ""
        max_steps = options["max_steps"]
        allow_replan = not options["no_replan"]
        user = _get_or_create_system_user()

        for query in queries:
            self._run_single_plan(query, model, max_steps, allow_replan, user)

    def _run_single_plan(
        self, query: str, model: str, max_steps: int, allow_replan: bool, user: User
    ) -> None:
        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write(self.style.HTTP_INFO(f"Query    : {query}"))
        self.stdout.write(self.style.HTTP_INFO(f"Model    : {model or 'default'}"))
        self.stdout.write(self.style.HTTP_INFO(f"Max steps: {max_steps}"))
        self.stdout.write(self.style.HTTP_INFO(f"Replan   : {'on' if allow_replan else 'off'}"))
        self.stdout.write("=" * 60)

        run = create_plan_run(
            user=user,
            query=query,
            model=model,
            max_steps=max_steps,
            allow_replan=allow_replan,
        )
        self.stdout.write(f"Run ID: {run.pk}\n")

        for raw_event in run_plan(run, model=model):
            line = raw_event.strip()
            if not line.startswith("data: "):
                continue
            event = json.loads(line[len("data: ") :])
            kind = event.get("event")

            if kind == "started":
                self.stdout.write(
                    self.style.WARNING(
                        f"  max_steps={event['max_steps']}  allow_replan={event['allow_replan']}"
                    )
                )
                self.stdout.write("-" * 60)
            elif kind == "plan":
                self.stdout.write(self.style.WARNING("  Plan:"))
                for i, step in enumerate(event.get("steps", [])):
                    tool = step.get("tool") or "reason"
                    self.stdout.write(f"    {i + 1}. {step.get('task')}  [{tool}]")
                self.stdout.write("-" * 60)
            elif kind == "step":
                self._print_plan_step(event)
            elif kind == "replan":
                self.stdout.write(self.style.WARNING(f"  >> REPLAN: {event.get('reason')}"))
                for i, step in enumerate(event.get("steps", [])):
                    tool = step.get("tool") or "reason"
                    self.stdout.write(f"     {i + 1}. {step.get('task')}  [{tool}]")
            elif kind == "result":
                self.stdout.write("")
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Answer (steps={event.get('steps')}, replans={event.get('replans')}):"
                    )
                )
                self.stdout.write(event.get("output") or "")
                self.stdout.write(
                    self.style.SUCCESS(f"\nPlan-and-Execute complete  (run_id={run.pk})")
                )
            elif kind == "error":
                self.stdout.write(self.style.ERROR(f"  error — {event.get('error')}"))

    def _print_plan_step(self, event: dict) -> None:
        order = event.get("order")
        task = (event.get("task") or "").replace("\n", " ")
        self.stdout.write(f"  [{order}] task   : {task[:160]}")
        tool = event.get("tool")
        if tool:
            args = json.dumps(event.get("tool_args") or {})
            observation = (event.get("observation") or "")[:160].replace("\n", " ")
            self.stdout.write(self.style.SUCCESS(f"        tool   : {tool}({args})"))
            self.stdout.write(f"        observ.: {observation}")
        result = (event.get("result") or "").replace("\n", " ")
        self.stdout.write(f"        result : {result[:200]}")

    # ------------------------------------------------------------------
    # orchestrate (Orchestrator-Workers)
    # ------------------------------------------------------------------

    def _run_orchestrate(self, options):
        queries = self._resolve_queries(options)
        model = options.get("model") or ""
        max_workers = options["max_workers"]
        user = _get_or_create_system_user()

        for query in queries:
            self._run_single_orchestrate(query, model, max_workers, user)

    def _run_single_orchestrate(self, query: str, model: str, max_workers: int, user: User) -> None:
        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write(self.style.HTTP_INFO(f"Query      : {query}"))
        self.stdout.write(self.style.HTTP_INFO(f"Model      : {model or 'default'}"))
        self.stdout.write(self.style.HTTP_INFO(f"Max workers: {max_workers}"))
        self.stdout.write("=" * 60)

        run = create_orchestrator_run(user=user, query=query, model=model, max_workers=max_workers)
        self.stdout.write(f"Run ID: {run.pk}\n")

        for raw_event in run_orchestrator(run, model=model):
            line = raw_event.strip()
            if not line.startswith("data: "):
                continue
            event = json.loads(line[len("data: ") :])
            kind = event.get("event")

            if kind == "started":
                self.stdout.write(self.style.WARNING(f"  max_workers={event['max_workers']}"))
                self.stdout.write("-" * 60)
            elif kind == "plan":
                self.stdout.write(self.style.WARNING("  Decomposition:"))
                for i, st in enumerate(event.get("subtasks", [])):
                    tool = st.get("tool") or "reason"
                    self.stdout.write(
                        f"    {i + 1}. {st.get('task')}  [{st.get('focus')}] [{tool}]"
                    )
                self.stdout.write("-" * 60)
            elif kind == "worker":
                self._print_orchestrate_worker(event)
            elif kind == "result":
                self.stdout.write("")
                self.stdout.write(self.style.SUCCESS(f"Answer (workers={event.get('workers')}):"))
                self.stdout.write(event.get("output") or "")
                self.stdout.write(
                    self.style.SUCCESS(f"\nOrchestrator-Workers complete  (run_id={run.pk})")
                )
            elif kind == "error":
                self.stdout.write(self.style.ERROR(f"  error — {event.get('error')}"))

    def _print_orchestrate_worker(self, event: dict) -> None:
        order = event.get("order")
        label = event.get("label")
        task = (event.get("task") or "").replace("\n", " ")
        style = self.style.ERROR if event.get("status") == "error" else self.style.SUCCESS
        self.stdout.write(f"  [{order}] {label}: {task[:140]}")
        tool = event.get("tool")
        if tool:
            args = json.dumps(event.get("tool_args") or {})
            observation = (event.get("observation") or "")[:160].replace("\n", " ")
            self.stdout.write(self.style.SUCCESS(f"        tool   : {tool}({args})"))
            self.stdout.write(f"        observ.: {observation}")
        body = event.get("output") or event.get("error") or ""
        self.stdout.write(style(f"        output : {body[:200].replace(chr(10), ' ')}"))

    # ------------------------------------------------------------------
    # multiagent (Multi-Agent Sequential/Hierarchical)
    # ------------------------------------------------------------------

    def _run_multiagent(self, options):
        queries = self._resolve_queries(options)
        model = options.get("model") or ""
        max_tools = options["max_tools"]
        user = _get_or_create_system_user()

        for query in queries:
            self._run_single_multiagent(query, model, max_tools, user)

    def _run_single_multiagent(self, query: str, model: str, max_tools: int, user: User) -> None:
        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write(self.style.HTTP_INFO(f"Query    : {query}"))
        self.stdout.write(self.style.HTTP_INFO(f"Model    : {model or 'default'}"))
        self.stdout.write(self.style.HTTP_INFO(f"Max tools: {max_tools}"))
        self.stdout.write("=" * 60)

        run = create_multiagent_run(user=user, query=query, model=model, max_tools=max_tools)
        self.stdout.write(f"Run ID: {run.pk}\n")

        for raw_event in run_multiagent(run, model=model):
            line = raw_event.strip()
            if not line.startswith("data: "):
                continue
            event = json.loads(line[len("data: ") :])
            kind = event.get("event")

            if kind == "route":
                agents = " -> ".join(event.get("agents") or [])
                self.stdout.write(self.style.WARNING(f"  roster : {agents}"))
                if event.get("reason"):
                    self.stdout.write(f"  reason : {event['reason']}")
                self.stdout.write("-" * 60)
            elif kind == "step":
                self._print_multiagent_step(event)
            elif kind == "result":
                self.stdout.write("")
                self.stdout.write(self.style.SUCCESS(f"Answer (stages={event.get('agents')}):"))
                self.stdout.write(event.get("output") or "")
                self.stdout.write(self.style.SUCCESS(f"\nMulti-Agent complete  (run_id={run.pk})"))
            elif kind == "error":
                self.stdout.write(self.style.ERROR(f"  error — {event.get('error')}"))

    def _print_multiagent_step(self, event: dict) -> None:
        label = event.get("label")
        style = self.style.ERROR if event.get("status") == "error" else self.style.SUCCESS
        self.stdout.write(style(f"  [{event.get('order')}] {label}"))
        for call in event.get("tool_calls") or []:
            args = json.dumps(call.get("args") or {})
            observation = (call.get("observation") or "")[:140].replace("\n", " ")
            self.stdout.write(self.style.SUCCESS(f"        tool   : {call.get('tool')}({args})"))
            self.stdout.write(f"        observ.: {observation}")
        if event.get("status") == "error":
            self.stdout.write(self.style.ERROR(f"        error  : {event.get('error')}"))
        else:
            body = (event.get("output") or "")[:200].replace("\n", " ")
            self.stdout.write(f"        output : {body}")

    # ------------------------------------------------------------------
    # dag (Multi-Agent Parallel/DAG)
    # ------------------------------------------------------------------

    def _run_dag(self, options):
        queries = self._resolve_queries(options)
        model = options.get("model") or ""
        max_nodes = options["max_nodes"]
        user = _get_or_create_system_user()

        for query in queries:
            self._run_single_dag(query, model, max_nodes, user)

    def _run_single_dag(self, query: str, model: str, max_nodes: int, user: User) -> None:
        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write(self.style.HTTP_INFO(f"Query    : {query}"))
        self.stdout.write(self.style.HTTP_INFO(f"Model    : {model or 'default'}"))
        self.stdout.write(self.style.HTTP_INFO(f"Max nodes: {max_nodes}"))
        self.stdout.write("=" * 60)

        run = create_dag_run(user=user, query=query, model=model, max_nodes=max_nodes)
        self.stdout.write(f"Run ID: {run.pk}\n")

        for raw_event in run_dag(run, model=model):
            line = raw_event.strip()
            if not line.startswith("data: "):
                continue
            event = json.loads(line[len("data: ") :])
            kind = event.get("event")

            if kind == "plan":
                self.stdout.write(self.style.WARNING("  Graph:"))
                for node in event.get("nodes", []):
                    tool = node.get("tool") or "reason"
                    deps = ", ".join(node.get("depends_on") or []) or "-"
                    self.stdout.write(
                        f"    {node.get('id')} [{node.get('focus')}] [{tool}]  <- {deps}"
                    )
                waves = event.get("waves") or []
                rendered = "  |  ".join(f"wave {i}: {', '.join(w)}" for i, w in enumerate(waves))
                self.stdout.write(self.style.WARNING(f"  Waves: {rendered}"))
                self.stdout.write("-" * 60)
            elif kind == "wave":
                ids = ", ".join(event.get("node_ids") or [])
                self.stdout.write(self.style.WARNING(f"  >> wave {event.get('index')}: {ids}"))
            elif kind == "node":
                self._print_dag_node(event)
            elif kind == "result":
                self.stdout.write("")
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Answer (nodes={event.get('nodes')}, waves={event.get('waves')}):"
                    )
                )
                self.stdout.write(event.get("output") or "")
                self.stdout.write(
                    self.style.SUCCESS(f"\nMulti-Agent DAG complete  (run_id={run.pk})")
                )
            elif kind == "error":
                self.stdout.write(self.style.ERROR(f"  error — {event.get('error')}"))

    def _print_dag_node(self, event: dict) -> None:
        deps = ", ".join(event.get("depends_on") or []) or "-"
        style = self.style.ERROR if event.get("status") == "error" else self.style.SUCCESS
        self.stdout.write(style(f"  [{event.get('node_id')}] {event.get('label')}  <- {deps}"))
        tool = event.get("tool")
        if tool:
            args = json.dumps(event.get("tool_args") or {})
            observation = (event.get("observation") or "")[:160].replace("\n", " ")
            self.stdout.write(self.style.SUCCESS(f"        tool   : {tool}({args})"))
            self.stdout.write(f"        observ.: {observation}")
        if event.get("status") == "error":
            self.stdout.write(self.style.ERROR(f"        error  : {event.get('error')}"))
        else:
            body = (event.get("output") or "")[:200].replace("\n", " ")
            self.stdout.write(f"        output : {body}")

    # ------------------------------------------------------------------
    # autonomous (Autonomous / Long-Horizon)
    # ------------------------------------------------------------------

    def _run_autonomous(self, options):
        queries = self._resolve_queries(options)
        model = options.get("model") or ""
        max_cycles = options["max_cycles"]
        max_subagents = options["max_subagents"]
        user = _get_or_create_system_user()

        for query in queries:
            self._run_single_autonomous(query, model, max_cycles, max_subagents, user)

    def _run_single_autonomous(
        self, query: str, model: str, max_cycles: int, max_subagents: int, user: User
    ) -> None:
        self.stdout.write("")
        self.stdout.write("=" * 60)
        self.stdout.write(self.style.HTTP_INFO(f"Goal      : {query}"))
        self.stdout.write(self.style.HTTP_INFO(f"Model     : {model or 'default'}"))
        self.stdout.write(
            self.style.HTTP_INFO(f"Max cycles: {max_cycles}  subagents: {max_subagents}")
        )
        self.stdout.write("=" * 60)

        run = create_autonomous_run(
            user=user,
            query=query,
            model=model,
            max_cycles=max_cycles,
            max_subagents=max_subagents,
        )
        self.stdout.write(f"Run ID: {run.pk}\n")

        for raw_event in run_autonomous(run, model=model):
            line = raw_event.strip()
            if not line.startswith("data: "):
                continue
            event = json.loads(line[len("data: ") :])
            kind = event.get("event")

            if kind == "goal":
                self.stdout.write(self.style.WARNING(f"  Goal : {event.get('goal')}"))
                backlog = event.get("backlog") or []
                if backlog:
                    self.stdout.write(self.style.WARNING("  Backlog:"))
                    for task in backlog:
                        self.stdout.write(f"    - {task}")
                self.stdout.write("-" * 60)
            elif kind == "cycle":
                self._print_autonomous_cycle(event)
            elif kind == "result":
                self.stdout.write("")
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Answer (cycles={event.get('cycles')}, stop={event.get('stop_reason')}):"
                    )
                )
                self.stdout.write(event.get("output") or "")
                self.stdout.write(self.style.SUCCESS(f"\nAutonomous complete  (run_id={run.pk})"))
            elif kind == "error":
                self.stdout.write(self.style.ERROR(f"  error — {event.get('error')}"))

    def _print_autonomous_cycle(self, event: dict) -> None:
        action = "subagent" if event.get("spawned") else event.get("action")
        style = self.style.ERROR if event.get("status") == "error" else self.style.SUCCESS
        flag = "  [goal complete]" if event.get("goal_complete") else ""
        self.stdout.write(style(f"  #{event.get('index')} [{action}]{flag}"))
        reflection = (event.get("reflection") or "")[:160].replace("\n", " ")
        if reflection:
            self.stdout.write(f"        reflect: {reflection}")
        if event.get("task"):
            self.stdout.write(f"        task   : {event.get('task')}")
        tool = event.get("tool")
        if tool:
            args = json.dumps(event.get("tool_args") or {})
            observation = (event.get("observation") or "")[:160].replace("\n", " ")
            self.stdout.write(self.style.SUCCESS(f"        tool   : {tool}({args})"))
            self.stdout.write(f"        observ.: {observation}")
        steps = event.get("subagent_steps") or []
        if steps:
            tools_used = ", ".join(s.get("tool", "") for s in steps)
            self.stdout.write(f"        subagent: {len(steps)} tool(s) [{tools_used}]")
        if event.get("status") == "error":
            self.stdout.write(self.style.ERROR(f"        error  : {event.get('error')}"))
        else:
            body = (event.get("output") or "")[:200].replace("\n", " ")
            self.stdout.write(f"        output : {body}")
