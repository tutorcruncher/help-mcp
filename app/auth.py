"""Authentication for the MCP server: static API keys or GitHub OAuth.

Two modes, chosen by configuration:

- **Key-based** (``MCP_API_KEYS`` set): clients present a static Bearer key
  (``Authorization: Bearer <key>``), validated against the configured keys via
  FastMCP's StaticTokenVerifier. The key itself is the gate — no GitHub OAuth
  app, no org membership check. This is the simplest way to connect the server
  to a single client (e.g. an automation/agent) without an interactive flow.

- **GitHub OAuth** (default): GitHubProvider makes this server act as an OAuth
  2.1 resource/authorization server to Claude's custom connector, proxying the
  flow to a GitHub OAuth App. The upstream GitHub token is then used by
  OrgMembershipMiddleware to verify org membership. OAuth state (dynamic client
  registrations and tokens) is persisted via a pluggable key-value store; with
  ``REDIS_URL`` set it survives restarts (otherwise the default on-disk store is
  lost on ephemeral filesystems like Heroku dyno cycling).
"""

from urllib.parse import urlparse

from cryptography.fernet import Fernet
from fastmcp.server.auth import AuthProvider
from fastmcp.server.auth.jwt_issuer import derive_jwt_key
from fastmcp.server.auth.providers.github import GitHubProvider
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
from key_value.aio.protocols import AsyncKeyValue
from key_value.aio.stores.redis import RedisStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

from app.config import Settings


def _build_client_storage(settings: Settings) -> AsyncKeyValue | None:
    """Build a persistent, encrypted OAuth-state store, or None for the default.

    Returns a Redis-backed store wrapped in Fernet encryption when ``redis_url``
    is set, so OAuth state survives restarts and is encrypted at rest with a key
    derived from the JWT signing key (matching FastMCP's default-store scheme).
    Heroku's managed Redis serves ``rediss://`` with a self-signed certificate,
    so TLS verification is relaxed for that scheme. Returns None when no Redis is
    configured, letting GitHubProvider use its built-in on-disk store.

    Args:
        settings: Runtime settings holding the optional Redis URL and signing key.

    Returns:
        AsyncKeyValue | None: The storage backend, or None to use the default.
    """
    if not settings.redis_url:
        return None

    if urlparse(settings.redis_url).scheme == 'rediss':
        store = RedisStore(url=settings.redis_url, ssl_cert_reqs='none', ssl_check_hostname=False)
    else:
        store = RedisStore(url=settings.redis_url)

    encryption_key = derive_jwt_key(
        high_entropy_material=settings.jwt_signing_key,
        salt='fastmcp-storage-encryption-key',
    )
    return FernetEncryptionWrapper(
        key_value=store,
        fernet=Fernet(key=encryption_key),
        raise_on_decryption_error=False,
    )


def build_key_verifier(settings: Settings) -> StaticTokenVerifier:
    """Build a static-token verifier from the configured API keys.

    Each key authenticates as a distinct client_id so logs/traces can tell connections
    apart. Possession of a valid key is the only gate (no org membership check).

    Args:
        settings: Runtime settings holding ``mcp_api_keys``.

    Returns:
        StaticTokenVerifier: Verifier to pass as ``FastMCP(auth=...)``.
    """
    tokens = {
        key: {'client_id': f'api-key-{index}', 'scopes': []} for index, key in enumerate(settings.mcp_api_keys, start=1)
    }
    return StaticTokenVerifier(tokens=tokens)


def build_auth(settings: Settings) -> AuthProvider:
    """Build the auth provider: static API keys when configured, else GitHub OAuth.

    Key-based auth takes precedence — when ``MCP_API_KEYS`` is set the server uses a
    StaticTokenVerifier and the GitHub OAuth credentials are not needed. Otherwise it
    builds the GitHubProvider (callback URL ``<base_url>/auth/callback``).

    Args:
        settings: Runtime settings holding the API keys or OAuth App credentials.

    Returns:
        AuthProvider: Configured auth provider to pass as ``FastMCP(auth=...)``.
    """
    if settings.key_auth_enabled:
        return build_key_verifier(settings)
    return GitHubProvider(
        client_id=settings.github_client_id,
        client_secret=settings.github_client_secret,
        base_url=settings.base_url,
        required_scopes=settings.github_scopes,
        jwt_signing_key=settings.jwt_signing_key,
        allowed_client_redirect_uris=settings.allowed_redirect_uris,
        client_storage=_build_client_storage(settings),
    )
