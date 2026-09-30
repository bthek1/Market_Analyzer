from datetime import UTC, date
from datetime import datetime as dt
from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.companies.models import (
    Company,
    CompanySnapshot,
    CompanySummary,
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

# ---------------------------------------------------------------------------
# Sector views
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSectorListCreateView:
    url = "/api/companies/sectors/"

    def test_list_unauthenticated_returns_200(self, api_client):
        assert api_client.get(self.url).status_code == 200

    def test_list_returns_all_sectors(self, api_client):
        Sector.objects.create(name="Technology")
        Sector.objects.create(name="Finance")
        assert api_client.get(self.url).data["count"] == 2

    def test_list_ordered_alphabetically(self, api_client):
        Sector.objects.create(name="Technology")
        Sector.objects.create(name="Finance")
        names = [s["name"] for s in api_client.get(self.url).data["results"]]
        assert names == sorted(names)

    def test_create_authenticated_returns_201(self, auth_client):
        resp = auth_client.post(self.url, {"name": "Healthcare"})
        assert resp.status_code == 201
        assert resp.data["name"] == "Healthcare"

    def test_create_unauthenticated_returns_401(self, api_client):
        assert api_client.post(self.url, {"name": "Healthcare"}).status_code == 401

    def test_create_persists_to_db(self, auth_client):
        auth_client.post(self.url, {"name": "Energy"})
        assert Sector.objects.filter(name="Energy").exists()

    def test_create_duplicate_name_returns_400(self, auth_client):
        Sector.objects.create(name="Technology")
        assert auth_client.post(self.url, {"name": "Technology"}).status_code == 400

    def test_id_is_int(self, api_client):
        Sector.objects.create(name="Technology")
        data = api_client.get(self.url).data["results"][0]
        assert isinstance(data["id"], int)


@pytest.mark.django_db
class TestSectorDetailView:
    def _url(self, pk):
        return f"/api/companies/sectors/{pk}/"

    def test_retrieve_returns_200(self, api_client):
        s = Sector.objects.create(name="Technology")
        assert api_client.get(self._url(s.pk)).status_code == 200

    def test_retrieve_nonexistent_returns_404(self, api_client):
        assert api_client.get(self._url(99999)).status_code == 404

    def test_partial_update_authenticated(self, auth_client):
        s = Sector.objects.create(name="Technology")
        resp = auth_client.patch(self._url(s.pk), {"description": "Updated"})
        assert resp.status_code == 200
        assert resp.data["description"] == "Updated"

    def test_delete_authenticated_returns_204(self, auth_client):
        s = Sector.objects.create(name="Technology")
        assert auth_client.delete(self._url(s.pk)).status_code == 204
        assert not Sector.objects.filter(pk=s.pk).exists()

    def test_delete_unauthenticated_returns_401(self, api_client):
        s = Sector.objects.create(name="Technology")
        assert api_client.delete(self._url(s.pk)).status_code == 401


# ---------------------------------------------------------------------------
# Industry views
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestIndustryListCreateView:
    url = "/api/companies/industries/"

    def setup_method(self):
        self.sector = Sector.objects.create(name="Technology")

    def test_list_unauthenticated_returns_200(self, api_client):
        assert api_client.get(self.url).status_code == 200

    def test_list_returns_all_industries(self, api_client):
        Industry.objects.create(name="Software")
        Industry.objects.create(name="Hardware")
        assert api_client.get(self.url).data["count"] == 2

    def test_list_filter_by_sector(self, api_client):
        Industry.objects.create(name="Software", sector=self.sector)
        other = Sector.objects.create(name="Finance")
        Industry.objects.create(name="Banking", sector=other)
        resp = api_client.get(self.url, {"sector": self.sector.pk})
        assert resp.data["count"] == 1
        assert resp.data["results"][0]["name"] == "Software"

    def test_create_authenticated_returns_201(self, auth_client):
        resp = auth_client.post(self.url, {"name": "Biotech", "sector": self.sector.pk})
        assert resp.status_code == 201
        assert resp.data["sector_name"] == "Technology"

    def test_create_unauthenticated_returns_401(self, api_client):
        assert api_client.post(self.url, {"name": "Biotech"}).status_code == 401

    def test_create_without_sector(self, auth_client):
        resp = auth_client.post(self.url, {"name": "Fintech"})
        assert resp.status_code == 201
        assert resp.data["sector"] is None


@pytest.mark.django_db
class TestIndustryDetailView:
    def _url(self, pk):
        return f"/api/companies/industries/{pk}/"

    def test_retrieve_returns_200(self, api_client):
        ind = Industry.objects.create(name="Software")
        assert api_client.get(self._url(ind.pk)).status_code == 200

    def test_retrieve_nonexistent_returns_404(self, api_client):
        assert api_client.get(self._url(99999)).status_code == 404

    def test_delete_authenticated_returns_204(self, auth_client):
        ind = Industry.objects.create(name="Software")
        assert auth_client.delete(self._url(ind.pk)).status_code == 204

    def test_delete_unauthenticated_returns_401(self, api_client):
        ind = Industry.objects.create(name="Software")
        assert api_client.delete(self._url(ind.pk)).status_code == 401


# ---------------------------------------------------------------------------
# Company views
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCompanyListCreateView:
    url = "/api/companies/"

    def setup_method(self):
        self.sector = Sector.objects.create(name="Technology")
        self.industry = Industry.objects.create(name="Software", sector=self.sector)

    def test_list_unauthenticated_returns_200(self, api_client):
        assert api_client.get(self.url).status_code == 200

    def test_list_returns_all_companies(self, api_client):
        Company.objects.create(symbol="AAPL")
        Company.objects.create(symbol="MSFT")
        assert api_client.get(self.url).data["count"] == 2

    def test_list_filter_by_sector(self, api_client):
        Company.objects.create(symbol="AAPL", sector=self.sector)
        Company.objects.create(symbol="JPM")
        resp = api_client.get(self.url, {"sector": self.sector.pk})
        assert resp.data["count"] == 1
        assert resp.data["results"][0]["symbol"] == "AAPL"

    def test_list_filter_by_industry(self, api_client):
        Company.objects.create(symbol="AAPL", industry=self.industry)
        Company.objects.create(symbol="JPM")
        resp = api_client.get(self.url, {"industry": self.industry.pk})
        assert resp.data["count"] == 1

    def test_list_filter_by_exchange(self, api_client):
        Company.objects.create(symbol="AAPL", exchange="NASDAQ")
        Company.objects.create(symbol="JPM", exchange="NYSE")
        resp = api_client.get(self.url, {"exchange": "NASDAQ"})
        assert resp.data["count"] == 1
        assert resp.data["results"][0]["symbol"] == "AAPL"

    def test_response_includes_sector_and_industry_names(self, api_client):
        Company.objects.create(symbol="AAPL", sector=self.sector, industry=self.industry)
        result = api_client.get(self.url).data["results"][0]
        assert result["sector_name"] == "Technology"
        assert result["industry_name"] == "Software"

    def test_create_authenticated_returns_201(self, auth_client):
        resp = auth_client.post(self.url, {"symbol": "AAPL"})
        assert resp.status_code == 201
        assert resp.data["symbol"] == "AAPL"

    def test_create_unauthenticated_returns_401(self, api_client):
        assert api_client.post(self.url, {"symbol": "AAPL"}).status_code == 401

    def test_create_missing_symbol_returns_400(self, auth_client):
        assert auth_client.post(self.url, {"name": "No Symbol"}).status_code == 400

    def test_create_duplicate_symbol_returns_400(self, auth_client):
        Company.objects.create(symbol="AAPL")
        assert auth_client.post(self.url, {"symbol": "AAPL"}).status_code == 400

    def test_search_by_symbol(self, api_client):
        Company.objects.create(symbol="AAPL", name="Apple Inc.")
        Company.objects.create(symbol="MSFT", name="Microsoft")
        resp = api_client.get(self.url, {"search": "AAPL"})
        assert resp.data["count"] == 1
        assert resp.data["results"][0]["symbol"] == "AAPL"

    def test_search_by_name(self, api_client):
        Company.objects.create(symbol="AAPL", name="Apple Inc.")
        Company.objects.create(symbol="MSFT", name="Microsoft")
        resp = api_client.get(self.url, {"search": "Apple"})
        assert resp.data["count"] == 1
        assert resp.data["results"][0]["symbol"] == "AAPL"

    def test_search_empty_returns_all(self, api_client):
        Company.objects.create(symbol="AAPL")
        Company.objects.create(symbol="MSFT")
        assert api_client.get(self.url, {"search": ""}).data["count"] == 2

    def test_filter_by_is_bootstrapped_true(self, api_client):
        Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        Company.objects.create(symbol="MSFT", is_bootstrapped=False)
        resp = api_client.get(self.url, {"is_bootstrapped": "true"})
        assert resp.data["count"] == 1
        assert resp.data["results"][0]["symbol"] == "AAPL"

    def test_filter_by_is_bootstrapped_false(self, api_client):
        Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        Company.objects.create(symbol="MSFT", is_bootstrapped=False)
        resp = api_client.get(self.url, {"is_bootstrapped": "false"})
        assert resp.data["count"] == 1
        assert resp.data["results"][0]["symbol"] == "MSFT"

    def test_list_includes_snapshot_metrics(self, api_client):
        company = Company.objects.create(symbol="AAPL")
        CompanySnapshot.objects.create(
            company=company,
            market_cap=3_000_000_000_000,
            trailing_pe=28.5,
            profit_margins=0.253,
            dividend_yield=0.005,
            raw={},
        )
        result = api_client.get(self.url).data["results"][0]
        assert result["market_cap"] == pytest.approx(3_000_000_000_000)
        assert result["trailing_pe"] == pytest.approx(28.5)
        assert result["profit_margins"] == pytest.approx(0.253)
        assert result["dividend_yield"] == pytest.approx(0.005)

    def test_list_snapshot_metrics_null_when_no_snapshot(self, api_client):
        Company.objects.create(symbol="AAPL")
        result = api_client.get(self.url).data["results"][0]
        assert result["market_cap"] is None
        assert result["trailing_pe"] is None
        assert result["profit_margins"] is None
        assert result["dividend_yield"] is None

    def test_ordering_by_market_cap_desc(self, api_client):
        c1 = Company.objects.create(symbol="SMALL")
        c2 = Company.objects.create(symbol="BIG")
        CompanySnapshot.objects.create(company=c1, market_cap=1_000_000, raw={})
        CompanySnapshot.objects.create(company=c2, market_cap=1_000_000_000_000, raw={})
        resp = api_client.get(self.url, {"ordering": "-market_cap"})
        symbols = [r["symbol"] for r in resp.data["results"]]
        assert symbols[0] == "BIG"

    def test_ordering_by_symbol_asc(self, api_client):
        Company.objects.create(symbol="MSFT")
        Company.objects.create(symbol="AAPL")
        resp = api_client.get(self.url, {"ordering": "symbol"})
        symbols = [r["symbol"] for r in resp.data["results"]]
        assert symbols == sorted(symbols)

    def test_ordering_by_symbol_desc(self, api_client):
        Company.objects.create(symbol="MSFT")
        Company.objects.create(symbol="AAPL")
        resp = api_client.get(self.url, {"ordering": "-symbol"})
        symbols = [r["symbol"] for r in resp.data["results"]]
        assert symbols == sorted(symbols, reverse=True)

    def test_response_includes_is_bootstrapped(self, api_client):
        Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        result = api_client.get(self.url).data["results"][0]
        assert result["is_bootstrapped"] is True


@pytest.mark.django_db
class TestCompanyDetailView:
    def _url(self, pk):
        return f"/api/companies/{pk}/"

    def test_retrieve_returns_200(self, api_client):
        c = Company.objects.create(symbol="AAPL")
        assert api_client.get(self._url(c.pk)).status_code == 200

    def test_retrieve_nonexistent_returns_404(self, api_client):
        assert api_client.get(self._url(99999)).status_code == 404

    def test_retrieve_includes_fk_names(self, api_client):
        sector = Sector.objects.create(name="Technology")
        industry = Industry.objects.create(name="Software", sector=sector)
        c = Company.objects.create(symbol="AAPL", sector=sector, industry=industry)
        resp = api_client.get(self._url(c.pk))
        assert resp.data["sector_name"] == "Technology"
        assert resp.data["industry_name"] == "Software"

    def test_partial_update_authenticated(self, auth_client):
        c = Company.objects.create(symbol="AAPL")
        resp = auth_client.patch(self._url(c.pk), {"name": "Apple Inc."})
        assert resp.status_code == 200
        assert resp.data["name"] == "Apple Inc."

    def test_update_unauthenticated_returns_401(self, api_client):
        c = Company.objects.create(symbol="AAPL")
        assert api_client.patch(self._url(c.pk), {"name": "Apple"}).status_code == 401

    def test_delete_authenticated_returns_204(self, auth_client):
        c = Company.objects.create(symbol="AAPL")
        assert auth_client.delete(self._url(c.pk)).status_code == 204

    def test_clear_sector_preserves_company(self, auth_client):
        sector = Sector.objects.create(name="Technology")
        c = Company.objects.create(symbol="AAPL", sector=sector)
        resp = auth_client.patch(self._url(c.pk), data={"sector": None}, format="json")
        assert resp.status_code == 200
        assert resp.data["sector"] is None

    def test_pk_is_int(self, api_client):
        c = Company.objects.create(symbol="AAPL")
        resp = api_client.get(self._url(c.pk))
        assert isinstance(resp.data["id"], int)


# ---------------------------------------------------------------------------
# Nested data views
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPriceBarListView:
    def setup_method(self):
        self.company = Company.objects.create(symbol="AAPL")

    def _url(self, pk):
        return f"/api/companies/{pk}/prices/"

    def _bar(self, d, **kw):
        defaults = dict(open="150", high="155", low="149", close="153", volume=100000)
        defaults.update(kw)
        return PriceBar.objects.create(company=self.company, date=d, **defaults)

    def test_returns_200(self, api_client):
        assert api_client.get(self._url(self.company.pk)).status_code == 200

    def test_returns_bars_for_company(self, api_client):
        self._bar(date(2024, 1, 1))
        self._bar(date(2024, 1, 2))
        resp = api_client.get(self._url(self.company.pk))
        assert resp.data["count"] == 2

    def test_filter_by_start_date(self, api_client):
        self._bar(date(2024, 1, 1))
        self._bar(date(2024, 1, 5))
        resp = api_client.get(self._url(self.company.pk), {"start": "2024-01-03"})
        assert resp.data["count"] == 1

    def test_filter_by_end_date(self, api_client):
        self._bar(date(2024, 1, 1))
        self._bar(date(2024, 1, 5))
        resp = api_client.get(self._url(self.company.pk), {"end": "2024-01-03"})
        assert resp.data["count"] == 1

    def test_bars_ordered_by_date_asc(self, api_client):
        self._bar(date(2024, 1, 3))
        self._bar(date(2024, 1, 1))
        dates = [r["date"] for r in api_client.get(self._url(self.company.pk)).data["results"]]
        assert dates == sorted(dates)


@pytest.mark.django_db
class TestCompanySnapshotListView:
    def setup_method(self):
        self.company = Company.objects.create(symbol="AAPL")

    def _url(self, pk):
        return f"/api/companies/{pk}/snapshots/"

    def test_returns_200(self, api_client):
        assert api_client.get(self._url(self.company.pk)).status_code == 200

    def test_returns_snapshots_for_company(self, api_client):
        CompanySnapshot.objects.create(company=self.company, raw={})
        CompanySnapshot.objects.create(company=self.company, raw={})
        assert api_client.get(self._url(self.company.pk)).data["count"] == 2

    def test_does_not_return_other_companies_snapshots(self, api_client):
        other = Company.objects.create(symbol="MSFT")
        CompanySnapshot.objects.create(company=other, raw={})
        assert api_client.get(self._url(self.company.pk)).data["count"] == 0


@pytest.mark.django_db
class TestFinancialStatementListView:
    def setup_method(self):
        self.company = Company.objects.create(symbol="AAPL")

    def _url(self, pk):
        return f"/api/companies/{pk}/financials/"

    def _fs(self, statement_type, period, metric="Revenue", value=100.0):
        return FinancialStatement.objects.create(
            company=self.company,
            statement_type=statement_type,
            period=period,
            period_end=date(2023, 12, 31),
            metric=metric,
            value=value,
        )

    def test_returns_200(self, api_client):
        assert api_client.get(self._url(self.company.pk)).status_code == 200

    def test_filter_by_statement_type(self, api_client):
        self._fs("income", "annual")
        self._fs("balance", "annual", metric="Assets")
        resp = api_client.get(self._url(self.company.pk), {"statement_type": "income"})
        assert resp.data["count"] == 1
        assert resp.data["results"][0]["statement_type"] == "income"

    def test_filter_by_period(self, api_client):
        self._fs("income", "annual")
        self._fs("income", "quarterly", metric="Q1 Revenue")
        resp = api_client.get(self._url(self.company.pk), {"period": "quarterly"})
        assert resp.data["count"] == 1


@pytest.mark.django_db
class TestDividendListView:
    def setup_method(self):
        self.company = Company.objects.create(symbol="AAPL")

    def _url(self, pk):
        return f"/api/companies/{pk}/dividends/"

    def test_returns_200(self, api_client):
        assert api_client.get(self._url(self.company.pk)).status_code == 200

    def test_returns_dividends_for_company(self, api_client):
        Dividend.objects.create(company=self.company, date=date(2024, 3, 1), amount="0.24")
        Dividend.objects.create(company=self.company, date=date(2024, 6, 1), amount="0.25")
        assert api_client.get(self._url(self.company.pk)).data["count"] == 2

    def test_dividends_ordered_newest_first(self, api_client):
        Dividend.objects.create(company=self.company, date=date(2024, 3, 1), amount="0.24")
        Dividend.objects.create(company=self.company, date=date(2024, 6, 1), amount="0.25")
        dates = [r["date"] for r in api_client.get(self._url(self.company.pk)).data["results"]]
        assert dates == sorted(dates, reverse=True)


# ---------------------------------------------------------------------------
# Sector company_count / industry_count annotations
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSectorAnnotations:
    url = "/api/companies/sectors/"

    def test_company_count_is_zero_with_no_companies(self, api_client):
        Sector.objects.create(name="Technology")
        result = api_client.get(self.url).data["results"][0]
        assert result["company_count"] == 0

    def test_company_count_reflects_linked_companies(self, api_client):
        sector = Sector.objects.create(name="Technology")
        Company.objects.create(symbol="AAPL", sector=sector)
        Company.objects.create(symbol="MSFT", sector=sector)
        result = api_client.get(self.url).data["results"][0]
        assert result["company_count"] == 2

    def test_industry_count_is_zero_with_no_industries(self, api_client):
        Sector.objects.create(name="Technology")
        result = api_client.get(self.url).data["results"][0]
        assert result["industry_count"] == 0

    def test_industry_count_reflects_linked_industries(self, api_client):
        sector = Sector.objects.create(name="Technology")
        Industry.objects.create(name="Software", sector=sector)
        Industry.objects.create(name="Hardware", sector=sector)
        result = api_client.get(self.url).data["results"][0]
        assert result["industry_count"] == 2


# ---------------------------------------------------------------------------
# Market hierarchy view
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestMarketHierarchyView:
    url = "/api/companies/market-hierarchy/"

    def test_returns_200(self, api_client):
        assert api_client.get(self.url).status_code == 200

    def test_empty_when_no_companies(self, api_client):
        Sector.objects.create(name="Technology")
        assert api_client.get(self.url).data == []

    def test_returns_sectors_with_companies(self, api_client):
        sector = Sector.objects.create(name="Technology")
        Company.objects.create(symbol="AAPL", sector=sector)
        data = api_client.get(self.url).data
        assert len(data) == 1
        assert data[0]["name"] == "Technology"
        assert data[0]["company_count"] == 1

    def test_children_include_industries(self, api_client):
        sector = Sector.objects.create(name="Technology")
        ind = Industry.objects.create(name="Software", sector=sector)
        Company.objects.create(symbol="AAPL", sector=sector, industry=ind)
        data = api_client.get(self.url).data
        children = data[0]["children"]
        assert len(children) == 1
        assert children[0]["name"] == "Software"
        assert children[0]["company_count"] == 1

    def test_other_bucket_for_uncategorised(self, api_client):
        sector = Sector.objects.create(name="Technology")
        Company.objects.create(symbol="AAPL", sector=sector, industry=None)
        data = api_client.get(self.url).data
        children = data[0]["children"]
        assert any(c["name"] == "Other" for c in children)

    def test_market_cap_mode_returns_market_cap_value(self, api_client):
        sector = Sector.objects.create(name="Technology")
        company = Company.objects.create(symbol="AAPL", sector=sector)
        CompanySnapshot.objects.create(
            company=company,
            market_cap=3_000_000,
            fetched_at=dt(2024, 6, 1, tzinfo=UTC),
            raw={},
        )
        data = api_client.get(self.url, {"metric": "market_cap"}).data
        assert len(data) == 1
        assert float(data[0]["market_cap"]) == pytest.approx(3_000_000)
        assert float(data[0]["value"]) == pytest.approx(3_000_000)

    def test_invalid_metric_falls_back_to_count(self, api_client):
        sector = Sector.objects.create(name="Technology")
        Company.objects.create(symbol="AAPL", sector=sector)
        data = api_client.get(self.url, {"metric": "invalid"}).data
        assert data[0]["value"] == 1

    def test_ordered_by_company_count_desc(self, api_client):
        s1 = Sector.objects.create(name="Technology")
        s2 = Sector.objects.create(name="Finance")
        Company.objects.create(symbol="AAPL", sector=s1)
        Company.objects.create(symbol="MSFT", sector=s1)
        Company.objects.create(symbol="JPM", sector=s2)
        data = api_client.get(self.url).data
        counts = [d["company_count"] for d in data]
        assert counts == sorted(counts, reverse=True)


# ---------------------------------------------------------------------------
# Financials pivoted view
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFinancialsPivotedView:
    def setup_method(self):
        self.company = Company.objects.create(symbol="AAPL")

    def _url(self, pk):
        return f"/api/companies/{pk}/financials/pivoted/"

    def _fs(self, metric, period_end, value, statement_type="income", period="annual"):
        FinancialStatement.objects.create(
            company=self.company,
            statement_type=statement_type,
            period=period,
            period_end=period_end,
            metric=metric,
            value=value,
        )

    def test_returns_200(self, api_client):
        assert api_client.get(self._url(self.company.pk)).status_code == 200

    def test_returns_dates_and_rows(self, api_client):
        self._fs("Revenue", date(2023, 12, 31), 100.0)
        data = api_client.get(self._url(self.company.pk)).data
        assert "dates" in data
        assert "rows" in data

    def test_dates_ordered_newest_first(self, api_client):
        self._fs("Revenue", date(2021, 12, 31), 80.0)
        self._fs("Costs", date(2023, 12, 31), 100.0)
        data = api_client.get(self._url(self.company.pk)).data
        assert data["dates"] == sorted(data["dates"], reverse=True)

    def test_limited_to_four_dates(self, api_client):
        for yr in [2020, 2021, 2022, 2023, 2024]:
            self._fs("Revenue", date(yr, 12, 31), float(yr))
        data = api_client.get(self._url(self.company.pk)).data
        assert len(data["dates"]) == 4

    def test_filter_by_statement_type(self, api_client):
        self._fs("Revenue", date(2023, 12, 31), 100.0, statement_type="income")
        self._fs("Assets", date(2023, 12, 31), 200.0, statement_type="balance")
        data = api_client.get(self._url(self.company.pk), {"statement_type": "income"}).data
        metrics = [r["metric"] for r in data["rows"]]
        assert "Revenue" in metrics
        assert "Assets" not in metrics

    def test_values_aligned_to_dates(self, api_client):
        self._fs("Revenue", date(2023, 12, 31), 100.0)
        data = api_client.get(self._url(self.company.pk)).data
        row = data["rows"][0]
        assert len(row["values"]) == len(data["dates"])


# ---------------------------------------------------------------------------
# Price bar ordering
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPriceBarOrdering:
    def setup_method(self):
        self.company = Company.objects.create(symbol="AAPL")

    def _url(self):
        return f"/api/companies/{self.company.pk}/prices/"

    def _bar(self, d):
        PriceBar.objects.create(
            company=self.company,
            date=d,
            open="150",
            high="155",
            low="149",
            close="153",
            volume=100000,
        )

    def test_default_ordering_is_ascending(self, api_client):
        self._bar(date(2024, 1, 3))
        self._bar(date(2024, 1, 1))
        dates = [r["date"] for r in api_client.get(self._url()).data["results"]]
        assert dates == sorted(dates)

    def test_ordering_desc_by_date(self, api_client):
        self._bar(date(2024, 1, 1))
        self._bar(date(2024, 1, 3))
        resp = api_client.get(self._url(), {"ordering": "-date"})
        dates = [r["date"] for r in resp.data["results"]]
        assert dates == sorted(dates, reverse=True)


# ---------------------------------------------------------------------------
# yfinance sync / ingest views
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestYFSyncCompanyView:
    def _url(self, symbol):
        return f"/api/companies/yf/sync/{symbol}/"

    @patch("apps.companies.views.sync_company_profile")
    def test_syncs_and_returns_company(self, mock_sync, auth_client):
        company = Company.objects.create(symbol="AAPL", name="Apple Inc.")
        mock_sync.return_value = company
        resp = auth_client.post(self._url("AAPL"))
        assert resp.status_code == 200
        assert resp.data["symbol"] == "AAPL"

    def test_requires_authentication(self, api_client):
        assert api_client.post(self._url("AAPL")).status_code == 401

    @patch("apps.companies.views.sync_company_profile")
    def test_not_found_returns_404(self, mock_sync, auth_client):
        mock_sync.return_value = None
        assert auth_client.post(self._url("ZZZZZ")).status_code == 404

    @patch("apps.companies.views.sync_company_profile")
    def test_uppercases_symbol(self, mock_sync, auth_client):
        company = Company.objects.create(symbol="AAPL")
        mock_sync.return_value = company
        auth_client.post(self._url("aapl"))
        mock_sync.assert_called_once_with("AAPL")


@pytest.mark.django_db
class TestYFIngestCompanyView:
    def _url(self, symbol):
        return f"/api/companies/yf/ingest/{symbol}/"

    @patch("apps.companies.views.sync_all_for_symbol")
    def test_successful_ingest_returns_200(self, mock_ingest, auth_client):
        mock_ingest.return_value = {
            "profile": True,
            "prices": 100,
            "snapshot": True,
            "financials": 50,
            "dividends": 10,
        }
        resp = auth_client.post(self._url("AAPL"))
        assert resp.status_code == 200
        assert resp.data["prices"] == 100

    def test_requires_authentication(self, api_client):
        assert api_client.post(self._url("AAPL")).status_code == 401

    @patch("apps.companies.views.sync_all_for_symbol")
    def test_profile_not_found_returns_404(self, mock_ingest, auth_client):
        mock_ingest.return_value = {
            "profile": False,
            "prices": 0,
            "snapshot": False,
            "financials": 0,
            "dividends": 0,
        }
        assert auth_client.post(self._url("ZZZZZ")).status_code == 404

    @patch("apps.companies.views.sync_all_for_symbol")
    def test_uppercases_symbol(self, mock_ingest, auth_client):
        mock_ingest.return_value = {
            "profile": True,
            "prices": 0,
            "snapshot": False,
            "financials": 0,
            "dividends": 0,
        }
        auth_client.post(self._url("aapl"))
        mock_ingest.assert_called_once_with("AAPL")


# ---------------------------------------------------------------------------
# Short interest view
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestShortInterestListView:
    def _url(self, pk):
        return f"/api/companies/{pk}/short-interest/"

    def test_returns_200(self, api_client):
        company = Company.objects.create(symbol="AAPL")
        resp = api_client.get(self._url(company.pk))
        assert resp.status_code == 200

    def test_returns_short_interest_rows(self, api_client):
        company = Company.objects.create(symbol="AAPL")
        ShortInterest.objects.create(
            company=company,
            fetched_at=dt.now(UTC),
            date_short_interest=date(2024, 3, 15),
            shares_short=120_000_000,
            short_ratio=2.1,
            short_pct_of_float=0.008,
        )
        resp = api_client.get(self._url(company.pk))
        assert resp.data["count"] == 1
        assert resp.data["results"][0]["shares_short"] == 120_000_000

    def test_returns_empty_for_company_with_no_data(self, api_client):
        company = Company.objects.create(symbol="AAPL")
        resp = api_client.get(self._url(company.pk))
        assert resp.data["count"] == 0

    def test_does_not_return_other_company_data(self, api_client):
        c1 = Company.objects.create(symbol="AAPL")
        c2 = Company.objects.create(symbol="MSFT")
        ShortInterest.objects.create(
            company=c2,
            fetched_at=dt.now(UTC),
            shares_short=50_000_000,
        )
        resp = api_client.get(self._url(c1.pk))
        assert resp.data["count"] == 0


# ---------------------------------------------------------------------------
# Institutional holders view
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestInstitutionalHoldersView:
    def _url(self, pk):
        return f"/api/companies/{pk}/institutional-holders/"

    def test_returns_200_when_data_exists(self, api_client):
        company = Company.objects.create(symbol="AAPL")
        InstitutionalHolderSnapshot.objects.create(
            company=company,
            fetched_at=dt.now(UTC),
            holders=[{"holder": "Vanguard", "shares": 1_000_000}],
        )
        resp = api_client.get(self._url(company.pk))
        assert resp.status_code == 200

    def test_returns_404_when_no_data(self, api_client):
        company = Company.objects.create(symbol="AAPL")
        resp = api_client.get(self._url(company.pk))
        assert resp.status_code == 404

    def test_returns_latest_snapshot(self, api_client):
        company = Company.objects.create(symbol="AAPL")
        old = dt(2024, 1, 1, tzinfo=UTC)
        new = dt(2024, 6, 1, tzinfo=UTC)
        InstitutionalHolderSnapshot.objects.create(
            company=company, fetched_at=old, holders=[{"holder": "Old"}]
        )
        InstitutionalHolderSnapshot.objects.create(
            company=company, fetched_at=new, holders=[{"holder": "Vanguard"}]
        )
        resp = api_client.get(self._url(company.pk))
        assert resp.data["holders"][0]["holder"] == "Vanguard"


# ---------------------------------------------------------------------------
# Earnings dates view
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEarningsDateListView:
    def _url(self, pk):
        return f"/api/companies/{pk}/earnings-dates/"

    def test_returns_200(self, api_client):
        company = Company.objects.create(symbol="AAPL")
        resp = api_client.get(self._url(company.pk))
        assert resp.status_code == 200

    def test_returns_earnings_date_rows(self, api_client):
        company = Company.objects.create(symbol="AAPL")
        EarningsDate.objects.create(
            company=company,
            earnings_date=date(2024, 1, 25),
            eps_estimate=2.10,
            reported_eps=2.18,
            surprise_pct=3.8,
            is_upcoming=False,
        )
        resp = api_client.get(self._url(company.pk))
        assert resp.data["count"] == 1
        assert float(resp.data["results"][0]["reported_eps"]) == 2.18

    def test_filter_by_is_upcoming(self, api_client):
        company = Company.objects.create(symbol="AAPL")
        EarningsDate.objects.create(
            company=company, earnings_date=date(2099, 1, 1), is_upcoming=True
        )
        EarningsDate.objects.create(
            company=company, earnings_date=date(2020, 1, 1), is_upcoming=False
        )
        resp = api_client.get(self._url(company.pk) + "?is_upcoming=true")
        assert resp.data["count"] == 1
        assert resp.data["results"][0]["is_upcoming"] is True


# ---------------------------------------------------------------------------
# Options expiry list + chain views
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestOptionsExpiryListView:
    # OptionsExpiryListView.get_queryset uses .distinct("expiry_date") which is
    # postgres-only — patch get_queryset to avoid that in the SQLite test env.

    def _url(self, pk):
        return f"/api/companies/{pk}/options/"

    @patch("apps.companies.views.OptionsExpiryListView.get_queryset")
    def test_returns_200(self, mock_qs, api_client):
        mock_qs.return_value = OptionsExpiry.objects.none()
        company = Company.objects.create(symbol="AAPL")
        resp = api_client.get(self._url(company.pk))
        assert resp.status_code == 200

    @patch("apps.companies.views.OptionsExpiryListView.get_queryset")
    def test_returns_expiry_dates(self, mock_qs, api_client):
        company = Company.objects.create(symbol="AAPL")
        expiry = OptionsExpiry.objects.create(
            company=company,
            expiry_date=date(2024, 1, 19),
            fetched_at=dt.now(UTC),
        )
        mock_qs.return_value = OptionsExpiry.objects.filter(pk=expiry.pk)
        resp = api_client.get(self._url(company.pk))
        assert resp.data["count"] == 1
        assert resp.data["results"][0]["expiry_date"] == "2024-01-19"

    @patch("apps.companies.views.OptionsExpiryListView.get_queryset")
    def test_returns_empty_when_no_options(self, mock_qs, api_client):
        mock_qs.return_value = OptionsExpiry.objects.none()
        company = Company.objects.create(symbol="AAPL")
        resp = api_client.get(self._url(company.pk))
        assert resp.data["count"] == 0


@pytest.mark.django_db
class TestOptionsChainView:
    def _url(self, pk, expiry_date):
        return f"/api/companies/{pk}/options/{expiry_date}/"

    def _make_expiry(self, company, expiry_date=date(2024, 1, 19)):
        return OptionsExpiry.objects.create(
            company=company,
            expiry_date=expiry_date,
            fetched_at=dt.now(UTC),
        )

    def test_returns_200_when_data_exists(self, api_client):
        company = Company.objects.create(symbol="AAPL")
        self._make_expiry(company)
        resp = api_client.get(self._url(company.pk, "2024-01-19"))
        assert resp.status_code == 200

    def test_returns_404_when_no_data(self, api_client):
        company = Company.objects.create(symbol="AAPL")
        resp = api_client.get(self._url(company.pk, "2024-01-19"))
        assert resp.status_code == 404

    def test_returns_calls_and_puts(self, api_client):
        company = Company.objects.create(symbol="AAPL")
        expiry = self._make_expiry(company)
        OptionsContract.objects.create(
            expiry=expiry,
            option_type=OptionsContract.OptionType.CALL,
            contract_symbol="AAPL240119C00150000",
            strike=Decimal("150.00"),
            implied_volatility=0.25,
            in_the_money=True,
        )
        OptionsContract.objects.create(
            expiry=expiry,
            option_type=OptionsContract.OptionType.PUT,
            contract_symbol="AAPL240119P00150000",
            strike=Decimal("150.00"),
            implied_volatility=0.30,
            in_the_money=False,
        )
        resp = api_client.get(self._url(company.pk, "2024-01-19"))
        assert resp.status_code == 200
        assert len(resp.data["calls"]) == 1
        assert len(resp.data["puts"]) == 1
        assert resp.data["calls"][0]["option_type"] == "call"
        assert resp.data["puts"][0]["option_type"] == "put"


# ---------------------------------------------------------------------------
# Company summary views
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCompanySummaryListView:
    def setup_method(self):
        self.company = Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        self.url = f"/api/companies/{self.company.symbol}/summaries/"

    def _make_summary(self, verdict="buy", text="Good company."):
        return CompanySummary.objects.create(
            company=self.company,
            model_name="llama3.2:3b",
            verdict=verdict,
            summary=text,
            data_snapshot={},
        )

    def test_returns_200_authenticated(self, auth_client):
        resp = auth_client.get(self.url)
        assert resp.status_code == 200

    def test_returns_401_unauthenticated(self, api_client):
        resp = api_client.get(self.url)
        assert resp.status_code == 401

    def test_returns_empty_when_no_summaries(self, auth_client):
        resp = auth_client.get(self.url)
        assert resp.data["count"] == 0
        assert resp.data["results"] == []

    def test_returns_summaries_newest_first(self, auth_client):
        s1 = self._make_summary(verdict="buy", text="first")
        s2 = self._make_summary(verdict="hold", text="second")
        resp = auth_client.get(self.url)
        ids = [r["id"] for r in resp.data["results"]]
        assert ids[0] == s2.pk
        assert ids[1] == s1.pk

    def test_returns_correct_fields(self, auth_client):
        self._make_summary()
        resp = auth_client.get(self.url)
        row = resp.data["results"][0]
        assert set(row.keys()) >= {"id", "verdict", "summary", "model_name", "generated_at"}

    def test_exposes_confidence_risks_drivers_and_snapshot(self, auth_client):
        CompanySummary.objects.create(
            company=self.company,
            model_name="qwen3:8b",
            verdict="sell",
            confidence=0.61,
            summary="Expensive versus peers.",
            key_risks=["trailing P/E 30.0 vs peer median 20.0"],
            key_drivers=["net margin 24.3% vs peer median 18.0%"],
            data_snapshot={"symbol": "AAPL", "peers": {"group": "industry"}},
        )
        row = auth_client.get(self.url).data["results"][0]
        assert row["confidence"] == 0.61
        assert row["key_risks"] == ["trailing P/E 30.0 vs peer median 20.0"]
        assert row["key_drivers"] == ["net margin 24.3% vs peer median 18.0%"]
        assert row["data_snapshot"]["peers"]["group"] == "industry"

    def test_stale_row_carries_its_reason_in_the_snapshot(self, auth_client):
        CompanySummary.objects.create(
            company=self.company,
            model_name="qwen3:8b",
            verdict="insufficient_data",
            summary="Not enough up-to-date data to form a view.",
            data_snapshot={"stale_data": ["snapshot last synced 34 days ago (limit 7 days)"]},
        )
        row = auth_client.get(self.url).data["results"][0]
        assert row["verdict"] == "insufficient_data"
        assert row["confidence"] is None
        assert row["data_snapshot"]["stale_data"] == [
            "snapshot last synced 34 days ago (limit 7 days)"
        ]

    def test_404_for_unknown_symbol(self, auth_client):
        resp = auth_client.get("/api/companies/ZZZZZ/summaries/")
        assert resp.status_code == 404


@pytest.mark.django_db
class TestCompanySummaryLatestView:
    def setup_method(self):
        self.company = Company.objects.create(symbol="MSFT", is_bootstrapped=True)
        self.url = f"/api/companies/{self.company.symbol}/summaries/latest/"

    def test_returns_404_when_no_summary(self, auth_client):
        resp = auth_client.get(self.url)
        assert resp.status_code == 404

    def test_returns_latest_summary(self, auth_client):
        CompanySummary.objects.create(
            company=self.company,
            model_name="m",
            verdict="buy",
            summary="older",
            data_snapshot={},
        )
        latest = CompanySummary.objects.create(
            company=self.company,
            model_name="m",
            verdict="hold",
            summary="newest",
            data_snapshot={},
        )
        resp = auth_client.get(self.url)
        assert resp.status_code == 200
        assert resp.data["id"] == latest.pk
        assert resp.data["verdict"] == "hold"

    def test_latest_exposes_the_new_fields(self, auth_client):
        CompanySummary.objects.create(
            company=self.company,
            model_name="m",
            verdict="buy",
            confidence=0.4,
            summary="newest",
            key_risks=["debt/equity 1.54 vs peer median 0.60"],
            key_drivers=["implied upside 25.00%"],
            data_snapshot={"symbol": "MSFT"},
        )
        resp = auth_client.get(self.url)
        assert resp.data["confidence"] == 0.4
        assert resp.data["key_risks"] == ["debt/equity 1.54 vs peer median 0.60"]
        assert resp.data["key_drivers"] == ["implied upside 25.00%"]
        assert resp.data["data_snapshot"] == {"symbol": "MSFT"}

    def test_returns_401_unauthenticated(self, api_client):
        resp = api_client.get(self.url)
        assert resp.status_code == 401

    def test_404_for_unknown_symbol(self, auth_client):
        resp = auth_client.get("/api/companies/ZZZZZ/summaries/latest/")
        assert resp.status_code == 404
