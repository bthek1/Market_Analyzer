from .base import *  # noqa: F403

DEBUG = True

ALLOWED_HOSTS = ["*"]

CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://192.168.2.28:5173",
]
# Allow any LAN host (192.168.x.x / 10.x.x.x) on the Vite dev port so the
# frontend works regardless of which machine IP serves it in development.
CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^http://192\.168\.\d{1,3}\.\d{1,3}:5173$",
]
CORS_ALLOW_CREDENTIALS = True

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# django-prometheus wraps the DB backend to time queries and count connection errors.
# Deliberately NOT in base.py: core/settings/test.py runs on SQLite (the knowledge-graph
# trigram paths degrade for it), and the postgresql wrapper cannot serve that. The guard
# means a sqlite DATABASE_URL here degrades to plain Django rather than failing to boot.
if DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":  # noqa: F405
    DATABASES["default"]["ENGINE"] = "django_prometheus.db.backends.postgresql"  # noqa: F405

# Single-process runserver, so one port is enough. Off unless asked for: binding a port
# on every `manage.py` invocation is a surprising side effect in development.
if env.bool("PROMETHEUS_METRICS_PORT_ENABLED", default=False):  # noqa: F405
    PROMETHEUS_METRICS_EXPORT_PORT = 8005
    PROMETHEUS_METRICS_EXPORT_ADDRESS = "127.0.0.1"
