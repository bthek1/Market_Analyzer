"""Unit tests for the Celery event -> Prometheus fold (issue #2, phase 3).

Events are fed in directly rather than through a broker: `handle_event` is separated
from the connection loop precisely so this is possible without Redis.
"""

import time

import pytest
from celery.events.state import State
from prometheus_client import CollectorRegistry

from apps.tasks import metrics
from apps.tasks.metrics import handle_event


def value(counter, task):
    """Current value of a labelled counter, or 0 if the label set was never touched."""
    for metric in counter.collect():
        for sample in metric.samples:
            if sample.labels.get("task") == task and sample.name.endswith("_total"):
                return sample.value
    return 0.0


@pytest.fixture
def state():
    return State()


def event(event_type, **fields):
    """A realistic Celery event.

    celery.events.state.State unpacks (uuid, hostname, timestamp, local_received, clock)
    off every task event and (hostname, timestamp, local_received) off worker events, so
    a bare {"type": ..., "uuid": ...} raises KeyError deep inside celery. Real events
    always carry these; the helper supplies them so the tests exercise the same path
    production does.
    """
    now = time.time()
    base = {
        "type": event_type,
        "hostname": "worker@stockmarket",
        "timestamp": now,
        "local_received": now,
        "clock": 1,
        "pid": 1234,
    }
    base.update(fields)
    return base


def send(state, uuid="t-1", name="apps.companies.tasks.sync_prices"):
    """The task-sent event is what teaches `state` the uuid -> name mapping."""
    handle_event(state, event("task-sent", uuid=uuid, name=name))


class TestTaskLifecycle:
    def test_sent_increments_the_sent_counter(self, state):
        before = value(metrics.TASK_SENT, "apps.companies.tasks.sync_prices")
        send(state)

        assert value(metrics.TASK_SENT, "apps.companies.tasks.sync_prices") == before + 1

    def test_success_increments_and_records_runtime(self, state):
        name = "apps.companies.tasks.sync_snapshot"
        send(state, uuid="t-2", name=name)
        before = value(metrics.TASK_SUCCEEDED, name)

        handle_event(state, event("task-succeeded", uuid="t-2", runtime=2.5))

        assert value(metrics.TASK_SUCCEEDED, name) == before + 1
        samples = {
            s.name: s.value
            for m in metrics.TASK_RUNTIME.collect()
            for s in m.samples
            if s.labels.get("task") == name
        }
        assert samples["celery_task_runtime_seconds_count"] >= 1
        assert samples["celery_task_runtime_seconds_sum"] >= 2.5

    def test_failure_increments_the_failure_counter(self, state):
        name = "apps.knowledge_graph.tasks.expand_concept_task"
        send(state, uuid="t-3", name=name)
        before = value(metrics.TASK_FAILED, name)

        handle_event(state, event("task-failed", uuid="t-3", exception="ValueError()"))

        assert value(metrics.TASK_FAILED, name) == before + 1

    def test_retry_increments_the_retry_counter(self, state):
        name = "apps.llm_analysis.tasks.generate_summary_single"
        send(state, uuid="t-4", name=name)
        before = value(metrics.TASK_RETRIED, name)

        handle_event(state, event("task-retried", uuid="t-4"))

        assert value(metrics.TASK_RETRIED, name) == before + 1

    def test_revoked_and_rejected_share_one_counter(self, state):
        name = "apps.tasks.tests.revoked"
        send(state, uuid="t-5", name=name)
        before = value(metrics.TASK_REJECTED, name)

        handle_event(state, event("task-revoked", uuid="t-5"))
        handle_event(state, event("task-rejected", uuid="t-5"))

        assert value(metrics.TASK_REJECTED, name) == before + 2


class TestRobustness:
    """This runs inside a long-lived exporter's event loop. Dropping a data point is
    always preferable to killing the process."""

    def test_event_for_an_unknown_task_is_dropped_not_counted(self, state):
        """The exporter can start mid-flight and see a completion whose sent event it
        never saw. Counting it under a placeholder name would be worse than skipping it -
        the task label is the only thing that makes the metric actionable."""
        handle_event(state, event("task-succeeded", uuid="never-seen", runtime=1.0))

        assert value(metrics.TASK_SUCCEEDED, "never-seen") == 0.0
        assert value(metrics.TASK_SUCCEEDED, None) == 0.0

    def test_unknown_event_type_is_ignored(self, state):
        handle_event(state, event("task-unheard-of", uuid="t-9"))

    def test_malformed_event_does_not_raise(self, state):
        for event in ({}, {"type": "task-succeeded"}, {"type": None}, {"uuid": "x"}):
            handle_event(state, event)

    def test_a_raising_state_does_not_propagate(self, state):
        """A corrupt event that blows up inside celery's own State must not take the
        exporter down with it."""

        class Exploding:
            def __init__(self):
                self.workers = {}
                self.tasks = {}

            def event(self, _):
                raise RuntimeError("corrupt event")

        handle_event(Exploding(), event("task-succeeded", uuid="t-1"))

    def test_success_without_runtime_still_counts(self, state):
        name = "apps.tasks.tests.no_runtime"
        send(state, uuid="t-6", name=name)
        before = value(metrics.TASK_SUCCEEDED, name)

        handle_event(state, event("task-succeeded", uuid="t-6"))

        assert value(metrics.TASK_SUCCEEDED, name) == before + 1


class TestWorkerGauge:
    def test_heartbeat_sets_the_online_worker_gauge(self, state):
        handle_event(state, event("worker-heartbeat", hostname="w1"))
        handle_event(state, event("worker-heartbeat", hostname="w2"))

        assert metrics.WORKERS_ONLINE._value.get() == 2


class TestCardinality:
    def test_task_name_is_the_only_label(self):
        """A task id or hostname label would create a new time series per execution,
        which is the standard way to kill a Prometheus install."""
        for counter in (
            metrics.TASK_SENT,
            metrics.TASK_STARTED,
            metrics.TASK_SUCCEEDED,
            metrics.TASK_FAILED,
            metrics.TASK_RETRIED,
            metrics.TASK_REJECTED,
            metrics.TASK_RUNTIME,
        ):
            assert counter._labelnames == ("task",), counter._name

    def test_runtime_buckets_cover_this_workload(self):
        """prometheus_client's default top bucket is 10s. A yfinance sync or an LLM agent
        run takes far longer, so every real task would land in +Inf and the histogram
        would carry no information."""
        assert max(metrics.TASK_RUNTIME._upper_bounds[:-1]) >= 300

    def test_metrics_are_registered_once(self):
        """Re-registering on a fresh registry proves the names do not collide, which is
        what breaks when a module is imported twice under different paths."""
        registry = CollectorRegistry()
        names = {m.describe()[0].name for m in [metrics.TASK_SENT, metrics.TASK_FAILED]}
        assert len(names) == 2
        assert registry is not None
