"""Read-only tools for the agent workflows.

Two families, and the difference is load-bearing:

* DOMAIN tools are pure database lookups (no LLM call, no network, no writes) over
  already-ingested company data. The query logic is shared with ``chain._research_company``
  via ``chain.snapshot_metrics`` / ``chain.annual_financials``.
* GENERIC tools (``current_time``, ``weather``) answer the everyday questions the domain
  tools cannot. ``current_time`` is pure computation; ``weather`` is the ONLY tool in this
  module that makes an outbound network call - a GET against the fixed Open-Meteo hosts in
  ``_WEATHER_HOSTS`` (no API key, no credentials, no user input in the hostname), bounded by
  ``_HTTP_TIMEOUT_S``. Everything else here stays local, so the browser agent remains the only
  workflow that reaches arbitrary sites.

Tools never raise: a bad symbol / bad args / an unknown tool / an unreachable weather API all
return a structured ``{"error": ...}`` observation so the agent loop can recover on the next turn.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC
from datetime import datetime as dt
from statistics import median, quantiles
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from core.tracing import record_error, span

# The weather tool's outbound call. Hosts are FIXED constants, never built from tool args -
# an LLM-supplied location must not be able to steer the request at a different server.
_WEATHER_HOSTS = {
    "geocode": "https://geocoding-api.open-meteo.com/v1/search",
    "forecast": "https://api.open-meteo.com/v1/forecast",
}
_HTTP_TIMEOUT_S = 8.0

# WMO weather interpretation codes -> a phrase the model can quote directly.
_WMO_CODES: dict[int, str] = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    56: "light freezing drizzle",
    57: "dense freezing drizzle",
    61: "slight rain",
    63: "moderate rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "heavy freezing rain",
    71: "slight snowfall",
    73: "moderate snowfall",
    75: "heavy snowfall",
    77: "snow grains",
    80: "slight rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    85: "slight snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    run: Callable[..., str]
    args: tuple[str, ...] = ()  # required arg names
    optional: tuple[str, ...] = field(default_factory=tuple)  # optional arg names


def _ok(data: object) -> str:
    return json.dumps(data, default=str)


def _err(message: str) -> str:
    return json.dumps({"error": message})


def _normalise(symbol: object) -> str:
    """Uppercase + the companies-app '.' -> '-' convention (BRK.B -> BRK-B)."""
    return str(symbol).strip().upper().replace(".", "-")


def _get_company(symbol: str):
    """Resolve a Company by symbol; returns None when not found."""
    from apps.companies.models import Company

    try:
        return Company.objects.select_related("sector", "industry").get(
            symbol__iexact=_normalise(symbol)
        )
    except Company.DoesNotExist:
        return None


# --- Tool implementations -----------------------------------------------------------------


def _company_profile(symbol: str) -> str:
    company = _get_company(symbol)
    if company is None:
        return _err(f"No company found for symbol '{symbol}'.")
    return _ok(
        {
            "symbol": company.symbol,
            "name": company.name or company.symbol,
            "sector": company.sector.name if company.sector else None,
            "industry": company.industry.name if company.industry else None,
            "exchange": company.exchange or None,
            "currency": company.currency or None,
            "country": company.country or None,
            "employees": company.full_time_employees,
        }
    )


def _company_snapshot(symbol: str) -> str:
    from apps.companies.models import CompanySnapshot

    from . import chain

    company = _get_company(symbol)
    if company is None:
        return _err(f"No company found for symbol '{symbol}'.")
    snapshot = CompanySnapshot.objects.filter(company=company).order_by("-fetched_at").first()
    if snapshot is None:
        return _err(f"No snapshot data for '{company.symbol}'.")
    return _ok({"symbol": company.symbol, **chain.snapshot_metrics(snapshot)})


def _company_financials(
    symbol: str, statement_type: str | None = None, period: str | None = None
) -> str:
    from apps.companies.models import FinancialStatement

    from . import chain

    company = _get_company(symbol)
    if company is None:
        return _err(f"No company found for symbol '{symbol}'.")

    valid_types = set(FinancialStatement.StatementType.values)
    if statement_type is not None and statement_type not in valid_types:
        return _err(f"statement_type must be one of {sorted(valid_types)}.")

    period = period or "annual"
    if period == "annual" and statement_type is None:
        rows = chain.annual_financials(company)
    else:
        qs = FinancialStatement.objects.filter(company=company, period=period)
        if statement_type is not None:
            qs = qs.filter(statement_type=statement_type)
        rows = list(
            qs.order_by("-period_end").values("statement_type", "period_end", "metric", "value")[
                :40
            ]
        )
    if not rows:
        return _err(f"No financial statements for '{company.symbol}'.")
    return _ok({"symbol": company.symbol, "period": period, "rows": rows})


def _recent_price(symbol: str) -> str:
    from apps.companies.models import PriceBar

    company = _get_company(symbol)
    if company is None:
        return _err(f"No company found for symbol '{symbol}'.")

    closes = [
        float(c)
        for c in PriceBar.objects.filter(company=company)
        .order_by("-date")
        .values_list("close", flat=True)[:200]
    ]
    if not closes:
        return _err(f"No price history for '{company.symbol}'.")

    latest = PriceBar.objects.filter(company=company).order_by("-date").first()
    sma_50 = round(sum(closes[:50]) / 50, 4) if len(closes) >= 50 else None
    sma_200 = round(sum(closes) / 200, 4) if len(closes) >= 200 else None
    return _ok(
        {
            "symbol": company.symbol,
            "date": latest.date,
            "close": float(latest.close),
            "sma_50": sma_50,
            "sma_200": sma_200,
        }
    )


# --- Sector / industry aggregation --------------------------------------------------------

# Valuation metrics aggregated across the companies in a sector or industry.
_AGG_METRICS: tuple[str, ...] = (
    "trailing_pe",
    "forward_pe",
    "price_to_book",
    "return_on_equity",
    "profit_margins",
    "dividend_yield",
    "debt_to_equity",
)


# Ratios where a NEGATIVE value is not a valuation at all: a negative P/E means losses and a
# negative P/B means negative book equity. Neither is "cheap", but both drag a median down and
# read as attractive to a model doing "lower is cheaper" - so they are excluded from the
# distribution and COUNTED instead. ROE, margins and D/E keep their negatives: there a negative
# value is meaningful and comparable (a loss-making margin IS worse than a thin one).
VALUATION_RATIOS: frozenset[str] = frozenset({"trailing_pe", "forward_pe", "price_to_book"})


# Snapshot fields stored as FRACTIONS (0.2326 = 23.26%) that are percentages to a reader.
# The database keeps fractions - it is the CompanySnapshot convention, and the AI summary's
# formatter depends on it - but a MODEL handed a bare fraction converts some to percent and
# not others within one answer (issue #11: ROE -2.4003 read as "-2.40%" beside a correct
# "-230.10%" margin from the same observation). So every LLM-facing observation carries these
# already in percent, and says so in the NAME: ``return_on_equity_pct: 23.26``. The name is
# the unit label that survives anything - truncation of the carried observation, a legend the
# model skims - and the value stays a number, so downstream steps can still compare it.
# debt_to_equity is deliberately absent: it is a MULTIPLE (1.5 = debt is 1.5x equity), read
# the same way as a P/E, and nobody writes it as a percent.
PERCENT_FIELDS: tuple[str, ...] = ("return_on_equity", "profit_margins", "dividend_yield")


def as_percent(value) -> float | None:
    """A stored fraction as a percent number (0.2326 -> 23.26). None stays None."""
    if value is None:
        return None
    return round(float(value) * 100, 2)


def _agent_units(aggregate: dict) -> dict:
    """``aggregate_snapshots`` output re-expressed for a model: percent fields as ``*_pct``.

    Done HERE, at the tool boundary, and not inside ``aggregate_snapshots`` itself: that
    function is also the AI summary's peer benchmark, whose formatter expects fractions and
    renders its own percent strings.
    """
    metrics = {}
    for name, stats in aggregate["metrics"].items():
        if name in PERCENT_FIELDS:
            metrics[f"{name}_pct"] = (
                None
                if stats is None
                else {k: v if k == "n" else as_percent(v) for k, v in stats.items()}
            )
        else:
            metrics[name] = stats
    return {**aggregate, "metrics": metrics}


def _stats(values: list, *, exclude_negative: bool = False) -> dict | None:
    """The DISTRIBUTION of the non-null values - median/p25/p75/min/max/n - or None if empty.

    Deliberately no mean. Every aggregated field is a ratio, and a ratio's mean is owned by its
    outliers: one company on an 8,404x P/E (near-zero earnings) put the Technology sector's
    "average" above its own 75th percentile, and the agent reasoned from it. The median is the
    typical company, and p25/p75 say how spread the group is - which is the question "is this
    stock expensive for its sector?" actually depends on.

    ``exclude_negative`` (for ``VALUATION_RATIOS``) drops negatives from every statistic and
    reports how many were dropped as ``negative``; a group with no non-negative value is None.
    """
    vals = [float(v) for v in values if v is not None]
    negative = 0
    if exclude_negative:
        negative = sum(1 for v in vals if v < 0)
        vals = [v for v in vals if v >= 0]
    if not vals:
        return None
    # statistics.quantiles needs at least two points; one value is its own quartiles.
    p25, _, p75 = quantiles(vals, n=4, method="inclusive") if len(vals) > 1 else vals * 3
    stats = {
        "median": round(median(vals), 4),
        "p25": round(p25, 4),
        "p75": round(p75, 4),
        "min": round(min(vals), 4),
        "max": round(max(vals), 4),
        "n": len(vals),
    }
    if exclude_negative:
        stats["negative"] = negative
    return stats


def aggregate_snapshots(companies) -> dict:
    """Aggregate the latest snapshot per company across a Company queryset.

    Public (no leading underscore) because ``companies.services`` reuses it to build the
    peer benchmark for the AI company summary - the peer maths lives in exactly one place.

    A correlated subquery picks each company's newest snapshot (portable across Postgres and
    the SQLite test backend), then every valuation metric is summarised and the five largest
    constituents by market cap are listed.
    """
    from django.db.models import OuterRef, Subquery

    from apps.companies.models import CompanySnapshot

    latest = CompanySnapshot.objects.filter(company=OuterRef("pk")).order_by("-fetched_at")
    fields = ("market_cap", *_AGG_METRICS)
    rows = [
        r
        for r in companies.annotate(
            _s_id=Subquery(latest.values("id")[:1]),
            **{f"_s_{f}": Subquery(latest.values(f)[:1]) for f in fields},
        ).values("symbol", "_s_id", *(f"_s_{f}" for f in fields))
        if r["_s_id"] is not None
    ]
    metrics = {
        m: _stats([r[f"_s_{m}"] for r in rows], exclude_negative=m in VALUATION_RATIOS)
        for m in _AGG_METRICS
    }
    largest = sorted(
        (r for r in rows if r["_s_market_cap"] is not None),
        key=lambda r: r["_s_market_cap"],
        reverse=True,
    )[:5]
    return {
        "companies": companies.count(),
        "with_snapshot": len(rows),
        "metrics": metrics,
        "largest": [
            {
                "symbol": r["symbol"],
                "market_cap": r["_s_market_cap"],
                "trailing_pe": r["_s_trailing_pe"],
                "price_to_book": r["_s_price_to_book"],
            }
            for r in largest
        ],
    }


def _list_sectors(sector: str | None = None) -> str:
    """No arg: every sector with its company count. With a sector: its industries + counts."""
    from django.db.models import Count

    from apps.companies.models import Sector

    if sector:
        obj = Sector.objects.filter(name__iexact=str(sector).strip()).first()
        if obj is None:
            names = list(Sector.objects.order_by("name").values_list("name", flat=True))
            return _err(f"No sector '{sector}'. Valid sectors: {names}.")
        industries = (
            obj.industries.annotate(n=Count("companies")).order_by("-n").values("name", "n")
        )
        return _ok(
            {
                "sector": obj.name,
                "industries": [{"industry": i["name"], "companies": i["n"]} for i in industries],
            }
        )

    sectors = Sector.objects.annotate(n=Count("companies")).order_by("-n").values("name", "n")
    return _ok({"sectors": [{"sector": s["name"], "companies": s["n"]} for s in sectors]})


# Rides on every sector/industry observation so the model is TOLD which statistic is the
# typical value instead of picking one. Placed LAST in the payload: chat carries only the first
# CARRY_OBSERVATION_CHARS of an observation into the next turn, and the numbers matter more.
STATS_LEGEND = (
    "median is the TYPICAL company - compare a stock against the median, and use p25/p75 (the"
    " middle half of the group) to judge whether it is unusually high or low. min/max are single"
    " outlier companies, never the typical value. negative = companies left out of a P/E or P/B"
    " because a negative ratio means losses or negative equity, not a low valuation. *_pct"
    " values are ALREADY percentages (23.26 means 23.26%) - never multiply or divide them."
)


def _sector_analysis(sector: str) -> str:
    from apps.companies.models import Company, Sector

    obj = Sector.objects.filter(name__iexact=str(sector).strip()).first()
    if obj is None:
        names = list(Sector.objects.order_by("name").values_list("name", flat=True))
        return _err(f"No sector '{sector}'. Valid sectors: {names}.")
    companies = Company.objects.filter(sector=obj)
    if not companies.exists():
        return _err(f"No companies in sector '{obj.name}'.")
    return _ok(
        {
            "sector": obj.name,
            **_agent_units(aggregate_snapshots(companies)),
            "how_to_read": STATS_LEGEND,
        }
    )


def _industry_analysis(industry: str) -> str:
    from apps.companies.models import Company, Industry

    obj = (
        Industry.objects.select_related("sector").filter(name__iexact=str(industry).strip()).first()
    )
    if obj is None:
        names = list(Industry.objects.order_by("name").values_list("name", flat=True))
        return _err(f"No industry '{industry}'. Valid industries: {names}.")
    companies = Company.objects.filter(industry=obj)
    if not companies.exists():
        return _err(f"No companies in industry '{obj.name}'.")
    return _ok(
        {
            "industry": obj.name,
            "sector": obj.sector.name if obj.sector else None,
            **_agent_units(aggregate_snapshots(companies)),
            "how_to_read": STATS_LEGEND,
        }
    )


# --- Company vs peers (issue #13) ---------------------------------------------------------

#: Fewest OTHER companies a group needs before it is a usable peer benchmark. Shared with the
#: AI summary (``companies.services``), which delegates its group choice to ``peer_group``.
MIN_PEERS = 3

#: Metrics compared against the peer group, in the order they are reported. The valuation
#: ratios come first: chat carries only the first CARRY_OBSERVATION_CHARS of an observation
#: into the next turn, and "is it cheap?" is the question this tool mostly answers.
PEER_METRICS: tuple[str, ...] = (
    "trailing_pe",
    "forward_pe",
    "price_to_book",
    "return_on_equity",
    "profit_margins",
    "dividend_yield",
    "debt_to_equity",
)


#: What below / above the median MEANS, per metric, in that metric's own vocabulary.
#:
#: EVERY metric has one, and that is load-bearing. The first version gave a reading only to
#: the valuation ratios, and the model filled the gap by analogy: P/B, ROE and margins shared
#: the band "top quarter", so 4 of 10 live runs called NVDA "more expensive than the typical
#: peer based on price-to-book, return on equity and profit margins". A high margin is not a
#: price. Only P/E and P/B may say cheap/expensive; the others say what they measure.
METRIC_READINGS: dict[str, tuple[str, str]] = {
    "trailing_pe": ("cheaper than the typical peer", "more expensive than the typical peer"),
    "forward_pe": ("cheaper than the typical peer", "more expensive than the typical peer"),
    "price_to_book": ("cheaper than the typical peer", "more expensive than the typical peer"),
    "return_on_equity": (
        "less profitable than the typical peer (not a price measure)",
        "more profitable than the typical peer (not a price measure)",
    ),
    "profit_margins": (
        "less profitable than the typical peer (not a price measure)",
        "more profitable than the typical peer (not a price measure)",
    ),
    "dividend_yield": (
        "pays a lower yield than the typical peer",
        "pays a higher yield than the typical peer",
    ),
    "debt_to_equity": (
        "less leveraged than the typical peer",
        "more leveraged than the typical peer",
    ),
}


def peer_group(company, scope: str | None = None):
    """``(scope, name, peers_queryset)`` for ``company``'s benchmark group, or None.

    ``scope`` None prefers the industry and falls back to the sector when the industry has
    fewer than ``MIN_PEERS`` other companies. An explicit scope uses only that level. The
    company itself is ALWAYS excluded, so it never drags its own median toward itself.
    """
    from apps.companies.models import Company

    levels = (scope,) if scope else ("industry", "sector")
    for level in levels:
        obj = getattr(company, level, None)
        if obj is None:
            continue
        peers = Company.objects.filter(**{level: obj}).exclude(pk=company.pk)
        if peers.count() >= MIN_PEERS:
            return level, str(obj), peers
    return None


def _band(value: float, stats: dict) -> str:
    """Where ``value`` sits in the peer distribution, in words."""
    if value < stats["p25"]:
        return "bottom quarter (below p25)"
    if value > stats["p75"]:
        return "top quarter (above p75)"
    if value < stats["median"]:
        return "lower-middle (p25 to median)"
    if value > stats["median"]:
        return "upper-middle (median to p75)"
    return "at the median"


def _vs_median(value: float, median: float) -> str:
    """'17% below' / '4% above' / 'equal to' - the RELATION, precomputed.

    This is the whole point of the tool. With both numbers correct in front of it, the model
    still wrote "28.49 is slightly above the median of 34.30" in 2 of 5 live runs. Comparing
    two floats is arithmetic, and arithmetic belongs in code.
    """
    if value == median:
        return "equal to"
    direction = "above" if value > median else "below"
    if median == 0:
        return direction
    gap = abs(value - median) / abs(median) * 100
    # "0% below" contradicts itself, and the model copies these strings verbatim.
    # (`< 1`, not `< 0.5`: format() rounds half to even, so 0.5 would still print "0%".)
    return f"under 1% {direction}" if gap < 1 else f"{gap:.0f}% {direction}"


def compare_metric(field: str, value, stats: dict | None) -> dict:
    """One metric of the company against its peers. Pure: no DB, easy to pin."""
    pct = field in PERCENT_FIELDS
    show = as_percent if pct else (lambda v: None if v is None else round(float(v), 2))
    row: dict = {"company": show(value)}
    if value is None:
        row["vs_median"] = "no company data"
        return row
    value = float(value)
    if field in VALUATION_RATIOS and value < 0:
        # Losses or negative equity. Beside a median it would read as "far cheaper than
        # peers", so there is no comparison at all - the same rule as the AI summary.
        row["vs_median"] = "negative - losses or negative equity, no meaningful comparison"
        return row
    if not stats:
        row["vs_median"] = "no peer data"
        return row
    row["median"] = show(stats["median"])
    row["vs_median"] = _vs_median(value, stats["median"])
    row["band"] = _band(value, stats)
    if value != stats["median"]:
        below, above = METRIC_READINGS[field]
        row["reading"] = below if value < stats["median"] else above
    return row


PEER_LEGEND = (
    "vs_median, band and reading are computed: quote them as given, never re-derive the"
    " direction, and apply each reading only to its own metric."
    " *_pct values are already percentages. Peers exclude the company itself."
)


def _peer_comparison(symbol: str, scope: str | None = None) -> str:
    from apps.companies.models import CompanySnapshot

    from . import chain

    if scope is not None:
        scope = str(scope).strip().lower() or None
        if scope not in (None, "sector", "industry"):
            return _err("scope must be 'sector' or 'industry' (or omitted for automatic).")

    company = _get_company(symbol)
    if company is None:
        return _err(f"No company found for symbol '{symbol}'.")
    snapshot = CompanySnapshot.objects.filter(company=company).order_by("-fetched_at").first()
    if snapshot is None:
        return _err(f"No snapshot data for '{company.symbol}'.")

    # Size and earnings ride along so one prefetch answers "how big / what EPS" too; they go
    # AFTER the comparisons, which are what the carried 600-char slice must keep.
    extras = {
        "market_cap": snapshot.market_cap,
        "trailing_eps": snapshot.trailing_eps,
        "forward_eps": snapshot.forward_eps,
    }
    group = peer_group(company, scope)
    if group is None:
        # Still useful: the company's own figures, and an honest reason there is no benchmark.
        where = f"its {scope}" if scope else "its industry or sector"
        return _ok(
            {
                "symbol": company.symbol,
                "peer_group": None,
                "note": f"Fewer than {MIN_PEERS} other companies in {where} - no benchmark.",
                "company_metrics": chain.snapshot_metrics(snapshot),
            }
        )
    level, name, peers = group
    agg = aggregate_snapshots(peers)
    comparisons = {
        (f"{field}_pct" if field in PERCENT_FIELDS else field): compare_metric(
            field, getattr(snapshot, field), agg["metrics"].get(field)
        )
        for field in PEER_METRICS
    }
    return _ok(
        {
            "symbol": company.symbol,
            "peer_group": {"scope": level, "name": name, "peers": agg["with_snapshot"]},
            "comparisons": comparisons,
            **extras,
            "how_to_read": PEER_LEGEND,
        }
    )


# --- Registry -----------------------------------------------------------------------------


# --- Generic tools ------------------------------------------------------------------------


def _current_time(timezone: str | None = None) -> str:
    """Wall-clock time in an IANA timezone (default UTC).

    Exists because the model has no clock: without it "how did the stock do this week" is
    answered against the training cutoff rather than today.
    """
    name = (timezone or "UTC").strip() or "UTC"
    try:
        tz = UTC if name.upper() == "UTC" else ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return _err(
            f"Unknown timezone '{name}'. Use an IANA name such as 'UTC', "
            "'America/New_York' or 'Australia/Sydney'."
        )

    now = dt.now(tz)
    return _ok(
        {
            "timezone": name,
            "iso": now.isoformat(),
            "date": now.date().isoformat(),
            "time": now.strftime("%H:%M:%S"),
            "weekday": now.strftime("%A"),
            "utc_offset": now.strftime("%z"),
            "unix": int(now.timestamp()),
        }
    )


def _geocode(location: str) -> dict | str:
    """Resolve a place name to coordinates. Returns the match dict, or an _err() string."""
    resp = httpx.get(
        _WEATHER_HOSTS["geocode"],
        params={"name": location, "count": 1, "format": "json"},
        timeout=_HTTP_TIMEOUT_S,
    )
    resp.raise_for_status()
    results = (resp.json() or {}).get("results") or []
    if not results:
        return _err(f"No place found matching '{location}'.")
    return results[0]


def _weather(location: str, units: str | None = None) -> str:
    """Current conditions plus today's high/low for a named place, via Open-Meteo."""
    location = str(location).strip()
    if not location:
        return _err("location must be a non-empty place name, e.g. 'Sydney'.")

    unit_system = (units or "metric").strip().lower()
    if unit_system not in ("metric", "imperial"):
        return _err(f"Unknown units '{unit_system}'. Use 'metric' or 'imperial'.")
    imperial = unit_system == "imperial"

    try:
        place = _geocode(location)
        if isinstance(place, str):  # already an _err() observation
            return place

        resp = httpx.get(
            _WEATHER_HOSTS["forecast"],
            params={
                "latitude": place["latitude"],
                "longitude": place["longitude"],
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                "wind_speed_10m,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min",
                "forecast_days": 1,
                "timezone": "auto",
                **(
                    {"temperature_unit": "fahrenheit", "wind_speed_unit": "mph"} if imperial else {}
                ),
            },
            timeout=_HTTP_TIMEOUT_S,
        )
        resp.raise_for_status()
        payload = resp.json() or {}
    except httpx.HTTPError as exc:
        # Network failure is DATA, not a crash - the agent reasons about it next turn.
        return _err(f"Weather lookup failed for '{location}': {exc}")
    except (KeyError, ValueError) as exc:
        return _err(f"Unexpected weather response for '{location}': {exc}")

    current = payload.get("current") or {}
    daily = payload.get("daily") or {}
    highs = daily.get("temperature_2m_max") or []
    lows = daily.get("temperature_2m_min") or []
    code = current.get("weather_code")

    name = ", ".join(
        str(part) for part in (place.get("name"), place.get("admin1"), place.get("country")) if part
    )
    return _ok(
        {
            "location": name or location,
            "latitude": place.get("latitude"),
            "longitude": place.get("longitude"),
            "local_time": current.get("time"),
            "timezone": payload.get("timezone"),
            "conditions": _WMO_CODES.get(code, "unknown") if code is not None else None,
            "temperature": current.get("temperature_2m"),
            "feels_like": current.get("apparent_temperature"),
            "humidity_pct": current.get("relative_humidity_2m"),
            "wind_speed": current.get("wind_speed_10m"),
            "today_high": highs[0] if highs else None,
            "today_low": lows[0] if lows else None,
            "units": {
                "temperature": "F" if imperial else "C",
                "wind_speed": "mph" if imperial else "km/h",
            },
            "source": "open-meteo.com",
        }
    )


TOOLS: dict[str, Tool] = {
    "company_profile": Tool(
        name="company_profile",
        description="Company name, sector, industry, exchange, country, and employee count.",
        run=_company_profile,
        args=("symbol",),
    ),
    "company_snapshot": Tool(
        name="company_snapshot",
        description=(
            "Latest valuation metrics: market cap, trailing/forward P/E, P/B, EPS, "
            "debt-to-equity, and return on equity / profit margins / dividend yield in percent "
            "(the *_pct fields)."
        ),
        run=_company_snapshot,
        args=("symbol",),
    ),
    "peer_comparison": Tool(
        name="peer_comparison",
        description=(
            "A company against its peers: for P/E, forward P/E, P/B, ROE, margins, dividend "
            "yield and D/E, the company's value, the peer median, and the COMPUTED relation "
            "(vs_median e.g. '17% below', band, reading). Optional scope (sector|industry, "
            "default industry then sector). Use for 'is X cheap/expensive vs its sector'."
        ),
        run=_peer_comparison,
        args=("symbol",),
        optional=("scope",),
    ),
    "company_financials": Tool(
        name="company_financials",
        description=(
            "Recent financial-statement line items. Optional statement_type "
            "(income|balance|cashflow) and period (annual|quarterly, default annual)."
        ),
        run=_company_financials,
        args=("symbol",),
        optional=("statement_type", "period"),
    ),
    "recent_price": Tool(
        name="recent_price",
        description="Latest close price and date, plus 50-day and 200-day moving averages.",
        run=_recent_price,
        args=("symbol",),
    ),
    "list_sectors": Tool(
        name="list_sectors",
        description=(
            "Discover valid names. With no args: every sector and its company count. "
            "With a sector: the industries within it and their company counts. "
            "Use this first to find the exact sector/industry name for the analysis tools."
        ),
        run=_list_sectors,
        args=(),
        optional=("sector",),
    ),
    "sector_analysis": Tool(
        name="sector_analysis",
        description=(
            "Distribution of valuation across all companies in a sector: median (the typical "
            "company), p25/p75, min/max for trailing/forward P/E, P/B, ROE, profit margins, "
            "dividend yield, debt-to-equity, plus the largest constituents. Use to judge a "
            "stock against its sector's MEDIAN."
        ),
        run=_sector_analysis,
        args=("sector",),
    ),
    "industry_analysis": Tool(
        name="industry_analysis",
        description=(
            "Same valuation distribution as sector_analysis but scoped to a single "
            "industry (a tighter peer group than the sector)."
        ),
        run=_industry_analysis,
        args=("industry",),
    ),
    "current_time": Tool(
        name="current_time",
        description=(
            "The current date and time. Optional timezone as an IANA name "
            "(e.g. 'America/New_York'), default UTC. Use this whenever the question "
            "depends on today's date - you have no clock of your own."
        ),
        run=_current_time,
        args=(),
        optional=("timezone",),
    ),
    "weather": Tool(
        name="weather",
        description=(
            "Current weather for a named place: conditions, temperature, feels-like, "
            "humidity, wind, and today's high/low. Optional units ('metric' default, "
            "or 'imperial')."
        ),
        run=_weather,
        args=("location",),
        optional=("units",),
    ),
}


# Appended to EVERY catalogue, so each agent that is shown tools is shown this with them rather
# than each prompt carrying its own copy. It is deliberately about CLAIMS, not numbers: a chat
# prompt that said "never state a number you were not given" was obeyed literally, and the model
# stated a RANKING instead ("higher dividend yields, such as MSFT or AVGO") from an observation
# carrying no dividend data at all. A rule that names one shape of fabrication licenses the rest.
GROUNDING_RULE = (
    "Only state what a tool returned: no number, ranking, comparison or superlative (highest,"
    " cheaper, better, such as X) about a company or group whose data for that metric you were"
    " not given. If you lack it, say so or call a tool."
)


def tool_catalogue(only: Iterable[str] | None = None) -> str:
    """Render the tool list (name + signature + description) for the system prompt.

    ``only`` (when given) restricts the catalogue to that allow-list of tool names, preserving
    registry order - used to advertise a sub-agent only the tools it is permitted to call.
    """
    allowed = set(only) if only is not None else None
    lines = []
    for tool in TOOLS.values():
        if allowed is not None and tool.name not in allowed:
            continue
        sig = ", ".join([*tool.args, *(f"{a}?" for a in tool.optional)])
        lines.append(f"- {tool.name}({sig}): {tool.description}")
    if lines:
        lines.append(GROUNDING_RULE)
    return "\n".join(lines)


def run_tool(name: str, args: dict | None) -> str:
    """Dispatch to a tool by name. Returns a JSON observation; never raises."""
    tool = TOOLS.get(name)
    if tool is None:
        return _err(f"Unknown tool '{name}'. Available: {sorted(TOOLS)}.")

    args = args or {}
    if not isinstance(args, dict):
        return _err("args must be an object.")

    allowed = set(tool.args) | set(tool.optional)
    unexpected = set(args) - allowed
    if unexpected:
        return _err(f"Unexpected args for {name}: {sorted(unexpected)}.")
    missing = set(tool.args) - set(args)
    if missing:
        return _err(f"Missing required args for {name}: {sorted(missing)}.")

    # One choke point for every workflow's tool calls - ReAct, plan-execute,
    # orchestrator, multiagent, dag and autonomous all dispatch through here, so a
    # single span covers the lot rather than instrumenting six modules.
    with span("agent.tool", **{"tool.name": name, "tool.args": sorted(args)}) as sp:
        try:
            return tool.run(**args)
        except Exception as exc:  # tools must never crash the loop
            # Marked on the span but still RETURNED as an observation, never raised:
            # the agent loops treat a tool error as data to reason about, and this
            # function's contract is that it never raises.
            record_error(sp, exc)
            return _err(f"Tool '{name}' failed: {exc}")
