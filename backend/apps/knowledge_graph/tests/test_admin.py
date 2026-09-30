import pytest
from django.contrib.admin.sites import AdminSite

from apps.knowledge_graph.admin import ConceptAdmin
from apps.knowledge_graph.models import Concept, ConceptEdge


@pytest.mark.django_db
class TestConceptAdmin:
    def _admin(self):
        return ConceptAdmin(Concept, AdminSite())

    def test_connections_column_is_listed(self):
        assert "connections" in self._admin().list_display

    def test_connections_counts_both_directions(self, rf):
        a = Concept.objects.create(name="A", slug="a")
        b = Concept.objects.create(name="B", slug="b")
        c = Concept.objects.create(name="C", slug="c")
        ConceptEdge.objects.create(source=a, target=b, relation="has_subfield", weight=0.5)
        ConceptEdge.objects.create(source=c, target=a, relation="has_subfield", weight=0.5)

        admin = self._admin()
        qs = admin.get_queryset(rf.get("/"))
        obj = qs.get(pk=a.pk)
        # one outgoing (a->b) + one incoming (c->a)
        assert obj._connections == 2
        assert admin.connections(obj) == 2

    def test_no_edges_is_zero(self, rf):
        a = Concept.objects.create(name="A", slug="a")
        admin = self._admin()
        obj = admin.get_queryset(rf.get("/")).get(pk=a.pk)
        assert admin.connections(obj) == 0
