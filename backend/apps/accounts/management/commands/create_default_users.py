import os

from django.core.management.base import BaseCommand
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from apps.accounts.models import CustomUser

console = Console()


class Command(BaseCommand):
    help = "Creates the default superuser and staff user from environment variables."

    def handle(self, *args, **kwargs):
        console.rule("[bold cyan]Creating Default Users[/bold cyan]")

        # --- Superuser ---
        console.print("\n[bold]Superuser[/bold]")
        su_email = os.getenv("DJANGO_SUPERUSER_EMAIL")
        su_password = os.getenv("DJANGO_SUPERUSER_PASSWORD")

        if not su_email or not su_password:
            console.print(
                "  [yellow]Skipped:[/yellow] "
                "DJANGO_SUPERUSER_EMAIL and DJANGO_SUPERUSER_PASSWORD not set."
            )
        elif CustomUser.objects.filter(email=su_email).exists():
            console.print(f"  [yellow]Skipped:[/yellow] Superuser already exists: {su_email}")
        else:
            CustomUser.objects.create_superuser(email=su_email, password=su_password)
            console.print(f"  [green]Created:[/green] {su_email}")

        # --- Staff user ---
        console.print("\n[bold]Staff User[/bold]")
        staff_email = os.getenv("DJANGO_STAFF_EMAIL")
        staff_password = os.getenv("DJANGO_STAFF_PASSWORD")

        if not staff_email or not staff_password:
            console.print(
                "  [yellow]Skipped:[/yellow] DJANGO_STAFF_EMAIL and DJANGO_STAFF_PASSWORD not set."
            )
        elif CustomUser.objects.filter(email=staff_email).exists():
            console.print(f"  [yellow]Skipped:[/yellow] Staff user already exists: {staff_email}")
        else:
            user = CustomUser.objects.create_user(
                email=staff_email, password=staff_password, is_staff=True
            )
            console.print(f"  [green]Created:[/green] {user.email} (PK: {user.pk})")

        # --- Summary table ---
        table = Table(title="Default Users", show_lines=True)
        table.add_column("Role", style="bold cyan")
        table.add_column("Email")
        table.add_column("Env var")

        superuser_email = os.getenv("DJANGO_SUPERUSER_EMAIL", "[dim]not set[/dim]")
        staff_email_display = staff_email or "[dim]not set[/dim]"

        table.add_row("Superuser", superuser_email, "DJANGO_SUPERUSER_EMAIL")
        table.add_row("Staff", staff_email_display, "DJANGO_STAFF_EMAIL")

        console.print()
        console.print(table)
        console.print(Panel("[bold green]Done[/bold green]", expand=False))
