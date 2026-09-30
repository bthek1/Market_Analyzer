from django.core.management.base import BaseCommand

from apps.companies.services import (
    bootstrap_next_batch,
    discover_and_create_stubs,
    sync_all_for_symbol,
    sync_company_profile,
)

"""
python manage.py discover_new_symbols
"""


class Command(BaseCommand):
    help = "Populate and sync company data via yfinance."

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="action")

        sub.add_parser(
            "discover",
            help="Scrape S&P 500 + NASDAQ-100 and create un-bootstrapped stubs.",
        )

        bootstrap_parser = sub.add_parser(
            "bootstrap",
            help="Process the next batch of un-bootstrapped companies (full ingest).",
        )
        bootstrap_parser.add_argument(
            "--batch-size",
            type=int,
            default=5,
            metavar="N",
            help="Number of symbols to ingest per run (default: 5).",
        )

        sync_parser = sub.add_parser(
            "sync",
            help="Refresh profiles for companies already in the DB.",
        )
        sync_parser.add_argument(
            "--symbol",
            type=str,
            default=None,
            help="Sync a single symbol.",
        )

        ingest_parser = sub.add_parser(
            "ingest",
            help="Full ingest for one symbol: profile, prices, snapshot, financials, dividends.",
        )
        ingest_parser.add_argument("symbol", type=str, help="Symbol to ingest.")

    def handle(self, *args, **options):
        action = options.get("action") or "discover"

        if action == "discover":
            self.stdout.write("Scraping S&P 500 + NASDAQ-100 for new symbols...")
            created = discover_and_create_stubs()
            self.stdout.write(self.style.SUCCESS(f"Done. {created} new symbol stubs created."))

        elif action == "bootstrap":
            batch_size = options.get("batch_size", 5)
            self.stdout.write(f"Bootstrapping next {batch_size} un-bootstrapped companies...")
            result = bootstrap_next_batch(batch_size=batch_size)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Done. attempted={result['attempted']} "
                    f"ok={result['ok']} failed={result['failed']}"
                )
            )

        elif action == "sync":
            symbol = options.get("symbol")
            if symbol:
                symbol = symbol.upper()
                self.stdout.write(f"Syncing {symbol} via yfinance...")
                company = sync_company_profile(symbol)
                if company:
                    self.stdout.write(self.style.SUCCESS(f"Synced: {company}"))
                else:
                    self.stdout.write(self.style.WARNING(f"No data found for {symbol}."))
            else:
                self.stdout.write(
                    self.style.ERROR(
                        "Please provide --symbol. "
                        "To refresh all profiles, trigger dispatch_profile_sync via the task API."
                    )
                )

        elif action == "ingest":
            symbol = options["symbol"].upper()
            self.stdout.write(f"Full ingest for {symbol}...")
            result = sync_all_for_symbol(symbol)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Done. profile={result['profile']} prices={result['prices']} "
                    f"snapshot={result['snapshot']} financials={result['financials']} "
                    f"dividends={result['dividends']}"
                )
            )
