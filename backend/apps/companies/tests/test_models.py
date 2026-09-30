from datetime import UTC
from datetime import datetime as dt

import pytest

from apps.companies.models import (
    Company,
    CompanySnapshot,
    CompanySummary,
    CompanySyncRecord,
    Dividend,
    FinancialStatement,
    Industry,
    PriceBar,
    Sector,
)


@pytest.mark.django_db
class TestSectorModel:
    def test_str_returns_name(self):
        assert str(Sector(name="Technology")) == "Technology"

    def test_create_with_description(self):
        s = Sector.objects.create(name="Finance", description="Financial services")
        assert s.description == "Financial services"

    def test_unique_name_constraint(self):
        Sector.objects.create(name="Technology")
        with pytest.raises(Exception):
            Sector.objects.create(name="Technology")

    def test_default_ordering_is_alphabetical(self):
        Sector.objects.create(name="Technology")
        Sector.objects.create(name="Finance")
        Sector.objects.create(name="Healthcare")
        names = list(Sector.objects.values_list("name", flat=True))
        assert names == sorted(names)

    def test_auto_int_primary_key(self):
        s = Sector.objects.create(name="Energy")
        assert isinstance(s.pk, int)


@pytest.mark.django_db
class TestIndustryModel:
    def setup_method(self):
        self.sector = Sector.objects.create(name="Technology")

    def test_str_returns_name(self):
        assert str(Industry(name="Software")) == "Software"

    def test_create_with_sector(self):
        ind = Industry.objects.create(name="Software", sector=self.sector)
        assert ind.sector == self.sector

    def test_create_without_sector(self):
        ind = Industry.objects.create(name="Biotech")
        assert ind.sector is None

    def test_sector_set_null_on_sector_delete(self):
        ind = Industry.objects.create(name="Software", sector=self.sector)
        self.sector.delete()
        ind.refresh_from_db()
        assert ind.sector is None

    def test_unique_name_constraint(self):
        Industry.objects.create(name="Software")
        with pytest.raises(Exception):
            Industry.objects.create(name="Software")

    def test_default_ordering_is_alphabetical(self):
        Industry.objects.create(name="Software")
        Industry.objects.create(name="Hardware")
        Industry.objects.create(name="Networking")
        names = list(Industry.objects.values_list("name", flat=True))
        assert names == sorted(names)

    def test_sector_reverse_relation(self):
        Industry.objects.create(name="Software", sector=self.sector)
        Industry.objects.create(name="Hardware", sector=self.sector)
        assert self.sector.industries.count() == 2


@pytest.mark.django_db
class TestCompanyModel:
    def setup_method(self):
        self.sector = Sector.objects.create(name="Technology")
        self.industry = Industry.objects.create(name="Software", sector=self.sector)

    def test_str_returns_symbol(self):
        assert str(Company(symbol="AAPL")) == "AAPL"

    def test_create_with_sector_and_industry(self):
        c = Company.objects.create(symbol="AAPL", sector=self.sector, industry=self.industry)
        assert c.sector == self.sector
        assert c.industry == self.industry

    def test_create_without_fks(self):
        c = Company.objects.create(symbol="MSFT")
        assert c.sector is None
        assert c.industry is None

    def test_sector_set_null_on_sector_delete(self):
        c = Company.objects.create(symbol="AAPL", sector=self.sector)
        self.sector.delete()
        c.refresh_from_db()
        assert c.sector is None

    def test_industry_set_null_on_industry_delete(self):
        c = Company.objects.create(symbol="AAPL", industry=self.industry)
        self.industry.delete()
        c.refresh_from_db()
        assert c.industry is None

    def test_symbol_unique_constraint(self):
        Company.objects.create(symbol="AAPL")
        with pytest.raises(Exception):
            Company.objects.create(symbol="AAPL")

    def test_exchange_textchoices(self):
        c = Company.objects.create(symbol="AAPL", exchange=Company.Exchange.NASDAQ)
        c.refresh_from_db()
        assert c.exchange == "NASDAQ"
        assert c.get_exchange_display() == "NASDAQ"

    def test_currency_textchoices(self):
        c = Company.objects.create(symbol="AAPL", currency=Company.Currency.USD)
        c.refresh_from_db()
        assert c.currency == "USD"
        assert c.get_currency_display() == "US Dollar"

    def test_blank_exchange_and_currency_default(self):
        c = Company.objects.create(symbol="NEW1")
        assert c.exchange == ""
        assert c.currency == ""

    def test_default_ordering_is_alphabetical(self):
        Company.objects.create(symbol="TSLA")
        Company.objects.create(symbol="AAPL")
        Company.objects.create(symbol="MSFT")
        symbols = list(Company.objects.values_list("symbol", flat=True))
        assert symbols == sorted(symbols)

    def test_auto_int_primary_key(self):
        c = Company.objects.create(symbol="NVDA")
        assert isinstance(c.pk, int)


@pytest.mark.django_db
class TestPriceBarModel:
    def setup_method(self):
        self.company = Company.objects.create(symbol="AAPL")

    def test_unique_together_company_date(self):
        from datetime import date

        PriceBar.objects.create(
            company=self.company,
            date=date(2024, 1, 1),
            open="150.00",
            high="155.00",
            low="149.00",
            close="153.00",
            volume=1000000,
        )
        with pytest.raises(Exception):
            PriceBar.objects.create(
                company=self.company,
                date=date(2024, 1, 1),
                open="151.00",
                high="156.00",
                low="150.00",
                close="154.00",
                volume=900000,
            )

    def test_cascade_delete_with_company(self):
        from datetime import date

        PriceBar.objects.create(
            company=self.company,
            date=date(2024, 1, 2),
            open="150.00",
            high="155.00",
            low="149.00",
            close="153.00",
            volume=1000000,
        )
        self.company.delete()
        assert PriceBar.objects.count() == 0

    def test_different_companies_same_date_allowed(self):
        from datetime import date

        other = Company.objects.create(symbol="MSFT")
        PriceBar.objects.create(
            company=self.company,
            date=date(2024, 1, 3),
            open="150.00",
            high="155.00",
            low="149.00",
            close="153.00",
            volume=1000000,
        )
        PriceBar.objects.create(
            company=other,
            date=date(2024, 1, 3),
            open="300.00",
            high="310.00",
            low="295.00",
            close="305.00",
            volume=500000,
        )
        assert PriceBar.objects.count() == 2


@pytest.mark.django_db
class TestCompanySnapshotModel:
    def setup_method(self):
        self.company = Company.objects.create(symbol="AAPL")

    def test_create_with_all_nullable_fields_none(self):
        snap = CompanySnapshot.objects.create(company=self.company, raw={})
        assert snap.market_cap is None
        assert snap.trailing_pe is None
        assert snap.forward_pe is None

    def test_fetched_at_auto_populated(self):
        snap = CompanySnapshot.objects.create(company=self.company, raw={})
        assert snap.fetched_at is not None

    def test_ordering_most_recent_first(self):
        CompanySnapshot.objects.create(company=self.company, raw={})
        CompanySnapshot.objects.create(company=self.company, raw={})
        snaps = list(CompanySnapshot.objects.filter(company=self.company))
        assert snaps[0].fetched_at >= snaps[1].fetched_at

    def test_cascade_delete_with_company(self):
        CompanySnapshot.objects.create(company=self.company, raw={})
        self.company.delete()
        assert CompanySnapshot.objects.count() == 0


@pytest.mark.django_db
class TestFinancialStatementModel:
    def setup_method(self):
        self.company = Company.objects.create(symbol="AAPL")

    def test_unique_together_constraint(self):
        from datetime import date

        kwargs = dict(
            company=self.company,
            statement_type=FinancialStatement.StatementType.INCOME,
            period=FinancialStatement.Period.ANNUAL,
            period_end=date(2023, 12, 31),
            metric="Revenue",
            value=100.0,
        )
        FinancialStatement.objects.create(**kwargs)
        with pytest.raises(Exception):
            FinancialStatement.objects.create(**kwargs)

    def test_statement_type_choices(self):
        assert FinancialStatement.StatementType.INCOME == "income"
        assert FinancialStatement.StatementType.BALANCE == "balance"
        assert FinancialStatement.StatementType.CASHFLOW == "cashflow"

    def test_period_choices(self):
        assert FinancialStatement.Period.ANNUAL == "annual"
        assert FinancialStatement.Period.QUARTERLY == "quarterly"

    def test_value_nullable(self):
        from datetime import date

        fs = FinancialStatement.objects.create(
            company=self.company,
            statement_type="income",
            period="annual",
            period_end=date(2023, 12, 31),
            metric="Revenue",
            value=None,
        )
        assert fs.value is None

    def test_cascade_delete_with_company(self):
        from datetime import date

        FinancialStatement.objects.create(
            company=self.company,
            statement_type="income",
            period="annual",
            period_end=date(2023, 12, 31),
            metric="Revenue",
            value=100.0,
        )
        self.company.delete()
        assert FinancialStatement.objects.count() == 0


@pytest.mark.django_db
class TestDividendModel:
    def setup_method(self):
        self.company = Company.objects.create(symbol="AAPL")

    def test_unique_together_company_date(self):
        from datetime import date

        Dividend.objects.create(company=self.company, date=date(2024, 3, 1), amount="0.2400")
        with pytest.raises(Exception):
            Dividend.objects.create(company=self.company, date=date(2024, 3, 1), amount="0.2500")

    def test_cascade_delete_with_company(self):
        from datetime import date

        Dividend.objects.create(company=self.company, date=date(2024, 3, 2), amount="0.2400")
        self.company.delete()
        assert Dividend.objects.count() == 0

    def test_amount_stored_as_decimal(self):
        from datetime import date
        from decimal import Decimal

        div = Dividend.objects.create(company=self.company, date=date(2024, 6, 1), amount="0.2500")
        div.refresh_from_db()
        assert div.amount == Decimal("0.2500")


@pytest.mark.django_db
class TestCompanySummaryModel:
    def setup_method(self):
        self.company = Company.objects.create(symbol="MSFT")

    def test_create_summary(self):
        s = CompanySummary.objects.create(
            company=self.company,
            model_name="llama3.2:3b",
            verdict=CompanySummary.Verdict.BUY,
            summary="Strong buy.",
            data_snapshot={"key": "value"},
        )
        assert s.pk is not None
        assert s.verdict == "buy"

    def test_ordering_newest_first(self):
        CompanySummary.objects.create(
            company=self.company,
            model_name="m",
            verdict=CompanySummary.Verdict.BUY,
            summary="first",
            data_snapshot={},
        )
        CompanySummary.objects.create(
            company=self.company,
            model_name="m",
            verdict=CompanySummary.Verdict.SELL,
            summary="second",
            data_snapshot={},
        )
        latest = CompanySummary.objects.filter(company=self.company).first()
        assert latest.summary == "second"

    def test_cascade_delete_with_company(self):
        CompanySummary.objects.create(
            company=self.company,
            model_name="m",
            verdict=CompanySummary.Verdict.HOLD,
            summary="hold",
            data_snapshot={},
        )
        self.company.delete()
        assert CompanySummary.objects.count() == 0

    def test_verdict_choices(self):
        verdicts = [v.value for v in CompanySummary.Verdict]
        assert set(verdicts) == {"buy", "hold", "sell", "insufficient_data"}


@pytest.mark.django_db
class TestCompanySyncRecordModel:
    def setup_method(self):
        self.company = Company.objects.create(symbol="AAPL")

    def test_create_record(self):
        now = dt.now(UTC)
        r = CompanySyncRecord.objects.create(
            company=self.company, sync_type="price", last_synced_at=now
        )
        assert r.pk is not None
        assert r.sync_type == "price"

    def test_str(self):
        r = CompanySyncRecord(company=self.company, sync_type="snapshot")
        assert str(r) == "AAPL / snapshot"

    def test_unique_together_enforced(self):
        from django.db import IntegrityError

        now = dt.now(UTC)
        CompanySyncRecord.objects.create(
            company=self.company, sync_type="price", last_synced_at=now
        )
        with pytest.raises(IntegrityError):
            CompanySyncRecord.objects.create(
                company=self.company, sync_type="price", last_synced_at=now
            )

    def test_cascade_delete_with_company(self):
        CompanySyncRecord.objects.create(
            company=self.company, sync_type="price", last_synced_at=dt.now(UTC)
        )
        self.company.delete()
        assert CompanySyncRecord.objects.count() == 0
