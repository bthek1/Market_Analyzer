from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pandas as pd

from apps.companies.yfinance_client import YFinanceClient, _normalize_profile


class TestNormalizeProfile:
    def test_returns_none_when_info_empty(self):
        assert _normalize_profile("AAPL", {}) is None

    def test_returns_none_when_no_symbol_key(self):
        assert _normalize_profile("AAPL", {"name": "Apple"}) is None

    def test_maps_known_exchange_codes(self):
        info = {"symbol": "AAPL", "exchange": "NMS"}
        result = _normalize_profile("AAPL", info)
        assert result["exchange"] == "NASDAQ"

    def test_pcx_maps_to_nyse_arca(self):
        info = {"symbol": "SPY", "exchange": "PCX"}
        result = _normalize_profile("SPY", info)
        assert result["exchange"] == "NYSE_ARCA"

    def test_unknown_exchange_returns_blank(self):
        info = {"symbol": "XYZ", "exchange": "UNKNOWN"}
        result = _normalize_profile("XYZ", info)
        assert result["exchange"] == ""

    def test_known_currency_preserved(self):
        info = {"symbol": "AAPL", "currency": "USD"}
        result = _normalize_profile("AAPL", info)
        assert result["currency"] == "USD"

    def test_unknown_currency_returns_blank(self):
        info = {"symbol": "XYZ", "currency": "XXX"}
        result = _normalize_profile("XYZ", info)
        assert result["currency"] == ""

    def test_extracts_sector_and_industry(self):
        info = {"symbol": "AAPL", "sector": "Technology", "industry": "Consumer Electronics"}
        result = _normalize_profile("AAPL", info)
        assert result["sector"] == "Technology"
        assert result["industry"] == "Consumer Electronics"

    def test_uses_symbol_as_name_fallback(self):
        info = {"symbol": "AAPL"}
        result = _normalize_profile("AAPL", info)
        assert result["name"] == "AAPL"

    def test_returns_all_profile_fields(self):
        info = {"symbol": "AAPL", "longName": "Apple Inc.", "marketCap": 3e12}
        result = _normalize_profile("AAPL", info)
        expected_keys = {
            "name",
            "exchange",
            "currency",
            "sector",
            "industry",
            "address",
            "city",
            "state",
            "zip_code",
            "country",
            "phone",
            "website",
            "ir_website",
            "description",
            "full_time_employees",
            "officers",
        }
        assert set(result.keys()) == expected_keys

    def test_extracts_address_fields(self):
        info = {
            "symbol": "AAPL",
            "address1": "One Apple Park Way",
            "city": "Cupertino",
            "state": "CA",
            "zip": "95014",
            "country": "United States",
            "phone": "408-996-1010",
            "website": "https://www.apple.com",
            "irWebsite": "https://investor.apple.com",
            "longBusinessSummary": "Apple designs computers.",
            "fullTimeEmployees": 150000,
        }
        result = _normalize_profile("AAPL", info)
        assert result["address"] == "One Apple Park Way"
        assert result["city"] == "Cupertino"
        assert result["state"] == "CA"
        assert result["zip_code"] == "95014"
        assert result["country"] == "United States"
        assert result["phone"] == "408-996-1010"
        assert result["website"] == "https://www.apple.com"
        assert result["ir_website"] == "https://investor.apple.com"
        assert result["description"] == "Apple designs computers."
        assert result["full_time_employees"] == 150000

    def test_extracts_officers(self):
        info = {
            "symbol": "AAPL",
            "companyOfficers": [
                {"name": "Tim Cook", "title": "CEO", "age": 63, "totalPay": 49000000},
            ],
        }
        result = _normalize_profile("AAPL", info)
        assert len(result["officers"]) == 1
        assert result["officers"][0]["name"] == "Tim Cook"
        assert result["officers"][0]["title"] == "CEO"
        assert result["officers"][0]["total_pay"] == 49000000

    def test_officers_empty_when_absent(self):
        info = {"symbol": "AAPL"}
        result = _normalize_profile("AAPL", info)
        assert result["officers"] == []

    def test_full_time_employees_none_when_invalid(self):
        info = {"symbol": "AAPL", "fullTimeEmployees": "N/A"}
        result = _normalize_profile("AAPL", info)
        assert result["full_time_employees"] is None


class TestGetProfile:
    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_returns_normalized_profile(self, MockTicker):
        MockTicker.return_value.info = {
            "symbol": "AAPL",
            "longName": "Apple Inc.",
            "exchange": "NMS",
            "currency": "USD",
            "sector": "Technology",
            "industry": "Consumer Electronics",
        }
        result = YFinanceClient().get_profile("AAPL")
        assert result is not None
        assert result["name"] == "Apple Inc."
        assert result["exchange"] == "NASDAQ"

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_returns_none_on_exception(self, MockTicker):
        MockTicker.side_effect = Exception("network error")
        assert YFinanceClient().get_profile("AAPL") is None

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_returns_none_for_empty_info(self, MockTicker):
        MockTicker.return_value.info = {}
        assert YFinanceClient().get_profile("AAPL") is None


class TestGetPriceHistory:
    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_returns_ohlcv_rows(self, MockTicker):
        df = pd.DataFrame(
            {
                "Open": [150.0, 153.0],
                "High": [155.0, 158.0],
                "Low": [149.0, 152.0],
                "Close": [153.0, 157.0],
                "Volume": [1000000, 900000],
            },
            index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
        )
        MockTicker.return_value.history.return_value = df
        rows = YFinanceClient().get_price_history("AAPL")
        assert len(rows) == 2
        assert rows[0]["date"] == date(2024, 1, 1)
        assert isinstance(rows[0]["close"], Decimal)
        assert rows[0]["volume"] == 1000000

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_skips_nan_close(self, MockTicker):
        df = pd.DataFrame(
            {
                "Open": [150.0],
                "High": [155.0],
                "Low": [149.0],
                "Close": [float("nan")],
                "Volume": [100000],
            },
            index=pd.to_datetime(["2024-01-01"]),
        )
        MockTicker.return_value.history.return_value = df
        assert YFinanceClient().get_price_history("AAPL") == []

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_returns_empty_on_exception(self, MockTicker):
        MockTicker.side_effect = Exception("error")
        assert YFinanceClient().get_price_history("AAPL") == []

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_returns_empty_when_df_empty(self, MockTicker):
        MockTicker.return_value.history.return_value = pd.DataFrame()
        assert YFinanceClient().get_price_history("AAPL") == []


class TestGetSnapshot:
    def _make_ticker(self, MockTicker, info: dict):
        mock = MagicMock()
        mock.info = info
        mock.recommendations = pd.DataFrame()
        MockTicker.return_value = mock

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_returns_snapshot_dict(self, MockTicker):
        self._make_ticker(
            MockTicker,
            {
                "symbol": "AAPL",
                "marketCap": 3_000_000_000_000,
                "trailingPE": 28.5,
                "forwardPE": 25.0,
            },
        )
        snap = YFinanceClient().get_snapshot("AAPL")
        assert snap is not None
        assert snap["market_cap"] == 3_000_000_000_000
        assert snap["trailing_pe"] == 28.5
        assert "raw" in snap

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_returns_none_for_empty_info(self, MockTicker):
        self._make_ticker(MockTicker, {})
        assert YFinanceClient().get_snapshot("AAPL") is None

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_nullable_fields_none_when_missing(self, MockTicker):
        self._make_ticker(MockTicker, {"symbol": "AAPL"})
        snap = YFinanceClient().get_snapshot("AAPL")
        assert snap["trailing_pe"] is None
        assert snap["market_cap"] is None

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_returns_none_on_exception(self, MockTicker):
        MockTicker.side_effect = Exception("error")
        assert YFinanceClient().get_snapshot("AAPL") is None

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_epoch_dates_converted(self, MockTicker):
        self._make_ticker(
            MockTicker,
            {
                "symbol": "AAPL",
                "exDividendDate": 1704067200,  # 2024-01-01 UTC
            },
        )
        snap = YFinanceClient().get_snapshot("AAPL")
        assert snap["ex_dividend_date"] == date(2024, 1, 1)

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_epoch_date_none_when_missing(self, MockTicker):
        self._make_ticker(MockTicker, {"symbol": "AAPL"})
        snap = YFinanceClient().get_snapshot("AAPL")
        assert snap["ex_dividend_date"] is None

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_recommendations_breakdown_parsed(self, MockTicker):
        mock = MagicMock()
        mock.info = {"symbol": "AAPL"}
        mock.recommendations = pd.DataFrame(
            {"strongBuy": [5], "buy": [10], "hold": [3], "sell": [1], "strongSell": [0]},
            index=["0m"],
        )
        MockTicker.return_value = mock
        snap = YFinanceClient().get_snapshot("AAPL")
        assert len(snap["recommendations_breakdown"]) == 1
        assert snap["recommendations_breakdown"][0]["strong_buy"] == 5

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_new_valuation_fields_populated(self, MockTicker):
        self._make_ticker(
            MockTicker,
            {
                "symbol": "AAPL",
                "beta": 1.24,
                "pegRatio": 2.1,
                "enterpriseValue": 2_900_000_000_000,
                "grossMargins": 0.44,
                "currentRatio": 1.07,
                "recommendationMean": 1.8,
                "recommendationKey": "buy",
            },
        )
        snap = YFinanceClient().get_snapshot("AAPL")
        assert snap["beta"] == 1.24
        assert snap["peg_ratio"] == 2.1
        assert snap["enterprise_value"] == 2_900_000_000_000
        assert snap["gross_margins"] == 0.44
        assert snap["current_ratio"] == 1.07
        assert snap["recommendation_mean"] == 1.8
        assert snap["recommendation_key"] == "buy"


class TestGetFinancials:
    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_returns_melted_rows(self, MockTicker):
        col = pd.Timestamp("2023-12-31")
        df = pd.DataFrame({"Revenue": [383285000000.0]}, index=[col]).T
        mock_ticker = MagicMock()
        mock_ticker.income_stmt = df
        mock_ticker.quarterly_income_stmt = pd.DataFrame()
        mock_ticker.balance_sheet = pd.DataFrame()
        mock_ticker.quarterly_balance_sheet = pd.DataFrame()
        mock_ticker.cashflow = pd.DataFrame()
        mock_ticker.quarterly_cashflow = pd.DataFrame()
        MockTicker.return_value = mock_ticker

        rows = YFinanceClient().get_financials("AAPL")
        assert len(rows) == 1
        assert rows[0]["statement_type"] == "income"
        assert rows[0]["period"] == "annual"
        assert rows[0]["metric"] == "Revenue"
        assert rows[0]["value"] == 383285000000.0

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_returns_empty_when_all_dfs_empty(self, MockTicker):
        mock_ticker = MagicMock()
        for attr in [
            "income_stmt",
            "quarterly_income_stmt",
            "balance_sheet",
            "quarterly_balance_sheet",
            "cashflow",
            "quarterly_cashflow",
        ]:
            setattr(mock_ticker, attr, pd.DataFrame())
        MockTicker.return_value = mock_ticker
        assert YFinanceClient().get_financials("AAPL") == []


class TestGetDividends:
    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_returns_dividend_rows(self, MockTicker):
        series = pd.Series(
            [0.24, 0.25],
            index=pd.to_datetime(["2024-03-01", "2024-06-01"]),
        )
        MockTicker.return_value.dividends = series
        rows = YFinanceClient().get_dividends("AAPL")
        assert len(rows) == 2
        assert rows[0]["date"] == date(2024, 3, 1)
        assert isinstance(rows[0]["amount"], Decimal)

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_returns_empty_when_no_dividends(self, MockTicker):
        MockTicker.return_value.dividends = pd.Series([], dtype=float)
        assert YFinanceClient().get_dividends("AAPL") == []

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_returns_empty_on_exception(self, MockTicker):
        MockTicker.side_effect = Exception("error")
        assert YFinanceClient().get_dividends("AAPL") == []


class TestEpochToDate:
    def test_valid_timestamp(self):
        from apps.companies.yfinance_client import _epoch_to_date

        result = _epoch_to_date(1704067200)
        assert result == date(2024, 1, 1)

    def test_none_returns_none(self):
        from apps.companies.yfinance_client import _epoch_to_date

        assert _epoch_to_date(None) is None

    def test_invalid_value_returns_none(self):
        from apps.companies.yfinance_client import _epoch_to_date

        assert _epoch_to_date("not-a-timestamp") is None


class TestGetInstitutionalHolders:
    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_returns_parsed_holders(self, MockTicker):
        df = pd.DataFrame(
            {
                "Holder": ["Vanguard"],
                "Shares": [1_000_000],
                "Date Reported": pd.to_datetime(["2024-03-31"]),
                "% Out": [0.065],
                "Value": [180_000_000],
            }
        )
        MockTicker.return_value.institutional_holders = df
        rows = YFinanceClient().get_institutional_holders("AAPL")
        assert len(rows) == 1
        assert rows[0]["holder"] == "Vanguard"
        assert rows[0]["shares"] == 1_000_000
        assert rows[0]["pct_out"] == 0.065

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_returns_empty_when_df_empty(self, MockTicker):
        MockTicker.return_value.institutional_holders = pd.DataFrame()
        assert YFinanceClient().get_institutional_holders("AAPL") == []

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_returns_empty_on_exception(self, MockTicker):
        MockTicker.side_effect = Exception("error")
        assert YFinanceClient().get_institutional_holders("AAPL") == []


class TestGetEarningsDates:
    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_returns_parsed_dates(self, MockTicker):
        df = pd.DataFrame(
            {
                "EPS Estimate": [1.50],
                "Reported EPS": [1.62],
                "Surprise(%)": [8.0],
            },
            index=pd.to_datetime(["2023-10-26"]),
        )
        MockTicker.return_value.earnings_dates = df
        rows = YFinanceClient().get_earnings_dates("AAPL")
        assert len(rows) == 1
        assert rows[0]["earnings_date"] == date(2023, 10, 26)
        assert rows[0]["eps_estimate"] == 1.50
        assert rows[0]["reported_eps"] == 1.62
        assert rows[0]["surprise_pct"] == 8.0

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_handles_nan_values(self, MockTicker):
        df = pd.DataFrame(
            {
                "EPS Estimate": [float("nan")],
                "Reported EPS": [float("nan")],
                "Surprise(%)": [float("nan")],
            },
            index=pd.to_datetime(["2025-01-30"]),
        )
        MockTicker.return_value.earnings_dates = df
        rows = YFinanceClient().get_earnings_dates("AAPL")
        assert len(rows) == 1
        assert rows[0]["eps_estimate"] is None
        assert rows[0]["reported_eps"] is None

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_returns_empty_when_df_empty(self, MockTicker):
        MockTicker.return_value.earnings_dates = pd.DataFrame()
        assert YFinanceClient().get_earnings_dates("AAPL") == []

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_is_upcoming_set_correctly(self, MockTicker):
        future = pd.Timestamp("2099-01-01")
        past = pd.Timestamp("2020-01-01")
        df = pd.DataFrame(
            {
                "EPS Estimate": [1.0, 1.0],
                "Reported EPS": [None, 1.1],
                "Surprise(%)": [None, 10.0],
            },
            index=[future, past],
        )
        MockTicker.return_value.earnings_dates = df
        rows = YFinanceClient().get_earnings_dates("AAPL")
        upcoming = [r for r in rows if r["earnings_date"] == date(2099, 1, 1)]
        historical = [r for r in rows if r["earnings_date"] == date(2020, 1, 1)]
        assert upcoming[0]["is_upcoming"] is True
        assert historical[0]["is_upcoming"] is False


class TestGetOptionsChain:
    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_parses_calls_and_puts(self, MockTicker):
        calls_df = pd.DataFrame(
            {
                "contractSymbol": ["AAPL240101C00150000"],
                "strike": [150.0],
                "lastPrice": [5.20],
                "bid": [5.10],
                "ask": [5.30],
                "volume": [1000],
                "openInterest": [5000],
                "impliedVolatility": [0.25],
                "inTheMoney": [True],
            }
        )
        puts_df = pd.DataFrame(
            {
                "contractSymbol": ["AAPL240101P00150000"],
                "strike": [150.0],
                "lastPrice": [4.80],
                "bid": [4.70],
                "ask": [4.90],
                "volume": [800],
                "openInterest": [4000],
                "impliedVolatility": [0.27],
                "inTheMoney": [False],
            }
        )
        chain = MagicMock()
        chain.calls = calls_df
        chain.puts = puts_df
        mock_ticker = MagicMock()
        mock_ticker.options = ("2024-01-01",)
        mock_ticker.option_chain.return_value = chain
        MockTicker.return_value = mock_ticker

        results = YFinanceClient().get_options_chain("AAPL", max_expiries=1)
        assert len(results) == 1
        assert results[0]["expiry_date"] == date(2024, 1, 1)
        assert len(results[0]["calls"]) == 1
        assert results[0]["calls"][0]["option_type"] == "call"
        assert len(results[0]["puts"]) == 1
        assert results[0]["puts"][0]["option_type"] == "put"

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_returns_empty_when_no_options(self, MockTicker):
        MockTicker.return_value.options = ()
        assert YFinanceClient().get_options_chain("AAPL") == []

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_respects_max_expiries(self, MockTicker):
        mock_ticker = MagicMock()
        mock_ticker.options = ("2024-01-01", "2024-02-01", "2024-03-01")
        empty_chain = MagicMock()
        empty_chain.calls = pd.DataFrame()
        empty_chain.puts = pd.DataFrame()
        mock_ticker.option_chain.return_value = empty_chain
        MockTicker.return_value = mock_ticker
        results = YFinanceClient().get_options_chain("AAPL", max_expiries=2)
        assert len(results) == 2

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_returns_empty_on_exception(self, MockTicker):
        MockTicker.side_effect = Exception("error")
        assert YFinanceClient().get_options_chain("AAPL") == []

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_handles_nan_strike(self, MockTicker):
        calls_df = pd.DataFrame(
            {
                "contractSymbol": ["AAPL240101C00150000"],
                "strike": [float("nan")],
                "lastPrice": [5.20],
                "bid": [5.10],
                "ask": [5.30],
                "volume": [1000],
                "openInterest": [5000],
                "impliedVolatility": [0.25],
                "inTheMoney": [True],
            }
        )
        chain = MagicMock()
        chain.calls = calls_df
        chain.puts = pd.DataFrame()
        mock_ticker = MagicMock()
        mock_ticker.options = ("2024-01-01",)
        mock_ticker.option_chain.return_value = chain
        MockTicker.return_value = mock_ticker
        results = YFinanceClient().get_options_chain("AAPL", max_expiries=1)
        assert len(results) == 1
        assert results[0]["calls"][0]["strike"] is None


class TestGetShortInterest:
    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_returns_short_interest_dict(self, MockTicker):
        MockTicker.return_value.info = {
            "symbol": "AAPL",
            "dateShortInterest": 1710460800,  # 2024-03-15
            "sharesShort": 120_000_000,
            "sharesShortPriorMonth": 110_000_000,
            "shortRatio": 2.1,
            "shortPercentOfFloat": 0.008,
            "sharesPercentSharesOut": 0.0077,
        }
        result = YFinanceClient().get_short_interest("AAPL")
        assert result is not None
        assert result["shares_short"] == 120_000_000
        assert result["short_ratio"] == 2.1
        assert result["short_pct_of_float"] == 0.008

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_returns_none_for_empty_info(self, MockTicker):
        MockTicker.return_value.info = {}
        assert YFinanceClient().get_short_interest("AAPL") is None

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_returns_none_on_exception(self, MockTicker):
        MockTicker.side_effect = Exception("error")
        assert YFinanceClient().get_short_interest("AAPL") is None

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_epoch_date_converted(self, MockTicker):
        MockTicker.return_value.info = {
            "symbol": "AAPL",
            "dateShortInterest": 1704067200,  # 2024-01-01
        }
        result = YFinanceClient().get_short_interest("AAPL")
        assert result["date_short_interest"] == date(2024, 1, 1)

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_none_values_handled(self, MockTicker):
        MockTicker.return_value.info = {"symbol": "AAPL"}
        result = YFinanceClient().get_short_interest("AAPL")
        assert result["shares_short"] is None
        assert result["short_ratio"] is None


class TestGetShortInterestFromRaw:
    def test_returns_short_interest_dict(self):
        raw = {
            "dateShortInterest": 1710460800,
            "sharesShort": 120_000_000,
            "sharesShortPriorMonth": 110_000_000,
            "shortRatio": 2.1,
            "shortPercentOfFloat": 0.008,
            "sharesPercentSharesOut": 0.0077,
        }
        result = YFinanceClient().get_short_interest_from_raw(raw)
        assert result is not None
        assert result["shares_short"] == 120_000_000
        assert result["short_ratio"] == 2.1

    def test_returns_none_for_empty_raw(self):
        assert YFinanceClient().get_short_interest_from_raw({}) is None
        assert YFinanceClient().get_short_interest_from_raw(None) is None

    def test_none_fields_handled(self):
        result = YFinanceClient().get_short_interest_from_raw({"someOtherKey": "value"})
        assert result["shares_short"] is None
        assert result["short_pct_of_float"] is None


class TestDiscoverTickers:
    @patch("apps.companies.yfinance_client.YFinanceClient._nasdaq100_tickers")
    @patch("apps.companies.yfinance_client.YFinanceClient._sp500_tickers")
    def test_combines_and_deduplicates(self, mock_sp500, mock_nasdaq):
        mock_sp500.return_value = ["AAPL", "MSFT", "SHARED"]
        mock_nasdaq.return_value = ["SHARED", "GOOG"]
        result = YFinanceClient().discover_tickers()
        assert "AAPL" in result
        assert "MSFT" in result
        assert "SHARED" in result
        assert "GOOG" in result
        assert result.count("SHARED") == 1

    @patch("apps.companies.yfinance_client.YFinanceClient._nasdaq100_tickers")
    @patch("apps.companies.yfinance_client.YFinanceClient._sp500_tickers")
    def test_skips_empty_strings(self, mock_sp500, mock_nasdaq):
        mock_sp500.return_value = ["AAPL", "", "MSFT"]
        mock_nasdaq.return_value = []
        result = YFinanceClient().discover_tickers()
        assert "" not in result
        assert len(result) == 2

    @patch("apps.companies.yfinance_client.httpx.get")
    def test_sp500_tickers_parses_csv(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.text = "Symbol,Name\nAAPL,Apple\nBRK.B,Berkshire\n"
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        result = YFinanceClient()._sp500_tickers()
        assert "AAPL" in result
        assert "BRK-B" in result  # dot normalised to dash

    @patch("apps.companies.yfinance_client.httpx.get")
    def test_sp500_tickers_returns_empty_on_error(self, mock_get):
        mock_get.side_effect = Exception("network error")
        assert YFinanceClient()._sp500_tickers() == []

    @patch("apps.companies.yfinance_client.httpx.get")
    def test_nasdaq100_tickers_parses_json(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": {"data": {"rows": [{"symbol": "AAPL"}, {"symbol": "MSFT"}]}}
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        result = YFinanceClient()._nasdaq100_tickers()
        assert "AAPL" in result
        assert "MSFT" in result

    @patch("apps.companies.yfinance_client.httpx.get")
    def test_nasdaq100_tickers_returns_empty_on_error(self, mock_get):
        mock_get.side_effect = Exception("network error")
        assert YFinanceClient()._nasdaq100_tickers() == []


class TestGetBulkProfiles:
    @patch("apps.companies.yfinance_client.time.sleep")
    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_returns_successful_profiles(self, MockTicker, mock_sleep):
        MockTicker.return_value.info = {
            "symbol": "AAPL",
            "longName": "Apple Inc.",
            "exchange": "NMS",
            "currency": "USD",
        }
        result = YFinanceClient().get_bulk_profiles(["AAPL"], delay=0)
        assert "AAPL" in result
        assert result["AAPL"]["name"] == "Apple Inc."

    @patch("apps.companies.yfinance_client.time.sleep")
    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_skips_failed_tickers(self, MockTicker, mock_sleep):
        MockTicker.side_effect = [Exception("error"), MagicMock(info={"symbol": "MSFT"})]
        result = YFinanceClient().get_bulk_profiles(["AAPL", "MSFT"], delay=0)
        assert "AAPL" not in result

    @patch("apps.companies.yfinance_client.time.sleep")
    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_calls_on_progress_callback(self, MockTicker, mock_sleep):
        MockTicker.return_value.info = {"symbol": "AAPL", "longName": "Apple"}
        calls = []
        YFinanceClient().get_bulk_profiles(["AAPL"], delay=0, on_progress=calls.append)
        assert "AAPL" in calls


class TestNormalizeProfileOfficerEdgeCase:
    def test_skips_non_dict_officers(self):
        info = {
            "symbol": "AAPL",
            "companyOfficers": ["not a dict", {"name": "Tim Cook", "title": "CEO"}],
        }
        result = _normalize_profile("AAPL", info)
        assert len(result["officers"]) == 1
        assert result["officers"][0]["name"] == "Tim Cook"


class TestGetInstitutionalHoldersEdgeCases:
    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_handles_pct_held_column_alias(self, MockTicker):
        df = pd.DataFrame(
            {
                "Holder": ["Vanguard"],
                "Shares": [1_000_000],
                "Date Reported": pd.to_datetime(["2024-03-31"]),
                "pctHeld": [0.065],
                "Value": [180_000_000],
            }
        )
        MockTicker.return_value.institutional_holders = df
        rows = YFinanceClient().get_institutional_holders("AAPL")
        assert len(rows) == 1
        assert rows[0]["pct_out"] == 0.065

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_handles_none_date_reported(self, MockTicker):
        df = pd.DataFrame(
            {
                "Holder": ["Vanguard"],
                "Shares": [1_000_000],
                "Date Reported": [None],
                "% Out": [0.065],
                "Value": [180_000_000],
            }
        )
        MockTicker.return_value.institutional_holders = df
        rows = YFinanceClient().get_institutional_holders("AAPL")
        assert len(rows) == 1
        assert rows[0]["date_reported"] is None

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_handles_string_date_reported(self, MockTicker):
        df = pd.DataFrame(
            {
                "Holder": ["Vanguard"],
                "Shares": [1_000_000],
                "Date Reported": ["2024-03-31"],
                "% Out": [0.065],
                "Value": [180_000_000],
            }
        )
        MockTicker.return_value.institutional_holders = df
        rows = YFinanceClient().get_institutional_holders("AAPL")
        assert len(rows) == 1
        assert rows[0]["date_reported"] == "2024-03-31"


class TestGetEarningsDatesEdgeCases:
    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_returns_empty_on_exception(self, MockTicker):
        MockTicker.side_effect = Exception("error")
        assert YFinanceClient().get_earnings_dates("AAPL") == []


class TestGetSnapshotInvalidValues:
    """Cover the exception branches in get_snapshot helper closures."""

    def _make_ticker(self, MockTicker, info: dict):
        mock = MagicMock()
        mock.info = info
        mock.recommendations = pd.DataFrame()
        MockTicker.return_value = mock

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_invalid_float_field_returns_none(self, MockTicker):
        self._make_ticker(
            MockTicker,
            {
                "symbol": "AAPL",
                "trailingPE": "not-a-number",
            },
        )
        snap = YFinanceClient().get_snapshot("AAPL")
        assert snap is not None
        assert snap["trailing_pe"] is None

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_invalid_int_field_returns_none(self, MockTicker):
        self._make_ticker(
            MockTicker,
            {
                "symbol": "AAPL",
                "marketCap": "N/A",
            },
        )
        snap = YFinanceClient().get_snapshot("AAPL")
        assert snap is not None
        assert snap["market_cap"] is None

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_invalid_small_int_field_returns_none(self, MockTicker):
        self._make_ticker(
            MockTicker,
            {
                "symbol": "AAPL",
                "auditRisk": "bad-value",
            },
        )
        snap = YFinanceClient().get_snapshot("AAPL")
        assert snap is not None
        assert snap["audit_risk"] is None


class TestGetBulkProfilesDelayAndBatch:
    @patch("apps.companies.yfinance_client.time.sleep")
    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_sleeps_between_tickers(self, MockTicker, mock_sleep):
        MockTicker.return_value.info = {"symbol": "AAPL", "longName": "Apple Inc."}
        YFinanceClient().get_bulk_profiles(["AAPL"], delay=0.1)
        mock_sleep.assert_called_with(0.1)

    @patch("apps.companies.yfinance_client.time.sleep")
    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_batch_delay_triggered_at_batch_boundary(self, MockTicker, mock_sleep):
        def make_info(sym):
            return {"symbol": sym, "longName": sym}

        MockTicker.return_value.info = {"symbol": "A", "longName": "A"}
        # Two symbols, batch_size=1: after first symbol the batch boundary fires
        calls_made = []

        def record_sleep(s):
            calls_made.append(s)

        mock_sleep.side_effect = record_sleep
        mock_ticker = MagicMock()
        mock_ticker.info = {"symbol": "AAPL"}
        MockTicker.return_value = mock_ticker

        YFinanceClient().get_bulk_profiles(["AAPL", "MSFT"], delay=0, batch_size=1)
        # 2.0-second batch delay should have been called once
        assert 2.0 in calls_made


class TestGetPriceHistoryEdgeCases:
    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_passes_start_to_history(self, MockTicker):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()
        MockTicker.return_value = mock_ticker
        YFinanceClient().get_price_history("AAPL", start=date(2024, 1, 1))
        mock_ticker.history.assert_called_once_with(start="2024-01-01")

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_skips_row_with_none_close(self, MockTicker):
        df = pd.DataFrame(
            {
                "Open": [150.0],
                "High": [155.0],
                "Low": [149.0],
                "Close": [None],
                "Volume": [100000],
            },
            index=pd.to_datetime(["2024-01-01"]),
        )
        MockTicker.return_value.history.return_value = df
        rows = YFinanceClient().get_price_history("AAPL")
        assert rows == []


class TestGetShortInterestInvalidValues:
    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_invalid_float_returns_none(self, MockTicker):
        MockTicker.return_value.info = {
            "symbol": "AAPL",
            "shortRatio": "bad",
        }
        result = YFinanceClient().get_short_interest("AAPL")
        assert result["short_ratio"] is None

    @patch("apps.companies.yfinance_client.yf.Ticker")
    def test_invalid_int_returns_none(self, MockTicker):
        MockTicker.return_value.info = {
            "symbol": "AAPL",
            "sharesShort": "N/A",
        }
        result = YFinanceClient().get_short_interest("AAPL")
        assert result["shares_short"] is None
