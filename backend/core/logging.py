"""Structured JSON logging for the Grafana/Loki side of the observability stack.

Every log line is one JSON object on stdout. In production systemd captures stdout
into the journal, Grafana Alloy ships the journal to Loki, and Loki's ``| json``
filter makes each field queryable at query time WITHOUT indexing it. That is the
whole reason for the format, and it dictates where values go:

    label (Alloy)  -> bounded sets only: host, unit, level
    JSON body      -> everything else: request ids, tickers, user ids, run ids

Putting an unbounded value in a Loki label builds a new index stream per value and is
the standard way to melt a small Loki install; putting it in the body costs nothing.

``request_id`` rides in a ContextVar rather than being threaded through call
signatures, so a line emitted deep inside a service, serializer or ORM hook still
correlates back to the request that caused it. See ``core.middleware`` for the two
places that does NOT reach.
"""

import json
import logging
from contextvars import ContextVar, Token
from datetime import UTC
from datetime import datetime as dt

from core.tracing import current_trace_ids

# Empty string rather than None so the plain-text "console" formatter can interpolate
# %(request_id)s unconditionally.
_request_id: ContextVar[str] = ContextVar("request_id", default="")

# Attribute names LogRecord itself owns. Anything on a record beyond these came from a
# caller's extra={...} and is worth shipping, so the formatter forwards it verbatim.
# Derived from a throwaway record rather than hand-listed, so a new attribute in a
# future Python does not start leaking into every log line as a bogus "extra".
_RESERVED = frozenset(vars(logging.makeLogRecord({}))) | {
    "message",
    "asctime",
    "taskName",
    "request_id",
    # Stamped by RequestIDFilter and emitted explicitly below, so they must not also be
    # forwarded by the generic extra= sweep.
    "trace_id",
    "span_id",
}


def get_request_id() -> str:
    """The current request's correlation id, or "" outside a request."""
    return _request_id.get()


def set_request_id(request_id: str) -> Token[str]:
    """Bind a correlation id to this context; pass the token back to reset_request_id."""
    return _request_id.set(request_id)


def reset_request_id(token: Token[str]) -> None:
    """Restore whatever id was bound before the matching set_request_id."""
    _request_id.reset(token)


class RequestIDFilter(logging.Filter):
    """Stamp every record with the ContextVar's request id.

    A logging Filter, not a formatter concern: the id has to be read in the thread and
    context that emitted the record. Formatting can happen later, elsewhere.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = get_request_id() or self._from_record_request(record)
        if not hasattr(record, "trace_id"):
            record.trace_id, record.span_id = self._trace_ids(record)
        return True

    @staticmethod
    def _trace_ids(record: logging.LogRecord) -> tuple[str, str]:
        """The active span's ids, falling back to the ones stamped on the request.

        Read HERE, in a Filter, rather than in the formatter, for the same reason the
        request id is: the ids belong to the context that emitted the record, and
        formatting can happen later and elsewhere.

        The fallback is load-bearing. ``BaseHandler.get_response`` logs every 4xx/5xx
        after the middleware chain has unwound, so the span has already ended and
        ``get_current_span()`` returns an invalid one - leaving the error lines as the
        only ones with no trace to click through to. RequestIDMiddleware stashed the
        ids on the request while the span was live.
        """
        trace_id, span_id = current_trace_ids()
        if trace_id:
            return trace_id, span_id

        request = getattr(record, "request", None)
        return getattr(request, "trace_id", "") or "", getattr(request, "span_id", "") or ""

    @staticmethod
    def _from_record_request(record: logging.LogRecord) -> str:
        """Recover the id from a record's ``request`` extra when the context is gone.

        ``BaseHandler.get_response`` logs EVERY 4xx/5xx response after the middleware
        chain has returned, so by then RequestIDMiddleware has already reset the
        ContextVar - and those error lines are precisely the ones worth correlating.
        Django's ``log_response`` passes ``request`` in ``extra``, and the middleware
        stamped the id onto the request object, so it is still recoverable here.
        """
        return getattr(getattr(record, "request", None), "request_id", "") or ""


class JSONFormatter(logging.Formatter):
    """One JSON object per line, with caller ``extra`` fields merged in."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": dt.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = getattr(record, "request_id", "")
        if request_id:
            payload["request_id"] = request_id

        # Trace ids go in the BODY, never a Loki label - a trace id is the most
        # unbounded value in the system, one stream per request. Grafana's derived
        # field reads them back out at query time, which is what turns a log line into
        # a click-through to the trace in Tempo. Stamped by RequestIDFilter (which can
        # recover them after the span has ended); absent when tracing is off.
        trace_id = getattr(record, "trace_id", "")
        if trace_id:
            payload["trace_id"] = trace_id
            payload["span_id"] = getattr(record, "span_id", "")

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        for key, value in record.__dict__.items():
            if key not in _RESERVED:
                payload[key] = value

        # A formatter that raises turns one bad extra= into a stderr traceback for every
        # subsequent log call, so serialisation failure degrades to a still-parseable
        # line instead. default=repr covers ordinary objects; this catches the rest
        # (recursive structures, non-str dict keys).
        try:
            return json.dumps(payload, default=repr)
        except (TypeError, ValueError):
            return json.dumps(
                {
                    "timestamp": payload["timestamp"],
                    "level": payload["level"],
                    "logger": payload["logger"],
                    "message": record.getMessage(),
                    "logging_error": "payload was not JSON-serialisable",
                }
            )
