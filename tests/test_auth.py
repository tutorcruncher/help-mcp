import dataclasses
from unittest.mock import patch

from cryptography.fernet import Fernet
from fastmcp.server.auth.providers.github import GitHubProvider
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
from key_value.aio.stores.redis import RedisStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

from app.auth import AUTH_MODE_CLAIM, KEY_AUTH_MODE, DualAuthProvider, build_auth

NO_OAUTH = dict(github_client_id='', github_client_secret='', base_url='', jwt_signing_key='')


def test_build_auth_without_redis_uses_default_store(settings):
    """With no Redis configured, the provider falls back to FastMCP's on-disk store."""
    provider = build_auth(settings)

    assert isinstance(provider, GitHubProvider)
    storage = provider._client_storage
    assert isinstance(storage, FernetEncryptionWrapper)
    assert not isinstance(storage.key_value, RedisStore)


def test_build_auth_with_redis_persists_encrypted_state(settings):
    """A configured Redis URL wires an encrypted Redis-backed OAuth state store."""
    settings = dataclasses.replace(settings, redis_url='redis://redis.example.test:6379/0')

    provider = build_auth(settings)

    assert isinstance(provider, GitHubProvider)
    storage = provider._client_storage
    assert isinstance(storage, FernetEncryptionWrapper)
    assert isinstance(storage.key_value, RedisStore)


def test_build_auth_key_only_uses_static_verifier(settings):
    """Keys but no OAuth credentials → a plain StaticTokenVerifier."""
    settings = dataclasses.replace(settings, mcp_api_keys=['key-one', 'key-two'], **NO_OAUTH)

    provider = build_auth(settings)

    assert isinstance(provider, StaticTokenVerifier)
    assert not isinstance(provider, GitHubProvider)
    assert set(provider.tokens) == {'key-one', 'key-two'}
    assert {claims['client_id'] for claims in provider.tokens.values()} == {'api-key-1', 'api-key-2'}
    # Keys are tagged so the org gate can bypass them.
    assert all(claims[AUTH_MODE_CLAIM] == KEY_AUTH_MODE for claims in provider.tokens.values())


def test_build_auth_dual_when_oauth_and_keys(settings):
    """OAuth credentials AND keys → a DualAuthProvider (serves OAuth + accepts keys)."""
    settings = dataclasses.replace(settings, mcp_api_keys=['key-one'])

    provider = build_auth(settings)

    assert isinstance(provider, DualAuthProvider)
    assert isinstance(provider, GitHubProvider)  # inherits the full OAuth flow
    assert set(provider._static_tokens) == {'key-one'}


async def test_dual_provider_accepts_static_key(settings):
    """DualAuthProvider.verify_token accepts a configured key as a key-tagged client."""
    provider = build_auth(dataclasses.replace(settings, mcp_api_keys=['key-one']))

    token = await provider.verify_token('key-one')

    assert token is not None
    assert token.client_id == 'api-key-1'
    assert token.claims[AUTH_MODE_CLAIM] == KEY_AUTH_MODE
    assert await provider.verify_token('not-a-key') is None  # unknown → falls through to OAuth (invalid)


@patch('app.auth.derive_jwt_key')
def test_build_auth_redis_encryption_key_derives_from_signing_key(mock_derive, settings):
    """The at-rest encryption key is derived from the JWT signing key and storage salt."""
    mock_derive.return_value = Fernet.generate_key()
    settings = dataclasses.replace(settings, redis_url='redis://redis.example.test:6379/0')

    build_auth(settings)

    mock_derive.assert_called_once_with(
        high_entropy_material=settings.jwt_signing_key,
        salt='fastmcp-storage-encryption-key',
    )
