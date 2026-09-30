"""Tests for the DB-derived domain gauges (issue #2, phase 4).

These run on every Prometheus scrape, so correctness and query count both matter.
"""

from datetime import UTC, timedelta
from datetime import datetime as dt
from unittest.mock import patch

import pytest
from django.conf import settings

from apps.tasks.collectors import DomainCollector


def families(collector=None):
    """{metric name: {labelset tuple: value}} for one collect() pass."""
    out = {}
    for family in (collector or DomainCollector()).collect():
        out[family.name] = {
            tuple(sample.labels.values()): sample.value for sample in family.samples
        }
    return out


def value(result, name, *labels):
    return result.get(name, {}).get(tuple(labels), 0.0)


@pytest.fixture(autouse=True)
def _no_ollama():
    """Never touch the network from a unit test; the probe is exercised separately."""
    with patch("httpx.Client") as client:
        client.side_effect = RuntimeError("no network in tests")
        yield


# ---------------------------------------------------------------------------
# Empty database
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEmptyDatabase:
    def test_collect_succeeds_with_no_data(self):
        """A fresh deployment scrapes before anything exists. Zeros, not a 500."""
        result = families()

        assert value(result, "stockmarket_companies") == 0.0
        assert value(result, "stockmarket_kg_concepts") == 0.0

    def test_no_divide_by_zero_or_none_values(self):
        for name, samples in families().items():
            for labels, val in samples.items():
                assert val is not None, (name, labels)
                assert val == val, f"{name}{labels} is NaN"


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestIngestionGauges:
    def test_counts_companies_and_unbootstrapped_stubs(self):
        from apps.companies.models import Company

        Company.objects.create(symbol="AAPL", name="Apple", is_bootstrapped=True)
        Company.objects.create(symbol="MSFT", name="Microsoft", is_bootstrapped=True)
        Company.objects.create(symbol="NEW", name="Stub", is_bootstrapped=False)

        result = families()
        assert value(result, "stockmarket_companies") == 3.0
        assert value(result, "stockmarket_companies_unbootstrapped") == 1.0

    def test_fresh_count_excludes_stale_syncs(self):
        from apps.companies.models import Company, CompanySyncRecord

        now = dt.now(UTC)
        fresh_co = Company.objects.create(symbol="A", name="A")
        stale_co = Company.objects.create(symbol="B", name="B")
        CompanySyncRecord.objects.create(
            company=fresh_co, sync_type="price", last_synced_at=now - timedelta(hours=1)
        )
        CompanySyncRecord.objects.create(
            company=stale_co, sync_type="price", last_synced_at=now - timedelta(days=3)
        )

        result = families()
        assert value(result, "stockmarket_sync_fresh_companies", "price") == 1.0

    def test_oldest_age_reports_the_worst_offender(self):
        """The oldest timestamp, not the average - one company stuck three days behind is
        the signal, and an average over 500 companies would bury it."""
        from apps.companies.models import Company, CompanySyncRecord

        now = dt.now(UTC)
        for symbol, age in (("A", timedelta(hours=1)), ("B", timedelta(days=3))):
            company = Company.objects.create(symbol=symbol, name=symbol)
            CompanySyncRecord.objects.create(
                company=company, sync_type="snapshot", last_synced_at=now - age
            )

        age_seconds = value(families(), "stockmarket_sync_oldest_age_seconds", "snapshot")
        assert age_seconds > timedelta(days=2).total_seconds()

    def test_sync_types_are_reported_separately(self):
        from apps.companies.models import Company, CompanySyncRecord

        company = Company.objects.create(symbol="A", name="A")
        now = dt.now(UTC)
        CompanySyncRecord.objects.create(company=company, sync_type="price", last_synced_at=now)
        CompanySyncRecord.objects.create(
            company=company, sync_type="financials", last_synced_at=now - timedelta(days=5)
        )

        result = families()
        assert value(result, "stockmarket_sync_fresh_companies", "price") == 1.0
        assert value(result, "stockmarket_sync_fresh_companies", "financials") == 0.0


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAgentGauges:
    def make_run(self, user, kind="react", status="done", age=timedelta(minutes=1), meta=None):
        from apps.llm_analysis.models import AgentRun

        run = AgentRun.objects.create(
            user=user, kind=kind, query="q", status=status, meta=meta or {}
        )
        # created_at is auto_now_add, so age has to be forced after insert.
        AgentRun.objects.filter(pk=run.pk).update(created_at=dt.now(UTC) - age)
        return run

    def test_counts_runs_by_kind_and_status(self, user):
        self.make_run(user, kind="react", status="done")
        self.make_run(user, kind="react", status="error")
        self.make_run(user, kind="dag", status="done")

        result = families()
        assert value(result, "stockmarket_agent_runs", "react", "done") == 1.0
        assert value(result, "stockmarket_agent_runs", "react", "error") == 1.0
        assert value(result, "stockmarket_agent_runs", "dag", "done") == 1.0

    def test_stuck_runs_need_both_running_and_old(self, user):
        """A recently started run is not stuck - the SSE workflows legitimately take
        minutes, and flagging them would make the gauge useless."""
        self.make_run(user, kind="autonomous", status="running", age=timedelta(minutes=5))
        self.make_run(user, kind="autonomous", status="running", age=timedelta(hours=4))
        self.make_run(user, kind="autonomous", status="done", age=timedelta(hours=4))

        assert value(families(), "stockmarket_agent_runs_stuck", "autonomous") == 1.0

    def test_browser_runs_grouped_by_stop_reason(self, user):
        self.make_run(user, kind="browser", meta={"stop_reason": "complete"})
        self.make_run(user, kind="browser", meta={"stop_reason": "timeout"})
        self.make_run(user, kind="browser", meta={"stop_reason": "timeout"})

        result = families()
        assert value(result, "stockmarket_browser_runs", "timeout") == 2.0
        assert value(result, "stockmarket_browser_runs", "complete") == 1.0

    def test_browser_run_without_a_stop_reason_is_labelled_unknown(self, user):
        """Never an empty label: an empty string reads as "no data" in Grafana rather
        than "we do not know why this stopped"."""
        self.make_run(user, kind="browser", meta={})

        assert value(families(), "stockmarket_browser_runs", "unknown") == 1.0


# ---------------------------------------------------------------------------
# Knowledge graph
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestKnowledgeGraphGauges:
    def test_counts_nodes_edges_and_exports_the_cap(self):
        from apps.knowledge_graph.models import Concept, ConceptEdge

        a = Concept.objects.create(name="Graph", slug="graph", base_slug="graph")
        b = Concept.objects.create(name="Node", slug="node", base_slug="node")
        ConceptEdge.objects.create(source=a, target=b, relation="has_subfield", weight=0.9)

        result = families()
        assert value(result, "stockmarket_kg_concepts") == 2.0
        assert value(result, "stockmarket_kg_edges") == 1.0
        # Exported as a series so "how close to the cap" is a ratio of two live values
        # rather than a number baked into an alert.
        assert value(result, "stockmarket_kg_max_concepts") == float(settings.KG_MAX_NODES)

    def test_rerank_backlog_counts_only_nodes_over_the_trigger(self):
        from apps.knowledge_graph.models import Concept, ConceptEdge

        hub = Concept.objects.create(name="Hub", slug="hub", base_slug="hub")
        for i in range(settings.KG_RERANK_TRIGGER + 2):
            target = Concept.objects.create(name=f"N{i}", slug=f"n{i}", base_slug=f"n{i}")
            ConceptEdge.objects.create(
                source=hub, target=target, relation="has_subfield", weight=0.9
            )

        assert value(families(), "stockmarket_kg_concepts_awaiting_rerank") == 1.0


# ---------------------------------------------------------------------------
# Query cost and failure isolation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestScrapeCost:
    def test_query_count_does_not_grow_with_row_count(self, user):
        """This runs on every scrape. An N+1 over 500 companies or nine sync types would
        be a recurring cost, so the count must be flat in the data size."""
        from apps.companies.models import Company, CompanySyncRecord

        def seed(start, stop):
            for i in range(start, stop):
                company = Company.objects.create(symbol=f"S{i}", name=f"S{i}")
                CompanySyncRecord.objects.create(
                    company=company, sync_type="price", last_synced_at=dt.now(UTC)
                )

        seed(0, 3)
        # Warm up first: the very first scrape also pays one-off connection setup, which
        # would make the baseline look inflated and hide real growth.
        self._count_queries(families)
        baseline = self._count_queries(families)

        seed(3, 30)
        assert self._count_queries(families) == baseline, (
            "query count grew with row count - a scrape-time N+1"
        )

    @staticmethod
    def _count_queries(fn):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            fn()
        return len(ctx.captured_queries)


@pytest.mark.django_db
class TestFailureIsolation:
    def test_one_broken_section_does_not_blank_the_rest(self):
        """REGISTRY.collect() iterates collectors and an exception propagates out of the
        WHOLE scrape - so an unguarded failure here would take down every other metric
        too, including the ones that would explain why."""
        collector = DomainCollector()
        with patch.object(DomainCollector, "_ingestion", side_effect=RuntimeError("table is gone")):
            result = families(collector)

        assert "stockmarket_companies" not in result
        # Everything else still reported.
        assert "stockmarket_kg_concepts" in result
        assert "stockmarket_ollama_up" in result

    def test_a_broken_section_is_logged(self, caplog):
        """A swallowed failure that is also silent would be worse than a crash - the
        metric would simply be absent with no explanation anywhere.

        NOTE: caplog attaches its handler to the ROOT logger, and core/settings/base.py
        sets propagate=False on the "apps" logger, so app records never reach it. The
        handler has to be attached to the emitting logger directly.
        """
        import logging

        logger = logging.getLogger("apps.tasks.collectors")
        logger.addHandler(caplog.handler)
        try:
            with patch.object(DomainCollector, "_agents", side_effect=RuntimeError("boom")):
                families(DomainCollector())
        finally:
            logger.removeHandler(caplog.handler)

        assert any("domain collector section failed" in r.message for r in caplog.records)


@pytest.mark.django_db
class TestOllamaProbe:
    def test_unreachable_ollama_reports_zero_not_an_error(self):
        """The probe is the only complete signal we have: LLM calls happen in Celery
        prefork children whose registries are unreachable, so per-call instrumentation
        would cover only the web half."""
        assert value(families(), "stockmarket_ollama_up") == 0.0

    def test_reachable_ollama_reports_one(self):
        class Response:
            status_code = 200

        class Client:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def get(self, _url):
                return Response()

        with patch("httpx.Client", return_value=Client()):
            assert value(families(), "stockmarket_ollama_up") == 1.0
