"""OpenTelemetry tracing setup (issue #5 phase 3).

The third signal, alongside the JSON logs in ``core.logging`` and the Prometheus
metrics wired in ``core.settings.prod``. Spans go to Grafana Alloy's OTLP receiver on
the loopback, which batches and forwards them to Tempo on the observability host - the
same push shape as the other two, so the application never learns where Tempo lives.

WHY TRACES AND NOT MORE METRICS
-------------------------------
There is deliberately no per-call Ollama latency metric, because LLM calls happen in
gunicorn workers AND Celery prefork children, whose ``prometheus_client`` registries
cannot be merged without ``PROMETHEUS_MULTIPROC_DIR`` - a metric covering only the web
half would look complete while silently missing AI summaries and KG expansion. Spans
have no shared-registry problem: every process exports independently over OTLP and
Tempo reassembles a trace by its id. See ``docs/project_docs/observability.md``.

WHERE THIS IS CALLED FROM, AND WHY NOT ``AppConfig.ready()``
------------------------------------------------------------
``ready()`` runs in EVERY process that calls ``django.setup()`` - each management
command during a deploy, Celery beat, the metrics exporter, and every pytest worker.
That is exactly the trap that forced ``PROMETHEUS_METRICS_EXPORT_PORT_RANGE`` out of
``base.py``. So tracing is initialised from explicit entry points instead:

    core/wsgi.py    -> the gunicorn workers (web requests)
    core/celery.py  -> each prefork CHILD, via the worker_process_init signal

Celery's prefork pool is the subtle one. ``BatchSpanProcessor`` runs a background
thread, and threads do not survive ``fork()`` - a provider built in the parent yields a
child whose spans are queued and never flushed. Initialising per child is the only
arrangement that works.

EVERYTHING HERE IS BEST-EFFORT
------------------------------
Instrumentation must never take down a request. Every failure path degrades to "no
tracing" and logs, exactly like the domain-metrics collector's per-section guards.
"""

import logging
import os
import socket
from contextlib import contextmanager

from django.conf import settings

logger = logging.getLogger(__name__)

# Import-time failure is survivable: the dependency group could be absent in a slim
# install, and "no tracing" is a far better outcome than a web process that will not
# boot. _IMPORT_ERROR is surfaced once, by configure_tracing, rather than at import.
try:
    from opentelemetry import context as otel_context
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
    from opentelemetry.trace import Status, StatusCode

    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised only in a broken install
    _IMPORT_ERROR = exc

# Guards against building a second TracerProvider. Re-running the instrumentors would
# double-wrap Django's handler and report every span twice.
_configured = False


def is_configured() -> bool:
    """Whether this process has already installed a TracerProvider."""
    return _configured


def reset_for_tests() -> None:
    """Drop the once-per-process latch. Tests only."""
    global _configured
    _configured = False


def _build_resource(service_name: str) -> "Resource":
    """Identity attached to every span this process emits.

    ``host.name`` duplicates the ``host`` attribute Alloy stamps on the way past. That
    is deliberate: Alloy's is the trustworthy one (the app cannot lie about which box
    it runs on), while this one survives if the pipeline is ever pointed straight at
    Tempo without an agent in between.
    """
    return Resource.create(
        {
            "service.name": service_name,
            "service.namespace": "stockmarket",
            "host.name": socket.gethostname(),
            "deployment.environment": os.environ.get("DJANGO_SETTINGS_MODULE", "unknown").rsplit(
                ".", 1
            )[-1],
        }
    )


def _build_sampler(ratio: float) -> "ParentBased":
    """Head sampling, parent-respecting.

    ParentBased matters more than the ratio: without it a sampled parent can have
    unsampled children, which renders as a trace with holes in it - worse than no
    trace, because the gap looks like a gap in the SYSTEM rather than in the sampling.
    """
    return ParentBased(root=TraceIdRatioBased(max(0.0, min(1.0, ratio))))


def _instrument(exclude_django: bool) -> None:
    """Attach the auto-instrumentors, each independently guarded.

    One missing or incompatible instrumentation package must not cost the others: a
    Celery worker still wants DB and HTTP spans even if the Django one fails.
    """
    from opentelemetry.instrumentation.celery import CeleryInstrumentor
    from opentelemetry.instrumentation.django import DjangoInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor

    instrumentors = [
        ("psycopg", PsycopgInstrumentor),
        ("redis", RedisInstrumentor),
        # httpx is how services.py talks to Ollama, so this is what gives LLM calls a
        # span in BOTH the web and Celery halves - the gap the metrics design could
        # not close. Phase 4 adds richer manual spans on top.
        ("httpx", HTTPXClientInstrumentor),
        ("celery", CeleryInstrumentor),
    ]
    if not exclude_django:
        instrumentors.append(("django", DjangoInstrumentor))

    for name, instrumentor_cls in instrumentors:
        try:
            instrumentor_cls().instrument()
        except Exception:
            logger.warning("otel: %s instrumentation failed", name, exc_info=True)


def configure_tracing(service_name: str, *, exclude_django: bool = False) -> bool:
    """Install a TracerProvider for this process. Returns whether tracing is now on.

    Idempotent and safe to call from anywhere; never raises.
    """
    global _configured

    if _configured:
        return True

    if not getattr(settings, "OTEL_TRACES_ENABLED", False):
        return False

    if _IMPORT_ERROR is not None:
        logger.warning("otel: tracing enabled but the SDK is unavailable: %s", _IMPORT_ERROR)
        return False

    try:
        provider = TracerProvider(
            resource=_build_resource(service_name),
            sampler=_build_sampler(settings.OTEL_TRACES_SAMPLER_RATIO),
        )
        # insecure=True because the receiver is Alloy on the LOOPBACK - there is no
        # network hop to protect, and the LAN leg (Alloy -> Tempo) is unauthenticated
        # by the same trusted-network reasoning as loki.write and remote_write.
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT, insecure=True)
            )
        )
        trace.set_tracer_provider(provider)
        _instrument(exclude_django=exclude_django)
    except Exception:
        logger.warning("otel: tracing setup failed; continuing untraced", exc_info=True)
        return False

    _configured = True
    logger.info(
        "otel: tracing enabled",
        extra={
            "service_name": service_name,
            "endpoint": settings.OTEL_EXPORTER_OTLP_ENDPOINT,
            "sample_ratio": settings.OTEL_TRACES_SAMPLER_RATIO,
        },
    )
    return True


def current_trace_ids() -> tuple[str, str]:
    """``(trace_id, span_id)`` as lowercase hex, or ``("", "")`` outside a span.

    Used by ``core.logging.JSONFormatter`` to put the ids in the log body, which is
    what lets a Loki line link through to its trace in Tempo. Returns empty strings
    rather than raising, because it runs inside a log formatter - where an exception
    would turn one bad line into a stderr traceback for every subsequent log call.
    """
    if _IMPORT_ERROR is not None:
        return "", ""

    try:
        span = trace.get_current_span()
        context = span.get_span_context()
        if not context.is_valid:
            return "", ""
        return format(context.trace_id, "032x"), format(context.span_id, "016x")
    except Exception:
        return "", ""


# ---------------------------------------------------------------------------
# Manual spans (issue #5 phase 4)
#
# The auto-instrumentors give request, DB and raw-HTTP spans. These helpers add the
# structure that makes an AGENT RUN legible: which model, which tool, how many tokens,
# and what actually ran in parallel.
#
# High-cardinality attribute values (AgentRun ids, tickers, concept slugs) are FINE
# here - Tempo does not index span attributes the way Loki indexes labels, so they cost
# nothing. They must still never become Prometheus or Loki labels. See the cardinality
# note in docs/project_docs/observability.md.
# ---------------------------------------------------------------------------

_TRACER_NAME = "stockmarket"


def _set_attributes(span_obj, attributes: dict) -> None:
    """Best-effort attribute setting. None values are dropped rather than stringified."""
    for key, value in attributes.items():
        if value is None:
            continue
        try:
            span_obj.set_attribute(key, value)
        except Exception:
            # An unsupported type must not abort the caller's work.
            try:
                span_obj.set_attribute(key, repr(value))
            except Exception:
                pass


@contextmanager
def span(name: str, **attributes):
    """Start a span around a block of work. A no-op when tracing is unavailable.

    Yields the span (or None) so the caller can attach attributes it only learns later -
    token counts, result sizes - without a second lookup.

    Never raises: this wraps real work, and an observability failure must not become an
    application failure.
    """
    if _IMPORT_ERROR is not None:
        yield None
        return

    try:
        tracer = trace.get_tracer(_TRACER_NAME)
    except Exception:
        yield None
        return

    with tracer.start_as_current_span(name) as span_obj:
        _set_attributes(span_obj, attributes)
        yield span_obj


def set_attributes(span_obj, **attributes) -> None:
    """Attach attributes to a span returned by ``span()``. Tolerates None."""
    if span_obj is None:
        return
    _set_attributes(span_obj, attributes)


def record_error(span_obj, exc: BaseException) -> None:
    """Mark a span as failed. Tolerates a no-op span."""
    if span_obj is None or _IMPORT_ERROR is not None:
        return
    try:
        span_obj.record_exception(exc)
        span_obj.set_status(Status(StatusCode.ERROR, str(exc)))
    except Exception:
        pass


def current_context():
    """Capture the active OTel context so another THREAD can continue this trace.

    OTel context rides a ContextVar, and a bare ``threading.Thread`` does not inherit
    one. Without this a span started in the new thread becomes its own root trace -
    which is exactly how the daemon thread in ``stream_in_background`` and the pool in
    ``chat_many`` would otherwise lose their parent. Same root cause as the two
    ``request_id`` propagation gaps documented in ``core.middleware``.
    """
    if _IMPORT_ERROR is not None:
        return None
    try:
        return otel_context.get_current()
    except Exception:
        return None


@contextmanager
def attached(ctx):
    """Re-attach a context captured by ``current_context()`` inside another thread."""
    if ctx is None or _IMPORT_ERROR is not None:
        yield
        return

    token = None
    try:
        token = otel_context.attach(ctx)
        yield
    finally:
        if token is not None:
            try:
                otel_context.detach(token)
            except Exception:
                pass


@contextmanager
def step_span(run, order, *, key: str = "", label: str = "", **extra):
    """A span for ONE agent step, nested inside the run's ``agent.run`` span.

    Carries the run's identity as well as the step's, because a span is only useful if
    you can get from it back to the thing that produced it, and Tempo does not join.
    All of these are high-cardinality-safe: span attributes are not indexed the way Loki
    labels are. They must NOT become Tempo span-metric dimensions for the same reason -
    see the dimension allow-list in infra/observability/tempo/config.yml.
    """
    attributes = {
        "agent.run_id": str(getattr(run, "pk", "")) or None,
        "agent.kind": getattr(run, "kind", None),
        "agent.step_order": order,
        "agent.step_key": key or None,
        "agent.step_label": label or None,
    }
    attributes.update(extra)
    with span("agent.step", **attributes) as span_obj:
        yield span_obj


# Set once the first time a step span fails, so the warning is not repeated per step.
_RECORD_STEP_WARNED = False


def record_completed_step(run, step) -> None:
    """Emit an ``agent.step`` span for a step that has ALREADY finished.

    Most workflows mark a step running, do the work, then mark it done - recording real
    ``started_at`` / ``completed_at`` timestamps on the row. Replaying those as a span
    with explicit start and end times is both simpler and MORE accurate than wrapping
    the call site: the duration is the step's own, not a wrapper's, and one choke point
    in ``store.update_step`` covers every workflow that follows the pattern.

    The span is parented to whatever is active when the step completes - inside the
    run's ``agent.run`` span - so it still lands in the right place in the waterfall.

    Silent no-op when tracing is off, when the timestamps are absent, or on any error:
    this runs inside a DB write path and must never affect it.
    """
    if _IMPORT_ERROR is not None:
        return

    try:
        # Inside the try: a model property that raises must not escape into the caller's
        # save() path, and getattr's default does NOT swallow an exception raised by a
        # property - it propagates.
        started = getattr(step, "started_at", None)
        completed = getattr(step, "completed_at", None)
        if started is None or completed is None:
            return

        tracer = trace.get_tracer(_TRACER_NAME)
        span_obj = tracer.start_span(
            "agent.step", start_time=int(started.timestamp() * 1_000_000_000)
        )
        # Positional dict, NOT **kwargs: these keys contain dots and cannot be keyword
        # arguments. Passing them as kwargs raises TypeError, which the guard below
        # would swallow - leaving this function silently emitting nothing at all.
        _set_attributes(
            span_obj,
            {
                "agent.run_id": str(getattr(run, "pk", "")) or None,
                "agent.kind": getattr(run, "kind", None),
                "agent.step_order": getattr(step, "order", None),
                "agent.step_key": getattr(step, "key", None) or None,
                "agent.step_label": getattr(step, "label", None) or None,
                "agent.step_status": getattr(step, "status", None),
            },
        )
        if getattr(step, "error", ""):
            span_obj.set_status(Status(StatusCode.ERROR, step.error[:200]))
        span_obj.end(end_time=int(completed.timestamp() * 1_000_000_000))
    except Exception:
        # Warn ONCE, then stay quiet. A bare `pass` here hid a real TypeError during
        # development - the dotted attribute keys were passed as **kwargs, so this
        # function silently emitted nothing at all and looked like it worked. But it
        # runs per step, so logging every time would flood the journal of a system that
        # is already misbehaving.
        global _RECORD_STEP_WARNED
        if not _RECORD_STEP_WARNED:
            _RECORD_STEP_WARNED = True
            logger.warning("otel: agent.step span could not be recorded", exc_info=True)
