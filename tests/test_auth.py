import dataclasses
from unittest.mock import patch

from cryptography.fernet import Fernet
from fastmcp.server.auth.providers.github import GitHubProvider
from key_value.aio.stores.redis import RedisStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

from app.auth import build_auth


def test_build_auth_without_redis_uses_default_store(settings):
    """With no Redis configured, the provider falls back to FastMCP's on-disk store."""
    provider = build_auth(settings)
    storage = provider._client_storage

    assert isinstance(provider, GitHubProvider)
    assert isinstance(storage, FernetEncryptionWrapper)
    assert not isinstance(storage.key_value, RedisStore)


def test_build_auth_with_redis_persists_encrypted_state(settings):
    """A configured Redis URL wires an encrypted Redis-backed OAuth state store."""
    settings = dataclasses.replace(settings, redis_url='redis://redis.example.test:6379/0')

    provider = build_auth(settings)
    storage = provider._client_storage

    assert isinstance(storage, FernetEncryptionWrapper)
    assert isinstance(storage.key_value, RedisStore)


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
