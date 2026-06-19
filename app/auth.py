"""GitHub OAuth authentication for the MCP server.

Uses FastMCP's GitHubProvider, which makes this server act as an OAuth 2.1
resource/authorization server to Claude's custom connector while proxying the
authorization flow to a GitHub OAuth App. After a user authenticates, the
upstream GitHub access token is retrievable via get_access_token().token —
used by OrgMembershipMiddleware to verify org membership.

OAuth state (dynamic client registrations and tokens) is persisted via a
pluggable key-value store. When ``REDIS_URL`` is configured the state lives in
Redis so it survives process restarts; without it FastMCP falls back to its
default on-disk store, which is lost whenever the host filesystem is ephemeral
(e.g. Heroku dyno cycling), forcing every connected client to re-authenticate.
"""

from urllib.parse import urlparse

from cryptography.fernet import Fernet
from fastmcp.server.auth.jwt_issuer import derive_jwt_key
from fastmcp.server.auth.providers.github import GitHubProvider
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


def build_auth(settings: Settings) -> GitHubProvider:
    """Build the GitHubProvider that authenticates each connecting user.

    The GitHub OAuth App's Authorization callback URL must be
    ``<base_url>/auth/callback`` (GitHubProvider's default redirect_path).

    Args:
        settings: Runtime settings holding the OAuth App credentials and base URL.

    Returns:
        GitHubProvider: Configured auth provider to pass as ``FastMCP(auth=...)``.
    """
    return GitHubProvider(
        client_id=settings.github_client_id,
        client_secret=settings.github_client_secret,
        base_url=settings.base_url,
        required_scopes=settings.github_scopes,
        jwt_signing_key=settings.jwt_signing_key,
        allowed_client_redirect_uris=settings.allowed_redirect_uris,
        client_storage=_build_client_storage(settings),
    )
