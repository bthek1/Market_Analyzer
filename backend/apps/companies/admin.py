from typing import ClassVar

from django.contrib import admin

from .models import (
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


@admin.register(Sector)
class SectorAdmin(admin.ModelAdmin):
    list_display: ClassVar[list[str]] = ["name", "description"]
    search_fields: ClassVar[list[str]] = ["name"]


@admin.register(Industry)
class IndustryAdmin(admin.ModelAdmin):
    list_display: ClassVar[list[str]] = ["name", "sector"]
    list_filter: ClassVar[list[str]] = ["sector"]
    list_select_related: ClassVar[list[str]] = ["sector"]
    search_fields: ClassVar[list[str]] = ["name"]


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display: ClassVar[list[str]] = [
        "symbol",
        "name",
        "sector",
        "industry",
        "exchange",
        "currency",
    ]
    list_filter: ClassVar[list[str]] = ["sector", "industry", "exchange", "currency"]
    list_select_related: ClassVar[list[str]] = ["sector", "industry"]
    search_fields: ClassVar[list[str]] = ["symbol", "name"]
    ordering: ClassVar[list[str]] = ["symbol"]


@admin.register(PriceBar)
class PriceBarAdmin(admin.ModelAdmin):
    list_display: ClassVar[list[str]] = ["company", "date", "close", "volume"]
    list_filter: ClassVar[list[str]] = ["company"]
    list_select_related: ClassVar[list[str]] = ["company"]
    ordering: ClassVar[list[str]] = ["-date"]


@admin.register(CompanySnapshot)
class CompanySnapshotAdmin(admin.ModelAdmin):
    list_display: ClassVar[list[str]] = ["company", "fetched_at", "market_cap", "trailing_pe"]
    list_select_related: ClassVar[list[str]] = ["company"]
    ordering: ClassVar[list[str]] = ["-fetched_at"]


@admin.register(FinancialStatement)
class FinancialStatementAdmin(admin.ModelAdmin):
    list_display: ClassVar[list[str]] = [
        "company",
        "statement_type",
        "period",
        "period_end",
        "metric",
        "value",
    ]
    list_filter: ClassVar[list[str]] = ["statement_type", "period"]
    list_select_related: ClassVar[list[str]] = ["company"]


@admin.register(Dividend)
class DividendAdmin(admin.ModelAdmin):
    list_display: ClassVar[list[str]] = ["company", "date", "amount"]
    list_select_related: ClassVar[list[str]] = ["company"]
    ordering: ClassVar[list[str]] = ["-date"]


@admin.register(CompanySummary)
class CompanySummaryAdmin(admin.ModelAdmin):
    list_display: ClassVar[list[str]] = ["company", "verdict", "model_name", "generated_at"]
    list_filter: ClassVar[list[str]] = ["verdict"]
    list_select_related: ClassVar[list[str]] = ["company"]
    ordering: ClassVar[list[str]] = ["-generated_at"]
    readonly_fields: ClassVar[list[str]] = ["generated_at", "data_snapshot"]


@admin.register(CompanySyncRecord)
class CompanySyncRecordAdmin(admin.ModelAdmin):
    list_display: ClassVar[list[str]] = ["company", "sync_type", "last_synced_at"]
    list_filter: ClassVar[list[str]] = ["sync_type"]
    list_select_related: ClassVar[list[str]] = ["company"]
    ordering: ClassVar[list[str]] = ["sync_type", "last_synced_at"]
    search_fields: ClassVar[list[str]] = ["company__symbol"]


@admin.register(ShortInterest)
class ShortInterestAdmin(admin.ModelAdmin):
    list_display: ClassVar[list[str]] = [
        "company",
        "fetched_at",
        "date_short_interest",
        "shares_short",
        "short_ratio",
        "short_pct_of_float",
    ]
    list_filter: ClassVar[list[str]] = ["company"]
    list_select_related: ClassVar[list[str]] = ["company"]
    ordering: ClassVar[list[str]] = ["-fetched_at"]
    search_fields: ClassVar[list[str]] = ["company__symbol"]


@admin.register(InstitutionalHolderSnapshot)
class InstitutionalHolderSnapshotAdmin(admin.ModelAdmin):
    list_display: ClassVar[list[str]] = ["company", "fetched_at"]
    list_select_related: ClassVar[list[str]] = ["company"]
    ordering: ClassVar[list[str]] = ["-fetched_at"]
    search_fields: ClassVar[list[str]] = ["company__symbol"]
    readonly_fields: ClassVar[list[str]] = ["holders"]


@admin.register(EarningsDate)
class EarningsDateAdmin(admin.ModelAdmin):
    list_display: ClassVar[list[str]] = [
        "company",
        "earnings_date",
        "eps_estimate",
        "reported_eps",
        "surprise_pct",
        "is_upcoming",
    ]
    list_filter: ClassVar[list[str]] = ["is_upcoming"]
    list_select_related: ClassVar[list[str]] = ["company"]
    ordering: ClassVar[list[str]] = ["-earnings_date"]
    search_fields: ClassVar[list[str]] = ["company__symbol"]


@admin.register(OptionsExpiry)
class OptionsExpiryAdmin(admin.ModelAdmin):
    list_display: ClassVar[list[str]] = ["company", "expiry_date", "fetched_at"]
    list_filter: ClassVar[list[str]] = ["company"]
    list_select_related: ClassVar[list[str]] = ["company"]
    ordering: ClassVar[list[str]] = ["expiry_date"]
    search_fields: ClassVar[list[str]] = ["company__symbol"]


@admin.register(OptionsContract)
class OptionsContractAdmin(admin.ModelAdmin):
    list_display: ClassVar[list[str]] = [
        "contract_symbol",
        "expiry",
        "option_type",
        "strike",
        "last_price",
        "volume",
        "open_interest",
        "implied_volatility",
        "in_the_money",
    ]
    list_filter: ClassVar[list[str]] = ["option_type", "in_the_money"]
    list_select_related: ClassVar[list[str]] = ["expiry", "expiry__company"]
    search_fields: ClassVar[list[str]] = ["contract_symbol", "expiry__company__symbol"]
    ordering: ClassVar[list[str]] = ["expiry__expiry_date", "option_type", "strike"]
