import os

from celery import Celery
from celery.signals import worker_process_init

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.dev")

app = Celery("stockmarket")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@worker_process_init.connect
def _init_tracing(**_kwargs):
    """Install tracing in each prefork CHILD, not the parent.

    BatchSpanProcessor runs a background thread, and threads do not survive fork() - a
    provider built in the parent leaves every child queueing spans that are never
    flushed. This signal fires after the fork, in the process that will actually run
    tasks, which is the only arrangement that works for the prefork pool.

    exclude_django because a Celery child serves no HTTP requests; the Django
    instrumentor would wrap a request handler that is never called.
    """
    from core.tracing import configure_tracing

    configure_tracing("stockmarket-celery", exclude_django=True)
