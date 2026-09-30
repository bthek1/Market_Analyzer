from urllib.parse import urlparse

import redis
from django.conf import settings


def _client() -> redis.Redis:
    url = settings.CELERY_BROKER_URL
    parsed = urlparse(url)
    return redis.Redis(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        db=int(parsed.path.lstrip("/") or 0),
        decode_responses=True,
    )


INFO_FIELDS = {
    "redis_version",
    "uptime_in_seconds",
    "connected_clients",
    "used_memory_human",
    "used_memory_peak_human",
    "mem_fragmentation_ratio",
    "total_commands_processed",
    "instantaneous_ops_per_sec",
    "keyspace_hits",
    "keyspace_misses",
}


def get_info() -> dict:
    client = _client()
    raw = client.info()
    keyspace = client.info("keyspace")
    result = {k: v for k, v in raw.items() if k in INFO_FIELDS}
    result["keyspace"] = keyspace
    return result


def get_keys(prefix: str | None = None, limit: int = 100) -> list[dict]:
    limit = min(limit, 500)
    client = _client()
    pattern = f"{prefix}*" if prefix else "*"

    keys = []
    for key in client.scan_iter(pattern, count=200):
        keys.append(key)
        if len(keys) >= limit:
            break

    if not keys:
        return []

    pipe = client.pipeline(transaction=False)
    for key in keys:
        pipe.type(key)
        pipe.ttl(key)
        pipe.memory_usage(key, samples=0)
    results = pipe.execute()

    output = []
    for i, key in enumerate(keys):
        key_type = results[i * 3]
        ttl = results[i * 3 + 1]
        mem = results[i * 3 + 2]
        output.append(
            {
                "key": key,
                "type": key_type,
                "ttl": ttl,
                "size_bytes": mem or 0,
            }
        )

    return output


def get_key_value(key: str) -> dict:
    client = _client()
    key_type = client.type(key)
    if key_type == "none":
        return {"type": "none", "value": None}

    if key_type == "string":
        value = client.get(key)
    elif key_type == "list":
        value = client.lrange(key, 0, 99)
    elif key_type == "set":
        value = list(client.smembers(key))
    elif key_type == "zset":
        value = client.zrange(key, 0, 99, withscores=True)
    elif key_type == "hash":
        value = client.hgetall(key)
    else:
        value = None

    return {"type": key_type, "value": value}
