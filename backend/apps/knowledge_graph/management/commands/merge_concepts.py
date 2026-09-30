from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from apps.knowledge_graph import services
from apps.knowledge_graph.models import Concept, ConceptEdge

console = Console()


def _resolve(identifier: str) -> Concept:
    """Find a concept by exact slug or exact name (slug wins). Raises if 0 or >1 match."""
    matches = list(Concept.objects.filter(Q(slug=identifier) | Q(name=identifier)))
    if not matches:
        raise CommandError(f'No concept matches "{identifier}".')
    if len(matches) > 1:
        slugs = ", ".join(c.slug for c in matches)
        raise CommandError(f'"{identifier}" is ambiguous (matches: {slugs}); use a slug.')
    return matches[0]


class Command(BaseCommand):
    help = "Fold duplicate concepts into a canonical one (re-point edges + record aliases)."

    def add_arguments(self, parser):
        parser.add_argument("canonical", help="Slug or exact name of the concept to keep.")
        parser.add_argument(
            "duplicates", nargs="+", help="Slugs or exact names of the concepts to fold in."
        )
        parser.add_argument(
            "--noinput",
            "--no-input",
            action="store_true",
            dest="noinput",
            help="Do not prompt for confirmation.",
        )

    def handle(self, *args, **options):
        console.rule("[bold cyan]Merge Concepts[/bold cyan]")

        canonical = _resolve(options["canonical"])
        duplicates = [_resolve(d) for d in options["duplicates"]]
        duplicates = [d for d in duplicates if d.pk != canonical.pk]
        if not duplicates:
            console.print("[yellow]Nothing to merge (no distinct duplicates).[/yellow]")
            return

        table = Table(show_header=True, header_style="bold")
        table.add_column("Role", style="cyan")
        table.add_column("Concept")
        table.add_column("Edges", justify="right")
        table.add_row("canonical", f"{canonical.name} ({canonical.slug})", str(_degree(canonical)))
        for d in duplicates:
            table.add_row("duplicate", f"{d.name} ({d.slug})", str(_degree(d)))
        console.print(table)

        if not options["noinput"] and not Confirm.ask(
            "[bold red]Fold the duplicates into the canonical concept?[/bold red]", default=False
        ):
            console.print("[yellow]Aborted.[/yellow]")
            return

        summary = services.merge_concepts(canonical, duplicates)
        console.print(
            "[green]Merged.[/green] "
            f"edges re-pointed: {summary['edges_repointed']} "
            f"(collapsed: {summary['edges_collapsed']}), "
            f"aliases added: {summary['aliases_added']}, "
            f"nodes deleted: {summary['nodes_deleted']}."
        )


def _degree(concept: Concept) -> int:
    return ConceptEdge.objects.filter(Q(source=concept) | Q(target=concept)).count()
