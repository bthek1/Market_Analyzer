"""Prometheus metrics derived from the Celery event stream.

Why this exists instead of an off-the-shelf exporter: PyPI's ``celery-exporter``
(OvalMoney) was last released in 2021 and pins ``celery>=4,<5``, so it cannot be
installed next to this project's Celery 5.x; the other well-known one
(danihodovic/celery-exporter) ships only as a Docker image, and the app container has no
Docker. Celery's own ``events`` API is a supported interface and this is a small amount
of code on top of it.

The event handling is deliberately separated from the connection loop (which lives in
the ``run_metrics_exporter`` command) so it can be driven directly from tests without a
broker.

CARDINALITY: the only label is the task name, which is bounded by the number of
``@shared_task`` functions in the codebase. Task ids, arguments and hostnames are NOT
labels - a task id label would create a new time series per execution, which is how a
Prometheus install dies.
"""

import logging

from prometheus_client import Counter, Gauge, Histogram

logger = logging.getLogger(__name__)

TASK_SENT = Counter(
    "celery_task_sent_total",
    "Tasks published to the broker.",
    ["task"],
)
TASK_STARTED = Counter(
    "celery_task_started_total",
    "Tasks picked up by a worker.",
    ["task"],
)
TASK_SUCCEEDED = Counter(
    "celery_task_succeeded_total",
    "Tasks that completed successfully.",
    ["task"],
)
TASK_FAILED = Counter(
    "celery_task_failed_total",
    "Tasks that raised.",
    ["task"],
)
TASK_RETRIED = Counter(
    "celery_task_retried_total",
    "Task retries.",
    ["task"],
)
TASK_REJECTED = Counter(
    "celery_task_rejected_total",
    "Tasks rejected or revoked before running.",
    ["task"],
)
TASK_RUNTIME = Histogram(
    "celery_task_runtime_seconds",
    "Wall-clock task runtime as reported by the worker.",
    ["task"],
    # Tuned for this workload, not the prometheus_client default: a yfinance sync or an
    # LLM agent run takes tens of seconds, so the default top bucket of 10s would put
    # almost every real task in +Inf and make the histogram useless.
    buckets=(0.1, 0.5, 1, 5, 15, 30, 60, 120, 300, 600),
)
WORKERS_ONLINE = Gauge(
    "celery_workers_online",
    "Workers currently sending heartbeats.",
)

# event type -> counter. Every one of these carries a task uuid we can resolve to a name.
_TASK_COUNTERS = {
    "task-sent": TASK_SENT,
    "task-started": TASK_STARTED,
    "task-succeeded": TASK_SUCCEEDED,
    "task-failed": TASK_FAILED,
    "task-retried": TASK_RETRIED,
    "task-rejected": TASK_REJECTED,
    "task-revoked": TASK_REJECTED,
}

TASK_EVENTS = tuple(_TASK_COUNTERS)


def handle_event(state, event: dict) -> None:
    """Fold one Celery event into the metrics.

    ``state`` is a ``celery.events.state.State``; it is what turns an event's bare uuid
    into a task name, because only ``task-sent``/``task-received`` carry the name and
    later events for the same task do not repeat it.

    Never raises: this runs inside the event loop of a long-lived exporter, and losing
    the whole process because one malformed event arrived would be a far worse outcome
    than dropping a data point.
    """
    try:
        state.event(event)
        event_type = event.get("type", "")

        if event_type == "worker-heartbeat":
            WORKERS_ONLINE.set(len([w for w in state.workers.values() if w.alive]))
            return

        counter = _TASK_COUNTERS.get(event_type)
        if counter is None:
            return

        task = state.tasks.get(event.get("uuid"))
        name = getattr(task, "name", None)
        if not name:
            # A task whose name we never saw - the exporter started mid-flight, or the
            # sent event was missed. Counting it under a placeholder would be worse than
            # skipping it, since the name is the only label that makes the metric useful.
            return

        counter.labels(task=name).inc()

        if event_type == "task-succeeded":
            runtime = event.get("runtime")
            if runtime is not None:
                TASK_RUNTIME.labels(task=name).observe(runtime)
    except Exception:
        logger.exception("failed to handle celery event", extra={"event_type": event.get("type")})
