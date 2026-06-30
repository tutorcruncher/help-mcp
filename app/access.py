"""Org-membership access control for the docs tools.

GitHub OAuth proves a user's identity but not that they belong to your
organization — any GitHub account can complete the flow. This middleware gates
the tools so that only *active members* of a configured GitHub org may list or
call them, checked against the GitHub API using the user's own token.
"""

import hashlib
import logging
import time
from collections.abc import Sequence

import httpx
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from app.auth import AUTH_MODE_CLAIM, KEY_AUTH_MODE

GITHUB_API = 'https://api.github.com'

logger = logging.getLogger('tc_help_mcp.access')


class OrgMembershipMiddleware(Middleware):
    """Allow tool access only to active members of a GitHub organization.

    Membership is checked via ``GET /user/memberships/orgs/{org}`` with the
    connecting user's token (requires the ``read:org`` scope) and cached for a
    short TTL to avoid an API call on every request. The cache is keyed by a
    hash of the token (never the token itself) and is bounded in size with
    expired entries purged, so it can't grow without limit or retain raw tokens.
    """

    def __init__(self, org: str, cache_ttl: float = 300.0, timeout: float = 10.0, max_cache: int = 1024) -> None:
        self.org = org
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self.max_cache = max_cache
        self._cache: dict[str, tuple[float, bool]] = {}

    @staticmethod
    def _key(token: str) -> str:
        """Return a non-reversible cache key for a token."""
        return hashlib.sha256(token.encode()).hexdigest()

    async def _check_github(self, token: str) -> bool:
        """Return whether the token's user is an active member of the org."""
        headers = {
            'Authorization': f'Bearer {token}',
            'Accept': 'application/vnd.github+json',
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f'{GITHUB_API}/user/memberships/orgs/{self.org}', headers=headers)
        except httpx.HTTPError as exc:
            logger.warning('org membership check failed for org=%s: %s', self.org, exc)
            return False
        state = response.json().get('state') if response.status_code == 200 else None
        logger.info('org membership check org=%s status=%s state=%s', self.org, response.status_code, state)
        return state == 'active'

    def _purge_expired(self, now: float) -> None:
        """Drop expired entries; if still over capacity, drop the soonest-expiring."""
        expired = [key for key, (expiry, _) in self._cache.items() if expiry <= now]
        for key in expired:
            del self._cache[key]
        if len(self._cache) >= self.max_cache:
            for key in sorted(self._cache, key=lambda k: self._cache[k][0])[: len(self._cache) - self.max_cache + 1]:
                del self._cache[key]

    async def _is_member(self, token: str) -> bool:
        """Return cached membership for the token, refreshing past the TTL."""
        now = time.monotonic()
        key = self._key(token)
        cached = self._cache.get(key)
        if cached is not None and cached[0] > now:
            return cached[1]
        allowed = await self._check_github(token)
        self._purge_expired(now)
        self._cache[key] = (now + self.cache_ttl, allowed)
        return allowed

    async def _allowed(self) -> bool:
        """Return whether the current request's user may use the tools."""
        access = get_access_token()
        if access is None:
            logger.info('access check: no authenticated token in request context')
            return False
        if access.claims and access.claims.get(AUTH_MODE_CLAIM) == KEY_AUTH_MODE:
            logger.info('access check: key-authenticated request bypasses org gate')
            return True
        login = access.claims.get('login') if access.claims else None
        allowed = await self._is_member(access.token)
        logger.info('access check login=%s org=%s allowed=%s', login, self.org, allowed)
        return allowed

    async def on_call_tool(self, context: MiddlewareContext, call_next: CallNext):
        """Reject tool calls from users who are not active org members."""
        if not await self._allowed():
            raise ToolError(f"Access denied: you must be an active member of the '{self.org}' GitHub organization.")
        return await call_next(context)

    async def on_list_tools(self, context: MiddlewareContext, call_next: CallNext) -> Sequence:
        """Hide the tool list entirely from users who are not org members."""
        if not await self._allowed():
            return []
        tools = await call_next(context)
        logger.info('list_tools returning %d tools', len(list(tools)))
        return tools
