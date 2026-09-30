from datetime import UTC, date, timedelta
from datetime import datetime as dt
from unittest.mock import MagicMock, patch

import pytest

from apps.companies.models import (
    Company,
    CompanySnapshot,
    CompanySummary,
    CompanySyncRecord,
    Dividend,
    EarningsDate,
    PriceBar,
)

# ---------------------------------------------------------------------------
# CompanySyncView
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCompanySyncView:
    def _url(self, pk: int, data_type: str) -> str:
        return f"/api/companies/{pk}/sync/{data_type}/"

    def test_unauthenticated_returns_401(self, api_client):
        company = Company.objects.create(symbol="AAPL")
        resp = api_client.post(self._url(company.pk, "dividends"))
        assert resp.status_code == 401

    def test_unknown_data_type_returns_400(self, auth_client):
        company = Company.objects.create(symbol="AAPL")
        resp = auth_client.post(self._url(company.pk, "nonexistent"))
        assert resp.status_code == 400

    def test_missing_company_returns_404(self, auth_client):
        resp = auth_client.post(self._url(999999, "dividends"))
        assert resp.status_code == 404

    @patch("apps.companies.views.current_app")
    def test_valid_request_returns_202_with_task_id(self, mock_app, auth_client):
        company = Company.objects.create(symbol="AAPL")
        mock_task = MagicMock()
        mock_task.id = "test-task-uuid-1234"
        mock_app.send_task.return_value = mock_task

        resp = auth_client.post(self._url(company.pk, "dividends"))

        assert resp.status_code == 202
        assert resp.data["task_id"] == "test-task-uuid-1234"
        assert resp.data["status"] == "queued"

    @patch("apps.companies.views.current_app")
    def test_dispatches_correct_task_for_each_type(self, mock_app, auth_client):
        company = Company.objects.create(symbol="AAPL")
        mock_task = MagicMock()
        mock_task.id = "task-x"
        mock_app.send_task.return_value = mock_task

        data_types = [
            "profile",
            "prices",
            "snapshot",
            "financials",
            "dividends",
            "short_interest",
            "institutional",
            "earnings",
            "options",
        ]
        for dt_key in data_types:
            resp = auth_client.post(self._url(company.pk, dt_key))
            assert resp.status_code == 202, f"Expected 202 for {dt_key}, got {resp.status_code}"


# ---------------------------------------------------------------------------
# CompanySyncStatusView
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCompanySyncStatusView:
    def _url(self, pk: int) -> str:
        return f"/api/companies/{pk}/sync-status/"

    def test_unauthenticated_returns_401(self, api_client):
        company = Company.objects.create(symbol="AAPL")
        resp = api_client.get(self._url(company.pk))
        assert resp.status_code == 401

    def test_missing_company_returns_404(self, auth_client):
        resp = auth_client.get(self._url(999999))
        assert resp.status_code == 404

    def test_all_keys_present_when_no_data(self, auth_client):
        company = Company.objects.create(symbol="AAPL")
        resp = auth_client.get(self._url(company.pk))
        assert resp.status_code == 200
        expected_keys = {
            "profile",
            "prices",
            "snapshot",
            "financials",
            "dividends",
            "short_interest",
            "institutional",
            "earnings",
            "options",
        }
        assert set(resp.data.keys()) == expected_keys

    def test_null_when_no_data(self, auth_client):
        company = Company.objects.create(symbol="AAPL")
        resp = auth_client.get(self._url(company.pk))
        assert resp.data["prices"] is None
        assert resp.data["snapshot"] is None
        assert resp.data["dividends"] is None

    def test_profile_returns_company_updated_at(self, auth_client):
        company = Company.objects.create(symbol="AAPL")
        resp = auth_client.get(self._url(company.pk))
        assert resp.data["profile"] is not None

    def test_prices_returns_max_date(self, auth_client):
        company = Company.objects.create(symbol="AAPL")
        PriceBar.objects.create(
            company=company,
            date=date(2026, 5, 1),
            open=100,
            high=105,
            low=99,
            close=103,
            volume=1000000,
        )
        PriceBar.objects.create(
            company=company,
            date=date(2026, 6, 1),
            open=105,
            high=110,
            low=104,
            close=109,
            volume=1100000,
        )
        resp = auth_client.get(self._url(company.pk))
        assert str(resp.data["prices"]) == "2026-06-01"

    def test_snapshot_returns_latest_fetched_at(self, auth_client):
        company = Company.objects.create(symbol="AAPL")
        CompanySnapshot.objects.create(company=company, raw={})
        resp = auth_client.get(self._url(company.pk))
        assert resp.data["snapshot"] is not None

    def test_dividends_returns_latest_updated_at(self, auth_client):
        company = Company.objects.create(symbol="AAPL")
        Dividend.objects.create(company=company, date=date(2026, 3, 1), amount="0.25")
        resp = auth_client.get(self._url(company.pk))
        assert resp.data["dividends"] is not None

    def test_earnings_returns_latest_fetched_at(self, auth_client):
        company = Company.objects.create(symbol="AAPL")
        older = dt(2026, 5, 1, tzinfo=UTC)
        newer = dt(2026, 6, 1, tzinfo=UTC)
        EarningsDate.objects.create(
            company=company,
            earnings_date=date(2026, 5, 1),
            fetched_at=older,
        )
        EarningsDate.objects.create(
            company=company,
            earnings_date=date(2026, 8, 1),
            fetched_at=newer,
        )
        resp = auth_client.get(self._url(company.pk))
        assert resp.data["earnings"] is not None
        # Returns the most recently fetched timestamp, not the max earnings_date (which could be future)
        assert resp.data["earnings"].date() == date(2026, 6, 1)

    def test_earnings_null_when_no_data(self, auth_client):
        company = Company.objects.create(symbol="AAPL")
        resp = auth_client.get(self._url(company.pk))
        assert resp.data["earnings"] is None

    def test_earnings_future_event_date_not_returned(self, auth_client):
        # Upcoming earnings in the future: fetched_at is now, earnings_date is future
        company = Company.objects.create(symbol="AAPL")
        EarningsDate.objects.create(
            company=company,
            earnings_date=date(2026, 9, 1),
            is_upcoming=True,
            fetched_at=dt(2026, 6, 2, tzinfo=UTC),
        )
        resp = auth_client.get(self._url(company.pk))
        # Must NOT return a future date string like "2026-09-01"
        assert "2026-09" not in str(resp.data["earnings"])


# ---------------------------------------------------------------------------
# GlobalSyncFreshnessView
# ---------------------------------------------------------------------------

_FRESHNESS_URL = "/api/companies/sync-freshness/"
_EXPECTED_LABELS = [
    "Prices",
    "Snapshot",
    "Profile",
    "Financials",
    "Dividends",
    "Earnings",
    "Institutional",
    "Options",
    "Short Interest",
]


@pytest.mark.django_db
class TestGlobalSyncFreshnessView:
    def test_unauthenticated_returns_401(self, api_client):
        resp = api_client.get(_FRESHNESS_URL)
        assert resp.status_code == 401

    def test_no_companies_returns_zeros(self, auth_client):
        resp = auth_client.get(_FRESHNESS_URL)
        assert resp.status_code == 200
        assert resp.data["total_companies"] == 0
        for dt_entry in resp.data["data_types"]:
            for v in dt_entry["buckets"].values():
                assert v == 0

    def test_all_labels_present_in_order(self, auth_client):
        resp = auth_client.get(_FRESHNESS_URL)
        assert resp.status_code == 200
        labels = [d["label"] for d in resp.data["data_types"]]
        assert labels == _EXPECTED_LABELS

    def test_buckets_keys_present(self, auth_client):
        resp = auth_client.get(_FRESHNESS_URL)
        expected_keys = {"lt_1h", "h1_6", "h6_24", "d1_7", "d7_30", "gt_30d", "never"}
        for dt_entry in resp.data["data_types"]:
            assert set(dt_entry["buckets"].keys()) == expected_keys

    def test_never_bucket_counts_companies_without_records(self, auth_client):
        Company.objects.create(symbol="AAPL")
        Company.objects.create(symbol="MSFT")
        resp = auth_client.get(_FRESHNESS_URL)
        assert resp.status_code == 200
        snapshot_entry = next(d for d in resp.data["data_types"] if d["label"] == "Snapshot")
        assert snapshot_entry["buckets"]["never"] == 2

    def test_recent_snapshot_lands_in_lt_1h(self, auth_client):
        company = Company.objects.create(symbol="AAPL")
        CompanySyncRecord.objects.create(
            company=company,
            sync_type="snapshot",
            last_synced_at=dt.now(UTC) - timedelta(minutes=10),
        )
        resp = auth_client.get(_FRESHNESS_URL)
        snapshot_entry = next(d for d in resp.data["data_types"] if d["label"] == "Snapshot")
        assert snapshot_entry["buckets"]["lt_1h"] == 1
        assert snapshot_entry["buckets"]["never"] == 0

    def test_old_snapshot_lands_in_gt_30d(self, auth_client):
        company = Company.objects.create(symbol="AAPL")
        CompanySyncRecord.objects.create(
            company=company,
            sync_type="snapshot",
            last_synced_at=dt.now(UTC) - timedelta(days=60),
        )
        resp = auth_client.get(_FRESHNESS_URL)
        snapshot_entry = next(d for d in resp.data["data_types"] if d["label"] == "Snapshot")
        assert snapshot_entry["buckets"]["gt_30d"] == 1

    def test_prices_today_lands_in_lt_1h_bucket(self, auth_client):
        company = Company.objects.create(symbol="AAPL")
        CompanySyncRecord.objects.create(
            company=company,
            sync_type="price",
            last_synced_at=dt.now(UTC) - timedelta(minutes=10),
        )
        resp = auth_client.get(_FRESHNESS_URL)
        prices_entry = next(d for d in resp.data["data_types"] if d["label"] == "Prices")
        assert prices_entry["buckets"]["lt_1h"] == 1

    def test_total_companies_matches_db_count(self, auth_client):
        Company.objects.create(symbol="AAPL")
        Company.objects.create(symbol="GOOGL")
        Company.objects.create(symbol="MSFT")
        resp = auth_client.get(_FRESHNESS_URL)
        assert resp.data["total_companies"] == 3

    def test_snapshot_h1_6_bucket(self, auth_client):
        company = Company.objects.create(symbol="AAPL")
        CompanySyncRecord.objects.create(
            company=company,
            sync_type="snapshot",
            last_synced_at=dt.now(UTC) - timedelta(hours=3),
        )
        resp = auth_client.get(_FRESHNESS_URL)
        entry = next(d for d in resp.data["data_types"] if d["label"] == "Snapshot")
        assert entry["buckets"]["h1_6"] == 1
        assert entry["buckets"]["lt_1h"] == 0

    def test_snapshot_h6_24_bucket(self, auth_client):
        company = Company.objects.create(symbol="AAPL")
        CompanySyncRecord.objects.create(
            company=company,
            sync_type="snapshot",
            last_synced_at=dt.now(UTC) - timedelta(hours=12),
        )
        resp = auth_client.get(_FRESHNESS_URL)
        entry = next(d for d in resp.data["data_types"] if d["label"] == "Snapshot")
        assert entry["buckets"]["h6_24"] == 1

    def test_snapshot_d1_7_bucket(self, auth_client):
        company = Company.objects.create(symbol="AAPL")
        CompanySyncRecord.objects.create(
            company=company,
            sync_type="snapshot",
            last_synced_at=dt.now(UTC) - timedelta(days=3),
        )
        resp = auth_client.get(_FRESHNESS_URL)
        entry = next(d for d in resp.data["data_types"] if d["label"] == "Snapshot")
        assert entry["buckets"]["d1_7"] == 1

    def test_snapshot_d7_30_bucket(self, auth_client):
        company = Company.objects.create(symbol="AAPL")
        CompanySyncRecord.objects.create(
            company=company,
            sync_type="snapshot",
            last_synced_at=dt.now(UTC) - timedelta(days=14),
        )
        resp = auth_client.get(_FRESHNESS_URL)
        entry = next(d for d in resp.data["data_types"] if d["label"] == "Snapshot")
        assert entry["buckets"]["d7_30"] == 1

    def test_bucket_counts_sum_to_total_companies(self, auth_client):
        offsets = [
            timedelta(minutes=30),
            timedelta(hours=3),
            timedelta(hours=18),
            timedelta(days=14),
            timedelta(days=60),
        ]
        for i, offset in enumerate(offsets):
            c = Company.objects.create(symbol=f"T{i:03d}")
            CompanySyncRecord.objects.create(
                company=c,
                sync_type="snapshot",
                last_synced_at=dt.now(UTC) - offset,
            )
        # 2 more companies with no sync record (never)
        Company.objects.create(symbol="NO1")
        Company.objects.create(symbol="NO2")
        resp = auth_client.get(_FRESHNESS_URL)
        assert resp.data["total_companies"] == 7
        entry = next(d for d in resp.data["data_types"] if d["label"] == "Snapshot")
        bucket_sum = sum(entry["buckets"].values())
        assert bucket_sum == 7

    def test_prices_old_lands_in_d1_7(self, auth_client):
        company = Company.objects.create(symbol="AAPL")
        CompanySyncRecord.objects.create(
            company=company,
            sync_type="price",
            last_synced_at=dt.now(UTC) - timedelta(days=3),
        )
        resp = auth_client.get(_FRESHNESS_URL)
        entry = next(d for d in resp.data["data_types"] if d["label"] == "Prices")
        assert entry["buckets"]["d1_7"] == 1

    def test_prices_very_old_lands_in_gt_30d(self, auth_client):
        company = Company.objects.create(symbol="AAPL")
        CompanySyncRecord.objects.create(
            company=company,
            sync_type="price",
            last_synced_at=dt.now(UTC) - timedelta(days=60),
        )
        resp = auth_client.get(_FRESHNESS_URL)
        entry = next(d for d in resp.data["data_types"] if d["label"] == "Prices")
        assert entry["buckets"]["gt_30d"] == 1

    def test_prices_never_when_no_sync_record(self, auth_client):
        Company.objects.create(symbol="AAPL")
        resp = auth_client.get(_FRESHNESS_URL)
        entry = next(d for d in resp.data["data_types"] if d["label"] == "Prices")
        assert entry["buckets"]["never"] == 1

    def test_multiple_companies_counted_independently_per_data_type(self, auth_client):
        c1 = Company.objects.create(symbol="AAPL")
        Company.objects.create(symbol="MSFT")
        CompanySyncRecord.objects.create(
            company=c1,
            sync_type="snapshot",
            last_synced_at=dt.now(UTC) - timedelta(minutes=5),
        )
        # MSFT has no sync record
        resp = auth_client.get(_FRESHNESS_URL)
        entry = next(d for d in resp.data["data_types"] if d["label"] == "Snapshot")
        assert entry["buckets"]["lt_1h"] == 1
        assert entry["buckets"]["never"] == 1

    def test_profile_sync_record_lands_in_correct_bucket(self, auth_client):
        company = Company.objects.create(symbol="AAPL")
        CompanySyncRecord.objects.create(
            company=company,
            sync_type="profile",
            last_synced_at=dt.now(UTC) - timedelta(minutes=10),
        )
        resp = auth_client.get(_FRESHNESS_URL)
        entry = next(d for d in resp.data["data_types"] if d["label"] == "Profile")
        assert entry["buckets"]["lt_1h"] == 1

    def test_short_interest_never_when_no_sync_record(self, auth_client):
        Company.objects.create(symbol="AAPL")
        resp = auth_client.get(_FRESHNESS_URL)
        entry = next(d for d in resp.data["data_types"] if d["label"] == "Short Interest")
        assert entry["buckets"]["never"] == 1

    def test_short_interest_recent_lands_in_lt_1h(self, auth_client):
        company = Company.objects.create(symbol="AAPL")
        CompanySyncRecord.objects.create(
            company=company,
            sync_type="short_interest",
            last_synced_at=dt.now(UTC) - timedelta(minutes=20),
        )
        resp = auth_client.get(_FRESHNESS_URL)
        entry = next(d for d in resp.data["data_types"] if d["label"] == "Short Interest")
        assert entry["buckets"]["lt_1h"] == 1
        assert entry["buckets"]["never"] == 0

    def test_short_interest_old_lands_in_gt_30d(self, auth_client):
        company = Company.objects.create(symbol="AAPL")
        CompanySyncRecord.objects.create(
            company=company,
            sync_type="short_interest",
            last_synced_at=dt.now(UTC) - timedelta(days=45),
        )
        resp = auth_client.get(_FRESHNESS_URL)
        entry = next(d for d in resp.data["data_types"] if d["label"] == "Short Interest")
        assert entry["buckets"]["gt_30d"] == 1
        assert entry["buckets"]["never"] == 0


# ---------------------------------------------------------------------------
# GlobalSummaryFreshnessView
# ---------------------------------------------------------------------------

_SUMMARY_FRESHNESS_URL = "/api/companies/summary-freshness/"
_BUCKET_KEYS = {"lt_1h", "h1_6", "h6_24", "d1_7", "d7_30", "gt_30d", "never"}


@pytest.mark.django_db
class TestGlobalSummaryFreshnessView:
    def test_unauthenticated_returns_401(self, api_client):
        resp = api_client.get(_SUMMARY_FRESHNESS_URL)
        assert resp.status_code == 401

    def test_no_companies_returns_zeros(self, auth_client):
        resp = auth_client.get(_SUMMARY_FRESHNESS_URL)
        assert resp.status_code == 200
        assert resp.data["total_companies"] == 0
        for v in resp.data["buckets"].values():
            assert v == 0

    def test_response_shape(self, auth_client):
        resp = auth_client.get(_SUMMARY_FRESHNESS_URL)
        assert resp.status_code == 200
        assert "total_companies" in resp.data
        assert set(resp.data["buckets"].keys()) == _BUCKET_KEYS

    def test_never_bucket_counts_companies_without_summary(self, auth_client):
        Company.objects.create(symbol="AAPL")
        Company.objects.create(symbol="MSFT")
        resp = auth_client.get(_SUMMARY_FRESHNESS_URL)
        assert resp.data["buckets"]["never"] == 2

    def test_recent_summary_lands_in_lt_1h(self, auth_client):
        company = Company.objects.create(symbol="AAPL")
        summary = CompanySummary.objects.create(
            company=company,
            model_name="test",
            verdict="hold",
            summary="test summary",
            data_snapshot={},
        )
        CompanySummary.objects.filter(pk=summary.pk).update(
            generated_at=dt.now(UTC) - timedelta(minutes=10)
        )
        resp = auth_client.get(_SUMMARY_FRESHNESS_URL)
        assert resp.data["buckets"]["lt_1h"] == 1
        assert resp.data["buckets"]["never"] == 0

    def test_old_summary_lands_in_gt_30d(self, auth_client):
        company = Company.objects.create(symbol="AAPL")
        summary = CompanySummary.objects.create(
            company=company,
            model_name="test",
            verdict="hold",
            summary="test summary",
            data_snapshot={},
        )
        CompanySummary.objects.filter(pk=summary.pk).update(
            generated_at=dt.now(UTC) - timedelta(days=60)
        )
        resp = auth_client.get(_SUMMARY_FRESHNESS_URL)
        assert resp.data["buckets"]["gt_30d"] == 1

    def test_bucket_counts_sum_to_total_companies(self, auth_client):
        Company.objects.create(symbol="NO1")
        Company.objects.create(symbol="NO2")
        c3 = Company.objects.create(symbol="HAS")
        summary = CompanySummary.objects.create(
            company=c3,
            model_name="test",
            verdict="buy",
            summary="good",
            data_snapshot={},
        )
        CompanySummary.objects.filter(pk=summary.pk).update(
            generated_at=dt.now(UTC) - timedelta(minutes=5)
        )
        resp = auth_client.get(_SUMMARY_FRESHNESS_URL)
        assert resp.data["total_companies"] == 3
        assert sum(resp.data["buckets"].values()) == 3

    def test_sync_freshness_no_longer_contains_summary_label(self, auth_client):
        resp = auth_client.get(_FRESHNESS_URL)
        assert resp.status_code == 200
        labels = [d["label"] for d in resp.data["data_types"]]
        assert "Summary" not in labels


# ---------------------------------------------------------------------------
# CompanySummaryGenerateView
# ---------------------------------------------------------------------------

_GENERATE_URL = "/api/companies/{symbol}/summaries/generate/"


@pytest.mark.django_db
class TestCompanySummaryGenerateView:
    def test_unauthenticated_returns_401(self, api_client):
        Company.objects.create(symbol="AAPL")
        resp = api_client.post(_GENERATE_URL.format(symbol="AAPL"))
        assert resp.status_code == 401

    def test_unknown_symbol_returns_404(self, auth_client):
        resp = auth_client.post(_GENERATE_URL.format(symbol="ZZZZ"))
        assert resp.status_code == 404

    @patch("apps.companies.views.current_app")
    def test_valid_request_returns_202_with_task_id(self, mock_app, auth_client):
        Company.objects.create(symbol="AAPL")
        mock_task = MagicMock()
        mock_task.id = "summary-task-uuid-1234"
        mock_app.send_task.return_value = mock_task

        resp = auth_client.post(_GENERATE_URL.format(symbol="AAPL"))

        assert resp.status_code == 202
        assert resp.data["task_id"] == "summary-task-uuid-1234"
        assert resp.data["status"] == "queued"

    @patch("apps.companies.views.current_app")
    def test_dispatches_correct_task_name_and_symbol(self, mock_app, auth_client):
        Company.objects.create(symbol="MSFT")
        mock_task = MagicMock()
        mock_task.id = "task-abc"
        mock_app.send_task.return_value = mock_task

        auth_client.post(_GENERATE_URL.format(symbol="msft"))

        mock_app.send_task.assert_called_once_with(
            "apps.companies.tasks.generate_summary_single",
            args=["MSFT"],
        )


# ---------------------------------------------------------------------------
# SyncFreshnessMatrixView
# ---------------------------------------------------------------------------

_MATRIX_URL = "/api/companies/sync-freshness/matrix/"


@pytest.mark.django_db
class TestSyncFreshnessMatrixView:
    def test_unauthenticated_returns_401(self, api_client):
        resp = api_client.get(_MATRIX_URL)
        assert resp.status_code == 401

    def test_no_companies_returns_empty_arrays(self, auth_client):
        resp = auth_client.get(_MATRIX_URL)
        assert resp.status_code == 200
        assert resp.data["total_companies"] == 0
        assert resp.data["symbols"] == []
        for entry in resp.data["data_types"]:
            assert entry["buckets"] == []

    def test_all_labels_present_in_order(self, auth_client):
        resp = auth_client.get(_MATRIX_URL)
        labels = [d["label"] for d in resp.data["data_types"]]
        assert labels == _EXPECTED_LABELS

    def test_symbols_are_alphabetical(self, auth_client):
        for symbol in ("MSFT", "AAPL", "ZM", "GOOGL"):
            Company.objects.create(symbol=symbol)
        resp = auth_client.get(_MATRIX_URL)
        assert resp.data["symbols"] == ["AAPL", "GOOGL", "MSFT", "ZM"]
        assert resp.data["total_companies"] == 4

    def test_bucket_array_is_aligned_with_symbols(self, auth_client):
        aapl = Company.objects.create(symbol="AAPL")
        Company.objects.create(symbol="MSFT")
        zm = Company.objects.create(symbol="ZM")
        CompanySyncRecord.objects.create(
            company=aapl,
            sync_type="snapshot",
            last_synced_at=dt.now(UTC) - timedelta(minutes=10),
        )
        CompanySyncRecord.objects.create(
            company=zm,
            sync_type="snapshot",
            last_synced_at=dt.now(UTC) - timedelta(days=60),
        )
        resp = auth_client.get(_MATRIX_URL)
        entry = next(d for d in resp.data["data_types"] if d["label"] == "Snapshot")
        # AAPL -> lt_1h (0), MSFT -> never (6), ZM -> gt_30d (5)
        assert entry["buckets"] == [0, 6, 5]

    def test_every_bucket_index_is_reachable(self, auth_client):
        offsets = [
            timedelta(minutes=30),
            timedelta(hours=3),
            timedelta(hours=18),
            timedelta(days=3),
            timedelta(days=14),
            timedelta(days=60),
        ]
        for i, offset in enumerate(offsets):
            c = Company.objects.create(symbol=f"T{i:03d}")
            CompanySyncRecord.objects.create(
                company=c,
                sync_type="price",
                last_synced_at=dt.now(UTC) - offset,
            )
        Company.objects.create(symbol="T999")  # never synced
        resp = auth_client.get(_MATRIX_URL)
        entry = next(d for d in resp.data["data_types"] if d["label"] == "Prices")
        assert entry["buckets"] == [0, 1, 2, 3, 4, 5, 6]

    def test_each_data_type_is_independent(self, auth_client):
        company = Company.objects.create(symbol="AAPL")
        CompanySyncRecord.objects.create(
            company=company,
            sync_type="price",
            last_synced_at=dt.now(UTC) - timedelta(minutes=5),
        )
        resp = auth_client.get(_MATRIX_URL)
        prices = next(d for d in resp.data["data_types"] if d["label"] == "Prices")
        snapshot = next(d for d in resp.data["data_types"] if d["label"] == "Snapshot")
        assert prices["buckets"] == [0]
        assert snapshot["buckets"] == [6]

    def test_bucket_arrays_match_symbol_count(self, auth_client):
        for i in range(5):
            Company.objects.create(symbol=f"C{i}")
        resp = auth_client.get(_MATRIX_URL)
        for entry in resp.data["data_types"]:
            assert len(entry["buckets"]) == len(resp.data["symbols"]) == 5

    def test_matrix_counts_agree_with_aggregate_endpoint(self, auth_client):
        c1 = Company.objects.create(symbol="AAPL")
        Company.objects.create(symbol="MSFT")
        CompanySyncRecord.objects.create(
            company=c1,
            sync_type="snapshot",
            last_synced_at=dt.now(UTC) - timedelta(hours=3),
        )
        matrix = auth_client.get(_MATRIX_URL)
        agg = auth_client.get(_FRESHNESS_URL)
        m_entry = next(d for d in matrix.data["data_types"] if d["label"] == "Snapshot")
        a_entry = next(d for d in agg.data["data_types"] if d["label"] == "Snapshot")
        assert m_entry["buckets"].count(1) == a_entry["buckets"]["h1_6"]
        assert m_entry["buckets"].count(6) == a_entry["buckets"]["never"]
