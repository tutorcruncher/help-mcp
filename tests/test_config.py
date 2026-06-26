import pytest

from app.config import HelpSource, load_settings

REQUIRED = {
    'GITHUB_OAUTH_CLIENT_ID': 'Ov23li_env',
    'GITHUB_OAUTH_CLIENT_SECRET': 'secret_env',
    'BASE_URL': 'https://app.example.test/',
    'JWT_SIGNING_KEY': 'k',
}


def _set_required(monkeypatch):
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)


def test_load_settings_reads_environment(monkeypatch):
    """load_settings parses every field, building help sources from token env vars."""
    _set_required(monkeypatch)
    monkeypatch.setenv('GITHUB_SCOPES', 'read:org')
    monkeypatch.setenv('ALLOWED_GITHUB_ORG', 'tutorcruncher')
    monkeypatch.setenv('ALLOW_UNGATED', '1')
    monkeypatch.setenv('ALLOWED_REDIRECT_URIS', 'https://claude.ai/api/mcp/auth_callback https://example.test/cb')
    monkeypatch.setenv('REDIS_URL', 'rediss://user:pass@redis.example.test:6380/0')
    monkeypatch.setenv('INTERCOM_API_BASE', 'https://api.intercom.io/')
    monkeypatch.setenv('INTERCOM_TOKEN_TUTORCRUNCHER', 'tc-tok')
    monkeypatch.setenv('INTERCOM_TOKEN_BOBBIN', 'bobbin-tok')
    monkeypatch.setenv('TC_API_DOCS_REPO', 'tutorcruncher/tc-api-docs')
    monkeypatch.setenv('TC_API_DOCS_REF', 'main')
    monkeypatch.setenv('GITHUB_TOKEN', 'ghp_x')
    monkeypatch.setenv('CACHE_TTL_SECONDS', '120')
    monkeypatch.setenv('SEARCH_RESULT_LIMIT', '5')
    monkeypatch.setenv('PORT', '1234')

    settings = load_settings()

    assert settings.github_client_id == 'Ov23li_env'
    assert settings.github_client_secret == 'secret_env'
    assert settings.base_url == 'https://app.example.test'
    assert settings.github_scopes == ['read:org']
    assert settings.jwt_signing_key == 'k'
    assert settings.allowed_github_org == 'tutorcruncher'
    assert settings.allow_ungated is True
    assert settings.allowed_redirect_uris == [
        'https://claude.ai/api/mcp/auth_callback',
        'https://example.test/cb',
    ]
    assert settings.redis_url == 'rediss://user:pass@redis.example.test:6380/0'
    assert settings.intercom_api_base == 'https://api.intercom.io'
    assert settings.help_sources == [
        HelpSource('tutorcruncher', 'tc-tok', 'https://help.tutorcruncher.com'),
        HelpSource('bobbin', 'bobbin-tok', 'https://intercom.help/bobbin-355e87537201'),
    ]
    assert settings.tc_api_docs_repo == 'tutorcruncher/tc-api-docs'
    assert settings.tc_api_docs_ref == 'main'
    assert settings.github_token == 'ghp_x'
    assert settings.cache_ttl_seconds == 120.0
    assert settings.search_result_limit == 5
    assert settings.port == 1234


def test_help_sources_skip_products_without_tokens(monkeypatch):
    """A product whose token is unset is skipped; only configured ones load."""
    _set_required(monkeypatch)
    monkeypatch.setenv('INTERCOM_TOKEN_TUTORCRUNCHER', 'tc-tok')
    monkeypatch.delenv('INTERCOM_TOKEN_BOBBIN', raising=False)

    settings = load_settings()

    assert settings.help_sources == [HelpSource('tutorcruncher', 'tc-tok', 'https://help.tutorcruncher.com')]
    assert settings.help_source('tutorcruncher') == settings.help_sources[0]
    assert settings.help_source('bobbin') is None


def test_defaults_fail_closed(monkeypatch):
    """Access defaults to a gated, fail-closed posture with sensible defaults."""
    _set_required(monkeypatch)
    for var in ('ALLOWED_GITHUB_ORG', 'ALLOW_UNGATED', 'ALLOWED_REDIRECT_URIS', 'GITHUB_TOKEN', 'REDIS_URL'):
        monkeypatch.delenv(var, raising=False)

    settings = load_settings()

    assert settings.allowed_github_org is None
    assert settings.allow_ungated is False
    assert settings.allowed_redirect_uris == ['https://claude.ai/api/mcp/auth_callback']
    assert settings.redis_url is None
    assert settings.github_scopes == ['read:org', 'read:user']
    assert settings.intercom_api_base == 'https://api.intercom.io'
    assert settings.github_token is None
    assert settings.cache_ttl_seconds == 300.0
    assert settings.search_result_limit == 8
    assert settings.port == 8000


def test_load_settings_reads_author_ids_and_image_store(monkeypatch):
    """Author ids attach to their workspace and IMAGE_STORE_* builds the image config."""
    _set_required(monkeypatch)
    monkeypatch.setenv('INTERCOM_TOKEN_TUTORCRUNCHER', 'tc-tok')
    monkeypatch.setenv('INTERCOM_AUTHOR_ID_TUTORCRUNCHER', '42')
    monkeypatch.delenv('INTERCOM_TOKEN_BOBBIN', raising=False)
    monkeypatch.setenv('IMAGE_STORE_BUCKET', 'shots-bucket')
    monkeypatch.setenv('IMAGE_STORE_PUBLIC_BASE', 'https://cdn.example.com/')
    monkeypatch.setenv('IMAGE_STORE_REGION', 'eu-west-1')
    monkeypatch.setenv('IMAGE_STORE_KEY_PREFIX', '/help-shots/')

    settings = load_settings()

    assert settings.help_sources == [HelpSource('tutorcruncher', 'tc-tok', 'https://help.tutorcruncher.com', 42)]
    assert settings.image_store.bucket == 'shots-bucket'
    assert settings.image_store.public_base == 'https://cdn.example.com'  # trailing slash stripped
    assert settings.image_store.region == 'eu-west-1'
    assert settings.image_store.key_prefix == 'help-shots'  # surrounding slashes stripped
    assert settings.image_store.configured is True


def test_image_store_unconfigured_by_default(monkeypatch):
    """With no IMAGE_STORE_* vars the store is present but not configured."""
    _set_required(monkeypatch)
    for var in ('IMAGE_STORE_BUCKET', 'IMAGE_STORE_PUBLIC_BASE', 'IMAGE_STORE_REGION', 'IMAGE_STORE_KEY_PREFIX'):
        monkeypatch.delenv(var, raising=False)

    settings = load_settings()

    assert settings.image_store.configured is False
    assert settings.image_store.bucket is None


def test_load_settings_missing_required_raises(monkeypatch):
    """A missing required variable raises a clear error naming the variable."""
    monkeypatch.delenv('JWT_SIGNING_KEY', raising=False)
    for name in ('GITHUB_OAUTH_CLIENT_ID', 'GITHUB_OAUTH_CLIENT_SECRET', 'BASE_URL'):
        monkeypatch.setenv(name, 'x')

    with pytest.raises(RuntimeError, match='JWT_SIGNING_KEY'):
        load_settings()
