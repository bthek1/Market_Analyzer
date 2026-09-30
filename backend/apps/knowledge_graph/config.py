"""Knowledge-graph runtime configuration.

Module-level accessors read from Django settings (env-seeded in ``core.settings.base``)
with safe defaults, so callers never touch ``settings.*`` directly.
"""

from __future__ import annotations

from django.conf import settings


def sim_threshold() -> float:
    return getattr(settings, "KG_SIM_THRESHOLD", 0.7)


def max_depth() -> int:
    return getattr(settings, "KG_MAX_DEPTH", 2)


def max_neighbors() -> int:
    return getattr(settings, "KG_MAX_NEIGHBORS", 8)


def max_nodes() -> int:
    return getattr(settings, "KG_MAX_NODES", 5000)


def max_degree() -> int:
    """Maximum edges kept per node (hub sparsification cap)."""
    return getattr(settings, "KG_MAX_DEGREE", 20)


def min_edge_weight() -> float:
    """Edges below this weight are pruned (unless they are a node's single best link)."""
    return getattr(settings, "KG_MIN_EDGE_WEIGHT", 0.6)


def rerank_trigger() -> int:
    """A node with MORE than this many edges is queued for an LLM rerank-and-prune."""
    return getattr(settings, "KG_RERANK_TRIGGER", 30)


def rerank_target() -> int:
    """The LLM rerank keeps this many of an over-the-trigger node's strongest edges."""
    return getattr(settings, "KG_RERANK_TARGET", 15)


def wsd_enabled() -> bool:
    """Whether resolve_concept runs the LLM word-sense-disambiguation judge on name collisions.

    Off by default: when a new name collides with an existing, already-described concept the judge
    decides same-sense (reuse) vs different-sense (mint a disambiguated node). Disabled -> the
    legacy "reuse the first same-name node" behaviour, so homonyms still merge until it is enabled.
    """
    return getattr(settings, "KG_WSD_ENABLED", False)
