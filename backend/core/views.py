import subprocess
from datetime import UTC, timedelta
from datetime import datetime as dt
from pathlib import Path

import httpx
from django.conf import settings
from django.db import OperationalError, connection
from django.db.models import Max
from redis import Redis
from redis.exceptions import RedisError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

_BEAT_STALE_MINUTES = 25

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _git_version() -> str:
    try:
        return subprocess.check_output(
            ["git", "describe", "--tags", "--exact-match", "HEAD"],
            cwd=_REPO_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except subprocess.CalledProcessError:
        pass  # not on a tagged commit — fall through to short hash
    except Exception:
        return "unknown"

    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_REPO_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def _check_redis() -> bool:
    try:
        r = Redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=1)
        return r.ping()
    except RedisError:
        return False


def _check_celery() -> bool:
    try:
        from core.celery import app as celery_app

        result = celery_app.control.inspect(timeout=1).ping()
        return bool(result)
    except Exception:
        return False


def _check_beat() -> bool:
    try:
        from django_celery_beat.models import PeriodicTask

        agg = PeriodicTask.objects.filter(enabled=True).aggregate(last=Max("last_run_at"))
        last = agg["last"]
        return last is not None and last >= dt.now(UTC) - timedelta(minutes=_BEAT_STALE_MINUTES)
    except Exception:
        return False


def _check_ollama() -> bool:
    # Through get_llm_config, NOT settings.OLLAMA_BASE_URL: the env var only seeds the
    # LLMSettings row, and the row is the source of truth once it exists. Reading the
    # setting would probe whichever host was configured at first-create and report health
    # for a server the app no longer talks to.
    try:
        from apps.llm_analysis.config import get_llm_config

        with httpx.Client(timeout=2) as client:
            resp = client.get(f"{get_llm_config().base_url.rstrip('/')}/api/tags")
            return resp.status_code == 200
    except Exception:
        return False


class HealthView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request):
        db_ok = True
        try:
            connection.ensure_connection()
        except OperationalError:
            db_ok = False

        redis_ok = _check_redis()
        celery_ok = _check_celery()
        beat_ok = _check_beat()
        ollama_ok = _check_ollama()

        return Response(
            {
                "version": _git_version(),
                "db": db_ok,
                "redis": redis_ok,
                "celery": celery_ok,
                "beat": beat_ok,
                "ollama": ollama_ok,
            }
        )
