"""Redis acceleration for durable repeated-source result reuse."""

from __future__ import annotations

from collections.abc import Protocol

from redis import Redis
from redis.exceptions import RedisError


class SourceResultCache(Protocol):
    def get(self, fingerprint: str) -> str | None: ...

    def set(self, fingerprint: str, task_id: str) -> None: ...

    def delete(self, fingerprint: str) -> None: ...


class RedisSourceResultCache:
    """Cache only opaque fingerprints and task IDs; MySQL remains authoritative."""

    def __init__(self, url: str, *, ttl_seconds: int = 30 * 24 * 60 * 60) -> None:
        if ttl_seconds < 60:
            raise ValueError("source cache TTL must be at least one minute")
        self.client = Redis.from_url(url, decode_responses=True, socket_timeout=2)
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def _key(fingerprint: str) -> str:
        return f"v2note:source-result:{fingerprint}"

    def get(self, fingerprint: str) -> str | None:
        try:
            value = self.client.get(self._key(fingerprint))
        except RedisError:
            return None
        return value if isinstance(value, str) else None

    def set(self, fingerprint: str, task_id: str) -> None:
        try:
            self.client.set(self._key(fingerprint), task_id, ex=self.ttl_seconds)
        except RedisError:
            # The durable MySQL mapping still provides correct idempotency.
            return

    def delete(self, fingerprint: str) -> None:
        try:
            self.client.delete(self._key(fingerprint))
        except RedisError:
            return

    def close(self) -> None:
        self.client.close()
