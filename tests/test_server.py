import dataclasses

import httpx
import pytest
from fastmcp.exceptions import ToolError
from fastmcp.tools import FunctionTool

from app.server import build_server

API_YML = """
endpoint_sections:
  - title: Clients
    id: clients
    layout: /clients/clients.yml
"""


class FakeResponse:
    def __init__(self, status_code=200, text=''):
        self.status_code = status_code
        self.text = text
        self.headers = {}


class FakeAsyncClient:
    def __init__(self, handler):
        self._handler = handler

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, **kwargs):
        return self._handler(url)


EXPECTED_TOOLS = {
    'list_help_articles',
    'search_help',
    'get_help_article',
    'list_api_sections',
    'search_api_docs',
    'get_api_section',
    'get_help_article_raw',
    'update_help_article',
    'create_help_article',
    'replace_help_article_image',
    'request_help_image_upload',
}


def test_build_server_refuses_when_ungated(settings):
    """With no org gate and no explicit opt-in, the server refuses to start."""
    ungated = dataclasses.replace(settings, allowed_github_org=None, allow_ungated=False)

    with pytest.raises(RuntimeError, match='No access gate configured'):
        build_server(ungated)


def test_build_server_builds_with_org_gate(settings):
    """An org-gated configuration builds the docs server."""
    server = build_server(settings)

    assert server.name == 'ProductDocs'


def test_build_server_allows_explicit_ungated_optin(settings):
    """ALLOW_UNGATED opt-in lets the server start without an org gate."""
    ungated = dataclasses.replace(settings, allowed_github_org=None, allow_ungated=True)

    server = build_server(ungated)

    assert server.name == 'ProductDocs'


def test_build_server_key_auth_is_its_own_gate(settings):
    """Key-based auth lets the server start with no org gate / opt-in, using a key verifier."""
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

    key_only = dataclasses.replace(settings, allowed_github_org=None, allow_ungated=False, mcp_api_keys=['secret-key'])

    server = build_server(key_only)

    assert server.name == 'ProductDocs'
    assert isinstance(server.auth, StaticTokenVerifier)


async def test_build_server_key_auth_skips_org_middleware(settings):
    """In key mode the GitHub org-membership middleware is not added (no GitHub identity)."""
    from app.access import OrgMembershipMiddleware

    key_mode = dataclasses.replace(settings, mcp_api_keys=['secret-key'])
    server = build_server(key_mode)

    assert not any(isinstance(m, OrgMembershipMiddleware) for m in server.middleware)
    # Tools are still registered as normal.
    assert {tool.name for tool in await server._list_tools()} == EXPECTED_TOOLS


async def test_build_server_registers_all_tools(settings):
    """All documentation tools plus the draft-only write tools are registered."""
    server = build_server(settings)

    tools = await server._list_tools()

    assert {tool.name for tool in tools} == EXPECTED_TOOLS


async def test_api_section_tool_runs_end_to_end(settings, monkeypatch):
    """A registered tool drives its client through to the live-fetch boundary."""
    monkeypatch.setattr(
        'app.apidocs.httpx.AsyncClient',
        lambda *a, **k: FakeAsyncClient(lambda url: FakeResponse(text=API_YML)),
    )
    server = build_server(settings)
    tool = await server.get_tool('list_api_sections')

    assert isinstance(tool, FunctionTool)
    assert await tool.fn() == [{'id': 'clients', 'title': 'Clients', 'kind': 'endpoint'}]


async def test_tool_maps_upstream_errors_to_tool_error(settings, monkeypatch):
    """Upstream failures surface to the model as a clean ToolError, not a stack trace."""

    def boom(url):
        raise httpx.ConnectError('connection refused')

    monkeypatch.setattr('app.intercom.httpx.AsyncClient', lambda *a, **k: FakeAsyncClient(boom))
    server = build_server(settings)
    tool = await server.get_tool('list_help_articles')

    assert isinstance(tool, FunctionTool)
    with pytest.raises(ToolError, match='Intercom request'):
        await tool.fn('tutorcruncher')
