"""Entry point: build the auth-enabled FastMCP server and run it over HTTP.

This server defines its own documentation tools (it does not proxy another server).
Each tool fetches from the live source — Intercom Articles API for help docs, the
tc-api-docs GitHub repo for the API reference — through a short-TTL cache. Access is
gated to active members of a configured GitHub org via OrgMembershipMiddleware.
"""

import asyncio
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
from app.images import ImageStore, ImageStoreError
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
            except (IntercomError, ApiDocsError, ImageStoreError) as exc:
                raise ToolError(str(exc)) from exc

    return wrapper


def build_server(settings: Settings) -> FastMCP:
    """Build the auth-enabled docs server with its tools registered.

    Auth is driven by configuration and OAuth + keys can run together: with
    ``MCP_API_KEYS`` a valid Bearer key is the gate; with GitHub OAuth credentials the
    OAuth flow is served and, when ``allowed_github_org`` is set, OAuth users are gated
    to active members of that org (key requests bypass the org gate inside the
    middleware). In OAuth mode with no org set, the server refuses to start unless
    ``allow_ungated`` is explicitly enabled, so a missing org fails closed.

    Args:
        settings: Runtime settings.

    Returns:
        FastMCP: The configured server.
    """
    if not settings.oauth_enabled and not settings.mcp_api_keys:
        raise RuntimeError(
            'No auth configured: set the GitHub OAuth credentials (GITHUB_OAUTH_CLIENT_ID, '
            'GITHUB_OAUTH_CLIENT_SECRET, BASE_URL, JWT_SIGNING_KEY) for OAuth, and/or set '
            'MCP_API_KEYS for key-based auth.'
        )
    if settings.oauth_enabled and not settings.allowed_github_org and not settings.allow_ungated:
        raise RuntimeError(
            'No access gate configured for OAuth users: set ALLOWED_GITHUB_ORG to restrict '
            'OAuth access to an org, or set ALLOW_UNGATED=1 to explicitly allow any authenticated '
            'GitHub user. Refusing to start ungated by default.'
        )

    cache = TTLCache(settings.cache_ttl_seconds)
    intercom = IntercomClient(settings.help_sources, settings.intercom_api_base, cache, settings.search_result_limit)
    apidocs = ApiDocsClient(settings.tc_api_docs_repo, settings.tc_api_docs_ref, settings.github_token, cache)
    images = ImageStore(settings.image_store)

    server = FastMCP(name='ProductDocs', auth=build_auth(settings))
    # Org-membership gating applies to OAuth users (it needs the user's GitHub token);
    # key-authenticated requests carry no GitHub identity and bypass it inside the
    # middleware, the key itself being their gate.
    if settings.oauth_enabled and settings.allowed_github_org:
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

    # ─── Write tools (Intercom Articles, draft-only) ──────────────────────────
    # Always registered, but every write is forced to Intercom state="draft": this
    # server never publishes live. A human reviews and publishes the draft in Intercom.

    @server.tool
    @_readable_errors
    async def get_help_article_raw(product: str, article_id: str) -> dict:
        """Return one article's RAW body HTML plus a parsed list of its images.

        Use this (not get_help_article, which returns cleaned markdown) when you need
        to edit the article: it preserves the exact Intercom HTML and lists every
        image with its src, alt, filename, nearest heading and surrounding text — the
        context needed to decide which app page each screenshot shows.

        Args:
            product: The product the article belongs to ("tutorcruncher" or "bobbin").
            article_id: The article id from list_help_articles or search_help.
        """
        return await intercom.get_article_raw(product, article_id)

    @server.tool
    @_readable_errors
    async def update_help_article(
        product: str, article_id: str, body_html: str | None = None, title: str | None = None
    ) -> dict:
        """Update an article's body and/or title, saving it as a DRAFT (never live).

        The change is saved with Intercom state="draft"; a human must publish it in
        the Intercom UI. Pass full replacement HTML in body_html. To swap a single
        image, prefer replace_help_article_image.

        Args:
            product: The product the article belongs to ("tutorcruncher" or "bobbin").
            article_id: The article id to update.
            body_html: Full replacement body HTML (Intercom's allowed subset). Omit to leave unchanged.
            title: New title. Omit to leave unchanged.
        """
        return await intercom.update_article(product, article_id, title=title, body_html=body_html)

    @server.tool
    @_readable_errors
    async def create_help_article(product: str, title: str, body_html: str, parent_id: str | None = None) -> dict:
        """Create a new help article as a DRAFT (never published live).

        Args:
            product: The product the article belongs to ("tutorcruncher" or "bobbin").
            title: Article title.
            body_html: Body HTML (Intercom's allowed subset).
            parent_id: Optional collection/section id to file the article under.
        """
        return await intercom.create_article(product, title, body_html, parent_id=parent_id)

    @server.tool
    @_readable_errors
    async def replace_help_article_image(product: str, article_id: str, old_src: str, new_url: str) -> dict:
        """Swap a single image URL in an article's body, saving it as a DRAFT.

        Replaces every occurrence of old_src with new_url in the raw body and saves a
        draft — a surgical string swap that preserves the rest of the HTML exactly.
        Errors if old_src is not present. Get old_src from get_help_article_raw and
        new_url (the public_url) from request_help_image_upload.

        Args:
            product: The product the article belongs to ("tutorcruncher" or "bobbin").
            article_id: The article id to edit.
            old_src: The existing image src (full URL) to replace.
            new_url: The new image URL to insert.
        """
        return await intercom.replace_article_image(product, article_id, old_src, new_url)

    @server.tool
    @_readable_errors
    async def request_help_image_upload(product: str, filename: str) -> dict:
        """Get a short-lived URL to upload a local screenshot to the image store.

        Intercom has no image-upload API, so a screenshot is hosted externally and
        embedded by URL. This server is remote and cannot read your local files, so
        it returns a presigned PUT URL: upload the local file's bytes directly to
        `put_url` (e.g. `curl -sS -X PUT --upload-file <local_path> "<put_url>"`),
        then use `public_url` as new_url in replace_help_article_image or as an
        <img src> in an article body. Do NOT read the image into context.

        Returns {"put_url": "...", "public_url": "..."}.

        Args:
            product: The product the image belongs to ("tutorcruncher" or "bobbin");
                used as the bucket sub-folder so each product's screenshots are separate.
            filename: The image filename (used for the stored object's name + extension),
                e.g. "tutors-add-dialog.png".
        """
        return await asyncio.to_thread(images.presign_put, filename, product)

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
