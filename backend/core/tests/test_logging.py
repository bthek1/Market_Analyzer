import json
import logging

import pytest

from core.logging import (
    JSONFormatter,
    RequestIDFilter,
    get_request_id,
    reset_request_id,
    set_request_id,
)


@pytest.fixture
def formatter():
    return JSONFormatter()


def make_record(**kwargs):
    """A LogRecord with sensible defaults, plus anything the test overrides."""
    defaults = {
        "name": "apps.companies",
        "level": logging.INFO,
        "pathname": "/app/views.py",
        "lineno": 42,
        "msg": "synced %s",
        "args": ("AAPL",),
        "exc_info": None,
    }
    defaults.update(kwargs)
    return logging.LogRecord(func=None, **defaults)


# ---------------------------------------------------------------------------
# JSONFormatter
# ---------------------------------------------------------------------------


class TestJSONFormatter:
    def test_emits_parseable_json_with_required_fields(self, formatter):
        payload = json.loads(formatter.format(make_record()))

        assert payload["level"] == "INFO"
        assert payload["logger"] == "apps.companies"
        # %-args are interpolated, not left as a template.
        assert payload["message"] == "synced AAPL"
        assert payload["timestamp"].endswith("+00:00"), "timestamp must be UTC-aware"

    def test_request_id_included_when_set(self, formatter):
        record = make_record()
        record.request_id = "abc123"

        assert json.loads(formatter.format(record))["request_id"] == "abc123"

    def test_request_id_omitted_when_absent_or_blank(self, formatter):
        blank = make_record()
        blank.request_id = ""

        assert "request_id" not in json.loads(formatter.format(make_record()))
        assert "request_id" not in json.loads(formatter.format(blank))

    def test_exception_is_formatted_into_the_payload(self, formatter):
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record = make_record(msg="failed", args=(), exc_info=sys.exc_info())

        payload = json.loads(formatter.format(record))
        assert "ValueError: boom" in payload["exception"]
        # The traceback must not leak into message - Loki indexes on the body shape.
        assert payload["message"] == "failed"

    def test_extra_fields_are_forwarded(self, formatter):
        record = make_record()
        record.symbol = "MSFT"
        record.duration_ms = 12.5

        payload = json.loads(formatter.format(record))
        assert payload["symbol"] == "MSFT"
        assert payload["duration_ms"] == 12.5

    def test_standard_record_attributes_are_not_leaked_as_extras(self, formatter):
        payload = json.loads(formatter.format(make_record()))

        # Noise that would otherwise be on every single line.
        for noise in ("msg", "args", "pathname", "lineno", "levelno", "created"):
            assert noise not in payload

    def test_unserialisable_extra_does_not_raise(self, formatter):
        class Opaque:
            def __repr__(self):
                return "<opaque>"

        record = make_record()
        record.thing = Opaque()

        payload = json.loads(formatter.format(record))
        assert payload["thing"] == "<opaque>"

    def test_recursive_extra_degrades_to_a_parseable_line(self, formatter):
        # json.dumps(default=repr) cannot save a self-referential container; the
        # formatter must still produce valid JSON rather than blow up the log call.
        recursive: list = []
        recursive.append(recursive)

        record = make_record(msg="cycle", args=())
        record.thing = recursive

        payload = json.loads(formatter.format(record))
        assert payload["message"] == "cycle"
        assert payload["logging_error"]


# ---------------------------------------------------------------------------
# RequestIDFilter / ContextVar
# ---------------------------------------------------------------------------


class TestRequestIDFilter:
    def test_stamps_the_context_id_onto_the_record(self):
        token = set_request_id("ctx-id")
        try:
            record = make_record()
            assert RequestIDFilter().filter(record) is True
            assert record.request_id == "ctx-id"
        finally:
            reset_request_id(token)

    def test_stamps_blank_outside_a_request(self):
        record = make_record()
        RequestIDFilter().filter(record)

        # Blank rather than missing, so the console formatter can interpolate it.
        assert record.request_id == ""

    def test_does_not_clobber_an_explicit_id(self):
        record = make_record()
        record.request_id = "explicit"

        token = set_request_id("ctx-id")
        try:
            RequestIDFilter().filter(record)
        finally:
            reset_request_id(token)

        assert record.request_id == "explicit"

    def test_reset_restores_the_previous_value(self):
        assert get_request_id() == ""

        token = set_request_id("first")
        assert get_request_id() == "first"
        reset_request_id(token)

        assert get_request_id() == ""


# ---------------------------------------------------------------------------
# Settings wiring
# ---------------------------------------------------------------------------


class TestLoggingSettings:
    def test_console_formatter_can_interpolate_request_id(self, settings):
        """The console format string references %(request_id)s, which only exists
        because the filter puts it there - so the two must stay wired together."""
        config = settings.LOGGING
        assert "request_id" in config["handlers"]["stdout"]["filters"]
        assert "%(request_id)s" in config["formatters"]["console"]["format"]

    def test_every_logger_has_the_stdout_handler(self, settings):
        for name, logger in settings.LOGGING["loggers"].items():
            assert logger["handlers"] == ["stdout"], name
            # Each carries its own handler, so propagating would duplicate the line.
            assert logger["propagate"] is False, name

    def test_configured_formatter_exists(self, settings):
        assert settings.LOGGING["handlers"]["stdout"]["formatter"] in settings.LOGGING["formatters"]
