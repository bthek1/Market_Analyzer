"""Data-migration tests.

``TestReduceRelationTypes`` (0002): rolls the schema back to 0001, seeds edges that use the
now-removed ``uses`` / ``applies_to`` relations, then migrates forward and asserts they
collapse into ``related_to`` - merging (not duplicating) when a ``related_to`` edge already
exists between the same pair.

``TestSubfieldToHasSubfield`` (0003): seeds ``subfield_of`` (child -> parent) edges at 0002,
migrates forward and asserts they flip to ``has_subfield`` (parent -> child) - swapping
source/target, merging on collision with a pre-existing ``has_subfield`` edge, and reversing
cleanly.

``TestRemoveRelatedTo`` (0008): seeds a ``related_to`` edge alongside structural edges at 0007,
migrates forward and asserts the ``related_to`` edges are DELETED while the structural
(``has_subfield`` / ``prerequisite_for``) edges and every concept survive.
"""

import uuid

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

APP = "knowledge_graph"
BEFORE = "0001_initial"
AFTER = "0002_reduce_relation_types"

# 0003 flips the hierarchy relation; it sits directly on top of 0002.
HAS_SUBFIELD_BEFORE = "0002_reduce_relation_types"
HAS_SUBFIELD_AFTER = "0003_subfield_of_to_has_subfield"

# 0004 renames the ordering relation prerequisite_of -> prerequisite_for (no direction change).
PREREQ_BEFORE = "0003_subfield_of_to_has_subfield"
PREREQ_AFTER = "0004_prerequisite_of_to_for"

# 0008 removes the related_to relation entirely (its edges are deleted).
REMOVE_RELATED_BEFORE = "0007_concept_negative_description"
REMOVE_RELATED_AFTER = "0008_remove_related_to"


def _migrate(target):
    executor = MigrationExecutor(connection)
    executor.migrate([(APP, target)])
    executor.loader.build_graph()
    return executor


@pytest.mark.django_db(transaction=True)
class TestReduceRelationTypes:
    def test_collapses_and_merges_legacy_relations(self):
        # Roll back to the pre-reduction schema.
        old_apps = _migrate(BEFORE).loader.project_state((APP, BEFORE)).apps
        Concept = old_apps.get_model(APP, "Concept")
        ConceptEdge = old_apps.get_model(APP, "ConceptEdge")

        a = Concept.objects.create(id=uuid.uuid4(), name="A", slug="a")
        b = Concept.objects.create(id=uuid.uuid4(), name="B", slug="b")
        c = Concept.objects.create(id=uuid.uuid4(), name="C", slug="c")

        # Plain remap: no existing related_to edge for this pair.
        ConceptEdge.objects.create(
            id=uuid.uuid4(), source=a, target=b, relation="uses", weight=0.4, times_seen=2
        )
        # Collision: an applies_to edge that must MERGE into the existing related_to edge.
        ConceptEdge.objects.create(
            id=uuid.uuid4(), source=a, target=c, relation="related_to", weight=0.5, times_seen=1
        )
        ConceptEdge.objects.create(
            id=uuid.uuid4(), source=a, target=c, relation="applies_to", weight=0.8, times_seen=3
        )

        try:
            # Migrate forward across the data migration.
            new_apps = _migrate(AFTER).loader.project_state((APP, AFTER)).apps
            NewEdge = new_apps.get_model(APP, "ConceptEdge")  # noqa: N806

            assert not NewEdge.objects.filter(relation__in=["uses", "applies_to"]).exists()

            # a->b: remapped in place.
            ab = NewEdge.objects.get(source_id=a.id, target_id=b.id)
            assert ab.relation == "related_to"
            assert ab.weight == pytest.approx(0.4)
            assert ab.times_seen == 2

            # a->c: single merged edge (times_seen summed, stronger weight kept).
            ac = NewEdge.objects.filter(source_id=a.id, target_id=c.id)
            assert ac.count() == 1
            merged = ac.first()
            assert merged.relation == "related_to"
            assert merged.weight == pytest.approx(0.8)
            assert merged.times_seen == 4
        finally:
            # Leave the schema at HEAD for the rest of the suite.
            _migrate(AFTER)


@pytest.mark.django_db(transaction=True)
class TestSubfieldToHasSubfield:
    def _seed_at_0002(self):
        old_apps = (
            _migrate(HAS_SUBFIELD_BEFORE).loader.project_state((APP, HAS_SUBFIELD_BEFORE)).apps
        )
        return old_apps.get_model(APP, "Concept"), old_apps.get_model(APP, "ConceptEdge")

    def _edges_at_head(self):
        new_apps = _migrate(HAS_SUBFIELD_AFTER).loader.project_state((APP, HAS_SUBFIELD_AFTER)).apps
        return new_apps.get_model(APP, "ConceptEdge")

    def test_flips_child_to_parent_into_parent_to_child(self):
        Concept, ConceptEdge = self._seed_at_0002()  # noqa: N806
        child = Concept.objects.create(id=uuid.uuid4(), name="QM", slug="qm")
        parent = Concept.objects.create(id=uuid.uuid4(), name="Physics", slug="physics")
        # Old convention: child -> parent.
        ConceptEdge.objects.create(
            id=uuid.uuid4(),
            source=child,
            target=parent,
            relation="subfield_of",
            weight=0.4,
            times_seen=2,
        )
        try:
            NewEdge = self._edges_at_head()  # noqa: N806
            assert not NewEdge.objects.filter(relation="subfield_of").exists()
            edge = NewEdge.objects.get()
            # New convention: parent -> child, source/target swapped, evidence preserved.
            assert edge.relation == "has_subfield"
            assert edge.source_id == parent.id
            assert edge.target_id == child.id
            assert edge.weight == pytest.approx(0.4)
            assert edge.times_seen == 2
        finally:
            _migrate(HAS_SUBFIELD_AFTER)

    def test_merges_when_flip_collides_with_existing_has_subfield(self):
        Concept, ConceptEdge = self._seed_at_0002()  # noqa: N806
        child = Concept.objects.create(id=uuid.uuid4(), name="QM", slug="qm")
        parent = Concept.objects.create(id=uuid.uuid4(), name="Physics", slug="physics")
        # A has_subfield parent->child edge already present (choices are not DB-enforced),
        # plus the legacy child->parent subfield_of edge that flips onto the same pair.
        ConceptEdge.objects.create(
            id=uuid.uuid4(),
            source=parent,
            target=child,
            relation="has_subfield",
            weight=0.5,
            times_seen=1,
        )
        ConceptEdge.objects.create(
            id=uuid.uuid4(),
            source=child,
            target=parent,
            relation="subfield_of",
            weight=0.8,
            times_seen=3,
        )
        try:
            NewEdge = self._edges_at_head()  # noqa: N806
            edges = NewEdge.objects.all()
            assert edges.count() == 1  # merged, not duplicated
            merged = edges.get()
            assert merged.relation == "has_subfield"
            assert merged.source_id == parent.id
            assert merged.target_id == child.id
            assert merged.times_seen == 4  # 1 + 3
            # Running mean over both observations: (0.5*1 + 0.8*3) / 4.
            assert merged.weight == pytest.approx(0.725)
        finally:
            _migrate(HAS_SUBFIELD_AFTER)

    def test_reverse_restores_subfield_of_orientation(self):
        Concept, ConceptEdge = self._seed_at_0002()  # noqa: N806
        child = Concept.objects.create(id=uuid.uuid4(), name="QM", slug="qm")
        parent = Concept.objects.create(id=uuid.uuid4(), name="Physics", slug="physics")
        ConceptEdge.objects.create(
            id=uuid.uuid4(),
            source=child,
            target=parent,
            relation="subfield_of",
            weight=0.4,
            times_seen=2,
        )
        try:
            self._edges_at_head()  # forward: child->parent subfield_of => parent->child has_subfield
            # Reverse back across 0003.
            old_apps = (
                _migrate(HAS_SUBFIELD_BEFORE).loader.project_state((APP, HAS_SUBFIELD_BEFORE)).apps
            )
            OldEdge = old_apps.get_model(APP, "ConceptEdge")  # noqa: N806
            assert not OldEdge.objects.filter(relation="has_subfield").exists()
            edge = OldEdge.objects.get()
            assert edge.relation == "subfield_of"
            assert edge.source_id == child.id  # original child -> parent orientation restored
            assert edge.target_id == parent.id
        finally:
            _migrate(HAS_SUBFIELD_AFTER)


@pytest.mark.django_db(transaction=True)
class TestPrerequisiteOfToFor:
    def _seed_at_0003(self):
        old_apps = _migrate(PREREQ_BEFORE).loader.project_state((APP, PREREQ_BEFORE)).apps
        return old_apps.get_model(APP, "Concept"), old_apps.get_model(APP, "ConceptEdge")

    def test_renames_relation_without_changing_direction(self):
        Concept, ConceptEdge = self._seed_at_0003()  # noqa: N806
        calc = Concept.objects.create(id=uuid.uuid4(), name="Calculus", slug="calc")
        phys = Concept.objects.create(id=uuid.uuid4(), name="Physics", slug="physics")
        # foundation -> dependent; this orientation must survive the rename verbatim.
        ConceptEdge.objects.create(
            id=uuid.uuid4(),
            source=calc,
            target=phys,
            relation="prerequisite_of",
            weight=0.6,
            times_seen=2,
        )
        try:
            new_apps = _migrate(PREREQ_AFTER).loader.project_state((APP, PREREQ_AFTER)).apps
            NewEdge = new_apps.get_model(APP, "ConceptEdge")  # noqa: N806
            assert not NewEdge.objects.filter(relation="prerequisite_of").exists()
            edge = NewEdge.objects.get()
            assert edge.relation == "prerequisite_for"
            assert edge.source_id == calc.id  # foundation -> dependent, unchanged
            assert edge.target_id == phys.id
            assert edge.weight == pytest.approx(0.6)
            assert edge.times_seen == 2
        finally:
            _migrate(PREREQ_AFTER)

    def test_reverse_restores_prerequisite_of(self):
        Concept, ConceptEdge = self._seed_at_0003()  # noqa: N806
        calc = Concept.objects.create(id=uuid.uuid4(), name="Calculus", slug="calc")
        phys = Concept.objects.create(id=uuid.uuid4(), name="Physics", slug="physics")
        ConceptEdge.objects.create(
            id=uuid.uuid4(),
            source=calc,
            target=phys,
            relation="prerequisite_of",
            weight=0.6,
            times_seen=2,
        )
        try:
            _migrate(PREREQ_AFTER)  # forward: prerequisite_of -> prerequisite_for
            old_apps = _migrate(PREREQ_BEFORE).loader.project_state((APP, PREREQ_BEFORE)).apps
            OldEdge = old_apps.get_model(APP, "ConceptEdge")  # noqa: N806
            assert not OldEdge.objects.filter(relation="prerequisite_for").exists()
            edge = OldEdge.objects.get()
            assert edge.relation == "prerequisite_of"
            assert edge.source_id == calc.id  # direction never changed
            assert edge.target_id == phys.id
        finally:
            _migrate(PREREQ_AFTER)


@pytest.mark.django_db(transaction=True)
class TestRemoveRelatedTo:
    def _seed_at_0007(self):
        old_apps = (
            _migrate(REMOVE_RELATED_BEFORE).loader.project_state((APP, REMOVE_RELATED_BEFORE)).apps
        )
        return old_apps.get_model(APP, "Concept"), old_apps.get_model(APP, "ConceptEdge")

    def test_deletes_related_to_edges_and_keeps_structural(self):
        Concept, ConceptEdge = self._seed_at_0007()  # noqa: N806
        a = Concept.objects.create(id=uuid.uuid4(), name="A", slug="a")
        b = Concept.objects.create(id=uuid.uuid4(), name="B", slug="b")
        c = Concept.objects.create(id=uuid.uuid4(), name="C", slug="c")
        # Two structural backbone edges that must survive verbatim.
        ConceptEdge.objects.create(
            id=uuid.uuid4(), source=a, target=b, relation="has_subfield", weight=0.9, times_seen=1
        )
        ConceptEdge.objects.create(
            id=uuid.uuid4(),
            source=b,
            target=c,
            relation="prerequisite_for",
            weight=0.8,
            times_seen=1,
        )
        # A related_to edge (c is joined to the graph ONLY by it) that must be deleted.
        ConceptEdge.objects.create(
            id=uuid.uuid4(), source=a, target=c, relation="related_to", weight=0.5, times_seen=1
        )
        try:
            new_apps = (
                _migrate(REMOVE_RELATED_AFTER)
                .loader.project_state((APP, REMOVE_RELATED_AFTER))
                .apps
            )
            NewEdge = new_apps.get_model(APP, "ConceptEdge")  # noqa: N806
            NewConcept = new_apps.get_model(APP, "Concept")  # noqa: N806

            # related_to edges are gone; both structural edges are untouched.
            assert not NewEdge.objects.filter(relation="related_to").exists()
            assert {(e.source_id, e.target_id, e.relation) for e in NewEdge.objects.all()} == {
                (a.id, b.id, "has_subfield"),
                (b.id, c.id, "prerequisite_for"),
            }
            # No concept is deleted - a node orphaned by the removal simply survives isolated.
            assert NewConcept.objects.count() == 3
        finally:
            _migrate(REMOVE_RELATED_AFTER)
