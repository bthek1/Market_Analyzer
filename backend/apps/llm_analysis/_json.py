"""Tolerant single-JSON-object parsing shared by the LLM agents.

Local models often wrap their JSON in fenced code blocks or surround it with prose. This helper
strips that noise and extracts the first ``{...}`` object. Used by both the ReAct agent
(``react.parse_react_output``) and the Evaluator-Optimizer agent (``eval_opt``).
"""

from __future__ import annotations

import json


def parse_json_object(raw: str) -> dict:
    """Tolerantly parse a single JSON object from noisy model output.

    Strips fenced code blocks and surrounding prose, then loads the first ``{...}`` span.
    Raises ``ValueError`` on unrecoverable output or non-object JSON.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("non-JSON output") from exc
    if not isinstance(data, dict):
        raise ValueError("output was not a JSON object")
    return data
