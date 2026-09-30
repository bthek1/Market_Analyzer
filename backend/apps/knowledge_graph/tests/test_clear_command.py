from unittest.mock import patch

import pytest
from django.core.management import call_command

from apps.knowledge_graph.models import Concept, ConceptEdge

CMD = "clear_knowledge_graph"
MODULE = f"apps.knowledge_graph.management.commands.{CMD}"


def _seed():
    a = Concept.objects.create(name="A", slug="a")
    b = Concept.objects.create(name="B", slug="b")
    ConceptEdge.objects.create(source=a, target=b, relation="has_subfield", weight=0.5)
    return a, b


@pytest.mark.django_db
class TestClearKnowledgeGraph:
    def test_noinput_deletes_everything(self):
        _seed()
        call_command(CMD, "--noinput")
        assert Concept.objects.count() == 0
        assert ConceptEdge.objects.count() == 0

    def test_confirm_yes_deletes(self):
        _seed()
        with patch(f"{MODULE}.Confirm.ask", return_value=True) as ask:
            call_command(CMD)
        ask.assert_called_once()
        assert Concept.objects.count() == 0
        assert ConceptEdge.objects.count() == 0

    def test_confirm_no_aborts(self):
        _seed()
        with patch(f"{MODULE}.Confirm.ask", return_value=False):
            call_command(CMD)
        assert Concept.objects.count() == 2
        assert ConceptEdge.objects.count() == 1

    def test_empty_graph_does_not_prompt(self):
        with patch(f"{MODULE}.Confirm.ask") as ask:
            call_command(CMD)
        ask.assert_not_called()

    def test_noinput_on_empty_graph_is_noop(self):
        call_command(CMD, "--noinput")
        assert Concept.objects.count() == 0
