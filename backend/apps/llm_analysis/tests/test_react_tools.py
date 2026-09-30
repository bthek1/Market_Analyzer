import json
from datetime import date, timedelta

import pytest

from apps.companies.models import (
    Company,
    CompanySnapshot,
    FinancialStatement,
    Industry,
    PriceBar,
    Sector,
)
from apps.llm_analysis.tools import (
    GROUNDING_RULE,
    METRIC_READINGS,
    PEER_METRICS,
    PERCENT_FIELDS,
    STATS_LEGEND,
    TOOLS,
    VALUATION_RATIOS,
    _stats,
    aggregate_snapshots,
    as_percent,
    compare_metric,
    peer_group,
    run_tool,
    tool_catalogue,
)


@pytest.fixture
def company(db):
    sector = Sector.objects.create(name="Technology")
    industry = Industry.objects.create(name="Consumer Electronics", sector=sector)
    return Company.objects.create(
        symbol="AAPL",
        name="Apple Inc.",
        exchange=Company.Exchange.NASDAQ,
        currency=Company.Currency.USD,
        country="United States",
        full_time_employees=164000,
        sector=sector,
        industry=industry,
    )


def _obs(name, args):
    return json.loads(run_tool(name, args))


# ---------------------------------------------------------------------------
# tool_catalogue (pure)
# ---------------------------------------------------------------------------


def test_tool_catalogue_lists_every_tool():
    catalogue = tool_catalogue()
    for name in TOOLS:
        assert name in catalogue
    # optional args are marked with a trailing '?'
    assert "statement_type?" in catalogue


def test_tool_catalogue_only_restricts_to_allowlist():
    catalogue = tool_catalogue(only=("company_profile", "recent_price"))
    assert "company_profile" in catalogue
    assert "recent_price" in catalogue
    # tools outside the allow-list are omitted
    assert "sector_analysis" not in catalogue
    assert "company_snapshot" not in catalogue


def test_tool_catalogue_empty_allowlist_is_empty():
    assert tool_catalogue(only=()) == ""


# ---------------------------------------------------------------------------
# Individual tools
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTools:
    def test_company_profile_returns_sector_industry(self, company):
        obs = _obs("company_profile", {"symbol": "AAPL"})
        assert obs["sector"] == "Technology"
        assert obs["industry"] == "Consumer Electronics"
        assert obs["name"] == "Apple Inc."
        assert obs["employees"] == 164000

    def test_company_snapshot_latest_only(self, company):
        CompanySnapshot.objects.create(company=company, trailing_pe=10.0, raw={})
        newest = CompanySnapshot.objects.create(company=company, trailing_pe=31.2, raw={})
        obs = _obs("company_snapshot", {"symbol": "AAPL"})
        assert obs["trailing_pe"] == 31.2
        assert obs["symbol"] == "AAPL"
        assert newest.trailing_pe == 31.2

    def test_company_financials_defaults_annual(self, company):
        FinancialStatement.objects.create(
            company=company,
            statement_type="income",
            period="annual",
            period_end=date(2023, 12, 31),
            metric="Total Revenue",
            value=383285000000.0,
        )
        FinancialStatement.objects.create(
            company=company,
            statement_type="income",
            period="quarterly",
            period_end=date(2024, 3, 31),
            metric="Total Revenue",
            value=90000000000.0,
        )
        obs = _obs("company_financials", {"symbol": "AAPL"})
        assert obs["period"] == "annual"
        assert all(r["metric"] == "Total Revenue" for r in obs["rows"])
        assert len(obs["rows"]) == 1  # only the annual row

    def test_company_financials_invalid_statement_type(self, company):
        obs = _obs("company_financials", {"symbol": "AAPL", "statement_type": "bogus"})
        assert "error" in obs

    def test_company_financials_explicit_type_and_period(self, company):
        FinancialStatement.objects.create(
            company=company,
            statement_type="balance",
            period="quarterly",
            period_end=date(2024, 3, 31),
            metric="Total Assets",
            value=350000000000.0,
        )
        # Income-statement annual rows that must be filtered out.
        FinancialStatement.objects.create(
            company=company,
            statement_type="income",
            period="annual",
            period_end=date(2023, 12, 31),
            metric="Total Revenue",
            value=383285000000.0,
        )
        obs = _obs(
            "company_financials",
            {"symbol": "AAPL", "statement_type": "balance", "period": "quarterly"},
        )
        assert obs["period"] == "quarterly"
        assert len(obs["rows"]) == 1
        assert obs["rows"][0]["metric"] == "Total Assets"

    def test_company_financials_none_when_empty(self, company):
        obs = _obs("company_financials", {"symbol": "AAPL"})
        assert "error" in obs  # company exists but has no statements

    def test_recent_price_latest_close(self, company):
        PriceBar.objects.create(
            company=company, date=date(2024, 1, 1), open=1, high=2, low=1, close=150, volume=100
        )
        PriceBar.objects.create(
            company=company, date=date(2024, 1, 2), open=1, high=2, low=1, close=155, volume=100
        )
        obs = _obs("recent_price", {"symbol": "AAPL"})
        assert obs["close"] == 155.0
        assert obs["date"] == "2024-01-02"
        assert obs["sma_50"] is None  # not enough bars

    def test_recent_price_computes_moving_averages(self, company):
        bars = [
            PriceBar(
                company=company,
                date=date(2023, 1, 1) + timedelta(days=i),
                open=1,
                high=2,
                low=1,
                close=100 + i,
                volume=10,
            )
            for i in range(200)
        ]
        PriceBar.objects.bulk_create(bars)
        obs = _obs("recent_price", {"symbol": "AAPL"})
        # 200 bars present -> both moving averages computed (latest close is 100+199 = 299).
        assert obs["close"] == 299.0
        assert obs["sma_50"] is not None
        assert obs["sma_200"] is not None

    def test_recent_price_no_history(self, company):
        obs = _obs("recent_price", {"symbol": "AAPL"})
        assert "error" in obs

    def test_company_snapshot_matches_shared_extraction(self, company):
        # The tool must reuse chain.snapshot_metrics (single source of truth, no duplication).
        from apps.llm_analysis import chain

        snap = CompanySnapshot.objects.create(
            company=company, trailing_pe=20.0, return_on_equity=0.3, raw={}
        )
        obs = _obs("company_snapshot", {"symbol": "AAPL"})
        expected = chain.snapshot_metrics(snap)
        assert {k: obs[k] for k in expected} == expected

    def test_symbol_normalised(self, db):
        Company.objects.create(symbol="BRK-B", name="Berkshire")
        obs = _obs("company_profile", {"symbol": "brk.b"})
        assert obs["symbol"] == "BRK-B"


# ---------------------------------------------------------------------------
# Sector / industry aggregation tools
# ---------------------------------------------------------------------------


@pytest.fixture
def tech_sector(db):
    """A Technology sector with two industries and three companies with latest snapshots."""
    sector = Sector.objects.create(name="Technology")
    electronics = Industry.objects.create(name="Consumer Electronics", sector=sector)
    software = Industry.objects.create(name="Software - Application", sector=sector)

    aapl = Company.objects.create(symbol="AAPL", name="Apple", sector=sector, industry=electronics)
    msft = Company.objects.create(symbol="MSFT", name="Microsoft", sector=sector, industry=software)
    crm = Company.objects.create(symbol="CRM", name="Salesforce", sector=sector, industry=software)

    # AAPL: an older snapshot that must be ignored, then the latest.
    CompanySnapshot.objects.create(company=aapl, trailing_pe=10.0, market_cap=1, raw={})
    CompanySnapshot.objects.create(
        company=aapl, trailing_pe=30.0, price_to_book=40.0, market_cap=3_000, raw={}
    )
    CompanySnapshot.objects.create(
        company=msft, trailing_pe=20.0, price_to_book=10.0, market_cap=2_000, raw={}
    )
    # CRM has no trailing_pe -> excluded from that metric's stats but still counted.
    CompanySnapshot.objects.create(company=crm, price_to_book=8.0, market_cap=200, raw={})
    return sector


@pytest.mark.django_db
class TestSectorIndustryTools:
    def test_list_sectors_counts_companies(self, tech_sector):
        obs = _obs("list_sectors", {})
        entry = next(s for s in obs["sectors"] if s["sector"] == "Technology")
        assert entry["companies"] == 3

    def test_list_sectors_drills_into_industries(self, tech_sector):
        obs = _obs("list_sectors", {"sector": "technology"})  # case-insensitive
        assert obs["sector"] == "Technology"
        counts = {i["industry"]: i["companies"] for i in obs["industries"]}
        assert counts["Software - Application"] == 2
        assert counts["Consumer Electronics"] == 1

    def test_list_sectors_unknown_sector(self, tech_sector):
        obs = _obs("list_sectors", {"sector": "Nope"})
        assert "error" in obs

    def test_sector_analysis_aggregates_latest_snapshot(self, tech_sector):
        obs = _obs("sector_analysis", {"sector": "Technology"})
        assert obs["sector"] == "Technology"
        assert obs["companies"] == 3
        assert obs["with_snapshot"] == 3
        pe = obs["metrics"]["trailing_pe"]
        # Only AAPL (latest 30, not the stale 10) and MSFT (20) have a P/E -> n=2. No mean:
        # the distribution is reported instead (issue #9).
        assert pe == {
            "median": 25.0,
            "p25": 22.5,
            "p75": 27.5,
            "min": 20.0,
            "max": 30.0,
            "n": 2,
            "negative": 0,
        }

    def test_sector_analysis_lists_largest_by_market_cap(self, tech_sector):
        obs = _obs("sector_analysis", {"sector": "Technology"})
        symbols = [c["symbol"] for c in obs["largest"]]
        assert symbols == ["AAPL", "MSFT", "CRM"]  # 3000 > 2000 > 200

    def test_sector_analysis_unknown_sector(self, tech_sector):
        obs = _obs("sector_analysis", {"sector": "Energy"})
        assert "error" in obs

    def test_sector_analysis_empty_sector(self, db):
        Sector.objects.create(name="Utilities")
        obs = _obs("sector_analysis", {"sector": "Utilities"})
        assert "error" in obs

    def test_industry_analysis_scopes_to_industry(self, tech_sector):
        obs = _obs("industry_analysis", {"industry": "Software - Application"})
        assert obs["industry"] == "Software - Application"
        assert obs["sector"] == "Technology"
        assert obs["companies"] == 2  # MSFT + CRM, not AAPL
        assert obs["metrics"]["trailing_pe"]["n"] == 1  # only MSFT has a P/E

    def test_industry_analysis_unknown_industry(self, tech_sector):
        obs = _obs("industry_analysis", {"industry": "Nope"})
        assert "error" in obs

    def test_industry_analysis_empty_industry(self, db):
        sector = Sector.objects.create(name="Utilities")
        Industry.objects.create(name="Utilities - Regulated Water", sector=sector)
        obs = _obs("industry_analysis", {"industry": "Utilities - Regulated Water"})
        assert "No companies in industry" in obs["error"]


# ---------------------------------------------------------------------------
# run_tool error handling (must never raise)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRunTool:
    def test_unknown_symbol_returns_error_observation(self, db):
        obs = _obs("company_profile", {"symbol": "NOPE"})
        assert "error" in obs

    def test_unknown_tool_name(self):
        obs = _obs("teleport", {"symbol": "AAPL"})
        assert "error" in obs

    def test_missing_required_arg(self):
        obs = _obs("company_profile", {})
        assert "error" in obs
        assert "symbol" in obs["error"]

    def test_unexpected_arg(self, company):
        obs = _obs("company_profile", {"symbol": "AAPL", "extra": 1})
        assert "error" in obs

    def test_none_args(self):
        obs = json.loads(run_tool("company_profile", None))
        assert "error" in obs

    def test_non_dict_args(self):
        obs = json.loads(run_tool("company_profile", ["AAPL"]))
        assert "error" in obs
        assert "object" in obs["error"]

    def test_snapshot_missing_data_observation(self, company):
        obs = _obs("company_snapshot", {"symbol": "AAPL"})
        assert "error" in obs  # company exists but has no snapshot

    @pytest.mark.parametrize("tool", ["company_snapshot", "company_financials", "recent_price"])
    def test_every_tool_handles_unknown_symbol(self, db, tool):
        obs = _obs(tool, {"symbol": "NOPE"})
        assert "error" in obs

    def test_internal_exception_is_caught(self, monkeypatch):
        from apps.llm_analysis import tools

        def boom(symbol):
            raise RuntimeError("kaboom")

        monkeypatch.setitem(
            tools.TOOLS,
            "company_profile",
            tools.Tool(
                name="company_profile",
                description="x",
                run=boom,
                args=("symbol",),
            ),
        )
        obs = json.loads(tools.run_tool("company_profile", {"symbol": "AAPL"}))
        assert "error" in obs
        assert "failed" in obs["error"]


# ---------------------------------------------------------------------------
# Generic tools: current_time (pure) and weather (the one networked tool)
# ---------------------------------------------------------------------------


class TestCurrentTime:
    def test_defaults_to_utc(self):
        obs = _obs("current_time", {})
        assert obs["timezone"] == "UTC"
        assert obs["utc_offset"] == "+0000"
        # the shape the model is told to expect
        for key in ("iso", "date", "time", "weekday", "unix"):
            assert obs[key]

    def test_named_timezone_offsets_from_utc(self):
        utc = _obs("current_time", {})
        ny = _obs("current_time", {"timezone": "America/New_York"})
        assert ny["timezone"] == "America/New_York"
        assert ny["utc_offset"] != "+0000"
        # same instant, different wall clock
        assert abs(ny["unix"] - utc["unix"]) < 5

    def test_unknown_timezone_is_an_observation(self):
        obs = _obs("current_time", {"timezone": "Mars/Olympus"})
        assert "error" in obs
        assert "IANA" in obs["error"]

    def test_blank_timezone_falls_back_to_utc(self):
        assert _obs("current_time", {"timezone": "  "})["timezone"] == "UTC"


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


_GEOCODE = {
    "results": [
        {
            "name": "Sydney",
            "admin1": "New South Wales",
            "country": "Australia",
            "latitude": -33.87,
            "longitude": 151.21,
        }
    ]
}
_FORECAST = {
    "timezone": "Australia/Sydney",
    "current": {
        "time": "2026-09-25T14:00",
        "temperature_2m": 21.4,
        "apparent_temperature": 20.1,
        "relative_humidity_2m": 62,
        "wind_speed_10m": 13.0,
        "weather_code": 3,
    },
    "daily": {"temperature_2m_max": [23.5], "temperature_2m_min": [14.2]},
}


def _fake_get(monkeypatch, responses, calls=None):
    """Patch httpx.get in the tools module; `responses` is keyed by URL substring."""
    from apps.llm_analysis import tools

    def get(url, params=None, timeout=None):
        if calls is not None:
            calls.append((url, params))
        for key, payload in responses.items():
            if key in url:
                if isinstance(payload, Exception):
                    raise payload
                return _FakeResponse(payload)
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(tools.httpx, "get", get)


class TestWeather:
    def test_returns_current_conditions(self, monkeypatch):
        _fake_get(monkeypatch, {"geocoding-api": _GEOCODE, "/v1/forecast": _FORECAST})
        obs = _obs("weather", {"location": "Sydney"})
        assert obs["location"] == "Sydney, New South Wales, Australia"
        assert obs["conditions"] == "overcast"  # WMO code 3
        assert obs["temperature"] == 21.4
        assert obs["today_high"] == 23.5
        assert obs["today_low"] == 14.2
        assert obs["units"] == {"temperature": "C", "wind_speed": "km/h"}

    def test_imperial_units_are_requested_upstream(self, monkeypatch):
        calls = []
        _fake_get(monkeypatch, {"geocoding-api": _GEOCODE, "/v1/forecast": _FORECAST}, calls)
        obs = _obs("weather", {"location": "Sydney", "units": "imperial"})
        forecast_params = calls[-1][1]
        assert forecast_params["temperature_unit"] == "fahrenheit"
        assert forecast_params["wind_speed_unit"] == "mph"
        assert obs["units"] == {"temperature": "F", "wind_speed": "mph"}

    def test_host_is_never_taken_from_the_argument(self, monkeypatch):
        """An LLM-supplied location must not be able to steer the request elsewhere."""
        calls = []
        _fake_get(monkeypatch, {"geocoding-api": _GEOCODE, "/v1/forecast": _FORECAST}, calls)
        _obs("weather", {"location": "http://evil.example/?x=Sydney"})
        for url, _params in calls:
            assert url.startswith(
                ("https://geocoding-api.open-meteo.com", "https://api.open-meteo.com")
            )

    def test_unknown_place_is_an_observation(self, monkeypatch):
        _fake_get(monkeypatch, {"geocoding-api": {"results": []}})
        obs = _obs("weather", {"location": "Nowheresville"})
        assert "error" in obs

    def test_network_failure_is_an_observation_not_a_raise(self, monkeypatch):
        import httpx

        _fake_get(monkeypatch, {"geocoding-api": httpx.ConnectError("down")})
        obs = _obs("weather", {"location": "Sydney"})
        assert "error" in obs
        assert "Weather lookup failed" in obs["error"]

    def test_blank_location_rejected_without_a_call(self, monkeypatch):
        _fake_get(monkeypatch, {})  # any call would AssertionError
        assert "error" in _obs("weather", {"location": "   "})

    def test_unknown_units_rejected_without_a_call(self, monkeypatch):
        _fake_get(monkeypatch, {})
        obs = _obs("weather", {"location": "Sydney", "units": "kelvin"})
        assert "error" in obs

    def test_requests_are_bounded_by_a_timeout(self, monkeypatch):
        calls = []
        from apps.llm_analysis import tools

        def get(url, params=None, timeout=None):
            calls.append(timeout)
            return _FakeResponse(_GEOCODE if "geocoding-api" in url else _FORECAST)

        monkeypatch.setattr(tools.httpx, "get", get)
        _obs("weather", {"location": "Sydney"})
        assert calls and all(t == tools._HTTP_TIMEOUT_S for t in calls)


# ---------------------------------------------------------------------------
# Issue #9: the aggregates report a DISTRIBUTION, never a mean
# ---------------------------------------------------------------------------


class TestStatsDistribution:
    def test_no_mean_and_carries_quartiles(self):
        stats = _stats([10.0, 20.0, 30.0, 40.0, 50.0])
        assert "avg" not in stats
        assert set(stats) == {"median", "p25", "p75", "min", "max", "n"}
        assert stats["median"] == 30.0
        assert stats["p25"] == 20.0
        assert stats["p75"] == 40.0

    def test_single_value_is_its_own_quartiles(self):
        # statistics.quantiles raises below two points - must degrade, not raise.
        assert _stats([7.0]) == {
            "median": 7.0,
            "p25": 7.0,
            "p75": 7.0,
            "min": 7.0,
            "max": 7.0,
            "n": 1,
        }

    def test_two_values_do_not_raise(self):
        stats = _stats([10.0, 20.0])
        assert stats["p25"] == 12.5
        assert stats["p75"] == 17.5

    def test_empty_and_all_null_are_none(self):
        assert _stats([]) is None
        assert _stats([None, None]) is None

    def test_outlier_moves_max_but_not_the_typical_value(self):
        # The property the whole issue rests on: ten companies near 20x and one at 8,000x
        # (near-zero earnings). A mean would read ~745x; the median and p75 must not move.
        typical = [18.0, 19.0, 19.5, 20.0, 20.0, 20.5, 21.0, 21.5, 22.0, 23.0]
        before = _stats(typical)
        after = _stats([*typical, 8_000.0])
        assert after["max"] == 8_000.0
        assert after["median"] == pytest.approx(before["median"], abs=0.5)
        assert after["p75"] == pytest.approx(before["p75"], abs=1.0)
        assert after["p75"] < 25.0


class TestNegativeValuationRatios:
    def test_the_valuation_ratios_are_exactly_pe_and_pb(self):
        # Pinned explicitly: the easy mistake is to apply the rule to every metric.
        assert frozenset({"trailing_pe", "forward_pe", "price_to_book"}) == VALUATION_RATIOS

    def test_negatives_are_counted_and_excluded(self):
        stats = _stats([-5.0, -1.0, 10.0, 20.0, 30.0], exclude_negative=True)
        assert stats["negative"] == 2
        assert stats["n"] == 3
        assert stats["min"] == 10.0
        assert stats["median"] == 20.0
        assert stats["p25"] == 15.0

    def test_all_negative_group_is_none(self):
        assert _stats([-3.0, -1.0], exclude_negative=True) is None

    def test_negatives_kept_when_not_excluding(self):
        stats = _stats([-0.2, 0.1, 0.3])
        assert "negative" not in stats
        assert stats["n"] == 3
        assert stats["min"] == -0.2


@pytest.mark.django_db
class TestAggregateNegativeHandling:
    @pytest.fixture
    def group(self, db):
        sector = Sector.objects.create(name="Technology")
        rows = [
            # symbol, P/B, ROE, margin, D/E
            ("NEG1", -4.0, -0.30, -0.10, 1.0),
            ("NEG2", -1.0, -0.05, -0.02, 0.5),
            ("A", 2.0, 0.10, 0.05, 0.2),
            ("B", 4.0, 0.20, 0.10, 0.4),
            ("C", 6.0, 0.30, 0.20, 0.6),
        ]
        for symbol, pb, roe, margin, de in rows:
            company = Company.objects.create(symbol=symbol, sector=sector)
            CompanySnapshot.objects.create(
                company=company,
                price_to_book=pb,
                return_on_equity=roe,
                profit_margins=margin,
                debt_to_equity=de,
                market_cap=1,
                raw={},
            )
        return Company.objects.filter(sector=sector)

    def test_price_to_book_excludes_negatives(self, group):
        pb = aggregate_snapshots(group)["metrics"]["price_to_book"]
        assert pb["negative"] == 2
        assert pb["n"] == 3
        assert pb["median"] == 4.0  # 2 with the negatives in; they read as "cheap"

    def test_all_negative_valuation_metric_is_none(self, db):
        sector = Sector.objects.create(name="Distressed")
        for i, pe in enumerate([-3.0, -9.0]):
            company = Company.objects.create(symbol=f"L{i}", sector=sector)
            CompanySnapshot.objects.create(company=company, trailing_pe=pe, raw={})
        metrics = aggregate_snapshots(Company.objects.filter(sector=sector))["metrics"]
        assert metrics["trailing_pe"] is None

    @pytest.mark.parametrize("field", sorted(VALUATION_RATIOS))
    def test_every_valuation_ratio_excludes_negatives(self, db, field):
        sector = Sector.objects.create(name="Mixed")
        for i, value in enumerate([-5.0, 10.0, 20.0, 30.0]):
            company = Company.objects.create(symbol=f"M{i}", sector=sector)
            CompanySnapshot.objects.create(company=company, raw={}, **{field: value})
        stats = aggregate_snapshots(Company.objects.filter(sector=sector))["metrics"][field]
        assert stats["negative"] == 1
        assert stats["n"] == 3
        assert stats["median"] == 20.0

    def test_aggregate_itself_carries_no_legend(self, group):
        # The legend is for the MODEL; the AI summary's data_snapshot must stay pure numbers.
        assert "how_to_read" not in aggregate_snapshots(group)

    def test_roe_and_margins_keep_their_negatives(self, group):
        metrics = aggregate_snapshots(group)["metrics"]
        for field in ("return_on_equity", "profit_margins", "debt_to_equity"):
            assert "negative" not in metrics[field], field
            assert metrics[field]["n"] == 5, field
        assert metrics["return_on_equity"]["min"] == -0.30
        assert metrics["profit_margins"]["median"] == 0.05


@pytest.mark.django_db
class TestSectorObservationIsSelfDescribing:
    def test_sector_observation_names_median_as_typical(self, tech_sector):
        obs = _obs("sector_analysis", {"sector": "Technology"})
        assert obs["how_to_read"] == STATS_LEGEND
        assert "median is the TYPICAL company" in obs["how_to_read"]
        # Last key, so chat's truncated carry-forward keeps the numbers rather than the legend.
        assert list(obs)[-1] == "how_to_read"

    def test_industry_observation_names_median_as_typical(self, tech_sector):
        obs = _obs("industry_analysis", {"industry": "Software - Application"})
        assert obs["how_to_read"] == STATS_LEGEND

    def test_observation_carries_no_mean_anywhere(self, tech_sector):
        raw = run_tool("sector_analysis", {"sector": "Technology"})
        assert '"avg"' not in raw

    def test_tool_description_points_at_the_median(self):
        assert "avg" not in TOOLS["sector_analysis"].description
        assert "median" in TOOLS["sector_analysis"].description


class TestGroundingRule:
    def test_rule_covers_claims_not_just_numbers(self):
        for word in ("number", "ranking", "comparison", "superlative"):
            assert word in GROUNDING_RULE

    def test_every_non_empty_catalogue_carries_it(self):
        assert tool_catalogue().endswith(GROUNDING_RULE)
        assert tool_catalogue(only=("company_profile",)).endswith(GROUNDING_RULE)
        assert tool_catalogue(only=()) == ""


@pytest.mark.django_db
class TestSectorObservationBudget:
    """The observation rides in chat's per-turn budget, which is sized against the LARGEST
    tool output (``company_financials``, ~1,181 tokens). Issue #9 grew it from 315 to 441
    tokens; this pins a ceiling so a future field cannot quietly outgrow the turn."""

    def test_fully_populated_sector_stays_within_half_the_turn_reserve(self, db):
        from apps.llm_analysis._context import estimate_tokens
        from apps.llm_analysis.chat_agent import TURN_RESERVE

        sector = Sector.objects.create(name="Technology")
        # Awkward, full-precision values: the worst case for serialised length.
        for i in range(12):
            company = Company.objects.create(symbol=f"SYM{i:02d}", sector=sector)
            CompanySnapshot.objects.create(
                company=company,
                market_cap=5_434_765_213_696 - i * 97_531_357,
                trailing_pe=8404.334123 / (i + 1),
                forward_pe=157.001317 / (i + 1),
                price_to_book=-1832.830219 if i == 0 else 1832.830219 / (i + 1),
                return_on_equity=-2.400311 + i * 0.611,
                profit_margins=-2.301011 + i * 0.25,
                dividend_yield=0.049713 / (i + 1),
                debt_to_equity=573.343311 / (i + 1),
                raw={},
            )
        raw = run_tool("sector_analysis", {"sector": "Technology"})
        assert estimate_tokens(raw) <= TURN_RESERVE // 2


@pytest.mark.django_db
class TestPercentUnits:
    """Issue #11: the model was handed FRACTIONS and scaled some to percent and not others
    within one answer (ROE min -2.4003 -> "-2.40%" beside a correct "-230.10%" margin). Every
    LLM-facing observation now carries those fields in percent, labelled by the NAME."""

    @pytest.fixture
    def snapshot(self, company):
        return CompanySnapshot.objects.create(
            company=company,
            trailing_pe=28.489874,
            debt_to_equity=0.16971,
            return_on_equity=1.17211,
            profit_margins=0.63663,
            dividend_yield=0.0044,
            raw={},
        )

    @pytest.fixture
    def group(self, db):
        sector = Sector.objects.create(name="Technology")
        for i, (roe, margin, dy) in enumerate(
            [(-2.4003, -2.301, 0.0005), (0.2326, 0.1849, 0.0106), (4.4286, 0.7295, 0.0497)]
        ):
            company = Company.objects.create(symbol=f"P{i}", sector=sector)
            CompanySnapshot.objects.create(
                company=company,
                trailing_pe=20.0 + i,
                debt_to_equity=0.5,
                return_on_equity=roe,
                profit_margins=margin,
                dividend_yield=dy,
                market_cap=1 + i,
                raw={},
            )
        return sector

    def test_as_percent(self):
        assert as_percent(0.2326) == 23.26
        assert as_percent(-2.4003) == -240.03
        assert as_percent(0.0044) == 0.44
        assert as_percent(None) is None

    def test_snapshot_renders_each_percent_field_in_percent(self, snapshot):
        obs = _obs("company_snapshot", {"symbol": "AAPL"})
        assert obs["return_on_equity_pct"] == 117.21
        assert obs["profit_margins_pct"] == 63.66
        assert obs["dividend_yield_pct"] == 0.44

    def test_snapshot_keeps_multiples_as_multiples(self, snapshot):
        obs = _obs("company_snapshot", {"symbol": "AAPL"})
        assert obs["debt_to_equity"] == pytest.approx(0.16971)
        assert obs["trailing_pe"] == pytest.approx(28.489874)

    def test_sector_renders_the_ROE_minimum_that_was_misread(self, group):  # noqa: N802
        metrics = _obs("sector_analysis", {"sector": "Technology"})["metrics"]
        assert metrics["return_on_equity_pct"]["min"] == -240.03
        assert metrics["return_on_equity_pct"]["max"] == 442.86
        assert metrics["profit_margins_pct"]["min"] == -230.1
        assert metrics["dividend_yield_pct"]["median"] == 1.06

    def test_sector_count_is_not_scaled(self, group):
        metrics = _obs("sector_analysis", {"sector": "Technology"})["metrics"]
        assert metrics["return_on_equity_pct"]["n"] == 3

    def test_sector_valuation_ratios_are_untouched(self, group):
        metrics = _obs("sector_analysis", {"sector": "Technology"})["metrics"]
        assert metrics["trailing_pe"]["median"] == 21.0
        assert metrics["debt_to_equity"]["median"] == 0.5

    def test_an_empty_percent_metric_stays_null(self, db):
        sector = Sector.objects.create(name="Bare")
        company = Company.objects.create(symbol="BARE", sector=sector)
        CompanySnapshot.objects.create(company=company, trailing_pe=10.0, raw={})
        metrics = _obs("sector_analysis", {"sector": "Bare"})["metrics"]
        assert metrics["dividend_yield_pct"] is None

    @pytest.mark.parametrize(
        "tool, args",
        [
            ("company_snapshot", {"symbol": "AAPL"}),
            ("sector_analysis", {"sector": "Technology"}),
            ("industry_analysis", {"industry": "Consumer Electronics"}),
        ],
    )
    def test_no_percent_field_leaves_as_a_bare_fraction(self, snapshot, tool, args):
        """Derived from PERCENT_FIELDS, so a field added there is covered here too. A bare
        name next to the _pct one would hand the model the ambiguity back."""
        obs = _obs(tool, args)
        keys = set(obs.get("metrics", obs))
        for field in PERCENT_FIELDS:
            assert field not in keys, (tool, field)
            assert f"{field}_pct" in keys, (tool, field)

    def test_the_summary_benchmark_still_gets_fractions(self, group):
        """aggregate_snapshots is ALSO the AI summary's peer benchmark, whose formatter does
        its own percent rendering - converting there would print 23,260%."""
        metrics = aggregate_snapshots(Company.objects.filter(sector=group))["metrics"]
        assert metrics["return_on_equity"]["median"] == 0.2326
        assert not any(k.endswith("_pct") for k in metrics)

    def test_legend_and_description_say_pct_is_already_percent(self):
        assert "*_pct" in STATS_LEGEND
        assert "never multiply or divide" in STATS_LEGEND
        assert "_pct" in TOOLS["company_snapshot"].description


# ---------------------------------------------------------------------------
# peer_comparison (issue #13): the relation to the peer median is COMPUTED
# ---------------------------------------------------------------------------

_STATS = {"median": 34.30, "p25": 20.85, "p75": 61.14, "min": 5.0, "max": 8000.0, "n": 86}


class TestCompareMetric:
    """Pure. The live failure was the model writing "28.49 is slightly above 34.30", so the
    exact strings the model copies are pinned, not just their presence."""

    def test_the_live_failure_case_reads_below(self):
        row = compare_metric("trailing_pe", 28.489874, _STATS)
        assert row == {
            "company": 28.49,
            "median": 34.3,
            "vs_median": "17% below",
            "band": "lower-middle (p25 to median)",
            "reading": "cheaper than the typical peer",
        }

    @pytest.mark.parametrize(
        "value, band",
        [
            (10.0, "bottom quarter (below p25)"),
            (20.85, "lower-middle (p25 to median)"),
            (34.30, "at the median"),
            (50.0, "upper-middle (median to p75)"),
            (61.14, "upper-middle (median to p75)"),
            (90.0, "top quarter (above p75)"),
        ],
    )
    def test_band_edges(self, value, band):
        assert compare_metric("trailing_pe", value, _STATS)["band"] == band

    def test_above_reads_more_expensive(self):
        row = compare_metric("price_to_book", 23.73, {**_STATS, "median": 8.04})
        assert row["vs_median"] == "195% above"
        assert row["reading"] == "more expensive than the typical peer"

    def test_equal_has_no_direction_and_no_reading(self):
        row = compare_metric("forward_pe", 34.30, _STATS)
        assert row["vs_median"] == "equal to"
        assert "reading" not in row  # neither cheaper nor dearer - no word to copy

    @pytest.mark.parametrize(
        "value, expected",
        [
            (34.2, "under 1% below"),
            (34.4, "under 1% above"),
            (34.65, "1% above"),
            (33.95, "1% below"),
        ],
    )
    def test_a_tiny_gap_never_reads_zero_percent(self, value, expected):
        """'0% below' contradicts itself, and the model copies these strings verbatim."""
        assert compare_metric("trailing_pe", value, _STATS)["vs_median"] == expected

    def test_an_exact_half_percent_gap_is_not_zero(self):
        """format() rounds half to EVEN, so a 0.5% gap prints as "0%" - which is why the cut
        is `< 1` and not `< 0.5`. Median 100 makes the gap exactly 0.5 in float arithmetic."""
        assert f"{0.5:.0f}" == "0"  # the property the threshold exists to defend against
        stats = {"median": 100.0, "p25": 50.0, "p75": 150.0}
        assert compare_metric("trailing_pe", 100.5, stats)["vs_median"] == "under 1% above"

    def test_a_zero_median_still_gets_a_direction(self):
        stats = {"median": 0.0, "p25": 0.0, "p75": 0.0}
        assert compare_metric("debt_to_equity", 0.5, stats)["vs_median"] == "above"

    def test_percent_fields_compare_in_percent(self):
        stats = {"median": 0.2323, "p25": 0.119, "p75": 0.4138}
        row = compare_metric("return_on_equity", 1.17211, stats)
        assert row["company"] == 117.21
        assert row["median"] == 23.23
        assert row["vs_median"] == "405% above"

    @pytest.mark.parametrize("field", PEER_METRICS)
    def test_every_metric_has_its_own_reading_both_ways(self, field):
        """The first version gave only P/E and P/B a reading, and the model borrowed "more
        expensive" for ROE and margins in 4/10 live runs. No metric may lack one."""
        low = compare_metric(field, 0.01, {"median": 0.5, "p25": 0.1, "p75": 0.9})
        high = compare_metric(field, 0.99, {"median": 0.5, "p25": 0.1, "p75": 0.9})
        assert (low["reading"], high["reading"]) == METRIC_READINGS[field]
        assert low["reading"] != high["reading"]

    def test_only_valuation_ratios_speak_of_price(self):
        """'Higher ROE = more expensive' is the misreading this vocabulary exists to stop."""
        for field, readings in METRIC_READINGS.items():
            priced = any(w in r for r in readings for w in ("cheap", "expensive"))
            assert priced == (field in VALUATION_RATIOS), field

    def test_profitability_readings_disclaim_price(self):
        for field in ("return_on_equity", "profit_margins"):
            assert all("not a price measure" in r for r in METRIC_READINGS[field])

    def test_readings_cover_exactly_the_compared_metrics(self):
        assert set(METRIC_READINGS) == set(PEER_METRICS)

    def test_the_dividend_yield_misread_case_reads_lower(self):
        """Live run 8 called NVDA's 0.44% yield 'significantly higher' than a 1.09% median."""
        row = compare_metric(
            "dividend_yield", 0.0044, {"median": 0.0109, "p25": 0.005, "p75": 0.02}
        )
        assert row["vs_median"] == "60% below"
        assert row["reading"] == "pays a lower yield than the typical peer"

    @pytest.mark.parametrize("field", sorted(VALUATION_RATIOS))
    def test_a_negative_valuation_ratio_gets_no_comparison(self, field):
        row = compare_metric(field, -15.0, _STATS)
        assert row == {
            "company": -15.0,
            "vs_median": "negative - losses or negative equity, no meaningful comparison",
        }

    def test_a_negative_margin_is_still_compared(self):
        row = compare_metric("profit_margins", -0.05, {"median": 0.18, "p25": 0.1, "p75": 0.27})
        assert row["vs_median"] == "128% below"

    def test_missing_company_value_or_peer_stats(self):
        assert compare_metric("trailing_pe", None, _STATS) == {
            "company": None,
            "vs_median": "no company data",
        }
        assert compare_metric("trailing_pe", 20.0, None)["vs_median"] == "no peer data"


@pytest.mark.django_db
class TestPeerComparisonTool:
    @pytest.fixture
    def market(self, db):
        """A 4-company industry inside a sector with 2 more companies elsewhere."""
        tech = Sector.objects.create(name="Technology")
        semis = Industry.objects.create(name="Semiconductors", sector=tech)
        software = Industry.objects.create(name="Software", sector=tech)
        rows = [
            ("NVDA", semis, 28.49, 0.6366),
            ("AMD", semis, 90.0, 0.10),
            ("INTC", semis, -20.0, -0.30),
            ("AVGO", semis, 45.06, 0.36),
            ("MSFT", software, 28.74, 0.36),
            ("CRM", software, 40.0, 0.16),
        ]
        for symbol, industry, pe, margin in rows:
            company = Company.objects.create(
                symbol=symbol, sector=tech, industry=industry, name=symbol
            )
            CompanySnapshot.objects.create(
                company=company, trailing_pe=pe, profit_margins=margin, market_cap=1, raw={}
            )

    def test_defaults_to_the_industry_when_it_has_enough_peers(self, market):
        obs = _obs("peer_comparison", {"symbol": "NVDA"})
        assert obs["peer_group"] == {"scope": "industry", "name": "Semiconductors", "peers": 3}

    def test_the_company_is_excluded_from_its_own_median(self, market):
        pe = _obs("peer_comparison", {"symbol": "NVDA"})["comparisons"]["trailing_pe"]
        # peers AMD 90, AVGO 45.06 (INTC's negative excluded) -> median 67.53, not incl. 28.49
        assert pe["median"] == 67.53
        assert pe["vs_median"] == "58% below"
        assert pe["reading"] == "cheaper than the typical peer"

    def test_explicit_sector_scope(self, market):
        obs = _obs("peer_comparison", {"symbol": "NVDA", "scope": "Sector"})
        assert obs["peer_group"]["scope"] == "sector"
        assert obs["peer_group"]["peers"] == 5
        # peers 90, 45.06, 28.74, 40 -> median 42.53
        assert obs["comparisons"]["trailing_pe"]["median"] == 42.53

    def test_percent_fields_use_pct_names(self, market):
        comps = _obs("peer_comparison", {"symbol": "NVDA"})["comparisons"]
        assert comps["profit_margins_pct"]["company"] == 63.66
        assert "profit_margins" not in comps

    def test_valuation_ratios_come_first(self, market):
        """Chat carries only the first 600 chars forward; "is it cheap?" must survive it."""
        obs = _obs("peer_comparison", {"symbol": "NVDA"})
        assert list(obs)[:3] == ["symbol", "peer_group", "comparisons"]
        assert list(obs["comparisons"])[:3] == ["trailing_pe", "forward_pe", "price_to_book"]
        assert list(obs)[-1] == "how_to_read"

    def test_an_explicit_scope_too_small_is_reported_not_widened(self, market):
        obs = _obs("peer_comparison", {"symbol": "MSFT", "scope": "industry"})
        assert obs["peer_group"] is None
        assert "its industry" in obs["note"]
        assert obs["company_metrics"]["trailing_pe"] == pytest.approx(28.74)

    def test_auto_scope_falls_back_to_the_sector(self, market):
        obs = _obs("peer_comparison", {"symbol": "MSFT"})
        assert obs["peer_group"]["scope"] == "sector"

    def test_bad_scope_symbol_and_missing_snapshot_are_errors(self, market):
        assert "scope must be" in _obs("peer_comparison", {"symbol": "NVDA", "scope": "x"})["error"]
        assert "No company" in _obs("peer_comparison", {"symbol": "ZZZZ"})["error"]
        Company.objects.create(symbol="BARE")
        assert "No snapshot" in _obs("peer_comparison", {"symbol": "BARE"})["error"]

    def test_fits_inside_the_turn_reserve(self, market):
        from apps.llm_analysis._context import estimate_tokens
        from apps.llm_analysis.chat_agent import MAX_PREFETCH, TURN_RESERVE

        raw = run_tool("peer_comparison", {"symbol": "NVDA"})
        # Two prefetched tickers must leave over half the turn's reserve for everything else.
        assert estimate_tokens(raw) * MAX_PREFETCH <= TURN_RESERVE // 2

    def test_peer_group_is_the_summary_rule(self, market):
        """companies.services delegates to it - one home for the group choice."""
        from apps.companies.services import _peer_group

        nvda = Company.objects.get(symbol="NVDA")
        level, name, peers = _peer_group(nvda)
        assert (level, name) == peer_group(nvda)[:2] == ("industry", "Semiconductors")
        assert not peers.filter(pk=nvda.pk).exists()
