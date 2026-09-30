from unittest.mock import patch

import pytest

from apps.knowledge_graph import services
from apps.knowledge_graph.models import Concept, ConceptEdge
from apps.knowledge_graph.services import resolve_concept
from apps.knowledge_graph.tasks import (
    crawl_hub_task,
    expand_concept_task,
    rerank_node_task,
    sweep_rerank_candidates,
    sweep_transitive_edges,
)


def _chain_expand(name, existing=None):
    """Fake expansion that always offers one fresh child named '<name>-child'.

    Left unbounded this would recurse forever; only the max_depth hop budget / novelty
    termination stops it.
    """
    return {
        "description": f"{name} desc",
        "neighbors": [{"name": f"{name}-child", "relation": "has_subfield", "weight": 0.9}],
    }


@pytest.mark.django_db
class TestExpandConceptTask:
    def test_fans_out_one_level(self):
        root, _ = resolve_concept("Physics")
        with patch.object(services, "expand", side_effect=_chain_expand):
            expand_concept_task(str(root.pk), max_depth=1)
        # root expanded + one child created; child not expanded (hop budget spent)
        assert Concept.objects.count() == 2
        child = Concept.objects.exclude(pk=root.pk).get()
        assert child.times_expanded == 0
        assert ConceptEdge.objects.filter(source=root, target=child).count() == 1

    def test_single_level_expand_never_recurses(self):
        # The per-node "Expand" UI sends max_depth=1 for ANY node. A hop budget of 1 expands
        # exactly that one node and recurses into nothing - the guarantee the frontend relies on.
        node = Concept.objects.create(name="Optics", slug="optics")
        with (
            patch.object(services, "expand", side_effect=_chain_expand),
            patch.object(expand_concept_task, "delay") as delay,
        ):
            expand_concept_task(str(node.pk), max_depth=1)
        node.refresh_from_db()
        assert node.times_expanded == 1
        child = Concept.objects.exclude(pk=node.pk).get()
        assert child.times_expanded == 0
        delay.assert_not_called()  # no recursion into the new child

    def test_recursion_stops_at_max_depth(self):
        # Run child .delay() synchronously so recursion is deterministic in tests (in
        # production each .delay enqueues to the broker for a worker to pick up).
        def run_sync(*args, **kwargs):
            return expand_concept_task(*args, **kwargs)

        root, _ = resolve_concept("Physics")
        with (
            patch.object(services, "expand", side_effect=_chain_expand),
            patch.object(expand_concept_task, "delay", side_effect=run_sync),
        ):
            expand_concept_task(str(root.pk), max_depth=2)
        # 3 nodes created across 2 hops; the last one is the leaf (never expanded)
        assert Concept.objects.count() == 3
        assert Concept.objects.filter(times_expanded=0).count() == 1
        assert Concept.objects.filter(times_expanded__gt=0).count() == 2

    def test_hop_budget_decrements_each_level(self):
        # The budget is a remaining-hops counter, not a stored node field: starting at N it
        # expands N nodes down a chain and each recursive call spends exactly one hop.
        def run_sync(*args, **kwargs):
            return expand_concept_task(*args, **kwargs)

        root, _ = resolve_concept("Physics")
        with (
            patch.object(services, "expand", side_effect=_chain_expand),
            patch.object(expand_concept_task, "delay", side_effect=run_sync) as delay,
        ):
            expand_concept_task(str(root.pk), max_depth=3)
        # 4 nodes across 3 hops; budgets handed to recursive calls strictly decrement to 1.
        assert Concept.objects.count() == 4
        assert Concept.objects.filter(times_expanded__gt=0).count() == 3  # only leaf unexpanded
        recursive_budgets = [call.args[1] for call in delay.call_args_list]
        assert recursive_budgets == [2, 1]  # root(3) -> child(2) -> grandchild(1) stops

    def test_novelty_termination_on_existing_nodes(self):
        root, _ = resolve_concept("Physics")

        def all_existing(name, existing=None):
            return {
                "description": "d",
                "neighbors": [{"name": "Physics", "relation": "has_subfield", "weight": 1.0}],
            }

        with patch.object(services, "expand", side_effect=all_existing):
            expand_concept_task(str(root.pk), max_depth=5)
        # only the root exists; the self-reference produced no new nodes -> no recursion
        assert Concept.objects.count() == 1

    def test_node_cap_short_circuits(self):
        root, _ = resolve_concept("Physics")
        with (
            patch.object(services, "max_nodes", return_value=0),
            patch.object(services, "expand", side_effect=_chain_expand) as m,
        ):
            expand_concept_task(str(root.pk), max_depth=2)
        m.assert_not_called()
        assert Concept.objects.count() == 1

    def test_expansion_queues_rerank_for_over_trigger_node(self):
        # A hub already over the rerank trigger: expanding it should queue a rerank task.
        hub = Concept.objects.create(name="Physics", slug="physics")
        for i in range(31):
            s = Concept.objects.create(name=f"S{i}", slug=f"s{i}")
            ConceptEdge.objects.create(source=hub, target=s, relation="has_subfield", weight=0.9)
        with (
            patch.object(services, "expand", return_value={"description": "d", "neighbors": []}),
            patch.object(rerank_node_task, "delay") as delay,
        ):
            expand_concept_task(str(hub.pk), max_depth=1)
        delay.assert_called_once_with(str(hub.pk), epoch=None)

    def test_small_expansion_does_not_queue_rerank(self):
        root, _ = resolve_concept("Physics")
        with (
            patch.object(services, "expand", side_effect=_chain_expand),
            patch.object(rerank_node_task, "delay") as delay,
        ):
            expand_concept_task(str(root.pk), max_depth=1)
        delay.assert_not_called()


@pytest.mark.django_db
class TestExpansionCancel:
    def test_stale_epoch_task_self_drops(self):
        # A task enqueued under an older epoch than the current one is dropped wholesale: it
        # never calls the LLM, expands nothing, and spawns no children.
        root, _ = resolve_concept("Physics")
        with (
            patch("apps.knowledge_graph.tasks.expansion_cancelled", return_value=True),
            patch.object(services, "expand", side_effect=_chain_expand) as m,
            patch.object(expand_concept_task, "delay") as delay,
        ):
            expand_concept_task(str(root.pk), max_depth=3, epoch=1)
        m.assert_not_called()
        delay.assert_not_called()
        assert Concept.objects.count() == 1
        root.refresh_from_db()
        assert root.times_expanded == 0

    def test_current_epoch_task_runs(self):
        # A task whose epoch is still current runs normally.
        root, _ = resolve_concept("Physics")
        with (
            patch("apps.knowledge_graph.tasks.expansion_cancelled", return_value=False),
            patch.object(services, "expand", side_effect=_chain_expand),
        ):
            expand_concept_task(str(root.pk), max_depth=1, epoch=5)
        root.refresh_from_db()
        assert root.times_expanded == 1
        assert Concept.objects.count() == 2

    def test_stale_epoch_rerank_self_drops(self):
        hub = Concept.objects.create(name="Physics", slug="physics")
        with (
            patch("apps.knowledge_graph.tasks.expansion_cancelled", return_value=True),
            patch.object(services, "rerank_and_prune") as m,
        ):
            rerank_node_task(str(hub.pk), epoch=1)
        m.assert_not_called()


@pytest.mark.django_db
class TestCrawlHubTask:
    def _run_sync(self):
        # Run child .delay() inline so the ring crawl is deterministic in tests.
        def run_sync(*args, **kwargs):
            return crawl_hub_task(*args, **kwargs)

        return run_sync

    def test_one_ring_expands_immediate_unexpanded_neighbors(self):
        # An already-expanded hub with two unexpanded neighbors. rings=1 expands exactly that
        # ring (the hub itself is a no-op) and goes no deeper.
        hub = Concept.objects.create(name="Hub", slug="hub", times_expanded=1)
        n1 = Concept.objects.create(name="N1", slug="n1")
        n2 = Concept.objects.create(name="N2", slug="n2")
        ConceptEdge.objects.create(source=hub, target=n1, relation="has_subfield", weight=0.9)
        ConceptEdge.objects.create(source=hub, target=n2, relation="has_subfield", weight=0.9)
        with (
            patch.object(services, "expand", return_value={"description": "d", "neighbors": []}),
            patch.object(crawl_hub_task, "delay", side_effect=self._run_sync()),
        ):
            crawl_hub_task(str(hub.pk), rings=1)
        n1.refresh_from_db()
        n2.refresh_from_db()
        assert n1.times_expanded == 1
        assert n2.times_expanded == 1

    def test_one_ring_stops_short_of_the_next_ring(self):
        # Hub -> A -> B chain, hub already expanded, A and B unexpanded. A single rings=1 crawl
        # reaches only A (the immediate ring); B is one ring too far.
        hub = Concept.objects.create(name="Hub", slug="hub", times_expanded=1)
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        ConceptEdge.objects.create(source=hub, target=a, relation="has_subfield", weight=0.9)
        ConceptEdge.objects.create(source=a, target=b, relation="has_subfield", weight=0.9)
        with (
            patch.object(services, "expand", return_value={"description": "d", "neighbors": []}),
            patch.object(crawl_hub_task, "delay", side_effect=self._run_sync()),
        ):
            crawl_hub_task(str(hub.pk), rings=1)
        a.refresh_from_db()
        b.refresh_from_db()
        assert a.times_expanded == 1
        assert b.times_expanded == 0  # one ring short

    def test_deeper_rings_crawl_the_whole_chain_in_one_call(self):
        # The same chain, but a single rings=2 crawl reaches A then the next ring B - the crawl
        # recurses THROUGH each node as it expands it (depth 1, then depth 2) within one call.
        hub = Concept.objects.create(name="Hub", slug="hub", times_expanded=1)
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        ConceptEdge.objects.create(source=hub, target=a, relation="has_subfield", weight=0.9)
        ConceptEdge.objects.create(source=a, target=b, relation="has_subfield", weight=0.9)
        with (
            patch.object(services, "expand", return_value={"description": "d", "neighbors": []}),
            patch.object(crawl_hub_task, "delay", side_effect=self._run_sync()),
        ):
            crawl_hub_task(str(hub.pk), rings=2)
        a.refresh_from_db()
        b.refresh_from_db()
        assert a.times_expanded == 1
        assert b.times_expanded == 1  # the deeper ring is reached in the same crawl

    def test_deeper_ring_reaches_through_an_already_expanded_inner_ring(self):
        # Hub -> A -> B, with hub AND A already expanded (e.g. a previous "2nd degree" run) but B
        # still unexpanded. A crawl that only followed unexpanded neighbours would stop at the
        # already-expanded A and never reach B. rings=2 must traverse THROUGH A to expand B.
        hub = Concept.objects.create(name="Hub", slug="hub", times_expanded=1)
        a = Concept.objects.create(name="A", slug="a", times_expanded=1)
        b = Concept.objects.create(name="B", slug="b")
        ConceptEdge.objects.create(source=hub, target=a, relation="has_subfield", weight=0.9)
        ConceptEdge.objects.create(source=a, target=b, relation="has_subfield", weight=0.9)
        with (
            patch.object(services, "expand", return_value={"description": "d", "neighbors": []}),
            patch.object(crawl_hub_task, "delay", side_effect=self._run_sync()),
        ):
            crawl_hub_task(str(hub.pk), rings=2)
        b.refresh_from_db()
        assert b.times_expanded == 1  # reached through the already-expanded inner ring

    def test_respects_cancel_epoch(self):
        hub = Concept.objects.create(name="Hub", slug="hub", times_expanded=1)
        n1 = Concept.objects.create(name="N1", slug="n1")
        ConceptEdge.objects.create(source=hub, target=n1, relation="has_subfield", weight=0.9)
        with (
            patch("apps.knowledge_graph.tasks.expansion_cancelled", return_value=True),
            patch.object(services, "expand") as m,
        ):
            crawl_hub_task(str(hub.pk), rings=3, epoch=1)
        m.assert_not_called()
        n1.refresh_from_db()
        assert n1.times_expanded == 0


@pytest.mark.django_db
class TestSweepRerankCandidates:
    def test_queues_rerank_for_each_over_trigger_node(self):
        # Two hubs over a trigger of 30, plus a small node that should be ignored.
        hubs = []
        for h in range(2):
            hub = Concept.objects.create(name=f"Hub{h}", slug=f"hub{h}")
            hubs.append(hub)
            for i in range(31):
                s = Concept.objects.create(name=f"H{h}S{i}", slug=f"h{h}s{i}")
                ConceptEdge.objects.create(
                    source=hub, target=s, relation="has_subfield", weight=0.9
                )
        small = Concept.objects.create(name="Small", slug="small")
        other = Concept.objects.create(name="Other", slug="other")
        ConceptEdge.objects.create(source=small, target=other, relation="has_subfield", weight=0.9)

        with patch.object(rerank_node_task, "delay") as delay:
            queued = sweep_rerank_candidates()

        assert queued == 2
        queued_ids = {call.args[0] for call in delay.call_args_list}
        assert queued_ids == {str(h.pk) for h in hubs}
        assert str(small.pk) not in queued_ids

    def test_noop_when_nothing_over_trigger(self):
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        ConceptEdge.objects.create(source=a, target=b, relation="has_subfield", weight=0.9)
        with patch.object(rerank_node_task, "delay") as delay:
            assert sweep_rerank_candidates() == 0
        delay.assert_not_called()


@pytest.mark.django_db
class TestSweepTransitiveEdges:
    def test_removes_redundant_chain_edge(self):
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        c = Concept.objects.create(name="C", slug="c")
        ConceptEdge.objects.create(source=a, target=b, relation="has_subfield", weight=0.9)
        ConceptEdge.objects.create(source=b, target=c, relation="has_subfield", weight=0.9)
        redundant = ConceptEdge.objects.create(
            source=a, target=c, relation="has_subfield", weight=0.9
        )
        assert sweep_transitive_edges() == 1
        assert not ConceptEdge.objects.filter(pk=redundant.pk).exists()
        assert ConceptEdge.objects.count() == 2

    def test_noop_when_already_reduced(self):
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        ConceptEdge.objects.create(source=a, target=b, relation="has_subfield", weight=0.9)
        assert sweep_transitive_edges() == 0
        assert ConceptEdge.objects.count() == 1
