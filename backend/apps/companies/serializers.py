from rest_framework import serializers

from .models import (
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


class SectorSerializer(serializers.ModelSerializer):
    company_count = serializers.IntegerField(read_only=True, default=0)
    industry_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Sector
        fields = ("id", "name", "description", "company_count", "industry_count")
        read_only_fields = ("id", "company_count", "industry_count")


class IndustrySerializer(serializers.ModelSerializer):
    sector_name = serializers.SerializerMethodField()
    company_count = serializers.IntegerField(read_only=True, default=0)
    total_market_cap = serializers.FloatField(read_only=True, default=None, allow_null=True)

    def get_sector_name(self, obj: Industry) -> str | None:
        return obj.sector.name if obj.sector else None

    class Meta:
        model = Industry
        fields = ("id", "name", "sector", "sector_name", "company_count", "total_market_cap")
        read_only_fields = ("id", "sector_name", "company_count", "total_market_cap")


class CompanySerializer(serializers.ModelSerializer):
    sector_name = serializers.SerializerMethodField()
    industry_name = serializers.SerializerMethodField()
    exchange_display = serializers.SerializerMethodField()
    currency_display = serializers.SerializerMethodField()
    market_cap = serializers.FloatField(read_only=True, allow_null=True, default=None)
    trailing_pe = serializers.FloatField(read_only=True, allow_null=True, default=None)
    profit_margins = serializers.FloatField(read_only=True, allow_null=True, default=None)
    dividend_yield = serializers.FloatField(read_only=True, allow_null=True, default=None)

    def get_sector_name(self, obj: Company) -> str | None:
        return obj.sector.name if obj.sector else None

    def get_industry_name(self, obj: Company) -> str | None:
        return obj.industry.name if obj.industry else None

    def get_exchange_display(self, obj: Company) -> str:
        return obj.get_exchange_display()

    def get_currency_display(self, obj: Company) -> str:
        return obj.get_currency_display()

    class Meta:
        model = Company
        fields = (
            "id",
            "symbol",
            "name",
            "exchange",
            "exchange_display",
            "currency",
            "currency_display",
            "is_bootstrapped",
            "sector",
            "sector_name",
            "industry",
            "industry_name",
            "market_cap",
            "trailing_pe",
            "profit_margins",
            "dividend_yield",
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
        )
        read_only_fields = (
            "id",
            "sector_name",
            "industry_name",
            "exchange_display",
            "currency_display",
            "market_cap",
            "trailing_pe",
            "profit_margins",
            "dividend_yield",
        )


class PriceBarSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceBar
        fields = ("id", "company", "date", "open", "high", "low", "close", "volume")
        read_only_fields = ("id",)


class CompanySnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanySnapshot
        fields = (
            "id",
            "company",
            "fetched_at",
            # Original fields
            "market_cap",
            "trailing_pe",
            "forward_pe",
            "price_to_book",
            "debt_to_equity",
            "return_on_equity",
            "profit_margins",
            "dividend_yield",
            "trailing_eps",
            "forward_eps",
            # Valuation extensions
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
            # Technical
            "fifty_day_average",
            "two_hundred_day_average",
            # Growth
            "revenue_growth",
            "earnings_growth",
            "earnings_quarterly_growth",
            # Margins
            "gross_margins",
            "operating_margins",
            "ebitda_margins",
            # Liquidity
            "current_ratio",
            "quick_ratio",
            # Profitability
            "return_on_assets",
            "ebitda",
            "total_cash",
            "total_cash_per_share",
            "free_cashflow",
            "operating_cashflow",
            "net_income_to_common",
            "revenue_per_share",
            # Ownership
            "held_pct_institutions",
            "held_pct_insiders",
            # Dividend snapshot
            "dividend_rate",
            "ex_dividend_date",
            "five_year_avg_dividend_yield",
            "trailing_annual_dividend_rate",
            "last_dividend_value",
            "last_dividend_date",
            # Fiscal calendar
            "last_fiscal_year_end",
            "next_fiscal_year_end",
            "most_recent_quarter",
            # Governance risk
            "audit_risk",
            "board_risk",
            "compensation_risk",
            "shareholder_rights_risk",
            "overall_risk",
            # Analyst consensus
            "recommendation_mean",
            "recommendation_key",
            "num_analyst_opinions",
            "target_high_price",
            "target_low_price",
            "target_mean_price",
            "target_median_price",
            "recommendations_breakdown",
            # Split history
            "last_split_factor",
            "last_split_date",
            "raw",
        )
        read_only_fields = ("id", "fetched_at")


class FinancialStatementSerializer(serializers.ModelSerializer):
    class Meta:
        model = FinancialStatement
        fields = ("id", "company", "statement_type", "period", "period_end", "metric", "value")
        read_only_fields = ("id",)


class DividendSerializer(serializers.ModelSerializer):
    class Meta:
        model = Dividend
        fields = ("id", "company", "date", "amount")
        read_only_fields = ("id",)


class ShortInterestSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShortInterest
        fields = (
            "id",
            "company",
            "fetched_at",
            "date_short_interest",
            "shares_short",
            "shares_short_prior_month",
            "short_ratio",
            "short_pct_of_float",
            "shares_pct_shares_out",
        )
        read_only_fields = ("id", "fetched_at")


class InstitutionalHolderSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = InstitutionalHolderSnapshot
        fields = ("id", "company", "fetched_at", "holders")
        read_only_fields = ("id", "fetched_at")


class EarningsDateSerializer(serializers.ModelSerializer):
    class Meta:
        model = EarningsDate
        fields = (
            "id",
            "company",
            "earnings_date",
            "eps_estimate",
            "reported_eps",
            "surprise_pct",
            "is_upcoming",
        )
        read_only_fields = ("id",)


class OptionsContractSerializer(serializers.ModelSerializer):
    class Meta:
        model = OptionsContract
        fields = (
            "id",
            "option_type",
            "contract_symbol",
            "strike",
            "last_price",
            "bid",
            "ask",
            "volume",
            "open_interest",
            "implied_volatility",
            "in_the_money",
        )
        read_only_fields = ("id",)


class OptionsExpirySerializer(serializers.ModelSerializer):
    calls = serializers.SerializerMethodField()
    puts = serializers.SerializerMethodField()

    def get_calls(self, obj: OptionsExpiry) -> list:
        qs = obj.contracts.filter(option_type=OptionsContract.OptionType.CALL).order_by("strike")
        return OptionsContractSerializer(qs, many=True).data

    def get_puts(self, obj: OptionsExpiry) -> list:
        qs = obj.contracts.filter(option_type=OptionsContract.OptionType.PUT).order_by("strike")
        return OptionsContractSerializer(qs, many=True).data

    class Meta:
        model = OptionsExpiry
        fields = ("id", "company", "expiry_date", "fetched_at", "calls", "puts")
        read_only_fields = ("id", "fetched_at")


class OptionsExpiryListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for the expiry list endpoint (no contracts)."""

    class Meta:
        model = OptionsExpiry
        fields = ("id", "expiry_date", "fetched_at")
        read_only_fields = ("id", "fetched_at")


class CompanySummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanySummary
        # Additive only: every pre-existing key stays, so the frontend contract holds.
        fields = (
            "id",
            "generated_at",
            "model_name",
            "verdict",
            "confidence",
            "summary",
            "key_risks",
            "key_drivers",
            "data_snapshot",
        )
        read_only_fields = ("id", "generated_at")
