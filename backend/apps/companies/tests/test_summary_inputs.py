"""Phase 1 of issue #3: the numbers the AI summary is fed must be correct and comparable.

Covers the percent-vs-fraction unit fix (ingestion + backfill migration), the new
price/technicals/peer/streak inputs, and the tolerance of a company with no data.
"""

from datetime import UTC, date, timedelta
from datetime import datetime as dt
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from apps.companies.models import (
    Company,
    CompanySnapshot,
    Dividend,
    EarningsDate,
    Industry,
    PriceBar,
    Sector,
    ShortInterest,
)
from apps.companies.services import (
    _assemble_company_data,
    _build_prompt_text,
    _fmt,
    _fmt_already_pct,
)
from apps.companies.yfinance_client import YFinanceClient

# ---------------------------------------------------------------------------
# Units: yfinance percent -> stored fraction
# ---------------------------------------------------------------------------


class TestIngestionUnits:
    def _ticker(self, MockTicker, info: dict):
        mock = MagicMock()
        mock.info = info
        mock.recommendations = pd.DataFrame()
        MockTicker.return_value = mock

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_percent_fields_divided_by_100(self, MockTicker):
        self._ticker(
            MockTicker,
            {
                "symbol": "AAPL",
                "dividendYield": 0.34,
                "debtToEquity": 78.445,
                "fiveYearAvgDividendYield": 0.55,
                # already a fraction in yfinance - must be left alone
                "profitMargins": 0.2431,
            },
        )
        snap = YFinanceClient().get_snapshot("AAPL")
        assert snap["dividend_yield"] == pytest.approx(0.0034)
        assert snap["debt_to_equity"] == pytest.approx(0.78445)
        assert snap["five_year_avg_dividend_yield"] == pytest.approx(0.0055)
        assert snap["profit_margins"] == pytest.approx(0.2431)

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_missing_percent_fields_stay_none(self, MockTicker):
        self._ticker(MockTicker, {"symbol": "AAPL"})
        snap = YFinanceClient().get_snapshot("AAPL")
        assert snap["dividend_yield"] is None
        assert snap["debt_to_equity"] is None
        assert snap["five_year_avg_dividend_yield"] is None


class TestRenderedUnits:
    def test_dividend_yield_renders_as_sub_percent(self):
        assert _fmt(0.0034, pct=True) == "0.34%"

    def test_debt_to_equity_renders_as_ratio(self):
        assert _fmt(0.78445) == "0.78"

    def test_surprise_pct_is_already_percent(self):
        assert _fmt_already_pct(6.74) == "6.74%"
        assert _fmt_already_pct(None) == "N/A"


@pytest.mark.django_db
class TestBackfillMigration:
    def test_scaling_functions_round_trip(self):
        import importlib

        from django.apps import apps as global_apps

        mod = importlib.import_module("apps.companies.migrations.0012_backfill_percent_to_fraction")
        company = Company.objects.create(symbol="AAPL")
        snap = CompanySnapshot.objects.create(
            company=company,
            dividend_yield=0.34,
            debt_to_equity=154.49,
            five_year_avg_dividend_yield=0.55,
            raw={},
        )

        mod.to_fraction(global_apps, None)
        snap.refresh_from_db()
        assert snap.dividend_yield == pytest.approx(0.0034)
        assert snap.debt_to_equity == pytest.approx(1.5449)
        assert snap.five_year_avg_dividend_yield == pytest.approx(0.0055)

        mod.to_percent(global_apps, None)
        snap.refresh_from_db()
        assert snap.dividend_yield == pytest.approx(0.34)
        assert snap.debt_to_equity == pytest.approx(154.49)

    def test_null_rows_untouched(self):
        import importlib

        from django.apps import apps as global_apps

        mod = importlib.import_module("apps.companies.migrations.0012_backfill_percent_to_fraction")
        company = Company.objects.create(symbol="NULLCO")
        snap = CompanySnapshot.objects.create(company=company, raw={})
        mod.to_fraction(global_apps, None)
        snap.refresh_from_db()
        assert snap.dividend_yield is None


# ---------------------------------------------------------------------------
# Assembled inputs
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAssembleCompanyData:
    def setup_method(self):
        self.sector = Sector.objects.create(name="Technology")
        self.industry = Industry.objects.create(name="Consumer Electronics", sector=self.sector)
        self.company = Company.objects.create(
            symbol="AAPL", name="Apple Inc.", sector=self.sector, industry=self.industry
        )

    def _snapshot(self, **kwargs):
        defaults = {
            "company": self.company,
            "market_cap": 3_000_000_000_000,
            "trailing_pe": 30.0,
            "price_to_book": 50.0,
            "profit_margins": 0.24,
            "return_on_equity": 1.5,
            "dividend_yield": 0.0034,
            "debt_to_equity": 1.54,
            "trailing_eps": 6.5,
            "fifty_two_week_high": 260.0,
            "fifty_two_week_low": 160.0,
            "fifty_day_average": 230.0,
            "two_hundred_day_average": 220.0,
            "target_mean_price": 250.0,
            "raw": {},
        }
        defaults.update(kwargs)
        return CompanySnapshot.objects.create(**defaults)

    def test_values_are_numbers_not_strings(self):
        self._snapshot()
        data = _assemble_company_data(self.company)
        assert data["valuation"]["trailing_pe"] == 30.0
        assert data["valuation"]["market_cap"] == 3_000_000_000_000
        assert isinstance(data["dividends"]["yield"], float)

    def test_price_and_technicals(self):
        self._snapshot()
        PriceBar.objects.create(
            company=self.company,
            date=date(2026, 9, 15),
            open=Decimal("209"),
            high=Decimal("211"),
            low=Decimal("208"),
            close=Decimal("210"),
            volume=1000,
        )
        data = _assemble_company_data(self.company)
        assert data["price"]["close"] == 210.0
        assert data["price"]["as_of"] == "2026-09-15"
        assert data["price"]["fifty_day_average"] == 230.0
        # (210 - 160) / (260 - 160)
        assert data["price"]["position_in_52w_range"] == pytest.approx(0.5)

    def test_implied_upside_computed(self):
        self._snapshot()
        PriceBar.objects.create(
            company=self.company,
            date=date(2026, 9, 15),
            open=Decimal("200"),
            high=Decimal("200"),
            low=Decimal("200"),
            close=Decimal("200"),
            volume=1,
        )
        data = _assemble_company_data(self.company)
        assert data["analyst"]["implied_upside"] == pytest.approx(0.25)

    def test_implied_upside_none_without_price(self):
        self._snapshot()
        data = _assemble_company_data(self.company)
        assert data["analyst"]["implied_upside"] is None

    def test_implied_upside_none_without_target(self):
        self._snapshot(target_mean_price=None)
        PriceBar.objects.create(
            company=self.company,
            date=date(2026, 9, 15),
            open=Decimal("200"),
            high=Decimal("200"),
            low=Decimal("200"),
            close=Decimal("200"),
            volume=1,
        )
        data = _assemble_company_data(self.company)
        assert data["analyst"]["implied_upside"] is None

    def test_earnings_history_and_beat_streak(self):
        for i, surprise in enumerate([6.74, 3.1, -1.2, 0.5]):
            EarningsDate.objects.create(
                company=self.company,
                earnings_date=date(2026, 8, 1) - timedelta(days=90 * i),
                reported_eps=1.5,
                eps_estimate=1.4,
                surprise_pct=surprise,
            )
        data = _assemble_company_data(self.company)
        assert len(data["earnings_history"]) == 4
        assert data["earnings_beat_streak"] == {"beats": 3, "quarters": 4}

    def test_dividend_ttm_and_coverage(self):
        self._snapshot()
        today = dt.now(UTC).date()
        for i in range(4):
            Dividend.objects.create(
                company=self.company,
                date=today - timedelta(days=80 * i),
                amount=Decimal("0.25"),
            )
        # outside the trailing 12 months - excluded
        Dividend.objects.create(
            company=self.company, date=today - timedelta(days=400), amount=Decimal("0.25")
        )
        data = _assemble_company_data(self.company)
        assert data["dividends"]["ttm_total_per_share"] == pytest.approx(1.0)
        assert data["dividends"]["eps_coverage"] == pytest.approx(6.5)

    def test_short_interest_month_over_month(self):
        ShortInterest.objects.create(
            company=self.company,
            fetched_at=dt.now(UTC),
            shares_short=110,
            shares_short_prior_month=100,
            short_ratio=1.2,
        )
        data = _assemble_company_data(self.company)
        assert data["short_interest"]["month_over_month_change"] == pytest.approx(0.1)

    def test_tolerates_company_with_no_data(self):
        bare = Company.objects.create(symbol="EMPTY")
        data = _assemble_company_data(bare)
        assert data["symbol"] == "EMPTY"
        assert "valuation" not in data
        assert "price" not in data
        assert "peers" not in data
        # the prompt still renders
        assert "EMPTY" in _build_prompt_text(data)


@pytest.mark.django_db
class TestPeerBenchmark:
    def setup_method(self):
        self.sector = Sector.objects.create(name="Technology")
        self.industry = Industry.objects.create(name="Consumer Electronics", sector=self.sector)
        self.other_industry = Industry.objects.create(name="Software", sector=self.sector)
        self.company = Company.objects.create(
            symbol="AAPL", sector=self.sector, industry=self.industry
        )
        CompanySnapshot.objects.create(company=self.company, trailing_pe=30.0, raw={})

    def _peer(self, symbol, industry, pe):
        peer = Company.objects.create(symbol=symbol, sector=self.sector, industry=industry)
        CompanySnapshot.objects.create(company=peer, trailing_pe=pe, market_cap=1, raw={})
        return peer

    def test_uses_industry_when_it_has_enough_peers(self):
        for i, pe in enumerate([10.0, 20.0, 30.0]):
            self._peer(f"IND{i}", self.industry, pe)
        data = _assemble_company_data(self.company)
        assert data["peers"]["group"] == "industry"
        assert data["peers"]["name"] == "Consumer Electronics"
        assert data["peers"]["metrics"]["trailing_pe"]["peer_median"] == pytest.approx(20.0)
        assert data["peers"]["metrics"]["trailing_pe"]["company"] == pytest.approx(30.0)

    def test_falls_back_to_sector_below_three_industry_peers(self):
        self._peer("IND0", self.industry, 10.0)
        for i, pe in enumerate([20.0, 40.0]):
            self._peer(f"SW{i}", self.other_industry, pe)
        data = _assemble_company_data(self.company)
        assert data["peers"]["group"] == "sector"
        assert data["peers"]["name"] == "Technology"
        assert data["peers"]["metrics"]["trailing_pe"]["peer_median"] == pytest.approx(20.0)

    def test_omitted_when_neither_group_has_peers(self):
        data = _assemble_company_data(self.company)
        assert "peers" not in data

    def test_omitted_when_peers_have_no_snapshots(self):
        for i in range(3):
            Company.objects.create(symbol=f"NOSNAP{i}", sector=self.sector, industry=self.industry)
        data = _assemble_company_data(self.company)
        assert "peers" not in data

    def test_rendered_beside_the_company_value(self):
        for i, pe in enumerate([10.0, 20.0, 30.0]):
            self._peer(f"IND{i}", self.industry, pe)
        text = _build_prompt_text(_assemble_company_data(self.company))
        assert "Peer Benchmark" in text
        assert "Trailing P/E: company 30.00 vs peer median 20.00" in text

    def test_peer_median_matches_the_plain_median_for_every_metric(self):
        # Issue #9 phase 1 reshaped aggregate_snapshots' stats; the summary reads only
        # `median` from it, and must get exactly the numbers it got before.
        values = {
            "trailing_pe": [12.0, 18.0, 25.0, 40.0],
            "forward_pe": [10.0, 15.0, 20.0, 30.0],
            "price_to_book": [1.0, 3.0, 5.0, 9.0],
            "profit_margins": [0.05, 0.10, 0.15, 0.30],
            "return_on_equity": [0.08, 0.12, 0.20, 0.40],
            "dividend_yield": [0.01, 0.02, 0.03, 0.04],
            "debt_to_equity": [0.2, 0.5, 1.0, 3.0],
        }
        for i in range(4):
            peer = Company.objects.create(
                symbol=f"IND{i}", sector=self.sector, industry=self.industry
            )
            CompanySnapshot.objects.create(
                company=peer, raw={}, **{field: vals[i] for field, vals in values.items()}
            )
        metrics = _assemble_company_data(self.company)["peers"]["metrics"]
        expected = {
            "trailing_pe": 21.5,
            "forward_pe": 17.5,
            "price_to_book": 4.0,
            "profit_margins": 0.125,
            "return_on_equity": 0.16,
            "dividend_yield": 0.025,
            "debt_to_equity": 0.75,
        }
        for field, median in expected.items():
            assert metrics[field]["peer_median"] == pytest.approx(median), field
            assert metrics[field]["peer_n"] == 4, field

    def test_negative_pb_peer_is_excluded_so_the_median_rises(self):
        # Issue #9 phase 2: a DELIBERATE change to a shipped number. A peer with negative book
        # equity used to drag the P/B median down (-> 3.0); it is now excluded and counted.
        for i, pb in enumerate([-8.0, 2.0, 4.0, 6.0]):
            peer = Company.objects.create(
                symbol=f"IND{i}", sector=self.sector, industry=self.industry
            )
            CompanySnapshot.objects.create(company=peer, price_to_book=pb, raw={})
        row = _assemble_company_data(self.company)["peers"]["metrics"]["price_to_book"]
        assert row["peer_median"] == pytest.approx(4.0)
        assert row["peer_n"] == 3
        assert row["peer_negative"] == 1

    def test_negative_roe_peer_still_counts(self):
        for i, roe in enumerate([-0.4, 0.1, 0.2, 0.3]):
            peer = Company.objects.create(
                symbol=f"IND{i}", sector=self.sector, industry=self.industry
            )
            CompanySnapshot.objects.create(company=peer, return_on_equity=roe, raw={})
        row = _assemble_company_data(self.company)["peers"]["metrics"]["return_on_equity"]
        assert row["peer_median"] == pytest.approx(0.15)
        assert row["peer_n"] == 4
        assert "peer_negative" not in row

    def test_own_negative_pe_gets_no_peer_comparison(self):
        CompanySnapshot.objects.create(company=self.company, trailing_pe=-15.0, raw={})
        for i, pe in enumerate([10.0, 20.0, 30.0]):
            self._peer(f"IND{i}", self.industry, pe)
        text = _build_prompt_text(_assemble_company_data(self.company))
        assert (
            "Trailing P/E: company -15.00 (negative - losses or negative equity,"
            " no meaningful peer comparison)" in text
        )
        assert "Trailing P/E: company -15.00 vs peer median" not in text

    def test_all_negative_peers_render_na_not_a_number(self):
        for i, pe in enumerate([-5.0, -10.0, -20.0]):
            self._peer(f"IND{i}", self.industry, pe)
        data = _assemble_company_data(self.company)
        row = data["peers"]["metrics"]["trailing_pe"]
        assert row["peer_median"] is None
        text = _build_prompt_text(data)
        assert "Trailing P/E: company 30.00 vs peer median N/A" in text

    def test_own_zero_pe_is_still_compared(self):
        # The boundary: only a NEGATIVE own value withholds the median.
        CompanySnapshot.objects.create(company=self.company, trailing_pe=0.0, raw={})
        for i, pe in enumerate([10.0, 20.0, 30.0]):
            self._peer(f"IND{i}", self.industry, pe)
        text = _build_prompt_text(_assemble_company_data(self.company))
        assert "Trailing P/E: company 0.00 vs peer median 20.00" in text

    def test_own_negative_roe_is_still_compared(self):
        CompanySnapshot.objects.create(company=self.company, return_on_equity=-0.1, raw={})
        for i, pe in enumerate([10.0, 20.0, 30.0]):
            self._peer(f"IND{i}", self.industry, pe)
        text = _build_prompt_text(_assemble_company_data(self.company))
        assert "Return on equity: company -10.00% vs peer median" in text


@pytest.mark.django_db
class TestPromptUnitRegressions:
    """The baseline failures from docs/project_docs/baselines/ai-summary-2026-09-16.md.

    These pin the exact strings the model used to be told - 244% yields, 674% surprises
    and 78x debt/equity - so a regression is caught here rather than in prose.
    """

    def setup_method(self):
        self.company = Company.objects.create(symbol="KO", name="Coca-Cola")

    def test_dividend_yield_and_leverage_render_at_true_scale(self):
        CompanySnapshot.objects.create(
            company=self.company,
            dividend_yield=0.0244,  # 2.44%, stored as a fraction
            debt_to_equity=0.78445,
            raw={},
        )
        text = _build_prompt_text(_assemble_company_data(self.company))
        assert "dividend yield: 2.44%" in text
        assert "debt/equity: 0.78" in text
        assert "244" not in text

    def test_earnings_surprise_stays_in_percent(self):
        EarningsDate.objects.create(
            company=self.company,
            earnings_date=date(2026, 7, 20),
            reported_eps=0.87,
            eps_estimate=0.82,
            surprise_pct=6.74,
        )
        text = _build_prompt_text(_assemble_company_data(self.company))
        assert "surprise 6.74%" in text
        assert "674" not in text

    def test_implied_upside_rendered_as_a_percent(self):
        CompanySnapshot.objects.create(company=self.company, target_mean_price=75.0, raw={})
        PriceBar.objects.create(
            company=self.company,
            date=date(2026, 9, 15),
            open=Decimal("60"),
            high=Decimal("60"),
            low=Decimal("60"),
            close=Decimal("60"),
            volume=1,
        )
        text = _build_prompt_text(_assemble_company_data(self.company))
        assert "implied upside vs last close: 25.00%" in text
