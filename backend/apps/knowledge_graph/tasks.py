"""Celery tasks: the recursive concept-expansion loop.

The loop is bounded twice over - by the ``max_depth`` hop budget (a remaining-hops counter
passed down and decremented each level, not a property stored on the node) and by novelty
termination (a branch that produces no new nodes spawns no child tasks).
"""

from celery import shared_task
from django.db import OperationalError

from .services import (
    all_neighbor_ids,
    all_over_trigger_nodes,
    expand_concept,
    expansion_cancelled,
    nodes_over_rerank_trigger,
    reduce_transitive_edges,
    rerank_and_prune,
    unexpanded_neighbor_ids,
)


@shared_task(
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def expand_concept_task(concept_id: str, max_depth: int, *, force: bool = False, epoch=None):
    """Expand one node, then recurse into its new neighbors while the hop budget allows.

    ``max_depth`` is the number of hops still to crawl from here: 1 expands only this node;
    each recursion spends one hop. The start node is irrelevant - this is a local budget.

    ``epoch`` is the cancel epoch this task was enqueued under; if a "Clear queue" has since
    bumped the epoch this task self-drops (doing nothing, spawning nothing), which is how the
    whole queued/prefetched crawl unwinds at once. Children inherit the parent's epoch so a
    clear kills the entire subtree.

    A residual transaction deadlock (``OperationalError``) under heavy parallel fan-out is
    transient, so the task auto-retries with jittered backoff. The node-claim is idempotent
    (an already-expanded node short-circuits), so a retry never double-expands.
    """
    if expansion_cancelled(epoch):
        return

    new_ids = expand_concept(concept_id, force=force)  # only NEW node ids returned

    # Hub control: any node this expansion pushed over the rerank trigger gets an offline
    # LLM rerank-and-prune. Queued separately so a slow LLM call never blocks the crawl.
    for node_id in nodes_over_rerank_trigger(concept_id):
        rerank_node_task.delay(str(node_id), epoch=epoch)

    if max_depth <= 1:
        return
    for cid in new_ids:
        expand_concept_task.delay(cid, max_depth - 1, epoch=epoch)  # children never forced


@shared_task(
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def rerank_node_task(concept_id: str, trigger: int | None = None, epoch=None):
    """LLM-rerank an over-the-trigger node's edges and prune it to the target degree.

    Idempotent and self-guarding: ``rerank_and_prune`` no-ops when the node is already at or
    under the trigger, so duplicate queueing (the same hub touched by several expansions) is
    harmless. ``trigger`` overrides the default >30 threshold - the manual UI button passes the
    target so a node is cleaned down to it on demand, without waiting to grow past 30. ``epoch``
    lets a "Clear queue" drop a still-queued rerank just like an expansion.
    """
    if expansion_cancelled(epoch):
        return
    rerank_and_prune(concept_id, trigger=trigger)


@shared_task(
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def crawl_hub_task(concept_id: str, rings: int, *, epoch=None):
    """Crawl outward from a hub, expanding ``rings`` successive rings of its frontier.

    This is what auto-expand seeds on each of the top-N most-connected concepts. Unlike
    ``expand_concept_task`` (which expands ONE node and recurses only into the brand-new nodes
    it just created), this expands the hub itself if still unexpanded and then steps outward
    ring by ring - so it keeps working even though the top hubs are already expanded (expanding
    them is a no-op; their frontier is what grows). ``rings`` is the remaining-rings budget:
    ``1`` expands the immediate ring, ``2`` that ring plus the next, and so on - i.e. "expand
    for depth 1, then depth 2, then depth 3" as it recurses outward.

    The intermediate rings traverse through ALREADY-EXPANDED neighbours (``all_neighbor_ids``),
    not just the unexpanded frontier, so a deeper crawl still reaches the unexpanded ring even
    when the inner rings were already expanded by an earlier, shallower crawl. Only the LAST
    ring (``rings - 1 == 0``) restricts to ``unexpanded_neighbor_ids`` - there is no point
    queuing a terminal task for a neighbour that is already expanded (it would be a pure no-op).

    Termination is automatic: the rings budget bounds the recursion (it can revisit a node
    around a cycle, but only until the budget runs out), and ``expand_concept`` is idempotent so
    passing back through an expanded node never double-expands it. ``epoch`` is the cancel epoch,
    so a "Clear queue" drops the whole crawl.
    """
    if expansion_cancelled(epoch):
        return

    expand_concept(concept_id)  # expand the hub itself if still unexpanded (no-op otherwise)
    if rings <= 0:
        return
    # Last ring: only still-unexpanded neighbours are worth a terminal task. Deeper rings:
    # traverse through expanded neighbours too, so the crawl can reach the unexpanded ring
    # beyond an already-expanded inner ring.
    next_ring = unexpanded_neighbor_ids if rings - 1 <= 0 else all_neighbor_ids
    for nid in next_ring(concept_id):
        crawl_hub_task.delay(nid, rings - 1, epoch=epoch)


@shared_task
def sweep_rerank_candidates():
    """Periodic sweep: queue a rerank-and-prune for every node over the trigger, graph-wide.

    The expansion-time trigger only re-checks nodes an expansion touched, so a hub can stay
    over the limit once the graph goes idle. This Beat task (see ``SCHEDULED_TASKS``) decouples
    clean-up from expansion entirely. Each queued ``rerank_node_task`` self-guards (no-ops if the
    node is already at/under the trigger), so an overlap with the expansion-time trigger is
    harmless. Returns the number of nodes queued. Epoch-less, so a "Clear queue" never drops it.
    """
    node_ids = all_over_trigger_nodes()
    for node_id in node_ids:
        rerank_node_task.delay(str(node_id))
    return len(node_ids)


@shared_task
def sweep_transitive_edges():
    """Periodic sweep: transitive reduction of the whole hierarchy, graph-wide.

    Removes edges implied by a longer same-relation path - e.g. drops A -has_subfield-> C when
    A -> B -> C already exists, leaving the cleaner A -> B -> C chain. Pure DB work (no LLM),
    idempotent, and a no-op once the graph is already reduced. Decouples this structural
    clean-up from expansion so an idle graph still gets tidied. Returns the number of edges
    removed. Epoch-less, so a "Clear queue" never drops it.
    """
    return reduce_transitive_edges()
