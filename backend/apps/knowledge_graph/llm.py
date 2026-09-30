"""LLM concept expansion.

Asks the main Ollama model for a concise description of a concept plus its most important
directly-related concepts, returned as structured JSON (Ollama ``format`` schema). Parsing
is tolerant and never raises: a malformed reply degrades to an empty expansion (which also
trips the novelty-termination rule in the recursive task).
"""

from __future__ import annotations

from apps.llm_analysis import services
from apps.llm_analysis._json import parse_json_object

from .config import max_neighbors
from .models import Relation

# The model picks a DIRECTED edge type; each maps to a canonical stored ``Relation`` plus
# whether THIS concept is the edge's source.
#
# Hierarchy (``has_subfield``) is offered in both directions because the model orients
# parent/child reliably. Prerequisites are NOT: the model is reliable at naming what a concept
# DEPENDS ON ("has_prerequisite") but routinely inverts the reverse direction (claiming a
# concept is a prerequisite FOR a more foundational one). So we only collect prerequisites
# from the dependent's side (foundation -> this concept), which the model gets right; every
# prerequisite edge is still captured because each dependent names its own foundations when it
# is expanded. There is intentionally no ``prerequisite_for`` bucket.
_DIRECTED: dict[str, tuple[str, bool]] = {
    # Hierarchy is stored canonically as parent -> child (``has_subfield``), so both directed
    # buckets map to that relation and only the orientation (source_is_self) differs.
    # neighbor is a child OF this concept -> this(parent) -> neighbor(child)
    "has_subfield": (Relation.HAS_SUBFIELD.value, True),
    # this concept is a child of the neighbor -> neighbor(parent) -> this(child)
    "subfield_of": (Relation.HAS_SUBFIELD.value, False),
    # neighbor is the foundation -> this concept depends on it (this is the target)
    "has_prerequisite": (Relation.PREREQUISITE_FOR.value, False),
}
_LLM_RELATIONS = list(_DIRECTED)

EXPANSION_SCHEMA = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "negative_description": {"type": "string"},
        "neighbors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "relation": {"type": "string", "enum": _LLM_RELATIONS},
                    "weight": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["name", "relation", "weight"],
            },
        },
    },
    "required": ["description", "neighbors"],
}

_SYSTEM = (
    "You build a concept knowledge graph. Write a concise 2-3 sentence description of the "
    "concept. Also write a one-sentence negative_description stating what this concept is NOT - "
    "the common things it is confused with but does not mean (e.g. for 'pop' the music genre: "
    "'Not the stack pop() operation.'). Then list its most important directly-related concepts "
    "as neighbors. For each "
    "neighbor pick exactly ONE directed relation describing how THIS concept relates TO the "
    "neighbor. List BOTH broader parents and narrower children, and the concepts THIS concept "
    "depends on, whenever they exist. Use only these relations:\n"
    "- subfield_of: THIS concept is a subfield or specialization of the neighbor (the "
    "neighbor is the broader parent field).\n"
    "- has_subfield: the neighbor is a subfield or specialization OF this concept (this "
    "concept is the broader parent; the neighbor is a narrower child).\n"
    "- has_prerequisite: the neighbor must be understood before THIS concept (this concept "
    "depends on the neighbor). Only list concepts THIS concept depends on, never the reverse.\n"
    "weight is the strength of the link from 0 to 1 (1.0 = inseparable)."
)


def _clean_neighbors(raw: object) -> list[dict]:
    """Validate/coerce the model's neighbor list defensively.

    Each cleaned item carries the canonical stored ``relation`` plus ``source_is_self`` (True
    when the edge points THIS concept -> neighbor), translated from the model's directed edge
    type so the caller can orient the edge without inferring direction from graph shape.
    """
    if not isinstance(raw, list):
        return []
    cleaned: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        directed = item.get("relation")
        if not isinstance(name, str) or not name.strip():
            continue
        if directed not in _DIRECTED:
            continue
        relation, source_is_self = _DIRECTED[directed]
        try:
            weight = float(item.get("weight"))
        except (TypeError, ValueError):
            weight = 0.5
        weight = min(1.0, max(0.0, weight))
        cleaned.append(
            {
                "name": name.strip(),
                "relation": relation,
                "source_is_self": source_is_self,
                "weight": weight,
            }
        )
        if len(cleaned) >= max_neighbors():
            break
    return cleaned


def expand(name: str, existing: list[str] | None = None) -> dict:
    """Return ``{"description": str, "negative_description": str, "neighbors": [...]}``.

    ``negative_description`` is a one-line "what this concept is NOT" (the homonym contrast signal,
    fed back to the sense judge and shown in the UI); missing -> ``""``. Never raises - a connection
    or parse failure yields an empty expansion (all keys present, blank).
    """
    note = ""
    if existing:
        note = (
            "\nConcepts already in the graph - reuse the EXACT name if a related concept "
            f"matches one of these: {', '.join(existing)}."
        )
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": f"Concept: {name}{note}"},
    ]
    try:
        raw = services.chat(messages, temperature=0.3, format=EXPANSION_SCHEMA)
        data = parse_json_object(raw)
    except (services.OllamaServiceError, ValueError):
        return {"description": "", "negative_description": "", "neighbors": []}

    description = data.get("description")
    if not isinstance(description, str):
        description = ""
    negative = data.get("negative_description")
    if not isinstance(negative, str):
        negative = ""
    return {
        "description": description.strip(),
        "negative_description": negative.strip(),
        "neighbors": _clean_neighbors(data.get("neighbors")),
    }


RERANK_SCHEMA = {
    "type": "object",
    "properties": {"keep": {"type": "array", "items": {"type": "string"}}},
    "required": ["keep"],
}

_RERANK_SYSTEM = (
    "You curate a concept knowledge graph. Given a concept and its current neighbor concepts, "
    "select the MOST important and genuinely correct neighbors to keep, dropping the rest. "
    "Drop neighbors that are miscategorised (e.g. a generic everyday word listed as a subfield), "
    "redundant, or only loosely associated. Prefer neighbors that are real, well-known subfields, "
    "parents, prerequisites, or strong associations of the concept. Return ONLY the names to keep, "
    "copied EXACTLY as given, as the most-important-first list 'keep', at most {k} entries."
)


def rerank_neighbors(name: str, neighbors: list[dict], keep: int) -> list[str]:
    """Ask the LLM which of ``neighbors`` to keep for concept ``name``, best first.

    ``neighbors`` is a list of ``{"name", "relation", "direction"}`` descriptors. Returns up to
    ``keep`` neighbor names (verbatim copies of the inputs). Never raises - a connection or parse
    failure yields an empty list, which the caller treats as "no LLM signal" and falls back to
    its structural ranking.
    """
    if not neighbors:
        return []
    lines = "\n".join(f"- {n['name']} ({n['direction']} {n['relation']})" for n in neighbors)
    user = f"Concept: {name}\nNeighbors:\n{lines}\n\nKeep the best {keep}."
    messages = [
        {"role": "system", "content": _RERANK_SYSTEM.format(k=keep)},
        {"role": "user", "content": user},
    ]
    try:
        raw = services.chat(messages, temperature=0.2, format=RERANK_SCHEMA)
        data = parse_json_object(raw)
    except (services.OllamaServiceError, ValueError):
        return []

    kept = data.get("keep")
    if not isinstance(kept, list):
        return []
    return [k.strip() for k in kept if isinstance(k, str) and k.strip()][:keep]


DISAMBIGUATE_SCHEMA = {
    "type": "object",
    "properties": {"match": {"type": "string"}},
    "required": ["match"],
}

_DISAMBIG_SYSTEM = (
    "You disambiguate word senses for a concept knowledge graph. Two concepts can share the same "
    "name but mean different things (e.g. 'pop' the music genre vs 'pop' the stack operation). "
    "Given a NEW usage of a name and the EXISTING numbered concepts that share that name, decide "
    "whether the new usage means the SAME concept as one of them, or a DIFFERENT one. Reply with "
    'the number of the matching entry, or "new" if the new usage is a genuinely different concept.'
)


def _sense_hint(info: dict | None) -> str:
    """A compact " (also known as ...; related to ...)" suffix from a candidate's evidence."""
    if not info:
        return ""
    parts = []
    aliases = [a for a in info.get("aliases") or [] if a]
    neighbors = [n for n in info.get("neighbors") or [] if n]
    negative = (info.get("negative") or "").strip()
    if aliases:
        parts.append("also known as " + ", ".join(aliases[:6]))
    if neighbors:
        parts.append("related to " + ", ".join(neighbors[:6]))
    if negative:
        parts.append("NOT: " + negative)
    return f" ({'; '.join(parts)})" if parts else ""


def disambiguate_sense(
    name: str, candidates: list, context: dict, evidence: dict | None = None
) -> str | None:
    """Judge whether a new use of ``name`` matches an existing same-name concept or is a new sense.

    ``candidates`` are established (described) ``Concept`` objects sharing the name; ``context`` is
    ``{"domain": <the concept being expanded>, "relation": <how name relates to it>}``. ``evidence``
    (optional) maps ``str(pk)`` -> ``{"aliases": [...], "neighbors": [...], "negative": str}`` to
    give the judge each sense's surface forms, local structure, and explicit "what it is NOT"
    exclusion - the strongest homonym-splitting signal. Returns the matching candidate's id (as
    ``str`` -> reuse it) or ``None`` (mint a new sense). Conservative and never raises: any parse
    failure or unclear reply falls back to the FIRST candidate's id (reuse), so a flaky judge
    degrades to the legacy merge, not over-splitting.
    """
    if not candidates:
        return None
    fallback = str(candidates[0].pk)
    evidence = evidence or {}
    listing = "\n".join(
        f"{i}. {c.name}: {(c.description or '').strip()[:200]}"
        f"{_sense_hint(evidence.get(str(c.pk)))}"
        for i, c in enumerate(candidates, 1)
    )
    domain = context.get("domain") or "(unknown)"
    relation = (context.get("relation") or "associated with").replace("_", " ")
    user = (
        f'New usage: the concept "{name}" appears as a "{relation}" of "{domain}".\n'
        f'Existing concepts also named "{name}":\n{listing}\n\n'
        "Which numbered entry means the SAME concept as the new usage? "
        'Reply with its number, or "new" if none match.'
    )
    messages = [
        {"role": "system", "content": _DISAMBIG_SYSTEM},
        {"role": "user", "content": user},
    ]
    try:
        raw = services.chat(messages, temperature=0.0, format=DISAMBIGUATE_SCHEMA)
        data = parse_json_object(raw)
    except (services.OllamaServiceError, ValueError):
        return fallback
    match = str(data.get("match", "")).strip().lower()
    if match in ("new", "none", "0", ""):
        return None
    try:
        idx = int(match)
    except ValueError:
        return fallback
    if 1 <= idx <= len(candidates):
        return str(candidates[idx - 1].pk)
    return fallback
