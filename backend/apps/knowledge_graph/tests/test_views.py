from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.knowledge_graph.models import Concept, ConceptEdge


@pytest.mark.django_db
class TestConceptListCreate:
    def test_requires_auth(self, api_client):
        resp = api_client.get(reverse("kg-concept-list"))
        assert resp.status_code == 401

    def test_list_paginated(self, auth_client):
        Concept.objects.create(name="A", slug="a")
        Concept.objects.create(name="B", slug="b")
        resp = auth_client.get(reverse("kg-concept-list"))
        assert resp.status_code == 200
        assert resp.data["count"] == 2

    def test_filter_by_search(self, auth_client):
        Concept.objects.create(name="Physics", slug="physics")
        Concept.objects.create(name="Biology", slug="biology")
        resp = auth_client.get(reverse("kg-concept-list"), {"search": "phys"})
        assert resp.data["count"] == 1
        assert resp.data["results"][0]["name"] == "Physics"

    def test_lists_highest_connections_first_with_count(self, auth_client):
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        c = Concept.objects.create(name="C", slug="c")
        # B is a hub: two structural edges (has_subfield / prerequisite_for). A has one, C is on
        # the receiving end of one.
        ConceptEdge.objects.create(source=a, target=b, relation="has_subfield", weight=0.5)
        ConceptEdge.objects.create(source=b, target=c, relation="prerequisite_for", weight=0.5)
        resp = auth_client.get(reverse("kg-concept-list"))
        results = resp.data["results"]
        assert [r["name"] for r in results] == ["B", "A", "C"]
        assert {r["name"]: r["connections"] for r in results} == {"B": 2, "A": 1, "C": 1}

    def test_orders_by_recursive_reach_when_requested(self, auth_client):
        # A -has_subfield-> B -has_subfield-> C: reach A=2, B=1, C=0 (vs connections B=2, A=1, C=1).
        # ?ordering=-reach must rank by reach and report each row's reach.
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        c = Concept.objects.create(name="C", slug="c")
        ConceptEdge.objects.create(source=a, target=b, relation="has_subfield", weight=0.5)
        ConceptEdge.objects.create(source=b, target=c, relation="has_subfield", weight=0.5)
        resp = auth_client.get(reverse("kg-concept-list"), {"ordering": "-reach"})
        results = resp.data["results"]
        assert [r["name"] for r in results] == ["A", "B", "C"]
        assert {r["name"]: r["reach"] for r in results} == {"A": 2, "B": 1, "C": 0}

    def test_orders_by_reach_ascending(self, auth_client):
        # ?ordering=reach (no minus) ranks lowest reach first.
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        c = Concept.objects.create(name="C", slug="c")
        ConceptEdge.objects.create(source=a, target=b, relation="has_subfield", weight=0.5)
        ConceptEdge.objects.create(source=b, target=c, relation="has_subfield", weight=0.5)
        resp = auth_client.get(reverse("kg-concept-list"), {"ordering": "reach"})
        assert [r["name"] for r in resp.data["results"]] == ["C", "B", "A"]

    def test_reach_ordering_respects_search(self, auth_client):
        # Search filters BEFORE the reach sort, so a non-matching concept is excluded.
        apricot = Concept.objects.create(name="Apricot", slug="apricot")
        apple = Concept.objects.create(name="Apple", slug="apple")
        Concept.objects.create(name="Banana", slug="banana")
        ConceptEdge.objects.create(
            source=apricot, target=apple, relation="has_subfield", weight=0.5
        )
        resp = auth_client.get(reverse("kg-concept-list"), {"ordering": "-reach", "search": "ap"})
        # "ap" matches Apricot + Apple, not Banana; Apricot ranks first (reach 1 vs 0).
        assert [r["name"] for r in resp.data["results"]] == ["Apricot", "Apple"]

    def test_default_list_leaves_reach_null(self, auth_client):
        # Without an explicit reach ordering the recursive metric is not computed (no cost).
        Concept.objects.create(name="A", slug="a")
        resp = auth_client.get(reverse("kg-concept-list"))
        assert resp.data["results"][0]["reach"] is None

    def test_create_node_requires_name(self, auth_client):
        resp = auth_client.post(reverse("kg-concept-list"), {}, format="json")
        assert resp.status_code == 400

    def test_create_node(self, auth_client):
        resp = auth_client.post(reverse("kg-concept-list"), {"name": "Physics"}, format="json")
        assert resp.status_code == 201
        assert resp.data["slug"] == "physics"
        # the graph is start-point agnostic: no root-relative fields are serialized
        assert "topic" not in resp.data
        assert "depth" not in resp.data

    def test_create_existing_returns_200(self, auth_client):
        Concept.objects.create(name="Physics", slug="physics")
        resp = auth_client.post(reverse("kg-concept-list"), {"name": "physics"}, format="json")
        assert resp.status_code == 200

    def test_create_node_seeds_negative_description(self, auth_client):
        resp = auth_client.post(
            reverse("kg-concept-list"),
            {"name": "pop", "negative_description": "Not the stack pop()."},
            format="json",
        )
        assert resp.status_code == 201
        assert resp.data["negative_description"] == "Not the stack pop()."

    def test_create_existing_does_not_clobber_negative_description(self, auth_client):
        # Resolving a colliding name returns the existing node; the seed must not overwrite it.
        Concept.objects.create(name="pop", slug="pop", negative_description="original")
        resp = auth_client.post(
            reverse("kg-concept-list"),
            {"name": "pop", "negative_description": "new value"},
            format="json",
        )
        assert resp.status_code == 200
        assert resp.data["negative_description"] == "original"


@pytest.mark.django_db
class TestConceptDetail:
    def test_returns_neighbors(self, auth_client):
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        ConceptEdge.objects.create(source=a, target=b, relation="has_subfield", weight=0.5)
        resp = auth_client.get(reverse("kg-concept-detail", args=[a.pk]))
        assert resp.status_code == 200
        assert len(resp.data["outgoing"]) == 1
        assert resp.data["outgoing"][0]["target"]["name"] == "B"

    def test_exposes_negative_description(self, auth_client):
        a = Concept.objects.create(
            name="pop", slug="pop", negative_description="Not the stack pop()."
        )
        resp = auth_client.get(reverse("kg-concept-detail", args=[a.pk]))
        assert resp.data["negative_description"] == "Not the stack pop()."

    def test_connections_counts_both_directions(self, auth_client):
        # The detail view is not annotated, so this exercises the serializer fallback count.
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        c = Concept.objects.create(name="C", slug="c")
        ConceptEdge.objects.create(source=a, target=b, relation="has_subfield", weight=0.5)
        ConceptEdge.objects.create(source=c, target=a, relation="prerequisite_for", weight=0.5)
        resp = auth_client.get(reverse("kg-concept-detail", args=[a.pk]))
        assert resp.data["connections"] == 2  # one outgoing + one incoming structural edge


@pytest.mark.django_db
class TestConceptDelete:
    def test_requires_auth(self, api_client):
        c = Concept.objects.create(name="A", slug="a")
        resp = api_client.delete(reverse("kg-concept-detail", args=[c.pk]))
        assert resp.status_code == 401
        assert Concept.objects.filter(pk=c.pk).exists()

    def test_delete_removes_node(self, auth_client):
        c = Concept.objects.create(name="A", slug="a")
        resp = auth_client.delete(reverse("kg-concept-detail", args=[c.pk]))
        assert resp.status_code == 204
        assert not Concept.objects.filter(pk=c.pk).exists()

    def test_delete_cascades_to_edges(self, auth_client):
        # Deleting a node removes both its incoming and outgoing edges, but leaves the
        # neighbor node itself intact.
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        ConceptEdge.objects.create(source=a, target=b, relation="prerequisite_for", weight=0.5)
        ConceptEdge.objects.create(source=b, target=a, relation="has_subfield", weight=0.5)
        resp = auth_client.delete(reverse("kg-concept-detail", args=[a.pk]))
        assert resp.status_code == 204
        assert ConceptEdge.objects.count() == 0
        assert Concept.objects.filter(pk=b.pk).exists()


@pytest.mark.django_db
class TestConceptGraph:
    def test_graph_shape_and_hop_cap(self, auth_client):
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        ConceptEdge.objects.create(source=a, target=b, relation="has_subfield", weight=0.5)
        resp = auth_client.get(reverse("kg-concept-graph", args=[a.pk]), {"hops": 1})
        assert resp.status_code == 200
        assert {n["slug"] for n in resp.data["nodes"]} == {"a", "b"}
        assert len(resp.data["edges"]) == 1

    def test_nodes_report_full_graph_degree(self, auth_client):
        # b sits just outside the 1-hop subgraph from a, but its edge still counts toward
        # a's reported connections (degree is over the whole graph, not the visible subgraph).
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        c = Concept.objects.create(name="C", slug="c")
        ConceptEdge.objects.create(source=a, target=b, relation="has_subfield", weight=0.5)
        ConceptEdge.objects.create(source=b, target=c, relation="has_subfield", weight=0.5)
        resp = auth_client.get(reverse("kg-concept-graph", args=[a.pk]), {"hops": 1})
        by_slug = {n["slug"]: n for n in resp.data["nodes"]}
        assert set(by_slug) == {"a", "b"}  # c is 2 hops away, not in the subgraph
        assert by_slug["a"]["connections"] == 1
        assert by_slug["b"]["connections"] == 2  # a->b and b->c, even though c is off-screen

    def test_nodes_report_recursive_structural_reach(self, auth_client):
        # a -has_subfield-> b -has_subfield-> c. Reach is the recursive subfield/prereq count over
        # the WHOLE graph: a reaches b and c (=2) even though c is off-screen at hops=1.
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        c = Concept.objects.create(name="C", slug="c")
        ConceptEdge.objects.create(source=a, target=b, relation="has_subfield", weight=0.5)
        ConceptEdge.objects.create(source=b, target=c, relation="has_subfield", weight=0.5)
        resp = auth_client.get(reverse("kg-concept-graph", args=[a.pk]), {"hops": 1})
        by_slug = {n["slug"]: n for n in resp.data["nodes"]}
        assert by_slug["a"]["reach"] == 2  # b + c, transitively, across the hop boundary
        assert by_slug["b"]["reach"] == 1  # c


@pytest.mark.django_db
class TestConceptExpand:
    def test_first_degree_expands_just_the_node(self, auth_client):
        c = Concept.objects.create(name="Physics", slug="physics")
        with (
            patch("apps.knowledge_graph.views.expand_concept_task.delay") as m,
            patch("apps.knowledge_graph.views.current_cancel_epoch", return_value=7),
        ):
            resp = auth_client.post(
                reverse("kg-concept-expand", args=[c.pk]),
                {"max_depth": 1, "force": True},
                format="json",
            )
        assert resp.status_code == 202
        # The current cancel epoch is stamped on the task so a later Clear can drop it.
        m.assert_called_once_with(str(c.pk), 1, force=True, epoch=7)

    def test_higher_degree_crawls_the_frontier(self, auth_client):
        # 2nd+ degree expands the node's EXISTING frontier ring by ring via the hub crawl,
        # so "2nd degree" expands the neighbours. rings = max_depth - 1.
        c = Concept.objects.create(name="Physics", slug="physics")
        with (
            patch("apps.knowledge_graph.views.crawl_hub_task.delay") as m,
            patch("apps.knowledge_graph.views.current_cancel_epoch", return_value=7),
        ):
            resp = auth_client.post(
                reverse("kg-concept-expand", args=[c.pk]),
                {"max_depth": 3, "force": True},
                format="json",
            )
        assert resp.status_code == 202
        m.assert_called_once_with(str(c.pk), 2, epoch=7)

    def test_expand_uses_default_depth(self, auth_client):
        # Default depth (>1) routes through the frontier crawl with rings = depth - 1.
        c = Concept.objects.create(name="Physics", slug="physics")
        with patch("apps.knowledge_graph.views.crawl_hub_task.delay") as m:
            resp = auth_client.post(reverse("kg-concept-expand", args=[c.pk]), {}, format="json")
        assert resp.status_code == 202
        args = m.call_args.args
        assert args[1] >= 1  # defaulted (max_depth - 1) rings


@pytest.mark.django_db
class TestConceptRerank:
    def test_requires_auth(self, api_client):
        c = Concept.objects.create(name="Physics", slug="physics")
        resp = api_client.post(reverse("kg-concept-rerank", args=[c.pk]))
        assert resp.status_code == 401

    def test_queues_rerank_with_target_trigger(self, auth_client):
        c = Concept.objects.create(name="Physics", slug="physics")
        with (
            patch("apps.knowledge_graph.views.rerank_node_task.delay") as m,
            patch("apps.knowledge_graph.views.current_cancel_epoch", return_value=7),
        ):
            resp = auth_client.post(reverse("kg-concept-rerank", args=[c.pk]))
        assert resp.status_code == 202
        # Manual trigger passes the target so the node is cleaned to it on demand (not >30).
        from apps.knowledge_graph.config import rerank_target

        m.assert_called_once_with(str(c.pk), trigger=rerank_target(), epoch=7)


@pytest.mark.django_db
class TestAutoExpand:
    def test_requires_auth(self, api_client):
        resp = api_client.post(reverse("kg-expansion-auto"))
        assert resp.status_code == 401

    def test_seeds_crawl_for_top_reach_hubs(self, auth_client):
        # A -has_subfield-> B -has_subfield-> C: reach A=2, B=1, C=0 (B is the densest by degree,
        # but A anchors the most structure). Auto-expand now seeds the highest-REACH hub first, at
        # the requested depth, stamped with the current cancel epoch.
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        c = Concept.objects.create(name="C", slug="c")
        ConceptEdge.objects.create(source=a, target=b, relation="has_subfield", weight=0.5)
        ConceptEdge.objects.create(source=b, target=c, relation="has_subfield", weight=0.5)
        with (
            patch("apps.knowledge_graph.views.crawl_hub_task.delay") as m,
            patch("apps.knowledge_graph.views.current_cancel_epoch", return_value=4),
        ):
            resp = auth_client.post(reverse("kg-expansion-auto"), {"max_depth": 3}, format="json")
        assert resp.status_code == 202
        assert resp.data["max_depth"] == 3
        assert resp.data["hubs"][0] == str(a.pk)  # highest-reach hub leads (not the densest, B)
        # Every seeded hub is crawled at the requested depth with the live epoch.
        for call in m.call_args_list:
            assert call.args[1] == 3
            assert call.kwargs == {"epoch": 4}
        assert {call.args[0] for call in m.call_args_list} == {str(a.pk), str(b.pk), str(c.pk)}


@pytest.mark.django_db
class TestExpansionClear:
    def test_requires_auth(self, api_client):
        resp = api_client.post(reverse("kg-expansion-clear"))
        assert resp.status_code == 401

    def test_clears_queue(self, auth_client):
        with patch(
            "apps.knowledge_graph.views.clear_expansion_queue",
            return_value={"purged": 12, "epoch": 3},
        ) as m:
            resp = auth_client.post(reverse("kg-expansion-clear"))
        assert resp.status_code == 200
        assert resp.data == {"status": "cleared", "purged": 12, "epoch": 3}
        m.assert_called_once_with()


@pytest.mark.django_db
class TestRerankAll:
    def test_requires_auth(self, api_client):
        resp = api_client.post(reverse("kg-rerank-all"))
        assert resp.status_code == 401

    def test_queues_rerank_for_every_over_trigger_node(self, auth_client):
        # Two hubs over the trigger; a small node is ignored.
        hubs = []
        for h in range(2):
            hub = Concept.objects.create(name=f"Hub{h}", slug=f"hub{h}")
            hubs.append(hub)
            for i in range(31):
                s = Concept.objects.create(name=f"H{h}S{i}", slug=f"h{h}s{i}")
                ConceptEdge.objects.create(
                    source=hub, target=s, relation="has_subfield", weight=0.9
                )
        with (
            patch("apps.knowledge_graph.views.rerank_node_task.delay") as m,
            patch("apps.knowledge_graph.views.current_cancel_epoch", return_value=7),
        ):
            resp = auth_client.post(reverse("kg-rerank-all"))
        assert resp.status_code == 202
        assert resp.data == {"status": "started", "queued": 2}
        queued_ids = {call.args[0] for call in m.call_args_list}
        assert queued_ids == {str(h.pk) for h in hubs}
        assert all(call.kwargs == {"epoch": 7} for call in m.call_args_list)

    def test_noop_when_nothing_over_trigger(self, auth_client):
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        ConceptEdge.objects.create(source=a, target=b, relation="has_subfield", weight=0.9)
        with patch("apps.knowledge_graph.views.rerank_node_task.delay") as m:
            resp = auth_client.post(reverse("kg-rerank-all"))
        assert resp.status_code == 202
        assert resp.data == {"status": "started", "queued": 0}
        m.assert_not_called()


@pytest.mark.django_db
class TestReduceTransitiveEdges:
    def test_requires_auth(self, api_client):
        resp = api_client.post(reverse("kg-edges-reduce"))
        assert resp.status_code == 401

    def test_reduces_and_reports_count(self, auth_client):
        with patch("apps.knowledge_graph.views.reduce_transitive_edges", return_value=3) as m:
            resp = auth_client.post(reverse("kg-edges-reduce"))
        assert resp.status_code == 200
        assert resp.data == {"status": "reduced", "removed": 3}
        m.assert_called_once_with()
