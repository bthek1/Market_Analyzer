"""Persistence service layer for AgentRun / AgentStep ``meta``.

The ONLY module that constructs or mutates ``AgentRun.meta`` / ``AgentStep.meta``.
Every write is validated against the kind's spec in ``meta_spec.py`` before it touches
the DB, so the JSON stays structured. Workflows call these helpers instead of setting
model attributes directly.

Writes are meta-only: the legacy typed columns are left at their defaults and are
dropped in the final phase of the refactor. Reads go through ``run_meta`` / ``step_meta``,
which layer the kind's declared defaults under the stored values.
"""

from __future__ import annotations

from datetime import UTC
from datetime import datetime as dt
from typing import TYPE_CHECKING, Any

from core.tracing import record_completed_step

from . import meta_spec

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.contrib.auth import get_user_model

    from .models import AgentRun, AgentStep

_UNSET = object()


# --- read accessors -----------------------------------------------------------------------


class MetaView:
    """Read-only attribute/`.get()` view over a meta dict with the kind's defaults applied.

    ``run_meta(run).max_steps`` returns the stored value or the spec default (or None for
    a key with no declared default / not in the spec)."""

    __slots__ = ("_d",)

    def __init__(self, data: dict[str, Any]):
        object.__setattr__(self, "_d", data)

    def __getattr__(self, name: str) -> Any:
        return self._d.get(name)

    def get(self, name: str, default: Any = None) -> Any:
        return self._d.get(name, default)

    def as_dict(self) -> dict[str, Any]:
        return dict(self._d)


def run_meta(run: AgentRun) -> MetaView:
    return MetaView({**meta_spec.run_defaults(run.kind), **(run.meta or {})})


def step_meta(step: AgentStep, kind: str | None = None) -> MetaView:
    # ``kind`` lets callers avoid a step.run lookup when they already know it.
    k = kind or step.run.kind
    return MetaView({**meta_spec.step_defaults(k), **(step.meta or {})})


# --- run writes ---------------------------------------------------------------------------


def create_run(
    user: get_user_model(),
    query: str,
    model: str,
    kind: str,
    *,
    parent: AgentRun | None = None,
    **meta: Any,
) -> AgentRun:
    from .models import AgentRun

    clean = meta_spec.validate_run_meta(kind, meta)
    return AgentRun.objects.create(
        user=user, query=query, model=model, kind=kind, parent=parent, meta=clean
    )


def update_run(
    run: AgentRun,
    *,
    status: str | None = None,
    output: str | None = None,
    error: str | None = None,
    completed_at: Any = _UNSET,
    parent: Any = _UNSET,
    **meta: Any,
) -> AgentRun:
    fields: list[str] = []
    if meta:
        clean = meta_spec.validate_run_meta(run.kind, meta)
        run.meta = {**(run.meta or {}), **clean}
        fields.append("meta")
    if status is not None:
        run.status = status
        fields.append("status")
    if output is not None:
        run.output = output
        fields.append("output")
    if error is not None:
        run.error = error
        fields.append("error")
    if completed_at is not _UNSET:
        run.completed_at = completed_at
        fields.append("completed_at")
    if parent is not _UNSET:
        run.parent = parent
        fields.append("parent")
    if fields:
        run.save(update_fields=fields)
    return run


def finish_run(
    run: AgentRun, *, output: str = "", error: str = "", status: str | None = None, **meta: Any
) -> AgentRun:
    from .models import AgentRun

    final = status or (AgentRun.Status.ERROR if error else AgentRun.Status.DONE)
    return update_run(
        run, status=final, output=output, error=error, completed_at=dt.now(UTC), **meta
    )


# --- step writes --------------------------------------------------------------------------


def seed_steps(run: AgentRun, rows: Iterable[dict]) -> list[AgentStep]:
    """Bulk-create pre-seeded child rows (chain/parallel). Each row dict carries
    ``order`` (+ optional ``key``/``label``/``status``/``output``) and validated meta."""
    from .models import AgentStep

    objs: list[AgentStep] = []
    for raw in rows:
        r = dict(raw)
        order = r.pop("order")
        key = r.pop("key", "")
        label = r.pop("label", "")
        status = r.pop("status", AgentStep.Status.PENDING)
        output = r.pop("output", "")
        clean = meta_spec.validate_step_meta(run.kind, r)
        objs.append(
            AgentStep(
                run=run, order=order, key=key, label=label, status=status, output=output, meta=clean
            )
        )
    AgentStep.objects.bulk_create(objs)
    return objs


def create_step(
    run: AgentRun,
    order: int,
    *,
    key: str = "",
    label: str = "",
    status: str | None = None,
    output: str = "",
    error: str = "",
    started_at: Any = None,
    completed_at: Any = None,
    **meta: Any,
) -> AgentStep:
    from .models import AgentStep

    clean = meta_spec.validate_step_meta(run.kind, meta)
    return AgentStep.objects.create(
        run=run,
        order=order,
        key=key,
        label=label,
        status=status or AgentStep.Status.DONE,
        output=output,
        error=error,
        started_at=started_at,
        completed_at=completed_at,
        meta=clean,
    )


# Statuses that mean a step is finished, and so is the span that represents it.
_TERMINAL_STEP_STATUSES = frozenset({"done", "error"})


def update_step(
    step: AgentStep,
    *,
    status: str | None = None,
    output: str | None = None,
    error: str | None = None,
    started_at: Any = _UNSET,
    completed_at: Any = _UNSET,
    kind: str | None = None,
    replay_span: bool = True,
    **meta: Any,
) -> AgentStep:
    fields: list[str] = []
    if meta:
        clean = meta_spec.validate_step_meta(kind or step.run.kind, meta)
        step.meta = {**(step.meta or {}), **clean}
        fields.append("meta")
    if status is not None:
        step.status = status
        fields.append("status")
    if output is not None:
        step.output = output
        fields.append("output")
    if error is not None:
        step.error = error
        fields.append("error")
    if started_at is not _UNSET:
        step.started_at = started_at
        fields.append("started_at")
    if completed_at is not _UNSET:
        step.completed_at = completed_at
        fields.append("completed_at")
    if fields:
        step.save(update_fields=fields)
        # One choke point covering every workflow that marks a step running and then
        # done/error with timestamps (chain, and the fan-out workflows under
        # _runtime.drive_waves). Replaying the recorded times is more accurate than
        # wrapping the call site, and never affects the write - see core.tracing.
        #
        # `replay_span=False` is for callers that ALREADY hold an open span for this step:
        # _runtime.drive wraps the step itself, and replaying here as well would emit two
        # agent.step spans for one step.
        if replay_span and step.status in _TERMINAL_STEP_STATUSES:
            record_completed_step(step.run, step)
    return step
