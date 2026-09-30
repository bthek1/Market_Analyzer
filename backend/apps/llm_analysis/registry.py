"""One entry per workflow (issue #6 phase 6).

Everything the HTTP layer needs to know about a workflow lives here: its ``AgentRun.kind``,
its URL slug, and the serializer that renders it. ``views.py`` used to carry a
near-identical list/detail pair per workflow - 22 classes differing only in those three
values - and ``urls.py`` a hand-written route per view.

The point is not the line count. It is that adding a twelfth workflow becomes ONE entry
rather than two classes plus two routes plus remembering both, and that a kind with no
entry fails a test instead of 404ing at runtime.

The URL slug is NOT the kind: the routes shipped before the kinds were consolidated, and
renaming them would break the frontend for no benefit. ``eval_opt`` is served at
``/evaluate/``, ``plan_exec`` at ``/plan/``, ``orchestrator`` at ``/orchestrate/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import serializers as ser

if TYPE_CHECKING:
    from rest_framework import serializers as drf


@dataclass(frozen=True)
class WorkflowSpec:
    """How one workflow is exposed over HTTP."""

    #: ``AgentRun.kind``.
    kind: str
    #: URL segment. Frozen by the frontend contract - see the module docstring.
    slug: str
    #: Renders a run (and, nested, its steps) for the list and detail endpoints.
    run_serializer: type[drf.ModelSerializer]
    #: ``chain`` lists at ``/chain/`` rather than ``/chain/history/``: its routes predate
    #: the convention and the frontend still calls the old path.
    list_at_root: bool = False

    @property
    def list_path(self) -> str:
        return f"{self.slug}/" if self.list_at_root else f"{self.slug}/history/"

    @property
    def detail_path(self) -> str:
        return f"{self.slug}/<uuid:pk>/"

    @property
    def list_name(self) -> str:
        return f"llm-{self.slug}-list"

    @property
    def detail_name(self) -> str:
        return f"llm-{self.slug}-detail"


WORKFLOWS: tuple[WorkflowSpec, ...] = (
    WorkflowSpec("chain", "chain", ser.ChainRunSerializer, list_at_root=True),
    WorkflowSpec("route", "route", ser.RouteRunSerializer),
    WorkflowSpec("parallel", "parallel", ser.ParallelRunSerializer),
    WorkflowSpec("react", "react", ser.ReactRunSerializer),
    WorkflowSpec("eval_opt", "evaluate", ser.EvalOptRunSerializer),
    WorkflowSpec("plan_exec", "plan", ser.PlanExecRunSerializer),
    WorkflowSpec("orchestrator", "orchestrate", ser.OrchestratorRunSerializer),
    WorkflowSpec("multiagent", "multiagent", ser.MultiAgentRunSerializer),
    WorkflowSpec("dag", "dag", ser.DagRunSerializer),
    WorkflowSpec("autonomous", "autonomous", ser.AutonomousRunSerializer),
    WorkflowSpec("browser", "browser", ser.BrowserRunSerializer),
    # "chat-agent", not "chat": /api/llm/chat/ is the OLD non-harness chat endpoint and
    # still serves useSinglePrompt, so the slug cannot collide with it.
    WorkflowSpec("chat", "chat-agent", ser.ChatRunSerializer),
)

BY_KIND: dict[str, WorkflowSpec] = {w.kind: w for w in WORKFLOWS}


def spec_for(kind: str) -> WorkflowSpec:
    """The spec for a run kind. Raises KeyError rather than guessing - a workflow with no
    entry has no endpoints, and that should fail loudly at import rather than 404."""
    return BY_KIND[kind]
