import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.prod")

# ORDER HERE IS LOAD-BEARING, and getting it wrong fails SILENTLY.
#
# DjangoInstrumentor does not wrap a handler - it INSERTS its middleware into
# settings.MIDDLEWARE. get_wsgi_application() constructs a WSGIHandler, whose __init__
# immediately calls load_middleware(), and that resolves settings.MIDDLEWARE exactly
# once. So instrumenting AFTER it mutates a list nobody reads again: every psycopg span
# still arrives, but with no request span above it, so each DB query becomes its own
# root trace. Verified in production - 5 traces, all rooted at "SELECT", zero
# server-kind spans - before the order was corrected.
#
# django.setup() first because the instrumentor needs importable settings;
# set_prefix=False matches what get_wsgi_application() would have passed.
django.setup(set_prefix=False)

from core.tracing import configure_tracing  # noqa: E402

# Here rather than in an AppConfig.ready() on purpose: ready() fires in every process
# that calls django.setup(), including each `manage.py` during a deploy and every pytest
# worker. This module is imported only by gunicorn, which is exactly the set of
# processes that should export web spans.
configure_tracing("stockmarket-api")

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
