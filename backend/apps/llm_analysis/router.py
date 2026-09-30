from __future__ import annotations

import json
import math
from typing import TYPE_CHECKING

from ._events import event, fail, succeed
from .config import get_llm_config

if TYPE_CHECKING:
    from collections.abc import Generator

    from .models import AgentRun


ROUTE_STEPS = {
    "simple": "Direct answer - one Ollama call with user query.",
    "analysis": "Financial analysis - 3 concurrent aspect calls (valuation/profitability/risk) "
    "then one aggregation.",
    "comparison": "Multi-ticker comparison - concurrent per-ticker narration then synthesis.",
    "deep_research": "Full pipeline - classify -> research DB -> synthesise -> format report.",
}

VALID_ROUTES = ("simple", "analysis", "comparison", "deep_research")

# Independent aspects fanned out concurrently for the analysis route (Parallelization /
# sectioning). Each is a focused prompt; results are aggregated by one main-model call.
ANALYSIS_ASPECTS = (
    (
        "Valuation",
        "Focus ONLY on valuation: P/E, P/B, EV/EBITDA, price-to-sales, and whether the "
        "stock looks cheap or expensive relative to its sector.",
    ),
    (
        "Profitability",
        "Focus ONLY on profitability and margins: gross/operating/net margins, ROE, ROIC, "
        "and margin trends.",
    ),
    (
        "Risk",
        "Focus ONLY on risk and balance-sheet health: debt-to-equity, leverage, liquidity, "
        "interest coverage, and downside risks.",
    ),
)


def _classify_route(query: str) -> dict:
    """One LLM call on the cheap classifier model. Returns {route, reason, tickers, complexity}."""
    from . import services

    system = (
        "You are a financial query classifier. "
        "Given a user query, return ONLY valid JSON: "
        '{"route": "simple"|"analysis"|"comparison"|"deep_research", '
        '"reason": "<one sentence>", '
        '"tickers": ["<TICKER>", ...], '
        '"complexity": "low"|"medium"|"high"}. '
        "Rules: simple=factual/price/definition; "
        "analysis=ratios/margins/benchmarks for a single company; "
        "comparison=2+ tickers contrasted against each other; "
        "deep_research=multi-ticker thesis/earnings/investment recommendation."
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": query},
    ]
    raw = services.chat(messages, model=services._classifier_model())
    parsed = _parse_classification(raw)
    return parsed


def _parse_classification(raw: str) -> dict:
    """Parse the classifier output, tolerating fenced or noisy JSON."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Classifier returned non-JSON output: {raw[:200]}") from exc

    route = data.get("route")
    if route not in VALID_ROUTES:
        route = "simple"

    return {
        "route": route,
        "reason": str(data.get("reason", "")),
        "tickers": [str(t).upper() for t in data.get("tickers", []) if t],
        "complexity": data.get("complexity", "low"),
    }


# Canonical phrasings per route, embedded once and compared against the query.
ROUTE_EXEMPLARS: dict[str, tuple[str, ...]] = {
    "simple": (
        "What is the current price of AAPL?",
        "Define price to earnings ratio",
        "What does market capitalization mean?",
        "When does the stock market open?",
    ),
    "analysis": (
        "Analyse Microsoft's valuation and profit margins",
        "How is NVDA's balance sheet and debt level?",
        "Is Apple overvalued based on its ratios?",
        "Break down Tesla's profitability and risk",
    ),
    "comparison": (
        "Compare MSFT vs GOOG vs AAPL",
        "Which is a better buy, Coca-Cola or Pepsi?",
        "Contrast the margins of Visa and Mastercard",
        "AMD versus Intel on growth and valuation",
    ),
    "deep_research": (
        "Build an investment thesis for NVDA",
        "Should I invest in Amazon for the long term?",
        "Give me a full research report on the energy sector",
        "Deep dive into Meta's earnings and outlook",
    ),
}

# Routes that need ticker/param extraction; semantic routing still defers those to the LLM.
_ROUTES_NEEDING_PARAMS = frozenset({"analysis", "comparison", "deep_research"})


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _route_semantic(query: str) -> dict | None:
    """Pick a route by embedding similarity. Returns None to signal LLM fallback.

    0 LLM calls when the chosen route needs no params (e.g. ``simple``); routes that
    require tickers still extract them via the LLM classifier.
    """
    from . import services

    exemplar_texts: list[str] = []
    exemplar_routes: list[str] = []
    for route, phrases in ROUTE_EXEMPLARS.items():
        for phrase in phrases:
            exemplar_texts.append(phrase)
            exemplar_routes.append(route)

    vectors = services.embed([query, *exemplar_texts])
    query_vec = vectors[0]

    best_per_route: dict[str, float] = {}
    for route, vec in zip(exemplar_routes, vectors[1:], strict=True):
        score = _cosine(query_vec, vec)
        if score > best_per_route.get(route, -1.0):
            best_per_route[route] = score

    best_route = max(best_per_route, key=best_per_route.get)
    confidence = best_per_route[best_route]

    if confidence < get_llm_config().route_threshold:
        return None  # not confident enough; let the LLM decide

    tickers: list[str] = []
    complexity = "low"
    if best_route in _ROUTES_NEEDING_PARAMS:
        params = _classify_route(query)
        tickers = params["tickers"]
        complexity = params["complexity"]

    return {
        "route": best_route,
        "reason": f"semantic match (cosine {confidence:.2f})",
        "tickers": tickers,
        "complexity": complexity,
        "route_method": "semantic",
        "route_confidence": confidence,
    }


def resolve_route(query: str) -> dict:
    """Decide the route, semantically when enabled, otherwise via the LLM classifier."""
    if get_llm_config().route_mode == "semantic":
        result = _route_semantic(query)
        if result is not None:
            return result

    classification = _classify_route(query)
    classification["route_method"] = "llm"
    classification["route_confidence"] = None
    return classification


def _run_analysis(query: str, model: str | None) -> str:
    """Sectioned analysis: fan out independent aspects, then aggregate (main model).

    Shares one copy of the sectioning logic with the observable ``parallel`` agent via
    ``parallel.section_batches`` / ``parallel.aggregate_sections``.
    """
    from . import parallel, services

    batches = parallel.section_batches(query)
    results = services.chat_many(batches, model=model)

    sections: list[tuple[str, str]] = []
    for (name, _), res in zip(ANALYSIS_ASPECTS, results, strict=True):
        body = res["ok"] if res["ok"] is not None else f"(aspect failed: {res['error']})"
        sections.append((name, body))
    return parallel.aggregate_sections(query, sections, model)


def _run_comparison(query: str, tickers: list[str], model: str | None) -> str:
    """Concurrent per-ticker narration then a single comparison synthesis (main model)."""
    import json

    from . import chain, services

    data = [entry for entry in chain.research_tickers(tickers) if entry.get("found")]
    if len(data) < 2:
        # Not enough resolvable tickers to compare - degrade to single-company analysis.
        return _run_analysis(query, model)

    batches = [
        [
            {
                "role": "user",
                "content": (
                    "Summarise the financial profile of "
                    + entry["symbol"]
                    + " from this data. Focus on valuation, profitability, and risk. "
                    "Be concise.\n\nData (JSON):\n" + json.dumps(entry, default=str)
                ),
            }
        ]
        for entry in data
    ]
    narrations = services.chat_many(batches, model=model)

    sections = []
    for entry, res in zip(data, narrations, strict=True):
        body = res["ok"] if res["ok"] is not None else f"(narration failed: {res['error']})"
        sections.append(f"### {entry['symbol']}\n{body}")
    narration_text = "\n\n".join(sections)

    agg_messages = [
        {
            "role": "user",
            "content": (
                'The user asked: "' + query + '"\n\n'
                "Per-company summaries:\n\n" + narration_text + "\n\n"
                "Write a structured comparison: contrast the companies on valuation, "
                "profitability, and risk, and state which looks more attractive and why."
            ),
        }
    ]
    return services.chat(agg_messages, model=model)


def run_route(run: AgentRun, model: str = "") -> Generator[str]:
    """SSE generator. Classifies the query, dispatches to a path, yields events."""
    from . import chain, services, store

    model_arg = model or None

    # Step 1: resolve the route (semantic or LLM; param extraction stays on the cheap model)
    try:
        classification = resolve_route(run.query)
    except (ValueError, services.OllamaServiceError) as exc:
        yield from fail(run, str(exc))
        return

    route = classification["route"]
    store.update_run(
        run,
        route=route,
        route_reason=classification["reason"],
        route_method=classification.get("route_method") or "",
        route_confidence=classification.get("route_confidence"),
    )

    yield event(
        "classified",
        route=route,
        reason=classification["reason"],
        tickers=classification["tickers"],
        complexity=classification["complexity"],
        route_method=classification.get("route_method"),
        route_confidence=classification.get("route_confidence"),
    )

    # Step 2: dispatch
    try:
        if route == "simple":
            output = services.chat([{"role": "user", "content": run.query}], model=model_arg)

        elif route == "analysis":
            output = _run_analysis(run.query, model_arg)

        elif route == "comparison":
            output = _run_comparison(run.query, classification["tickers"], model_arg)

        else:  # deep_research
            chain_run = services.create_chain_run(user=run.user, query=run.query, model=model)
            store.update_run(run, parent=chain_run)

            yield from chain.run_chain(chain_run, model=model_arg)

            chain_run.refresh_from_db()
            format_step = chain_run.steps.filter(key="format").first()
            output = format_step.output if format_step else ""

    except services.OllamaServiceError as exc:
        yield from fail(run, str(exc))
        return

    yield from succeed(run, output, route=route)
