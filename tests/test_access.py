from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.access import OrgMembershipMiddleware

CONTEXT: Any = object()


@dataclass
class FakeToken:
    token: str


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


def _patch_httpx(response: FakeResponse) -> MagicMock:
    """Patch app.access.httpx.AsyncClient to return a fixed response."""
    client = AsyncMock()
    client.get = AsyncMock(return_value=response)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=ctx)


async def test_active_member_allowed():
    """A 200 with state=active grants membership."""
    mw = OrgMembershipMiddleware('tutorcruncher')
    with patch('app.access.httpx.AsyncClient', _patch_httpx(FakeResponse(200, {'state': 'active'}))):
        assert await mw._check_github('gho_x') is True


async def test_pending_member_denied():
    """A pending invitation is not active membership."""
    mw = OrgMembershipMiddleware('tutorcruncher')
    with patch('app.access.httpx.AsyncClient', _patch_httpx(FakeResponse(200, {'state': 'pending'}))):
        assert await mw._check_github('gho_x') is False


async def test_non_member_denied():
    """A 404 (no membership record) is denied."""
    mw = OrgMembershipMiddleware('tutorcruncher')
    with patch('app.access.httpx.AsyncClient', _patch_httpx(FakeResponse(404))):
        assert await mw._check_github('gho_x') is False


async def test_membership_is_cached():
    """Repeated checks within the TTL hit GitHub only once per token."""
    mw = OrgMembershipMiddleware('tutorcruncher', cache_ttl=300.0)
    with patch.object(mw, '_check_github', AsyncMock(return_value=True)) as mock_check:
        assert await mw._is_member('gho_x') is True
        assert await mw._is_member('gho_x') is True
        mock_check.assert_awaited_once()


async def test_cache_keyed_by_hash_not_raw_token():
    """The raw token is never stored as a cache key."""
    mw = OrgMembershipMiddleware('tutorcruncher')
    with patch.object(mw, '_check_github', AsyncMock(return_value=True)):
        await mw._is_member('gho_secret')
    assert 'gho_secret' not in mw._cache
    assert all('gho_secret' not in key for key in mw._cache)


async def test_cache_is_bounded():
    """The cache never grows past max_cache entries."""
    mw = OrgMembershipMiddleware('tutorcruncher', max_cache=8)
    with patch.object(mw, '_check_github', AsyncMock(return_value=True)):
        for i in range(100):
            await mw._is_member(f'gho_{i}')
    assert len(mw._cache) <= 8


async def test_expired_entries_are_purged():
    """Entries past their TTL are dropped, not retained forever."""
    mw = OrgMembershipMiddleware('tutorcruncher', cache_ttl=0.0)
    with patch.object(mw, '_check_github', AsyncMock(return_value=True)):
        await mw._is_member('gho_a')
        await mw._is_member('gho_b')
    assert len(mw._cache) <= 1


async def test_on_call_tool_denies_non_member():
    """Tool calls from non-members raise ToolError and never reach the backend."""
    from fastmcp.exceptions import ToolError

    mw = OrgMembershipMiddleware('tutorcruncher')
    call_next = AsyncMock()
    with patch.object(mw, '_allowed', AsyncMock(return_value=False)):
        with pytest.raises(ToolError, match='tutorcruncher'):
            await mw.on_call_tool(CONTEXT, call_next)
    call_next.assert_not_awaited()


async def test_on_call_tool_allows_member():
    """Tool calls from members are forwarded to the backend."""
    mw = OrgMembershipMiddleware('tutorcruncher')
    call_next = AsyncMock(return_value='result')
    with patch.object(mw, '_allowed', AsyncMock(return_value=True)):
        assert await mw.on_call_tool(CONTEXT, call_next) == 'result'
    call_next.assert_awaited_once()


async def test_on_list_tools_hides_for_non_member():
    """Non-members see an empty tool list."""
    mw = OrgMembershipMiddleware('tutorcruncher')
    call_next = AsyncMock()
    with patch.object(mw, '_allowed', AsyncMock(return_value=False)):
        assert await mw.on_list_tools(CONTEXT, call_next) == []
    call_next.assert_not_awaited()


async def test_allowed_false_without_token():
    """No authenticated token means no access."""
    mw = OrgMembershipMiddleware('tutorcruncher')
    with patch('app.access.get_access_token', return_value=None):
        assert await mw._allowed() is False
