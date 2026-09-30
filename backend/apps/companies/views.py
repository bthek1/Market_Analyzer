from celery import current_app
from django.db.models import Count, Max, OuterRef, Subquery
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, status
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

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
    OptionsExpiry,
    PriceBar,
    Sector,
    ShortInterest,
)
from .serializers import (
    CompanySerializer,
    CompanySnapshotSerializer,
    CompanySummarySerializer,
    DividendSerializer,
    EarningsDateSerializer,
    FinancialStatementSerializer,
    IndustrySerializer,
    InstitutionalHolderSnapshotSerializer,
    OptionsExpiryListSerializer,
    OptionsExpirySerializer,
    PriceBarSerializer,
    SectorSerializer,
    ShortInterestSerializer,
)
from .services import (
    get_financials_pivoted,
    get_market_hierarchy,
    sync_all_for_symbol,
    sync_company_profile,
)

# ---------------------------------------------------------------------------
# Sector
# ---------------------------------------------------------------------------


class SectorListCreateView(generics.ListCreateAPIView):
    serializer_class = SectorSerializer
    permission_classes = (IsAuthenticatedOrReadOnly,)

    def get_queryset(self):
        return Sector.objects.annotate(
            company_count=Count("companies", distinct=True),
            industry_count=Count("industries", distinct=True),
        )


class SectorDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Sector.objects.all()
    serializer_class = SectorSerializer
    permission_classes = (IsAuthenticatedOrReadOnly,)


# ---------------------------------------------------------------------------
# Industry
# ---------------------------------------------------------------------------


class IndustryListCreateView(generics.ListCreateAPIView):
    serializer_class = IndustrySerializer
    permission_classes = (IsAuthenticatedOrReadOnly,)
    filter_backends = (DjangoFilterBackend, SearchFilter, OrderingFilter)
    filterset_fields = ("sector",)
    search_fields = ("name",)
    ordering_fields = ("name", "sector__name")
    ordering = ("name",)

    def get_queryset(self):
        from django.db.models import FloatField, Sum

        latest_mc_sq = (
            CompanySnapshot.objects.filter(company=OuterRef("pk"))
            .order_by("-fetched_at")
            .values("market_cap")[:1]
        )
        industry_total_mc_sq = (
            Company.objects.filter(industry=OuterRef("pk"))
            .annotate(latest_mc=Subquery(latest_mc_sq))
            .values("industry")
            .annotate(total=Sum("latest_mc"))
            .values("total")
        )
        return (
            Industry.objects.select_related("sector")
            .annotate(company_count=Count("companies"))
            .annotate(total_market_cap=Subquery(industry_total_mc_sq, output_field=FloatField()))
        )


class IndustryDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Industry.objects.select_related("sector")
    serializer_class = IndustrySerializer
    permission_classes = (IsAuthenticatedOrReadOnly,)


# ---------------------------------------------------------------------------
# Company
# ---------------------------------------------------------------------------


class CompanyListCreateView(generics.ListCreateAPIView):
    serializer_class = CompanySerializer
    permission_classes = (IsAuthenticatedOrReadOnly,)
    filter_backends = (DjangoFilterBackend, SearchFilter, OrderingFilter)
    filterset_fields = ("sector", "industry", "exchange", "is_bootstrapped")
    search_fields = ("symbol", "name")
    ordering_fields = (
        "symbol",
        "name",
        "market_cap",
        "trailing_pe",
        "profit_margins",
        "dividend_yield",
    )
    ordering = ("symbol",)

    def get_queryset(self):
        from django.db.models import FloatField

        def _latest_snapshot_sq(field: str):
            return Subquery(
                CompanySnapshot.objects.filter(company=OuterRef("pk"))
                .order_by("-fetched_at")
                .values(field)[:1],
                output_field=FloatField(),
            )

        return Company.objects.select_related("sector", "industry").annotate(
            market_cap=_latest_snapshot_sq("market_cap"),
            trailing_pe=_latest_snapshot_sq("trailing_pe"),
            profit_margins=_latest_snapshot_sq("profit_margins"),
            dividend_yield=_latest_snapshot_sq("dividend_yield"),
        )


class CompanyDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Company.objects.select_related("sector", "industry")
    serializer_class = CompanySerializer
    permission_classes = (IsAuthenticatedOrReadOnly,)


# ---------------------------------------------------------------------------
# Nested read-only data per company
# ---------------------------------------------------------------------------


class PriceBarListView(generics.ListAPIView):
    serializer_class = PriceBarSerializer
    permission_classes = (IsAuthenticatedOrReadOnly,)
    filter_backends = (OrderingFilter,)
    ordering_fields = ("date",)
    ordering = ("date",)

    def get_queryset(self):
        qs = PriceBar.objects.filter(company_id=self.kwargs["pk"])
        params = self.request.query_params
        if start := params.get("start"):
            qs = qs.filter(date__gte=start)
        if end := params.get("end"):
            qs = qs.filter(date__lte=end)
        return qs


class CompanySnapshotListView(generics.ListAPIView):
    serializer_class = CompanySnapshotSerializer
    permission_classes = (IsAuthenticatedOrReadOnly,)

    def get_queryset(self):
        return CompanySnapshot.objects.filter(company_id=self.kwargs["pk"])


class FinancialStatementListView(generics.ListAPIView):
    serializer_class = FinancialStatementSerializer
    permission_classes = (IsAuthenticatedOrReadOnly,)

    def get_queryset(self):
        qs = FinancialStatement.objects.filter(company_id=self.kwargs["pk"])
        params = self.request.query_params
        if statement_type := params.get("statement_type"):
            qs = qs.filter(statement_type=statement_type)
        if period := params.get("period"):
            qs = qs.filter(period=period)
        return qs


class DividendListView(generics.ListAPIView):
    serializer_class = DividendSerializer
    permission_classes = (IsAuthenticatedOrReadOnly,)

    def get_queryset(self):
        return Dividend.objects.filter(company_id=self.kwargs["pk"]).order_by("-date")


class ShortInterestListView(generics.ListAPIView):
    """GET /api/companies/<pk>/short-interest/ — short interest history."""

    serializer_class = ShortInterestSerializer
    permission_classes = (IsAuthenticatedOrReadOnly,)

    def get_queryset(self):
        return ShortInterest.objects.filter(company_id=self.kwargs["pk"])


class InstitutionalHoldersView(generics.RetrieveAPIView):
    """GET /api/companies/<pk>/institutional-holders/ — latest holder snapshot."""

    serializer_class = InstitutionalHolderSnapshotSerializer
    permission_classes = (IsAuthenticatedOrReadOnly,)

    def get_object(self):
        return (
            InstitutionalHolderSnapshot.objects.filter(company_id=self.kwargs["pk"])
            .order_by("-fetched_at")
            .first()
        )

    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        instance = self.get_object()
        if instance is None:
            return Response(
                {"detail": "No institutional holder data available."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(self.get_serializer(instance).data)


class EarningsDateListView(generics.ListAPIView):
    """GET /api/companies/<pk>/earnings-dates/ — earnings calendar."""

    serializer_class = EarningsDateSerializer
    permission_classes = (IsAuthenticatedOrReadOnly,)
    filter_backends = (DjangoFilterBackend, OrderingFilter)
    filterset_fields = ("is_upcoming",)
    ordering_fields = ("earnings_date",)
    ordering = ("-earnings_date",)

    def get_queryset(self):
        return EarningsDate.objects.filter(company_id=self.kwargs["pk"])


class OptionsExpiryListView(generics.ListAPIView):
    """GET /api/companies/<pk>/options/ — available expiry dates."""

    serializer_class = OptionsExpiryListSerializer
    permission_classes = (IsAuthenticatedOrReadOnly,)

    def get_queryset(self):
        return (
            OptionsExpiry.objects.filter(company_id=self.kwargs["pk"])
            .order_by("expiry_date")
            .distinct("expiry_date")
        )


class OptionsChainView(generics.RetrieveAPIView):
    """GET /api/companies/<pk>/options/<expiry_date>/ — calls + puts for an expiry."""

    serializer_class = OptionsExpirySerializer
    permission_classes = (IsAuthenticatedOrReadOnly,)

    def get_object(self):
        return (
            OptionsExpiry.objects.filter(
                company_id=self.kwargs["pk"],
                expiry_date=self.kwargs["expiry_date"],
            )
            .prefetch_related("contracts")
            .order_by("-fetched_at")
            .first()
        )

    def retrieve(self, request: Request, *args, **kwargs) -> Response:
        instance = self.get_object()
        if instance is None:
            return Response(
                {"detail": "No options data for this expiry."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(self.get_serializer(instance).data)


# ---------------------------------------------------------------------------
# Aggregation / computed endpoints
# ---------------------------------------------------------------------------


class MarketHierarchyView(APIView):
    """GET /api/companies/market-hierarchy/ -- sector->industry tree with counts."""

    permission_classes = (IsAuthenticatedOrReadOnly,)

    def get(self, request: Request) -> Response:
        metric = request.query_params.get("metric", "count")
        if metric not in ("count", "market_cap"):
            metric = "count"
        return Response(get_market_hierarchy(metric=metric))


class FinancialsPivotedView(APIView):
    """GET /api/companies/<pk>/financials/pivoted/ -- pivot table of metrics x dates."""

    permission_classes = (IsAuthenticatedOrReadOnly,)

    def get(self, request: Request, pk: int) -> Response:
        params = request.query_params
        data = get_financials_pivoted(
            company_id=pk,
            statement_type=params.get("statement_type"),
            period=params.get("period"),
        )
        return Response(data)


# ---------------------------------------------------------------------------
# yfinance sync / full ingest
# ---------------------------------------------------------------------------


_DATA_TYPE_TASKS = {
    "profile": "apps.companies.tasks.sync_profile_single",
    "prices": "apps.companies.tasks.sync_prices_single",
    "snapshot": "apps.companies.tasks.sync_snapshot_single",
    "financials": "apps.companies.tasks.sync_financials_single",
    "dividends": "apps.companies.tasks.sync_dividends_single",
    "short_interest": "apps.companies.tasks.sync_short_interest_single",
    "institutional": "apps.companies.tasks.sync_institutional_holders_single",
    "earnings": "apps.companies.tasks.sync_earnings_single",
    "options": "apps.companies.tasks.sync_options_single",
}


class CompanySyncView(APIView):
    """POST /api/companies/<pk>/sync/<data_type>/ -- fire async Celery task."""

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: int, data_type: str) -> Response:
        if data_type not in _DATA_TYPE_TASKS:
            return Response({"detail": "Unknown data type."}, status=status.HTTP_400_BAD_REQUEST)
        company = get_object_or_404(Company, pk=pk)
        task = current_app.send_task(_DATA_TYPE_TASKS[data_type], args=[company.symbol])
        return Response({"task_id": task.id, "status": "queued"}, status=status.HTTP_202_ACCEPTED)


class CompanySyncStatusView(APIView):
    """GET /api/companies/<pk>/sync-status/ -- last-fetched timestamps per data type."""

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, pk: int) -> Response:
        company = get_object_or_404(Company, pk=pk)

        def _latest(qs, field: str = "fetched_at"):
            row = qs.order_by(f"-{field}").values(field).first()
            return row[field] if row else None

        prices_max = company.prices.aggregate(last=Max("date"))["last"]

        return Response(
            {
                "profile": company.updated_at,
                "prices": prices_max,
                "snapshot": _latest(company.snapshots.all()),
                "financials": _latest(company.financials.all(), "updated_at"),
                "dividends": _latest(company.dividends.all(), "updated_at"),
                "short_interest": _latest(company.short_interest.all()),
                "institutional": _latest(company.institutional_holder_snapshots.all()),
                "earnings": _latest(company.earnings_dates.all(), "fetched_at"),
                "options": _latest(company.options_expiries.all()),
            }
        )


class YFSyncCompanyView(APIView):
    """POST /api/companies/yf/sync/<symbol>/ -- profile only."""

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, symbol: str) -> Response:
        symbol = symbol.upper()
        company = sync_company_profile(symbol)
        if company is None:
            return Response(
                {"detail": f"No yfinance data found for {symbol}."},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = CompanySerializer(company)
        return Response(serializer.data, status=status.HTTP_200_OK)


class YFIngestCompanyView(APIView):
    """POST /api/companies/yf/ingest/<symbol>/ -- full ingest."""

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, symbol: str) -> Response:
        symbol = symbol.upper()
        result = sync_all_for_symbol(symbol)
        if not result["profile"]:
            return Response(
                {"detail": f"No yfinance data found for {symbol}."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(result, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# Global sync freshness
# ---------------------------------------------------------------------------

# (label, source, value)
# source="sync_record" -> value is sync_type string, uses CompanySyncRecord.last_synced_at
# source="model"       -> value is (Model, ts_field), uses _bucket_counts_datetime
_FRESHNESS_DATA_TYPES = [
    ("Prices", "sync_record", "price"),
    ("Snapshot", "sync_record", "snapshot"),
    ("Profile", "sync_record", "profile"),
    ("Financials", "sync_record", "financials"),
    ("Dividends", "sync_record", "dividends"),
    ("Earnings", "sync_record", "earnings_dates"),
    ("Institutional", "sync_record", "institutional_holders"),
    ("Options", "sync_record", "options"),
    ("Short Interest", "sync_record", "short_interest"),
]


def _bucket_counts_sync_record(company_qs, sync_type: str, now) -> dict:
    """Bucket companies by their latest CompanySyncRecord.last_synced_at for sync_type."""
    from datetime import timedelta

    from django.db.models import Q

    latest_sub = CompanySyncRecord.objects.filter(
        company=OuterRef("pk"), sync_type=sync_type
    ).values("last_synced_at")[:1]
    annotated = company_qs.annotate(latest_ts=Subquery(latest_sub))

    t1h = now - timedelta(hours=1)
    t6h = now - timedelta(hours=6)
    t24h = now - timedelta(hours=24)
    t7d = now - timedelta(days=7)
    t30d = now - timedelta(days=30)

    return annotated.aggregate(
        lt_1h=Count("pk", filter=Q(latest_ts__gte=t1h)),
        h1_6=Count("pk", filter=Q(latest_ts__gte=t6h, latest_ts__lt=t1h)),
        h6_24=Count("pk", filter=Q(latest_ts__gte=t24h, latest_ts__lt=t6h)),
        d1_7=Count("pk", filter=Q(latest_ts__gte=t7d, latest_ts__lt=t24h)),
        d7_30=Count("pk", filter=Q(latest_ts__gte=t30d, latest_ts__lt=t7d)),
        gt_30d=Count("pk", filter=Q(latest_ts__isnull=False, latest_ts__lt=t30d)),
        never=Count("pk", filter=Q(latest_ts__isnull=True)),
    )


def _bucket_counts_datetime(company_qs, model, ts_field: str, now) -> dict:
    """Annotate companies with their latest datetime ts_field, then bucket."""
    from datetime import timedelta

    from django.db.models import Q

    latest_sub = (
        model.objects.filter(company=OuterRef("pk")).order_by(f"-{ts_field}").values(ts_field)[:1]
    )
    annotated = company_qs.annotate(latest_ts=Subquery(latest_sub))

    t1h = now - timedelta(hours=1)
    t6h = now - timedelta(hours=6)
    t24h = now - timedelta(hours=24)
    t7d = now - timedelta(days=7)
    t30d = now - timedelta(days=30)

    return annotated.aggregate(
        lt_1h=Count("pk", filter=Q(latest_ts__gte=t1h)),
        h1_6=Count("pk", filter=Q(latest_ts__gte=t6h, latest_ts__lt=t1h)),
        h6_24=Count("pk", filter=Q(latest_ts__gte=t24h, latest_ts__lt=t6h)),
        d1_7=Count("pk", filter=Q(latest_ts__gte=t7d, latest_ts__lt=t24h)),
        d7_30=Count("pk", filter=Q(latest_ts__gte=t30d, latest_ts__lt=t7d)),
        gt_30d=Count("pk", filter=Q(latest_ts__isnull=False, latest_ts__lt=t30d)),
        never=Count("pk", filter=Q(latest_ts__isnull=True)),
    )


class GlobalSyncFreshnessView(APIView):
    """GET /api/companies/sync-freshness/ -- bucket counts per data type."""

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        now = timezone.now()
        company_qs = Company.objects.all()
        total = company_qs.count()

        data_types = []
        for label, source, value in _FRESHNESS_DATA_TYPES:
            if source == "sync_record":
                buckets = _bucket_counts_sync_record(company_qs, value, now)
            else:
                model, ts_field = value
                buckets = _bucket_counts_datetime(company_qs, model, ts_field, now)
            data_types.append({"label": label, "buckets": buckets})

        return Response({"total_companies": total, "data_types": data_types})


def _bucket_index(latest_ts, now) -> int:
    """Map a timestamp to its bucket index in the aggregate bucket order (6 = never)."""
    from datetime import timedelta

    if latest_ts is None:
        return 6
    age = now - latest_ts
    if age < timedelta(hours=1):
        return 0
    if age < timedelta(hours=6):
        return 1
    if age < timedelta(hours=24):
        return 2
    if age < timedelta(days=7):
        return 3
    if age < timedelta(days=30):
        return 4
    return 5


class SyncFreshnessMatrixView(APIView):
    """GET /api/companies/sync-freshness/matrix/ -- per-company bucket per data type.

    Returns one bucket index (0-6, matching the aggregate endpoint's bucket order)
    for every (company, data type) pair, with companies in alphabetical symbol order.
    Encoded as parallel arrays to keep the payload small (~500 companies x 9 types).
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        now = timezone.now()
        symbols = list(Company.objects.order_by("symbol").values_list("symbol", flat=True))

        # One pass over every sync record; rows are unique per (company, sync_type).
        latest: dict[str, dict[str, object]] = {}
        records = CompanySyncRecord.objects.values_list(
            "company__symbol", "sync_type", "last_synced_at"
        )
        for symbol, sync_type, last_synced_at in records:
            latest.setdefault(sync_type, {})[symbol] = last_synced_at

        data_types = []
        for label, source, value in _FRESHNESS_DATA_TYPES:
            if source != "sync_record":
                continue
            by_symbol = latest.get(value, {})
            data_types.append(
                {
                    "label": label,
                    "buckets": [_bucket_index(by_symbol.get(s), now) for s in symbols],
                }
            )

        return Response(
            {
                "total_companies": len(symbols),
                "symbols": symbols,
                "data_types": data_types,
            }
        )


class GlobalSummaryFreshnessView(APIView):
    """GET /api/companies/summary-freshness/ -- AI summary generation progress."""

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        now = timezone.now()
        company_qs = Company.objects.all()
        total = company_qs.count()
        buckets = _bucket_counts_datetime(company_qs, CompanySummary, "generated_at", now)
        return Response({"total_companies": total, "buckets": buckets})


# ---------------------------------------------------------------------------
# Company summaries
# ---------------------------------------------------------------------------


class CompanySummaryListView(generics.ListAPIView):
    """GET /api/companies/{symbol}/summaries/ -- paginated summary history."""

    serializer_class = CompanySummarySerializer
    permission_classes = (IsAuthenticated,)

    def get_queryset(self):
        company = get_object_or_404(Company, symbol=self.kwargs["symbol"].upper())
        return CompanySummary.objects.filter(company=company).select_related("company")


class CompanySummaryLatestView(generics.RetrieveAPIView):
    """GET /api/companies/{symbol}/summaries/latest/ -- most recent summary."""

    serializer_class = CompanySummarySerializer
    permission_classes = (IsAuthenticated,)

    def get_object(self):
        company = get_object_or_404(Company, symbol=self.kwargs["symbol"].upper())
        summary = CompanySummary.objects.filter(company=company).first()
        if summary is None:
            from rest_framework.exceptions import NotFound

            raise NotFound("No summary available for this company.")
        return summary


class CompanySummaryGenerateView(APIView):
    """POST /api/companies/{symbol}/summaries/generate/ -- queue AI summary generation."""

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, symbol: str) -> Response:
        get_object_or_404(Company, symbol=symbol.upper())
        task = current_app.send_task(
            "apps.companies.tasks.generate_summary_single",
            args=[symbol.upper()],
        )
        return Response({"task_id": task.id, "status": "queued"}, status=status.HTTP_202_ACCEPTED)
