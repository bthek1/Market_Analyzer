from datetime import UTC
from datetime import datetime as dt
from unittest.mock import MagicMock, patch

import pytest

from apps.companies.models import Company, CompanySyncRecord
from apps.companies.tasks import (
    _record_sync,
    _stale_symbols,
    backfill_snapshot_fields_task,
    bootstrap_tick,
    bulk_import_symbols,
    discover_new_symbols,
    ingest_symbol_full,
    sync_dividends_single,
    sync_financials_single,
    sync_prices_single,
    sync_profile_single,
    sync_snapshot_single,
    tick_earnings_dates_sync,
    tick_options_sync,
    tick_price_sync,
    tick_short_interest_sync,
    tick_snapshot_sync,
    tick_summary_generation,
)

# ---------------------------------------------------------------------------
# Bootstrap tasks
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDiscoverNewSymbols:
    @patch("apps.companies.tasks.discover_and_create_stubs")
    def test_returns_created_count(self, mock_discover):
        mock_discover.return_value = 10
        result = discover_new_symbols.run()
        assert result == {"created": 10}

    @patch("apps.companies.tasks.discover_and_create_stubs")
    def test_calls_service(self, mock_discover):
        mock_discover.return_value = 0
        discover_new_symbols.run()
        mock_discover.assert_called_once()

    @patch("apps.companies.tasks.discover_and_create_stubs")
    def test_zero_when_all_known(self, mock_discover):
        mock_discover.return_value = 0
        result = discover_new_symbols.run()
        assert result["created"] == 0


@pytest.mark.django_db
class TestBootstrapTick:
    @patch("apps.companies.tasks.bootstrap_next_batch")
    def test_returns_summary(self, mock_batch):
        mock_batch.return_value = {"attempted": 5, "ok": 5, "failed": 0}
        result = bootstrap_tick.run()
        assert result == {"attempted": 5, "ok": 5, "failed": 0}

    @patch("apps.companies.tasks.bootstrap_next_batch")
    def test_called_with_batch_size_5(self, mock_batch):
        mock_batch.return_value = {"attempted": 0, "ok": 0, "failed": 0}
        bootstrap_tick.run()
        mock_batch.assert_called_once_with(batch_size=5)

    def test_max_retries_is_zero(self):
        assert bootstrap_tick.max_retries == 0

    @patch("apps.companies.tasks.bootstrap_next_batch")
    def test_partial_failures_counted(self, mock_batch):
        mock_batch.return_value = {"attempted": 5, "ok": 3, "failed": 2}
        result = bootstrap_tick.run()
        assert result["failed"] == 2

    @patch("apps.companies.tasks.bootstrap_next_batch")
    def test_noop_when_all_bootstrapped(self, mock_batch):
        mock_batch.return_value = {"attempted": 0, "ok": 0, "failed": 0}
        result = bootstrap_tick.run()
        assert result["attempted"] == 0


# ---------------------------------------------------------------------------
# _stale_symbols + _record_sync helpers
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestStaleSymbolHelpers:
    def test_returns_empty_when_no_bootstrapped_companies(self):
        Company.objects.create(symbol="STUB", is_bootstrapped=False)
        assert _stale_symbols("price") == []

    def test_companies_with_no_record_sort_first(self):
        c1 = Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        Company.objects.create(symbol="MSFT", is_bootstrapped=True)
        # Only AAPL has a record — MSFT has none and should sort first
        CompanySyncRecord.objects.create(
            company=c1, sync_type="price", last_synced_at=dt(2020, 1, 1, tzinfo=UTC)
        )
        result = _stale_symbols("price", batch_size=1)
        assert result == ["MSFT"]

    def test_orders_by_last_synced_at_ascending(self):
        c1 = Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        c2 = Company.objects.create(symbol="MSFT", is_bootstrapped=True)
        CompanySyncRecord.objects.create(
            company=c1, sync_type="price", last_synced_at=dt(2023, 1, 1, tzinfo=UTC)
        )
        CompanySyncRecord.objects.create(
            company=c2, sync_type="price", last_synced_at=dt(2024, 1, 1, tzinfo=UTC)
        )
        result = _stale_symbols("price", batch_size=2)
        assert result[0] == "AAPL"  # older record first
        assert result[1] == "MSFT"

    def test_respects_batch_size_limit(self):
        Company.objects.bulk_create(
            [Company(symbol=f"SYM{i}", is_bootstrapped=True) for i in range(20)]
        )
        result = _stale_symbols("price", batch_size=5)
        assert len(result) == 5

    def test_excludes_unbootstrapped(self):
        Company.objects.create(symbol="STUB", is_bootstrapped=False)
        Company.objects.create(symbol="REAL", is_bootstrapped=True)
        result = _stale_symbols("price", batch_size=10)
        assert "STUB" not in result
        assert "REAL" in result

    def test_record_sync_creates_records(self):
        Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        _record_sync(["AAPL"], "price")
        assert CompanySyncRecord.objects.filter(sync_type="price").count() == 1

    def test_record_sync_upserts_on_second_call(self):
        Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        _record_sync(["AAPL"], "price")
        first_time = CompanySyncRecord.objects.get(
            company__symbol="AAPL", sync_type="price"
        ).last_synced_at
        _record_sync(["AAPL"], "price")
        second_time = CompanySyncRecord.objects.get(
            company__symbol="AAPL", sync_type="price"
        ).last_synced_at
        assert CompanySyncRecord.objects.filter(sync_type="price").count() == 1
        assert second_time >= first_time

    def test_record_sync_ignores_unknown_symbols(self):
        _record_sync(["DOESNOTEXIST"], "price")
        assert CompanySyncRecord.objects.count() == 0


# ---------------------------------------------------------------------------
# Rolling tick tasks
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTickPriceSync:
    def test_empty_db_returns_zeros(self):
        result = tick_price_sync.run()
        assert result == {"ok": 0, "failed": 0, "bars": 0}

    @patch("apps.companies.tasks.sync_price_history")
    def test_syncs_stale_symbols_and_records(self, mock_sync):
        mock_sync.return_value = 50
        Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        result = tick_price_sync.run()
        assert result["ok"] == 1
        assert result["bars"] == 50
        assert CompanySyncRecord.objects.filter(sync_type="price").count() == 1

    @patch("apps.companies.tasks.sync_price_history")
    def test_records_even_failed_symbols(self, mock_sync):
        mock_sync.side_effect = Exception("network error")
        Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        result = tick_price_sync.run()
        assert result["failed"] == 1
        # failed symbols still get recorded to advance their staleness clock
        assert CompanySyncRecord.objects.filter(sync_type="price").count() == 1

    @patch("apps.companies.tasks.sync_price_history")
    def test_picks_stalest_symbol_first(self, mock_sync):
        mock_sync.return_value = 0
        c_old = Company.objects.create(symbol="OLD", is_bootstrapped=True)
        c_new = Company.objects.create(symbol="NEW", is_bootstrapped=True)
        CompanySyncRecord.objects.create(
            company=c_old, sync_type="price", last_synced_at=dt(2020, 1, 1, tzinfo=UTC)
        )
        CompanySyncRecord.objects.create(
            company=c_new, sync_type="price", last_synced_at=dt(2024, 1, 1, tzinfo=UTC)
        )
        tick_price_sync.run()
        first_call = mock_sync.call_args_list[0][0][0]
        assert first_call == "OLD"

    def test_unbootstrapped_excluded(self):
        Company.objects.create(symbol="STUB", is_bootstrapped=False)
        result = tick_price_sync.run()
        assert result == {"ok": 0, "failed": 0, "bars": 0}


@pytest.mark.django_db
class TestTickSnapshotSync:
    def test_empty_db_returns_zeros(self):
        result = tick_snapshot_sync.run()
        assert result == {"ok": 0, "failed": 0}

    @patch("apps.companies.tasks.sync_snapshot")
    def test_syncs_and_records(self, mock_sync):
        mock_sync.return_value = MagicMock()
        Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        result = tick_snapshot_sync.run()
        assert result["ok"] == 1
        assert CompanySyncRecord.objects.filter(sync_type="snapshot").count() == 1

    @patch("apps.companies.tasks.sync_snapshot")
    def test_picks_stalest_symbol_first(self, mock_sync):
        mock_sync.return_value = MagicMock()
        c_old = Company.objects.create(symbol="OLD", is_bootstrapped=True)
        c_new = Company.objects.create(symbol="NEW", is_bootstrapped=True)
        CompanySyncRecord.objects.create(
            company=c_old, sync_type="snapshot", last_synced_at=dt(2020, 1, 1, tzinfo=UTC)
        )
        CompanySyncRecord.objects.create(
            company=c_new, sync_type="snapshot", last_synced_at=dt(2024, 1, 1, tzinfo=UTC)
        )
        tick_snapshot_sync.run()
        first_call = mock_sync.call_args_list[0][0][0]
        assert first_call == "OLD"


@pytest.mark.django_db
class TestTickEarningsDatesSync:
    def test_empty_db_returns_zeros(self):
        result = tick_earnings_dates_sync.run()
        assert result == {"ok": 0, "failed": 0, "rows": 0}

    @patch("apps.companies.tasks.sync_earnings_dates")
    def test_syncs_and_records(self, mock_sync):
        mock_sync.return_value = 5
        Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        result = tick_earnings_dates_sync.run()
        assert result["ok"] == 1
        assert result["rows"] == 5
        assert CompanySyncRecord.objects.filter(sync_type="earnings_dates").count() == 1

    @patch("apps.companies.tasks.sync_earnings_dates")
    def test_picks_stalest_symbol_first(self, mock_sync):
        mock_sync.return_value = 0
        c_old = Company.objects.create(symbol="OLD", is_bootstrapped=True)
        c_new = Company.objects.create(symbol="NEW", is_bootstrapped=True)
        CompanySyncRecord.objects.create(
            company=c_old, sync_type="earnings_dates", last_synced_at=dt(2020, 1, 1, tzinfo=UTC)
        )
        CompanySyncRecord.objects.create(
            company=c_new, sync_type="earnings_dates", last_synced_at=dt(2024, 1, 1, tzinfo=UTC)
        )
        tick_earnings_dates_sync.run()
        first_call = mock_sync.call_args_list[0][0][0]
        assert first_call == "OLD"


@pytest.mark.django_db
class TestTickOptionsSync:
    @patch("apps.companies.tasks._is_weekend", return_value=True)
    def test_skips_on_weekend(self, _mock):
        result = tick_options_sync.run()
        assert result["skipped"] == "weekend"

    @patch("apps.companies.tasks._is_weekend", return_value=False)
    def test_empty_db_returns_zeros_on_weekday(self, _mock):
        result = tick_options_sync.run()
        assert result == {"ok": 0, "failed": 0, "contracts": 0}

    @patch("apps.companies.tasks.sync_options")
    @patch("apps.companies.tasks._is_weekend", return_value=False)
    def test_syncs_on_weekday(self, _mock_weekend, mock_sync):
        mock_sync.return_value = 10
        Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        result = tick_options_sync.run()
        assert result["ok"] == 1
        assert result["contracts"] == 10


# ---------------------------------------------------------------------------
# tick_summary_generation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTickSummaryGeneration:
    def test_empty_db_returns_zero(self):
        result = tick_summary_generation.run()
        assert result == {"queued": 0}

    def test_unbootstrapped_excluded(self):
        Company.objects.create(symbol="STUB", is_bootstrapped=False)
        result = tick_summary_generation.run()
        assert result == {"queued": 0}

    def test_queues_companies_with_no_summary_first(self):
        from apps.companies.models import CompanySummary

        c1 = Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        Company.objects.create(symbol="MSFT", is_bootstrapped=True)
        # AAPL has an old summary, MSFT has none — MSFT should be picked first
        CompanySummary.objects.create(
            company=c1,
            model_name="m",
            verdict="buy",
            summary="old",
            data_snapshot={},
        )
        with patch("apps.companies.tasks.generate_summary_single") as mock_task:
            mock_task.delay = MagicMock()
            result = tick_summary_generation.run(batch_size=1)
        assert result["queued"] == 1
        mock_task.delay.assert_called_once_with("MSFT")

    def test_respects_batch_size(self):
        Company.objects.bulk_create(
            [Company(symbol=f"SYM{i}", is_bootstrapped=True) for i in range(10)]
        )
        with patch("apps.companies.tasks.generate_summary_single") as mock_task:
            mock_task.delay = MagicMock()
            result = tick_summary_generation.run(batch_size=3)
        assert result["queued"] == 3
        assert mock_task.delay.call_count == 3

    def test_does_not_create_sync_records(self):
        Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        with patch("apps.companies.tasks.generate_summary_single") as mock_task:
            mock_task.delay = MagicMock()
            tick_summary_generation.run()
        assert CompanySyncRecord.objects.count() == 0

    def test_orders_nulls_first_in_sql(self):
        """Regression guard: never-summarised companies (NULL latest_summary_at)
        must be queued before already-summarised ones. Postgres sorts NULLs LAST
        under a plain ASC, so the query must request NULLS FIRST explicitly. This
        asserts on the compiled SQL because the test DB (SQLite) sorts NULLs first
        by default and would otherwise mask the Postgres-only bug.
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        with patch("apps.companies.tasks.generate_summary_single") as mock_task:
            mock_task.delay = MagicMock()
            with CaptureQueriesContext(connection) as ctx:
                tick_summary_generation.run()

        ordering_sql = [
            q["sql"]
            for q in ctx.captured_queries
            if "companies_company" in q["sql"] and "ORDER BY" in q["sql"]
        ]
        assert ordering_sql, "expected an ordered query against companies_company"
        assert any("NULLS FIRST" in sql for sql in ordering_sql), (
            "tick_summary_generation must order by latest_summary_at NULLS FIRST"
        )

    def test_unsummarised_picked_before_old_summaries(self):
        """With a batch larger than the unsummarised pool, every never-summarised
        company is queued before any already-summarised one (oldest-first among
        those that have a summary)."""
        from apps.companies.models import CompanySummary

        old = Company.objects.create(symbol="OLD", is_bootstrapped=True)
        recent = Company.objects.create(symbol="RECENT", is_bootstrapped=True)
        Company.objects.create(symbol="NEW1", is_bootstrapped=True)
        Company.objects.create(symbol="NEW2", is_bootstrapped=True)
        for company, when in (
            (old, dt(2020, 1, 1, tzinfo=UTC)),
            (recent, dt(2026, 1, 1, tzinfo=UTC)),
        ):
            summary = CompanySummary.objects.create(
                company=company,
                model_name="m",
                verdict="buy",
                summary="s",
                data_snapshot={},
            )
            # generated_at is auto_now_add; .update() bypasses it to set a fixed time.
            CompanySummary.objects.filter(pk=summary.pk).update(generated_at=when)

        with patch("apps.companies.tasks.generate_summary_single") as mock_task:
            mock_task.delay = MagicMock()
            tick_summary_generation.run(batch_size=3)

        queued = [c.args[0] for c in mock_task.delay.call_args_list]
        # Two unsummarised companies must come first (order among them unspecified),
        # then the oldest-summarised; the recently-summarised one is not reached.
        assert set(queued[:2]) == {"NEW1", "NEW2"}
        assert queued[2] == "OLD"
        assert "RECENT" not in queued


# ---------------------------------------------------------------------------
# Backfill task
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBackfillSnapshotFieldsTask:
    @patch("apps.companies.tasks.backfill_snapshot_fields")
    def test_returns_updated_count(self, mock_backfill):
        mock_backfill.return_value = 42
        result = backfill_snapshot_fields_task.run()
        assert result == {"updated": 42}

    @patch("apps.companies.tasks.backfill_snapshot_fields")
    def test_calls_service(self, mock_backfill):
        mock_backfill.return_value = 0
        backfill_snapshot_fields_task.run()
        mock_backfill.assert_called_once()


# ---------------------------------------------------------------------------
# Legacy / manual tasks
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBulkImportSymbolsTask:
    @patch("apps.companies.tasks.import_from_yfinance")
    def test_returns_created_count(self, mock_import):
        mock_import.return_value = 3
        result = bulk_import_symbols.run(["AAPL", "MSFT", "TSLA"])
        assert result == {"created": 3}

    @patch("apps.companies.tasks.import_from_yfinance")
    def test_passes_symbols_to_service(self, mock_import):
        mock_import.return_value = 0
        bulk_import_symbols.run(["AAPL"])
        mock_import.assert_called_once_with(["AAPL"])

    @patch("apps.companies.tasks.import_from_yfinance")
    def test_empty_list_returns_zero(self, mock_import):
        mock_import.return_value = 0
        result = bulk_import_symbols.run([])
        assert result == {"created": 0}


@pytest.mark.django_db
class TestIngestSymbolFullTask:
    @patch("apps.companies.tasks.sync_all_for_symbol")
    def test_returns_full_summary(self, mock_ingest):
        mock_ingest.return_value = {
            "profile": True,
            "prices": 100,
            "snapshot": True,
            "financials": 50,
            "dividends": 10,
        }
        result = ingest_symbol_full.run("AAPL")
        assert result["prices"] == 100
        assert result["profile"] is True

    @patch("apps.companies.tasks.sync_all_for_symbol")
    def test_uppercases_symbol(self, mock_ingest):
        mock_ingest.return_value = {
            "profile": True,
            "prices": 0,
            "snapshot": False,
            "financials": 0,
            "dividends": 0,
        }
        ingest_symbol_full.run("aapl")
        mock_ingest.assert_called_once_with("AAPL")


# ---------------------------------------------------------------------------
# Celery settings
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTaskResultsBackend:
    def test_result_backend_is_django_db(self, settings):
        assert settings.CELERY_RESULT_BACKEND == "django-db"

    def test_result_extended_captures_metadata(self, settings):
        assert settings.CELERY_RESULT_EXTENDED is True

    def test_beat_scheduler_is_database(self, settings):
        assert settings.CELERY_BEAT_SCHEDULER == ("django_celery_beat.schedulers:DatabaseScheduler")

    @patch("apps.companies.tasks.import_from_yfinance")
    def test_bulk_import_returns_success(self, mock_import):
        mock_import.return_value = 2
        result = bulk_import_symbols.apply(args=[["AAPL", "MSFT"]])
        assert result.status == "SUCCESS"
        assert result.get() == {"created": 2}


# ---------------------------------------------------------------------------
# generate_summary_single
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGenerateSummarySingleTask:
    def test_calls_service_and_returns_verdict(self):
        from apps.companies.tasks import generate_summary_single

        mock_summary = MagicMock()
        mock_summary.verdict = "buy"
        mock_summary.pk = "abc-123"

        with patch(
            "apps.companies.tasks.generate_company_summary", return_value=mock_summary
        ) as mock_svc:
            result = generate_summary_single.apply(args=["AAPL"]).get()

        mock_svc.assert_called_once_with("AAPL")
        assert result["verdict"] == "buy"
        assert result["symbol"] == "AAPL"

    def test_retries_on_ollama_error(self):
        from apps.companies.tasks import generate_summary_single
        from apps.llm_analysis.services import OllamaServiceError

        with patch(
            "apps.companies.tasks.generate_company_summary",
            side_effect=OllamaServiceError("timeout"),
        ):
            task = generate_summary_single.s("AAPL").apply()

        assert task.status in ("FAILURE", "RETRY")


# ---------------------------------------------------------------------------
# Remaining tick tasks (failure paths + full coverage)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTickSnapshotSyncFailure:
    @patch("apps.companies.tasks.sync_snapshot")
    def test_records_even_failed_symbols(self, mock_sync):
        mock_sync.side_effect = Exception("timeout")
        Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        result = tick_snapshot_sync.run()
        assert result["failed"] == 1
        assert CompanySyncRecord.objects.filter(sync_type="snapshot").count() == 1


@pytest.mark.django_db
class TestTickProfileSync:
    def test_empty_db_returns_zeros(self):
        from apps.companies.tasks import tick_profile_sync

        result = tick_profile_sync.run()
        assert result == {"ok": 0, "failed": 0}

    @patch("apps.companies.tasks.sync_company_profile")
    def test_syncs_and_records(self, mock_sync):
        from apps.companies.tasks import tick_profile_sync

        mock_sync.return_value = MagicMock()
        Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        result = tick_profile_sync.run()
        assert result["ok"] == 1
        assert CompanySyncRecord.objects.filter(sync_type="profile").count() == 1

    @patch("apps.companies.tasks.sync_company_profile")
    def test_records_even_failed_symbols(self, mock_sync):
        from apps.companies.tasks import tick_profile_sync

        mock_sync.side_effect = Exception("api error")
        Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        result = tick_profile_sync.run()
        assert result["failed"] == 1
        assert CompanySyncRecord.objects.filter(sync_type="profile").count() == 1


@pytest.mark.django_db
class TestTickFinancialSync:
    def test_empty_db_returns_zeros(self):
        from apps.companies.tasks import tick_financial_sync

        result = tick_financial_sync.run()
        assert result == {"ok": 0, "failed": 0, "rows": 0}

    @patch("apps.companies.tasks.sync_financials")
    def test_syncs_and_records(self, mock_sync):
        from apps.companies.tasks import tick_financial_sync

        mock_sync.return_value = 30
        Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        result = tick_financial_sync.run()
        assert result["ok"] == 1
        assert result["rows"] == 30
        assert CompanySyncRecord.objects.filter(sync_type="financials").count() == 1

    @patch("apps.companies.tasks.sync_financials")
    def test_records_even_failed_symbols(self, mock_sync):
        from apps.companies.tasks import tick_financial_sync

        mock_sync.side_effect = Exception("api error")
        Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        result = tick_financial_sync.run()
        assert result["failed"] == 1
        assert CompanySyncRecord.objects.filter(sync_type="financials").count() == 1


@pytest.mark.django_db
class TestTickDividendSync:
    def test_empty_db_returns_zeros(self):
        from apps.companies.tasks import tick_dividend_sync

        result = tick_dividend_sync.run()
        assert result == {"ok": 0, "failed": 0, "rows": 0}

    @patch("apps.companies.tasks.sync_dividends")
    def test_syncs_and_records(self, mock_sync):
        from apps.companies.tasks import tick_dividend_sync

        mock_sync.return_value = 4
        Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        result = tick_dividend_sync.run()
        assert result["ok"] == 1
        assert result["rows"] == 4
        assert CompanySyncRecord.objects.filter(sync_type="dividends").count() == 1

    @patch("apps.companies.tasks.sync_dividends")
    def test_records_even_failed_symbols(self, mock_sync):
        from apps.companies.tasks import tick_dividend_sync

        mock_sync.side_effect = Exception("api error")
        Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        result = tick_dividend_sync.run()
        assert result["failed"] == 1
        assert CompanySyncRecord.objects.filter(sync_type="dividends").count() == 1


@pytest.mark.django_db
class TestTickInstitutionalHoldersSync:
    def test_empty_db_returns_zeros(self):
        from apps.companies.tasks import tick_institutional_holders_sync

        result = tick_institutional_holders_sync.run()
        assert result == {"ok": 0, "failed": 0}

    @patch("apps.companies.tasks.sync_institutional_holders")
    def test_syncs_and_records(self, mock_sync):
        from apps.companies.tasks import tick_institutional_holders_sync

        mock_sync.return_value = MagicMock()
        Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        result = tick_institutional_holders_sync.run()
        assert result["ok"] == 1
        assert CompanySyncRecord.objects.filter(sync_type="institutional_holders").count() == 1

    @patch("apps.companies.tasks.sync_institutional_holders")
    def test_records_even_failed_symbols(self, mock_sync):
        from apps.companies.tasks import tick_institutional_holders_sync

        mock_sync.side_effect = Exception("api error")
        Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        result = tick_institutional_holders_sync.run()
        assert result["failed"] == 1
        assert CompanySyncRecord.objects.filter(sync_type="institutional_holders").count() == 1


@pytest.mark.django_db
class TestTickShortInterestSync:
    def test_empty_db_returns_zeros(self):
        result = tick_short_interest_sync.run()
        assert result == {"ok": 0, "failed": 0}

    @patch("apps.companies.tasks.sync_short_interest")
    def test_syncs_and_records(self, mock_sync):
        mock_sync.return_value = MagicMock()
        Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        result = tick_short_interest_sync.run()
        assert result["ok"] == 1
        assert result["failed"] == 0
        assert CompanySyncRecord.objects.filter(sync_type="short_interest").count() == 1

    @patch("apps.companies.tasks.sync_short_interest")
    def test_records_even_failed_symbols(self, mock_sync):
        mock_sync.side_effect = Exception("api error")
        Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        result = tick_short_interest_sync.run()
        assert result["failed"] == 1
        assert CompanySyncRecord.objects.filter(sync_type="short_interest").count() == 1

    def test_excludes_unbootstrapped(self):
        Company.objects.create(symbol="AAPL", is_bootstrapped=False)
        result = tick_short_interest_sync.run()
        assert result == {"ok": 0, "failed": 0}


@pytest.mark.django_db
class TestTickEarningsDatsSyncFailure:
    @patch("apps.companies.tasks.sync_earnings_dates")
    def test_records_even_failed_symbols(self, mock_sync):
        mock_sync.side_effect = Exception("api error")
        Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        result = tick_earnings_dates_sync.run()
        assert result["failed"] == 1
        assert CompanySyncRecord.objects.filter(sync_type="earnings_dates").count() == 1


@pytest.mark.django_db
class TestTickOptionsSyncFailure:
    @patch("apps.companies.tasks.sync_options")
    @patch("apps.companies.tasks._is_weekend", return_value=False)
    def test_records_even_failed_symbols(self, _mock_weekend, mock_sync):
        mock_sync.side_effect = Exception("api error")
        Company.objects.create(symbol="AAPL", is_bootstrapped=True)
        result = tick_options_sync.run()
        assert result["failed"] == 1
        assert CompanySyncRecord.objects.filter(sync_type="options").count() == 1


class TestIsWeekend:
    def test_returns_bool(self):
        from apps.companies.tasks import _is_weekend

        assert isinstance(_is_weekend(), bool)


# ---------------------------------------------------------------------------
# Single-symbol tasks
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSingleSymbolTasks:
    @patch("apps.companies.tasks.sync_company_profile")
    def test_sync_profile_single(self, mock_sync):
        from apps.companies.tasks import sync_profile_single

        mock_sync.return_value = MagicMock()
        result = sync_profile_single.run("AAPL")
        assert result == {"ok": True}
        mock_sync.assert_called_once_with("AAPL")

    @patch("apps.companies.tasks.sync_company_profile")
    def test_sync_profile_single_returns_false_on_none(self, mock_sync):
        from apps.companies.tasks import sync_profile_single

        mock_sync.return_value = None
        result = sync_profile_single.run("BAD")
        assert result == {"ok": False}

    @patch("apps.companies.tasks.sync_price_history")
    def test_sync_prices_single(self, mock_sync):
        from apps.companies.tasks import sync_prices_single

        mock_sync.return_value = 100
        result = sync_prices_single.run("AAPL")
        assert result == {"bars": 100}
        mock_sync.assert_called_once_with("AAPL")

    @patch("apps.companies.tasks.sync_snapshot")
    def test_sync_snapshot_single(self, mock_sync):
        from apps.companies.tasks import sync_snapshot_single

        mock_sync.return_value = MagicMock()
        result = sync_snapshot_single.run("AAPL")
        assert result == {"ok": True}

    @patch("apps.companies.tasks.sync_snapshot")
    def test_sync_snapshot_single_none(self, mock_sync):
        from apps.companies.tasks import sync_snapshot_single

        mock_sync.return_value = None
        result = sync_snapshot_single.run("BAD")
        assert result == {"ok": False}

    @patch("apps.companies.tasks.sync_financials")
    def test_sync_financials_single(self, mock_sync):
        from apps.companies.tasks import sync_financials_single

        mock_sync.return_value = 50
        result = sync_financials_single.run("AAPL")
        assert result == {"rows": 50}

    @patch("apps.companies.tasks.sync_dividends")
    def test_sync_dividends_single(self, mock_sync):
        from apps.companies.tasks import sync_dividends_single

        mock_sync.return_value = 8
        result = sync_dividends_single.run("AAPL")
        assert result == {"rows": 8}

    @patch("apps.companies.tasks.sync_institutional_holders")
    def test_sync_institutional_holders_single(self, mock_sync):
        from apps.companies.tasks import sync_institutional_holders_single

        mock_sync.return_value = MagicMock()
        result = sync_institutional_holders_single.run("AAPL")
        assert result == {"ok": True}

    @patch("apps.companies.tasks.sync_earnings_dates")
    def test_sync_earnings_single(self, mock_sync):
        from apps.companies.tasks import sync_earnings_single

        mock_sync.return_value = 6
        result = sync_earnings_single.run("AAPL")
        assert result == {"rows": 6}

    @patch("apps.companies.tasks.sync_options")
    def test_sync_options_single(self, mock_sync):
        from apps.companies.tasks import sync_options_single

        mock_sync.return_value = 12
        result = sync_options_single.run("AAPL")
        assert result == {"expiries": 12}

    @patch("apps.companies.tasks.sync_short_interest")
    def test_sync_short_interest_single(self, mock_sync):
        from apps.companies.tasks import sync_short_interest_single

        mock_sync.return_value = MagicMock()
        result = sync_short_interest_single.run("AAPL")
        assert result == {"ok": True}
        mock_sync.assert_called_once_with("AAPL")

    @patch("apps.companies.tasks.sync_short_interest")
    def test_sync_short_interest_single_returns_false_on_none(self, mock_sync):
        from apps.companies.tasks import sync_short_interest_single

        mock_sync.return_value = None
        result = sync_short_interest_single.run("AAPL")
        assert result == {"ok": False}


# ---------------------------------------------------------------------------
# Single-symbol tasks record their sync (the AI-summary freshness gate reads
# CompanySyncRecord, so a manual sync that does not write one stays "stale")
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSingleSymbolTasksRecordSync:
    @pytest.fixture(autouse=True)
    def _company(self):
        return Company.objects.create(symbol="AAPL", is_bootstrapped=True)

    def _last(self, sync_type):
        return CompanySyncRecord.objects.filter(company__symbol="AAPL", sync_type=sync_type).first()

    @patch("apps.companies.tasks.sync_snapshot")
    def test_snapshot_single_records(self, mock_sync):
        mock_sync.return_value = MagicMock()
        sync_snapshot_single.run("AAPL")
        assert self._last("snapshot") is not None

    @patch("apps.companies.tasks.sync_snapshot")
    def test_snapshot_single_skips_when_no_data(self, mock_sync):
        mock_sync.return_value = None
        sync_snapshot_single.run("AAPL")
        assert self._last("snapshot") is None

    @patch("apps.companies.tasks.sync_price_history")
    def test_prices_single_records_even_with_no_new_bars(self, mock_sync):
        mock_sync.return_value = 0
        sync_prices_single.run("AAPL")
        assert self._last("price") is not None

    @patch("apps.companies.tasks.sync_financials")
    def test_financials_single_records(self, mock_sync):
        mock_sync.return_value = 12
        sync_financials_single.run("AAPL")
        assert self._last("financials") is not None

    @patch("apps.companies.tasks.sync_dividends")
    def test_dividends_single_records(self, mock_sync):
        mock_sync.return_value = 4
        sync_dividends_single.run("AAPL")
        assert self._last("dividends") is not None

    @patch("apps.companies.tasks.sync_company_profile")
    def test_profile_single_records(self, mock_sync):
        mock_sync.return_value = MagicMock()
        sync_profile_single.run("AAPL")
        assert self._last("profile") is not None

    @patch("apps.companies.tasks.sync_snapshot")
    def test_record_is_refreshed_not_duplicated(self, mock_sync):
        mock_sync.return_value = MagicMock()
        CompanySyncRecord.objects.create(
            company=Company.objects.get(symbol="AAPL"),
            sync_type="snapshot",
            last_synced_at=dt(2020, 1, 1, tzinfo=UTC),
        )
        sync_snapshot_single.run("AAPL")
        assert CompanySyncRecord.objects.filter(sync_type="snapshot").count() == 1
        assert self._last("snapshot").last_synced_at.year > 2020
