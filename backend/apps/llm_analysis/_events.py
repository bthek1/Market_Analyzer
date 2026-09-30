"""Shared SSE framing and terminal-run events for every agent workflow.

Each workflow module used to define its own ``_sse`` and ``_finish``: nine byte-identical
copies of each, and they had already drifted (``react`` framed without ``default=str``
while the other eight did not). The loop and the per-step payloads still belong to the
workflow; the framing and the two terminal events do not.

Every workflow ends the same two ways, so those are generators here rather than plain
helpers - a caller writes ``yield from fail(run, exc)`` and gets the DB write and the
event in the right order, once:

    run finished OK    -> ``succeed``: status done + a ``result`` event
    run finished badly -> ``fail``:    status error + an ``error`` event

``meta`` is the run's workflow-specific ``AgentRun.meta`` payload (validated by
``store``); keyword arguments are extra fields on the SSE event itself. They are separate
because several workflows persist a value without streaming it, or the reverse.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Generator

    from .models import AgentRun, AgentStep


def sse(payload: dict[str, Any]) -> str:
    """Frame one payload as an SSE ``data:`` line.

    ``default=str`` is deliberate: step payloads carry datetimes and UUIDs, and a
    TypeError here would kill the stream mid-run rather than degrade one field.
    """
    return f"data: {json.dumps(payload, default=str)}\n\n"


def event(name: str, **fields: Any) -> str:
    """Frame a named workflow event. ``event("plan", steps=[...])``."""
    return sse({"event": name, **fields})


def delta(text: str) -> str:
    """One incremental slice of an answer being written.

    Not a row and not a step: a delta corresponds to nothing persisted, and the finished
    text lands on the run's ``output`` like any other. It exists so an INTERACTIVE surface
    can render a reply as it is produced - every other workflow here is a batch run where
    time-to-last-token is the only figure that matters.
    """
    return event("delta", text=text)


def step_payload(step: AgentStep, *, kind: str | None = None) -> dict[str, Any]:
    """A step's DRF representation as a dict.

    Exists for ``chain``, whose SSE payload carries no ``event`` discriminator at all (the
    frontend keys off ``step_id``) and so cannot go through ``step_event``. It still has
    to be the SAME serialisation as the detail endpoint, which is what this shares.
    """
    from .serializers import step_serializer_for

    return dict(step_serializer_for(kind or step.run.kind)(step).data)


def step_event(step: AgentStep, name: str, *, kind: str | None = None, **extra: Any) -> str:
    """Frame a persisted ``AgentStep`` as its workflow's SSE step event.

    The payload IS the step's DRF representation, so the live stream and the detail
    endpoint cannot disagree about field names or values - they are one serialisation.
    They used to be written independently, and drifted: ``dag`` streamed ``id``/``args``
    while its detail endpoint returned ``node_id``/``tool_args``, so a refresh-restore
    silently dropped the tool arguments from the UI.

    ``kind`` lets a caller skip a ``step.run`` lookup when it already knows it.
    """
    return event(name, **step_payload(step, kind=kind), **extra)


def succeed(
    run: AgentRun,
    output: str,
    *,
    meta: dict[str, Any] | None = None,
    **event_fields: Any,
) -> Generator[str]:
    """Finish ``run`` successfully and yield its terminal ``result`` event."""
    from . import store

    store.finish_run(run, output=output, **(meta or {}))
    yield event("result", output=output, run_id=str(run.id), **event_fields)


def fail(
    run: AgentRun,
    error: str,
    *,
    output: str = "",
    meta: dict[str, Any] | None = None,
    **event_fields: Any,
) -> Generator[str]:
    """Finish ``run`` as errored and yield its terminal ``error`` event.

    ``output`` exists for the workflows that keep their best partial answer on the row
    even though the run failed (eval_opt keeps the best-scoring draft).
    """
    from . import store

    store.finish_run(run, output=output, error=error, **(meta or {}))
    yield event("error", error=error, **event_fields)
