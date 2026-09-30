from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_redis(monkeypatch):
    client = MagicMock()
    client.info.side_effect = lambda section=None: (
        {
            "redis_version": "7.2.4",
            "uptime_in_seconds": 3600,
            "connected_clients": 2,
            "used_memory_human": "1.00M",
            "used_memory_peak_human": "1.20M",
            "mem_fragmentation_ratio": 1.05,
            "total_commands_processed": 5000,
            "instantaneous_ops_per_sec": 10,
            "keyspace_hits": 400,
            "keyspace_misses": 20,
        }
        if section is None
        else {"db0": {"keys": 10, "expires": 3}}
    )
    client.scan_iter.return_value = iter(["celery-task-meta-abc", "_kombu.binding.celery"])
    pipe = MagicMock()
    pipe.execute.return_value = ["string", 86400, 240, "string", -1, 120]
    client.pipeline.return_value = pipe
    client.type.return_value = "string"
    client.get.return_value = "some-value"

    with patch("apps.redis_monitor.services._client", return_value=client):
        yield client


@pytest.mark.django_db
class TestRedisInfoView:
    def test_unauthenticated_returns_401(self, api_client):
        response = api_client.get("/api/redis/info/")
        assert response.status_code == 401

    def test_returns_info(self, auth_client, mock_redis):
        response = auth_client.get("/api/redis/info/")
        assert response.status_code == 200
        data = response.json()
        assert data["redis_version"] == "7.2.4"
        assert data["uptime_in_seconds"] == 3600
        assert "keyspace" in data

    def test_info_fields_filtered(self, auth_client, mock_redis):
        response = auth_client.get("/api/redis/info/")
        data = response.json()
        assert "used_memory_human" in data
        assert "mem_fragmentation_ratio" in data
        assert "connected_clients" in data
        assert "instantaneous_ops_per_sec" in data
        assert "keyspace_hits" in data
        assert "keyspace_misses" in data


@pytest.mark.django_db
class TestRedisKeysView:
    def test_unauthenticated_returns_401(self, api_client):
        response = api_client.get("/api/redis/keys/")
        assert response.status_code == 401

    def test_returns_keys(self, auth_client, mock_redis):
        response = auth_client.get("/api/redis/keys/")
        assert response.status_code == 200
        data = response.json()
        assert "keys" in data
        assert "count" in data
        assert data["count"] == 2
        assert data["keys"][0]["key"] == "celery-task-meta-abc"
        assert data["keys"][0]["type"] == "string"
        assert data["keys"][0]["ttl"] == 86400
        assert data["keys"][0]["size_bytes"] == 240

    def test_size_bytes_defaults_to_zero_when_memory_usage_returns_none(
        self, auth_client, mock_redis
    ):
        pipe = MagicMock()
        pipe.execute.return_value = ["string", 86400, None]
        mock_redis.pipeline.return_value = pipe
        mock_redis.scan_iter.return_value = iter(["some-key"])
        response = auth_client.get("/api/redis/keys/")
        assert response.json()["keys"][0]["size_bytes"] == 0

    def test_empty_redis_returns_empty_list(self, auth_client, mock_redis):
        mock_redis.scan_iter.return_value = iter([])
        response = auth_client.get("/api/redis/keys/")
        data = response.json()
        assert data["keys"] == []
        assert data["count"] == 0

    def test_limit_stops_scan_early(self, auth_client, mock_redis):
        # Return 5 keys but limit to 2 — scan should stop at 2
        mock_redis.scan_iter.return_value = iter(["k1", "k2", "k3", "k4", "k5"])
        pipe = MagicMock()
        pipe.execute.return_value = ["string", -1, 100, "string", -1, 100]
        mock_redis.pipeline.return_value = pipe
        response = auth_client.get("/api/redis/keys/?limit=2")
        assert response.json()["count"] == 2

    def test_prefix_filter_passed_to_scan(self, auth_client, mock_redis):
        auth_client.get("/api/redis/keys/?prefix=celery")
        mock_redis.scan_iter.assert_called_once_with("celery*", count=200)

    def test_no_prefix_uses_wildcard(self, auth_client, mock_redis):
        auth_client.get("/api/redis/keys/")
        mock_redis.scan_iter.assert_called_once_with("*", count=200)

    def test_limit_capped_at_500(self, auth_client, mock_redis):
        auth_client.get("/api/redis/keys/?limit=9999")
        assert mock_redis.scan_iter.called

    def test_invalid_limit_defaults_to_100(self, auth_client, mock_redis):
        response = auth_client.get("/api/redis/keys/?limit=abc")
        assert response.status_code == 200


@pytest.mark.django_db
class TestRedisKeyValueView:
    def test_unauthenticated_returns_401(self, api_client):
        response = api_client.get("/api/redis/keys/some-key/value/")
        assert response.status_code == 401

    def test_string_type(self, auth_client, mock_redis):
        response = auth_client.get("/api/redis/keys/some-key/value/")
        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "string"
        assert data["value"] == "some-value"

    def test_missing_key_returns_none(self, auth_client, mock_redis):
        mock_redis.type.return_value = "none"
        response = auth_client.get("/api/redis/keys/nonexistent/value/")
        assert response.status_code == 200
        assert response.json() == {"type": "none", "value": None}

    def test_list_type(self, auth_client, mock_redis):
        mock_redis.type.return_value = "list"
        mock_redis.lrange.return_value = ["item1", "item2"]
        response = auth_client.get("/api/redis/keys/my-list/value/")
        data = response.json()
        assert data["type"] == "list"
        assert data["value"] == ["item1", "item2"]
        mock_redis.lrange.assert_called_once_with("my-list", 0, 99)

    def test_set_type(self, auth_client, mock_redis):
        mock_redis.type.return_value = "set"
        mock_redis.smembers.return_value = {"a", "b"}
        response = auth_client.get("/api/redis/keys/my-set/value/")
        data = response.json()
        assert data["type"] == "set"
        assert set(data["value"]) == {"a", "b"}

    def test_zset_type(self, auth_client, mock_redis):
        mock_redis.type.return_value = "zset"
        mock_redis.zrange.return_value = [("member1", 1.0), ("member2", 2.0)]
        response = auth_client.get("/api/redis/keys/my-zset/value/")
        data = response.json()
        assert data["type"] == "zset"
        assert len(data["value"]) == 2
        mock_redis.zrange.assert_called_once_with("my-zset", 0, 99, withscores=True)

    def test_hash_type(self, auth_client, mock_redis):
        mock_redis.type.return_value = "hash"
        mock_redis.hgetall.return_value = {"field1": "val1", "field2": "val2"}
        response = auth_client.get("/api/redis/keys/my-hash/value/")
        data = response.json()
        assert data["type"] == "hash"
        assert data["value"] == {"field1": "val1", "field2": "val2"}

    def test_unknown_type_returns_none_value(self, auth_client, mock_redis):
        mock_redis.type.return_value = "stream"
        response = auth_client.get("/api/redis/keys/my-stream/value/")
        data = response.json()
        assert data["type"] == "stream"
        assert data["value"] is None


@pytest.mark.django_db
class TestClientConstruction:
    def test_client_uses_broker_url(self, settings):
        settings.CELERY_BROKER_URL = "redis://myhost:6380/2"
        with patch("redis.Redis") as mock_cls:
            mock_cls.return_value = MagicMock()
            from apps.redis_monitor.services import _client

            _client()
            mock_cls.assert_called_once_with(
                host="myhost",
                port=6380,
                db=2,
                decode_responses=True,
            )

    def test_client_defaults_for_bare_url(self, settings):
        settings.CELERY_BROKER_URL = "redis://localhost/0"
        with patch("redis.Redis") as mock_cls:
            mock_cls.return_value = MagicMock()
            from apps.redis_monitor.services import _client

            _client()
            call_kwargs = mock_cls.call_args.kwargs
            assert call_kwargs["host"] == "localhost"
            assert call_kwargs["db"] == 0
