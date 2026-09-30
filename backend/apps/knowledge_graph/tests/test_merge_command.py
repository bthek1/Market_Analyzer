from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.knowledge_graph.models import Concept, ConceptAlias, ConceptEdge

CMD = "merge_concepts"
MODULE = f"apps.knowledge_graph.management.commands.{CMD}"


def _seed():
    graph = Concept.objects.create(name="graph", slug="graph")
    graphs = Concept.objects.create(name="graphs", slug="graphs")
    node = Concept.objects.create(name="node", slug="node")
    ConceptEdge.objects.create(source=graphs, target=node, relation="has_subfield", weight=0.9)
    return graph, graphs, node


@pytest.mark.django_db
class TestMergeCommand:
    def test_noinput_merges_by_slug(self):
        graph, _graphs, node = _seed()
        call_command(CMD, "graph", "graphs", "--noinput")
        assert not Concept.objects.filter(slug="graphs").exists()
        assert ConceptEdge.objects.filter(source=graph, target=node).exists()
        assert ConceptAlias.objects.filter(slug="graphs", concept=graph).exists()

    def test_resolves_by_exact_name(self):
        _seed()
        call_command(CMD, "graph", "graphs", "--noinput")
        assert not Concept.objects.filter(slug="graphs").exists()

    def test_confirm_no_aborts(self):
        _seed()
        with patch(f"{MODULE}.Confirm.ask", return_value=False):
            call_command(CMD, "graph", "graphs")
        assert Concept.objects.filter(slug="graphs").exists()  # untouched

    def test_confirm_yes_merges(self):
        _seed()
        with patch(f"{MODULE}.Confirm.ask", return_value=True) as ask:
            call_command(CMD, "graph", "graphs")
        ask.assert_called_once()
        assert not Concept.objects.filter(slug="graphs").exists()

    def test_unknown_identifier_raises(self):
        Concept.objects.create(name="graph", slug="graph")
        with pytest.raises(CommandError):
            call_command(CMD, "graph", "nonexistent", "--noinput")

    def test_merging_node_into_itself_is_noop(self):
        Concept.objects.create(name="graph", slug="graph")
        call_command(CMD, "graph", "graph", "--noinput")
        assert Concept.objects.filter(slug="graph").exists()
