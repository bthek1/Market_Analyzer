import uuid

import pytest
from django.db import IntegrityError

from apps.knowledge_graph.models import Concept, ConceptEdge, Relation


@pytest.mark.django_db
class TestConcept:
    def test_create_assigns_uuid_pk(self):
        c = Concept.objects.create(name="Physics", slug="physics")
        assert isinstance(c.pk, uuid.UUID)
        assert c.times_expanded == 0

    def test_str(self):
        c = Concept.objects.create(name="Physics", slug="physics")
        assert str(c) == "Physics"


class TestRelation:
    def test_only_two_relation_types(self):
        # The graph has exactly two structural relations; `uses`, `applies_to` and the symmetric
        # `related_to` were all removed. Guard against accidental re-introduction.
        assert [r.value for r in Relation] == [
            "has_subfield",
            "prerequisite_for",
        ]
        assert "uses" not in Relation.values
        assert "applies_to" not in Relation.values
        assert "related_to" not in Relation.values


@pytest.mark.django_db
class TestConceptEdge:
    def test_unique_edge_constraint(self):
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        ConceptEdge.objects.create(source=a, target=b, relation=Relation.HAS_SUBFIELD, weight=0.5)
        with pytest.raises(IntegrityError):
            ConceptEdge.objects.create(
                source=a, target=b, relation=Relation.HAS_SUBFIELD, weight=0.9
            )

    def test_same_pair_different_relation_allowed(self):
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        ConceptEdge.objects.create(source=a, target=b, relation=Relation.HAS_SUBFIELD, weight=0.5)
        ConceptEdge.objects.create(
            source=a, target=b, relation=Relation.PREREQUISITE_FOR, weight=0.5
        )
        assert ConceptEdge.objects.count() == 2
