from django.core.management.base import BaseCommand
from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from apps.knowledge_graph.models import Concept, ConceptEdge

console = Console()

"""
python manage.py clear_knowledge_graph
"""


class Command(BaseCommand):
    help = "Delete all concepts and edges from the knowledge graph."

    def add_arguments(self, parser):
        parser.add_argument(
            "--noinput",
            "--no-input",
            action="store_true",
            dest="noinput",
            help="Do not prompt for confirmation.",
        )

    def handle(self, *args, **options):
        console.rule("[bold cyan]Clear Knowledge Graph[/bold cyan]")

        edge_count = ConceptEdge.objects.count()
        concept_count = Concept.objects.count()

        table = Table(show_header=True, header_style="bold")
        table.add_column("Model", style="cyan")
        table.add_column("Rows", justify="right")
        table.add_row("Concept", str(concept_count))
        table.add_row("ConceptEdge", str(edge_count))
        console.print(table)

        if edge_count == 0 and concept_count == 0:
            console.print("[green]Knowledge graph is already empty.[/green]")
            return

        if not options["noinput"] and not Confirm.ask(
            "[bold red]Delete everything above?[/bold red]", default=False
        ):
            console.print("[yellow]Aborted.[/yellow]")
            return

        # Edges are removed via FK cascade, but delete explicitly for clear output.
        ConceptEdge.objects.all().delete()
        Concept.objects.all().delete()

        console.print(
            f"[green]Deleted[/green] {concept_count} concept(s) and {edge_count} edge(s)."
        )
