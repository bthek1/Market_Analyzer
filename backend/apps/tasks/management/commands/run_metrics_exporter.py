"""Long-running Prometheus exporter for Celery task metrics.

Runs as its own systemd unit (stockmarket-metrics.service) rather than inside gunicorn,
for two reasons: consuming the Celery event stream needs a persistent broker connection
that would be duplicated by every one of the four gunicorn workers, and phase 4's
DB-derived gauges must be computed by exactly ONE process or they are multiplied by the
worker count.

The HTTP server runs on a background thread (prometheus_client.start_http_server) while
the main thread blocks on the event loop.
"""

import logging
import time

from django.core.management.base import BaseCommand
from prometheus_client import REGISTRY, start_http_server

from apps.tasks.collectors import DomainCollector
from apps.tasks.metrics import TASK_EVENTS, handle_event

logger = logging.getLogger(__name__)

# Reconnect backoff. The broker going away is routine (a Redis restart, a deploy), so
# this loops rather than exiting and leaving systemd to restart the whole process.
RECONNECT_DELAY_S = 5


class Command(BaseCommand):
    help = "Serve Prometheus metrics derived from the Celery event stream."

    def add_arguments(self, parser):
        parser.add_argument("--port", type=int, default=8010)
        # Loopback only: Alloy scrapes from this same host, and the metrics are not
        # something to publish on the LAN.
        parser.add_argument("--address", default="127.0.0.1")
        parser.add_argument(
            "--once",
            action="store_true",
            help="Start the HTTP server, drain nothing and return (smoke test).",
        )

    def handle(self, *args, **options):
        from core.celery import app as celery_app

        # Registered before the server starts, so the very first scrape already carries
        # the domain gauges. A custom collector computes on collect(), which is why this
        # process must be the only one running it - see apps/tasks/collectors.py.
        REGISTRY.register(DomainCollector())
        start_http_server(options["port"], addr=options["address"])
        self.stdout.write(
            self.style.SUCCESS(f"metrics on http://{options['address']}:{options['port']}/metrics")
        )
        if options["once"]:
            return

        state = celery_app.events.State()

        while True:
            try:
                with celery_app.connection() as connection:
                    recv = celery_app.events.Receiver(
                        connection,
                        handlers={
                            **{event: self._make_handler(state) for event in TASK_EVENTS},
                            # Heartbeats keep the worker gauge honest; the catch-all keeps
                            # `state` consistent so task names resolve.
                            "worker-heartbeat": self._make_handler(state),
                            "*": state.event,
                        },
                    )
                    self.stdout.write("consuming celery events")
                    recv.capture(limit=None, timeout=None, wakeup=True)
            except KeyboardInterrupt:
                raise
            except Exception:
                logger.exception("celery event stream dropped; reconnecting")
                time.sleep(RECONNECT_DELAY_S)

    @staticmethod
    def _make_handler(state):
        return lambda event: handle_event(state, event)
