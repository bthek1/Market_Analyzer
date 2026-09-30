from datetime import date
from decimal import Decimal

import pytest

from apps.companies.models import (
    Company,
    CompanySnapshot,
    Dividend,
    FinancialStatement,
    Industry,
    PriceBar,
    Sector,
)
from apps.companies.serializers import (
    CompanySerializer,
    CompanySnapshotSerializer,
    DividendSerializer,
    FinancialStatementSerializer,
    IndustrySerializer,
    PriceBarSerializer,
    SectorSerializer,
)


@pytest.mark.django_db
class TestSectorSerializer:
    def test_serializes_all_fields(self):
        s = Sector.objects.create(name="Technology", description="Tech companies")
        data = SectorSerializer(s).data
        assert data["name"] == "Technology"
        assert data["description"] == "Tech companies"
        assert "id" in data
        assert isinstance(data["id"], int)

    def test_deserializes_valid_data(self):
        s = SectorSerializer(data={"name": "Finance", "description": ""})
        assert s.is_valid(), s.errors
        obj = s.save()
        assert obj.name == "Finance"

    def test_rejects_missing_name(self):
        s = SectorSerializer(data={"description": "no name"})
        assert not s.is_valid()
        assert "name" in s.errors

    def test_rejects_duplicate_name(self):
        Sector.objects.create(name="Technology")
        s = SectorSerializer(data={"name": "Technology"})
        assert not s.is_valid()
        assert "name" in s.errors

    def test_description_optional(self):
        s = SectorSerializer(data={"name": "Energy"})
        assert s.is_valid(), s.errors


@pytest.mark.django_db
class TestIndustrySerializer:
    def setup_method(self):
        self.sector = Sector.objects.create(name="Technology")

    def test_serializes_sector_name(self):
        ind = Industry.objects.create(name="Software", sector=self.sector)
        data = IndustrySerializer(ind).data
        assert data["sector_name"] == "Technology"
        assert data["sector"] == self.sector.pk

    def test_sector_name_none_when_no_sector(self):
        ind = Industry.objects.create(name="Biotech")
        data = IndustrySerializer(ind).data
        assert data["sector_name"] is None

    def test_deserializes_with_sector(self):
        s = IndustrySerializer(data={"name": "Hardware", "sector": self.sector.pk})
        assert s.is_valid(), s.errors
        obj = s.save()
        assert obj.sector == self.sector

    def test_deserializes_without_sector(self):
        s = IndustrySerializer(data={"name": "Fintech"})
        assert s.is_valid(), s.errors
        obj = s.save()
        assert obj.sector is None

    def test_rejects_missing_name(self):
        s = IndustrySerializer(data={"sector": self.sector.pk})
        assert not s.is_valid()
        assert "name" in s.errors


@pytest.mark.django_db
class TestCompanySerializer:
    def setup_method(self):
        self.sector = Sector.objects.create(name="Technology")
        self.industry = Industry.objects.create(name="Software", sector=self.sector)

    def test_serializes_sector_and_industry_names(self):
        c = Company.objects.create(symbol="AAPL", sector=self.sector, industry=self.industry)
        data = CompanySerializer(c).data
        assert data["sector_name"] == "Technology"
        assert data["industry_name"] == "Software"

    def test_names_null_when_no_fks(self):
        c = Company.objects.create(symbol="MSFT")
        data = CompanySerializer(c).data
        assert data["sector_name"] is None
        assert data["industry_name"] is None

    def test_exchange_display_field(self):
        c = Company.objects.create(symbol="AAPL", exchange="NASDAQ")
        data = CompanySerializer(c).data
        assert data["exchange"] == "NASDAQ"
        assert data["exchange_display"] == "NASDAQ"

    def test_currency_display_field(self):
        c = Company.objects.create(symbol="AAPL", currency="USD")
        data = CompanySerializer(c).data
        assert data["currency"] == "USD"
        assert data["currency_display"] == "US Dollar"

    def test_all_expected_fields_present(self):
        c = Company.objects.create(symbol="AAPL")
        data = CompanySerializer(c).data
        for field in [
            "id",
            "symbol",
            "name",
            "exchange",
            "exchange_display",
            "currency",
            "currency_display",
            "sector",
            "sector_name",
            "industry",
            "industry_name",
        ]:
            assert field in data, f"Missing field: {field}"

    def test_id_is_read_only(self):
        c = Company.objects.create(symbol="AAPL")
        s = CompanySerializer(c, data={"id": 99999, "symbol": "AAPL"})
        assert s.is_valid(), s.errors
        assert "id" not in s.validated_data

    def test_deserializes_with_sector_and_industry(self):
        s = CompanySerializer(
            data={
                "symbol": "TSLA",
                "sector": self.sector.pk,
                "industry": self.industry.pk,
            }
        )
        assert s.is_valid(), s.errors
        obj = s.save()
        assert obj.sector == self.sector
        assert obj.industry == self.industry

    def test_symbol_required(self):
        s = CompanySerializer(data={"name": "No Symbol Corp"})
        assert not s.is_valid()
        assert "symbol" in s.errors

    def test_rejects_duplicate_symbol(self):
        Company.objects.create(symbol="AAPL")
        s = CompanySerializer(data={"symbol": "AAPL"})
        assert not s.is_valid()
        assert "symbol" in s.errors


@pytest.mark.django_db
class TestPriceBarSerializer:
    def setup_method(self):
        self.company = Company.objects.create(symbol="AAPL")

    def test_serializes_all_fields(self):
        bar = PriceBar.objects.create(
            company=self.company,
            date=date(2024, 1, 1),
            open="150.00",
            high="155.00",
            low="149.00",
            close="153.00",
            volume=1000000,
        )
        data = PriceBarSerializer(bar).data
        assert data["date"] == "2024-01-01"
        assert Decimal(data["close"]) == Decimal("153.00")
        assert data["volume"] == 1000000

    def test_id_is_read_only(self):
        s = PriceBarSerializer(
            data={
                "id": 99,
                "company": self.company.pk,
                "date": "2024-01-01",
                "open": "150.00",
                "high": "155.00",
                "low": "149.00",
                "close": "153.00",
                "volume": 1000000,
            }
        )
        assert s.is_valid(), s.errors
        assert "id" not in s.validated_data


@pytest.mark.django_db
class TestCompanySnapshotSerializer:
    def setup_method(self):
        self.company = Company.objects.create(symbol="AAPL")

    def test_serializes_snapshot(self):
        snap = CompanySnapshot.objects.create(
            company=self.company,
            market_cap=3_000_000_000_000,
            trailing_pe=28.5,
            raw={"symbol": "AAPL"},
        )
        data = CompanySnapshotSerializer(snap).data
        assert data["market_cap"] == 3_000_000_000_000
        assert data["trailing_pe"] == 28.5
        assert "fetched_at" in data

    def test_fetched_at_read_only(self):
        snap = CompanySnapshot.objects.create(company=self.company, raw={})
        s = CompanySnapshotSerializer(
            snap, data={"company": self.company.pk, "fetched_at": "2020-01-01T00:00:00Z", "raw": {}}
        )
        assert s.is_valid(), s.errors
        assert "fetched_at" not in s.validated_data

    def test_nullable_fields_serialized_as_null(self):
        snap = CompanySnapshot.objects.create(company=self.company, raw={})
        data = CompanySnapshotSerializer(snap).data
        assert data["market_cap"] is None
        assert data["trailing_pe"] is None


@pytest.mark.django_db
class TestFinancialStatementSerializer:
    def setup_method(self):
        self.company = Company.objects.create(symbol="AAPL")

    def test_serializes_all_fields(self):
        fs = FinancialStatement.objects.create(
            company=self.company,
            statement_type="income",
            period="annual",
            period_end=date(2023, 12, 31),
            metric="Revenue",
            value=383285000000.0,
        )
        data = FinancialStatementSerializer(fs).data
        assert data["statement_type"] == "income"
        assert data["period"] == "annual"
        assert data["metric"] == "Revenue"
        assert data["value"] == 383285000000.0

    def test_id_is_read_only(self):
        s = FinancialStatementSerializer(
            data={
                "id": 99,
                "company": self.company.pk,
                "statement_type": "income",
                "period": "annual",
                "period_end": "2023-12-31",
                "metric": "Revenue",
                "value": 100.0,
            }
        )
        assert s.is_valid(), s.errors
        assert "id" not in s.validated_data


@pytest.mark.django_db
class TestDividendSerializer:
    def setup_method(self):
        self.company = Company.objects.create(symbol="AAPL")

    def test_serializes_all_fields(self):
        div = Dividend.objects.create(company=self.company, date=date(2024, 3, 1), amount="0.2400")
        data = DividendSerializer(div).data
        assert data["date"] == "2024-03-01"
        assert Decimal(data["amount"]) == Decimal("0.2400")

    def test_id_is_read_only(self):
        s = DividendSerializer(
            data={
                "id": 99,
                "company": self.company.pk,
                "date": "2024-03-01",
                "amount": "0.2400",
            }
        )
        assert s.is_valid(), s.errors
        assert "id" not in s.validated_data


@pytest.mark.django_db
class TestCompanySummarySerializer:
    def setup_method(self):
        self.company = Company.objects.create(symbol="AAPL")

    def _summary(self, **kwargs):
        from apps.companies.models import CompanySummary

        defaults = {
            "company": self.company,
            "model_name": "qwen3:8b",
            "verdict": "buy",
            "confidence": 0.8,
            "summary": "Prose.",
            "key_risks": ["P/E 30 vs peer median 20"],
            "key_drivers": ["ROE 150% vs peer median 22%"],
            "data_snapshot": {"symbol": "AAPL"},
        }
        defaults.update(kwargs)
        return CompanySummary.objects.create(**defaults)

    def test_legacy_fields_unchanged(self):
        from apps.companies.serializers import CompanySummarySerializer

        data = CompanySummarySerializer(self._summary()).data
        for key in ("id", "generated_at", "model_name", "verdict", "summary"):
            assert key in data
        assert data["verdict"] == "buy"

    def test_new_fields_exposed(self):
        from apps.companies.serializers import CompanySummarySerializer

        data = CompanySummarySerializer(self._summary()).data
        assert data["confidence"] == 0.8
        assert data["key_risks"] == ["P/E 30 vs peer median 20"]
        assert data["key_drivers"] == ["ROE 150% vs peer median 22%"]
        assert data["data_snapshot"] == {"symbol": "AAPL"}

    def test_old_style_row_without_confidence_serializes(self):
        from apps.companies.serializers import CompanySummarySerializer

        data = CompanySummarySerializer(self._summary(confidence=None)).data
        assert data["confidence"] is None
        assert data["key_risks"] == ["P/E 30 vs peer median 20"]
