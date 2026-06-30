"""Entry point: build the auth-enabled FastMCP server and run it over HTTP.

This server defines its own documentation tools (it does not proxy another server).
Each tool fetches from the live source — Intercom Articles API for help docs, the
tc-api-docs GitHub repo for the API reference — through a short-TTL cache. Access is
gated to active members of a configured GitHub org via OrgMembershipMiddleware.
"""

import functools
import logging
from collections.abc import Awaitable, Callable

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from app.access import OrgMembershipMiddleware
from app.apidocs import ApiDocsClient, ApiDocsError
from app.auth import build_auth
from app.cache import TTLCache
from app.config import Settings, load_settings
from app.intercom import IntercomClient, IntercomError
from app.observability import configure_observability, tool_span


def _readable_errors(fn: Callable[..., Awaitable]) -> Callable[..., Awaitable]:
    """Wrap a tool in an observability span and clean up upstream errors.

    Upstream client failures become readable ToolErrors the model can relay; the
    span (a no-op unless Logfire is configured) records the call's timing and errors.
    """

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        with tool_span(getattr(fn, '__name__', 'tool')):
            try:
                return await fn(*args, **kwargs)
            except (IntercomError, ApiDocsError) as exc:
                raise ToolError(str(exc)) from exc

    return wrapper


def build_server(settings: Settings) -> FastMCP:
    """Build the auth-enabled docs server with its tools registered.

    Auth is key-based when ``MCP_API_KEYS`` is set (a valid Bearer key is the gate);
    otherwise GitHub OAuth is used and, when ``allowed_github_org`` is set, tool
    access is gated to active members of that org. In OAuth mode with no org set, the
    server refuses to start unless ``allow_ungated`` is explicitly enabled, so a
    missing org fails closed.

    Args:
        settings: Runtime settings.

    Returns:
        FastMCP: The configured server.
    """
    if not settings.key_auth_enabled and not settings.allowed_github_org and not settings.allow_ungated:
        raise RuntimeError(
            'No access gate configured: set MCP_API_KEYS for key-based auth, set '
            'ALLOWED_GITHUB_ORG to restrict OAuth access to an org, or set ALLOW_UNGATED=1 '
            'to explicitly allow any authenticated GitHub user. Refusing to start ungated by default.'
        )

    cache = TTLCache(settings.cache_ttl_seconds)
    intercom = IntercomClient(settings.help_sources, settings.intercom_api_base, cache, settings.search_result_limit)
    apidocs = ApiDocsClient(settings.tc_api_docs_repo, settings.tc_api_docs_ref, settings.github_token, cache)

    server = FastMCP(name='ProductDocs', auth=build_auth(settings))
    # Org-membership gating only applies to OAuth (it needs the user's GitHub token);
    # in key-auth mode the key itself is the gate.
    if not settings.key_auth_enabled and settings.allowed_github_org:
        server.add_middleware(OrgMembershipMiddleware(settings.allowed_github_org))

    @server.tool
    @_readable_errors
    async def list_help_articles(product: str | None = None) -> list[dict]:
        """List help-centre articles across the team's products as a lightweight catalogue.

        Returns one entry per article — product, id, title, description, url and
        collection — with no article bodies. Scan this to choose articles, then call
        get_help_article for the full text. This is the primary retrieval aid.

        Args:
            product: Restrict to one product ("tutorcruncher" or "bobbin"). Omit to
                span all configured products.
        """
        return await intercom.list_articles(product)

    @server.tool
    @_readable_errors
    async def search_help(query: str, product: str | None = None) -> list[dict]:
        """Search help-centre articles and return the best matches (no bodies).

        Runs Intercom search across the selected product(s), dedupes and ranks, and
        returns the top results as product, id, title, summary and url. Call
        get_help_article for the full body of a chosen result.

        Args:
            query: Free-text search phrase.
            product: Restrict to one product ("tutorcruncher" or "bobbin"). Omit to
                span all configured products.
        """
        return await intercom.search(query, product)

    @server.tool
    @_readable_errors
    async def get_help_article(product: str, article_id: str) -> dict:
        """Return one help-centre article's full cleaned body, with title and url.

        Args:
            product: The product the article belongs to ("tutorcruncher" or "bobbin");
                required so the server queries the correct Intercom workspace.
            article_id: The article id from list_help_articles or search_help.
        """
        return await intercom.get_article(product, article_id)

    @server.tool
    @_readable_errors
    async def list_api_sections() -> list[dict]:
        """List all TutorCruncher API reference sections (id, title, kind).

        Scan this to choose a section, then call get_api_section for its full content.
        """
        return await apidocs.list_sections()

    @server.tool
    @_readable_errors
    async def search_api_docs(query: str) -> list[dict]:
        """Search the TutorCruncher API reference by keyword.

        Matches section and subsection (endpoint) titles, returning whole matching
        sections as id, title, kind and their subsection titles.

        Args:
            query: Free-text search phrase (e.g. "contractor fields", "create invoice").
        """
        return await apidocs.search(query)

    @server.tool
    @_readable_errors
    async def get_api_section(section_id: str) -> dict:
        """Return one whole API reference section assembled to markdown.

        Includes every subsection: object/field definitions, endpoints (method and
        path), query parameters, and request/response examples.

        Args:
            section_id: A section id from list_api_sections or search_api_docs
                (e.g. "clients", "contractors").
        """
        return await apidocs.get_section(section_id)

    return server


def main() -> None:
    """Load settings, build the server and run it over Streamable HTTP."""
    logging.basicConfig(level=logging.INFO)
    configure_observability()
    settings = load_settings()
    server = build_server(settings)
    server.run(transport='http', host='0.0.0.0', port=settings.port)


if __name__ == '__main__':
    main()
