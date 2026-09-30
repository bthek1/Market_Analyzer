"""DB-derived Prometheus gauges for the domain (issue #2, phase 4).

A prometheus_client *custom collector*: values are computed when Prometheus scrapes,
not cached and refreshed on a timer, so a gauge can never be stale relative to the
scrape that reported it.

This MUST run in exactly one process. A gauge like "companies with a stale snapshot" is
a property of the database, not of the process reporting it - emitted from all four
gunicorn workers it would be summed to four times the truth, or flap depending on how
the query is aggregated. That is why it lives in stockmarket-metrics.service rather than
in the web app, and why none of it goes through django-prometheus.

Every sub-collector is individually guarded. REGISTRY.collect() iterates collectors and
an exception propagates out of the whole scrape, so one failing query would take down
every OTHER metric too - including the ones that would tell you why.
"""

import logging
from datetime import UTC, timedelta
from datetime import datetime as dt

import httpx
from prometheus_client.core import GaugeMetricFamily

logger = logging.getLogger(__name__)

# A snapshot older than this counts as stale. Deliberately looser than the AI summary's
# own freshness gate (7 days for snapshots): this is "ingestion is broken", not "do not
# opine on this company".
STALE_AFTER = timedelta(hours=24)
# An AgentRun still "running" after this long is almost certainly orphaned - the longest
# legitimate workflow is the autonomous agent at 8 cycles.
STUCK_RUN_AFTER = timedelta(hours=1)
OLLAMA_PROBE_TIMEOUT_S = 2


def _gauge(name, doc, value, labels=None, label_names=()):
    family = GaugeMetricFamily(name, doc, labels=list(label_names))
    family.add_metric(list(labels or ()), value)
    return family


class DomainCollector:
    """Yields the domain gauges. Registered by run_metrics_exporter."""

    def collect(self):
        for section in (
            self._ingestion,
            self._agents,
            self._knowledge_graph,
            self._ollama,
        ):
            try:
                yield from section()
            except Exception:
                # One broken query must not blank the whole /metrics response.
                logger.exception(
                    "domain collector section failed",
                    extra={"section": getattr(section, "__name__", repr(section))},
                )

    # -- ingestion ----------------------------------------------------------
    def _ingestion(self):
        from django.db.models import Count, Min, Q

        from apps.companies.models import Company, CompanySyncRecord

        total = Company.objects.count()
        yield _gauge("stockmarket_companies", "Companies known to the system.", total)
        yield _gauge(
            "stockmarket_companies_unbootstrapped",
            "Companies created as stubs that have never been fully ingested.",
            Company.objects.filter(is_bootstrapped=False).count(),
        )

        cutoff = dt.now(UTC) - STALE_AFTER
        fresh = GaugeMetricFamily(
            "stockmarket_sync_fresh_companies",
            "Companies whose last successful sync of this type is within 24h.",
            labels=["sync_type"],
        )
        oldest = GaugeMetricFamily(
            "stockmarket_sync_oldest_age_seconds",
            "Age of the OLDEST last-sync timestamp for this type, in seconds.",
            labels=["sync_type"],
        )
        # ONE grouped query, not a count per sync_type. This runs on every scrape, so an
        # N+1 here is a recurring cost rather than a one-off - and there are nine types.
        rows = CompanySyncRecord.objects.values("sync_type").annotate(
            fresh=Count("id", filter=Q(last_synced_at__gte=cutoff)),
            oldest=Min("last_synced_at"),
        )
        now = dt.now(UTC)
        for row in rows:
            fresh.add_metric([row["sync_type"]], row["fresh"])
            if row["oldest"] is not None:
                oldest.add_metric([row["sync_type"]], (now - row["oldest"]).total_seconds())
        yield fresh
        yield oldest

    # -- agents -------------------------------------------------------------
    def _agents(self):
        from django.db.models import Count

        from apps.llm_analysis.models import AgentRun

        runs = GaugeMetricFamily(
            "stockmarket_agent_runs",
            "AgentRun rows by workflow kind and terminal status.",
            labels=["kind", "status"],
        )
        for row in AgentRun.objects.values("kind", "status").annotate(n=Count("id")):
            runs.add_metric([row["kind"], row["status"]], row["n"])
        yield runs

        stuck_cutoff = dt.now(UTC) - STUCK_RUN_AFTER
        stuck = GaugeMetricFamily(
            "stockmarket_agent_runs_stuck",
            "Runs still 'running' well past any legitimate workflow duration.",
            labels=["kind"],
        )
        for row in (
            AgentRun.objects.filter(status="running", created_at__lt=stuck_cutoff)
            .values("kind")
            .annotate(n=Count("id"))
        ):
            stuck.add_metric([row["kind"]], row["n"])
        yield stuck

        # Browser runs are the only ones that leave the network, so their outcome mix is
        # worth separating from the rest.
        browser = GaugeMetricFamily(
            "stockmarket_browser_runs",
            "Browser agent runs by stop reason.",
            labels=["stop_reason"],
        )
        # Grouped in SQL, not per row: add_metric() with a repeated label set emits
        # duplicate samples instead of summing them, so a reason seen twice would be
        # reported as 1.
        for row in (
            AgentRun.objects.filter(kind="browser")
            .values("meta__stop_reason")
            .annotate(n=Count("id"))
        ):
            # Never an empty label - Grafana renders that as "no data" rather than
            # "we do not know why this stopped".
            browser.add_metric([str(row["meta__stop_reason"] or "unknown")], row["n"])
        yield browser

    # -- knowledge graph ----------------------------------------------------
    def _knowledge_graph(self):
        from django.conf import settings
        from django.db.models import Count

        from apps.knowledge_graph.models import Concept, ConceptEdge

        yield _gauge("stockmarket_kg_concepts", "Concept nodes.", Concept.objects.count())
        yield _gauge("stockmarket_kg_edges", "ConceptEdge rows.", ConceptEdge.objects.count())
        # Exported rather than hard-coded in the alert, so "how close to the cap" is a
        # ratio of two live series and the alert survives a config change.
        yield _gauge(
            "stockmarket_kg_max_concepts",
            "Configured KG_MAX_NODES ceiling.",
            getattr(settings, "KG_MAX_NODES", 0),
        )

        trigger = getattr(settings, "KG_RERANK_TRIGGER", 30)
        over = Concept.objects.annotate(degree=Count("outgoing")).filter(degree__gt=trigger).count()
        yield _gauge(
            "stockmarket_kg_concepts_awaiting_rerank",
            "Concepts over KG_RERANK_TRIGGER edges, queued for the rerank sweep.",
            over,
        )

    # -- ollama -------------------------------------------------------------
    def _ollama(self):
        """Reachability, probed at scrape time.

        Deliberately a probe rather than per-call instrumentation: LLM calls happen in
        BOTH gunicorn workers and Celery prefork children, and a child process' registry
        is unreachable without PROMETHEUS_MULTIPROC_DIR. A latency metric covering only
        the web half would be worse than none - it would look complete. Per-call cost is
        visible instead through agent run duration and Celery task runtime.
        """
        from apps.llm_analysis.config import get_llm_config

        up = 0
        try:
            base = get_llm_config().base_url
            with httpx.Client(timeout=OLLAMA_PROBE_TIMEOUT_S) as client:
                up = int(client.get(f"{base}/api/tags").status_code == 200)
        except Exception:
            up = 0
        yield _gauge("stockmarket_ollama_up", "Ollama answered /api/tags.", up)
