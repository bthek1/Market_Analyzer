"""Knowledge-graph business logic: dedup-aware node resolution, expansion, and subgraph reads.

Dedup is slug-exact plus ``pg_trgm`` trigram similarity (PostgreSQL only - the trigram step
is skipped on other backends, e.g. SQLite in tests, where it degrades to slug-exact dedup).
"""

from __future__ import annotations

from collections import defaultdict, deque

from django.contrib.postgres.search import TrigramSimilarity
from django.db import connection, transaction
from django.db.models import Count, F, Q
from django.utils.text import slugify

from .config import (
    max_degree,
    max_nodes,
    min_edge_weight,
    rerank_target,
    rerank_trigger,
    sim_threshold,
    wsd_enabled,
)
from .llm import disambiguate_sense, expand, rerank_neighbors
from .models import Concept, ConceptAlias, ConceptEdge, Relation

# When a node pair ends up with competing relations we keep the most specific one. A
# hierarchy claim (has_subfield) outranks an ordering claim (prerequisite_for).
RELATION_PRECEDENCE = {
    Relation.HAS_SUBFIELD.value: 2,
    Relation.PREREQUISITE_FOR.value: 1,
}

# Both relations are structural (hierarchy + ordering); the graph has no non-structural
# relations. Kept as an explicit tuple so the connection-count and reach queries document which
# relations they traverse.
STRUCTURAL_RELATIONS = (Relation.HAS_SUBFIELD.value, Relation.PREREQUISITE_FOR.value)


def connection_count_annotation():
    """Count expression for a concept's structural (hierarchy + ordering) connections."""
    return Count(
        "outgoing", filter=Q(outgoing__relation__in=STRUCTURAL_RELATIONS), distinct=True
    ) + Count("incoming", filter=Q(incoming__relation__in=STRUCTURAL_RELATIONS), distinct=True)


# Cooperative cancellation for the expansion crawl. Every queued task carries the cancel
# "epoch" current when it was enqueued; "Clear queue" bumps the epoch (in the broker's Redis,
# shared across the web and worker processes) and purges the broker. A worker then drops any
# task whose epoch is now stale - which catches BOTH the tasks still sitting in the broker AND
# the ones a worker has already prefetched into memory (a bare broker purge misses the latter).
# New expansions enqueue at the bumped epoch, so they run normally - clearing never wedges the
# feature. All Redis access degrades to "no cancellation" if Redis is unreachable (e.g. eager
# unit tests), so the crawl behaves exactly as before when the control plane is absent.
_CANCEL_EPOCH_KEY = "kg:expand_cancel_epoch"


def _broker_redis():
    """A Redis client on the Celery broker, or None if the driver/connection is unavailable."""
    from urllib.parse import urlparse

    from django.conf import settings

    try:
        import redis

        parsed = urlparse(settings.CELERY_BROKER_URL)
        return redis.Redis(
            host=parsed.hostname or "localhost",
            port=parsed.port or 6379,
            db=int(parsed.path.lstrip("/") or 0),
            decode_responses=True,
            socket_connect_timeout=1,
        )
    except Exception:
        return None


def current_cancel_epoch() -> int:
    """The cancel epoch new tasks should be stamped with (0 when Redis is unavailable)."""
    client = _broker_redis()
    if client is None:
        return 0
    try:
        return int(client.get(_CANCEL_EPOCH_KEY) or 0)
    except Exception:
        return 0


def expansion_cancelled(epoch: int | None) -> bool:
    """True when a task stamped with ``epoch`` has been superseded by a later Clear."""
    if epoch is None:
        return False
    return epoch < current_cancel_epoch()


def clear_expansion_queue() -> dict:
    """Stop the crawl: bump the cancel epoch and purge the broker queue.

    Returns ``{"purged": <messages dropped from the broker>, "epoch": <new epoch>}``. Already
    prefetched/in-flight tasks self-drop on their next start because their epoch is now stale;
    a task mid-LLM-call finishes that one call (it cannot be interrupted) but spawns nothing.
    """
    epoch = 0
    client = _broker_redis()
    if client is not None:
        try:
            epoch = int(client.incr(_CANCEL_EPOCH_KEY))
        except Exception:
            epoch = 0

    purged = 0
    try:
        from core.celery import app

        purged = app.control.purge() or 0
    except Exception:
        purged = 0
    return {"purged": purged, "epoch": epoch}


def _trigram_supported() -> bool:
    return connection.vendor == "postgresql"


def _trigram_near(name: str, threshold: float) -> Concept | None:
    """The single most trigram-similar concept by name above ``threshold`` (Postgres only)."""
    return (
        Concept.objects.annotate(s=TrigramSimilarity("name", name))
        .filter(s__gt=threshold)
        .order_by("-s")
        .first()
    )


def resolve_concept(
    name: str, sim: float | None = None, *, context: dict | None = None
) -> tuple[Concept, bool]:
    """Resolve a name to a Concept: same-base-slug (sense-aware) -> trigram-near -> create.

    Returns ``(concept, created)``. ``get_or_create`` on the slug guards the parallel-worker
    race when two tasks mint the same brand-new slug at once.

    ``context`` (optional ``{"domain", "relation"}`` describing how the name is being used) drives
    word-sense disambiguation: when the name collides with an EXISTING, already-described concept,
    an LLM judge decides same-sense (reuse) vs different-sense (mint a disambiguated node), so
    homonyms like "pop" (genre) and "pop" (stack op) no longer merge. Without context, with WSD
    disabled, or when the judge is unavailable it degrades to reusing the first same-name node
    (the legacy behaviour).
    """
    name = name.strip()
    base = slugify(name)
    # Candidates are gathered by base_slug OR an owning alias slug: a word that already MEANS a
    # concept counts as a hit (synonymy recall). This subsumes the old bare slug-exact step.
    candidates = _candidates_for(base)
    if not candidates and _trigram_supported():
        near = _trigram_near(name, sim_threshold() if sim is None else sim)
        if near:
            # The fuzzy match becomes a permanent, zero-cost exact alias so the next mention of
            # this surface form hits the alias-exact lookup instead of re-running trigram.
            record_alias(near, name)
            candidates = [near]

    if not candidates:
        return Concept.objects.get_or_create(slug=base, defaults={"name": name, "base_slug": base})

    reuse = _pick_sense(name, candidates, context)
    if reuse is not None:
        return reuse, False
    return _create_sense(name, base, context)


def _candidates_for(base: str) -> list[Concept]:
    """Concepts whose base_slug == ``base`` OR which own a ``ConceptAlias`` with that slug.

    Dedups by pk and preserves order (base-slug matches first, then alias-only matches) so the
    sense logic downstream sees every concept the surface form could denote, each once.
    """
    seen: set = set()
    out: list[Concept] = []
    for c in Concept.objects.filter(base_slug=base):
        if c.pk not in seen:
            seen.add(c.pk)
            out.append(c)
    for alias in ConceptAlias.objects.filter(slug=base).select_related("concept"):
        if alias.concept_id not in seen:
            seen.add(alias.concept_id)
            out.append(alias.concept)
    return out


def record_alias(concept: Concept, name: str) -> None:
    """Record ``name`` as an alias (surface form) of ``concept`` - the ONLY alias writer.

    No-op (never raises) when the slug is already the concept's canonical slug, an alias with
    that slug already exists, or a DIFFERENT concept already owns that slug (ambiguous - a single
    surface form must not point at two concepts). ``get_or_create`` on the unique slug guards the
    parallel-worker race, the same pattern ``resolve_concept`` uses for new nodes.
    """
    slug = slugify(name)
    if not slug or slug == concept.slug:
        return
    if Concept.objects.filter(slug=slug).exclude(pk=concept.pk).exists():
        return  # the surface form is some other concept's canonical slug - ambiguous, skip
    existing = ConceptAlias.objects.filter(slug=slug).first()
    if existing is not None:
        return  # already an alias (of this or another concept) - idempotent, never reassign
    ConceptAlias.objects.get_or_create(
        slug=slug, defaults={"concept": concept, "name": name.strip()}
    )


def _pick_sense(name: str, candidates: list[Concept], context: dict | None) -> Concept | None:
    """Choose an existing same-name Concept to reuse, or ``None`` to mint a new sense.

    The judge only runs when a name collides with an ESTABLISHED concept (one that already has a
    committed description) AND WSD is enabled AND a usage context is supplied - so the common cases
    (a fresh name, or colliding with an unexpanded stub that has no meaning yet) stay zero-cost and
    reuse the existing node exactly as before.

    Whenever WSD is enabled and a surface form resolves to an existing sense whose canonical slug
    differs from ``slugify(name)``, the surface form is folded as an alias (``record_alias``): a
    confirmed same-sense match and Phase 1's synonym fold thus become the SAME event. When WSD is
    off (or the judge errors) the legacy reuse is kept and no alias is written.
    """
    if not wsd_enabled():
        return candidates[0]  # legacy reuse - no sense judging, no alias recording

    established = [c for c in candidates if (c.description or "").strip()]
    if not established or not context:
        # An unexpanded stub (no committed meaning) or a context-free call: nothing to
        # disambiguate, so reuse directly - but still fold the surface form as an alias.
        return _reuse_sense(candidates[0], name)
    try:
        match_id = disambiguate_sense(
            name, established, context, evidence=_sense_evidence(established)
        )
    except Exception:
        return candidates[0]  # flaky judge -> legacy reuse, no alias written
    if match_id is None:
        return None  # a genuinely different sense - caller mints a new node
    by_id = {str(c.pk): c for c in candidates}
    return _reuse_sense(by_id.get(str(match_id), candidates[0]), name)


def _reuse_sense(concept: Concept, name: str) -> Concept:
    """Reuse ``concept`` for ``name``, folding the surface form as an alias if it is a synonym."""
    if slugify(name) != concept.slug:
        record_alias(concept, name)
    return concept


def _sense_evidence(candidates: list[Concept]) -> dict:
    """Per-candidate disambiguation evidence: its known aliases + a few graph neighbors.

    Keyed by ``str(pk)``. Aliases tell the judge which words already belong to a sense; the
    sample neighbors sketch the sense's local structure. Both sharpen same-vs-different decisions
    beyond the bare name + description.
    """
    evidence: dict = {}
    for c in candidates:
        aliases = list(c.aliases.values_list("name", flat=True))
        evidence[str(c.pk)] = {
            "aliases": aliases,
            "neighbors": _neighbor_names(c, limit=6),
            "negative": (c.negative_description or "").strip(),
        }
    return evidence


def _create_sense(name: str, base: str, context: dict | None) -> tuple[Concept, bool]:
    """Create a new disambiguated sense for ``name`` (sharing the lexical key ``base``).

    The new node keeps ``base_slug = base`` so future uses of the name find it as a candidate, but
    takes a distinct, domain-suffixed ``slug`` (and display name) so the two senses stay separate.
    """
    domain = (context or {}).get("domain") or ""
    suffix = slugify(domain) or "alt"
    display = f"{name} ({domain})" if domain else name
    slug = f"{base}-{suffix}"
    n = 2
    while Concept.objects.filter(slug=slug).exists():
        slug = f"{base}-{suffix}-{n}"
        n += 1
    return Concept.objects.get_or_create(slug=slug, defaults={"name": display, "base_slug": base})


def merge_concepts(canonical: Concept, duplicates: list[Concept]) -> dict:
    """Fold ``duplicates`` into ``canonical``: re-point edges, move aliases, delete the dups.

    Remediation for nodes that fragmented across surface forms before alias-aware resolution
    existed (e.g. ``graph``/``graphs``). One transaction:

    1. Re-point every edge incident to a duplicate onto ``canonical`` via ``_upsert_edge`` (so the
       at-most-one-edge-per-pair / relation-precedence / evidence-merge rules apply), dropping any
       edge that becomes a self-loop after re-pointing.
    2. Record each duplicate's name as an alias of ``canonical`` and move the duplicate's own
       ``ConceptAlias`` rows onto ``canonical`` (dropping slug collisions).
    3. Carry ``description`` onto ``canonical`` only when canonical's is empty (never clobber).
    4. Delete the duplicate ``Concept`` rows (CASCADE clears any leftover collapsed edges).

    Idempotent and orphan-safe; silently skips a missing/identical node and never raises.
    Returns a summary ``{edges_repointed, edges_collapsed, aliases_added, nodes_deleted}``.
    """
    summary = {"edges_repointed": 0, "edges_collapsed": 0, "aliases_added": 0, "nodes_deleted": 0}
    dups = [d for d in duplicates if d is not None and d.pk != canonical.pk]
    if not dups:
        return summary

    with transaction.atomic():
        for dup in dups:
            incident = list(
                ConceptEdge.objects.filter(Q(source=dup) | Q(target=dup)).select_related(
                    "source", "target"
                )
            )
            for e in incident:
                relation, weight = e.relation, e.weight
                # Swap the duplicate endpoint for canonical, preserving the edge's orientation.
                src = canonical if e.source_id == dup.pk else e.source
                dst = canonical if e.target_id == dup.pk else e.target
                e.delete()  # remove the old edge; _upsert_edge re-asserts onto canonical
                if src.pk == dst.pk:
                    continue  # would be a self-loop after re-pointing - drop it
                before = ConceptEdge.objects.count()
                _upsert_edge(src, dst, relation, weight)
                summary["edges_repointed"] += 1
                if ConceptEdge.objects.count() <= before:
                    summary["edges_collapsed"] += 1

            before_aliases = ConceptAlias.objects.filter(concept=canonical).count()
            # Move the duplicate's own aliases over (dropping slug collisions).
            for alias in ConceptAlias.objects.filter(concept=dup):
                if (
                    alias.slug == canonical.slug
                    or ConceptAlias.objects.filter(slug=alias.slug).exclude(pk=alias.pk).exists()
                ):
                    alias.delete()  # collides with canonical's slug or an existing alias
                else:
                    alias.concept = canonical
                    alias.save(update_fields=["concept"])

            # Carry description only when canonical lacks one (never clobber a real value).
            if not (canonical.description or "").strip() and (dup.description or "").strip():
                canonical.description = dup.description
                canonical.save(update_fields=["description"])

            dup_name = dup.name
            dup.delete()
            summary["nodes_deleted"] += 1
            # Record the duplicate's surface form AFTER deleting it - while the duplicate existed
            # it owned that slug, so record_alias would (correctly) have skipped it as ambiguous.
            record_alias(canonical, dup_name)
            summary["aliases_added"] += (
                ConceptAlias.objects.filter(concept=canonical).count() - before_aliases
            )
    return summary


def _neighbor_names(concept: Concept, limit: int = 20) -> list[str]:
    """Names of the concept's existing graph neighbors (the convergence feedback)."""
    return list(
        Concept.objects.filter(Q(incoming__source=concept) | Q(outgoing__target=concept))
        .values_list("name", flat=True)
        .distinct()[:limit]
    )


def expand_concept(concept_id, *, force: bool = False) -> list[str]:
    """Expand one node into a description + neighbor edges.

    Returns the ids (as ``str``) of genuinely-new neighbor concepts created by this call,
    which the recursive task uses to decide whether to keep fanning out.

    Concurrency: the node is claimed with a single conditional ``UPDATE`` (a Postgres
    ``FOR NO KEY UPDATE`` lock, which does NOT conflict with the ``FOR KEY SHARE`` locks
    that edge inserts take on their target rows) rather than a ``select_for_update`` held
    across the slow LLM call. The LLM call runs OUTSIDE any transaction so no row lock is
    held during it - this is what kept parallel expansions of mutually-linked concepts from
    deadlocking on each other's FK locks.
    """
    if Concept.objects.count() >= max_nodes():
        return []

    concept = Concept.objects.get(pk=concept_id)
    # Cheap read-only short-circuit so an already-expanded node skips the LLM call entirely.
    # The authoritative guard against the rare concurrent race is the conditional UPDATE below.
    if concept.times_expanded and not force:
        return []

    # Slow LLM/HTTP call - deliberately outside any transaction (never raises; see llm.expand)
    # so no row lock is held across it.
    result = expand(concept.name, _neighbor_names(concept))

    new_ids: list[str] = []
    with transaction.atomic():
        # Claim the node inside the write transaction with a single conditional UPDATE (a
        # Postgres FOR NO KEY UPDATE lock, which does NOT conflict with the FOR KEY SHARE
        # locks that edge inserts take on their target rows). For the normal path only an
        # unexpanded node is claimable, so duplicate/racing tasks short-circuit. Claiming in
        # the same transaction as the writes keeps the whole call idempotent on retry: a
        # deadlock rolls the claim back too, so an auto-retry re-runs cleanly.
        if force:
            claimed = Concept.objects.filter(pk=concept_id).update(
                times_expanded=F("times_expanded") + 1
            )
        else:
            claimed = Concept.objects.filter(pk=concept_id, times_expanded=0).update(
                times_expanded=1
            )
        if not claimed:
            return []

        concept.description = result["description"]
        concept.negative_description = result.get("negative_description", "")
        concept.save(update_fields=["description", "negative_description"])

        for n in result["neighbors"]:
            # Pass the expanding concept as the usage context so word-sense disambiguation can tell
            # e.g. "pop" (a prerequisite of "stacks") from "pop" (a subfield of "music").
            target, created = resolve_concept(
                n["name"], context={"domain": concept.name, "relation": n["relation"]}
            )
            if target.pk == concept.pk:
                continue
            # The LLM names the direction (which side is the child/parent or
            # prerequisite/dependent), so orient the edge from its bucket rather than guessing
            # from graph shape. Default to this-concept-as-source for hand-built expansions
            # (e.g. tests) that omit the flag.
            if n.get("source_is_self", True):
                _upsert_edge(concept, target, n["relation"], n["weight"])
            else:
                _upsert_edge(target, concept, n["relation"], n["weight"])
            if created:
                new_ids.append(str(target.pk))
    return new_ids


def _upsert_edge(source: Concept, target: Concept, relation: str, weight: float) -> None:
    """Assert a relation between two concepts, keeping AT MOST ONE edge per node pair.

    There is never more than one edge between any two concepts (regardless of direction or
    relation). The caller supplies the direction (the LLM names which side is the
    child/parent or prerequisite/dependent, so we trust its bucketing). When the pair already
    carries an edge of the winning relation we preserve that existing edge's orientation - the
    first assertion of a relation fixes its direction, so a later reversed assertion cannot
    flip it. Otherwise the caller's ``source -> target`` orientation is used. The most specific
    relation wins (has_subfield > prerequisite_for) and the weight/times_seen of
    every prior edge plus this observation are merged. This keeps the "flows both ways" bug
    and any parallel multi-relation edges collapsed in one place.
    """
    existing = list(
        ConceptEdge.objects.filter(
            Q(source=source, target=target) | Q(source=target, target=source)
        )
    )

    # Most specific relation across the proposed edge + everything already on the pair.
    win_rel = max(
        [relation, *(e.relation for e in existing)],
        key=lambda r: RELATION_PRECEDENCE.get(r, 0),
    )

    # Merge evidence: running mean over all prior observations plus this one.
    prior_seen = sum(e.times_seen for e in existing)
    prior_weight = sum(e.weight * e.times_seen for e in existing)
    merged_seen = prior_seen + 1
    merged_weight = (prior_weight + weight) / merged_seen

    # Keep an existing edge already in the winning relation (preserving its PK AND direction);
    # otherwise create one in the caller-supplied orientation.
    survivor = next((e for e in existing if e.relation == win_rel), None)
    src, dst = (survivor.source, survivor.target) if survivor else (source, target)

    for e in existing:
        if e is not survivor:
            e.delete()

    if survivor is None:
        ConceptEdge.objects.create(
            source=src, target=dst, relation=win_rel, weight=merged_weight, times_seen=merged_seen
        )
    else:
        survivor.weight = merged_weight
        survivor.times_seen = merged_seen
        survivor.save(update_fields=["weight", "times_seen"])


# Edges are ranked for keep/evict decisions by corroboration first, then strength: an edge
# multiple independent expansions agreed on (times_seen) is more trustworthy than a single
# LLM's confidence (weight). Relation type is deliberately NOT a quality signal here.
def _edge_rank(e: ConceptEdge) -> tuple[int, float]:
    return (e.times_seen, e.weight)


def _enforce_degree_cap(node_id, cap: int | None = None) -> int:
    """Evict a node's weakest incident edges until it is within ``cap`` (default config).

    Skips any edge whose far endpoint would be orphaned (its only remaining link), so
    sparsifying a hub never disconnects a leaf. Returns the number of edges removed.
    """
    cap = max_degree() if cap is None else cap
    incident = list(ConceptEdge.objects.filter(Q(source_id=node_id) | Q(target_id=node_id)))
    excess = len(incident) - cap
    if excess <= 0:
        return 0

    incident.sort(key=_edge_rank)  # weakest first
    removed = 0
    for e in incident:
        if removed >= excess:
            break
        other = e.target_id if e.source_id == node_id else e.source_id
        far_degree = ConceptEdge.objects.filter(Q(source_id=other) | Q(target_id=other)).count()
        if far_degree <= 1:
            continue  # would orphan the far node; leave it
        e.delete()
        removed += 1
    return removed


def prune_edges(max_degree_cap: int | None = None, min_weight: float | None = None) -> int:
    """One-off sparsification: drop sub-threshold edges then cap every node's degree.

    A re-runnable repair (like ``normalize_edges``) applying the SAME two rules the
    insert-time path enforces, so a bulk clean-up and steady-state growth converge on the
    same shape:

    * Weight floor: edges below ``min_weight`` are removed, EXCEPT a node's single strongest
      link (``_edge_rank``) is always kept so nothing is fully orphaned.
    * Degree cap: every node is reduced to at most ``max_degree_cap`` edges via
      ``_enforce_degree_cap`` (weakest first, never orphaning the far node).

    Returns the number of edges removed. Idempotent.
    """
    cap = max_degree() if max_degree_cap is None else max_degree_cap
    floor = min_edge_weight() if min_weight is None else min_weight

    before = ConceptEdge.objects.count()
    with transaction.atomic():
        # 1) Weight floor. Protect each node's single strongest link from the floor so a node
        #    whose every edge is weak still keeps its best one.
        edges = list(ConceptEdge.objects.all())
        incident: dict = defaultdict(list)
        for e in edges:
            incident[e.source_id].append(e)
            incident[e.target_id].append(e)
        best_ids = {max(inc, key=_edge_rank).pk for inc in incident.values()}
        weak = [e.pk for e in edges if e.weight < floor and e.pk not in best_ids]
        ConceptEdge.objects.filter(pk__in=weak).delete()

        # 2) Degree cap. Degrees only fall, so capping each initially-over node once is enough.
        #    Recompute degree after the floor pass (same transaction sees the deletes).
        over = (
            Concept.objects.annotate(
                d=Count("outgoing", distinct=True) + Count("incoming", distinct=True)
            )
            .filter(d__gt=cap)
            .values_list("id", flat=True)
        )
        for node_id in list(over):
            _enforce_degree_cap(node_id, cap=cap)
    return before - ConceptEdge.objects.count()


def nodes_over_rerank_trigger(concept_id, trigger: int | None = None) -> list:
    """Ids of the concept and its neighbors whose degree now exceeds the rerank trigger.

    An expansion only touches the concept and its direct neighbors, so this is exactly the set
    that could have crossed the threshold. The recursive task calls this after each expansion
    and queues an LLM rerank for each returned id.
    """
    trig = rerank_trigger() if trigger is None else trigger
    touched = {concept_id} | set(
        Concept.objects.filter(
            Q(incoming__source_id=concept_id) | Q(outgoing__target_id=concept_id)
        ).values_list("id", flat=True)
    )
    over = (
        Concept.objects.filter(pk__in=touched)
        .annotate(d=Count("outgoing", distinct=True) + Count("incoming", distinct=True))
        .filter(d__gt=trig)
        .values_list("id", flat=True)
    )
    return list(over)


def all_over_trigger_nodes(trigger: int | None = None) -> list:
    """Ids of EVERY node whose degree exceeds the rerank trigger, across the whole graph.

    The expansion-time trigger only re-checks nodes an expansion touched, so a hub can sit
    over the limit indefinitely once the graph goes idle. The periodic sweep walks this list
    and queues a rerank for each, decoupling clean-up from expansion entirely.
    """
    trig = rerank_trigger() if trigger is None else trigger
    over = (
        Concept.objects.annotate(
            d=Count("outgoing", distinct=True) + Count("incoming", distinct=True)
        )
        .filter(d__gt=trig)
        .values_list("id", flat=True)
    )
    return list(over)


def rerank_and_prune(concept_id, *, trigger: int | None = None, target: int | None = None) -> int:
    """LLM-rerank one node's edges and prune it down to ``target`` of the best ones.

    No-op unless the node has MORE than ``trigger`` edges (the guard lives here so the task can
    be queued liberally). The LLM, shown all neighbors at once, picks the most important/correct
    ``target`` to keep - a comparative judgement the per-edge expansion weights cannot make. Any
    keep-slots the LLM leaves unfilled (or an LLM failure entirely) fall back to the structural
    ``_edge_rank`` order, so this never deletes more than intended and never raises. Pruning is
    orphan-protected: an edge that is the far node's only remaining link is always kept.

    Returns the number of edges removed.
    """
    trig = rerank_trigger() if trigger is None else trigger
    tgt = rerank_target() if target is None else target

    concept = Concept.objects.get(pk=concept_id)
    edges = list(
        ConceptEdge.objects.filter(Q(source=concept) | Q(target=concept)).select_related(
            "source", "target"
        )
    )
    if len(edges) <= trig:
        return 0

    descriptors = []
    for e in edges:
        if e.source_id == concept.pk:
            other, direction = e.target, "has neighbor"
        else:
            other, direction = e.source, "neighbor links to"
        descriptors.append(
            {"edge": e, "name": other.name, "relation": e.relation, "dir": direction}
        )

    # LLM keep-list (best first), mapped back to edges by neighbor slug.
    by_slug = {slugify(d["name"]): d["edge"] for d in descriptors}
    keep: list[ConceptEdge] = []
    keep_ids: set = set()
    llm_input = [
        {"name": d["name"], "relation": d["relation"], "direction": d["dir"]} for d in descriptors
    ]
    for nm in rerank_neighbors(concept.name, llm_input, tgt):
        e = by_slug.get(slugify(nm))
        if e is not None and e.pk not in keep_ids:
            keep.append(e)
            keep_ids.add(e.pk)
        if len(keep) >= tgt:
            break

    # Backfill any remaining slots from the structural ranking (also the total-LLM-failure path).
    if len(keep) < tgt:
        for d in sorted(descriptors, key=lambda d: _edge_rank(d["edge"]), reverse=True):
            if len(keep) >= tgt:
                break
            if d["edge"].pk not in keep_ids:
                keep.append(d["edge"])
                keep_ids.add(d["edge"].pk)

    removed = 0
    with transaction.atomic():
        for d in descriptors:
            e = d["edge"]
            if e.pk in keep_ids:
                continue
            other_id = e.target_id if e.source_id == concept.pk else e.source_id
            far_degree = ConceptEdge.objects.filter(
                Q(source_id=other_id) | Q(target_id=other_id)
            ).count()
            if far_degree <= 1:
                continue  # would orphan the far node; leave it
            e.delete()
            removed += 1
    return removed


def normalize_edges() -> int:
    """One-off repair enforcing the at-most-one-edge-per-pair invariant on existing data.

    Collapses every node pair that currently has more than one edge (bidirectional and/or
    multi-relation) into a single canonical edge using the same rules as ``_upsert_edge``.
    Returns the number of edges removed. Idempotent - safe to re-run.
    """
    before = ConceptEdge.objects.count()
    groups: dict[frozenset, list[ConceptEdge]] = {}
    for e in ConceptEdge.objects.select_related("source", "target"):
        groups.setdefault(frozenset((e.source_id, e.target_id)), []).append(e)

    with transaction.atomic():
        for edges in groups.values():
            if len(edges) < 2:
                continue
            win_rel = max((e.relation for e in edges), key=lambda r: RELATION_PRECEDENCE.get(r, 0))
            merged_seen = sum(e.times_seen for e in edges)
            merged_weight = sum(e.weight * e.times_seen for e in edges) / merged_seen
            # Keep the orientation of an existing edge already in the winning relation; with
            # direction now supplied by the LLM there is no structural signal to re-derive it.
            keeper = next((e for e in edges if e.relation == win_rel), edges[0])
            src, dst = keeper.source, keeper.target
            for e in edges:
                e.delete()
            ConceptEdge.objects.create(
                source=src,
                target=dst,
                relation=win_rel,
                weight=merged_weight,
                times_seen=merged_seen,
            )
    return before - ConceptEdge.objects.count()


# Relations whose edges are transitive: if a -R-> b and b -R-> c then a -R-> c is implied, so a
# direct a -R-> c edge is redundant and can be dropped. has_subfield is transitive (containment)
# and prerequisite_for is transitive (ordering) - both graph relations are transitive.
_TRANSITIVE_RELATIONS = (Relation.HAS_SUBFIELD.value, Relation.PREREQUISITE_FOR.value)


def _nodes_on_cycle(adj: dict[object, set]) -> set:
    """Ids of every node that lies on a directed cycle in ``adj`` (iterative DFS, three-colour).

    Transitive reduction is only well-defined on a DAG, so the caller skips edges touching these
    nodes - a stray bidirectional/cyclic claim then never strips a whole loop.
    """
    white, grey, black = 0, 1, 2
    colour: dict = defaultdict(int)
    on_cycle: set = set()
    for root in list(adj):
        if colour[root] != white:
            continue
        stack = [(root, iter(adj.get(root, ())))]
        path = [root]
        colour[root] = grey
        while stack:
            node, it = stack[-1]
            advanced = False
            for nxt in it:
                if colour[nxt] == grey:  # back-edge -> everything on the current path stack cycles
                    idx = path.index(nxt)
                    on_cycle.update(path[idx:])
                elif colour[nxt] == white:
                    colour[nxt] = grey
                    stack.append((nxt, iter(adj.get(nxt, ()))))
                    path.append(nxt)
                    advanced = True
                    break
            if not advanced:
                colour[node] = black
                stack.pop()
                path.pop()
    return on_cycle


def _reaches_excluding(adj: dict[object, set], src, dst) -> bool:
    """True if ``dst`` is reachable from ``src`` in ``adj`` WITHOUT using the direct src->dst edge.

    Used to test whether an edge src->dst is transitively implied by a longer path (length >= 2).
    """
    stack = [n for n in adj.get(src, ()) if n != dst]
    seen = set(stack)
    while stack:
        node = stack.pop()
        if node == dst:
            return True
        # the direct src->dst edge is never traversed (src is not revisited in a DAG)
        for nxt in adj.get(node, ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return False


def reduce_transitive_edges() -> int:
    """Transitive reduction: drop a -R-> c when a longer R-path a -> ... -> c already implies it.

    Runs independently per transitive relation (has_subfield, prerequisite_for). Reachability is
    computed against a SNAPSHOT of the original
    edges, so the result is the canonical transitive reduction (order-independent). Edges that lie
    on a cycle of their relation are skipped, since reduction is only well-defined on a DAG - a
    stray cyclic claim never strips a whole loop. Returns the number of edges removed. Idempotent.
    """
    removed = 0
    with transaction.atomic():
        for rel in _TRANSITIVE_RELATIONS:
            edges = list(ConceptEdge.objects.filter(relation=rel))
            adj: dict = defaultdict(set)
            for e in edges:
                adj[e.source_id].add(e.target_id)

            on_cycle = _nodes_on_cycle(adj)
            redundant_pks = [
                e.pk
                for e in edges
                if e.source_id not in on_cycle
                and e.target_id not in on_cycle
                and _reaches_excluding(adj, e.source_id, e.target_id)
            ]
            removed += ConceptEdge.objects.filter(pk__in=redundant_pks).delete()[0]
    return removed


def top_connected_concept_ids(limit: int = 5) -> list[str]:
    """The ``limit`` most-connected concepts (ids, as ``str``), densest first.

    These are the hubs auto-expand crawls outward from - growing the graph around the parts
    that already matter most rather than wherever the visible canvas happens to be.
    """
    return [
        str(pk)
        for pk in Concept.objects.annotate(
            connections=Count("outgoing", distinct=True) + Count("incoming", distinct=True)
        )
        .order_by("-connections", "name")
        .values_list("id", flat=True)[:limit]
    ]


def top_reach_concept_ids(limit: int = 5) -> list[str]:
    """The ``limit`` highest-REACH concepts (ids, as ``str``), most structure first.

    "Reach" is the recursive subfield + prerequisite-for count (see ``structure_reach_for``) - how
    much of the knowledge structure a concept anchors. Auto-expand crawls outward from these hubs
    so the graph grows around the concepts that ORGANISE the most knowledge, not merely the ones
    with the most immediate neighbours (which is what ``top_connected_concept_ids`` ranks by).
    Ties break by raw degree then name for a stable, deterministic order.
    """
    rows = list(
        Concept.objects.annotate(
            connections=Count("outgoing", distinct=True) + Count("incoming", distinct=True)
        ).values_list("id", "name", "connections")
    )
    if not rows:
        return []
    reaches = structure_reach_for([r[0] for r in rows])
    ranked = sorted(rows, key=lambda r: (-reaches.get(str(r[0]), 0), -r[2], r[1].lower()))
    return [str(r[0]) for r in ranked[:limit]]


def unexpanded_neighbor_ids(concept_id) -> list[str]:
    """Ids (as ``str``) of a concept's still-unexpanded neighbors - its immediate frontier ring.

    Used by the ring crawl's LAST ring to expand only what is still new: expanding a ring marks
    those nodes expanded, so the final call adds exactly the new (deeper) ring and never
    re-expands a node.
    """
    return [
        str(pk)
        for pk in Concept.objects.filter(
            Q(incoming__source_id=concept_id) | Q(outgoing__target_id=concept_id),
            times_expanded=0,
        )
        .values_list("id", flat=True)
        .distinct()
    ]


def all_neighbor_ids(concept_id) -> list[str]:
    """Ids (as ``str``) of ALL of a concept's neighbors, regardless of expansion state.

    The deeper rings of the crawl traverse through ALREADY-EXPANDED neighbors (not just the
    unexpanded frontier) so a "3rd degree" expansion can still reach the unexpanded ring two
    hops out even when the first ring was already expanded by an earlier "2nd degree" run. The
    rings budget bounds the recursion and ``expand_concept`` is idempotent, so passing back
    through an expanded node is a cheap no-op.
    """
    return [
        str(pk)
        for pk in Concept.objects.filter(
            Q(incoming__source_id=concept_id) | Q(outgoing__target_id=concept_id),
        )
        .values_list("id", flat=True)
        .distinct()
    ]


def structure_reach_for(concept_ids) -> dict[str, int]:
    """For each given concept, the number of DISTINCT concepts reachable by following outgoing
    ``has_subfield`` or ``prerequisite_for`` edges transitively.

    This is a concept's recursive subfields plus everything it is (recursively) a prerequisite
    for - i.e. how much of the knowledge STRUCTURE it anchors, which the graph encodes as node
    colour/scale instead of the raw neighbour count. Adjacency is built over the WHOLE graph (not
    just a subgraph) so the count is the true recursive reach; the traversal is iterative and
    guarded by a ``seen`` set, so it is safe on deep chains and any residual cycles. Both graph
    relations are structural, so every edge contributes to reach.
    """
    ids = [str(c) for c in concept_ids]
    if not ids:
        return {}
    out: dict[str, list[str]] = defaultdict(list)
    for source_id, target_id in ConceptEdge.objects.filter(
        relation__in=(Relation.HAS_SUBFIELD, Relation.PREREQUISITE_FOR)
    ).values_list("source_id", "target_id"):
        out[str(source_id)].append(str(target_id))

    def reach(start: str) -> int:
        seen: set[str] = set()
        stack = list(out.get(start, ()))
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            stack.extend(out.get(node, ()))
        seen.discard(start)  # a cycle back to the start must not count the node itself
        return len(seen)

    return {cid: reach(cid) for cid in ids}


def build_subgraph(root: Concept, hops: int = 2) -> dict:
    """BFS outward from ``root`` up to ``hops`` edges, returning ``{nodes, edges}``.

    Both incoming and outgoing edges are followed so the visual subgraph is connected.
    """
    visited: dict = {root.pk: root}
    frontier: deque = deque([(root.pk, 0)])
    edges: list[ConceptEdge] = []
    seen_edges: set = set()

    while frontier:
        node_id, dist = frontier.popleft()
        if dist >= hops:
            continue
        incident = ConceptEdge.objects.filter(
            Q(source_id=node_id) | Q(target_id=node_id)
        ).select_related("source", "target")
        for edge in incident:
            if edge.pk not in seen_edges:
                seen_edges.add(edge.pk)
                edges.append(edge)
            for end in (edge.source, edge.target):
                if end.pk not in visited:
                    visited[end.pk] = end
                    frontier.append((end.pk, dist + 1))

    # Re-fetch the visited nodes annotated with their full-graph degree (not just the
    # degree within this subgraph) so the serializer reports total connections in one query.
    nodes = list(
        Concept.objects.filter(pk__in=visited).annotate(connections=connection_count_annotation())
    )
    # Attach each node's recursive structural reach (subfields + prerequisite-for, transitively
    # over the WHOLE graph) - the graph colours/scales nodes by this, not by raw neighbour count.
    reaches = structure_reach_for([n.pk for n in nodes])
    for n in nodes:
        n.reach = reaches.get(str(n.pk), 0)
    return {"nodes": nodes, "edges": edges}
