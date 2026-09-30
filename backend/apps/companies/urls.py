from django.urls import path

from .views import (
    CompanyDetailView,
    CompanyListCreateView,
    CompanySnapshotListView,
    CompanySummaryGenerateView,
    CompanySummaryLatestView,
    CompanySummaryListView,
    CompanySyncStatusView,
    CompanySyncView,
    DividendListView,
    EarningsDateListView,
    FinancialsPivotedView,
    FinancialStatementListView,
    GlobalSummaryFreshnessView,
    GlobalSyncFreshnessView,
    IndustryDetailView,
    IndustryListCreateView,
    InstitutionalHoldersView,
    MarketHierarchyView,
    OptionsChainView,
    OptionsExpiryListView,
    PriceBarListView,
    SectorDetailView,
    SectorListCreateView,
    ShortInterestListView,
    SyncFreshnessMatrixView,
    YFIngestCompanyView,
    YFSyncCompanyView,
)

urlpatterns = [
    # Sectors
    path("sectors/", SectorListCreateView.as_view(), name="sector-list"),
    path("sectors/<int:pk>/", SectorDetailView.as_view(), name="sector-detail"),
    # Industries
    path("industries/", IndustryListCreateView.as_view(), name="industry-list"),
    path("industries/<int:pk>/", IndustryDetailView.as_view(), name="industry-detail"),
    # Aggregation / computed
    path("market-hierarchy/", MarketHierarchyView.as_view(), name="market-hierarchy"),
    path("sync-freshness/", GlobalSyncFreshnessView.as_view(), name="global-sync-freshness"),
    path(
        "sync-freshness/matrix/",
        SyncFreshnessMatrixView.as_view(),
        name="sync-freshness-matrix",
    ),
    path(
        "summary-freshness/",
        GlobalSummaryFreshnessView.as_view(),
        name="global-summary-freshness",
    ),
    # Companies
    path("", CompanyListCreateView.as_view(), name="company-list"),
    path("<int:pk>/", CompanyDetailView.as_view(), name="company-detail"),
    # Nested data per company
    path("<int:pk>/prices/", PriceBarListView.as_view(), name="company-prices"),
    path("<int:pk>/snapshots/", CompanySnapshotListView.as_view(), name="company-snapshots"),
    path("<int:pk>/financials/", FinancialStatementListView.as_view(), name="company-financials"),
    path(
        "<int:pk>/financials/pivoted/",
        FinancialsPivotedView.as_view(),
        name="company-financials-pivoted",
    ),
    path("<int:pk>/dividends/", DividendListView.as_view(), name="company-dividends"),
    path(
        "<int:pk>/short-interest/",
        ShortInterestListView.as_view(),
        name="company-short-interest",
    ),
    path(
        "<int:pk>/institutional-holders/",
        InstitutionalHoldersView.as_view(),
        name="company-institutional-holders",
    ),
    path(
        "<int:pk>/earnings-dates/",
        EarningsDateListView.as_view(),
        name="company-earnings-dates",
    ),
    path("<int:pk>/options/", OptionsExpiryListView.as_view(), name="company-options"),
    path(
        "<int:pk>/options/<str:expiry_date>/",
        OptionsChainView.as_view(),
        name="company-options-chain",
    ),
    # Per-type async sync + freshness status
    path("<int:pk>/sync-status/", CompanySyncStatusView.as_view(), name="company-sync-status"),
    path("<int:pk>/sync/<str:data_type>/", CompanySyncView.as_view(), name="company-sync"),
    # yfinance endpoints
    path("yf/sync/<str:symbol>/", YFSyncCompanyView.as_view(), name="yf-sync-company"),
    path("yf/ingest/<str:symbol>/", YFIngestCompanyView.as_view(), name="yf-ingest-company"),
    # AI summaries (by symbol)
    path(
        "<str:symbol>/summaries/",
        CompanySummaryListView.as_view(),
        name="company-summary-list",
    ),
    path(
        "<str:symbol>/summaries/latest/",
        CompanySummaryLatestView.as_view(),
        name="company-summary-latest",
    ),
    path(
        "<str:symbol>/summaries/generate/",
        CompanySummaryGenerateView.as_view(),
        name="company-summary-generate",
    ),
]
