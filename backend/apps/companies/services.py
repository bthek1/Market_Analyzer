import logging
from collections.abc import Callable
from datetime import UTC, date, timedelta
from datetime import datetime as dt
from decimal import Decimal as Dec

from django.db.models import Max

from apps.llm_analysis.services import chat as ollama_chat
from apps.llm_analysis.tools import VALUATION_RATIOS

from .models import (
    Company,
    CompanySnapshot,
    CompanySummary,
    CompanySyncRecord,
    Dividend,
    EarningsDate,
    FinancialStatement,
    Industry,
    InstitutionalHolderSnapshot,
    OptionsContract,
    OptionsExpiry,
    PriceBar,
    Sector,
    ShortInterest,
)
from .yfinance_client import YFinanceClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def _get_or_create_sector(name: str) -> "Sector | None":
    if not name:
        return None
    sector, _ = Sector.objects.get_or_create(name=name, defaults={"description": ""})
    return sector


def _get_or_create_industry(name: str, sector: "Sector | None") -> "Industry | None":
    if not name:
        return None
    industry, created = Industry.objects.get_or_create(name=name)
    if created and sector is not None:
        industry.sector = sector
        industry.save(update_fields=["sector"])
    elif not created and sector is not None and industry.sector is None:
        industry.sector = sector
        industry.save(update_fields=["sector"])
    return industry


# ---------------------------------------------------------------------------
# Company profile sync
# ---------------------------------------------------------------------------


def _apply_yf_profile(symbol: str, data: dict) -> Company:
    """Upsert a Company from a normalised yfinance profile dict."""
    sector = _get_or_create_sector(data.get("sector", ""))
    industry = _get_or_create_industry(data.get("industry", ""), sector)
    defaults = {
        "name": data.get("name", symbol),
        "exchange": data.get("exchange", ""),
        "currency": data.get("currency", ""),
        "sector": sector,
        "industry": industry,
        "address": data.get("address", ""),
        "city": data.get("city", ""),
        "state": data.get("state", ""),
        "zip_code": data.get("zip_code", ""),
        "country": data.get("country", ""),
        "phone": data.get("phone", ""),
        "website": data.get("website", ""),
        "ir_website": data.get("ir_website", ""),
        "description": data.get("description", ""),
        "full_time_employees": data.get("full_time_employees"),
        "officers": data.get("officers", []),
    }
    company, _ = Company.objects.update_or_create(symbol=symbol, defaults=defaults)
    return company


def sync_company_profile(symbol: str) -> "Company | None":
    """Fetch a yfinance profile for one symbol and upsert into the DB."""
    client = YFinanceClient()
    data = client.get_profile(symbol)
    if not data:
        return None
    return _apply_yf_profile(symbol, data)


# ---------------------------------------------------------------------------
# Price history
# ---------------------------------------------------------------------------


def sync_price_history(
    symbol: str,
    period: str | None = None,
    start: date | None = None,
) -> int:
    """Fetch OHLCV bars for one symbol and bulk-insert new rows.

    Defaults to incremental mode: fetches only since the most recent stored
    PriceBar date. Pass period="max" for a full history fetch (bootstrap).
    Returns the count of PriceBar rows inserted (existing bars are skipped).
    """

    try:
        company = Company.objects.get(symbol=symbol)
    except Company.DoesNotExist:
        return 0

    if start is None and period is None:
        last_date = (
            PriceBar.objects.filter(company=company)
            .order_by("-date")
            .values_list("date", flat=True)
            .first()
        )
        start = last_date  # None when no bars exist -> yfinance will use "max"

    client = YFinanceClient()
    bars = client.get_price_history(symbol, period=period, start=start)
    if not bars:
        return 0

    objects = [
        PriceBar(
            company=company,
            date=bar["date"],
            open=bar["open"],
            high=bar["high"],
            low=bar["low"],
            close=bar["close"],
            volume=bar["volume"],
        )
        for bar in bars
    ]
    created = PriceBar.objects.bulk_create(objects, ignore_conflicts=True)
    return len(created)


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def sync_snapshot(symbol: str) -> "CompanySnapshot | None":
    """Create a new point-in-time CompanySnapshot for one symbol."""
    try:
        company = Company.objects.get(symbol=symbol)
    except Company.DoesNotExist:
        return None

    client = YFinanceClient()
    data = client.get_snapshot(symbol)
    if not data:
        return None

    return CompanySnapshot.objects.create(
        company=company,
        market_cap=data.get("market_cap"),
        trailing_pe=data.get("trailing_pe"),
        forward_pe=data.get("forward_pe"),
        price_to_book=data.get("price_to_book"),
        debt_to_equity=data.get("debt_to_equity"),
        return_on_equity=data.get("return_on_equity"),
        profit_margins=data.get("profit_margins"),
        dividend_yield=data.get("dividend_yield"),
        trailing_eps=data.get("trailing_eps"),
        forward_eps=data.get("forward_eps"),
        beta=data.get("beta"),
        fifty_two_week_high=data.get("fifty_two_week_high"),
        fifty_two_week_low=data.get("fifty_two_week_low"),
        week52_change=data.get("week52_change"),
        sandp52_week_change=data.get("sandp52_week_change"),
        average_volume=data.get("average_volume"),
        shares_outstanding=data.get("shares_outstanding"),
        float_shares=data.get("float_shares"),
        enterprise_value=data.get("enterprise_value"),
        enterprise_to_revenue=data.get("enterprise_to_revenue"),
        enterprise_to_ebitda=data.get("enterprise_to_ebitda"),
        peg_ratio=data.get("peg_ratio"),
        trailing_peg_ratio=data.get("trailing_peg_ratio"),
        price_to_sales=data.get("price_to_sales"),
        payout_ratio=data.get("payout_ratio"),
        book_value=data.get("book_value"),
        fifty_day_average=data.get("fifty_day_average"),
        two_hundred_day_average=data.get("two_hundred_day_average"),
        revenue_growth=data.get("revenue_growth"),
        earnings_growth=data.get("earnings_growth"),
        earnings_quarterly_growth=data.get("earnings_quarterly_growth"),
        gross_margins=data.get("gross_margins"),
        operating_margins=data.get("operating_margins"),
        ebitda_margins=data.get("ebitda_margins"),
        current_ratio=data.get("current_ratio"),
        quick_ratio=data.get("quick_ratio"),
        return_on_assets=data.get("return_on_assets"),
        ebitda=data.get("ebitda"),
        total_cash=data.get("total_cash"),
        total_cash_per_share=data.get("total_cash_per_share"),
        free_cashflow=data.get("free_cashflow"),
        operating_cashflow=data.get("operating_cashflow"),
        net_income_to_common=data.get("net_income_to_common"),
        revenue_per_share=data.get("revenue_per_share"),
        held_pct_institutions=data.get("held_pct_institutions"),
        held_pct_insiders=data.get("held_pct_insiders"),
        dividend_rate=data.get("dividend_rate"),
        ex_dividend_date=data.get("ex_dividend_date"),
        five_year_avg_dividend_yield=data.get("five_year_avg_dividend_yield"),
        trailing_annual_dividend_rate=data.get("trailing_annual_dividend_rate"),
        last_dividend_value=data.get("last_dividend_value"),
        last_dividend_date=data.get("last_dividend_date"),
        last_fiscal_year_end=data.get("last_fiscal_year_end"),
        next_fiscal_year_end=data.get("next_fiscal_year_end"),
        most_recent_quarter=data.get("most_recent_quarter"),
        audit_risk=data.get("audit_risk"),
        board_risk=data.get("board_risk"),
        compensation_risk=data.get("compensation_risk"),
        shareholder_rights_risk=data.get("shareholder_rights_risk"),
        overall_risk=data.get("overall_risk"),
        recommendation_mean=data.get("recommendation_mean"),
        recommendation_key=data.get("recommendation_key"),
        num_analyst_opinions=data.get("num_analyst_opinions"),
        target_high_price=data.get("target_high_price"),
        target_low_price=data.get("target_low_price"),
        target_mean_price=data.get("target_mean_price"),
        target_median_price=data.get("target_median_price"),
        recommendations_breakdown=data.get("recommendations_breakdown", []),
        last_split_factor=data.get("last_split_factor"),
        last_split_date=data.get("last_split_date"),
        raw=data.get("raw", {}),
    )


# ---------------------------------------------------------------------------
# Snapshot backfill (reads from existing .raw, no new API calls)
# ---------------------------------------------------------------------------


def backfill_snapshot_fields(company_id: int | None = None) -> int:
    """Populate new CompanySnapshot columns from the existing .raw JSON.

    No yfinance API calls are made. Processes snapshots that still have
    beta=None as a proxy for un-backfilled rows (beta is almost always present).
    Returns the count of snapshots updated.
    """

    qs = CompanySnapshot.objects.filter(beta__isnull=True)
    if company_id is not None:
        qs = qs.filter(company_id=company_id)

    updated = 0
    for snap in qs.iterator(chunk_size=200):
        raw = snap.raw or {}
        if not raw:
            continue

        def _float(key: str) -> float | None:
            val = raw.get(key)
            try:
                return float(val) if val is not None else None
            except (TypeError, ValueError):
                return None

        def _int(key: str) -> int | None:
            val = raw.get(key)
            try:
                return int(val) if val is not None else None
            except (TypeError, ValueError):
                return None

        def _str(key: str) -> str | None:
            val = raw.get(key)
            return str(val) if val is not None else None

        def _pct_to_fraction(key: str) -> float | None:
            """yfinance gives this field in percent; snapshots store fractions."""
            val = _float(key)
            return None if val is None else val / 100.0

        def _epoch(key: str):
            from .yfinance_client import _epoch_to_date

            return _epoch_to_date(raw.get(key))

        snap.beta = _float("beta")
        snap.fifty_two_week_high = _float("fiftyTwoWeekHigh")
        snap.fifty_two_week_low = _float("fiftyTwoWeekLow")
        snap.week52_change = _float("52WeekChange")
        snap.sandp52_week_change = _float("SandP52WeekChange")
        snap.average_volume = _int("averageVolume")
        snap.shares_outstanding = _int("sharesOutstanding")
        snap.float_shares = _int("floatShares")
        snap.enterprise_value = _int("enterpriseValue")
        snap.enterprise_to_revenue = _float("enterpriseToRevenue")
        snap.enterprise_to_ebitda = _float("enterpriseToEbitda")
        snap.peg_ratio = _float("pegRatio")
        snap.trailing_peg_ratio = _float("trailingPegRatio")
        snap.price_to_sales = _float("priceToSalesTrailingTwelveMonths")
        snap.payout_ratio = _float("payoutRatio")
        snap.book_value = _float("bookValue")
        snap.fifty_day_average = _float("fiftyDayAverage")
        snap.two_hundred_day_average = _float("twoHundredDayAverage")
        snap.revenue_growth = _float("revenueGrowth")
        snap.earnings_growth = _float("earningsGrowth")
        snap.earnings_quarterly_growth = _float("earningsQuarterlyGrowth")
        snap.gross_margins = _float("grossMargins")
        snap.operating_margins = _float("operatingMargins")
        snap.ebitda_margins = _float("ebitdaMargins")
        snap.current_ratio = _float("currentRatio")
        snap.quick_ratio = _float("quickRatio")
        snap.return_on_assets = _float("returnOnAssets")
        snap.ebitda = _int("ebitda")
        snap.total_cash = _int("totalCash")
        snap.total_cash_per_share = _float("totalCashPerShare")
        snap.free_cashflow = _int("freeCashflow")
        snap.operating_cashflow = _int("operatingCashflow")
        snap.net_income_to_common = _int("netIncomeToCommon")
        snap.revenue_per_share = _float("revenuePerShare")
        snap.held_pct_institutions = _float("heldPercentInstitutions")
        snap.held_pct_insiders = _float("heldPercentInsiders")
        snap.dividend_rate = _float("dividendRate")
        snap.ex_dividend_date = _epoch("exDividendDate")
        snap.five_year_avg_dividend_yield = _pct_to_fraction("fiveYearAvgDividendYield")
        snap.trailing_annual_dividend_rate = _float("trailingAnnualDividendRate")
        snap.last_dividend_value = _float("lastDividendValue")
        snap.last_dividend_date = _epoch("lastDividendDate")
        snap.last_fiscal_year_end = _epoch("lastFiscalYearEnd")
        snap.next_fiscal_year_end = _epoch("nextFiscalYearEnd")
        snap.most_recent_quarter = _epoch("mostRecentQuarter")
        snap.audit_risk = _int("auditRisk")
        snap.board_risk = _int("boardRisk")
        snap.compensation_risk = _int("compensationRisk")
        snap.shareholder_rights_risk = _int("shareHolderRightsRisk")
        snap.overall_risk = _int("overallRisk")
        snap.recommendation_mean = _float("recommendationMean")
        snap.recommendation_key = _str("recommendationKey")
        snap.num_analyst_opinions = _int("numberOfAnalystOpinions")
        snap.target_high_price = _float("targetHighPrice")
        snap.target_low_price = _float("targetLowPrice")
        snap.target_mean_price = _float("targetMeanPrice")
        snap.target_median_price = _float("targetMedianPrice")
        snap.last_split_factor = _str("lastSplitFactor")
        snap.last_split_date = _epoch("lastSplitDate")
        snap.save(
            update_fields=[
                "beta",
                "fifty_two_week_high",
                "fifty_two_week_low",
                "week52_change",
                "sandp52_week_change",
                "average_volume",
                "shares_outstanding",
                "float_shares",
                "enterprise_value",
                "enterprise_to_revenue",
                "enterprise_to_ebitda",
                "peg_ratio",
                "trailing_peg_ratio",
                "price_to_sales",
                "payout_ratio",
                "book_value",
                "fifty_day_average",
                "two_hundred_day_average",
                "revenue_growth",
                "earnings_growth",
                "earnings_quarterly_growth",
                "gross_margins",
                "operating_margins",
                "ebitda_margins",
                "current_ratio",
                "quick_ratio",
                "return_on_assets",
                "ebitda",
                "total_cash",
                "total_cash_per_share",
                "free_cashflow",
                "operating_cashflow",
                "net_income_to_common",
                "revenue_per_share",
                "held_pct_institutions",
                "held_pct_insiders",
                "dividend_rate",
                "ex_dividend_date",
                "five_year_avg_dividend_yield",
                "trailing_annual_dividend_rate",
                "last_dividend_value",
                "last_dividend_date",
                "last_fiscal_year_end",
                "next_fiscal_year_end",
                "most_recent_quarter",
                "audit_risk",
                "board_risk",
                "compensation_risk",
                "shareholder_rights_risk",
                "overall_risk",
                "recommendation_mean",
                "recommendation_key",
                "num_analyst_opinions",
                "target_high_price",
                "target_low_price",
                "target_mean_price",
                "target_median_price",
                "last_split_factor",
                "last_split_date",
            ]
        )
        updated += 1
    return updated


# ---------------------------------------------------------------------------
# Short interest
# ---------------------------------------------------------------------------


def sync_short_interest(symbol: str) -> "ShortInterest | None":
    """Create a new ShortInterest row only when date_short_interest changes.

    Data is extracted from the same Ticker.info call as snapshots, so the
    snapshot should be synced first where possible. This function makes its
    own info call for standalone use.
    """
    try:
        company = Company.objects.get(symbol=symbol)
    except Company.DoesNotExist:
        return None

    client = YFinanceClient()
    data = client.get_short_interest(symbol)
    if not data:
        return None

    return _upsert_short_interest(company, data)


def sync_short_interest_from_raw(company: Company, raw: dict) -> "ShortInterest | None":
    """Create ShortInterest from an already-fetched raw info dict (no extra API call)."""
    client = YFinanceClient()
    data = client.get_short_interest_from_raw(raw)
    if not data:
        return None
    return _upsert_short_interest(company, data)


def _upsert_short_interest(company: Company, data: dict) -> "ShortInterest | None":
    new_date = data.get("date_short_interest")
    latest = ShortInterest.objects.filter(company=company).order_by("-fetched_at").first()
    if latest and latest.date_short_interest == new_date:
        return None  # no change — monthly dedup
    return ShortInterest.objects.create(
        company=company,
        fetched_at=dt.now(UTC),
        date_short_interest=new_date,
        shares_short=data.get("shares_short"),
        shares_short_prior_month=data.get("shares_short_prior_month"),
        short_ratio=data.get("short_ratio"),
        short_pct_of_float=data.get("short_pct_of_float"),
        shares_pct_shares_out=data.get("shares_pct_shares_out"),
    )


def backfill_short_interest() -> int:
    """Backfill ShortInterest from existing CompanySnapshot.raw rows."""
    created = 0
    for snap in (
        CompanySnapshot.objects.select_related("company")
        .filter(raw__isnull=False)
        .order_by("company", "-fetched_at")
        .distinct("company")
    ):
        result = sync_short_interest_from_raw(snap.company, snap.raw)
        if result:
            created += 1
    return created


# ---------------------------------------------------------------------------
# Institutional holders
# ---------------------------------------------------------------------------


def sync_institutional_holders(symbol: str) -> "InstitutionalHolderSnapshot | None":
    """Fetch and store a new InstitutionalHolderSnapshot for one symbol."""
    try:
        company = Company.objects.get(symbol=symbol)
    except Company.DoesNotExist:
        return None

    client = YFinanceClient()
    holders = client.get_institutional_holders(symbol)
    return InstitutionalHolderSnapshot.objects.create(
        company=company,
        fetched_at=dt.now(UTC),
        holders=holders,
    )


# ---------------------------------------------------------------------------
# Earnings dates
# ---------------------------------------------------------------------------


def sync_earnings_dates(symbol: str) -> int:
    """Fetch and upsert EarningsDate rows for one symbol.

    Returns the count of rows created or updated.
    """
    try:
        company = Company.objects.get(symbol=symbol)
    except Company.DoesNotExist:
        return 0

    client = YFinanceClient()
    records = client.get_earnings_dates(symbol)
    if not records:
        return 0

    now = dt.now(UTC)
    objects = [
        EarningsDate(
            company=company,
            earnings_date=r["earnings_date"],
            eps_estimate=r["eps_estimate"],
            reported_eps=r["reported_eps"],
            surprise_pct=r["surprise_pct"],
            is_upcoming=r["is_upcoming"],
            fetched_at=now,
        )
        for r in records
    ]
    created = EarningsDate.objects.bulk_create(
        objects,
        update_conflicts=True,
        unique_fields=["company", "earnings_date"],
        update_fields=["eps_estimate", "reported_eps", "surprise_pct", "is_upcoming", "fetched_at"],
    )
    return len(created)


# ---------------------------------------------------------------------------
# Options chains
# ---------------------------------------------------------------------------


def sync_options(symbol: str) -> int:
    """Fetch and upsert options chain data for one symbol.

    Creates OptionsExpiry rows and bulk-upserts OptionsContract rows.
    Returns total count of contracts created/updated.
    """
    try:
        company = Company.objects.get(symbol=symbol)
    except Company.DoesNotExist:
        return 0

    client = YFinanceClient()
    chains = client.get_options_chain(symbol)
    if not chains:
        return 0

    now = dt.now(UTC)
    total = 0
    for chain in chains:
        expiry_date = chain["expiry_date"]
        expiry, _ = OptionsExpiry.objects.get_or_create(
            company=company,
            expiry_date=expiry_date,
            fetched_at=now,
        )
        all_contracts = []
        for contract_data in chain["calls"] + chain["puts"]:
            strike = contract_data.get("strike")
            if strike is None:
                continue
            all_contracts.append(
                OptionsContract(
                    expiry=expiry,
                    option_type=contract_data["option_type"],
                    contract_symbol=contract_data["contract_symbol"],
                    strike=Dec(strike),
                    last_price=(
                        Dec(contract_data["last_price"])
                        if contract_data.get("last_price")
                        else None
                    ),
                    bid=Dec(contract_data["bid"]) if contract_data.get("bid") else None,
                    ask=Dec(contract_data["ask"]) if contract_data.get("ask") else None,
                    volume=contract_data.get("volume"),
                    open_interest=contract_data.get("open_interest"),
                    implied_volatility=contract_data.get("implied_volatility"),
                    in_the_money=contract_data.get("in_the_money"),
                )
            )
        created = OptionsContract.objects.bulk_create(
            all_contracts,
            update_conflicts=True,
            unique_fields=["expiry", "option_type", "contract_symbol"],
            update_fields=[
                "strike",
                "last_price",
                "bid",
                "ask",
                "volume",
                "open_interest",
                "implied_volatility",
                "in_the_money",
            ],
        )
        total += len(created)
    return total


# ---------------------------------------------------------------------------
# Financial statements
# ---------------------------------------------------------------------------


def sync_financials(symbol: str) -> int:
    """Fetch financial statement rows for one symbol and upsert into the DB.

    Returns the count of rows created or updated.
    """
    try:
        company = Company.objects.get(symbol=symbol)
    except Company.DoesNotExist:
        return 0

    client = YFinanceClient()
    rows = client.get_financials(symbol)
    if not rows:
        return 0

    now = dt.now(UTC)
    objects = [
        FinancialStatement(
            company=company,
            statement_type=row["statement_type"],
            period=row["period"],
            period_end=row["period_end"],
            metric=row["metric"],
            value=row["value"],
            updated_at=now,
        )
        for row in rows
    ]
    created = FinancialStatement.objects.bulk_create(
        objects,
        update_conflicts=True,
        unique_fields=["company", "statement_type", "period", "period_end", "metric"],
        update_fields=["value", "updated_at"],
    )
    return len(created)


# ---------------------------------------------------------------------------
# Dividends
# ---------------------------------------------------------------------------


def sync_dividends(symbol: str) -> int:
    """Fetch dividend records for one symbol and bulk-insert new rows.

    Returns the count of Dividend rows inserted (existing rows are skipped).
    """
    try:
        company = Company.objects.get(symbol=symbol)
    except Company.DoesNotExist:
        return 0

    client = YFinanceClient()
    records = client.get_dividends(symbol)
    if not records:
        return 0

    now = dt.now(UTC)
    objects = [
        Dividend(company=company, date=r["date"], amount=r["amount"], updated_at=now)
        for r in records
    ]
    created = Dividend.objects.bulk_create(
        objects,
        update_conflicts=True,
        unique_fields=["company", "date"],
        update_fields=["amount", "updated_at"],
    )
    return len(created)


# ---------------------------------------------------------------------------
# Sync bookkeeping
# ---------------------------------------------------------------------------


def record_sync(symbols: list[str], sync_type: str) -> None:
    """Upsert CompanySyncRecord.last_synced_at = now for each symbol.

    Every ingestion path must call this, not only the batched Beat ticks: these rows
    are what the AI summary freshness gate (_stale_sync_reasons) reads first, and the
    only signal for sync types that write no row of their own. _ingested_at is the
    backstop when a path forgets, not a licence to skip it.
    Unknown symbols are silently skipped.
    """
    now = dt.now(UTC)
    companies = list(Company.objects.filter(symbol__in=symbols).only("pk"))
    CompanySyncRecord.objects.bulk_create(
        [CompanySyncRecord(company=c, sync_type=sync_type, last_synced_at=now) for c in companies],
        update_conflicts=True,
        unique_fields=["company", "sync_type"],
        update_fields=["last_synced_at"],
    )


# ---------------------------------------------------------------------------
# Full single-symbol ingest
# ---------------------------------------------------------------------------


def sync_all_for_symbol(symbol: str) -> dict:
    """Run all sync operations for one symbol.

    Returns a result dict with counts/booleans for each sync type.
    """
    profile = sync_company_profile(symbol)
    prices = sync_price_history(symbol)
    snapshot = sync_snapshot(symbol)
    financials = sync_financials(symbol)
    dividends = sync_dividends(symbol)
    institutional = sync_institutional_holders(symbol)
    earnings = sync_earnings_dates(symbol)
    options = sync_options(symbol)

    # Piggyback short interest from the snapshot raw to avoid an extra API call
    short = None
    if snapshot is not None:
        try:
            company = Company.objects.get(symbol=symbol)
            short = sync_short_interest_from_raw(company, snapshot.raw)
        except Company.DoesNotExist:
            pass

    if profile is not None:
        # Count-returning syncs report 0 both for "nothing new" and "nothing found",
        # so a real company that did not raise counts as synced; object-returning
        # ones record only when they actually produced a row.
        recorded = ["profile", "price", "financials", "dividends", "earnings_dates", "options"]
        if snapshot is not None:
            recorded.append("snapshot")
        if institutional is not None:
            recorded.append("institutional_holders")
        if short is not None:
            recorded.append("short_interest")
        for sync_type in recorded:
            record_sync([symbol], sync_type)

    return {
        "profile": profile is not None,
        "prices": prices,
        "snapshot": snapshot is not None,
        "financials": financials,
        "dividends": dividends,
        "institutional_holders": institutional is not None,
        "earnings_dates": earnings,
        "options": options,
        "short_interest": short is not None,
    }


# ---------------------------------------------------------------------------
# Market hierarchy
# ---------------------------------------------------------------------------


def get_market_hierarchy(metric: str = "count") -> list[dict]:
    """Return sector->industry tree ordered by the chosen metric.

    metric="count"      -- value = company count (default)
    metric="market_cap" -- value = sum of latest CompanySnapshot.market_cap
    """
    from django.db.models import Count, OuterRef, Subquery, Sum

    # Latest market_cap per company (NULL when no snapshot exists).
    latest_market_cap_sq = (
        CompanySnapshot.objects.filter(company=OuterRef("pk"))
        .order_by("-fetched_at")
        .values("market_cap")[:1]
    )

    # Annotate every company with its latest market_cap.
    companies_qs = Company.objects.annotate(latest_mc=Subquery(latest_market_cap_sq))

    use_market_cap = metric == "market_cap"
    order_field = "-total_market_cap" if use_market_cap else "-company_count"

    # --- Sectors ---
    sectors = Sector.objects.annotate(company_count=Count("companies", distinct=True)).filter(
        company_count__gt=0
    )
    if use_market_cap:
        # Sum latest_mc over all companies in each sector.
        sector_mc: dict[int, float] = {}
        for row in (
            companies_qs.filter(sector__isnull=False)
            .values("sector_id")
            .annotate(total=Sum("latest_mc"))
        ):
            sector_mc[row["sector_id"]] = float(row["total"] or 0)
        sectors = sorted(sectors, key=lambda s: sector_mc.get(s.pk, 0), reverse=True)
    else:
        sectors = sectors.order_by(order_field)

    # --- Industries ---
    industries = (
        Industry.objects.select_related("sector")
        .annotate(company_count=Count("companies", distinct=True))
        .filter(company_count__gt=0)
    )

    industry_mc: dict[int, float] = {}
    if use_market_cap:
        for row in (
            companies_qs.filter(industry__isnull=False)
            .values("industry_id")
            .annotate(total=Sum("latest_mc"))
        ):
            industry_mc[row["industry_id"]] = float(row["total"] or 0)

    industries_by_sector: dict[int, list[dict]] = {}
    for ind in industries:
        if ind.sector_id is None:
            continue
        mc = industry_mc.get(ind.pk, 0)
        node_val = mc if use_market_cap else ind.company_count
        industries_by_sector.setdefault(ind.sector_id, []).append(
            {
                "name": ind.name,
                "value": node_val,
                "company_count": ind.company_count,
                "market_cap": mc,
            }
        )

    # Sort children by the chosen metric descending.
    for children in industries_by_sector.values():
        children.sort(key=lambda n: n["value"], reverse=True)

    # --- Uncategorised companies per sector ---
    uncategorised_by_sector: dict[int, dict] = {}
    for row in (
        companies_qs.filter(industry__isnull=True, sector__isnull=False)
        .values("sector_id")
        .annotate(n=Count("id"), total_mc=Sum("latest_mc"))
    ):
        uncategorised_by_sector[row["sector_id"]] = {
            "n": row["n"],
            "mc": float(row["total_mc"] or 0),
        }

    result = []
    for sector in sectors:
        children = list(industries_by_sector.get(sector.pk, []))
        unc = uncategorised_by_sector.get(sector.pk)
        if unc and unc["n"] > 0:
            unc_val = unc["mc"] if use_market_cap else unc["n"]
            children.append(
                {
                    "name": "Other",
                    "value": unc_val,
                    "company_count": unc["n"],
                    "market_cap": unc["mc"],
                }
            )
        mc_val = sector_mc.get(sector.pk, 0) if use_market_cap else 0
        node_val = mc_val if use_market_cap else sector.company_count
        node: dict = {
            "name": sector.name,
            "value": node_val,
            "company_count": sector.company_count,
            "market_cap": mc_val,
        }
        if children:
            node["children"] = children
        result.append(node)

    return result


# ---------------------------------------------------------------------------
# Financials pivot
# ---------------------------------------------------------------------------


def get_financials_pivoted(
    company_id: int,
    statement_type: str | None = None,
    period: str | None = None,
    max_dates: int = 4,
) -> dict:
    """Return financial statements as {dates, rows} pivot table.

    dates  -- up to max_dates most-recent period_end values, descending.
    rows   -- [{metric, values: [v0, v1, ...]}] aligned to dates.
    """
    qs = FinancialStatement.objects.filter(company_id=company_id)
    if statement_type:
        qs = qs.filter(statement_type=statement_type)
    if period:
        qs = qs.filter(period=period)

    date_set: set[str] = set()
    metric_map: dict[str, dict[str, float | None]] = {}
    for row in qs.values("period_end", "metric", "value"):
        d = str(row["period_end"])
        date_set.add(d)
        metric_map.setdefault(row["metric"], {})[d] = row["value"]

    dates = sorted(date_set, reverse=True)[:max_dates]
    rows = [
        {"metric": metric, "values": [vals.get(d) for d in dates]}
        for metric, vals in metric_map.items()
    ]
    return {"dates": dates, "rows": rows}


# ---------------------------------------------------------------------------
# Bulk / background operations
# ---------------------------------------------------------------------------


def discover_and_create_stubs() -> int:
    """Scrape S&P 500 + NASDAQ-100 and bulk-create un-bootstrapped Company stubs.

    Existing symbols are skipped. Returns the count of new stubs created.
    """
    client = YFinanceClient()
    discovered = client.discover_tickers()
    existing = set(Company.objects.values_list("symbol", flat=True))
    seen: set[str] = set()
    new: list[Company] = []
    for symbol in discovered:
        if not symbol or symbol in existing or symbol in seen:
            continue
        seen.add(symbol)
        new.append(Company(symbol=symbol, name=symbol, is_bootstrapped=False))
    if new:
        Company.objects.bulk_create(new, batch_size=500)
    return len(new)


def bootstrap_next_batch(batch_size: int = 5) -> dict:
    """Fully ingest the next batch of un-bootstrapped companies.

    Processes symbols sequentially so peak memory stays flat. On success sets
    is_bootstrapped=True; leaves it False on failure so the next tick retries.
    Returns {"attempted": int, "ok": int, "failed": int}.
    """
    symbols = list(
        Company.objects.filter(is_bootstrapped=False)
        .order_by("id")
        .values_list("symbol", flat=True)[:batch_size]
    )
    ok = 0
    failed = 0
    for symbol in symbols:
        try:
            sync_all_for_symbol(symbol)
            Company.objects.filter(symbol=symbol).update(is_bootstrapped=True)
            ok += 1
        except Exception:
            logger.exception("bootstrap failed for %s", symbol)
            failed += 1
    return {"attempted": len(symbols), "ok": ok, "failed": failed}


def import_from_yfinance(
    symbols: list[str],
    on_progress: Callable[[str], None] | None = None,
) -> int:
    """Fetch yfinance profiles for the given symbols and upsert into the DB.

    Creates new Company rows for any symbols not yet present.
    Returns the count of rows created (not updated).
    """
    yf_client = YFinanceClient()
    existing = set(Company.objects.values_list("symbol", flat=True))
    created = 0

    profiles = yf_client.get_bulk_profiles(symbols, on_progress=on_progress)
    for symbol, data in profiles.items():
        is_new = symbol not in existing
        _apply_yf_profile(symbol, data)
        if is_new:
            created += 1

    return created


# ---------------------------------------------------------------------------
# Company summary generation
# ---------------------------------------------------------------------------
#
# UNIT CONVENTION (see also YFinanceClient.get_snapshot): every ratio on
# CompanySnapshot is a FRACTION - 0.0044 means 0.44%. The single deliberate
# exception is EarningsDate.surprise_pct, which is stored in PERCENT because the
# earnings chart reads it directly; it renders through _fmt_already_pct.
#
# _assemble_company_data stores raw NUMBERS (never pre-formatted strings) so the
# persisted data_snapshot can be diffed and recomputed against; formatting happens
# only in _build_prompt_text.

_SUMMARY_SYSTEM_PROMPT = (
    "You are a professional equity analyst. You are given structured financial data for one"
    " company, including peer medians for its industry or sector. Reply with a single JSON"
    " object and nothing else.\n\n"
    "Fields:\n"
    "  verdict:     one of buy, hold, sell, insufficient_data\n"
    "  confidence:  0.0-1.0, how strongly the supplied data supports that verdict\n"
    "  summary:     150-250 words of plain prose\n"
    "  key_drivers: 2-4 short phrases, each citing a number from the data\n"
    "  key_risks:   2-4 short phrases, each citing a number from the data\n\n"
    "Rules:\n"
    "- Use only the data supplied. Never invent a number, an event or a corporate action to"
    " explain a value you find surprising; if a value looks implausible, say so and lower"
    " your confidence.\n"
    "- Every claim must cite a number from the data.\n"
    "- Judge valuation RELATIVE to the peer medians given, not against absolute rules of"
    " thumb.\n"
    "- Say sell when the data warrants it. Sell criteria include: valuation multiples well"
    " above the peer median without matching growth or margins; contracting revenue or"
    " compressing margins versus the peer median; dividend coverage below 1.5x; a"
    " deteriorating balance sheet (debt/equity well above peers, current ratio below 1); a"
    " price far above analyst targets (negative implied upside).\n"
    "- Say insufficient_data when the data is too sparse to judge, and set a low confidence."
)

# The Ollama structured-output schema. Constraining the response removes the old
# regex-scraped "VERDICT:" trailing line entirely.
_SUMMARY_FORMAT: dict = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["buy", "hold", "sell", "insufficient_data"]},
        "confidence": {"type": "number"},
        "summary": {"type": "string"},
        "key_drivers": {"type": "array", "items": {"type": "string"}},
        "key_risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["verdict", "summary"],
}

# Sync types gated on, mapped to the LLMSettings field holding their max age in days.
_FRESHNESS_WINDOWS: tuple[tuple[str, str], ...] = (
    ("snapshot", "summary_snapshot_max_age_days"),
    ("price", "summary_price_max_age_days"),
    ("financials", "summary_financials_max_age_days"),
)

_ANNUAL_METRICS = [
    "Total Revenue",
    "Net Income",
    "Operating Income",
    "Free Cash Flow",
    "Total Debt",
    "Total Stockholder Equity",
    "Cash And Cash Equivalents",
]

# Snapshot metrics compared against the peer median, and whether they are fractions.
_PEER_METRICS: tuple[tuple[str, str, str], ...] = (
    ("trailing_pe", "Trailing P/E", "num"),
    ("forward_pe", "Forward P/E", "num"),
    ("price_to_book", "Price / Book", "num"),
    ("profit_margins", "Net margin", "pct"),
    ("return_on_equity", "Return on equity", "pct"),
    ("dividend_yield", "Dividend yield", "pct"),
    ("debt_to_equity", "Debt / Equity", "num"),
)


def _fmt_large(value: float | int | None) -> str:
    if value is None:
        return "N/A"
    v = float(value)
    if abs(v) >= 1e12:
        return f"${v / 1e12:.2f}T"
    if abs(v) >= 1e9:
        return f"${v / 1e9:.2f}B"
    if abs(v) >= 1e6:
        return f"${v / 1e6:.2f}M"
    return f"{v:.2f}"


def _fmt(value: float | None, pct: bool = False) -> str:
    """Render a stored value. ``pct=True`` means the value is a FRACTION."""
    if value is None:
        return "N/A"
    if pct:
        return f"{value * 100:.2f}%"
    return f"{value:.2f}"


def _fmt_already_pct(value: float | None) -> str:
    """Render a value that is ALREADY in percent (EarningsDate.surprise_pct)."""
    if value is None:
        return "N/A"
    return f"{value:.2f}%"


def _num(value) -> float | None:
    """Coerce a DB value (Decimal, int, float, None) to a JSON-safe float."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ratio(numerator, denominator) -> float | None:
    """Safe division; None when either side is missing or the denominator is zero."""
    a, b = _num(numerator), _num(denominator)
    if a is None or b is None or b == 0:
        return None
    return a / b


def _peer_group(company: Company):
    """Return (label, name, queryset_of_peers) for the company's benchmark group.

    Prefers the industry, falls back to the sector when the industry holds fewer than
    ``MIN_PEERS`` other companies, and returns None when neither does. The company
    itself is always excluded so it never drags its own median.

    Delegates to ``llm_analysis.tools.peer_group``, which the agents' ``peer_comparison``
    tool also uses (issue #13) - the group choice has one home, like the peer maths.
    """
    from apps.llm_analysis.tools import peer_group

    return peer_group(company)


def _peer_benchmark(company: Company, snapshot: CompanySnapshot | None) -> dict | None:
    """Company metrics beside their peer medians, or None when there is no usable group."""
    from apps.llm_analysis.tools import aggregate_snapshots

    group = _peer_group(company)
    if group is None:
        return None
    label, name, peers = group

    agg = aggregate_snapshots(peers)
    if not agg.get("with_snapshot"):
        return None

    metrics = {}
    for field, _, _ in _PEER_METRICS:
        stats = (agg.get("metrics") or {}).get(field) or {}
        metrics[field] = {
            "company": _num(getattr(snapshot, field, None)) if snapshot else None,
            "peer_median": stats.get("median"),
            "peer_n": stats.get("n"),
        }
        # Only the valuation ratios carry it: how many peers were left OUT of the median
        # because their P/E or P/B was negative (losses / negative equity - issue #9).
        if "negative" in stats:
            metrics[field]["peer_negative"] = stats["negative"]
    return {
        "group": label,
        "name": name,
        "peers": agg["with_snapshot"],
        "metrics": metrics,
    }


def _assemble_company_data(company: Company) -> dict:
    """Collect DB data for a company into a structured dict of NUMBERS for the LLM prompt."""
    data: dict = {
        "symbol": company.symbol,
        "name": company.name or company.symbol,
        "sector": str(company.sector) if company.sector else "N/A",
        "industry": str(company.industry) if company.industry else "N/A",
    }

    snapshot = CompanySnapshot.objects.filter(company=company).order_by("-fetched_at").first()
    latest_bar = PriceBar.objects.filter(company=company).order_by("-date").first()
    price = _num(latest_bar.close) if latest_bar else None

    if latest_bar or snapshot:
        high = _num(snapshot.fifty_two_week_high) if snapshot else None
        low = _num(snapshot.fifty_two_week_low) if snapshot else None
        band = None
        if price is not None and high is not None and low is not None and high > low:
            band = (price - low) / (high - low)
        data["price"] = {
            "close": price,
            "as_of": str(latest_bar.date) if latest_bar else None,
            "fifty_day_average": _num(snapshot.fifty_day_average) if snapshot else None,
            "two_hundred_day_average": (
                _num(snapshot.two_hundred_day_average) if snapshot else None
            ),
            "week52_high": high,
            "week52_low": low,
            "position_in_52w_range": band,
            "week52_change": _num(snapshot.week52_change) if snapshot else None,
            "sandp52_week_change": _num(snapshot.sandp52_week_change) if snapshot else None,
        }

    if snapshot:
        data["valuation"] = {
            "market_cap": _num(snapshot.market_cap),
            "trailing_pe": _num(snapshot.trailing_pe),
            "forward_pe": _num(snapshot.forward_pe),
            "price_to_book": _num(snapshot.price_to_book),
            "price_to_sales": _num(snapshot.price_to_sales),
            "enterprise_to_ebitda": _num(snapshot.enterprise_to_ebitda),
            "peg_ratio": _num(snapshot.peg_ratio),
            "beta": _num(snapshot.beta),
            "trailing_eps": _num(snapshot.trailing_eps),
            "forward_eps": _num(snapshot.forward_eps),
        }
        data["profitability"] = {
            "profit_margins": _num(snapshot.profit_margins),
            "gross_margins": _num(snapshot.gross_margins),
            "operating_margins": _num(snapshot.operating_margins),
            "ebitda_margins": _num(snapshot.ebitda_margins),
            "return_on_equity": _num(snapshot.return_on_equity),
            "return_on_assets": _num(snapshot.return_on_assets),
            "free_cashflow": _num(snapshot.free_cashflow),
            "total_cash": _num(snapshot.total_cash),
        }
        data["growth"] = {
            "revenue_growth_yoy": _num(snapshot.revenue_growth),
            "earnings_growth_yoy": _num(snapshot.earnings_growth),
            "earnings_quarterly_growth": _num(snapshot.earnings_quarterly_growth),
        }
        data["leverage"] = {
            "debt_to_equity": _num(snapshot.debt_to_equity),
            "current_ratio": _num(snapshot.current_ratio),
            "quick_ratio": _num(snapshot.quick_ratio),
        }
        target_mean = _num(snapshot.target_mean_price)
        data["analyst"] = {
            "recommendation": snapshot.recommendation_key or "N/A",
            "mean_score": _num(snapshot.recommendation_mean),
            "num_opinions": snapshot.num_analyst_opinions,
            "target_low": _num(snapshot.target_low_price),
            "target_mean": target_mean,
            "target_high": _num(snapshot.target_high_price),
            # Computed here so the model never has to do arithmetic; None (not 0) when
            # either side is missing.
            "implied_upside": (
                ((target_mean - price) / price)
                if (price not in (None, 0) and target_mean is not None)
                else None
            ),
        }

    peers = _peer_benchmark(company, snapshot)
    if peers:
        data["peers"] = peers

    dividends_qs = Dividend.objects.filter(company=company).order_by("-date")
    ttm_total = None
    cutoff = dt.now(UTC).date() - timedelta(days=365)
    ttm_rows = [d for d in dividends_qs.values("date", "amount")[:12] if d["date"] >= cutoff]
    if ttm_rows:
        ttm_total = float(sum(Dec(str(r["amount"])) for r in ttm_rows))

    if snapshot or ttm_total is not None:
        data["dividends"] = {
            "yield": _num(snapshot.dividend_yield) if snapshot else None,
            "payout_ratio": _num(snapshot.payout_ratio) if snapshot else None,
            "five_year_avg_yield": (
                _num(snapshot.five_year_avg_dividend_yield) if snapshot else None
            ),
            "ttm_total_per_share": ttm_total,
            "eps_coverage": _ratio(snapshot.trailing_eps if snapshot else None, ttm_total),
        }

    short = ShortInterest.objects.filter(company=company).order_by("-fetched_at").first()
    if short:
        prior = _num(short.shares_short_prior_month)
        current = _num(short.shares_short)
        data["short_interest"] = {
            "short_ratio": _num(short.short_ratio),
            "short_pct_of_float": _num(short.short_pct_of_float),
            "shares_short": current,
            "shares_short_prior_month": prior,
            "month_over_month_change": (
                ((current - prior) / prior)
                if (prior not in (None, 0) and current is not None)
                else None
            ),
        }

    annual_rows = (
        FinancialStatement.objects.filter(
            company=company,
            period="annual",
            metric__in=_ANNUAL_METRICS,
        )
        .order_by("-period_end")
        .values("metric", "period_end", "value")[:28]
    )
    if annual_rows:
        annuals: dict[str, dict] = {}
        for row in annual_rows:
            yr = str(row["period_end"])
            annuals.setdefault(yr, {})[row["metric"]] = _num(row["value"])
        data["annual_financials"] = annuals

    quarterly_rows = (
        FinancialStatement.objects.filter(
            company=company,
            period="quarterly",
            metric__in=["Total Revenue", "Net Income", "Free Cash Flow"],
        )
        .order_by("-period_end")
        .values("metric", "period_end", "value")[:12]
    )
    if quarterly_rows:
        quarters: dict[str, dict] = {}
        for row in quarterly_rows:
            qtr = str(row["period_end"])
            quarters.setdefault(qtr, {})[row["metric"]] = _num(row["value"])
        data["quarterly_financials"] = quarters

    reported = list(
        EarningsDate.objects.filter(company=company, reported_eps__isnull=False)
        .order_by("-earnings_date")
        .values("earnings_date", "reported_eps", "eps_estimate", "surprise_pct")[:4]
    )
    if reported:
        data["earnings_history"] = [
            {
                "date": str(r["earnings_date"]),
                "reported_eps": _num(r["reported_eps"]),
                "estimated_eps": _num(r["eps_estimate"]),
                # PERCENT, not a fraction - see the unit note at the top of this section.
                "surprise_pct": _num(r["surprise_pct"]),
            }
            for r in reported
        ]
        beats = sum(1 for r in reported if (r["surprise_pct"] or 0) > 0)
        data["earnings_beat_streak"] = {"beats": beats, "quarters": len(reported)}

    upcoming_earnings = (
        EarningsDate.objects.filter(company=company, is_upcoming=True)
        .order_by("earnings_date")
        .first()
    )
    if upcoming_earnings:
        data["upcoming_earnings_date"] = str(upcoming_earnings.earnings_date)

    recent_dividends = list(dividends_qs.values("date", "amount")[:4])
    if recent_dividends:
        data["recent_dividends"] = [
            {"date": str(d["date"]), "amount": _num(d["amount"])} for d in recent_dividends
        ]

    return data


# (key, label, kind) per prompt section. kind: money | num | pct | pct_raw | int | str
_SECTION_SPECS: tuple[tuple[str, str, tuple[tuple[str, str, str], ...]], ...] = (
    (
        "price",
        "Price & Technicals",
        (
            ("close", "last close", "num"),
            ("as_of", "as of", "str"),
            ("fifty_day_average", "50-day average", "num"),
            ("two_hundred_day_average", "200-day average", "num"),
            ("week52_high", "52-week high", "num"),
            ("week52_low", "52-week low", "num"),
            ("position_in_52w_range", "position in 52-week range", "pct"),
            ("week52_change", "52-week change", "pct"),
            ("sandp52_week_change", "S&P 500 52-week change", "pct"),
        ),
    ),
    (
        "valuation",
        "Valuation",
        (
            ("market_cap", "market cap", "money"),
            ("trailing_pe", "trailing P/E", "num"),
            ("forward_pe", "forward P/E", "num"),
            ("price_to_book", "price/book", "num"),
            ("price_to_sales", "price/sales", "num"),
            ("enterprise_to_ebitda", "EV/EBITDA", "num"),
            ("peg_ratio", "PEG ratio", "num"),
            ("beta", "beta", "num"),
            ("trailing_eps", "trailing EPS", "num"),
            ("forward_eps", "forward EPS", "num"),
        ),
    ),
    (
        "profitability",
        "Profitability",
        (
            ("gross_margins", "gross margin", "pct"),
            ("operating_margins", "operating margin", "pct"),
            ("ebitda_margins", "EBITDA margin", "pct"),
            ("profit_margins", "net margin", "pct"),
            ("return_on_equity", "return on equity", "pct"),
            ("return_on_assets", "return on assets", "pct"),
            ("free_cashflow", "free cash flow", "money"),
            ("total_cash", "total cash", "money"),
        ),
    ),
    (
        "growth",
        "Growth",
        (
            ("revenue_growth_yoy", "revenue growth YoY", "pct"),
            ("earnings_growth_yoy", "earnings growth YoY", "pct"),
            ("earnings_quarterly_growth", "quarterly earnings growth", "pct"),
        ),
    ),
    (
        "leverage",
        "Leverage & Liquidity",
        (
            ("debt_to_equity", "debt/equity", "num"),
            ("current_ratio", "current ratio", "num"),
            ("quick_ratio", "quick ratio", "num"),
        ),
    ),
    (
        "dividends",
        "Dividends",
        (
            ("yield", "dividend yield", "pct"),
            ("five_year_avg_yield", "5-year average yield", "pct"),
            ("payout_ratio", "payout ratio", "pct"),
            ("ttm_total_per_share", "dividends paid (TTM, per share)", "num"),
            ("eps_coverage", "EPS / dividends coverage", "num"),
        ),
    ),
    (
        "analyst",
        "Analyst Consensus",
        (
            ("recommendation", "recommendation", "str"),
            ("mean_score", "mean score (1=buy, 5=sell)", "num"),
            ("num_opinions", "analysts covering", "int"),
            ("target_low", "target low", "num"),
            ("target_mean", "target mean", "num"),
            ("target_high", "target high", "num"),
            ("implied_upside", "implied upside vs last close", "pct"),
        ),
    ),
    (
        "short_interest",
        "Short Interest",
        (
            ("short_ratio", "short ratio (days to cover)", "num"),
            ("short_pct_of_float", "short % of float", "pct"),
            ("shares_short", "shares short", "int"),
            ("shares_short_prior_month", "shares short (prior month)", "int"),
            ("month_over_month_change", "month-over-month change", "pct"),
        ),
    ),
)


def _render(value, kind: str) -> str:
    if value is None:
        return "N/A"
    if kind == "money":
        return _fmt_large(value)
    if kind == "pct":
        return _fmt(value, pct=True)
    if kind == "pct_raw":
        return _fmt_already_pct(value)
    if kind == "int":
        return f"{int(value):,}"
    if kind == "num":
        return _fmt(value)
    return str(value)


def _build_prompt_text(data: dict) -> str:
    lines = [
        f"Company: {data['name']} ({data['symbol']})",
        f"Sector: {data['sector']} | Industry: {data['industry']}",
        "",
    ]

    for section_key, title, fields in _SECTION_SPECS:
        section = data.get(section_key)
        if not section:
            continue
        lines.append(f"[{title}]")
        for key, label, kind in fields:
            lines.append(f"  {label}: {_render(section.get(key), kind)}")
        lines.append("")

    peers = data.get("peers")
    if peers:
        lines.append(
            f"[Peer Benchmark - {peers['name']} ({peers['group']}), "
            f"{peers['peers']} peers with data]"
        )
        for field, label, kind in _PEER_METRICS:
            row = (peers.get("metrics") or {}).get(field) or {}
            own = row.get("company")
            if field in VALUATION_RATIOS and own is not None and own < 0:
                # A negative P/E or P/B is losses or negative book equity, not a low valuation:
                # set beside a peer median it reads as "far cheaper than peers". No number is
                # better than that one (issue #9), so the median is withheld for this line.
                lines.append(
                    f"  {label}: company {_render(own, kind)}"
                    " (negative - losses or negative equity, no meaningful peer comparison)"
                )
                continue
            lines.append(
                f"  {label}: company {_render(own, kind)}"
                f" vs peer median {_render(row.get('peer_median'), kind)}"
            )
        lines.append("")

    if "earnings_history" in data:
        streak = data.get("earnings_beat_streak") or {}
        lines.append("[Recent Reported Earnings (most recent first)]")
        for row in data["earnings_history"]:
            lines.append(
                f"  {row['date']}: reported EPS {_render(row['reported_eps'], 'num')}"
                f" vs estimate {_render(row['estimated_eps'], 'num')}"
                f" (surprise {_render(row['surprise_pct'], 'pct_raw')})"
            )
        if streak:
            lines.append(f"  beats: {streak['beats']} of the last {streak['quarters']} quarters")
        lines.append("")

    if "upcoming_earnings_date" in data:
        lines.append(f"Upcoming earnings: {data['upcoming_earnings_date']}\n")

    if "annual_financials" in data:
        lines.append("[Annual Financials (most recent 4 years)]")
        for period, metrics in sorted(data["annual_financials"].items(), reverse=True):
            lines.append(f"  {period}:")
            for metric, val in metrics.items():
                lines.append(f"    {metric}: {_fmt_large(val)}")
        lines.append("")

    if "quarterly_financials" in data:
        lines.append("[Quarterly Financials (most recent quarters)]")
        for period, metrics in sorted(data["quarterly_financials"].items(), reverse=True):
            lines.append(f"  {period}:")
            for metric, val in metrics.items():
                lines.append(f"    {metric}: {_fmt_large(val)}")
        lines.append("")

    if "recent_dividends" in data:
        lines.append("[Recent Dividends]")
        for d in data["recent_dividends"]:
            lines.append(f"  {d['date']}: {_render(d['amount'], 'num')}")
        lines.append("")

    return "\n".join(lines)


def _parse_summary_response(response: str) -> dict:
    """Tolerantly parse the model's structured summary.

    Anything unusable - non-JSON, a missing/unknown verdict - degrades to an
    ``insufficient_data`` row rather than raising, exactly as the old regex did.
    """
    from apps.llm_analysis._json import parse_json_object

    try:
        payload = parse_json_object(response)
    except ValueError:
        logger.warning("Summary response was not JSON; defaulting to insufficient_data")
        return {
            "verdict": CompanySummary.Verdict.INSUFFICIENT_DATA,
            "confidence": None,
            "summary": response.strip(),
            "key_drivers": [],
            "key_risks": [],
        }

    raw_verdict = str(payload.get("verdict", "")).strip().lower()
    valid = {v.value for v in CompanySummary.Verdict}
    if raw_verdict not in valid:
        logger.warning("Unusable verdict %r; defaulting to insufficient_data", raw_verdict)
        raw_verdict = CompanySummary.Verdict.INSUFFICIENT_DATA

    confidence = payload.get("confidence")
    try:
        confidence = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        confidence = None
    if confidence is not None:
        # Models occasionally answer 85 for "85%" or a negative number. Clamp into range
        # rather than persist something the UI would render as 8500%.
        confidence = min(max(confidence, 0.0), 1.0)

    def _phrases(key: str) -> list[str]:
        value = payload.get(key)
        if not isinstance(value, list):
            return []
        return [str(v).strip() for v in value if str(v).strip()][:6]

    summary = str(payload.get("summary") or "").strip() or response.strip()
    return {
        "verdict": raw_verdict,
        "confidence": confidence,
        "summary": summary,
        "key_drivers": _phrases("key_drivers"),
        "key_risks": _phrases("key_risks"),
    }


def _ingested_at(company: Company) -> dict[str, object]:
    """Newest ingestion timestamp per gated sync type, derived from the DATA itself.

    The safety net behind CompanySyncRecord: an ingestion path that forgets to call
    record_sync still cannot make fresh data look stale. Each value is the moment a
    row was last written, not the period it describes -- PriceBar.created_at rather
    than PriceBar.date, so a stale-dated bar written today counts as today.
    """
    latest = {
        "snapshot": company.snapshots.aggregate(v=Max("fetched_at"))["v"],
        "price": company.prices.aggregate(v=Max("created_at"))["v"],
        "financials": company.financials.aggregate(v=Max("updated_at"))["v"],
    }
    return {k: v for k, v in latest.items() if v is not None}


def _stale_sync_reasons(company: Company) -> list[str]:
    """Names of the sync types whose data is too old (or absent) to opine on.

    Freshness is the LATER of the bookkeeping row (CompanySyncRecord, written by
    record_sync) and the newest actual row of that kind (see _ingested_at), so the
    gate never blocks on data that is demonstrably fresh just because nobody
    recorded the sync. Neither present counts as stale: never-synced is not fresh.
    """
    from apps.llm_analysis.config import get_llm_config

    config = get_llm_config()
    now = dt.now(UTC)
    records = {
        r.sync_type: r.last_synced_at
        for r in CompanySyncRecord.objects.filter(
            company=company, sync_type__in=[t for t, _ in _FRESHNESS_WINDOWS]
        )
    }
    ingested = _ingested_at(company)

    reasons = []
    for sync_type, field in _FRESHNESS_WINDOWS:
        max_age = getattr(config, field)
        candidates = [t for t in (records.get(sync_type), ingested.get(sync_type)) if t is not None]
        if not candidates:
            reasons.append(f"{sync_type} has never been synced")
            continue
        age_days = (now - max(candidates)).days
        if age_days > max_age:
            reasons.append(f"{sync_type} last synced {age_days} days ago (limit {max_age} days)")
    return reasons


def generate_company_summary(symbol: str) -> CompanySummary:
    """Assemble company data, call Ollama, persist and return a CompanySummary row.

    Refuses to opine on stale data: if any gated sync type is outside its freshness
    window the row is written as ``insufficient_data`` with ZERO LLM calls.

    Raises Company.DoesNotExist if symbol not found.
    Raises OllamaServiceError on LLM failure.
    """
    from django.conf import settings

    company = Company.objects.select_related("sector", "industry").get(symbol=symbol)
    data = _assemble_company_data(company)
    model_name = getattr(settings, "OLLAMA_MAIN_MODEL", "unknown")

    stale = _stale_sync_reasons(company)
    if stale:
        data["stale_data"] = stale
        return CompanySummary.objects.create(
            company=company,
            model_name=model_name,
            verdict=CompanySummary.Verdict.INSUFFICIENT_DATA,
            confidence=None,
            summary=("Not enough up-to-date data to form a view: " + "; ".join(stale) + "."),
            key_risks=[],
            key_drivers=[],
            data_snapshot=data,
        )

    prompt_text = _build_prompt_text(data)
    messages = [
        {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": prompt_text},
    ]
    response_text = ollama_chat(messages, format=_SUMMARY_FORMAT)
    parsed = _parse_summary_response(response_text)

    return CompanySummary.objects.create(
        company=company,
        model_name=model_name,
        verdict=parsed["verdict"],
        confidence=parsed["confidence"],
        summary=parsed["summary"],
        key_risks=parsed["key_risks"],
        key_drivers=parsed["key_drivers"],
        data_snapshot=data,
    )
