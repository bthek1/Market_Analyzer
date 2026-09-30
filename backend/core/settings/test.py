from .base import *  # noqa: F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# allauth/authtoken migrations have a swappable_dependency on AUTH_USER_MODEL that
# resolves to accounts.0001_enable_pgvector (the graph root), not 0002_initial where
# CustomUser is actually created. Treating these as unmigrated lets Django syncdb
# their tables from models and avoids the ordering conflict on SQLite in-memory tests.
MIGRATION_MODULES = {
    "account": None,
    "socialaccount": None,
    "authtoken": None,
}

# Tracing is forced OFF regardless of the developer's .env. Same class of problem as
# the metrics port below: configure_tracing() would start a BatchSpanProcessor thread
# and an OTLP exporter in every pytest worker, making the suite depend on a reachable
# collector. Asserted in core/tests/test_tracing.py.
OTEL_TRACES_ENABLED = False

# No django_prometheus DB wrapper and no metrics port here, both deliberately:
# the wrapper above is postgresql-only while these tests run on SQLite, and binding a
# port would break parallel runs (pytest -n auto) with EADDRINUSE. Both are asserted in
# core/tests/test_prometheus_wiring.py so a future edit to base.py cannot reintroduce
# them silently.
