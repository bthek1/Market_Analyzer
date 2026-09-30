import json
from datetime import UTC, date, timedelta
from datetime import datetime as dt
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.companies.models import (
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
from apps.companies.services import (
    backfill_snapshot_fields,
    bootstrap_next_batch,
    discover_and_create_stubs,
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

MOCK_PROFILE = {
    "name": "Apple Inc.",
    "exchange": "NASDAQ",
    "currency": "USD",
    "sector": "Technology",
    "industry": "Consumer Electronics",
    "address": "One Apple Park Way",
    "city": "Cupertino",
    "state": "CA",
    "zip_code": "95014",
    "country": "United States",
    "phone": "408-996-1010",
    "website": "https://www.apple.com",
    "ir_website": "",
    "description": "Apple designs consumer electronics.",
    "full_time_employees": 150000,
    "officers": [
        {
            "name": "Tim Cook",
            "title": "CEO",
            "age": 63,
            "year_born": 1960,
            "fiscal_year": None,
            "total_pay": 49000000,
            "exercised_value": None,
            "unexercised_value": None,
        }
    ],
}

MOCK_SNAPSHOT = {
    "market_cap": 3_000_000_000_000,
    "trailing_pe": 28.5,
    "forward_pe": 25.0,
    "price_to_book": 45.0,
    "debt_to_equity": 150.0,
    "return_on_equity": 1.45,
    "profit_margins": 0.25,
    "dividend_yield": 0.005,
    "trailing_eps": 6.13,
    "forward_eps": 7.20,
    # New fields
    "beta": 1.24,
    "fifty_two_week_high": 199.62,
    "fifty_two_week_low": 124.17,
    "week52_change": 0.45,
    "sandp52_week_change": 0.22,
    "average_volume": 55_000_000,
    "shares_outstanding": 15_550_061_000,
    "float_shares": 15_549_000_000,
    "enterprise_value": 2_900_000_000_000,
    "enterprise_to_revenue": 7.5,
    "enterprise_to_ebitda": 22.0,
    "peg_ratio": 2.1,
    "trailing_peg_ratio": None,
    "price_to_sales": 7.8,
    "payout_ratio": 0.15,
    "book_value": 4.25,
    "fifty_day_average": 185.0,
    "two_hundred_day_average": 175.0,
    "revenue_growth": 0.02,
    "earnings_growth": 0.05,
    "earnings_quarterly_growth": 0.08,
    "gross_margins": 0.44,
    "operating_margins": 0.30,
    "ebitda_margins": 0.33,
    "current_ratio": 1.07,
    "quick_ratio": 0.95,
    "return_on_assets": 0.28,
    "ebitda": 130_000_000_000,
    "total_cash": 50_000_000_000,
    "total_cash_per_share": 3.20,
    "free_cashflow": 90_000_000_000,
    "operating_cashflow": 110_000_000_000,
    "net_income_to_common": 97_000_000_000,
    "revenue_per_share": 25.0,
    "held_pct_institutions": 0.62,
    "held_pct_insiders": 0.003,
    "dividend_rate": 1.0,
    "ex_dividend_date": date(2024, 2, 9),
    "five_year_avg_dividend_yield": 0.7,
    "trailing_annual_dividend_rate": 0.96,
    "last_dividend_value": 0.25,
    "last_dividend_date": date(2024, 2, 15),
    "last_fiscal_year_end": date(2023, 9, 30),
    "next_fiscal_year_end": date(2024, 9, 30),
    "most_recent_quarter": date(2024, 3, 31),
    "audit_risk": 4,
    "board_risk": 1,
    "compensation_risk": 3,
    "shareholder_rights_risk": 1,
    "overall_risk": 2,
    "recommendation_mean": 1.8,
    "recommendation_key": "buy",
    "num_analyst_opinions": 37,
    "target_high_price": 250.0,
    "target_low_price": 158.0,
    "target_mean_price": 210.0,
    "target_median_price": 215.0,
    "recommendations_breakdown": [],
    "last_split_factor": "4:1",
    "last_split_date": date(2020, 8, 31),
    "raw": {"symbol": "AAPL", "beta": 1.24},
}

MOCK_PRICES = [
    {
        "date": date(2024, 1, 1),
        "open": Decimal("150"),
        "high": Decimal("155"),
        "low": Decimal("149"),
        "close": Decimal("153"),
        "volume": 1000000,
    },
    {
        "date": date(2024, 1, 2),
        "open": Decimal("153"),
        "high": Decimal("158"),
        "low": Decimal("152"),
        "close": Decimal("157"),
        "volume": 900000,
    },
]

MOCK_FINANCIALS = [
    {
        "statement_type": "income",
        "period": "annual",
        "period_end": date(2023, 12, 31),
        "metric": "Revenue",
        "value": 383285000000.0,
    },
    {
        "statement_type": "balance",
        "period": "annual",
        "period_end": date(2023, 12, 31),
        "metric": "Total Assets",
        "value": 352583000000.0,
    },
]

MOCK_DIVIDENDS = [
    {"date": date(2024, 3, 1), "amount": Decimal("0.2400")},
    {"date": date(2024, 6, 1), "amount": Decimal("0.2500")},
]


# ---------------------------------------------------------------------------
# sync_company_profile
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSyncCompanyProfile:
    @patch("apps.companies.services.YFinanceClient")
    def test_creates_company(self, MockYF):
        MockYF.return_value.get_profile.return_value = MOCK_PROFILE
        company = sync_company_profile("AAPL")
        assert company is not None
        assert company.symbol == "AAPL"
        assert company.name == "Apple Inc."

    @patch("apps.companies.services.YFinanceClient")
    def test_creates_sector_and_industry(self, MockYF):
        MockYF.return_value.get_profile.return_value = MOCK_PROFILE
        sync_company_profile("AAPL")
        assert Sector.objects.filter(name="Technology").exists()
        assert Industry.objects.filter(name="Consumer Electronics").exists()

    @patch("apps.companies.services.YFinanceClient")
    def test_sector_and_industry_linked_to_company(self, MockYF):
        MockYF.return_value.get_profile.return_value = MOCK_PROFILE
        company = sync_company_profile("AAPL")
        assert company.sector.name == "Technology"
        assert company.industry.name == "Consumer Electronics"

    @patch("apps.companies.services.YFinanceClient")
    def test_industry_linked_to_sector(self, MockYF):
        MockYF.return_value.get_profile.return_value = MOCK_PROFILE
        sync_company_profile("AAPL")
        ind = Industry.objects.get(name="Consumer Electronics")
        assert ind.sector.name == "Technology"

    @patch("apps.companies.services.YFinanceClient")
    def test_exchange_and_currency_stored(self, MockYF):
        MockYF.return_value.get_profile.return_value = MOCK_PROFILE
        company = sync_company_profile("AAPL")
        assert company.exchange == "NASDAQ"
        assert company.currency == "USD"

    @patch("apps.companies.services.YFinanceClient")
    def test_stores_address_and_description(self, MockYF):
        MockYF.return_value.get_profile.return_value = MOCK_PROFILE
        company = sync_company_profile("AAPL")
        assert company.address == "One Apple Park Way"
        assert company.city == "Cupertino"
        assert company.country == "United States"
        assert company.description == "Apple designs consumer electronics."
        assert company.full_time_employees == 150000

    @patch("apps.companies.services.YFinanceClient")
    def test_officers_replaced_not_appended(self, MockYF):
        MockYF.return_value.get_profile.return_value = MOCK_PROFILE
        sync_company_profile("AAPL")
        sync_company_profile("AAPL")
        company = Company.objects.get(symbol="AAPL")
        assert len(company.officers) == 1  # not doubled

    @patch("apps.companies.services.YFinanceClient")
    def test_reuses_existing_sector(self, MockYF):
        Sector.objects.create(name="Technology")
        MockYF.return_value.get_profile.return_value = MOCK_PROFILE
        sync_company_profile("AAPL")
        assert Sector.objects.filter(name="Technology").count() == 1

    @patch("apps.companies.services.YFinanceClient")
    def test_updates_existing_company(self, MockYF):
        Company.objects.create(symbol="AAPL", name="Old Name")
        MockYF.return_value.get_profile.return_value = MOCK_PROFILE
        company = sync_company_profile("AAPL")
        assert company.name == "Apple Inc."
        assert Company.objects.filter(symbol="AAPL").count() == 1

    @patch("apps.companies.services.YFinanceClient")
    def test_returns_none_when_no_data(self, MockYF):
        MockYF.return_value.get_profile.return_value = None
        assert sync_company_profile("ZZZZZ") is None


# ---------------------------------------------------------------------------
# sync_price_history
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSyncPriceHistory:
    @patch("apps.companies.services.YFinanceClient")
    def test_creates_price_bars(self, MockYF):
        Company.objects.create(symbol="AAPL")
        MockYF.return_value.get_price_history.return_value = MOCK_PRICES
        count = sync_price_history("AAPL")
        assert count == 2
        assert PriceBar.objects.filter(company__symbol="AAPL").count() == 2

    @patch("apps.companies.services.YFinanceClient")
    def test_ignores_duplicate_bars(self, MockYF):
        Company.objects.create(symbol="AAPL")
        MockYF.return_value.get_price_history.return_value = MOCK_PRICES
        sync_price_history("AAPL")
        sync_price_history("AAPL")
        assert PriceBar.objects.count() == 2

    @patch("apps.companies.services.YFinanceClient")
    def test_returns_zero_for_unknown_symbol(self, MockYF):
        MockYF.return_value.get_price_history.return_value = MOCK_PRICES
        assert sync_price_history("ZZZZZ") == 0

    @patch("apps.companies.services.YFinanceClient")
    def test_returns_zero_when_no_bars(self, MockYF):
        Company.objects.create(symbol="AAPL")
        MockYF.return_value.get_price_history.return_value = []
        assert sync_price_history("AAPL") == 0

    @patch("apps.companies.services.YFinanceClient")
    def test_incremental_passes_start_when_bars_exist(self, MockYF):
        company = Company.objects.create(symbol="AAPL")
        PriceBar.objects.create(
            company=company,
            date=date(2024, 1, 2),
            open="153",
            high="158",
            low="152",
            close="157",
            volume=900000,
        )
        MockYF.return_value.get_price_history.return_value = []
        sync_price_history("AAPL")
        MockYF.return_value.get_price_history.assert_called_once_with(
            "AAPL", period=None, start=date(2024, 1, 2)
        )

    @patch("apps.companies.services.YFinanceClient")
    def test_incremental_passes_no_start_when_no_bars(self, MockYF):
        Company.objects.create(symbol="AAPL")
        MockYF.return_value.get_price_history.return_value = []
        sync_price_history("AAPL")
        MockYF.return_value.get_price_history.assert_called_once_with(
            "AAPL", period=None, start=None
        )

    @patch("apps.companies.services.YFinanceClient")
    def test_explicit_period_overrides_incremental(self, MockYF):
        company = Company.objects.create(symbol="AAPL")
        PriceBar.objects.create(
            company=company,
            date=date(2024, 1, 2),
            open="153",
            high="158",
            low="152",
            close="157",
            volume=900000,
        )
        MockYF.return_value.get_price_history.return_value = []
        sync_price_history("AAPL", period="max")
        MockYF.return_value.get_price_history.assert_called_once_with(
            "AAPL", period="max", start=None
        )


# ---------------------------------------------------------------------------
# sync_snapshot
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSyncSnapshot:
    @patch("apps.companies.services.YFinanceClient")
    def test_creates_snapshot(self, MockYF):
        Company.objects.create(symbol="AAPL")
        MockYF.return_value.get_snapshot.return_value = MOCK_SNAPSHOT
        snap = sync_snapshot("AAPL")
        assert snap is not None
        assert snap.market_cap == 3_000_000_000_000
        assert snap.trailing_pe == 28.5

    @patch("apps.companies.services.YFinanceClient")
    def test_each_call_creates_new_snapshot(self, MockYF):
        Company.objects.create(symbol="AAPL")
        MockYF.return_value.get_snapshot.return_value = MOCK_SNAPSHOT
        sync_snapshot("AAPL")
        sync_snapshot("AAPL")
        assert CompanySnapshot.objects.count() == 2

    @patch("apps.companies.services.YFinanceClient")
    def test_returns_none_for_unknown_symbol(self, MockYF):
        MockYF.return_value.get_snapshot.return_value = MOCK_SNAPSHOT
        assert sync_snapshot("ZZZZZ") is None

    @patch("apps.companies.services.YFinanceClient")
    def test_returns_none_when_no_data(self, MockYF):
        Company.objects.create(symbol="AAPL")
        MockYF.return_value.get_snapshot.return_value = None
        assert sync_snapshot("AAPL") is None


# ---------------------------------------------------------------------------
# sync_financials
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSyncFinancials:
    @patch("apps.companies.services.YFinanceClient")
    def test_creates_financial_rows(self, MockYF):
        Company.objects.create(symbol="AAPL")
        MockYF.return_value.get_financials.return_value = MOCK_FINANCIALS
        count = sync_financials("AAPL")
        assert count == 2
        assert FinancialStatement.objects.filter(company__symbol="AAPL").count() == 2

    @patch("apps.companies.services.YFinanceClient")
    def test_upserts_existing_rows(self, MockYF):
        Company.objects.create(symbol="AAPL")
        MockYF.return_value.get_financials.return_value = MOCK_FINANCIALS
        sync_financials("AAPL")
        updated = [
            {
                "statement_type": "income",
                "period": "annual",
                "period_end": date(2023, 12, 31),
                "metric": "Revenue",
                "value": 999.0,
            },
            MOCK_FINANCIALS[1],
        ]
        MockYF.return_value.get_financials.return_value = updated
        sync_financials("AAPL")
        assert FinancialStatement.objects.count() == 2
        assert FinancialStatement.objects.get(metric="Revenue").value == 999.0

    @patch("apps.companies.services.YFinanceClient")
    def test_returns_zero_for_unknown_symbol(self, MockYF):
        MockYF.return_value.get_financials.return_value = MOCK_FINANCIALS
        assert sync_financials("ZZZZZ") == 0


# ---------------------------------------------------------------------------
# sync_dividends
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSyncDividends:
    @patch("apps.companies.services.YFinanceClient")
    def test_creates_dividend_rows(self, MockYF):
        Company.objects.create(symbol="AAPL")
        MockYF.return_value.get_dividends.return_value = MOCK_DIVIDENDS
        count = sync_dividends("AAPL")
        assert count == 2
        assert Dividend.objects.filter(company__symbol="AAPL").count() == 2

    @patch("apps.companies.services.YFinanceClient")
    def test_ignores_duplicate_dividends(self, MockYF):
        Company.objects.create(symbol="AAPL")
        MockYF.return_value.get_dividends.return_value = MOCK_DIVIDENDS
        sync_dividends("AAPL")
        sync_dividends("AAPL")
        assert Dividend.objects.count() == 2

    @patch("apps.companies.services.YFinanceClient")
    def test_returns_zero_for_unknown_symbol(self, MockYF):
        MockYF.return_value.get_dividends.return_value = MOCK_DIVIDENDS
        assert sync_dividends("ZZZZZ") == 0


# ---------------------------------------------------------------------------
# sync_all_for_symbol
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSyncAllForSymbol:
    def _mock_yf(self, MockYF, *, profile=MOCK_PROFILE):
        MockYF.return_value.get_profile.return_value = profile
        MockYF.return_value.get_price_history.return_value = MOCK_PRICES
        MockYF.return_value.get_snapshot.return_value = MOCK_SNAPSHOT
        MockYF.return_value.get_financials.return_value = MOCK_FINANCIALS
        MockYF.return_value.get_dividends.return_value = MOCK_DIVIDENDS
        MockYF.return_value.get_institutional_holders.return_value = []
        MockYF.return_value.get_earnings_dates.return_value = []
        MockYF.return_value.get_options_chain.return_value = []
        MockYF.return_value.get_short_interest_from_raw.return_value = None

    @patch("apps.companies.services.YFinanceClient")
    def test_returns_full_summary(self, MockYF):
        self._mock_yf(MockYF)
        result = sync_all_for_symbol("AAPL")
        assert result["profile"] is True
        assert result["prices"] == 2
        assert result["snapshot"] is True
        assert result["financials"] == 2
        assert result["dividends"] == 2

    @patch("apps.companies.services.YFinanceClient")
    def test_profile_false_when_no_data(self, MockYF):
        self._mock_yf(MockYF, profile=None)
        MockYF.return_value.get_price_history.return_value = []
        MockYF.return_value.get_snapshot.return_value = None
        MockYF.return_value.get_financials.return_value = []
        MockYF.return_value.get_dividends.return_value = []
        result = sync_all_for_symbol("ZZZZZ")
        assert result["profile"] is False

    @patch("apps.companies.services.YFinanceClient")
    def test_records_sync_for_the_gated_types(self, MockYF):
        self._mock_yf(MockYF)
        sync_all_for_symbol("AAPL")
        recorded = set(
            CompanySyncRecord.objects.filter(company__symbol="AAPL").values_list(
                "sync_type", flat=True
            )
        )
        # the three the AI-summary freshness gate reads
        assert {"snapshot", "price", "financials"} <= recorded

    @patch("apps.companies.services.YFinanceClient")
    def test_records_nothing_for_unknown_symbol(self, MockYF):
        self._mock_yf(MockYF, profile=None)
        MockYF.return_value.get_price_history.return_value = []
        MockYF.return_value.get_snapshot.return_value = None
        MockYF.return_value.get_financials.return_value = []
        MockYF.return_value.get_dividends.return_value = []
        sync_all_for_symbol("ZZZZZ")
        assert CompanySyncRecord.objects.count() == 0


# ---------------------------------------------------------------------------
# discover_and_create_stubs
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDiscoverAndCreateStubs:
    @patch("apps.companies.services.YFinanceClient")
    def test_creates_stubs_for_new_symbols(self, MockYF):
        MockYF.return_value.discover_tickers.return_value = ["AAPL", "MSFT", "TSLA"]
        count = discover_and_create_stubs()
        assert count == 3
        assert Company.objects.count() == 3

    @patch("apps.companies.services.YFinanceClient")
    def test_skips_existing_symbols(self, MockYF):
        Company.objects.create(symbol="AAPL")
        MockYF.return_value.discover_tickers.return_value = ["AAPL", "MSFT"]
        count = discover_and_create_stubs()
        assert count == 1
        assert Company.objects.filter(symbol="AAPL").count() == 1

    @patch("apps.companies.services.YFinanceClient")
    def test_new_stubs_are_not_bootstrapped(self, MockYF):
        MockYF.return_value.discover_tickers.return_value = ["AAPL"]
        discover_and_create_stubs()
        assert Company.objects.get(symbol="AAPL").is_bootstrapped is False

    @patch("apps.companies.services.YFinanceClient")
    def test_returns_zero_when_all_known(self, MockYF):
        Company.objects.create(symbol="AAPL")
        MockYF.return_value.discover_tickers.return_value = ["AAPL"]
        assert discover_and_create_stubs() == 0

    @patch("apps.companies.services.YFinanceClient")
    def test_deduplicates_discovered_list(self, MockYF):
        MockYF.return_value.discover_tickers.return_value = ["AAPL", "AAPL", "MSFT"]
        count = discover_and_create_stubs()
        assert count == 2


# ---------------------------------------------------------------------------
# bootstrap_next_batch
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBootstrapNextBatch:
    @patch("apps.companies.services.sync_all_for_symbol")
    def test_ingests_unbootstrapped_symbols(self, mock_sync):
        mock_sync.return_value = {
            "profile": True,
            "prices": 10,
            "snapshot": True,
            "financials": 5,
            "dividends": 2,
        }
        Company.objects.create(symbol="AAPL", is_bootstrapped=False)
        Company.objects.create(symbol="MSFT", is_bootstrapped=False)
        result = bootstrap_next_batch(batch_size=5)
        assert result["ok"] == 2
        assert result["failed"] == 0
        assert Company.objects.filter(is_bootstrapped=True).count() == 2

    @patch("apps.companies.services.sync_all_for_symbol")
    def test_skips_already_bootstrapped(self, mock_sync):
        Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        result = bootstrap_next_batch(batch_size=5)
        mock_sync.assert_not_called()
        assert result["attempted"] == 0

    @patch("apps.companies.services.sync_all_for_symbol")
    def test_failed_symbol_stays_unbootstrapped(self, mock_sync):
        mock_sync.side_effect = Exception("network error")
        Company.objects.create(symbol="BAD", is_bootstrapped=False)
        result = bootstrap_next_batch(batch_size=5)
        assert result["failed"] == 1
        assert Company.objects.get(symbol="BAD").is_bootstrapped is False

    @patch("apps.companies.services.sync_all_for_symbol")
    def test_one_failure_does_not_abort_others(self, mock_sync):
        mock_sync.side_effect = [
            Exception("boom"),
            {"profile": True, "prices": 0, "snapshot": False, "financials": 0, "dividends": 0},
        ]
        Company.objects.create(symbol="BAD", is_bootstrapped=False)
        Company.objects.create(symbol="GOOD", is_bootstrapped=False)
        result = bootstrap_next_batch(batch_size=5)
        assert result["ok"] == 1
        assert result["failed"] == 1
        assert Company.objects.get(symbol="GOOD").is_bootstrapped is True

    @patch("apps.companies.services.sync_all_for_symbol")
    def test_respects_batch_size(self, mock_sync):
        mock_sync.return_value = {
            "profile": True,
            "prices": 0,
            "snapshot": False,
            "financials": 0,
            "dividends": 0,
        }
        for i in range(10):
            Company.objects.create(symbol=f"SYM{i}", is_bootstrapped=False)
        result = bootstrap_next_batch(batch_size=3)
        assert result["attempted"] == 3
        assert mock_sync.call_count == 3


# ---------------------------------------------------------------------------
# import_from_yfinance
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestImportFromYFinance:
    @patch("apps.companies.services.YFinanceClient")
    def test_creates_new_companies(self, MockYF):
        MockYF.return_value.get_bulk_profiles.return_value = {
            "AAPL": MOCK_PROFILE,
            "MSFT": {**MOCK_PROFILE, "name": "Microsoft"},
        }
        assert import_from_yfinance(["AAPL", "MSFT"]) == 2
        assert Company.objects.count() == 2

    @patch("apps.companies.services.YFinanceClient")
    def test_updates_existing_counts_only_new(self, MockYF):
        Company.objects.create(symbol="AAPL", name="Old Name")
        MockYF.return_value.get_bulk_profiles.return_value = {
            "AAPL": MOCK_PROFILE,
            "MSFT": {**MOCK_PROFILE, "name": "Microsoft"},
        }
        assert import_from_yfinance(["AAPL", "MSFT"]) == 1
        assert Company.objects.get(symbol="AAPL").name == "Apple Inc."

    @patch("apps.companies.services.YFinanceClient")
    def test_returns_zero_when_no_new(self, MockYF):
        Company.objects.create(symbol="AAPL")
        MockYF.return_value.get_bulk_profiles.return_value = {"AAPL": MOCK_PROFILE}
        assert import_from_yfinance(["AAPL"]) == 0


# ---------------------------------------------------------------------------
# Private helpers: _get_or_create_sector / _get_or_create_industry
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGetOrCreateSector:
    def test_returns_none_for_empty_name(self):
        from apps.companies.services import _get_or_create_sector

        assert _get_or_create_sector("") is None
        assert Sector.objects.count() == 0

    def test_creates_sector_for_new_name(self):
        from apps.companies.services import _get_or_create_sector

        sector = _get_or_create_sector("Technology")
        assert sector is not None
        assert sector.name == "Technology"

    def test_reuses_existing_sector(self):
        from apps.companies.services import _get_or_create_sector

        Sector.objects.create(name="Technology")
        _get_or_create_sector("Technology")
        assert Sector.objects.filter(name="Technology").count() == 1


@pytest.mark.django_db
class TestGetOrCreateIndustry:
    def test_returns_none_for_empty_name(self):
        from apps.companies.services import _get_or_create_industry

        assert _get_or_create_industry("", None) is None
        assert Industry.objects.count() == 0

    def test_creates_industry_and_links_sector(self):
        from apps.companies.services import _get_or_create_industry

        sector = Sector.objects.create(name="Technology")
        ind = _get_or_create_industry("Software", sector)
        assert ind is not None
        assert ind.sector == sector

    def test_sets_sector_on_existing_industry_with_no_sector(self):
        from apps.companies.services import _get_or_create_industry

        sector = Sector.objects.create(name="Technology")
        Industry.objects.create(name="Software")
        ind = _get_or_create_industry("Software", sector)
        assert ind.sector == sector

    def test_does_not_overwrite_existing_sector(self):
        from apps.companies.services import _get_or_create_industry

        original = Sector.objects.create(name="Technology")
        other = Sector.objects.create(name="Finance")
        Industry.objects.create(name="Software", sector=original)
        ind = _get_or_create_industry("Software", other)
        assert ind.sector == original


# ---------------------------------------------------------------------------
# sync_financials / sync_dividends empty-data paths
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSyncFinancialsEmptyData:
    @patch("apps.companies.services.YFinanceClient")
    def test_returns_zero_when_client_returns_empty(self, MockYF):
        Company.objects.create(symbol="AAPL")
        MockYF.return_value.get_financials.return_value = []
        assert sync_financials("AAPL") == 0

    @patch("apps.companies.services.YFinanceClient")
    def test_returns_zero_for_unknown_symbol(self, MockYF):
        MockYF.return_value.get_financials.return_value = MOCK_FINANCIALS
        assert sync_financials("ZZZZZ") == 0


@pytest.mark.django_db
class TestSyncDividendsEmptyData:
    @patch("apps.companies.services.YFinanceClient")
    def test_returns_zero_when_client_returns_empty(self, MockYF):
        Company.objects.create(symbol="AAPL")
        MockYF.return_value.get_dividends.return_value = []
        assert sync_dividends("AAPL") == 0

    @patch("apps.companies.services.YFinanceClient")
    def test_returns_zero_for_unknown_symbol(self, MockYF):
        MockYF.return_value.get_dividends.return_value = MOCK_DIVIDENDS
        assert sync_dividends("ZZZZZ") == 0


# ---------------------------------------------------------------------------
# get_market_hierarchy
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGetMarketHierarchy:
    from apps.companies.services import get_market_hierarchy

    def test_empty_when_no_companies(self):
        from apps.companies.services import get_market_hierarchy

        Sector.objects.create(name="Technology")
        assert get_market_hierarchy() == []

    def test_includes_sector_with_companies(self):
        from apps.companies.services import get_market_hierarchy

        sector = Sector.objects.create(name="Technology")
        Company.objects.create(symbol="AAPL", sector=sector)
        result = get_market_hierarchy()
        assert len(result) == 1
        assert result[0]["name"] == "Technology"
        assert result[0]["company_count"] == 1

    def test_industry_without_sector_is_skipped(self):
        from apps.companies.services import get_market_hierarchy

        sector = Sector.objects.create(name="Technology")
        orphan = Industry.objects.create(name="Orphan", sector=None)
        Company.objects.create(symbol="AAPL", sector=sector, industry=orphan)
        result = get_market_hierarchy()
        children = result[0].get("children", [])
        assert not any(c["name"] == "Orphan" for c in children)

    def test_uncategorised_companies_become_other_bucket(self):
        from apps.companies.services import get_market_hierarchy

        sector = Sector.objects.create(name="Technology")
        Company.objects.create(symbol="AAPL", sector=sector, industry=None)
        result = get_market_hierarchy()
        children = result[0]["children"]
        assert any(c["name"] == "Other" for c in children)

    def test_children_ordered_by_company_count_desc(self):
        from apps.companies.services import get_market_hierarchy

        sector = Sector.objects.create(name="Technology")
        ind1 = Industry.objects.create(name="Software", sector=sector)
        ind2 = Industry.objects.create(name="Hardware", sector=sector)
        Company.objects.create(symbol="AAPL", sector=sector, industry=ind1)
        Company.objects.create(symbol="MSFT", sector=sector, industry=ind1)
        Company.objects.create(symbol="INTL", sector=sector, industry=ind2)
        result = get_market_hierarchy()
        counts = [c["company_count"] for c in result[0]["children"]]
        assert counts == sorted(counts, reverse=True)

    def test_sectors_ordered_by_company_count_desc(self):
        from apps.companies.services import get_market_hierarchy

        s1 = Sector.objects.create(name="Technology")
        s2 = Sector.objects.create(name="Finance")
        Company.objects.create(symbol="AAPL", sector=s1)
        Company.objects.create(symbol="MSFT", sector=s1)
        Company.objects.create(symbol="JPM", sector=s2)
        result = get_market_hierarchy()
        counts = [r["company_count"] for r in result]
        assert counts == sorted(counts, reverse=True)


@pytest.mark.django_db
class TestGetMarketHierarchyMarketCap:
    from apps.companies.services import get_market_hierarchy

    def _snapshot(self, company, market_cap, fetched_at):
        return CompanySnapshot.objects.create(
            company=company,
            market_cap=market_cap,
            fetched_at=fetched_at,
            raw={},
        )

    def test_market_cap_value_uses_latest_snapshot(self):
        from apps.companies.services import get_market_hierarchy

        sector = Sector.objects.create(name="Technology")
        company = Company.objects.create(symbol="AAPL", sector=sector)
        self._snapshot(company, 1_000_000, "2024-01-01T00:00:00+00:00")
        self._snapshot(company, 2_000_000, "2024-06-01T00:00:00+00:00")

        result = get_market_hierarchy(metric="market_cap")
        assert len(result) == 1
        assert result[0]["market_cap"] == pytest.approx(2_000_000)
        assert result[0]["value"] == pytest.approx(2_000_000)

    def test_old_snapshots_not_double_counted(self):
        from apps.companies.services import get_market_hierarchy

        sector = Sector.objects.create(name="Technology")
        company = Company.objects.create(symbol="AAPL", sector=sector)
        # Three historical snapshots — only latest (3M) should count.
        self._snapshot(company, 1_000_000, "2024-01-01T00:00:00+00:00")
        self._snapshot(company, 2_000_000, "2024-03-01T00:00:00+00:00")
        self._snapshot(company, 3_000_000, "2024-06-01T00:00:00+00:00")

        result = get_market_hierarchy(metric="market_cap")
        assert result[0]["market_cap"] == pytest.approx(3_000_000)

    def test_industry_market_cap_aggregated(self):
        from apps.companies.services import get_market_hierarchy

        sector = Sector.objects.create(name="Technology")
        ind = Industry.objects.create(name="Software", sector=sector)
        c1 = Company.objects.create(symbol="AAPL", sector=sector, industry=ind)
        c2 = Company.objects.create(symbol="MSFT", sector=sector, industry=ind)
        self._snapshot(c1, 1_000_000, "2024-06-01T00:00:00+00:00")
        self._snapshot(c2, 500_000, "2024-06-01T00:00:00+00:00")

        result = get_market_hierarchy(metric="market_cap")
        child = result[0]["children"][0]
        assert child["name"] == "Software"
        assert child["market_cap"] == pytest.approx(1_500_000)

    def test_sectors_ordered_by_market_cap_desc(self):
        from apps.companies.services import get_market_hierarchy

        s1 = Sector.objects.create(name="Technology")
        s2 = Sector.objects.create(name="Finance")
        c1 = Company.objects.create(symbol="AAPL", sector=s1)
        c2 = Company.objects.create(symbol="JPM", sector=s2)
        self._snapshot(c1, 500_000, "2024-06-01T00:00:00+00:00")
        self._snapshot(c2, 2_000_000, "2024-06-01T00:00:00+00:00")

        result = get_market_hierarchy(metric="market_cap")
        assert result[0]["name"] == "Finance"
        assert result[1]["name"] == "Technology"

    def test_count_mode_unchanged(self):
        from apps.companies.services import get_market_hierarchy

        sector = Sector.objects.create(name="Technology")
        company = Company.objects.create(symbol="AAPL", sector=sector)
        self._snapshot(company, 9_999_999, "2024-06-01T00:00:00+00:00")

        result = get_market_hierarchy(metric="count")
        assert result[0]["value"] == 1
        assert result[0]["company_count"] == 1


# ---------------------------------------------------------------------------
# get_financials_pivoted
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGetFinancialsPivoted:
    def setup_method(self):
        self.company = Company.objects.create(symbol="AAPL")

    def _fs(self, metric, period_end, value, statement_type="income", period="annual"):
        FinancialStatement.objects.create(
            company=self.company,
            statement_type=statement_type,
            period=period,
            period_end=period_end,
            metric=metric,
            value=value,
        )

    def test_returns_dates_and_rows_keys(self):
        from apps.companies.services import get_financials_pivoted

        self._fs("Revenue", date(2023, 12, 31), 100.0)
        result = get_financials_pivoted(self.company.pk)
        assert "dates" in result
        assert "rows" in result

    def test_dates_are_newest_first(self):
        from apps.companies.services import get_financials_pivoted

        self._fs("Revenue", date(2021, 12, 31), 80.0)
        self._fs("Costs", date(2023, 12, 31), 100.0)
        result = get_financials_pivoted(self.company.pk)
        assert result["dates"] == sorted(result["dates"], reverse=True)

    def test_limited_to_four_dates_by_default(self):
        from apps.companies.services import get_financials_pivoted

        for yr in [2020, 2021, 2022, 2023, 2024]:
            self._fs("Revenue", date(yr, 12, 31), float(yr))
        result = get_financials_pivoted(self.company.pk)
        assert len(result["dates"]) == 4

    def test_filter_by_statement_type(self):
        from apps.companies.services import get_financials_pivoted

        self._fs("Revenue", date(2023, 12, 31), 100.0, statement_type="income")
        self._fs("Assets", date(2023, 12, 31), 200.0, statement_type="balance")
        result = get_financials_pivoted(self.company.pk, statement_type="income")
        metrics = [r["metric"] for r in result["rows"]]
        assert "Revenue" in metrics
        assert "Assets" not in metrics

    def test_filter_by_period(self):
        from apps.companies.services import get_financials_pivoted

        self._fs("Revenue", date(2023, 12, 31), 100.0, period="annual")
        self._fs("Revenue", date(2023, 9, 30), 25.0, period="quarterly")
        result = get_financials_pivoted(self.company.pk, period="quarterly")
        assert len(result["dates"]) == 1
        assert result["dates"][0] == "2023-09-30"

    def test_values_aligned_to_dates(self):
        from apps.companies.services import get_financials_pivoted

        self._fs("Revenue", date(2023, 12, 31), 100.0)
        self._fs("Revenue", date(2022, 12, 31), 90.0)
        result = get_financials_pivoted(self.company.pk)
        row = result["rows"][0]
        assert len(row["values"]) == len(result["dates"])

    def test_empty_when_no_statements(self):
        from apps.companies.services import get_financials_pivoted

        result = get_financials_pivoted(self.company.pk)
        assert result["dates"] == []
        assert result["rows"] == []


# ---------------------------------------------------------------------------
# sync_snapshot - new fields
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSyncSnapshotNewFields:
    @patch("apps.companies.services.YFinanceClient")
    def test_stores_new_valuation_fields(self, MockYF):
        Company.objects.create(symbol="AAPL")
        MockYF.return_value.get_snapshot.return_value = MOCK_SNAPSHOT
        snap = sync_snapshot("AAPL")
        assert snap is not None
        assert snap.beta == 1.24
        assert snap.gross_margins == 0.44
        assert snap.recommendation_key == "buy"
        assert snap.audit_risk == 4
        assert snap.enterprise_value == 2_900_000_000_000

    @patch("apps.companies.services.YFinanceClient")
    def test_stores_date_fields(self, MockYF):
        Company.objects.create(symbol="AAPL")
        MockYF.return_value.get_snapshot.return_value = MOCK_SNAPSHOT
        snap = sync_snapshot("AAPL")
        assert snap.ex_dividend_date == date(2024, 2, 9)
        assert snap.last_fiscal_year_end == date(2023, 9, 30)
        assert snap.last_split_date == date(2020, 8, 31)


# ---------------------------------------------------------------------------
# backfill_snapshot_fields
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBackfillSnapshotFields:
    def setup_method(self):
        self.company = Company.objects.create(symbol="AAPL")

    def test_backfills_from_raw(self):
        snap = CompanySnapshot.objects.create(
            company=self.company,
            raw={
                "symbol": "AAPL",
                "beta": 1.24,
                "pegRatio": 2.1,
                "grossMargins": 0.44,
                "recommendationKey": "buy",
                "auditRisk": 4,
            },
        )
        count = backfill_snapshot_fields()
        assert count == 1
        snap.refresh_from_db()
        assert snap.beta == 1.24
        assert snap.peg_ratio == 2.1
        assert snap.gross_margins == 0.44
        assert snap.recommendation_key == "buy"
        assert snap.audit_risk == 4

    def test_skips_already_filled(self):
        CompanySnapshot.objects.create(
            company=self.company,
            beta=1.5,
            raw={"symbol": "AAPL", "beta": 1.5},
        )
        count = backfill_snapshot_fields()
        assert count == 0  # beta is set so not a candidate

    def test_returns_zero_when_no_snapshots(self):
        assert backfill_snapshot_fields() == 0


# ---------------------------------------------------------------------------
# sync_short_interest
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSyncShortInterest:
    @patch("apps.companies.services.YFinanceClient")
    def test_creates_row(self, MockYF):
        Company.objects.create(symbol="AAPL")
        MockYF.return_value.get_short_interest.return_value = {
            "date_short_interest": date(2024, 3, 15),
            "shares_short": 120_000_000,
            "shares_short_prior_month": 110_000_000,
            "short_ratio": 2.1,
            "short_pct_of_float": 0.008,
            "shares_pct_shares_out": 0.0077,
        }
        si = sync_short_interest("AAPL")
        assert si is not None
        assert si.shares_short == 120_000_000
        assert ShortInterest.objects.count() == 1

    @patch("apps.companies.services.YFinanceClient")
    def test_dedup_skips_same_date(self, MockYF):
        Company.objects.create(symbol="AAPL")
        data = {
            "date_short_interest": date(2024, 3, 15),
            "shares_short": 120_000_000,
            "shares_short_prior_month": None,
            "short_ratio": None,
            "short_pct_of_float": None,
            "shares_pct_shares_out": None,
        }
        MockYF.return_value.get_short_interest.return_value = data
        sync_short_interest("AAPL")
        result = sync_short_interest("AAPL")
        assert result is None
        assert ShortInterest.objects.count() == 1

    @patch("apps.companies.services.YFinanceClient")
    def test_returns_none_for_unknown_symbol(self, MockYF):
        assert sync_short_interest("ZZZZZ") is None


# ---------------------------------------------------------------------------
# sync_institutional_holders
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSyncInstitutionalHolders:
    @patch("apps.companies.services.YFinanceClient")
    def test_creates_snapshot(self, MockYF):
        Company.objects.create(symbol="AAPL")
        MockYF.return_value.get_institutional_holders.return_value = [
            {
                "holder": "Vanguard",
                "shares": 1_000_000,
                "date_reported": "2024-03-31",
                "pct_out": 0.065,
                "value": 180_000_000,
            },
        ]
        snapshot = sync_institutional_holders("AAPL")
        assert snapshot is not None
        assert len(snapshot.holders) == 1
        assert InstitutionalHolderSnapshot.objects.count() == 1

    @patch("apps.companies.services.YFinanceClient")
    def test_empty_holders_still_creates_row(self, MockYF):
        Company.objects.create(symbol="AAPL")
        MockYF.return_value.get_institutional_holders.return_value = []
        snapshot = sync_institutional_holders("AAPL")
        assert snapshot is not None
        assert snapshot.holders == []


# ---------------------------------------------------------------------------
# sync_earnings_dates
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSyncEarningsDates:
    @patch("apps.companies.services.YFinanceClient")
    def test_creates_rows(self, MockYF):
        Company.objects.create(symbol="AAPL")
        MockYF.return_value.get_earnings_dates.return_value = [
            {
                "earnings_date": date(2024, 1, 25),
                "eps_estimate": 2.10,
                "reported_eps": 2.18,
                "surprise_pct": 3.8,
                "is_upcoming": False,
            }
        ]
        count = sync_earnings_dates("AAPL")
        assert count == 1
        assert EarningsDate.objects.count() == 1

    @patch("apps.companies.services.YFinanceClient")
    def test_upserts_existing_row(self, MockYF):
        company = Company.objects.create(symbol="AAPL")
        EarningsDate.objects.create(
            company=company,
            earnings_date=date(2024, 1, 25),
            eps_estimate=2.10,
        )
        MockYF.return_value.get_earnings_dates.return_value = [
            {
                "earnings_date": date(2024, 1, 25),
                "eps_estimate": 2.10,
                "reported_eps": 2.18,
                "surprise_pct": 3.8,
                "is_upcoming": False,
            }
        ]
        sync_earnings_dates("AAPL")
        row = EarningsDate.objects.get(company=company)
        assert row.reported_eps == 2.18
        assert EarningsDate.objects.count() == 1


# ---------------------------------------------------------------------------
# sync_options
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSyncOptions:
    @patch("apps.companies.services.YFinanceClient")
    def test_creates_expiry_and_contracts(self, MockYF):
        Company.objects.create(symbol="AAPL")
        MockYF.return_value.get_options_chain.return_value = [
            {
                "expiry_date": date(2024, 1, 19),
                "calls": [
                    {
                        "option_type": "call",
                        "contract_symbol": "AAPL240119C00150000",
                        "strike": "150.00",
                        "last_price": "5.20",
                        "bid": "5.10",
                        "ask": "5.30",
                        "volume": 1000,
                        "open_interest": 5000,
                        "implied_volatility": 0.25,
                        "in_the_money": True,
                    }
                ],
                "puts": [],
            }
        ]
        count = sync_options("AAPL")
        assert count == 1
        assert OptionsExpiry.objects.count() == 1
        assert OptionsContract.objects.count() == 1

    @patch("apps.companies.services.YFinanceClient")
    def test_returns_zero_when_no_chains(self, MockYF):
        Company.objects.create(symbol="AAPL")
        MockYF.return_value.get_options_chain.return_value = []
        assert sync_options("AAPL") == 0

    @patch("apps.companies.services.YFinanceClient")
    def test_returns_zero_for_unknown_symbol(self, MockYF):
        assert sync_options("ZZZZZ") == 0


# ---------------------------------------------------------------------------
# backfill_short_interest
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBackfillShortInterest:
    # backfill_short_interest uses .distinct("company") which is postgres-only.
    # Patch sync_short_interest_from_raw and the queryset to test the iteration logic.

    @patch("apps.companies.services.sync_short_interest_from_raw")
    def test_creates_row_from_raw(self, mock_sync):
        from apps.companies.services import backfill_short_interest

        company = Company.objects.create(symbol="AAPL")
        snap = CompanySnapshot.objects.create(
            company=company,
            raw={"symbol": "AAPL", "sharesShort": 120_000_000},
        )
        mock_sync.return_value = ShortInterest(company=company)
        with patch("apps.companies.services.CompanySnapshot.objects.select_related") as mock_qs:
            mock_qs.return_value.filter.return_value.order_by.return_value.distinct.return_value = [
                snap
            ]
            count = backfill_short_interest()
        assert count == 1
        mock_sync.assert_called_once_with(company, snap.raw)

    @patch("apps.companies.services.sync_short_interest_from_raw")
    def test_returns_zero_when_no_snapshots(self, mock_sync):
        from apps.companies.services import backfill_short_interest

        with patch("apps.companies.services.CompanySnapshot.objects.select_related") as mock_qs:
            mock_qs.return_value.filter.return_value.order_by.return_value.distinct.return_value = []
            count = backfill_short_interest()
        assert count == 0
        mock_sync.assert_not_called()

    @patch("apps.companies.services.sync_short_interest_from_raw")
    def test_skips_when_sync_returns_none(self, mock_sync):
        from apps.companies.services import backfill_short_interest

        company = Company.objects.create(symbol="AAPL")
        snap = CompanySnapshot.objects.create(company=company, raw={})
        mock_sync.return_value = None
        with patch("apps.companies.services.CompanySnapshot.objects.select_related") as mock_qs:
            mock_qs.return_value.filter.return_value.order_by.return_value.distinct.return_value = [
                snap
            ]
            count = backfill_short_interest()
        assert count == 0


# ---------------------------------------------------------------------------
# backfill_snapshot_fields — empty raw branch
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBackfillSnapshotFieldsEmptyRaw:
    def test_skips_snapshot_with_empty_raw(self):
        company = Company.objects.create(symbol="AAPL")
        CompanySnapshot.objects.create(company=company, beta=None, raw={})
        count = backfill_snapshot_fields()
        assert count == 0


# ---------------------------------------------------------------------------
# sync_short_interest_from_raw — success path
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSyncShortInterestFromRaw:
    def test_creates_row_from_raw(self):
        from apps.companies.services import sync_short_interest_from_raw

        company = Company.objects.create(symbol="AAPL")
        raw = {
            "dateShortInterest": 1710460800,
            "sharesShort": 120_000_000,
            "sharesShortPriorMonth": 110_000_000,
            "shortRatio": 2.1,
            "shortPercentOfFloat": 0.008,
            "sharesPercentSharesOut": 0.0077,
        }
        si = sync_short_interest_from_raw(company, raw)
        assert si is not None
        assert si.shares_short == 120_000_000
        assert ShortInterest.objects.count() == 1

    def test_returns_none_for_empty_raw(self):
        from apps.companies.services import sync_short_interest_from_raw

        company = Company.objects.create(symbol="AAPL")
        assert sync_short_interest_from_raw(company, {}) is None


# ---------------------------------------------------------------------------
# generate_company_summary
# ---------------------------------------------------------------------------

_MOCK_PAYLOAD = {
    "verdict": "buy",
    "confidence": 0.72,
    "summary": (
        "Agilent Technologies shows consistent revenue growth and healthy operating margins "
        "relative to its peer median, with manageable leverage."
    ),
    "key_drivers": ["operating margin 24.3% vs peer median 18.0%"],
    "key_risks": ["trailing P/E 30.0 vs peer median 20.0"],
}


def _mock_response(**overrides) -> str:
    payload = {**_MOCK_PAYLOAD, **overrides}
    return json.dumps(payload)


@pytest.mark.django_db
class TestGenerateCompanySummary:
    def setup_method(self):
        self.company = Company.objects.create(
            symbol="A", name="Agilent Technologies", is_bootstrapped=True
        )
        self._mark_fresh()

    def _mark_fresh(self):
        now = dt.now(UTC)
        for sync_type in ("snapshot", "price", "financials"):
            CompanySyncRecord.objects.update_or_create(
                company=self.company, sync_type=sync_type, defaults={"last_synced_at": now}
            )

    def test_creates_summary_row_with_buy_verdict(self):
        from apps.companies.services import generate_company_summary

        with patch("apps.companies.services.ollama_chat", return_value=_mock_response()):
            summary = generate_company_summary("A")

        assert summary.pk is not None
        assert summary.verdict == CompanySummary.Verdict.BUY
        assert summary.confidence == pytest.approx(0.72)
        assert summary.key_drivers == _MOCK_PAYLOAD["key_drivers"]
        assert summary.key_risks == _MOCK_PAYLOAD["key_risks"]
        assert "peer median" in summary.summary
        assert CompanySummary.objects.count() == 1

    @pytest.mark.parametrize(
        "verdict",
        ["buy", "hold", "sell", "insufficient_data"],
    )
    def test_each_verdict_round_trips(self, verdict):
        from apps.companies.services import generate_company_summary

        with patch(
            "apps.companies.services.ollama_chat", return_value=_mock_response(verdict=verdict)
        ):
            summary = generate_company_summary("A")

        assert summary.verdict == verdict

    def test_uses_structured_output_format(self):
        from apps.companies.services import _SUMMARY_FORMAT, generate_company_summary

        captured = {}

        def fake_chat(messages, **kwargs):
            captured.update(kwargs)
            return _mock_response()

        with patch("apps.companies.services.ollama_chat", side_effect=fake_chat):
            generate_company_summary("A")

        assert captured["format"] == _SUMMARY_FORMAT

    def test_malformed_json_defaults_to_insufficient_data(self):
        from apps.companies.services import generate_company_summary

        with patch(
            "apps.companies.services.ollama_chat", return_value="Analysis with no JSON at all."
        ):
            summary = generate_company_summary("A")

        assert summary.verdict == CompanySummary.Verdict.INSUFFICIENT_DATA
        assert summary.confidence is None
        assert summary.summary == "Analysis with no JSON at all."

    def test_missing_verdict_defaults_to_insufficient_data(self):
        from apps.companies.services import generate_company_summary

        with patch(
            "apps.companies.services.ollama_chat",
            return_value=json.dumps({"summary": "No verdict here."}),
        ):
            summary = generate_company_summary("A")

        assert summary.verdict == CompanySummary.Verdict.INSUFFICIENT_DATA
        assert summary.summary == "No verdict here."

    def test_out_of_choices_verdict_defaults_to_insufficient_data(self):
        from apps.companies.services import generate_company_summary

        with patch(
            "apps.companies.services.ollama_chat", return_value=_mock_response(verdict="STRONG BUY")
        ):
            summary = generate_company_summary("A")

        assert summary.verdict == CompanySummary.Verdict.INSUFFICIENT_DATA

    def test_fenced_json_is_parsed(self):
        from apps.companies.services import generate_company_summary

        fenced = "```json\n" + _mock_response(verdict="hold") + "\n```"
        with patch("apps.companies.services.ollama_chat", return_value=fenced):
            summary = generate_company_summary("A")

        assert summary.verdict == CompanySummary.Verdict.HOLD

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [(85, 1.0), (1.4, 1.0), (-0.5, 0.0), ("high", None), (None, None), (0.5, 0.5)],
    )
    def test_confidence_is_clamped_or_nulled(self, raw, expected):
        from apps.companies.services import generate_company_summary

        with patch(
            "apps.companies.services.ollama_chat", return_value=_mock_response(confidence=raw)
        ):
            summary = generate_company_summary("A")

        if expected is None:
            assert summary.confidence is None
        else:
            assert summary.confidence == pytest.approx(expected)

    def test_non_list_phrases_are_dropped(self):
        from apps.companies.services import generate_company_summary

        with patch(
            "apps.companies.services.ollama_chat",
            return_value=_mock_response(key_risks="just a string", key_drivers=None),
        ):
            summary = generate_company_summary("A")

        assert summary.key_risks == []
        assert summary.key_drivers == []

    def test_data_snapshot_stored(self):
        from apps.companies.services import generate_company_summary

        with patch("apps.companies.services.ollama_chat", return_value=_mock_response()):
            summary = generate_company_summary("A")

        assert summary.data_snapshot["symbol"] == "A"
        assert summary.data_snapshot["name"] == "Agilent Technologies"

    def test_no_snapshot_still_generates(self):
        """Company with no CompanySnapshot should still produce a summary row."""
        from apps.companies.services import generate_company_summary

        with patch("apps.companies.services.ollama_chat", return_value=_mock_response()):
            summary = generate_company_summary("A")

        assert summary.pk is not None

    def test_raises_for_unknown_symbol(self):
        from apps.companies.services import generate_company_summary

        with pytest.raises(Company.DoesNotExist):
            generate_company_summary("ZZZZZ")

    def test_includes_snapshot_data_in_prompt(self):
        from apps.companies.services import generate_company_summary

        CompanySnapshot.objects.create(
            company=self.company,
            market_cap=500_000_000_000,
            trailing_pe=25.5,
            raw={},
        )

        captured = {}

        def fake_chat(messages, **kwargs):
            captured["messages"] = messages
            return _mock_response()

        with patch("apps.companies.services.ollama_chat", side_effect=fake_chat):
            generate_company_summary("A")

        user_msg = captured["messages"][1]["content"]
        assert "500.00B" in user_msg
        assert "trailing P/E: 25.50" in user_msg

    def test_includes_annual_financials_when_available(self):
        from apps.companies.services import generate_company_summary

        FinancialStatement.objects.create(
            company=self.company,
            statement_type="income",
            period="annual",
            period_end=date(2024, 9, 30),
            metric="Total Revenue",
            value=6_840_000_000,
        )

        captured = {}

        def fake_chat(messages, **kwargs):
            captured["messages"] = messages
            return _mock_response()

        with patch("apps.companies.services.ollama_chat", side_effect=fake_chat):
            generate_company_summary("A")

        user_msg = captured["messages"][1]["content"]
        assert "Annual Financials" in user_msg


@pytest.mark.django_db
class TestSummaryFreshnessGate:
    def setup_method(self):
        self.company = Company.objects.create(symbol="A", name="Agilent", is_bootstrapped=True)

    def _sync(self, sync_type, days_ago):
        CompanySyncRecord.objects.update_or_create(
            company=self.company,
            sync_type=sync_type,
            defaults={"last_synced_at": dt.now(UTC) - timedelta(days=days_ago)},
        )

    def _all_fresh(self):
        for sync_type in ("snapshot", "price", "financials"):
            self._sync(sync_type, 0)

    def test_fresh_data_makes_exactly_one_llm_call(self):
        from apps.companies.services import generate_company_summary

        self._all_fresh()
        with patch("apps.companies.services.ollama_chat", return_value=_mock_response()) as chat:
            summary = generate_company_summary("A")

        assert chat.call_count == 1
        assert summary.verdict == CompanySummary.Verdict.BUY

    def test_stale_snapshot_skips_the_llm(self):
        from apps.companies.services import generate_company_summary

        self._all_fresh()
        self._sync("snapshot", 34)

        with patch("apps.companies.services.ollama_chat") as chat:
            summary = generate_company_summary("A")

        chat.assert_not_called()
        assert summary.verdict == CompanySummary.Verdict.INSUFFICIENT_DATA
        assert "snapshot last synced 34 days ago" in summary.summary
        assert summary.data_snapshot["stale_data"] == [
            "snapshot last synced 34 days ago (limit 7 days)"
        ]

    def test_stale_price_is_gated_on_its_own_window(self):
        from apps.companies.services import generate_company_summary

        self._all_fresh()
        self._sync("price", 5)

        with patch("apps.companies.services.ollama_chat") as chat:
            summary = generate_company_summary("A")

        chat.assert_not_called()
        assert summary.verdict == CompanySummary.Verdict.INSUFFICIENT_DATA

    def test_financials_window_is_wide(self):
        from apps.companies.services import generate_company_summary

        self._all_fresh()
        self._sync("financials", 90)

        with patch("apps.companies.services.ollama_chat", return_value=_mock_response()) as chat:
            generate_company_summary("A")

        assert chat.call_count == 1

    def test_missing_sync_records_count_as_stale(self):
        from apps.companies.services import generate_company_summary

        with patch("apps.companies.services.ollama_chat") as chat:
            summary = generate_company_summary("A")

        chat.assert_not_called()
        assert summary.verdict == CompanySummary.Verdict.INSUFFICIENT_DATA
        assert summary.data_snapshot["stale_data"] == [
            "snapshot has never been synced",
            "price has never been synced",
            "financials has never been synced",
        ]

    def test_windows_come_from_llm_settings(self, llm_settings):
        from apps.companies.services import generate_company_summary

        self._all_fresh()
        self._sync("snapshot", 20)
        llm_settings.summary_snapshot_max_age_days = 30

        with patch("apps.companies.services.ollama_chat", return_value=_mock_response()) as chat:
            generate_company_summary("A")

        assert chat.call_count == 1

    # -- data-derived fallback: fresh rows beat a missing/stale sync record --

    def _snapshot_row(self, days_ago=0):
        snap = CompanySnapshot.objects.create(company=self.company, trailing_pe=20.0, raw={})
        CompanySnapshot.objects.filter(pk=snap.pk).update(
            fetched_at=dt.now(UTC) - timedelta(days=days_ago)
        )
        return snap

    def _price_row(self, days_ago=0):
        bar = PriceBar.objects.create(
            company=self.company,
            date=date(2026, 1, 2),
            open=1,
            high=1,
            low=1,
            close=1,
            volume=1,
        )
        PriceBar.objects.filter(pk=bar.pk).update(created_at=dt.now(UTC) - timedelta(days=days_ago))
        return bar

    def _financials_row(self, days_ago=0):
        row = FinancialStatement.objects.create(
            company=self.company,
            statement_type="income",
            period="annual",
            period_end=date(2025, 12, 31),
            metric="Total Revenue",
            value=1.0,
        )
        FinancialStatement.objects.filter(pk=row.pk).update(
            updated_at=dt.now(UTC) - timedelta(days=days_ago)
        )
        return row

    def test_fresh_snapshot_row_beats_a_stale_sync_record(self):
        """The ABBV bug: data synced minutes ago, bookkeeping row months old."""
        from apps.companies.services import generate_company_summary

        self._all_fresh()
        self._sync("snapshot", 37)
        self._snapshot_row(days_ago=0)

        with patch("apps.companies.services.ollama_chat", return_value=_mock_response()) as chat:
            summary = generate_company_summary("A")

        assert chat.call_count == 1
        assert summary.verdict == CompanySummary.Verdict.BUY

    def test_fresh_rows_beat_missing_sync_records_entirely(self):
        from apps.companies.services import generate_company_summary

        self._snapshot_row()
        self._price_row()
        self._financials_row()
        assert CompanySyncRecord.objects.count() == 0

        with patch("apps.companies.services.ollama_chat", return_value=_mock_response()) as chat:
            generate_company_summary("A")

        assert chat.call_count == 1

    def test_fresh_sync_record_beats_stale_rows(self):
        """max() cuts both ways -- a recorded sync that wrote no new row is fresh."""
        from apps.companies.services import generate_company_summary

        self._all_fresh()
        self._snapshot_row(days_ago=37)
        self._price_row(days_ago=37)
        self._financials_row(days_ago=365)

        with patch("apps.companies.services.ollama_chat", return_value=_mock_response()) as chat:
            generate_company_summary("A")

        assert chat.call_count == 1

    def test_both_signals_stale_still_gates(self):
        from apps.companies.services import generate_company_summary

        self._all_fresh()
        self._sync("snapshot", 37)
        self._snapshot_row(days_ago=20)

        with patch("apps.companies.services.ollama_chat") as chat:
            summary = generate_company_summary("A")

        chat.assert_not_called()
        # reported age is the LATER of the two signals, not the older record
        assert summary.data_snapshot["stale_data"] == [
            "snapshot last synced 20 days ago (limit 7 days)"
        ]

    def test_price_freshness_uses_ingest_time_not_bar_date(self):
        """A backfilled bar dated years ago, written now, counts as a fresh price sync."""
        from apps.companies.services import generate_company_summary

        self._all_fresh()
        self._sync("price", 30)
        bar = PriceBar.objects.create(
            company=self.company,
            date=date(2019, 3, 1),
            open=1,
            high=1,
            low=1,
            close=1,
            volume=1,
        )
        assert (dt.now(UTC) - bar.created_at).days == 0

        with patch("apps.companies.services.ollama_chat", return_value=_mock_response()) as chat:
            generate_company_summary("A")

        assert chat.call_count == 1
