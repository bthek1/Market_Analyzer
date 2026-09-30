from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command

from apps.companies.models import Company

CMD = "discover_new_symbols"
MODULE = f"apps.companies.management.commands.{CMD}"


def _run(*args, **kwargs):
    out = StringIO()
    call_command(CMD, *args, stdout=out, **kwargs)
    return out.getvalue()


@pytest.mark.django_db
class TestDiscoverAction:
    @patch(f"{MODULE}.discover_and_create_stubs")
    def test_calls_service(self, mock_discover):
        mock_discover.return_value = 5
        _run("discover")
        mock_discover.assert_called_once()

    @patch(f"{MODULE}.discover_and_create_stubs")
    def test_reports_created_count(self, mock_discover):
        mock_discover.return_value = 5
        out = _run("discover")
        assert "5 new symbol stubs created" in out

    @patch(f"{MODULE}.discover_and_create_stubs")
    def test_zero_when_all_known(self, mock_discover):
        mock_discover.return_value = 0
        out = _run("discover")
        assert "0 new symbol stubs created" in out

    @patch(f"{MODULE}.discover_and_create_stubs")
    def test_prints_scraping_message(self, mock_discover):
        mock_discover.return_value = 3
        out = _run("discover")
        assert "Scraping" in out

    @patch(f"{MODULE}.discover_and_create_stubs")
    def test_default_action_is_discover(self, mock_discover):
        mock_discover.return_value = 0
        _run()
        mock_discover.assert_called_once()


@pytest.mark.django_db
class TestBootstrapAction:
    @patch(f"{MODULE}.bootstrap_next_batch")
    def test_calls_service_with_default_batch_size(self, mock_batch):
        mock_batch.return_value = {"attempted": 5, "ok": 5, "failed": 0}
        _run("bootstrap")
        mock_batch.assert_called_once_with(batch_size=5)

    @patch(f"{MODULE}.bootstrap_next_batch")
    def test_custom_batch_size_passed_through(self, mock_batch):
        mock_batch.return_value = {"attempted": 20, "ok": 20, "failed": 0}
        _run("bootstrap", "--batch-size", "20")
        mock_batch.assert_called_once_with(batch_size=20)

    @patch(f"{MODULE}.bootstrap_next_batch")
    def test_output_contains_attempted(self, mock_batch):
        mock_batch.return_value = {"attempted": 5, "ok": 5, "failed": 0}
        out = _run("bootstrap")
        assert "attempted=5" in out

    @patch(f"{MODULE}.bootstrap_next_batch")
    def test_output_contains_ok(self, mock_batch):
        mock_batch.return_value = {"attempted": 5, "ok": 5, "failed": 0}
        out = _run("bootstrap")
        assert "ok=5" in out

    @patch(f"{MODULE}.bootstrap_next_batch")
    def test_partial_failures_shown(self, mock_batch):
        mock_batch.return_value = {"attempted": 5, "ok": 3, "failed": 2}
        out = _run("bootstrap")
        assert "failed=2" in out

    @patch(f"{MODULE}.bootstrap_next_batch")
    def test_prints_bootstrapping_message(self, mock_batch):
        mock_batch.return_value = {"attempted": 5, "ok": 5, "failed": 0}
        out = _run("bootstrap")
        assert "Bootstrapping" in out


@pytest.mark.django_db
class TestSyncAction:
    @patch(f"{MODULE}.sync_company_profile")
    def test_sync_single_symbol(self, mock_sync):
        mock_sync.return_value = Company(symbol="AAPL", name="Apple Inc.")
        _run("sync", "--symbol", "AAPL")
        mock_sync.assert_called_once_with("AAPL")

    @patch(f"{MODULE}.sync_company_profile")
    def test_sync_uppercases_symbol(self, mock_sync):
        mock_sync.return_value = Company(symbol="AAPL", name="Apple Inc.")
        _run("sync", "--symbol", "aapl")
        mock_sync.assert_called_once_with("AAPL")

    @patch(f"{MODULE}.sync_company_profile")
    def test_found_company_prints_synced(self, mock_sync):
        mock_sync.return_value = Company(symbol="AAPL", name="Apple Inc.")
        out = _run("sync", "--symbol", "AAPL")
        assert "Synced" in out

    @patch(f"{MODULE}.sync_company_profile")
    def test_not_found_shows_warning(self, mock_sync):
        mock_sync.return_value = None
        out = _run("sync", "--symbol", "ZZZZZ")
        assert "No data found" in out

    @patch(f"{MODULE}.sync_company_profile")
    def test_prints_syncing_message(self, mock_sync):
        mock_sync.return_value = Company(symbol="AAPL")
        out = _run("sync", "--symbol", "AAPL")
        assert "Syncing AAPL" in out

    def test_without_symbol_shows_error(self):
        out = _run("sync")
        assert "Please provide --symbol" in out

    def test_without_symbol_does_not_call_service(self):
        with patch(f"{MODULE}.sync_company_profile") as mock_sync:
            _run("sync")
        mock_sync.assert_not_called()


_INGEST_RESULT = {
    "profile": True,
    "prices": 100,
    "snapshot": True,
    "financials": 50,
    "dividends": 10,
}


@pytest.mark.django_db
class TestIngestAction:
    @patch(f"{MODULE}.sync_all_for_symbol")
    def test_calls_service(self, mock_ingest):
        mock_ingest.return_value = _INGEST_RESULT
        _run("ingest", "AAPL")
        mock_ingest.assert_called_once_with("AAPL")

    @patch(f"{MODULE}.sync_all_for_symbol")
    def test_uppercases_symbol(self, mock_ingest):
        mock_ingest.return_value = _INGEST_RESULT
        _run("ingest", "aapl")
        mock_ingest.assert_called_once_with("AAPL")

    @patch(f"{MODULE}.sync_all_for_symbol")
    def test_output_contains_prices(self, mock_ingest):
        mock_ingest.return_value = _INGEST_RESULT
        out = _run("ingest", "AAPL")
        assert "prices=100" in out

    @patch(f"{MODULE}.sync_all_for_symbol")
    def test_output_contains_financials(self, mock_ingest):
        mock_ingest.return_value = _INGEST_RESULT
        out = _run("ingest", "AAPL")
        assert "financials=50" in out

    @patch(f"{MODULE}.sync_all_for_symbol")
    def test_output_contains_dividends(self, mock_ingest):
        mock_ingest.return_value = _INGEST_RESULT
        out = _run("ingest", "AAPL")
        assert "dividends=10" in out

    @patch(f"{MODULE}.sync_all_for_symbol")
    def test_prints_full_ingest_message(self, mock_ingest):
        mock_ingest.return_value = _INGEST_RESULT
        out = _run("ingest", "AAPL")
        assert "Full ingest for AAPL" in out
