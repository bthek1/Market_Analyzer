from unittest.mock import patch

import pytest
from django.db.models import Q

from apps.knowledge_graph import services
from apps.knowledge_graph.models import Concept, ConceptAlias, ConceptEdge


def _expansion(description="desc", neighbors=None, negative_description=""):
    return {
        "description": description,
        "negative_description": negative_description,
        "neighbors": neighbors or [],
    }


@pytest.mark.django_db
class TestResolveConcept:
    def test_exact_slug_returns_existing(self):
        existing = Concept.objects.create(name="Physics", slug="physics")
        got, created = services.resolve_concept("physics")
        assert got.pk == existing.pk
        assert created is False

    def test_novel_name_creates(self):
        got, created = services.resolve_concept("Quantum Mechanics")
        assert created is True
        assert got.slug == "quantum-mechanics"

    def test_degrades_to_slug_only_without_trigram(self):
        # On SQLite (tests) the trigram step is skipped, so a near variant creates a
        # separate node rather than merging.
        Concept.objects.create(name="quantum mechanics", slug="quantum-mechanics")
        assert services._trigram_supported() is False
        got, created = services.resolve_concept("quantum mechanic")
        assert created is True
        assert got.slug == "quantum-mechanic"

    def test_base_slug_defaults_to_slug(self):
        c = Concept.objects.create(name="Physics", slug="physics")
        c.refresh_from_db()
        assert c.base_slug == "physics"


@pytest.mark.django_db
class TestResolveConceptSenses:
    """Word-sense disambiguation: a name colliding with an established concept is judged."""

    def _established_pop(self):
        return Concept.objects.create(name="pop", slug="pop", description="pop music genre")

    def test_reuses_matched_sense(self):
        pop = self._established_pop()
        with (
            patch("apps.knowledge_graph.services.wsd_enabled", return_value=True),
            patch(
                "apps.knowledge_graph.services.disambiguate_sense", return_value=str(pop.pk)
            ) as judge,
        ):
            got, created = services.resolve_concept(
                "pop", context={"domain": "dance", "relation": "has_subfield"}
            )
        assert created is False
        assert got.pk == pop.pk
        judge.assert_called_once()

    def test_mints_new_sense_for_different_meaning(self):
        pop = self._established_pop()
        with (
            patch("apps.knowledge_graph.services.wsd_enabled", return_value=True),
            patch("apps.knowledge_graph.services.disambiguate_sense", return_value=None),
        ):
            got, created = services.resolve_concept(
                "pop", context={"domain": "stacks", "relation": "prerequisite_for"}
            )
        assert created is True
        assert got.pk != pop.pk
        assert got.base_slug == "pop"  # shares the lexical key...
        assert got.slug != "pop"  # ...but is a distinct, disambiguated sense
        assert got.slug.startswith("pop-")
        assert "stacks" in got.name  # display name carries the domain: "pop (stacks)"
        # Both senses now coexist under the same base_slug.
        assert set(Concept.objects.filter(base_slug="pop").values_list("slug", flat=True)) == {
            "pop",
            got.slug,
        }

    def test_empty_stub_reused_without_invoking_judge(self):
        # A same-name node with no committed meaning (no description) is reused directly - there is
        # nothing to disambiguate yet, so the judge is never called.
        stub = Concept.objects.create(name="pop", slug="pop")
        with (
            patch("apps.knowledge_graph.services.wsd_enabled", return_value=True),
            patch("apps.knowledge_graph.services.disambiguate_sense") as judge,
        ):
            got, created = services.resolve_concept(
                "pop", context={"domain": "stacks", "relation": "prerequisite_for"}
            )
        assert got.pk == stub.pk
        assert created is False
        judge.assert_not_called()

    def test_wsd_disabled_reuses_first_without_judge(self):
        pop = self._established_pop()
        with (
            patch("apps.knowledge_graph.services.wsd_enabled", return_value=False),
            patch("apps.knowledge_graph.services.disambiguate_sense") as judge,
        ):
            got, created = services.resolve_concept(
                "pop", context={"domain": "stacks", "relation": "prerequisite_for"}
            )
        assert got.pk == pop.pk
        assert created is False
        judge.assert_not_called()

    def test_degrades_to_reuse_when_judge_raises(self):
        pop = self._established_pop()
        with (
            patch("apps.knowledge_graph.services.wsd_enabled", return_value=True),
            patch(
                "apps.knowledge_graph.services.disambiguate_sense",
                side_effect=RuntimeError("boom"),
            ),
        ):
            got, created = services.resolve_concept(
                "pop", context={"domain": "stacks", "relation": "prerequisite_for"}
            )
        assert got.pk == pop.pk  # never over-splits on a flaky judge
        assert created is False

    def test_no_context_reuses_legacy(self):
        # Even with WSD on, a call without usage context cannot disambiguate -> legacy reuse.
        pop = self._established_pop()
        with (
            patch("apps.knowledge_graph.services.wsd_enabled", return_value=True),
            patch("apps.knowledge_graph.services.disambiguate_sense") as judge,
        ):
            got, _created = services.resolve_concept("pop")
        assert got.pk == pop.pk
        judge.assert_not_called()


@pytest.mark.django_db
class TestRecordAlias:
    def test_records_a_new_alias(self):
        graph = Concept.objects.create(name="graph", slug="graph")
        services.record_alias(graph, "graphs")
        alias = ConceptAlias.objects.get(slug="graphs")
        assert alias.concept_id == graph.pk
        assert alias.name == "graphs"

    def test_idempotent_no_duplicate_row(self):
        graph = Concept.objects.create(name="graph", slug="graph")
        services.record_alias(graph, "graphs")
        services.record_alias(graph, "graphs")
        assert ConceptAlias.objects.filter(slug="graphs").count() == 1

    def test_skips_when_slug_is_canonical(self):
        graph = Concept.objects.create(name="graph", slug="graph")
        services.record_alias(graph, "Graph")  # slugify -> "graph" == canonical
        assert ConceptAlias.objects.count() == 0

    def test_skips_when_another_concept_owns_the_slug(self):
        graph = Concept.objects.create(name="graph", slug="graph")
        Concept.objects.create(name="graphs", slug="graphs")  # a real distinct node
        services.record_alias(graph, "graphs")
        assert ConceptAlias.objects.count() == 0  # ambiguous - never reassign

    def test_skips_when_alias_already_exists(self):
        graph = Concept.objects.create(name="graph", slug="graph")
        other = Concept.objects.create(name="chart", slug="chart")
        services.record_alias(graph, "graphs")
        services.record_alias(other, "graphs")  # alias already taken by graph
        assert ConceptAlias.objects.get(slug="graphs").concept_id == graph.pk


@pytest.mark.django_db
class TestAliasAwareResolution:
    def test_alias_exact_hit_reuses_node_no_new_node(self):
        graph = Concept.objects.create(name="graph", slug="graph")
        ConceptAlias.objects.create(concept=graph, name="graphs", slug="graphs")
        got, created = services.resolve_concept("graphs")
        assert created is False
        assert got.pk == graph.pk
        assert Concept.objects.count() == 1

    def test_trigram_near_creates_alias_and_reuses(self):
        # The trigram branch is Postgres-only; mock the lookup so the SQLite test exercises the
        # "fuzzy match -> reuse node AND record a permanent alias" behaviour.
        graph = Concept.objects.create(name="graph", slug="graph")
        with (
            patch.object(services, "_trigram_supported", return_value=True),
            patch.object(services, "_trigram_near", return_value=graph),
        ):
            got, created = services.resolve_concept("graphz")
        assert created is False
        assert got.pk == graph.pk
        assert ConceptAlias.objects.filter(slug="graphz", concept=graph).exists()

    def test_second_mention_is_alias_exact_no_trigram(self):
        graph = Concept.objects.create(name="graph", slug="graph")
        with (
            patch.object(services, "_trigram_supported", return_value=True),
            patch.object(services, "_trigram_near", return_value=graph) as near,
        ):
            services.resolve_concept("graphz")  # first: trigram -> alias
            near.reset_mock()
            got, created = services.resolve_concept("graphz")  # second: alias-exact, no trigram
        assert created is False
        assert got.pk == graph.pk
        near.assert_not_called()
        assert ConceptAlias.objects.filter(slug="graphz").count() == 1

    def test_sqlite_alias_path_without_trigram(self):
        # No trigram on SQLite: a brand-new variant still creates a node, but an existing alias
        # resolves exactly.
        assert services._trigram_supported() is False
        graph = Concept.objects.create(name="graph", slug="graph")
        ConceptAlias.objects.create(concept=graph, name="graphs", slug="graphs")
        got, created = services.resolve_concept("graphs")
        assert created is False and got.pk == graph.pk


@pytest.mark.django_db
class TestMergeConcepts:
    def test_merges_duplicate_edges_aliases_and_resolution(self):
        graph = Concept.objects.create(name="graph", slug="graph", description="a graph")
        graphs = Concept.objects.create(name="graphs", slug="graphs")
        node = Concept.objects.create(name="node", slug="node")
        # graphs holds an edge that should land on graph.
        ConceptEdge.objects.create(source=graphs, target=node, relation="has_subfield", weight=0.9)

        summary = services.merge_concepts(graph, [graphs])

        assert summary["nodes_deleted"] == 1
        assert not Concept.objects.filter(slug="graphs").exists()
        # The edge now hangs off graph.
        assert ConceptEdge.objects.filter(source=graph, target=node).exists()
        # graphs is an alias of graph, and resolving either returns graph.
        assert ConceptAlias.objects.filter(slug="graphs", concept=graph).exists()
        assert services.resolve_concept("graphs")[0].pk == graph.pk
        assert services.resolve_concept("graph")[0].pk == graph.pk

    def test_self_loop_after_repoint_is_dropped(self):
        graph = Concept.objects.create(name="graph", slug="graph")
        graphs = Concept.objects.create(name="graphs", slug="graphs")
        # An edge between the two merged nodes would become a self-loop on graph.
        ConceptEdge.objects.create(source=graph, target=graphs, relation="has_subfield", weight=0.5)
        services.merge_concepts(graph, [graphs])
        assert ConceptEdge.objects.count() == 0  # self-loop dropped, not created

    def test_duplicate_aliases_move_and_collisions_skipped(self):
        graph = Concept.objects.create(name="graph", slug="graph")
        graphs = Concept.objects.create(name="graphs", slug="graphs")
        ConceptAlias.objects.create(concept=graphs, name="graphz", slug="graphz")
        # graphs owns an alias whose slug equals the canonical's slug - it must be dropped, not
        # moved (an alias can never share a slug with its own concept).
        ConceptAlias.objects.create(concept=graphs, name="Graph", slug="graph")
        services.merge_concepts(graph, [graphs])
        # graphz moved onto graph; the colliding "graph" alias was dropped.
        assert ConceptAlias.objects.get(slug="graphz").concept_id == graph.pk
        assert not ConceptAlias.objects.filter(slug="graph").exists()

    def test_carries_description_only_when_canonical_empty(self):
        graph = Concept.objects.create(name="graph", slug="graph")  # no description
        graphs = Concept.objects.create(name="graphs", slug="graphs", description="from dup")
        services.merge_concepts(graph, [graphs])
        graph.refresh_from_db()
        assert graph.description == "from dup"

    def test_does_not_clobber_existing_description(self):
        graph = Concept.objects.create(name="graph", slug="graph", description="real")
        graphs = Concept.objects.create(name="graphs", slug="graphs", description="from dup")
        services.merge_concepts(graph, [graphs])
        graph.refresh_from_db()
        assert graph.description == "real"

    def test_merging_node_into_itself_is_noop(self):
        graph = Concept.objects.create(name="graph", slug="graph")
        summary = services.merge_concepts(graph, [graph])
        assert summary["nodes_deleted"] == 0
        assert Concept.objects.filter(slug="graph").exists()


@pytest.mark.django_db
class TestSenseGatedAliasRecording:
    """Phase 3: a same-sense reuse also folds the surface form as an alias (one decision)."""

    def test_same_sense_reuse_records_alias(self):
        # A disambiguated sense (base_slug "pop", canonical slug "pop-music"). Resolving the bare
        # surface form "pop" and the judge confirming this sense folds "pop" as an alias.
        music = Concept.objects.create(
            name="pop (music)", slug="pop-music", base_slug="pop", description="music genre"
        )
        with (
            patch("apps.knowledge_graph.services.wsd_enabled", return_value=True),
            patch("apps.knowledge_graph.services.disambiguate_sense", return_value=str(music.pk)),
        ):
            got, created = services.resolve_concept(
                "pop", context={"domain": "charts", "relation": "has_subfield"}
            )
        assert created is False and got.pk == music.pk
        assert ConceptAlias.objects.filter(slug="pop", concept=music).exists()

    def test_different_sense_records_no_alias(self):
        music = Concept.objects.create(
            name="pop (music)", slug="pop-music", base_slug="pop", description="music genre"
        )
        with (
            patch("apps.knowledge_graph.services.wsd_enabled", return_value=True),
            patch("apps.knowledge_graph.services.disambiguate_sense", return_value=None),
        ):
            got, created = services.resolve_concept(
                "pop", context={"domain": "stacks", "relation": "prerequisite_for"}
            )
        assert created is True and got.pk != music.pk  # a new, distinct sense
        assert not ConceptAlias.objects.exists()  # no alias recorded across senses

    def test_flag_off_writes_no_alias(self):
        music = Concept.objects.create(
            name="pop (music)", slug="pop-music", base_slug="pop", description="music genre"
        )
        with patch("apps.knowledge_graph.services.wsd_enabled", return_value=False):
            got, _created = services.resolve_concept(
                "pop", context={"domain": "charts", "relation": "has_subfield"}
            )
        assert got.pk == music.pk
        assert not ConceptAlias.objects.exists()  # legacy reuse, no alias

    def test_judge_raises_writes_no_alias(self):
        music = Concept.objects.create(
            name="pop (music)", slug="pop-music", base_slug="pop", description="music genre"
        )
        with (
            patch("apps.knowledge_graph.services.wsd_enabled", return_value=True),
            patch(
                "apps.knowledge_graph.services.disambiguate_sense",
                side_effect=RuntimeError("boom"),
            ),
        ):
            got, _created = services.resolve_concept(
                "pop", context={"domain": "charts", "relation": "has_subfield"}
            )
        assert got.pk == music.pk  # degrades to reuse
        assert not ConceptAlias.objects.exists()  # no alias on the degraded path

    def test_evidence_includes_aliases_and_neighbors(self):
        music = Concept.objects.create(
            name="pop (music)", slug="pop-music", base_slug="pop", description="music genre"
        )
        ConceptAlias.objects.create(concept=music, name="pop-genre", slug="pop-genre")
        nb = Concept.objects.create(name="melody", slug="melody")
        ConceptEdge.objects.create(source=music, target=nb, relation="has_subfield", weight=0.9)

        captured = {}

        def fake_judge(name, cands, context, evidence=None):
            captured["evidence"] = evidence
            return str(music.pk)

        with (
            patch("apps.knowledge_graph.services.wsd_enabled", return_value=True),
            patch("apps.knowledge_graph.services.disambiguate_sense", side_effect=fake_judge),
        ):
            services.resolve_concept(
                "pop", context={"domain": "charts", "relation": "has_subfield"}
            )
        ev = captured["evidence"][str(music.pk)]
        assert "pop-genre" in ev["aliases"]
        assert "melody" in ev["neighbors"]


@pytest.mark.django_db
class TestExpandConcept:
    def test_creates_description_and_edges(self):
        root = Concept.objects.create(name="Physics", slug="physics")
        neighbors = [
            {"name": "Quantum Mechanics", "relation": "has_subfield", "weight": 0.9},
            {"name": "Thermodynamics", "relation": "has_subfield", "weight": 0.8},
        ]
        with patch.object(services, "expand", return_value=_expansion("Physics is...", neighbors)):
            new_ids = services.expand_concept(root.pk)

        root.refresh_from_db()
        assert root.description == "Physics is..."
        assert root.times_expanded == 1
        assert len(new_ids) == 2
        assert ConceptEdge.objects.filter(source=root).count() == 2

    def test_persists_negative_description(self):
        root = Concept.objects.create(name="pop", slug="pop")
        with patch.object(
            services,
            "expand",
            return_value=_expansion("music genre", negative_description="Not the stack pop()."),
        ):
            services.expand_concept(root.pk)
        root.refresh_from_db()
        assert root.negative_description == "Not the stack pop()."

    def test_expansion_splits_a_homonym_into_a_new_sense(self):
        # "pop" already exists as an established MUSIC concept. Expanding "stacks" with a neighbour
        # "pop" (the stack operation) must NOT merge into the music node: with WSD on and the judge
        # ruling "different", a new disambiguated sense is created and the edge lands on it.
        Concept.objects.create(name="pop", slug="pop", description="pop music genre")
        stacks = Concept.objects.create(name="stacks", slug="stacks")
        neighbors = [
            {"name": "pop", "relation": "prerequisite_for", "source_is_self": False, "weight": 0.7},
        ]
        with (
            patch.object(services, "expand", return_value=_expansion("LIFO structure", neighbors)),
            patch("apps.knowledge_graph.services.wsd_enabled", return_value=True),
            patch("apps.knowledge_graph.services.disambiguate_sense", return_value=None),
        ):
            services.expand_concept(stacks.pk)

        senses = Concept.objects.filter(base_slug="pop")
        assert senses.count() == 2  # the music sense + a new stack-operation sense
        new = senses.exclude(slug="pop").get()
        assert "stacks" in new.name  # "pop (stacks)"
        # The stacks edge lands on the NEW sense; the music "pop" stays edge-free (no bridge).
        assert ConceptEdge.objects.filter(source=new, target=stacks).exists()
        assert not ConceptEdge.objects.filter(
            Q(source__slug="pop") | Q(target__slug="pop")
        ).exists()

    def test_parent_neighbor_edge_points_into_the_node(self):
        # A neighbor the LLM marks as a broader parent (source_is_self False) must produce a
        # has_subfield edge parent -> this node, i.e. pointing INTO this node as the child.
        root = Concept.objects.create(name="Quantum Mechanics", slug="qm")
        neighbors = [
            {
                "name": "Physics",
                "relation": "has_subfield",
                "source_is_self": False,
                "weight": 0.9,
            },
        ]
        with patch.object(services, "expand", return_value=_expansion(neighbors=neighbors)):
            new_ids = services.expand_concept(root.pk)

        assert len(new_ids) == 1
        edge = ConceptEdge.objects.get()
        assert edge.target_id == root.pk  # parent -> this node (this node is the child)
        assert edge.relation == "has_subfield"

    def test_second_call_without_force_is_noop(self):
        root = Concept.objects.create(name="Physics", slug="physics", times_expanded=1)
        with patch.object(services, "expand") as m:
            new_ids = services.expand_concept(root.pk)
        m.assert_not_called()
        assert new_ids == []

    def test_force_reexpands(self):
        root = Concept.objects.create(name="Physics", slug="physics", times_expanded=1)
        with patch.object(services, "expand", return_value=_expansion()):
            services.expand_concept(root.pk, force=True)
        root.refresh_from_db()
        assert root.times_expanded == 2

    def test_self_edge_skipped(self):
        root = Concept.objects.create(name="Physics", slug="physics")
        neighbors = [{"name": "Physics", "relation": "has_subfield", "weight": 1.0}]
        with patch.object(services, "expand", return_value=_expansion(neighbors=neighbors)):
            new_ids = services.expand_concept(root.pk)
        assert new_ids == []
        assert ConceptEdge.objects.count() == 0

    def test_repeat_edge_updates_weight_running_mean(self):
        root = Concept.objects.create(name="Physics", slug="physics")
        Concept.objects.create(name="Quantum Mechanics", slug="quantum-mechanics")
        neighbors = [{"name": "Quantum Mechanics", "relation": "has_subfield", "weight": 0.4}]
        with patch.object(services, "expand", return_value=_expansion(neighbors=neighbors)):
            services.expand_concept(root.pk)
            services.expand_concept(root.pk, force=True)

        edge = ConceptEdge.objects.get(source=root)
        assert edge.times_seen == 2
        assert edge.weight == pytest.approx(0.4)

    def test_all_existing_neighbors_returns_empty(self):
        root = Concept.objects.create(name="Physics", slug="physics")
        Concept.objects.create(name="Quantum Mechanics", slug="quantum-mechanics")
        neighbors = [{"name": "Quantum Mechanics", "relation": "has_subfield", "weight": 0.9}]
        with patch.object(services, "expand", return_value=_expansion(neighbors=neighbors)):
            new_ids = services.expand_concept(root.pk)
        assert new_ids == []  # node already existed -> not "new"
        assert ConceptEdge.objects.count() == 1


@pytest.mark.django_db
class TestSingleEdgePerPair:
    def _pair_edges(self, a, b):
        return [e for e in ConceptEdge.objects.all() if {e.source_id, e.target_id} == {a.pk, b.pk}]

    def test_direction_is_preserved_as_supplied_by_caller(self):
        physics = Concept.objects.create(name="Physics", slug="physics")
        qm = Concept.objects.create(name="Quantum Mechanics", slug="qm")
        # The caller (driven by the LLM's bucket) supplies the orientation; the edge is stored
        # verbatim (qm -> physics here) with no structural re-orientation.
        services._upsert_edge(qm, physics, "has_subfield", 1.0)
        pair = self._pair_edges(physics, qm)
        assert len(pair) == 1
        assert pair[0].source_id == qm.pk
        assert pair[0].target_id == physics.pk

    def test_first_assertion_of_a_relation_fixes_direction(self):
        physics = Concept.objects.create(name="Physics", slug="physics")
        qm = Concept.objects.create(name="Quantum Mechanics", slug="qm")
        services._upsert_edge(qm, physics, "has_subfield", 0.9)  # qm -> physics
        services._upsert_edge(physics, qm, "has_subfield", 0.9)  # reversed assertion
        pair = self._pair_edges(physics, qm)
        assert len(pair) == 1
        assert pair[0].source_id == qm.pk  # original orientation kept, not flipped
        assert pair[0].target_id == physics.pk
        assert pair[0].times_seen == 2

    def test_only_one_edge_per_pair_most_specific_relation_wins(self):
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        services._upsert_edge(a, b, "prerequisite_for", 0.5)
        services._upsert_edge(b, a, "has_subfield", 0.9)  # different relation AND direction
        pair = self._pair_edges(a, b)
        assert len(pair) == 1
        assert pair[0].relation == "has_subfield"  # outranks prerequisite_for

    def test_evidence_merges_across_collapsed_edges(self):
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        services._upsert_edge(a, b, "has_subfield", 0.6)
        services._upsert_edge(a, b, "has_subfield", 0.6)
        pair = self._pair_edges(a, b)
        assert len(pair) == 1
        assert pair[0].times_seen == 2
        assert pair[0].weight == pytest.approx(0.6)

    def test_prerequisite_direction_preserved(self):
        calc = Concept.objects.create(name="Calculus", slug="calc")
        phys = Concept.objects.create(name="Physics", slug="physics")
        # calculus is a prerequisite for physics: foundation -> dependent, as the caller orients.
        services._upsert_edge(calc, phys, "prerequisite_for", 0.9)
        pair = self._pair_edges(phys, calc)
        assert len(pair) == 1
        assert pair[0].source_id == calc.pk
        assert pair[0].target_id == phys.pk

    def test_normalize_edges_repairs_existing_data_and_is_idempotent(self):
        physics = Concept.objects.create(name="Physics", slug="physics")
        qm = Concept.objects.create(name="QM", slug="qm")
        thermo = Concept.objects.create(name="Thermo", slug="thermo")
        ConceptEdge.objects.create(
            source=thermo, target=physics, relation="has_subfield", weight=0.9
        )
        # A contradictory bidirectional pair plus a redundant prerequisite_for between physics & qm.
        ConceptEdge.objects.create(source=physics, target=qm, relation="has_subfield", weight=1.0)
        ConceptEdge.objects.create(source=qm, target=physics, relation="has_subfield", weight=0.95)
        ConceptEdge.objects.create(
            source=physics, target=qm, relation="prerequisite_for", weight=0.5
        )

        removed = services.normalize_edges()
        assert removed == 2  # three edges on the pair -> one survivor
        pair = self._pair_edges(physics, qm)
        assert len(pair) == 1
        assert pair[0].relation == "has_subfield"  # outranks the redundant prerequisite_for
        # Collapsed onto the pair; direction is the first surviving has_subfield edge's.
        assert {pair[0].source_id, pair[0].target_id} == {physics.pk, qm.pk}
        # thermo -> physics (its own pair) is untouched.
        assert ConceptEdge.objects.filter(source=thermo, target=physics).exists()
        # Running again changes nothing.
        assert services.normalize_edges() == 0


@pytest.mark.django_db
class TestDegreeCapAndPrune:
    def _hub_with_spokes(self, n, *, spoke_extra_edge=True):
        """A hub linked to ``n`` spokes; each spoke optionally also links to its OWN private
        anchor so it is not a degree-1 leaf (lets the cap evict the hub-spoke edge without
        orphaning the spoke). Distinct anchors avoid an order-dependent shared-anchor race."""
        hub = Concept.objects.create(name="Hub", slug="hub")
        spokes = []
        for i in range(n):
            s = Concept.objects.create(name=f"S{i}", slug=f"s{i}")
            # Descending weight so the cap has a deterministic order to evict by.
            ConceptEdge.objects.create(
                source=hub, target=s, relation="has_subfield", weight=1.0 - i * 0.01
            )
            if spoke_extra_edge:
                anchor = Concept.objects.create(name=f"A{i}", slug=f"a{i}")
                ConceptEdge.objects.create(
                    source=s, target=anchor, relation="has_subfield", weight=0.9
                )
            spokes.append(s)
        return hub, None, spokes

    def _degree(self, c):
        from django.db.models import Q

        return ConceptEdge.objects.filter(Q(source=c) | Q(target=c)).count()

    def test_prune_caps_node_degree(self):
        hub, _anchor, _spokes = self._hub_with_spokes(30)
        removed = services.prune_edges(max_degree_cap=10, min_weight=0.0)
        assert removed == 20
        assert self._degree(hub) == 10
        # The strongest (lowest-index) spokes are the ones kept.
        kept = set(ConceptEdge.objects.filter(source=hub).values_list("target__slug", flat=True))
        assert "s0" in kept and "s9" in kept and "s10" not in kept

    def test_prune_never_orphans_a_leaf(self):
        # Spokes have no other edge, so capping the hub would orphan them: protection keeps them.
        hub, _anchor, _spokes = self._hub_with_spokes(30, spoke_extra_edge=False)
        services.prune_edges(max_degree_cap=10, min_weight=0.0)
        assert self._degree(hub) == 30  # cannot evict without orphaning a degree-1 spoke

    def test_prune_drops_below_weight_floor_but_keeps_best(self):
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        c = Concept.objects.create(name="C", slug="c")
        d = Concept.objects.create(name="D", slug="d")
        # a-b (0.55) is below the floor but is the single strongest link of both A and B.
        ConceptEdge.objects.create(source=a, target=b, relation="has_subfield", weight=0.55)
        # a-c (0.40) is below the floor and is neither A's best (a-b) nor C's best (c-d).
        ConceptEdge.objects.create(source=a, target=c, relation="has_subfield", weight=0.40)
        ConceptEdge.objects.create(source=c, target=d, relation="has_subfield", weight=0.90)
        removed = services.prune_edges(max_degree_cap=100, min_weight=0.6)
        # Only a-c is dropped; a-b survives as a best-link, c-d is above the floor.
        assert removed == 1
        assert ConceptEdge.objects.filter(source=a, target=b).exists()
        assert not ConceptEdge.objects.filter(source=a, target=c).exists()
        assert ConceptEdge.objects.filter(source=c, target=d).exists()

    def test_prune_is_idempotent(self):
        self._hub_with_spokes(30)
        services.prune_edges(max_degree_cap=10, min_weight=0.0)
        assert services.prune_edges(max_degree_cap=10, min_weight=0.0) == 0


@pytest.mark.django_db
class TestRerankAndPrune:
    def _hub(self, n):
        """A hub with ``n`` spokes, each also linked to its own anchor (so it is not a
        degree-1 leaf and can be pruned without orphaning)."""
        hub = Concept.objects.create(name="Physics", slug="physics")
        for i in range(n):
            s = Concept.objects.create(name=f"S{i}", slug=f"s{i}")
            anchor = Concept.objects.create(name=f"A{i}", slug=f"a{i}")
            ConceptEdge.objects.create(source=hub, target=s, relation="has_subfield", weight=0.9)
            ConceptEdge.objects.create(source=s, target=anchor, relation="has_subfield", weight=0.9)
        return hub

    def _hub_degree(self, hub):
        return ConceptEdge.objects.filter(Q(source=hub) | Q(target=hub)).count()

    def test_noop_when_at_or_below_trigger(self):
        hub = self._hub(30)  # exactly 30 edges -> not MORE than 30
        with patch.object(services, "rerank_neighbors") as rr:
            removed = services.rerank_and_prune(hub.pk, trigger=30, target=15)
        assert removed == 0
        rr.assert_not_called()  # guard short-circuits before any LLM call

    def test_keeps_llm_chosen_edges_and_prunes_to_target(self):
        hub = self._hub(40)
        # LLM keeps S0..S14 (the first 15 spokes), by name.
        keep = [f"S{i}" for i in range(15)]
        with patch.object(services, "rerank_neighbors", return_value=keep):
            removed = services.rerank_and_prune(hub.pk, trigger=30, target=15)
        assert self._hub_degree(hub) == 15
        assert removed == 25
        kept = set(ConceptEdge.objects.filter(source=hub).values_list("target__slug", flat=True))
        assert kept == {f"s{i}" for i in range(15)}

    def test_falls_back_to_structural_rank_on_llm_failure(self):
        hub = Concept.objects.create(name="Physics", slug="physics")
        for i in range(40):
            s = Concept.objects.create(name=f"S{i}", slug=f"s{i}")
            anchor = Concept.objects.create(name=f"A{i}", slug=f"a{i}")
            # Descending weight so structural ranking has a deterministic order.
            ConceptEdge.objects.create(
                source=hub, target=s, relation="has_subfield", weight=1.0 - i * 0.01
            )
            ConceptEdge.objects.create(source=s, target=anchor, relation="has_subfield", weight=0.9)
        with patch.object(services, "rerank_neighbors", return_value=[]):  # LLM gave nothing
            services.rerank_and_prune(hub.pk, trigger=30, target=15)
        assert self._hub_degree(hub) == 15
        kept = set(ConceptEdge.objects.filter(source=hub).values_list("target__slug", flat=True))
        assert kept == {f"s{i}" for i in range(15)}  # the 15 strongest survived

    def test_does_not_orphan_a_leaf(self):
        # Spokes have no anchor: pruning any would orphan it, so all are kept despite the trigger.
        hub = Concept.objects.create(name="Physics", slug="physics")
        for i in range(40):
            s = Concept.objects.create(name=f"S{i}", slug=f"s{i}")
            ConceptEdge.objects.create(source=hub, target=s, relation="has_subfield", weight=0.9)
        with patch.object(services, "rerank_neighbors", return_value=[f"S{i}" for i in range(15)]):
            removed = services.rerank_and_prune(hub.pk, trigger=30, target=15)
        assert removed == 0
        assert self._hub_degree(hub) == 40

    def test_nodes_over_trigger_finds_concept_and_neighbors(self):
        hub = self._hub(35)  # hub has 35 edges; spokes/anchors have 2 and 1
        spoke = Concept.objects.get(slug="s0")
        over = services.nodes_over_rerank_trigger(hub.pk, trigger=30)
        assert hub.pk in over
        assert spoke.pk not in over

    def test_all_over_trigger_nodes_spans_whole_graph(self):
        big = self._hub(35)  # 35 edges -> over a trigger of 30
        small = Concept.objects.create(name="Small", slug="small")
        other = Concept.objects.create(name="Other", slug="other")
        ConceptEdge.objects.create(source=small, target=other, relation="has_subfield", weight=0.9)
        over = services.all_over_trigger_nodes(trigger=30)
        assert big.pk in over
        assert small.pk not in over and other.pk not in over


@pytest.mark.django_db
class TestBuildSubgraph:
    def test_bfs_respects_hops(self):
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        c = Concept.objects.create(name="C", slug="c")
        ConceptEdge.objects.create(source=a, target=b, relation="has_subfield", weight=0.5)
        ConceptEdge.objects.create(source=b, target=c, relation="has_subfield", weight=0.5)

        one_hop = services.build_subgraph(a, hops=1)
        node_slugs = {n.slug for n in one_hop["nodes"]}
        assert node_slugs == {"a", "b"}

        two_hop = services.build_subgraph(a, hops=2)
        node_slugs = {n.slug for n in two_hop["nodes"]}
        assert node_slugs == {"a", "b", "c"}


@pytest.mark.django_db
class TestStructureReach:
    def test_counts_recursive_subfields_and_prerequisites(self):
        # A -has_subfield-> B -prerequisite_for-> C. A reaches both B and C; B reaches C; C none.
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        c = Concept.objects.create(name="C", slug="c")
        ConceptEdge.objects.create(source=a, target=b, relation="has_subfield", weight=0.9)
        ConceptEdge.objects.create(source=b, target=c, relation="prerequisite_for", weight=0.9)
        reach = services.structure_reach_for([a.pk, b.pk, c.pk])
        assert reach[str(a.pk)] == 2
        assert reach[str(b.pk)] == 1
        assert reach[str(c.pk)] == 0

    def test_counts_distinct_nodes_across_diamond_paths(self):
        # A -> B -> D and A -> C -> D: D is reachable two ways but counts once. A reaches B, C, D.
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        c = Concept.objects.create(name="C", slug="c")
        d = Concept.objects.create(name="D", slug="d")
        ConceptEdge.objects.create(source=a, target=b, relation="has_subfield", weight=0.9)
        ConceptEdge.objects.create(source=a, target=c, relation="has_subfield", weight=0.9)
        ConceptEdge.objects.create(source=b, target=d, relation="has_subfield", weight=0.9)
        ConceptEdge.objects.create(source=c, target=d, relation="has_subfield", weight=0.9)
        assert services.structure_reach_for([a.pk])[str(a.pk)] == 3

    def test_is_cycle_safe(self):
        # A -> B -> A: reach must terminate and not count the start node itself.
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        ConceptEdge.objects.create(source=a, target=b, relation="has_subfield", weight=0.9)
        ConceptEdge.objects.create(source=b, target=a, relation="has_subfield", weight=0.9)
        reach = services.structure_reach_for([a.pk, b.pk])
        assert reach[str(a.pk)] == 1
        assert reach[str(b.pk)] == 1

    def test_build_subgraph_attaches_reach_to_nodes(self):
        # A -> B -> C; the subgraph's A node carries reach=2 for the serializer to expose.
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        c = Concept.objects.create(name="C", slug="c")
        ConceptEdge.objects.create(source=a, target=b, relation="has_subfield", weight=0.9)
        ConceptEdge.objects.create(source=b, target=c, relation="has_subfield", weight=0.9)
        nodes = {n.slug: n for n in services.build_subgraph(a, hops=2)["nodes"]}
        assert nodes["a"].reach == 2
        assert nodes["b"].reach == 1
        assert nodes["c"].reach == 0


@pytest.mark.django_db
class TestReduceTransitiveEdges:
    """Transitive reduction: drop A -R-> C when a longer same-relation path A -> ... -> C exists."""

    def _nodes(self, *names):
        return {n: Concept.objects.create(name=n, slug=n.lower()) for n in names}

    def _edge(self, s, t, relation="has_subfield", weight=0.9):
        return ConceptEdge.objects.create(source=s, target=t, relation=relation, weight=weight)

    def _pairs(self, relation=None):
        qs = ConceptEdge.objects.all()
        if relation:
            qs = qs.filter(relation=relation)
        return {(e.source.name, e.target.name) for e in qs.select_related("source", "target")}

    def test_drops_the_redundant_chain_edge(self):
        # A->B, B->C, A->C  ==>  A->B, B->C (the direct A->C is implied by A->B->C)
        n = self._nodes("A", "B", "C")
        self._edge(n["A"], n["B"])
        self._edge(n["B"], n["C"])
        self._edge(n["A"], n["C"])
        removed = services.reduce_transitive_edges()
        assert removed == 1
        assert self._pairs() == {("A", "B"), ("B", "C")}

    def test_drops_only_the_diamond_long_edge(self):
        # A->B, A->C, B->D, C->D, A->D  ==>  only A->D (implied by A->B->D / A->C->D) is dropped.
        n = self._nodes("A", "B", "C", "D")
        self._edge(n["A"], n["B"])
        self._edge(n["A"], n["C"])
        self._edge(n["B"], n["D"])
        self._edge(n["C"], n["D"])
        self._edge(n["A"], n["D"])
        removed = services.reduce_transitive_edges()
        assert removed == 1
        assert self._pairs() == {("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")}

    def test_reduces_per_relation_only(self):
        # The A->C edge is prerequisite_for; the path A->B->C is has_subfield. A cross-relation
        # path does NOT justify dropping the edge - reduction runs per relation.
        n = self._nodes("A", "B", "C")
        self._edge(n["A"], n["B"], relation="has_subfield")
        self._edge(n["B"], n["C"], relation="has_subfield")
        self._edge(n["A"], n["C"], relation="prerequisite_for")
        assert services.reduce_transitive_edges() == 0
        assert ("A", "C") in self._pairs(relation="prerequisite_for")

    def test_reduces_prerequisite_for_chains(self):
        # prerequisite_for is transitive too.
        n = self._nodes("A", "B", "C")
        self._edge(n["A"], n["B"], relation="prerequisite_for")
        self._edge(n["B"], n["C"], relation="prerequisite_for")
        self._edge(n["A"], n["C"], relation="prerequisite_for")
        assert services.reduce_transitive_edges() == 1
        assert self._pairs() == {("A", "B"), ("B", "C")}

    def test_skips_edges_on_a_cycle(self):
        # A->B->C->A is a cycle: reduction is undefined on a cycle, so every edge is left intact
        # (a stray cyclic claim never strips the whole loop).
        n = self._nodes("A", "B", "C")
        self._edge(n["A"], n["B"])
        self._edge(n["B"], n["C"])
        self._edge(n["C"], n["A"])
        assert services.reduce_transitive_edges() == 0
        assert len(self._pairs()) == 3

    def test_is_idempotent(self):
        n = self._nodes("A", "B", "C")
        self._edge(n["A"], n["B"])
        self._edge(n["B"], n["C"])
        self._edge(n["A"], n["C"])
        assert services.reduce_transitive_edges() == 1
        assert services.reduce_transitive_edges() == 0  # already reduced


class TestExpansionCancel:
    def test_cancelled_when_epoch_is_stale(self):
        with patch.object(services, "current_cancel_epoch", return_value=3):
            assert services.expansion_cancelled(2) is True
            assert services.expansion_cancelled(3) is False  # same epoch is current
            assert services.expansion_cancelled(4) is False  # newer than current

    def test_none_epoch_is_never_cancelled(self):
        # Tasks enqueued without an epoch (e.g. legacy/hand-built) are never dropped.
        with patch.object(services, "current_cancel_epoch", return_value=99):
            assert services.expansion_cancelled(None) is False

    def test_epoch_defaults_to_zero_without_redis(self):
        # No Redis client -> no cancellation control plane -> epoch 0, nothing cancelled.
        with patch.object(services, "_broker_redis", return_value=None):
            assert services.current_cancel_epoch() == 0
            assert services.expansion_cancelled(0) is False

    def test_clear_bumps_epoch_and_purges(self):
        fake_redis = type("R", (), {"incr": lambda self, key: 4})()
        fake_app = type("A", (), {"control": type("C", (), {"purge": lambda self: 9})()})()
        with (
            patch.object(services, "_broker_redis", return_value=fake_redis),
            patch("core.celery.app", fake_app),
        ):
            result = services.clear_expansion_queue()
        assert result == {"purged": 9, "epoch": 4}

    def test_clear_degrades_when_redis_down(self):
        # Redis unavailable: clear still returns a well-formed result (epoch 0) and does not raise.
        fake_app = type("A", (), {"control": type("C", (), {"purge": lambda self: 0})()})()
        with (
            patch.object(services, "_broker_redis", return_value=None),
            patch("core.celery.app", fake_app),
        ):
            result = services.clear_expansion_queue()
        assert result == {"purged": 0, "epoch": 0}


@pytest.mark.django_db
class TestTopConnectedConceptIds:
    def test_returns_densest_first(self):
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        c = Concept.objects.create(name="C", slug="c")
        # B is the hub (2 edges), A has 1, C has 1.
        ConceptEdge.objects.create(source=a, target=b, relation="has_subfield", weight=0.5)
        ConceptEdge.objects.create(source=b, target=c, relation="has_subfield", weight=0.5)
        ids = services.top_connected_concept_ids(limit=2)
        assert ids[0] == str(b.pk)  # densest hub first
        assert len(ids) == 2

    def test_limit_caps_results(self):
        for i in range(4):
            Concept.objects.create(name=f"N{i}", slug=f"n{i}")
        assert len(services.top_connected_concept_ids(limit=3)) == 3


@pytest.mark.django_db
class TestTopReachConceptIds:
    def test_ranks_by_recursive_reach_not_degree(self):
        # A -has_subfield-> B -has_subfield-> C: reach A=2, B=1, C=0. B is the densest by degree,
        # but A anchors the most structure, so reach ranking puts A first (degree ranking would
        # put B first).
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        c = Concept.objects.create(name="C", slug="c")
        ConceptEdge.objects.create(source=a, target=b, relation="has_subfield", weight=0.5)
        ConceptEdge.objects.create(source=b, target=c, relation="has_subfield", weight=0.5)
        assert services.top_reach_concept_ids(limit=3) == [str(a.pk), str(b.pk), str(c.pk)]
        # Sanity: degree ranking would lead with B, so the two orderings genuinely differ.
        assert services.top_connected_concept_ids(limit=1) == [str(b.pk)]

    def test_breaks_ties_by_degree_then_name(self):
        # Among equal-reach leaves the higher-degree one ranks first. B and C are both childless
        # (zero outgoing reach); B has an extra INCOMING edge so its degree is higher.
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        c = Concept.objects.create(name="C", slug="c")
        e = Concept.objects.create(name="E", slug="e")
        ConceptEdge.objects.create(source=a, target=b, relation="has_subfield", weight=0.5)
        ConceptEdge.objects.create(source=a, target=c, relation="has_subfield", weight=0.5)
        ConceptEdge.objects.create(source=e, target=b, relation="has_subfield", weight=0.5)
        ids = services.top_reach_concept_ids(limit=10)
        # B and C both have zero reach; B's higher degree ranks it ahead of C.
        assert ids.index(str(b.pk)) < ids.index(str(c.pk))

    def test_limit_caps_results(self):
        for i in range(4):
            Concept.objects.create(name=f"N{i}", slug=f"n{i}")
        assert len(services.top_reach_concept_ids(limit=2)) == 2

    def test_empty_graph_returns_empty(self):
        assert services.top_reach_concept_ids(limit=5) == []


@pytest.mark.django_db
class TestUnexpandedNeighborIds:
    def test_only_unexpanded_neighbors_both_directions(self):
        hub = Concept.objects.create(name="Hub", slug="hub", times_expanded=1)
        done = Concept.objects.create(name="Done", slug="done", times_expanded=1)
        fresh_out = Concept.objects.create(name="Out", slug="out")
        fresh_in = Concept.objects.create(name="In", slug="in")
        ConceptEdge.objects.create(source=hub, target=done, relation="has_subfield", weight=0.5)
        ConceptEdge.objects.create(
            source=hub, target=fresh_out, relation="has_subfield", weight=0.5
        )
        ConceptEdge.objects.create(source=fresh_in, target=hub, relation="has_subfield", weight=0.5)
        ids = set(services.unexpanded_neighbor_ids(str(hub.pk)))
        # The expanded neighbor is excluded; both unexpanded neighbors (in + out) are included.
        assert ids == {str(fresh_out.pk), str(fresh_in.pk)}


@pytest.mark.django_db
class TestAllNeighborIds:
    def test_includes_expanded_and_unexpanded_both_directions(self):
        # Unlike unexpanded_neighbor_ids, this returns EVERY neighbor regardless of expansion
        # state so a deeper crawl can traverse THROUGH an already-expanded ring.
        hub = Concept.objects.create(name="Hub", slug="hub", times_expanded=1)
        done = Concept.objects.create(name="Done", slug="done", times_expanded=1)
        fresh_out = Concept.objects.create(name="Out", slug="out")
        fresh_in = Concept.objects.create(name="In", slug="in")
        ConceptEdge.objects.create(source=hub, target=done, relation="has_subfield", weight=0.5)
        ConceptEdge.objects.create(
            source=hub, target=fresh_out, relation="has_subfield", weight=0.5
        )
        ConceptEdge.objects.create(source=fresh_in, target=hub, relation="has_subfield", weight=0.5)
        ids = set(services.all_neighbor_ids(str(hub.pk)))
        # All three neighbors - the expanded one included - in both directions.
        assert ids == {str(done.pk), str(fresh_out.pk), str(fresh_in.pk)}

    def test_deduplicates_multi_edge_neighbor(self):
        # A neighbor linked by several edges appears once.
        hub = Concept.objects.create(name="Hub", slug="hub", times_expanded=1)
        nb = Concept.objects.create(name="NB", slug="nb")
        ConceptEdge.objects.create(source=hub, target=nb, relation="has_subfield", weight=0.9)
        ConceptEdge.objects.create(source=nb, target=hub, relation="has_subfield", weight=0.5)
        assert services.all_neighbor_ids(str(hub.pk)) == [str(nb.pk)]
