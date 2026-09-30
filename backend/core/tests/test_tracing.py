"""Tracing wiring (issue #5 phase 3).

Two classes of invariant, both of which fail silently in opposite directions.

The dangerous one is tracing switching itself ON where it must not: a TracerProvider
built in a pytest worker starts a BatchSpanProcessor thread and an OTLP exporter, which
makes the suite depend on a reachable collector and slows every process that merely
imports settings. This is the same trap that kept the Prometheus port range out of
``base.py`` (see ``test_prometheus_wiring.py``) - and there it reached production.

The other is tracing quietly NOT working: a renamed log field breaks the Loki -> Tempo
pivot with no error anywhere, and instrumentation that raises would take a request down
rather than degrading.
"""

import json
import logging
from unittest.mock import patch

import pytest
from django.test import override_settings

from core import tracing
from core.logging import JSONFormatter, RequestIDFilter


@pytest.fixture(autouse=True)
def _reset_latch():
    """configure_tracing latches once per process; undo it between tests.

    Instrumentors are process-global, so they must be unwound too - otherwise the first
    test to enable tracing leaves Django instrumented and every later one sees
    "Attempting to instrument while already instrumented" and silently no-ops.
    """
    tracing.reset_for_tests()
    yield
    tracing.reset_for_tests()
    for module, name in (
        ("django", "DjangoInstrumentor"),
        ("psycopg", "PsycopgInstrumentor"),
        ("redis", "RedisInstrumentor"),
        ("httpx", "HTTPXClientInstrumentor"),
        ("celery", "CeleryInstrumentor"),
    ):
        try:
            instrumentor = getattr(
                __import__(f"opentelemetry.instrumentation.{module}", fromlist=[name]), name
            )
            instrumentor().uninstrument()
        except Exception:
            pass


def make_record(**extra):
    record = logging.makeLogRecord({"name": "core.test", "levelname": "INFO", "msg": "hello"})
    for key, value in extra.items():
        setattr(record, key, value)
    return record


class TestDisabledByDefault:
    def test_the_test_settings_force_tracing_off(self, settings):
        """The load-bearing assertion in this file. If this fails, every pytest worker
        starts an exporter - and `pytest -n 2` would do it twice over."""
        assert settings.OTEL_TRACES_ENABLED is False

    def test_configure_is_a_noop_when_disabled(self):
        assert tracing.configure_tracing("svc") is False
        assert tracing.is_configured() is False

    @override_settings(OTEL_TRACES_ENABLED=True)
    def test_configure_does_not_raise_when_the_collector_is_unreachable(self):
        """The exporter connects lazily, so setup succeeds with nothing listening. What
        matters is that a bad endpoint can never propagate into a request."""
        with override_settings(OTEL_EXPORTER_OTLP_ENDPOINT="http://127.0.0.1:1"):
            assert tracing.configure_tracing("svc") is True

    @override_settings(OTEL_TRACES_ENABLED=True)
    def test_setup_failure_degrades_to_untraced_rather_than_raising(self):
        """Instrumentation must never take down a process it was only observing."""
        with patch.object(tracing, "TracerProvider", side_effect=RuntimeError("boom")):
            assert tracing.configure_tracing("svc") is False
        assert tracing.is_configured() is False

    @override_settings(OTEL_TRACES_ENABLED=True)
    def test_a_failing_instrumentor_does_not_abort_the_others(self):
        """A Celery child still wants DB and HTTP spans even if one package is broken,
        so each instrumentor is guarded individually rather than as a block."""
        calls = []

        class Boom:
            def instrument(self):
                calls.append("boom")
                raise RuntimeError("this package is broken")

        class Fine:
            def instrument(self):
                calls.append("fine")

        # Boom is first, so a shared try/except would stop before Fine ever ran.
        with patch("opentelemetry.instrumentation.psycopg.PsycopgInstrumentor", Boom):
            with patch("opentelemetry.instrumentation.redis.RedisInstrumentor", Fine):
                assert tracing.configure_tracing("svc") is True

        assert calls[:2] == ["boom", "fine"], "a failing instrumentor blocked the next one"

    @override_settings(OTEL_TRACES_ENABLED=True)
    def test_configure_is_idempotent(self):
        """A second TracerProvider would double-wrap the handler and report every span
        twice, which reads as a load problem rather than a config one."""
        assert tracing.configure_tracing("svc") is True
        with patch.object(tracing, "TracerProvider") as provider:
            assert tracing.configure_tracing("svc") is True
        assert not provider.called


class TestSampler:
    @pytest.mark.parametrize(
        ("configured", "effective"),
        [(-5.0, 0.0), (0.0, 0.0), (0.25, 0.25), (1.0, 1.0), (99.0, 1.0)],
    )
    def test_ratio_is_clamped_into_0_1(self, configured, effective):
        """A ratio outside 0..1 is a config typo. OTel accepts a rate above 1 and then
        samples everything, so the mistake looks like it worked."""
        sampler = tracing._build_sampler(configured)

        assert sampler._root.rate == effective

    def test_sampling_is_parent_based(self):
        """Without ParentBased a sampled parent can have unsampled children, which
        renders as a trace with holes - worse than no trace, because the gap looks like
        a gap in the SYSTEM rather than in the sampling."""
        sampler = tracing._build_sampler(0.5)

        assert "ParentBased" in sampler.__class__.__name__


class TestLogCorrelation:
    """The JSON log body is what Grafana's derived field reads to build the pivot."""

    def test_no_trace_ids_outside_a_span(self):
        assert tracing.current_trace_ids() == ("", "")

    def test_formatter_omits_trace_fields_when_untraced(self):
        """Tracing ships off, so the common case must not add empty keys to every line."""
        payload = json.loads(JSONFormatter().format(make_record()))

        assert "trace_id" not in payload
        assert "span_id" not in payload

    def test_filter_then_formatter_emits_both_ids_when_a_span_is_active(self):
        record = make_record()
        with patch("core.logging.current_trace_ids", return_value=("abc123", "def456")):
            RequestIDFilter().filter(record)
        payload = json.loads(JSONFormatter().format(record))

        assert payload["trace_id"] == "abc123"
        assert payload["span_id"] == "def456"

    def test_ids_are_read_by_the_filter_not_the_formatter(self):
        """They belong to the context that EMITTED the record; formatting can happen
        later and on another thread, where the span is long gone."""
        record = make_record()
        with patch("core.logging.current_trace_ids", return_value=("abc123", "def456")):
            RequestIDFilter().filter(record)

        # Span gone by formatting time - the ids must already be on the record.
        with patch("core.logging.current_trace_ids", return_value=("", "")):
            payload = json.loads(JSONFormatter().format(record))

        assert payload["trace_id"] == "abc123"

    def test_error_lines_recover_the_ids_from_the_request(self):
        """REGRESSION (found in prod). BaseHandler.get_response logs every 4xx/5xx AFTER
        the middleware chain unwinds, so the span has ended and get_current_span()
        returns an invalid one. Without this fallback the error lines - the ones most
        worth correlating - are the only ones with no trace to click through to.
        Verified in prod: `Not Found: /api/companies/ZZZZNOTREAL/` carried a request_id
        and trace_id=None. Exactly the rescue request_id already needed."""

        class FakeRequest:
            request_id = "req-9"
            trace_id = "t-from-request"
            span_id = "s-from-request"

        record = make_record(request=FakeRequest())
        with patch("core.logging.current_trace_ids", return_value=("", "")):
            RequestIDFilter().filter(record)
        payload = json.loads(JSONFormatter().format(record))

        assert payload["trace_id"] == "t-from-request"
        assert payload["span_id"] == "s-from-request"

    def test_an_active_span_wins_over_the_request_fallback(self):
        """The fallback is a rescue, not the primary source - a nested span must report
        its own id rather than the request's root one."""

        class FakeRequest:
            trace_id = "stale"
            span_id = "stale"

        record = make_record(request=FakeRequest())
        with patch("core.logging.current_trace_ids", return_value=("live", "live-span")):
            RequestIDFilter().filter(record)

        assert record.trace_id == "live"

    def test_middleware_stamps_the_ids_while_the_span_is_live(self):
        """The other half of the rescue: the OTel middleware sits outside this one, so
        its span is readable here and nowhere later."""
        from core.middleware import RequestIDMiddleware

        class FakeRequest:
            def __init__(self):
                self.META = {}

        request = FakeRequest()
        with patch("core.middleware.current_trace_ids", return_value=("t1", "s1")):
            RequestIDMiddleware(lambda _r: {})(request)

        assert request.trace_id == "t1"
        assert request.span_id == "s1"

    def test_request_id_still_works_alongside_trace_ids(self):
        """request_id is the pivot that ALWAYS exists - the SSE streaming paths have no
        span to link to - so it must not be displaced by the trace fields."""
        record = make_record(request_id="req-1")
        with patch("core.logging.current_trace_ids", return_value=("abc", "def")):
            RequestIDFilter().filter(record)
        payload = json.loads(JSONFormatter().format(record))

        assert payload["request_id"] == "req-1"
        assert payload["trace_id"] == "abc"

    def test_ids_are_not_duplicated_into_the_extra_sweep(self):
        """The formatter forwards every non-reserved record attribute; trace_id/span_id
        are emitted explicitly, so they must be reserved or they appear twice."""
        record = make_record()
        with patch("core.logging.current_trace_ids", return_value=("abc", "def")):
            RequestIDFilter().filter(record)
        raw = JSONFormatter().format(record)

        assert raw.count('"trace_id"') == 1

    def test_trace_id_lookup_never_raises_into_the_formatter(self):
        """It runs inside a log formatter: an exception there turns one bad line into a
        stderr traceback for every subsequent log call in the process."""
        with patch.object(tracing.trace, "get_current_span", side_effect=RuntimeError("boom")):
            assert tracing.current_trace_ids() == ("", "")

    def test_ids_are_rendered_as_the_hex_grafana_expects(self):
        """Grafana matches the raw hex out of the log body; an int or a 0x prefix would
        produce a link that resolves to nothing."""

        class FakeContext:
            is_valid = True
            trace_id = 0x0123456789ABCDEF0123456789ABCDEF
            span_id = 0x0123456789ABCDEF

        with patch.object(tracing.trace, "get_current_span") as get_span:
            get_span.return_value.get_span_context.return_value = FakeContext()
            trace_id, span_id = tracing.current_trace_ids()

        assert trace_id == "0123456789abcdef0123456789abcdef"
        assert span_id == "0123456789abcdef"
        assert len(trace_id) == 32
        assert len(span_id) == 16


class TestEntryPoints:
    """WHERE configure_tracing is called from is the whole design, so it is pinned."""

    def test_wsgi_configures_tracing(self):
        """gunicorn imports wsgi.py, and only gunicorn does - which is exactly the set
        of processes that should export web spans."""
        from pathlib import Path

        text = (Path(tracing.__file__).parent / "wsgi.py").read_text()

        assert "configure_tracing" in text

    def test_wsgi_instruments_before_building_the_application(self):
        """REGRESSION (found in prod). DjangoInstrumentor does not wrap a handler, it
        INSERTS middleware into settings.MIDDLEWARE - and get_wsgi_application() builds a
        WSGIHandler whose __init__ calls load_middleware(), resolving that list exactly
        once. Instrumenting afterwards mutates a list nobody reads again: psycopg spans
        still arrive, but with no request span above them, so every DB query becomes its
        own root trace. Observed as 5 traces all rooted at "SELECT", 0 server spans.
        """
        from pathlib import Path

        text = (Path(tracing.__file__).parent / "wsgi.py").read_text()
        # Comments stripped: the explanation above the call names both symbols, and a
        # raw substring search would read the prose as the ordering.
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))

        assert code.index("configure_tracing(") < code.index("get_wsgi_application()")

    @override_settings(OTEL_TRACES_ENABLED=True)
    def test_instrumenting_actually_inserts_django_middleware(self):
        """The mechanism the ordering test depends on. If a future OTel release stops
        touching MIDDLEWARE, the source-order assertion above would keep passing while
        meaning nothing - so assert the effect too."""
        from django.conf import settings as django_settings

        before = list(django_settings.MIDDLEWARE)
        try:
            assert tracing.configure_tracing("svc") is True
            added = [m for m in django_settings.MIDDLEWARE if m not in before]

            assert any("opentelemetry" in m for m in added), (
                f"instrument() added no OTel middleware; MIDDLEWARE unchanged: {added}"
            )
        finally:
            django_settings.MIDDLEWARE = before

    def test_prometheus_middleware_stays_outermost_of_the_app_chain(self):
        """The OTel middleware inserts at position 0, i.e. OUTSIDE django-prometheus.
        That is harmless and deliberate: nothing prometheus previously measured moves
        outside its pair, so its latency coverage is unchanged - it simply does not count
        OTel's own overhead. Pinned so the interaction is a decision, not an accident."""
        from django.conf import settings as django_settings

        chain = [m for m in django_settings.MIDDLEWARE if "opentelemetry" not in m]

        assert chain[0] == "django_prometheus.middleware.PrometheusBeforeMiddleware"
        assert chain[-1] == "django_prometheus.middleware.PrometheusAfterMiddleware"

    def test_celery_configures_tracing_per_prefork_child(self):
        """BatchSpanProcessor's thread does not survive fork(), so a provider built in
        the parent leaves every child queueing spans that are never flushed."""
        from pathlib import Path

        text = (Path(tracing.__file__).parent / "celery.py").read_text()

        assert "worker_process_init" in text
        assert "exclude_django=True" in text

    def test_no_app_config_ready_hook_initialises_tracing(self):
        """ready() runs in EVERY process calling django.setup() - each management
        command during a deploy, and every pytest worker. That is exactly why the
        Prometheus port range had to leave base.py."""
        from pathlib import Path

        backend = Path(tracing.__file__).resolve().parents[1]
        for apps_py in backend.glob("apps/*/apps.py"):
            assert "configure_tracing" not in apps_py.read_text(), apps_py


class TestProdRollout:
    """How OTEL_* actually reaches the running processes."""

    def tasks(self):
        from pathlib import Path

        import yaml

        repo = Path(__file__).resolve().parents[3]
        return yaml.safe_load(
            (repo / "infra/ansible/roles/deploy/tasks/main.yml").read_text()
        ), repo

    def env_task(self):
        tasks, _ = self.tasks()
        return next(t for t in tasks if t["name"] == "Write .env from vault")

    def test_env_file_task_is_tagged_observability(self):
        """Otherwise `just obs-deploy` writes the Grafana half of phase 3 while the app
        keeps running without OTEL_TRACES_ENABLED - traces silently never appear."""
        tags = self.env_task().get("tags", [])
        tags = [tags] if isinstance(tags, str) else tags

        assert "observability" in tags

    def test_env_file_change_restarts_the_processes_that_read_it(self):
        """systemd reads EnvironmentFile at unit START. Without a restart the file on
        disk is correct while both services run on the old environment."""
        notify = self.env_task().get("notify", [])
        notify = [notify] if isinstance(notify, str) else notify

        assert "restart api" in notify
        assert "restart celery" in notify

    def test_the_tracing_flag_may_live_in_the_shared_env_file(self):
        """The INVERSE of the Prometheus rule, and the reason is the whole design:
        PROMETHEUS_EXPORT_WORKER_PORTS binds ports from AppConfig.ready() in every
        process calling django.setup(), so it must stay in the gunicorn unit. Tracing
        starts only where wsgi.py / celery.py explicitly call configure_tracing(), so a
        management command reading this value does nothing with it."""
        _, repo = self.tasks()
        env_j2 = (repo / "infra/ansible/roles/deploy/templates/env.j2").read_text()
        assignments = [
            line.split("=", 1)[0].strip()
            for line in env_j2.splitlines()
            if "=" in line and not line.lstrip().startswith("#")
        ]

        assert "OTEL_TRACES_ENABLED" in assignments
        assert "PROMETHEUS_EXPORT_WORKER_PORTS" not in assignments
