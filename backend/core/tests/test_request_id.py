import logging

import pytest

from core.logging import RequestIDFilter, get_request_id
from core.middleware import RequestIDMiddleware


def build(get_response=None, header="X-Request-ID"):
    """Middleware instance with the header name pinned, independent of settings."""
    middleware = RequestIDMiddleware(get_response or (lambda request: DummyResponse()))
    middleware.header = header
    middleware.meta_key = "HTTP_" + header.upper().replace("-", "_")
    return middleware


class DummyResponse(dict):
    """Responses only need __setitem__ for the header echo."""


class DummyRequest:
    def __init__(self, **meta):
        self.META = meta


# ---------------------------------------------------------------------------
# Id generation and inbound handling
# ---------------------------------------------------------------------------


class TestRequestIDGeneration:
    def test_generates_an_id_when_the_header_is_absent(self):
        request = DummyRequest()
        response = build()(request)

        assert len(request.request_id) == 32, "expected a uuid4 hex"
        assert response["X-Request-ID"] == request.request_id

    def test_honours_a_well_formed_inbound_id(self):
        request = DummyRequest(HTTP_X_REQUEST_ID="upstream-abc_123")
        build()(request)

        assert request.request_id == "upstream-abc_123"

    def test_uses_the_configured_header_name(self):
        request = DummyRequest(HTTP_X_CORRELATION_ID="from-nginx")
        response = build(header="X-Correlation-ID")(request)

        assert request.request_id == "from-nginx"
        assert response["X-Correlation-ID"] == "from-nginx"

    @pytest.mark.parametrize(
        "hostile",
        [
            # A newline forges a second log line; a CR splits the HTTP response.
            'x\n{"level":"ERROR","message":"forged"}',
            "x\r\nSet-Cookie: pwned=1",
            "has spaces",
            'quote"inject',
            "a" * 65,
            "",
        ],
    )
    def test_rejects_hostile_inbound_ids_and_mints_a_fresh_one(self, hostile):
        request = DummyRequest(HTTP_X_REQUEST_ID=hostile)
        build()(request)

        assert request.request_id != hostile
        assert len(request.request_id) == 32


# ---------------------------------------------------------------------------
# ContextVar lifecycle
# ---------------------------------------------------------------------------


class TestContextVarLifecycle:
    def test_id_is_visible_to_log_records_during_the_request(self, caplog):
        seen = {}

        def view(request):
            logging.getLogger("apps.test").warning("inside")
            seen["ctx"] = get_request_id()
            return DummyResponse()

        with caplog.at_level(logging.WARNING):
            request = DummyRequest()
            build(view)(request)

        assert seen["ctx"] == request.request_id

    def test_context_is_cleared_after_the_request(self):
        build()(DummyRequest())

        assert get_request_id() == "", "the id must not leak into the next request"

    def test_context_is_cleared_even_when_the_view_raises(self):
        def exploding_view(request):
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            build(exploding_view)(DummyRequest())

        assert get_request_id() == ""


# ---------------------------------------------------------------------------
# Integration through the real stack
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRequestIDIntegration:
    def test_real_response_carries_the_header(self, api_client, settings):
        response = api_client.get("/api/health/")

        assert response[settings.REQUEST_ID_HEADER]

    def test_error_responses_logged_outside_the_chain_still_carry_the_id(self, api_client):
        """Django's BaseHandler.get_response logs every 4xx/5xx AFTER the middleware
        chain returns, so the ContextVar is already reset - yet error lines are the ones
        most worth correlating. RequestIDFilter recovers the id from the request object
        Django puts in the record's extra. A regression here silently strips the id from
        every error log line, which is the hardest kind of gap to notice."""
        captured = []

        class Capture(logging.Handler):
            def emit(self, record):
                RequestIDFilter().filter(record)
                captured.append(record)

        handler = Capture()
        logger = logging.getLogger("django.request")
        logger.addHandler(handler)
        try:
            api_client.get("/api/no-such-route/", HTTP_X_REQUEST_ID="err-correlation")
        finally:
            logger.removeHandler(handler)

        assert captured, "django.request logged nothing for a 404"
        assert captured[0].request_id == "err-correlation"

    def test_middleware_is_installed_first(self, settings):
        """Ahead of everything else, so a line logged by any other middleware still
        correlates. Phase 3 inserts PrometheusBeforeMiddleware above it."""
        assert "core.middleware.RequestIDMiddleware" in settings.MIDDLEWARE[:2]
