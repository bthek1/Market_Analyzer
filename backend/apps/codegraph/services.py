"""Read-only access to the graphify code-knowledge graph.

`graphify extract . --code-only` writes `graphify-out/graph.json` at the repo root - a
NetworkX node-link dump of the codebase built by deterministic tree-sitter AST parsing.
This module is the ONLY place that touches that file: it parses, normalises the raw
graphify field names into our own stable shape, and filters. Views stay HTTP-only.

The artefact is gitignored and local-only, so "not built yet" is a NORMAL state, not an
error - `load_graph` raises `GraphNotBuiltError` and the view turns that into a 404 with a hint.

Normalisation matters: it isolates the rest of the codebase (and the frontend) from
graphify's own schema, so a future release renaming `links` or `confidence` is a one-file fix.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from django.conf import settings

# Graphify tags every edge with how it was derived. Code edges come from the AST pass and
# are EXTRACTED (fact); INFERRED edges are heuristic guesses. The UI defaults to EXTRACTED.
CONFIDENCE_EXTRACTED = "EXTRACTED"

# A force-directed graph stops being readable - and starts pinning the CPU - well before the
# full graph size (~4.6k nodes / 11k edges for this repo), so responses are capped by degree.
DEFAULT_LIMIT = 400
MAX_LIMIT = 2000


class GraphNotBuiltError(Exception):
    """The graphify output file does not exist yet."""


class GraphUnreadableError(Exception):
    """The graphify output file exists but is not valid JSON."""


def graph_path() -> Path:
    """Filesystem location of graph.json (settings override wins, repo root by default)."""
    configured = getattr(settings, "GRAPHIFY_GRAPH_PATH", None)
    if configured:
        return Path(configured)
    # BASE_DIR is backend/; the graphify output lives at the repo root beside it.
    return Path(settings.BASE_DIR).parent / "graphify-out" / "graph.json"


# Parsing a 5.5 MB JSON file on every request is wasteful when it only changes on re-index,
# so the normalised graph is memoised against the file's mtime+size.
_cache: dict[str, Any] = {"key": None, "graph": None}


def _layer(path: str) -> str:
    """Top-level slice of the repo a node belongs to.

    This is the graph's colour encoding. Graphify's own Leiden `community` is NOT usable for
    that - this repo yields ~400 of them, and a categorical scale is only readable at a
    handful of values. Layer is bounded at three-plus-other, is stable as the graph grows,
    and is what someone actually asks of an architecture picture ("does the frontend reach
    into infra?"). Community stays available as a filter and in the detail panel.
    """
    if path.startswith("backend/"):
        return "backend"
    if path.startswith("frontend/"):
        return "frontend"
    if path.startswith("infra/"):
        return "infra"
    return "other"


def _module(path: str) -> str:
    """Finer grouping for the filter dropdown: the Django app or frontend folder."""
    parts = path.split("/")
    if path.startswith("backend/apps/") and len(parts) > 2:
        return "/".join(parts[:3])
    if path.startswith("frontend/src/") and len(parts) > 2:
        return "/".join(parts[:3])
    return "/".join(parts[:2]) if len(parts) > 1 else path


def _normalise_node(raw: dict) -> dict:
    path = raw.get("source_file") or ""
    return {
        "id": raw.get("id"),
        "label": raw.get("label") or raw.get("norm_label") or raw.get("id"),
        "file": path,
        "line": raw.get("source_location") or "",
        # graphify's `file_type` is really the node KIND: code / rationale / concept.
        "kind": raw.get("file_type") or "unknown",
        "layer": _layer(path),
        "module": _module(path),
        "community": raw.get("community"),
        "community_name": raw.get("community_name") or "",
    }


def _normalise_edge(raw: dict) -> dict:
    return {
        "source": raw.get("source"),
        "target": raw.get("target"),
        "relation": raw.get("relation") or "related",
        "confidence": raw.get("confidence") or CONFIDENCE_EXTRACTED,
        "context": raw.get("context") or "",
        "file": raw.get("source_file") or "",
        "line": raw.get("source_location") or "",
        "weight": raw.get("weight") or 1.0,
    }


def load_graph() -> dict:
    """Parse and normalise graph.json, memoised on the file's mtime.

    Raises GraphNotBuiltError when the file is absent, GraphUnreadableError when it is corrupt.
    """
    path = graph_path()
    try:
        stat = path.stat()
    except OSError as exc:
        raise GraphNotBuiltError(str(path)) from exc

    key = f"{path}:{stat.st_mtime_ns}:{stat.st_size}"
    if _cache["key"] == key and _cache["graph"] is not None:
        return _cache["graph"]

    try:
        with path.open(encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise GraphUnreadableError(str(path)) from exc

    nodes = [_normalise_node(n) for n in raw.get("nodes") or []]
    # NetworkX node-link calls them "links"; older/other dumps may say "edges".
    edges = [_normalise_edge(e) for e in raw.get("links") or raw.get("edges") or []]

    known = {n["id"] for n in nodes}
    # Defensive: an edge pointing at a pruned node would render as a floating stub.
    edges = [e for e in edges if e["source"] in known and e["target"] in known]

    graph = {
        "nodes": nodes,
        "edges": edges,
        "built_at_commit": raw.get("built_at_commit") or "",
        "generated_at": stat.st_mtime,
    }
    _cache["key"] = key
    _cache["graph"] = graph
    return graph


def _degrees(edges: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for edge in edges:
        counts[edge["source"]] = counts.get(edge["source"], 0) + 1
        counts[edge["target"]] = counts.get(edge["target"], 0) + 1
    return counts


def facets(graph: dict) -> dict:
    """Available filter values, computed over the WHOLE graph so the UI dropdowns are stable
    (they must not shrink as the user narrows the current view)."""
    kinds: dict[str, int] = {}
    layers: dict[str, int] = {}
    modules: dict[str, int] = {}
    for node in graph["nodes"]:
        kinds[node["kind"]] = kinds.get(node["kind"], 0) + 1
        layers[node["layer"]] = layers.get(node["layer"], 0) + 1
        modules[node["module"]] = modules.get(node["module"], 0) + 1
    relations: dict[str, int] = {}
    confidences: dict[str, int] = {}
    for edge in graph["edges"]:
        relations[edge["relation"]] = relations.get(edge["relation"], 0) + 1
        confidences[edge["confidence"]] = confidences.get(edge["confidence"], 0) + 1
    return {
        "kinds": sorted(kinds.items(), key=lambda kv: -kv[1]),
        "layers": sorted(layers.items(), key=lambda kv: -kv[1]),
        "modules": sorted(modules.items(), key=lambda kv: -kv[1]),
        "relations": sorted(relations.items(), key=lambda kv: -kv[1]),
        "confidences": sorted(confidences.items(), key=lambda kv: -kv[1]),
    }


def get_subgraph(
    *,
    kind: str | None = None,
    layer: str | None = None,
    module: str | None = None,
    confidence: str | None = None,
    relation: str | None = None,
    community: int | None = None,
    search: str | None = None,
    path_prefix: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> dict:
    """Filtered projection of the graph, capped at `limit` nodes by degree.

    Pruning happens HERE and never in the browser - the full graph is ~5.5 MB.
    """
    graph = load_graph()
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))

    edges = graph["edges"]
    if confidence:
        edges = [e for e in edges if e["confidence"] == confidence]
    if relation:
        edges = [e for e in edges if e["relation"] == relation]

    # Degree is computed AFTER the edge filters so ranking reflects what will be drawn.
    degrees = _degrees(edges)

    nodes = graph["nodes"]
    if kind:
        nodes = [n for n in nodes if n["kind"] == kind]
    if layer:
        nodes = [n for n in nodes if n["layer"] == layer]
    if module:
        nodes = [n for n in nodes if n["module"] == module]
    if community is not None:
        nodes = [n for n in nodes if n["community"] == community]
    if path_prefix:
        nodes = [n for n in nodes if n["file"].startswith(path_prefix)]
    if search:
        needle = search.lower()
        nodes = [n for n in nodes if needle in n["label"].lower() or needle in n["file"].lower()]

    matched = len(nodes)
    ranked = sorted(nodes, key=lambda n: (-degrees.get(n["id"], 0), n["label"]))
    kept = ranked[:limit]
    kept_ids = {n["id"] for n in kept}

    out_nodes = [{**n, "degree": degrees.get(n["id"], 0)} for n in kept]
    out_edges = [e for e in edges if e["source"] in kept_ids and e["target"] in kept_ids]

    return {
        "nodes": out_nodes,
        "edges": out_edges,
        "stats": {
            "total_nodes": len(graph["nodes"]),
            "total_edges": len(graph["edges"]),
            "matched_nodes": matched,
            "returned_nodes": len(out_nodes),
            "returned_edges": len(out_edges),
            "truncated": matched > len(out_nodes),
            "limit": limit,
        },
        "facets": facets(graph),
        "built_at_commit": graph["built_at_commit"],
        "generated_at": graph["generated_at"],
    }


def get_node_detail(node_id: str) -> dict | None:
    """One node plus its immediate neighbours, for the selection panel."""
    graph = load_graph()
    node = next((n for n in graph["nodes"] if n["id"] == node_id), None)
    if node is None:
        return None

    by_id = {n["id"]: n for n in graph["nodes"]}
    incoming, outgoing = [], []
    for edge in graph["edges"]:
        if edge["target"] == node_id:
            other = by_id.get(edge["source"])
            if other:
                incoming.append({**edge, "node": other})
        elif edge["source"] == node_id:
            other = by_id.get(edge["target"])
            if other:
                outgoing.append({**edge, "node": other})

    return {
        **node,
        "degree": len(incoming) + len(outgoing),
        "incoming": incoming,
        "outgoing": outgoing,
    }
