"""Per-kind specification + validator for ``AgentRun.meta`` / ``AgentStep.meta``.

The unified models keep only the cross-cutting spine as real columns; every
workflow-specific field lives in the ``meta`` JSONField. This module is the single
source of truth for what each ``kind`` may store in meta (run scope and step scope),
and the pure validator that enforces it. All meta writes go through ``store.py``,
which calls ``validate_run_meta`` / ``validate_step_meta`` here.

Keeping this pure (no Django imports, no DB) makes it trivially unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Acceptable Python types per field. JSON means "an array or object" (or None).
INT: tuple[type, ...] = (int,)
STR: tuple[type, ...] = (str,)
BOOL: tuple[type, ...] = (bool,)
FLOAT: tuple[type, ...] = (int, float)
JSON: tuple[type, ...] = (list, dict)


_MISSING = object()


@dataclass(frozen=True)
class FieldSpec:
    """One meta field: its accepted type(s), the default used on read, and optional
    value choices. ``default`` is what the accessor/serializer returns when the key is
    absent (mirrors the old column defaults), NOT something injected into stored meta."""

    types: tuple[type, ...]
    default: Any = _MISSING
    choices: tuple[Any, ...] | None = None


# --- choice vocabularies (mirror the old model TextChoices) -------------------------------
ROUTE_VALUES = ("simple", "analysis", "comparison", "deep_research")
ROUTE_METHODS = ("llm", "semantic")
STRATEGIES = ("sectioning", "voting")
ACTIONS = ("tool", "subagent", "reason")
BROWSER_PROVIDERS = ("anthropic", "ollama")
BROWSER_STOP_REASONS = ("complete", "budget", "timeout", "error")


# --- run-scope meta, per kind -------------------------------------------------------------
RUN_META: dict[str, dict[str, FieldSpec]] = {
    "chain": {},
    "route": {
        "route": FieldSpec(STR, "", ROUTE_VALUES),
        "route_reason": FieldSpec(STR, ""),
        "route_method": FieldSpec(STR, "", ROUTE_METHODS),
        "route_confidence": FieldSpec(FLOAT, None),
    },
    "parallel": {
        "strategy": FieldSpec(STR, "sectioning", STRATEGIES),
        "n": FieldSpec(INT, None),
        "tally": FieldSpec(JSON, None),
    },
    "react": {
        "max_steps": FieldSpec(INT, None),
    },
    "chat": {
        "max_steps": FieldSpec(INT, None),
        # Position in the conversation. Written from phase 2 (sessions) onward; a phase-1
        # turn is always turn 0 because it has no session to be the nth turn of.
        "turn": FieldSpec(INT, 0),
        "tools_used": FieldSpec(JSON, None),
        # How many earlier turns this turn folded into the session summary. Recorded on the
        # run as well as streamed, so a reload can still explain a gap in the transcript.
        "compacted": FieldSpec(INT, 0),
    },
    "eval_opt": {
        "max_iterations": FieldSpec(INT, None),
        "threshold": FieldSpec(INT, None),
        "best_score": FieldSpec(INT, None),
    },
    "plan_exec": {
        "max_steps": FieldSpec(INT, None),
        "allow_replan": FieldSpec(BOOL, None),
        "plan": FieldSpec(JSON, None),
        "replans": FieldSpec(INT, 0),
    },
    "orchestrator": {
        "max_workers": FieldSpec(INT, None),
        "plan": FieldSpec(JSON, None),
    },
    "multiagent": {
        "max_tools": FieldSpec(INT, None),
        "agents": FieldSpec(JSON, None),
        "route_reason": FieldSpec(STR, ""),
    },
    "dag": {
        "max_nodes": FieldSpec(INT, None),
        "plan": FieldSpec(JSON, None),
    },
    "autonomous": {
        "max_cycles": FieldSpec(INT, None),
        "max_subagents": FieldSpec(INT, None),
        "goal": FieldSpec(STR, ""),
        "backlog": FieldSpec(JSON, None),
        "stop_reason": FieldSpec(STR, ""),
    },
    "browser": {
        "provider": FieldSpec(STR, "", BROWSER_PROVIDERS),
        "max_steps": FieldSpec(INT, None),
        "allowed_domains": FieldSpec(JSON, []),
        "urls_visited": FieldSpec(JSON, []),
        "stop_reason": FieldSpec(STR, "", BROWSER_STOP_REASONS),
        "duration_s": FieldSpec(FLOAT, None),
    },
}


# --- step-scope meta, per kind ------------------------------------------------------------
STEP_META: dict[str, dict[str, FieldSpec]] = {
    "chain": {},
    "parallel": {
        "vote": FieldSpec(STR, ""),
    },
    "react": {
        "thought": FieldSpec(STR, ""),
        "tool": FieldSpec(STR, ""),
        "tool_args": FieldSpec(JSON, None),
        "observation": FieldSpec(STR, ""),
        "is_answer": FieldSpec(BOOL, False),
    },
    "chat": {
        "thought": FieldSpec(STR, ""),
        "tool": FieldSpec(STR, ""),
        "tool_args": FieldSpec(JSON, None),
        "observation": FieldSpec(STR, ""),
        "is_answer": FieldSpec(BOOL, False),
    },
    "eval_opt": {
        "draft": FieldSpec(STR, ""),
        "score": FieldSpec(INT, None),
        "feedback": FieldSpec(STR, ""),
        "passed": FieldSpec(BOOL, False),
    },
    "plan_exec": {
        "task": FieldSpec(STR, ""),
        "tool": FieldSpec(STR, ""),
        "tool_args": FieldSpec(JSON, None),
        "observation": FieldSpec(STR, ""),
        "result": FieldSpec(STR, ""),
    },
    "orchestrator": {
        "task": FieldSpec(STR, ""),
        "tool": FieldSpec(STR, ""),
        "tool_args": FieldSpec(JSON, None),
        "observation": FieldSpec(STR, ""),
    },
    "multiagent": {
        "input": FieldSpec(STR, ""),
        "tool_calls": FieldSpec(JSON, None),
    },
    "dag": {
        "task": FieldSpec(STR, ""),
        "wave": FieldSpec(INT, None),
        "depends_on": FieldSpec(JSON, []),
        "tool": FieldSpec(STR, ""),
        "tool_args": FieldSpec(JSON, None),
        "observation": FieldSpec(STR, ""),
    },
    "autonomous": {
        "reflection": FieldSpec(STR, ""),
        "task": FieldSpec(STR, ""),
        "action": FieldSpec(STR, "reason", ACTIONS),
        "tool": FieldSpec(STR, ""),
        "tool_args": FieldSpec(JSON, None),
        "observation": FieldSpec(STR, ""),
        "spawned": FieldSpec(BOOL, False),
        "subagent_steps": FieldSpec(JSON, None),
        "backlog": FieldSpec(JSON, None),
        "goal_complete": FieldSpec(BOOL, False),
    },
    "browser": {
        "action": FieldSpec(STR, ""),
        "action_args": FieldSpec(JSON, None),
        "url": FieldSpec(STR, ""),
        "title": FieldSpec(STR, ""),
        "evaluation": FieldSpec(STR, ""),
        "memory": FieldSpec(STR, ""),
        # A relative path under BROWSER_SCREENSHOT_ROOT, never the image bytes -
        # base64 in JSONB would be ~200 KB per step.
        "screenshot": FieldSpec(STR, ""),
    },
}


class MetaValidationError(ValueError):
    """Raised when meta data violates the kind's spec (unknown key, wrong type, bad choice)."""


def _validate(spec_map: dict[str, dict[str, FieldSpec]], scope: str, kind: str, data: dict) -> dict:
    if kind not in spec_map:
        raise MetaValidationError(f"Unknown kind {kind!r} for {scope} meta.")
    spec = spec_map[kind]
    clean: dict[str, Any] = {}
    for key, value in data.items():
        if key not in spec:
            raise MetaValidationError(
                f"Unknown {scope} meta key {key!r} for kind {kind!r}; allowed: {sorted(spec)}"
            )
        fs = spec[key]
        if value is not None:
            # bool is an int subclass, so guard it out of INT/FLOAT checks.
            if fs.types in (INT, FLOAT) and isinstance(value, bool):
                raise MetaValidationError(
                    f"{scope} meta key {key!r} (kind {kind!r}) expects {fs.types}, got bool."
                )
            if not isinstance(value, fs.types):
                raise MetaValidationError(
                    f"{scope} meta key {key!r} (kind {kind!r}) expects {fs.types}, "
                    f"got {type(value).__name__}."
                )
            if fs.choices is not None and value not in fs.choices:
                raise MetaValidationError(
                    f"{scope} meta key {key!r} (kind {kind!r}) must be one of "
                    f"{fs.choices}, got {value!r}."
                )
        clean[key] = value
    return clean


def validate_run_meta(kind: str, data: dict) -> dict:
    """Return a cleaned copy of run-scope meta for ``kind``; raise on any violation."""
    return _validate(RUN_META, "run", kind, data)


def validate_step_meta(kind: str, data: dict) -> dict:
    """Return a cleaned copy of step-scope meta for ``kind``; raise on any violation."""
    return _validate(STEP_META, "step", kind, data)


def run_defaults(kind: str) -> dict:
    """The read-time defaults for every run meta field of ``kind`` (absent key -> default)."""
    return {k: fs.default for k, fs in RUN_META.get(kind, {}).items() if fs.default is not _MISSING}


def step_defaults(kind: str) -> dict:
    """The read-time defaults for every step meta field of ``kind``."""
    return {
        k: fs.default for k, fs in STEP_META.get(kind, {}).items() if fs.default is not _MISSING
    }
