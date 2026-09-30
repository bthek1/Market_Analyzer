import csv
import io
import logging
import math
import time
from collections.abc import Callable
from datetime import UTC, date
from datetime import datetime as dt
from decimal import Decimal, InvalidOperation

import httpx
import yfinance as yf

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
}

# Yahoo Finance exchange code -> Company.Exchange choice value
_EXCHANGE_MAP: dict[str, str] = {
    "NMS": "NASDAQ",
    "NGM": "NASDAQ",
    "NCM": "NASDAQ",
    "NYQ": "NYSE",
    "NYS": "NYSE",
    "AMX": "AMEX",
    "PCX": "NYSE_ARCA",
    "LSE": "LSE",
    "ASX": "ASX",
    "TSX": "TSX",
}

# Known ISO currency codes that match Company.Currency choices
_KNOWN_CURRENCIES = {"USD", "EUR", "GBP", "AUD", "CAD", "JPY", "CHF", "HKD", "CNY"}

_FETCH_DELAY = 0.1  # seconds between individual ticker fetches


def _epoch_to_date(value: object) -> date | None:
    """Convert a Unix timestamp int to a date. Returns None for missing/invalid values."""
    if value is None:
        return None
    try:
        return dt.fromtimestamp(int(value), tz=UTC).date()
    except (TypeError, ValueError, OSError):
        return None


def _normalize_profile(symbol: str, info: dict) -> dict | None:
    """Convert a yfinance info dict into a profile dict for Company.

    Returns None when info is empty (ticker not found / delisted).
    """
    if not info or not info.get("symbol"):
        return None

    exchange_raw = info.get("exchange", "")
    exchange = _EXCHANGE_MAP.get(exchange_raw, "")

    currency_raw = (info.get("currency") or "").upper()
    currency = currency_raw if currency_raw in _KNOWN_CURRENCIES else ""

    officers_raw = info.get("companyOfficers") or []
    officers = []
    for o in officers_raw:
        if not isinstance(o, dict):
            continue
        officers.append(
            {
                "name": o.get("name", ""),
                "title": o.get("title", ""),
                "age": o.get("age"),
                "year_born": o.get("yearBorn"),
                "fiscal_year": o.get("fiscalYear"),
                "total_pay": o.get("totalPay"),
                "exercised_value": o.get("exercisedValue"),
                "unexercised_value": o.get("unexercisedValue"),
            }
        )

    employees = info.get("fullTimeEmployees")
    if employees is not None:
        try:
            employees = int(employees)
        except (TypeError, ValueError):
            employees = None

    return {
        "name": info.get("longName") or info.get("shortName") or symbol,
        "exchange": exchange,
        "currency": currency,
        "sector": info.get("sector", ""),
        "industry": info.get("industry", ""),
        "address": info.get("address1", ""),
        "city": info.get("city", ""),
        "state": info.get("state", ""),
        "zip_code": info.get("zip", ""),
        "country": info.get("country", ""),
        "phone": info.get("phone", ""),
        "website": info.get("website", ""),
        "ir_website": info.get("irWebsite", ""),
        "description": info.get("longBusinessSummary", ""),
        "full_time_employees": employees,
        "officers": officers,
    }


class YFinanceClient:
    """Fetch company data from Yahoo Finance via the yfinance library."""

    # ------------------------------------------------------------------
    # Ticker discovery
    # ------------------------------------------------------------------

    def discover_tickers(self) -> list[str]:
        """Return a deduplicated list of tickers from S&P 500 and NASDAQ-100."""
        tickers: list[str] = []
        tickers.extend(self._sp500_tickers())
        tickers.extend(self._nasdaq100_tickers())
        seen: set[str] = set()
        result: list[str] = []
        for t in tickers:
            if t and t not in seen:
                seen.add(t)
                result.append(t)
        return result

    def _sp500_tickers(self) -> list[str]:
        try:
            url = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/master/data/constituents.csv"
            resp = httpx.get(url, timeout=15, follow_redirects=True, headers=_HEADERS)
            resp.raise_for_status()
            reader = csv.DictReader(io.StringIO(resp.text))
            return [row["Symbol"].replace(".", "-") for row in reader if row.get("Symbol")]
        except Exception:
            logger.exception("failed to fetch S&P 500 tickers")
            return []

    def _nasdaq100_tickers(self) -> list[str]:
        try:
            url = "https://api.nasdaq.com/api/quote/list-type/nasdaq100"
            resp = httpx.get(url, timeout=15, follow_redirects=True, headers=_HEADERS)
            resp.raise_for_status()
            rows = resp.json()["data"]["data"]["rows"]
            return [r["symbol"] for r in rows if r.get("symbol")]
        except Exception:
            logger.exception("failed to fetch NASDAQ-100 tickers")
            return []

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------

    def get_profile(self, symbol: str) -> dict | None:
        """Fetch and normalise a single symbol's profile from Yahoo Finance."""
        try:
            info = yf.Ticker(symbol).info
            return _normalize_profile(symbol, info)
        except Exception:
            return None

    def get_bulk_profiles(
        self,
        symbols: list[str],
        delay: float = _FETCH_DELAY,
        batch_size: int = 50,
        on_progress: Callable[[str], None] | None = None,
    ) -> dict[str, dict]:
        """Fetch profiles for multiple symbols, returning only successful results."""
        results: dict[str, dict] = {}
        for i, symbol in enumerate(symbols):
            try:
                info = yf.Ticker(symbol).info
                profile = _normalize_profile(symbol, info)
                if profile:
                    results[symbol] = profile
            except Exception:
                pass
            if on_progress:
                on_progress(symbol)
            if delay:
                time.sleep(delay)
            if batch_size and (i + 1) % batch_size == 0 and (i + 1) < len(symbols):
                time.sleep(2.0)
        return results

    # ------------------------------------------------------------------
    # Price history
    # ------------------------------------------------------------------

    def get_price_history(
        self,
        symbol: str,
        period: str | None = None,
        start: date | None = None,
    ) -> list[dict]:
        """Return OHLCV bars for the given symbol.

        Pass `start` for incremental fetches (since a known date).
        Pass `period` for yfinance period strings (e.g. "max", "5d").
        If neither is given, defaults to period="max".

        Each dict: {date, open, high, low, close (all Decimal), volume (int)}.
        Rows where close is NaN are skipped.
        """
        try:
            ticker = yf.Ticker(symbol)
            if start is not None:
                df = ticker.history(start=str(start))
            else:
                df = ticker.history(period=period or "max")
        except Exception:
            return []

        if df is None or df.empty:
            return []

        rows: list[dict] = []
        for ts, row in df.iterrows():
            close = row.get("Close")
            if close is None:
                continue
            try:
                if math.isnan(float(close)):
                    continue
            except (TypeError, ValueError):
                continue

            bar_date: date = ts.date() if hasattr(ts, "date") else ts
            try:
                rows.append(
                    {
                        "date": bar_date,
                        "open": Decimal(str(row["Open"])),
                        "high": Decimal(str(row["High"])),
                        "low": Decimal(str(row["Low"])),
                        "close": Decimal(str(close)),
                        "volume": int(row["Volume"]),
                    }
                )
            except (InvalidOperation, KeyError):
                continue

        return rows

    # ------------------------------------------------------------------
    # Snapshot (point-in-time market metrics)
    # ------------------------------------------------------------------

    def get_snapshot(self, symbol: str) -> dict | None:
        """Return current market metrics for the given symbol.

        Also fetches Ticker.recommendations and includes the per-period breakdown.
        Returns None when yfinance returns no usable data.

        UNIT CONVENTION: every ratio stored on ``CompanySnapshot`` is a FRACTION
        (0.0044 = 0.44%). yfinance is inconsistent - ``profitMargins`` and
        ``returnOnEquity`` already arrive as fractions, while ``dividendYield``,
        ``fiveYearAvgDividendYield`` and ``debtToEquity`` arrive scaled to PERCENT
        (0.44, 154.49). Those three are divided by 100 here, at ingestion, so every
        reader can assume the fraction convention. ``EarningsDate.surprise_pct`` is
        the one deliberate exception: it stays in percent (the earnings chart reads
        it directly) and is rendered through ``_fmt_already_pct``.
        """
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
        except Exception:
            return None

        if not info or not info.get("symbol"):
            return None

        def _float(key: str) -> float | None:
            val = info.get(key)
            try:
                return float(val) if val is not None else None
            except (TypeError, ValueError):
                return None

        def _int(key: str) -> int | None:
            val = info.get(key)
            try:
                return int(val) if val is not None else None
            except (TypeError, ValueError):
                return None

        def _small_int(key: str) -> int | None:
            val = info.get(key)
            try:
                return int(val) if val is not None else None
            except (TypeError, ValueError):
                return None

        def _pct_to_fraction(key: str) -> float | None:
            """yfinance gives this field in percent; store it as a fraction."""
            val = _float(key)
            return None if val is None else val / 100.0

        def _str(key: str) -> str | None:
            val = info.get(key)
            return str(val) if val is not None else None

        recommendations_breakdown = self._parse_recommendations(ticker)

        return {
            # Original fields
            "market_cap": _int("marketCap"),
            "trailing_pe": _float("trailingPE"),
            "forward_pe": _float("forwardPE"),
            "price_to_book": _float("priceToBook"),
            "debt_to_equity": _pct_to_fraction("debtToEquity"),
            "return_on_equity": _float("returnOnEquity"),
            "profit_margins": _float("profitMargins"),
            "dividend_yield": _pct_to_fraction("dividendYield"),
            "trailing_eps": _float("trailingEps"),
            "forward_eps": _float("forwardEps"),
            # Valuation extensions
            "beta": _float("beta"),
            "fifty_two_week_high": _float("fiftyTwoWeekHigh"),
            "fifty_two_week_low": _float("fiftyTwoWeekLow"),
            "week52_change": _float("52WeekChange"),
            "sandp52_week_change": _float("SandP52WeekChange"),
            "average_volume": _int("averageVolume"),
            "shares_outstanding": _int("sharesOutstanding"),
            "float_shares": _int("floatShares"),
            "enterprise_value": _int("enterpriseValue"),
            "enterprise_to_revenue": _float("enterpriseToRevenue"),
            "enterprise_to_ebitda": _float("enterpriseToEbitda"),
            "peg_ratio": _float("pegRatio"),
            "trailing_peg_ratio": _float("trailingPegRatio"),
            "price_to_sales": _float("priceToSalesTrailingTwelveMonths"),
            "payout_ratio": _float("payoutRatio"),
            "book_value": _float("bookValue"),
            # Technical
            "fifty_day_average": _float("fiftyDayAverage"),
            "two_hundred_day_average": _float("twoHundredDayAverage"),
            # Growth
            "revenue_growth": _float("revenueGrowth"),
            "earnings_growth": _float("earningsGrowth"),
            "earnings_quarterly_growth": _float("earningsQuarterlyGrowth"),
            # Margins
            "gross_margins": _float("grossMargins"),
            "operating_margins": _float("operatingMargins"),
            "ebitda_margins": _float("ebitdaMargins"),
            # Liquidity
            "current_ratio": _float("currentRatio"),
            "quick_ratio": _float("quickRatio"),
            # Profitability
            "return_on_assets": _float("returnOnAssets"),
            "ebitda": _int("ebitda"),
            "total_cash": _int("totalCash"),
            "total_cash_per_share": _float("totalCashPerShare"),
            "free_cashflow": _int("freeCashflow"),
            "operating_cashflow": _int("operatingCashflow"),
            "net_income_to_common": _int("netIncomeToCommon"),
            "revenue_per_share": _float("revenuePerShare"),
            # Ownership
            "held_pct_institutions": _float("heldPercentInstitutions"),
            "held_pct_insiders": _float("heldPercentInsiders"),
            # Dividend snapshot
            "dividend_rate": _float("dividendRate"),
            "ex_dividend_date": _epoch_to_date(info.get("exDividendDate")),
            "five_year_avg_dividend_yield": _pct_to_fraction("fiveYearAvgDividendYield"),
            "trailing_annual_dividend_rate": _float("trailingAnnualDividendRate"),
            "last_dividend_value": _float("lastDividendValue"),
            "last_dividend_date": _epoch_to_date(info.get("lastDividendDate")),
            # Fiscal calendar
            "last_fiscal_year_end": _epoch_to_date(info.get("lastFiscalYearEnd")),
            "next_fiscal_year_end": _epoch_to_date(info.get("nextFiscalYearEnd")),
            "most_recent_quarter": _epoch_to_date(info.get("mostRecentQuarter")),
            # Governance risk
            "audit_risk": _small_int("auditRisk"),
            "board_risk": _small_int("boardRisk"),
            "compensation_risk": _small_int("compensationRisk"),
            "shareholder_rights_risk": _small_int("shareHolderRightsRisk"),
            "overall_risk": _small_int("overallRisk"),
            # Analyst consensus
            "recommendation_mean": _float("recommendationMean"),
            "recommendation_key": _str("recommendationKey"),
            "num_analyst_opinions": _int("numberOfAnalystOpinions"),
            "target_high_price": _float("targetHighPrice"),
            "target_low_price": _float("targetLowPrice"),
            "target_mean_price": _float("targetMeanPrice"),
            "target_median_price": _float("targetMedianPrice"),
            "recommendations_breakdown": recommendations_breakdown,
            # Split history
            "last_split_factor": _str("lastSplitFactor"),
            "last_split_date": _epoch_to_date(info.get("lastSplitDate")),
            "raw": info,
        }

    def _parse_recommendations(self, ticker: "yf.Ticker") -> list[dict]:
        """Parse Ticker.recommendations into a list of period dicts."""
        try:
            df = ticker.recommendations
        except Exception:
            return []
        if df is None or df.empty:
            return []
        rows = []
        try:
            for period, row in df.iterrows():
                rows.append(
                    {
                        "period": str(period),
                        "strong_buy": int(row.get("strongBuy", 0) or 0),
                        "buy": int(row.get("buy", 0) or 0),
                        "hold": int(row.get("hold", 0) or 0),
                        "sell": int(row.get("sell", 0) or 0),
                        "strong_sell": int(row.get("strongSell", 0) or 0),
                    }
                )
        except Exception:
            logger.exception("failed to parse recommendations for ticker")
        return rows

    # ------------------------------------------------------------------
    # Short interest (from info dict)
    # ------------------------------------------------------------------

    def get_short_interest(self, symbol: str) -> dict | None:
        """Extract short interest fields from Ticker.info.

        Returns None when info is missing or fields are all absent.
        """
        try:
            info = yf.Ticker(symbol).info
        except Exception:
            return None

        if not info or not info.get("symbol"):
            return None

        def _float(key: str) -> float | None:
            val = info.get(key)
            try:
                return float(val) if val is not None else None
            except (TypeError, ValueError):
                return None

        def _int(key: str) -> int | None:
            val = info.get(key)
            try:
                return int(val) if val is not None else None
            except (TypeError, ValueError):
                return None

        return {
            "date_short_interest": _epoch_to_date(info.get("dateShortInterest")),
            "shares_short": _int("sharesShort"),
            "shares_short_prior_month": _int("sharesShortPriorMonth"),
            "short_ratio": _float("shortRatio"),
            "short_pct_of_float": _float("shortPercentOfFloat"),
            "shares_pct_shares_out": _float("sharesPercentSharesOut"),
        }

    def get_short_interest_from_raw(self, raw: dict) -> dict | None:
        """Extract short interest from an already-fetched raw info dict."""
        if not raw:
            return None

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

        return {
            "date_short_interest": _epoch_to_date(raw.get("dateShortInterest")),
            "shares_short": _int("sharesShort"),
            "shares_short_prior_month": _int("sharesShortPriorMonth"),
            "short_ratio": _float("shortRatio"),
            "short_pct_of_float": _float("shortPercentOfFloat"),
            "shares_pct_shares_out": _float("sharesPercentSharesOut"),
        }

    # ------------------------------------------------------------------
    # Institutional holders
    # ------------------------------------------------------------------

    def get_institutional_holders(self, symbol: str) -> list[dict]:
        """Return institutional holders as a list of dicts.

        Parses Ticker.institutional_holders DataFrame. Returns [] on failure.
        """
        try:
            df = yf.Ticker(symbol).institutional_holders
        except Exception:
            return []
        if df is None or df.empty:
            return []
        rows = []
        try:
            for _, row in df.iterrows():
                date_reported = row.get("Date Reported")
                if hasattr(date_reported, "date"):
                    date_reported = date_reported.date().isoformat()
                elif date_reported is not None:
                    date_reported = str(date_reported)
                else:
                    date_reported = None
                pct_out = row.get("% Out") or row.get("pctHeld")
                try:
                    pct_out = float(pct_out) if pct_out is not None else None
                except (TypeError, ValueError):
                    pct_out = None
                value = row.get("Value")
                try:
                    value = int(value) if value is not None else None
                except (TypeError, ValueError):
                    value = None
                shares = row.get("Shares")
                try:
                    shares = int(shares) if shares is not None else None
                except (TypeError, ValueError):
                    shares = None
                rows.append(
                    {
                        "holder": str(row.get("Holder", "") or ""),
                        "shares": shares,
                        "date_reported": date_reported,
                        "pct_out": pct_out,
                        "value": value,
                    }
                )
        except Exception:
            logger.exception("failed to parse institutional holders")
        return rows

    # ------------------------------------------------------------------
    # Earnings dates
    # ------------------------------------------------------------------

    def get_earnings_dates(self, symbol: str) -> list[dict]:
        """Return earnings date records as a list of dicts.

        Handles NaT/NaN gracefully. Returns [] on failure.
        Each dict: {earnings_date (date), eps_estimate, reported_eps, surprise_pct}.
        """
        try:
            df = yf.Ticker(symbol).earnings_dates
        except Exception:
            return []
        if df is None or df.empty:
            return []
        rows = []
        today = dt.now(UTC).date()
        try:
            for ts, row in df.iterrows():
                try:
                    earnings_date = ts.date() if hasattr(ts, "date") else ts
                    if earnings_date is None:
                        continue
                except Exception:
                    continue

                def _safe_float(val: object) -> float | None:
                    if val is None:
                        return None
                    try:
                        f = float(val)
                        return None if math.isnan(f) else f
                    except (TypeError, ValueError):
                        return None

                rows.append(
                    {
                        "earnings_date": earnings_date,
                        "eps_estimate": _safe_float(row.get("EPS Estimate")),
                        "reported_eps": _safe_float(row.get("Reported EPS")),
                        "surprise_pct": _safe_float(row.get("Surprise(%)")),
                        "is_upcoming": earnings_date > today,
                    }
                )
        except Exception:
            logger.exception("failed to parse earnings dates")
        return rows

    # ------------------------------------------------------------------
    # Options chains
    # ------------------------------------------------------------------

    def get_options_chain(self, symbol: str, max_expiries: int = 4) -> list[dict]:
        """Return options chain data for the nearest `max_expiries` expiry dates.

        Each element: {expiry_date (date), calls: [contract_dict], puts: [contract_dict]}.
        Returns [] on failure or when no options exist.
        """
        try:
            ticker = yf.Ticker(symbol)
            expiries = ticker.options
        except Exception:
            return []
        if not expiries:
            return []

        results = []
        for expiry_str in expiries[:max_expiries]:
            try:
                chain = ticker.option_chain(expiry_str)
                expiry_date = dt.strptime(expiry_str, "%Y-%m-%d").date()
                calls = self._parse_option_df(chain.calls, "call")
                puts = self._parse_option_df(chain.puts, "put")
                results.append({"expiry_date": expiry_date, "calls": calls, "puts": puts})
            except Exception:
                logger.exception("failed to parse option chain for expiry %s", expiry_str)
                continue

        return results

    def _parse_option_df(self, df: object, option_type: str) -> list[dict]:
        if df is None or getattr(df, "empty", True):
            return []
        rows = []
        try:
            for _, row in df.iterrows():

                def _safe_decimal(val: object) -> str | None:
                    if val is None:
                        return None
                    try:
                        f = float(val)
                        return None if math.isnan(f) else str(round(f, 4))
                    except (TypeError, ValueError):
                        return None

                def _safe_float(val: object) -> float | None:
                    if val is None:
                        return None
                    try:
                        f = float(val)
                        return None if math.isnan(f) else f
                    except (TypeError, ValueError):
                        return None

                def _safe_int(val: object) -> int | None:
                    if val is None:
                        return None
                    try:
                        return int(val)
                    except (TypeError, ValueError):
                        return None

                in_money = row.get("inTheMoney")
                if in_money is not None:
                    try:
                        in_money = bool(in_money)
                    except Exception:
                        in_money = None

                rows.append(
                    {
                        "option_type": option_type,
                        "contract_symbol": str(row.get("contractSymbol", "") or ""),
                        "strike": _safe_decimal(row.get("strike")),
                        "last_price": _safe_decimal(row.get("lastPrice")),
                        "bid": _safe_decimal(row.get("bid")),
                        "ask": _safe_decimal(row.get("ask")),
                        "volume": _safe_int(row.get("volume")),
                        "open_interest": _safe_int(row.get("openInterest")),
                        "implied_volatility": _safe_float(row.get("impliedVolatility")),
                        "in_the_money": in_money,
                    }
                )
        except Exception:
            logger.exception("failed to parse option contracts")
        return rows

    # ------------------------------------------------------------------
    # Financial statements
    # ------------------------------------------------------------------

    def get_financials(self, symbol: str) -> list[dict]:
        """Return melted financial statement rows for the given symbol.

        Each dict: {statement_type, period, period_end (date), metric (str), value (float|None)}.
        Sources: income_stmt, balance_sheet, cashflow (annual + quarterly).
        """
        ticker = yf.Ticker(symbol)
        sources = [
            (ticker.income_stmt, "income", "annual"),
            (ticker.quarterly_income_stmt, "income", "quarterly"),
            (ticker.balance_sheet, "balance", "annual"),
            (ticker.quarterly_balance_sheet, "balance", "quarterly"),
            (ticker.cashflow, "cashflow", "annual"),
            (ticker.quarterly_cashflow, "cashflow", "quarterly"),
        ]

        rows: list[dict] = []
        for df, statement_type, period in sources:
            if df is None or df.empty:
                continue
            for col in df.columns:
                period_end: date = col.date() if hasattr(col, "date") else col
                for metric, value in df[col].items():
                    try:
                        float_val: float | None = float(value) if value is not None else None
                        if float_val is not None and math.isnan(float_val):
                            float_val = None
                    except (TypeError, ValueError):
                        float_val = None
                    rows.append(
                        {
                            "statement_type": statement_type,
                            "period": period,
                            "period_end": period_end,
                            "metric": str(metric),
                            "value": float_val,
                        }
                    )

        return rows

    # ------------------------------------------------------------------
    # Dividends
    # ------------------------------------------------------------------

    def get_dividends(self, symbol: str) -> list[dict]:
        """Return dividend payment records for the given symbol.

        Each dict: {date (date), amount (Decimal)}.
        """
        try:
            series = yf.Ticker(symbol).dividends
        except Exception:
            return []

        if series is None or series.empty:
            return []

        rows: list[dict] = []
        for ts, amount in series.items():
            div_date: date = ts.date() if hasattr(ts, "date") else ts
            try:
                rows.append(
                    {
                        "date": div_date,
                        "amount": Decimal(str(amount)),
                    }
                )
            except InvalidOperation:
                continue

        return rows
