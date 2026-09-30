import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def user(db):
    return User.objects.create_user(email="test@example.com", password="testpass123")


@pytest.fixture
def auth_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def llm_settings(monkeypatch):
    """In-memory LLMSettings singleton for tests that read LLM config without a DB.

    Patches ``LLMSettings.get_solo`` (the single point ``get_llm_config`` calls) to
    return an unsaved instance carrying the model field defaults. Tests can mutate the
    returned object to exercise non-default configuration.
    """
    from apps.llm_analysis.models import LLMSettings

    cfg = LLMSettings()
    monkeypatch.setattr(LLMSettings, "get_solo", classmethod(lambda cls: cfg))
    return cfg


@pytest.fixture
def spans():
    """A real OTel provider exporting into memory, installed for one test.

    Yields the EXPORTER - call ``.get_finished_spans()``. ``trace.set_tracer_provider()``
    only takes effect once per process, so the provider is swapped directly; otherwise the
    second test to use this would silently record into the first one's exporter.

    Lives here rather than beside one test module because two suites need it: the tracing
    tests in ``core/`` and the agent-runtime tests in ``apps/llm_analysis/``, which assert
    that a step's LLM calls nest INSIDE its span.
    """
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    original = trace.get_tracer_provider()
    trace._TRACER_PROVIDER = provider
    try:
        yield exporter
    finally:
        trace._TRACER_PROVIDER = original
