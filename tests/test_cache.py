import asyncio

from app.cache import TTLCache


async def test_caches_within_ttl():
    """A second call within the TTL returns the cached value without re-loading."""
    cache = TTLCache(ttl=300.0)
    calls = []

    async def loader():
        calls.append(1)
        return 'value'

    assert await cache.get_or_load('k', loader) == 'value'
    assert await cache.get_or_load('k', loader) == 'value'
    assert calls == [1]


async def test_reloads_after_expiry(monkeypatch):
    """Past the TTL the loader runs again and the fresh value is cached."""
    clock = {'now': 1000.0}
    monkeypatch.setattr('app.cache.time.monotonic', lambda: clock['now'])
    cache = TTLCache(ttl=60.0)
    values = iter(['first', 'second'])

    async def loader():
        return next(values)

    assert await cache.get_or_load('k', loader) == 'first'
    clock['now'] += 61.0
    assert await cache.get_or_load('k', loader) == 'second'


async def test_distinct_keys_load_concurrently():
    """Loads for different keys are not serialised by the per-key lock."""
    cache = TTLCache(ttl=300.0)
    started = asyncio.Event()

    async def slow():
        started.set()
        await asyncio.sleep(0.05)
        return 'slow'

    async def fast():
        await started.wait()
        return 'fast'

    results = await asyncio.gather(cache.get_or_load('a', slow), cache.get_or_load('b', fast))
    assert results == ['slow', 'fast']


async def test_concurrent_same_key_loads_once():
    """Concurrent callers for one key share a single load."""
    cache = TTLCache(ttl=300.0)
    calls = []

    async def loader():
        calls.append(1)
        await asyncio.sleep(0.01)
        return 'value'

    results = await asyncio.gather(*(cache.get_or_load('k', loader) for _ in range(5)))
    assert results == ['value'] * 5
    assert calls == [1]


async def test_purge_evicts_over_capacity(monkeypatch):
    """Writing past max_entries drops the soonest-expiring entries."""
    clock = {'now': 1000.0}
    monkeypatch.setattr('app.cache.time.monotonic', lambda: clock['now'])
    cache = TTLCache(ttl=300.0, max_entries=2)

    async def loader(value):
        return value

    await cache.get_or_load('a', lambda: loader('a'))
    clock['now'] += 1
    await cache.get_or_load('b', lambda: loader('b'))
    clock['now'] += 1
    await cache.get_or_load('c', lambda: loader('c'))

    assert 'a' not in cache._entries
    assert set(cache._entries) == {'b', 'c'}
