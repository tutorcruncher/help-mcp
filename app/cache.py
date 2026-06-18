"""A small async TTL cache for latency/rate-limit protection.

This is deliberately *not* a source of truth: entries expire after a short TTL and
the value is re-fetched from the live source. It exists only to avoid hammering
Intercom / GitHub when Claude makes several tool calls in quick succession.

``get_or_load`` holds a per-key lock across the load so concurrent calls for the
same key wait for a single fetch (no thundering herd), while loads for *different*
keys run concurrently — important for the API-docs fan-out, which fetches many
distinct files at once through one shared cache.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable, Hashable
from typing import Any


class TTLCache:
    """An async key/value cache whose entries expire after a fixed TTL.

    Args:
        ttl: Seconds an entry stays fresh before it is re-loaded.
        max_entries: Soft cap; expired entries are purged on write and, if still
            over capacity, the soonest-expiring entries are dropped.
    """

    def __init__(self, ttl: float, max_entries: int = 4096) -> None:
        self.ttl = ttl
        self.max_entries = max_entries
        self._entries: dict[Hashable, tuple[float, Any]] = {}
        self._locks: dict[Hashable, asyncio.Lock] = {}

    def _lock_for(self, key: Hashable) -> asyncio.Lock:
        """Return the lock guarding loads for a key, creating it on first use."""
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def _purge(self, now: float) -> None:
        """Drop expired entries; if still over capacity, drop the soonest-expiring."""
        expired = [key for key, (expiry, _) in self._entries.items() if expiry <= now]
        for key in expired:
            del self._entries[key]
            self._locks.pop(key, None)
        if len(self._entries) >= self.max_entries:
            overflow = len(self._entries) - self.max_entries + 1
            for key in sorted(self._entries, key=lambda k: self._entries[k][0])[:overflow]:
                del self._entries[key]
                self._locks.pop(key, None)

    async def get_or_load(self, key: Hashable, loader: Callable[[], Awaitable[Any]]) -> Any:
        """Return the cached value for ``key`` or load and cache it.

        The loader runs at most once per key per TTL window even under concurrent
        callers, because it is awaited while holding the key's lock.

        Args:
            key: Cache key.
            loader: Async callable that fetches the value from the live source.

        Returns:
            The cached or freshly loaded value.
        """
        async with self._lock_for(key):
            now = time.monotonic()
            cached = self._entries.get(key)
            if cached is not None and cached[0] > now:
                return cached[1]
            value = await loader()
            self._purge(now)
            self._entries[key] = (now + self.ttl, value)
            return value

    def clear(self) -> None:
        """Drop all cached entries (used in tests)."""
        self._entries.clear()
        self._locks.clear()
