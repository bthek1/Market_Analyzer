import subprocess
from datetime import UTC, timedelta
from datetime import datetime as dt
from unittest.mock import MagicMock, patch

import httpx
import pytest
from django.db import OperationalError
from redis.exceptions import RedisError

from core.views import _check_beat, _check_celery, _check_ollama, _check_redis, _git_version

# ---------------------------------------------------------------------------
# HealthView
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestHealthView:
    url = "/api/health/"

    def test_always_returns_200(self, api_client):
        with (
            patch("core.views._check_redis", return_value=False),
            patch("core.views._check_celery", return_value=False),
            patch("core.views._check_beat", return_value=False),
            patch("core.views._check_ollama", return_value=False),
            patch(
                "django.db.connection.ensure_connection",
                side_effect=OperationalError("down"),
            ),
        ):
            response = api_client.get(self.url)
        assert response.status_code == 200

    def test_response_keys(self, api_client):
        with (
            patch("core.views._check_redis", return_value=True),
            patch("core.views._check_celery", return_value=True),
            patch("core.views._check_beat", return_value=True),
            patch("core.views._check_ollama", return_value=True),
        ):
            response = api_client.get(self.url)
        assert set(response.data.keys()) == {"version", "db", "redis", "celery", "beat", "ollama"}

    def test_all_healthy(self, api_client):
        with (
            patch("core.views._check_redis", return_value=True),
            patch("core.views._check_celery", return_value=True),
            patch("core.views._check_beat", return_value=True),
            patch("core.views._check_ollama", return_value=True),
        ):
            response = api_client.get(self.url)
        assert response.data["db"] is True
        assert response.data["redis"] is True
        assert response.data["celery"] is True
        assert response.data["beat"] is True
        assert response.data["ollama"] is True

    def test_db_down_reflected(self, api_client):
        with (
            patch("core.views._check_redis", return_value=True),
            patch("core.views._check_celery", return_value=True),
            patch("core.views._check_beat", return_value=True),
            patch("core.views._check_ollama", return_value=True),
            patch(
                "django.db.connection.ensure_connection",
                side_effect=OperationalError("connection refused"),
            ),
        ):
            response = api_client.get(self.url)
        assert response.data["db"] is False

    def test_redis_down_reflected(self, api_client):
        with (
            patch("core.views._check_redis", return_value=False),
            patch("core.views._check_celery", return_value=True),
            patch("core.views._check_beat", return_value=True),
            patch("core.views._check_ollama", return_value=True),
        ):
            response = api_client.get(self.url)
        assert response.data["redis"] is False

    def test_celery_down_reflected(self, api_client):
        with (
            patch("core.views._check_redis", return_value=True),
            patch("core.views._check_celery", return_value=False),
            patch("core.views._check_beat", return_value=True),
            patch("core.views._check_ollama", return_value=True),
        ):
            response = api_client.get(self.url)
        assert response.data["celery"] is False

    def test_beat_down_reflected(self, api_client):
        with (
            patch("core.views._check_redis", return_value=True),
            patch("core.views._check_celery", return_value=True),
            patch("core.views._check_beat", return_value=False),
            patch("core.views._check_ollama", return_value=True),
        ):
            response = api_client.get(self.url)
        assert response.data["beat"] is False

    def test_ollama_down_reflected(self, api_client):
        with (
            patch("core.views._check_redis", return_value=True),
            patch("core.views._check_celery", return_value=True),
            patch("core.views._check_beat", return_value=True),
            patch("core.views._check_ollama", return_value=False),
        ):
            response = api_client.get(self.url)
        assert response.data["ollama"] is False

    def test_no_auth_required(self, api_client):
        with (
            patch("core.views._check_redis", return_value=True),
            patch("core.views._check_celery", return_value=True),
            patch("core.views._check_beat", return_value=True),
            patch("core.views._check_ollama", return_value=True),
        ):
            response = api_client.get(self.url)
        assert response.status_code not in (401, 403)

    def test_post_not_allowed(self, api_client):
        response = api_client.post(self.url)
        assert response.status_code == 405

    def test_version_is_non_empty_string(self, api_client):
        with (
            patch("core.views._check_redis", return_value=True),
            patch("core.views._check_celery", return_value=True),
            patch("core.views._check_beat", return_value=True),
            patch("core.views._check_ollama", return_value=True),
        ):
            response = api_client.get(self.url)
        assert isinstance(response.data["version"], str)
        assert response.data["version"] != ""


# ---------------------------------------------------------------------------
# _check_redis
# ---------------------------------------------------------------------------


class TestCheckRedis:
    def test_returns_true_on_successful_ping(self):
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        with patch("core.views.Redis.from_url", return_value=mock_redis):
            assert _check_redis() is True

    def test_returns_false_on_connection_error(self):
        with patch("core.views.Redis.from_url", side_effect=RedisError("refused")):
            assert _check_redis() is False

    def test_returns_false_when_ping_raises(self):
        mock_redis = MagicMock()
        mock_redis.ping.side_effect = RedisError("timeout")
        with patch("core.views.Redis.from_url", return_value=mock_redis):
            assert _check_redis() is False


# ---------------------------------------------------------------------------
# _check_celery
# ---------------------------------------------------------------------------


class TestCheckCelery:
    def test_returns_true_when_workers_respond(self):
        mock_inspect = MagicMock()
        mock_inspect.ping.return_value = {"worker@host": {"ok": "pong"}}
        with patch("core.celery.app.control.inspect", return_value=mock_inspect):
            assert _check_celery() is True

    def test_returns_false_when_no_workers_respond(self):
        mock_inspect = MagicMock()
        mock_inspect.ping.return_value = {}
        with patch("core.celery.app.control.inspect", return_value=mock_inspect):
            assert _check_celery() is False

    def test_returns_false_when_ping_returns_none(self):
        mock_inspect = MagicMock()
        mock_inspect.ping.return_value = None
        with patch("core.celery.app.control.inspect", return_value=mock_inspect):
            assert _check_celery() is False

    def test_returns_false_on_exception(self):
        with patch("core.celery.app.control.inspect", side_effect=Exception("broker down")):
            assert _check_celery() is False


# ---------------------------------------------------------------------------
# _check_beat
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCheckBeat:
    def _mock_aggregate(self, last_run_at):
        mock_qs = MagicMock()
        mock_qs.aggregate.return_value = {"last": last_run_at}
        return patch(
            "django_celery_beat.models.PeriodicTask.objects.filter",
            return_value=mock_qs,
        )

    def test_returns_true_when_recently_run(self):
        recent = dt.now(UTC) - timedelta(minutes=5)
        with self._mock_aggregate(recent):
            assert _check_beat() is True

    def test_returns_false_when_stale(self):
        stale = dt.now(UTC) - timedelta(minutes=30)
        with self._mock_aggregate(stale):
            assert _check_beat() is False

    def test_returns_false_when_never_run(self):
        with self._mock_aggregate(None):
            assert _check_beat() is False

    def test_returns_false_on_exception(self):
        with patch(
            "django_celery_beat.models.PeriodicTask.objects.filter",
            side_effect=Exception("db error"),
        ):
            assert _check_beat() is False


# ---------------------------------------------------------------------------
# _check_ollama
# ---------------------------------------------------------------------------


class TestCheckOllama:
    """The probe reads its URL from LLMSettings, not settings.OLLAMA_BASE_URL - the env
    var only SEEDS the row, so the setting can name a host the app no longer talks to."""

    def test_returns_true_on_200(self, llm_settings):
        mock_resp = MagicMock(status_code=200)
        with patch("core.views.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            assert _check_ollama() is True

    def test_probes_the_configured_host_not_the_setting(self, llm_settings, settings):
        """The divergence this guards: change the row and the probe must follow it."""
        llm_settings.base_url = "http://moved-host:11434/"
        settings.OLLAMA_BASE_URL = "http://stale-host:11434"
        mock_resp = MagicMock(status_code=200)

        with patch("core.views.httpx.Client") as mock_cls:
            client = mock_cls.return_value.__enter__.return_value
            client.get.return_value = mock_resp
            _check_ollama()

        assert client.get.call_args.args[0] == "http://moved-host:11434/api/tags"

    def test_returns_false_on_non_200(self, llm_settings):
        mock_resp = MagicMock(status_code=503)
        with patch("core.views.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            assert _check_ollama() is False

    def test_returns_false_on_connect_error(self, llm_settings):
        with patch("core.views.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__.side_effect = httpx.ConnectError("refused")
            assert _check_ollama() is False

    def test_returns_false_on_timeout(self, llm_settings):
        with patch("core.views.httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__.side_effect = httpx.TimeoutException("timed out")
            assert _check_ollama() is False


# ---------------------------------------------------------------------------
# _git_version
# ---------------------------------------------------------------------------


class TestGitVersion:
    def test_returns_tag_when_on_tagged_commit(self):
        with patch("subprocess.check_output", return_value="v1.2.3\n"):
            assert _git_version() == "v1.2.3"

    def test_falls_back_to_short_hash_when_not_on_tag(self):
        def side_effect(cmd, **kwargs):
            if "--exact-match" in cmd:
                raise subprocess.CalledProcessError(128, cmd)
            return "abc1234\n"

        with patch("subprocess.check_output", side_effect=side_effect):
            assert _git_version() == "abc1234"

    def test_returns_unknown_when_git_unavailable(self):
        with patch("subprocess.check_output", side_effect=OSError("no git")):
            assert _git_version() == "unknown"

    def test_returns_unknown_when_hash_lookup_also_fails(self):
        def side_effect(cmd, **kwargs):
            if "--exact-match" in cmd:
                raise subprocess.CalledProcessError(128, cmd)
            raise OSError("git rev-parse failed")

        with patch("subprocess.check_output", side_effect=side_effect):
            assert _git_version() == "unknown"
