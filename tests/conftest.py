import pytest

from app.config import HelpSource, Settings


@pytest.fixture
def help_sources() -> list[HelpSource]:
    """Two configured Intercom workspaces (TutorCruncher + Bobbin)."""
    return [
        HelpSource(product='tutorcruncher', token='tc-token', help_centre_base='https://help.tutorcruncher.com'),
        HelpSource(
            product='bobbin', token='bobbin-token', help_centre_base='https://intercom.help/bobbin-355e87537201'
        ),
    ]


@pytest.fixture
def settings(help_sources) -> Settings:
    """A complete Settings instance for tests, with no external dependencies."""
    return Settings(
        github_client_id='Ov23li_test',
        github_client_secret='secret_test',
        base_url='https://example.test',
        github_scopes=['read:org', 'read:user'],
        jwt_signing_key='test-signing-key',
        allowed_github_org='tutorcruncher',
        allow_ungated=False,
        allowed_redirect_uris=['https://claude.ai/api/mcp/auth_callback'],
        redis_url=None,
        intercom_api_base='https://api.intercom.io',
        help_sources=help_sources,
        tc_api_docs_repo='tutorcruncher/tc-api-docs',
        tc_api_docs_ref='master',
        github_token=None,
        cache_ttl_seconds=300.0,
        search_result_limit=8,
        port=8000,
    )
