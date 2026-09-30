"""
Run one live browser-agent query end to end. This is the smoke test the pytest suite
deliberately does not have: it launches a real browser and reaches the public internet.

Usage:
    python manage.py browse "who are NVIDIA's three largest competitors by revenue?"
    python manage.py browse "latest Fed rate decision" --max-steps 8 --headed
    python manage.py browse "..." --user me@example.com --provider ollama
"""

from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from rich.console import Console
from rich.panel import Panel

from apps.llm_analysis import browser, config, services

console = Console()


class Command(BaseCommand):
    help = "Run one live browser-agent query (launches a real browser)."

    def add_arguments(self, parser):
        parser.add_argument("query", help="What to search the web for.")
        parser.add_argument("--user", help="Email of the run owner (default: first user).")
        parser.add_argument("--provider", choices=("anthropic", "ollama"))
        parser.add_argument("--model", default="")
        parser.add_argument("--max-steps", type=int)
        parser.add_argument(
            "--headed",
            action="store_true",
            help="Show the browser window instead of running headless.",
        )

    def handle(self, *args, **opts):
        users = get_user_model().objects
        owner = (
            users.filter(email=opts["user"]).first()
            if opts["user"]
            else users.order_by("date_joined").first()
        )
        if owner is None:
            raise CommandError("No user to own the run. Create one, or pass --user.")

        cfg = config.get_llm_config()
        if opts["headed"]:
            cfg.browser_headless = False

        run = services.create_browser_run(
            user=owner,
            query=opts["query"],
            model=opts["model"],
            provider=opts["provider"] or cfg.browser_provider,
            max_steps=opts["max_steps"] or cfg.browser_max_steps,
            allowed_domains=browser.parse_domains(cfg.browser_allowed_domains),
        )
        console.print(f"[bold]Run[/bold] {run.id} owner={owner.email}")

        browser.acquire_slot()
        for chunk in browser.run_browser(run, model=opts["model"]):
            event = json.loads(chunk[len("data: ") :].strip())
            kind = event.get("event")
            if kind == "started":
                console.print(
                    f"provider={event['provider']} max_steps={event['max_steps']} "
                    f"domains={len(event['allowed_domains']) or 'any'}"
                )
            elif kind == "step":
                console.print(
                    f"  [cyan]{event['order']}[/cyan] {event['action']} -> {event['url']}\n"
                    f"     {event['goal']}"
                )
            elif kind == "result":
                console.print(Panel(event["output"], title="Answer"))
                console.print("Sources: " + (", ".join(event["sources"]) or "none"))
                console.print(f"Stopped because: {event['stop_reason']}")
            elif kind == "error":
                console.print(f"[red]{event['error']}[/red]")
