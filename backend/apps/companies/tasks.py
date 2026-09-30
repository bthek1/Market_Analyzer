import logging
from datetime import UTC
from datetime import datetime as dt

from celery import shared_task

from apps.llm_analysis.services import OllamaServiceError

from .services import (
    backfill_snapshot_fields,
    bootstrap_next_batch,
    discover_and_create_stubs,
    generate_company_summary,
    import_from_yfinance,
    sync_all_for_symbol,
    sync_company_profile,
    sync_dividends,
    sync_earnings_dates,
    sync_financials,
    sync_institutional_holders,
    sync_options,
    sync_price_history,
    sync_short_interest,
    sync_snapshot,
)
from .services import (
    record_sync as _record_sync,
)

logger = logging.getLogger(__name__)

_BATCH_SIZE = 10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stale_symbols(sync_type: str, batch_size: int = _BATCH_SIZE) -> list[str]:
    """Return up to batch_size bootstrapped symbols with the oldest last_synced_at.

    Symbols with no CompanySyncRecord for this sync_type sort first (epoch fallback).
    """
    from django.db.models import OuterRef, Subquery, Value
    from django.db.models.functions import Coalesce

    from .models import Company, CompanySyncRecord

    epoch = dt(1970, 1, 1, tzinfo=UTC)

    latest_sync = CompanySyncRecord.objects.filter(
        company=OuterRef("pk"), sync_type=sync_type
    ).values("last_synced_at")[:1]

    return list(
        Company.objects.filter(is_bootstrapped=True)
        .annotate(last_sync=Coalesce(Subquery(latest_sync), Value(epoch)))
        .order_by("last_sync")[:batch_size]
        .values_list("symbol", flat=True)
    )


# ---------------------------------------------------------------------------
# Bootstrap tasks
# ---------------------------------------------------------------------------


@shared_task
def discover_new_symbols() -> dict:
    """Scrape index lists and create un-bootstrapped stubs for new symbols."""
    created = discover_and_create_stubs()
    logger.info("Symbol discovery: %d new stubs created", created)
    return {"created": created}


@shared_task(bind=True, max_retries=0)
def bootstrap_tick(self) -> dict:
    """Process the next 5 un-bootstrapped companies (sequential, low memory)."""
    result = bootstrap_next_batch(batch_size=5)
    logger.info(
        "Bootstrap tick: attempted=%d ok=%d failed=%d",
        result["attempted"],
        result["ok"],
        result["failed"],
    )
    return result


# ---------------------------------------------------------------------------
# Rolling tick tasks
# ---------------------------------------------------------------------------


@shared_task
def tick_price_sync() -> dict:
    """Sync prices for the batch_size most-stale bootstrapped symbols."""
    symbols = _stale_symbols("price")
    if not symbols:
        return {"ok": 0, "failed": 0, "bars": 0}
    ok, fail, bars = 0, 0, 0
    for symbol in symbols:
        try:
            bars += sync_price_history(symbol)
            ok += 1
        except Exception as exc:
            fail += 1
            logger.warning("tick_price_sync failed for %s: %s", symbol, exc)
    _record_sync(symbols, "price")
    logger.info("tick_price_sync: ok=%d fail=%d bars=%d", ok, fail, bars)
    return {"ok": ok, "failed": fail, "bars": bars}


@shared_task
def tick_snapshot_sync() -> dict:
    """Sync snapshots for the batch_size most-stale bootstrapped symbols."""
    symbols = _stale_symbols("snapshot")
    if not symbols:
        return {"ok": 0, "failed": 0}
    ok, fail = 0, 0
    for symbol in symbols:
        try:
            sync_snapshot(symbol)
            ok += 1
        except Exception as exc:
            fail += 1
            logger.warning("tick_snapshot_sync failed for %s: %s", symbol, exc)
    _record_sync(symbols, "snapshot")
    logger.info("tick_snapshot_sync: ok=%d fail=%d", ok, fail)
    return {"ok": ok, "failed": fail}


@shared_task
def tick_profile_sync() -> dict:
    """Sync profiles for the batch_size most-stale bootstrapped symbols."""
    symbols = _stale_symbols("profile")
    if not symbols:
        return {"ok": 0, "failed": 0}
    ok, fail = 0, 0
    for symbol in symbols:
        try:
            sync_company_profile(symbol)
            ok += 1
        except Exception as exc:
            fail += 1
            logger.warning("tick_profile_sync failed for %s: %s", symbol, exc)
    _record_sync(symbols, "profile")
    logger.info("tick_profile_sync: ok=%d fail=%d", ok, fail)
    return {"ok": ok, "failed": fail}


@shared_task
def tick_financial_sync() -> dict:
    """Sync financials for the batch_size most-stale bootstrapped symbols."""
    symbols = _stale_symbols("financials")
    if not symbols:
        return {"ok": 0, "failed": 0, "rows": 0}
    ok, fail, rows = 0, 0, 0
    for symbol in symbols:
        try:
            rows += sync_financials(symbol)
            ok += 1
        except Exception as exc:
            fail += 1
            logger.warning("tick_financial_sync failed for %s: %s", symbol, exc)
    _record_sync(symbols, "financials")
    logger.info("tick_financial_sync: ok=%d fail=%d rows=%d", ok, fail, rows)
    return {"ok": ok, "failed": fail, "rows": rows}


@shared_task
def tick_dividend_sync() -> dict:
    """Sync dividends for the batch_size most-stale bootstrapped symbols."""
    symbols = _stale_symbols("dividends")
    if not symbols:
        return {"ok": 0, "failed": 0, "rows": 0}
    ok, fail, rows = 0, 0, 0
    for symbol in symbols:
        try:
            rows += sync_dividends(symbol)
            ok += 1
        except Exception as exc:
            fail += 1
            logger.warning("tick_dividend_sync failed for %s: %s", symbol, exc)
    _record_sync(symbols, "dividends")
    logger.info("tick_dividend_sync: ok=%d fail=%d rows=%d", ok, fail, rows)
    return {"ok": ok, "failed": fail, "rows": rows}


@shared_task
def tick_earnings_dates_sync() -> dict:
    """Sync earnings dates for the batch_size most-stale bootstrapped symbols."""
    symbols = _stale_symbols("earnings_dates")
    if not symbols:
        return {"ok": 0, "failed": 0, "rows": 0}
    ok, fail, rows = 0, 0, 0
    for symbol in symbols:
        try:
            rows += sync_earnings_dates(symbol)
            ok += 1
        except Exception as exc:
            fail += 1
            logger.warning("tick_earnings_dates_sync failed for %s: %s", symbol, exc)
    _record_sync(symbols, "earnings_dates")
    logger.info("tick_earnings_dates_sync: ok=%d fail=%d rows=%d", ok, fail, rows)
    return {"ok": ok, "failed": fail, "rows": rows}


@shared_task
def tick_institutional_holders_sync() -> dict:
    """Sync institutional holders for the batch_size most-stale bootstrapped symbols."""
    symbols = _stale_symbols("institutional_holders")
    if not symbols:
        return {"ok": 0, "failed": 0}
    ok, fail = 0, 0
    for symbol in symbols:
        try:
            sync_institutional_holders(symbol)
            ok += 1
        except Exception as exc:
            fail += 1
            logger.warning("tick_institutional_holders_sync failed for %s: %s", symbol, exc)
    _record_sync(symbols, "institutional_holders")
    logger.info("tick_institutional_holders_sync: ok=%d fail=%d", ok, fail)
    return {"ok": ok, "failed": fail}


@shared_task
def tick_short_interest_sync() -> dict:
    """Sync short interest for the batch_size most-stale bootstrapped symbols."""
    symbols = _stale_symbols("short_interest")
    if not symbols:
        return {"ok": 0, "failed": 0}
    ok, fail = 0, 0
    for symbol in symbols:
        try:
            sync_short_interest(symbol)
            ok += 1
        except Exception as exc:
            fail += 1
            logger.warning("tick_short_interest_sync failed for %s: %s", symbol, exc)
    _record_sync(symbols, "short_interest")
    logger.info("tick_short_interest_sync: ok=%d fail=%d", ok, fail)
    return {"ok": ok, "failed": fail}


def _is_weekend() -> bool:
    return dt.now(UTC).weekday() >= 5


@shared_task
def tick_options_sync() -> dict:
    """Sync options for the batch_size most-stale bootstrapped symbols (Mon-Fri only)."""
    if _is_weekend():
        return {"ok": 0, "failed": 0, "contracts": 0, "skipped": "weekend"}
    symbols = _stale_symbols("options")
    if not symbols:
        return {"ok": 0, "failed": 0, "contracts": 0}
    ok, fail, contracts = 0, 0, 0
    for symbol in symbols:
        try:
            contracts += sync_options(symbol)
            ok += 1
        except Exception as exc:
            fail += 1
            logger.warning("tick_options_sync failed for %s: %s", symbol, exc)
    _record_sync(symbols, "options")
    logger.info("tick_options_sync: ok=%d fail=%d contracts=%d", ok, fail, contracts)
    return {"ok": ok, "failed": fail, "contracts": contracts}


# ---------------------------------------------------------------------------
# Summary generation tick
# ---------------------------------------------------------------------------


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def generate_summary_single(self, symbol: str) -> dict:
    """Generate and persist an AI summary for one company."""
    try:
        summary = generate_company_summary(symbol)
        logger.info("Summary generated for %s: verdict=%s", symbol, summary.verdict)
        return {"symbol": symbol, "verdict": summary.verdict, "id": str(summary.pk)}
    except OllamaServiceError as exc:
        logger.warning("Ollama error for %s, retrying: %s", symbol, exc)
        raise self.retry(exc=exc)


@shared_task
def tick_summary_generation(batch_size: int = 5) -> dict:
    """Queue generate_summary_single for the batch_size companies with the oldest summary."""
    from django.db.models import F, OuterRef, Subquery

    from .models import Company, CompanySummary

    latest_generated_at = (
        CompanySummary.objects.filter(company=OuterRef("pk"))
        .order_by("-generated_at")
        .values("generated_at")[:1]
    )

    symbols = list(
        Company.objects.filter(is_bootstrapped=True)
        .annotate(latest_summary_at=Subquery(latest_generated_at))
        # Never-summarised companies (NULL) must come first. Postgres sorts
        # NULLs LAST under a plain ASC, so request NULLS FIRST explicitly.
        .order_by(F("latest_summary_at").asc(nulls_first=True))[:batch_size]
        .values_list("symbol", flat=True)
    )

    for symbol in symbols:
        generate_summary_single.delay(symbol)

    logger.info("tick_summary_generation: queued %d symbols", len(symbols))
    return {"queued": len(symbols)}


# ---------------------------------------------------------------------------
# Single-symbol tasks (UI-triggered, one company at a time)
# ---------------------------------------------------------------------------


@shared_task
def sync_profile_single(symbol: str) -> dict:
    company = sync_company_profile(symbol)
    if company is not None:
        _record_sync([symbol], "profile")
    return {"ok": company is not None}


@shared_task
def sync_prices_single(symbol: str) -> dict:
    n = sync_price_history(symbol)
    _record_sync([symbol], "price")
    return {"bars": n}


@shared_task
def sync_snapshot_single(symbol: str) -> dict:
    snap = sync_snapshot(symbol)
    if snap is not None:
        _record_sync([symbol], "snapshot")
    return {"ok": snap is not None}


@shared_task
def sync_financials_single(symbol: str) -> dict:
    n = sync_financials(symbol)
    _record_sync([symbol], "financials")
    return {"rows": n}


@shared_task
def sync_dividends_single(symbol: str) -> dict:
    n = sync_dividends(symbol)
    _record_sync([symbol], "dividends")
    return {"rows": n}


@shared_task
def sync_short_interest_single(symbol: str) -> dict:
    result = sync_short_interest(symbol)
    if result is not None:
        _record_sync([symbol], "short_interest")
    return {"ok": result is not None}


@shared_task
def sync_institutional_holders_single(symbol: str) -> dict:
    result = sync_institutional_holders(symbol)
    if result is not None:
        _record_sync([symbol], "institutional_holders")
    return {"ok": result is not None}


@shared_task
def sync_earnings_single(symbol: str) -> dict:
    n = sync_earnings_dates(symbol)
    _record_sync([symbol], "earnings_dates")
    return {"rows": n}


@shared_task
def sync_options_single(symbol: str) -> dict:
    n = sync_options(symbol)
    _record_sync([symbol], "options")
    return {"expiries": n}


# ---------------------------------------------------------------------------
# Legacy / manual tasks (kept for API-triggered use)
# ---------------------------------------------------------------------------


@shared_task
def bulk_import_symbols(symbols: list[str]) -> dict:
    """Import a specific list of symbols via yfinance (trigger manually)."""
    created = import_from_yfinance(symbols)
    logger.info("Bulk yfinance import: %d new companies created", created)
    return {"created": created}


@shared_task
def ingest_symbol_full(symbol: str) -> dict:
    """Full ingest for one symbol: profile, prices, snapshot, financials, dividends."""
    result = sync_all_for_symbol(symbol.upper())
    logger.info(
        "Full ingest for %s: profile=%s prices=%d snapshot=%s financials=%d dividends=%d",
        symbol,
        result["profile"],
        result["prices"],
        result["snapshot"],
        result["financials"],
        result["dividends"],
    )
    return result


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def backfill_snapshot_fields_task(self) -> dict:
    """Backfill new CompanySnapshot columns from existing .raw JSON (no API calls)."""
    updated = backfill_snapshot_fields()
    logger.info("backfill_snapshot_fields: %d rows updated", updated)
    return {"updated": updated}
