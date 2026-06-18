"""Live integration tests against the real upstreams.

These are skipped by default. They hit the network, so they are guarded:
 - API-docs tests run when ``RUN_INTEGRATION=1`` (the tc-api-docs repo is public).
 - Intercom tests additionally require ``INTERCOM_TOKEN_TUTORCRUNCHER``.

Run with:  RUN_INTEGRATION=1 uv run pytest -n0 tests/test_integration.py
"""

import os

import pytest

from app.apidocs import ApiDocsClient
from app.cache import TTLCache
from app.config import HelpSource
from app.intercom import IntercomClient

run_integration = pytest.mark.skipif(
    os.environ.get('RUN_INTEGRATION') != '1',
    reason='set RUN_INTEGRATION=1 to run live integration tests',
)
needs_intercom = pytest.mark.skipif(
    not os.environ.get('INTERCOM_TOKEN_TUTORCRUNCHER'),
    reason='set INTERCOM_TOKEN_TUTORCRUNCHER to run Intercom integration tests',
)


@run_integration
async def test_live_api_section_has_content():
    """A known API section assembles to non-empty markdown with its endpoints."""
    client = ApiDocsClient('tutorcruncher/tc-api-docs', 'master', os.environ.get('GITHUB_TOKEN'), TTLCache(ttl=300.0))

    sections = await client.list_sections()
    assert any(section['id'] == 'clients' for section in sections)

    section = await client.get_section('clients')
    assert section['title'] == 'Clients'
    assert '/api/clients/' in section['content']


@run_integration
@needs_intercom
async def test_live_help_article_has_content():
    """The catalogue lists articles and a fetched article has a cleaned body."""
    source = HelpSource('tutorcruncher', os.environ['INTERCOM_TOKEN_TUTORCRUNCHER'], 'https://help.tutorcruncher.com')
    client = IntercomClient([source], 'https://api.intercom.io', TTLCache(ttl=300.0), search_limit=8)

    catalogue = await client.list_articles('tutorcruncher')
    assert catalogue

    article = await client.get_article('tutorcruncher', catalogue[0]['id'])
    assert article['title']
    assert article['body']
