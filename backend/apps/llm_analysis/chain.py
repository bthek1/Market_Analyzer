from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime as dt
from typing import TYPE_CHECKING

from core.tracing import step_span

from ._events import sse, step_payload

if TYPE_CHECKING:
    from collections.abc import Generator

    from .models import AgentRun, AgentStep


@dataclass
class ChainStep:
    id: str
    label: str
    order: int


CHAIN_STEPS: list[ChainStep] = [
    ChainStep(id="classify", label="Classify Query", order=0),
    ChainStep(id="research", label="Gather Data", order=1),
    ChainStep(id="synthesise", label="Synthesise", order=2),
    ChainStep(id="format", label="Format Report", order=3),
]


@dataclass
class StepResult:
    step_id: str
    output: str


# Chain's payload carries no "event" discriminator - the frontend keys off ``step_id`` -
# so it cannot use ``event()``/``step_event()``. It still shares the framing and, for real
# steps, the SAME serialisation as the detail endpoint.


def _step_event(run_id: object, step: AgentStep) -> str:
    """One persisted chain step, exactly as ``/api/llm/chain/<id>/`` would return it."""
    return sse({"run_id": str(run_id), **step_payload(step, kind="chain")})


def _signal(run_id: object, step_id: str, status: str, error: str | None = None) -> str:
    """A run-level signal (``__init__`` / ``__done__``). Not a step - no row exists."""
    return sse(
        {
            "run_id": str(run_id),
            "step_id": step_id,
            "label": "",
            "status": status,
            "output": None,
            "error": error,
        }
    )


def _classify(query: str, context: list[StepResult], model: str | None) -> str:
    from . import services

    prompt = (
        "You are a financial query classifier. "
        "Given the user's query, extract and return ONLY a JSON object with these keys:\n"
        "- intent: one of [compare, analyse, dividend, valuation, growth, debt, overview]\n"
        '- tickers: list of uppercase stock ticker symbols mentioned (e.g. ["AAPL", "MSFT"])\n'
        "- time_horizon: one of [recent, annual, multi_year, all_time]\n\n"
        f"Query: {query}\n\n"
        "Return only the JSON object. No explanation."
    )
    messages = [{"role": "user", "content": prompt}]
    # Classification always runs on the cheap classifier model, not the run's main model.
    return services.chat(messages, model=services._classifier_model())


def snapshot_metrics(snapshot) -> dict:
    """Core valuation metrics from a CompanySnapshot row (shared with the ReAct tools).

    LLM-FACING: both callers serialise this straight into a prompt, so the fraction-valued
    ratios leave here in PERCENT under ``*_pct`` names (issue #11) - see ``tools.as_percent``.
    """
    from .tools import as_percent

    return {
        "market_cap": snapshot.market_cap,
        "trailing_pe": snapshot.trailing_pe,
        "forward_pe": snapshot.forward_pe,
        "price_to_book": snapshot.price_to_book,
        "trailing_eps": snapshot.trailing_eps,
        "forward_eps": snapshot.forward_eps,
        "debt_to_equity": snapshot.debt_to_equity,
        "return_on_equity_pct": as_percent(snapshot.return_on_equity),
        "profit_margins_pct": as_percent(snapshot.profit_margins),
        "dividend_yield_pct": as_percent(snapshot.dividend_yield),
    }


def annual_financials(company, limit: int = 40) -> list[dict]:
    """Recent annual financial-statement rows for a company (shared with the ReAct tools)."""
    from apps.companies.models import FinancialStatement

    return list(
        FinancialStatement.objects.filter(company=company, period="annual")
        .order_by("-period_end")
        .values("statement_type", "period_end", "metric", "value")[:limit]
    )


def _research_company(symbol: str) -> dict:
    """Pull the latest snapshot + annual financials for one ticker (no LLM call)."""
    from apps.companies.models import Company, CompanySnapshot

    try:
        company = Company.objects.select_related("sector", "industry").get(symbol__iexact=symbol)
    except Company.DoesNotExist:
        return {"symbol": symbol, "found": False}

    snapshot = CompanySnapshot.objects.filter(company=company).order_by("-fetched_at").first()

    entry: dict = {
        "symbol": company.symbol,
        "found": True,
        "name": company.name or company.symbol,
        "sector": company.sector.name if company.sector else None,
        "industry": company.industry.name if company.industry else None,
        "snapshot": None,
        "financials": annual_financials(company),
    }
    if snapshot:
        entry["snapshot"] = snapshot_metrics(snapshot)
    return entry


def research_tickers(tickers: list[str]) -> list[dict]:
    """Reusable DB research for up to 5 tickers. No LLM calls."""
    return [_research_company(symbol) for symbol in tickers[:5]]


def _research(query: str, context: list[StepResult], model: str | None) -> str:
    classify_output = next((s.output for s in context if s.step_id == "classify"), "{}")
    try:
        parsed = json.loads(classify_output)
    except json.JSONDecodeError:
        parsed = {}

    tickers: list[str] = parsed.get("tickers", [])
    if not tickers:
        return json.dumps({"message": "No tickers identified.", "companies": []})

    return json.dumps(research_tickers(tickers), default=str)


def _synthesise(query: str, context: list[StepResult], model: str | None) -> str:
    from . import services

    classify_output = next((s.output for s in context if s.step_id == "classify"), "")
    research_output = next((s.output for s in context if s.step_id == "research"), "")

    prompt = (
        "You are a senior financial analyst. "
        'The user asked: "' + query + '"\n\n'
        "Query classification:\n" + classify_output + "\n\n"
        "Company data (JSON):\n" + research_output + "\n\n"
        "Analyse this data thoroughly. Reason about the key metrics, trends, and risks. "
        "Be precise and structured. Output a detailed analysis in plain prose."
    )
    messages = [{"role": "user", "content": prompt}]
    return services.chat(messages, model=model)


def _format_report(query: str, context: list[StepResult], model: str | None) -> str:
    from . import services

    synthesis = next((s.output for s in context if s.step_id == "synthesise"), "")

    prompt = (
        "You are a financial report writer. "
        "Rewrite the following analysis as a clean, well-structured markdown report. "
        "Use these sections (include only those relevant to the data):\n"
        "## Summary\n## Key Metrics\n## Analysis\n## Risks\n## Outlook\n\n"
        "Analysis to format:\n" + synthesis
    )
    messages = [{"role": "user", "content": prompt}]
    return services.chat(messages, model=model)


_STEP_HANDLERS = {
    "classify": _classify,
    "research": _research,
    "synthesise": _synthesise,
    "format": _format_report,
}


def run_chain(run: AgentRun, model: str | None = None) -> Generator[str]:
    yield _signal(run.id, "__init__", "running")
    context: list[StepResult] = []

    for step_def in CHAIN_STEPS:
        with step_span(run, step_def.order, key=step_def.id, label=step_def.label):
            step_row = run.steps.get(key=step_def.id)
            step_row.status = "running"
            step_row.started_at = dt.now(UTC)
            step_row.save(update_fields=["status", "started_at"])

            yield _step_event(run.id, step_row)

            try:
                handler = _STEP_HANDLERS[step_def.id]
                output = handler(run.query, context, model)
                context.append(StepResult(step_id=step_def.id, output=output))

                step_row.status = "done"
                step_row.output = output
                step_row.completed_at = dt.now(UTC)
                step_row.save(update_fields=["status", "output", "completed_at"])

                yield _step_event(run.id, step_row)

            except Exception as exc:
                step_row.status = "error"
                step_row.error = str(exc)
                step_row.completed_at = dt.now(UTC)
                step_row.save(update_fields=["status", "error", "completed_at"])

                run.status = "error"
                run.completed_at = dt.now(UTC)
                run.save(update_fields=["status", "completed_at"])

                yield _step_event(run.id, step_row)
                yield _signal(run.id, "__done__", "error")
                return

    run.status = "done"
    run.completed_at = dt.now(UTC)
    run.save(update_fields=["status", "completed_at"])
    yield _signal(run.id, "__done__", "done")
