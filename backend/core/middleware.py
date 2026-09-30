"""Request-scoped middleware. Currently just correlation ids.

A correlation id turns "this request was slow" into "here is every log line it
produced". Alloy ships the id in the JSON body, and the Loki datasource carries a
derived field that pivots one line into the whole request.

Since issue #5 this also carries the TRACE ids, for a reason that is not obvious: the
OpenTelemetry span is gone by the time Django logs a 4xx/5xx, so the error lines - the
ones actually worth correlating - would otherwise be the only ones with no trace to
click through to. Stamping them on the request here, while the span is still active,
is what lets ``RequestIDFilter`` recover them afterwards. Exactly the same rescue the
request id already needed.
"""

import re
import uuid

from django.conf import settings

from core.logging import reset_request_id, set_request_id
from core.tracing import current_trace_ids

# An inbound id lands in log lines and in a response header, so it is untrusted input on
# two injection paths at once: a newline would forge a second log line, a CR would split
# the HTTP response. Allow only an opaque token and regenerate anything else.
_VALID_REQUEST_ID = re.compile(r"\A[A-Za-z0-9_-]{1,64}\Z")


class RequestIDMiddleware:
    """Bind a correlation id for the duration of the request.

    Honours an inbound header when it is well-formed (so a caller can correlate across
    services) and mints a uuid4 hex otherwise. Always echoes the id back on the
    response, which is what lets a user paste it into a bug report.

    Two known gaps, both inherent to a ContextVar bound around get_response:

    - ``StreamingHttpResponse`` bodies are consumed AFTER middleware returns, so lines
      emitted while a stream is producing have no id. That covers every SSE agent
      endpoint.
    - ``services.stream_in_background`` drives its workflow on a daemon thread, which
      does not inherit this context at all.

    Agent runs are correlated by their ``AgentRun`` id instead, which is persisted and
    already in the SSE payloads.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.header = getattr(settings, "REQUEST_ID_HEADER", "X-Request-ID")
        self.meta_key = "HTTP_" + self.header.upper().replace("-", "_")

    def __call__(self, request):
        request_id = self._incoming_id(request) or uuid.uuid4().hex
        request.request_id = request_id

        # The OTel middleware sits OUTSIDE this one, so its span is active here and its
        # ids are readable. They are stashed on the request because BaseHandler logs
        # every 4xx/5xx after the whole chain has unwound, when the span has ended.
        # Empty strings when tracing is off, which costs nothing.
        request.trace_id, request.span_id = current_trace_ids()

        token = set_request_id(request_id)
        try:
            response = self.get_response(request)
        finally:
            reset_request_id(token)

        response[self.header] = request_id
        return response

    def _incoming_id(self, request) -> str:
        candidate = request.META.get(self.meta_key, "")
        return candidate if _VALID_REQUEST_ID.match(candidate) else ""
