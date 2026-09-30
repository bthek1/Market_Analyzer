"""Guard the django-prometheus wiring (issue #2, phase 3).

Each of these protects an arrangement that is easy to break by accident and whose
breakage is either silent (metrics quietly stop being collected) or catastrophic in a
way that only shows up outside the test suite (ports bound during pytest, a postgresql
backend loaded under SQLite).
"""

import re
from pathlib import Path

import pytest
from django.conf import settings

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[3]

BEFORE = "django_prometheus.middleware.PrometheusBeforeMiddleware"
AFTER = "django_prometheus.middleware.PrometheusAfterMiddleware"
PROM_PG_ENGINE = "django_prometheus.db.backends.postgresql"


class TestMiddlewareOrdering:
    def test_before_middleware_is_first(self):
        """django-prometheus times the whole chain, so anything outside these two is not
        counted in the latency they report. A new middleware prepended above BEFORE
        silently shrinks every measurement."""
        assert settings.MIDDLEWARE[0] == BEFORE

    def test_after_middleware_is_last(self):
        assert settings.MIDDLEWARE[-1] == AFTER

    def test_request_id_middleware_still_wraps_the_app(self):
        """It must stay above everything that logs, but below the prometheus pair."""
        order = list(settings.MIDDLEWARE)
        assert order.index("core.middleware.RequestIDMiddleware") == 1

    def test_app_is_installed(self):
        assert "django_prometheus" in settings.INSTALLED_APPS


class TestTestSettingsAreIsolated:
    """The test settings must not inherit the two production-only pieces."""

    def test_no_prometheus_db_backend_under_sqlite(self):
        """The wrapper is postgresql-only, and part of this suite runs on SQLite. If it
        ever leaks into base.py the whole suite fails to connect."""
        engine = settings.DATABASES["default"]["ENGINE"]
        assert engine == "django.db.backends.sqlite3"
        assert PROM_PG_ENGINE not in engine

    def test_no_metrics_port_is_bound_during_tests(self):
        """django_prometheus binds these in AppConfig.ready(). Set in base.py, every
        pytest process would try to bind them - and `pytest -n auto` would collide."""
        assert not hasattr(settings, "PROMETHEUS_METRICS_EXPORT_PORT_RANGE")
        assert not hasattr(settings, "PROMETHEUS_METRICS_EXPORT_PORT")


class TestProdSettings:
    """Read prod.py's source rather than importing it - importing would need the full
    production env (ALLOWED_HOSTS, a real DATABASE_URL) and would bind ports."""

    @pytest.fixture
    def source(self):
        # Read the file, never import it: prod.py calls env.list("ALLOWED_HOSTS"), which
        # raises without the production environment, and importing it would also bind the
        # four metrics ports inside the test process.
        return (REPO_ROOT / "backend/core/settings/prod.py").read_text()

    def test_prod_swaps_the_db_engine(self, source):
        text = source
        assert PROM_PG_ENGINE in text

    def test_prod_exports_one_port_per_gunicorn_worker(self, source):
        """The api unit runs --workers 4 and each worker keeps its own registry, so the
        port range and the worker count have to agree - otherwise a worker's metrics are
        simply never scraped."""
        text = source
        unit = (
            REPO_ROOT / "infra/ansible/roles/services/templates/stockmarket-api.service.j2"
        ).read_text()

        workers = int(re.search(r"--workers (\d+)", unit).group(1))
        start, stop = map(
            int,
            re.search(
                r"PROMETHEUS_METRICS_EXPORT_PORT_RANGE = range\((\d+), (\d+)\)", text
            ).groups(),
        )

        assert stop - start == workers, (
            f"port range covers {stop - start} workers but gunicorn runs {workers}"
        )

    def test_port_range_is_gated_to_the_gunicorn_unit_only(self, source):
        """django_prometheus binds in AppConfig.ready(), which runs in EVERY process that
        calls django.setup() - the Celery worker, beat, the metrics exporter and each
        `manage.py` during a deploy. Ungated, whichever started first would claim 8005,
        Alloy would scrape a Celery worker's registry believing it to be a web worker,
        and one gunicorn worker would go unscraped. Nothing crashes (exhaustion only
        warns), so it would silently report the wrong thing."""
        assert "PROMETHEUS_EXPORT_WORKER_PORTS" in source

        units = {
            path.name: path.read_text()
            for path in (REPO_ROOT / "infra/ansible/roles/services/templates").glob(
                "stockmarket-*.service.j2"
            )
        }
        setters = {
            name for name, text in units.items() if "PROMETHEUS_EXPORT_WORKER_PORTS=true" in text
        }

        assert setters == {"stockmarket-api.service.j2"}, (
            f"only gunicorn may claim the worker ports, but {sorted(setters)} set the flag"
        )

    def test_obs_deploy_ships_the_unit_that_carries_the_flag(self):
        """`prod.py` gates the metrics ports on PROMETHEUS_EXPORT_WORKER_PORTS, and only
        the api unit sets it - so the task deploying that unit MUST carry the
        observability tag. Untagged, `just obs-deploy` ships the gated settings without
        the flag that enables them, gunicorn binds no metrics ports at all, and every
        Django metric silently disappears. That regression reached production once."""
        tasks = yaml.safe_load(
            (REPO_ROOT / "infra/ansible/roles/services/tasks/main.yml").read_text()
        )
        task = next(t for t in tasks if t["name"] == "Deploy stockmarket-api systemd unit")

        tags = task.get("tags", [])
        tags = [tags] if isinstance(tags, str) else tags
        assert "observability" in tags

        # And Environment= only applies on a restart - a daemon-reload leaves the running
        # master with its old environment.
        notify = task.get("notify", [])
        notify = [notify] if isinstance(notify, str) else notify
        assert "restart api" in notify

    def test_the_flag_is_not_in_the_shared_env_file(self):
        """Every unit reads the same {{ app_dir }}/.env, so putting it there would hand
        the ports to whichever process booted first - the exact bug the gate fixes.

        Checks ASSIGNMENTS, not prose: env.j2 legitimately explains in a comment why the
        tracing flag may live there while this one may not, and a bare substring search
        cannot tell an explanation from a setting.
        """
        env_j2 = (REPO_ROOT / "infra/ansible/roles/deploy/templates/env.j2").read_text()
        assignments = [
            line.split("=", 1)[0].strip()
            for line in env_j2.splitlines()
            if "=" in line and not line.lstrip().startswith("#")
        ]

        assert "PROMETHEUS_EXPORT_WORKER_PORTS" not in assignments

    def test_alloy_scrapes_every_worker_port(self, source):
        """The range and Alloy's static target list must agree, or a worker's counters
        are dropped and every rate() silently under-reports."""
        text = source
        start, stop = map(
            int,
            re.search(
                r"PROMETHEUS_METRICS_EXPORT_PORT_RANGE = range\((\d+), (\d+)\)", text
            ).groups(),
        )

        site = yaml.safe_load((REPO_ROOT / "infra/ansible/site.yml").read_text())
        targets = set()
        for play in site:
            for role in play.get("roles", []):
                if isinstance(role, dict):
                    for scrape in role.get("alloy_app_scrape_targets", []):
                        if scrape["job"] == "django":
                            targets |= set(scrape["targets"])

        assert targets == {f"127.0.0.1:{port}" for port in range(start, stop)}


class TestCeleryEventPipeline:
    """Celery task metrics need THREE switches on at once. Miss any one and the event
    stream still flows - carrying worker heartbeats but no task lifecycle - so every task
    metric reads a plausible-looking zero rather than erroring."""

    def test_worker_send_task_events_is_on(self):
        assert settings.CELERY_WORKER_SEND_TASK_EVENTS is True

    def test_task_sent_event_is_on(self):
        """Without this there is no task-sent event, which is what teaches the exporter
        the uuid -> task name mapping. Every later event for that task is then unnameable
        and gets dropped."""
        assert settings.CELERY_TASK_SEND_SENT_EVENT is True

    def test_worker_unit_passes_the_events_flag(self):
        unit = (
            REPO_ROOT / "infra/ansible/roles/services/templates/stockmarket-celery.service.j2"
        ).read_text()
        exec_start = next(line for line in unit.splitlines() if line.startswith("ExecStart="))

        assert re.search(r"(^|\s)-E(\s|$)", exec_start), (
            "the worker publishes no task events without -E"
        )


class TestMetricsExporterUnit:
    """The exporter's port is declared in two places that must agree."""

    @pytest.fixture
    def unit(self):
        return (
            REPO_ROOT / "infra/ansible/roles/services/templates/stockmarket-metrics.service.j2"
        ).read_text()

    def test_unit_port_matches_alloys_celery_scrape_target(self, unit):
        """If these drift, the exporter runs happily and Alloy scrapes nothing - the
        Celery dashboard is simply empty, with no error anywhere."""
        port = int(re.search(r"--port (\d+)", unit).group(1))

        site = yaml.safe_load((REPO_ROOT / "infra/ansible/site.yml").read_text())
        targets = set()
        for play in site:
            for role in play.get("roles", []):
                if isinstance(role, dict):
                    for scrape in role.get("alloy_app_scrape_targets", []):
                        if scrape["job"] == "celery":
                            targets |= set(scrape["targets"])

        assert targets == {f"127.0.0.1:{port}"}

    def test_unit_binds_loopback_only(self, unit):
        """Alloy scrapes from the same host; these metrics have no business on the LAN."""
        assert "--address 127.0.0.1" in unit

    def test_unit_runs_the_management_command(self, unit):
        assert "manage.py run_metrics_exporter" in unit

    def test_unit_restarts_forever(self, unit):
        """It holds a long-lived broker connection, so a Redis restart will kill it."""
        assert "Restart=always" in unit

    def test_command_is_registered_and_wires_the_http_server(self, monkeypatch):
        """--once exercises import + argument handling without consuming events. The
        HTTP server is patched rather than bound: a real bind would race under
        `pytest -n auto`."""
        from django.core.management import call_command

        calls = []
        monkeypatch.setattr(
            "apps.tasks.management.commands.run_metrics_exporter.start_http_server",
            lambda port, addr: calls.append((port, addr)),
        )

        call_command("run_metrics_exporter", "--once", "--port", "9999")

        assert calls == [(9999, "127.0.0.1")]

    def test_command_covers_every_task_event_it_counts(self):
        """The handler map and the subscription list are separate structures; an event
        counted but never subscribed to would never arrive."""
        from apps.tasks.metrics import _TASK_COUNTERS, TASK_EVENTS

        assert set(TASK_EVENTS) == set(_TASK_COUNTERS)
