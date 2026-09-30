import environ

from .base import *  # noqa: F403

env = environ.Env()

DEBUG = False

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])

SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# django-prometheus wraps the DB backend to time queries and count connection errors.
# Deliberately NOT in base.py: core/settings/test.py runs on SQLite (the knowledge-graph
# trigram paths degrade for it), and the postgresql wrapper cannot serve that. The guard
# means a sqlite DATABASE_URL here degrades to plain Django rather than failing to boot.
if DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":  # noqa: F405
    DATABASES["default"]["ENGINE"] = "django_prometheus.db.backends.postgresql"  # noqa: F405

# One metrics port per gunicorn worker (the unit runs --workers 4). Each worker process
# owns a separate prometheus_client registry, so a single /metrics URL would report
# whichever worker happened to serve the scrape. Alloy scrapes all four and Prometheus
# sums the counters.
#
# The alternative, PROMETHEUS_MULTIPROC_DIR, needs --preload, a writable tmpfs and a
# worker-exit hook to reap dead PIDs - all of which this avoids.
#
# NOT in base.py: binding happens in django_prometheus' AppConfig.ready(), so setting it
# there would make every management command, every runserver and every pytest process
# try to bind these ports.
#
# Gated on an env var that ONLY the gunicorn unit sets. Binding happens in
# django_prometheus' AppConfig.ready(), which runs in EVERY process that calls
# django.setup() - the Celery worker, beat, the metrics exporter, and each `manage.py`
# invocation during a deploy. Ungated, whichever of those started first would claim
# 8005, Alloy would scrape a Celery worker's registry believing it to be a web worker,
# and one gunicorn worker would go unscraped. (Exhaustion only logs a warning and
# returns None, so nothing crashed - it silently reported the wrong thing.)
if env.bool("PROMETHEUS_EXPORT_WORKER_PORTS", default=False):
    PROMETHEUS_METRICS_EXPORT_PORT_RANGE = range(8005, 8009)
    PROMETHEUS_METRICS_EXPORT_ADDRESS = "127.0.0.1"
