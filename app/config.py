"""Environment-backed configuration for the product-docs MCP server.

Help sources are modelled as a list of per-product entries so that adding a new
product later is config-only: one line in ``KNOWN_HELP_PRODUCTS`` plus an
``INTERCOM_TOKEN_<PRODUCT>`` environment variable. Products whose token is unset
are skipped, so the server runs with whatever workspaces are configured.
"""

import os
from dataclasses import dataclass

# Known help-centre products: (product, help_centre_base). The live source list is
# built from these by pairing each with its INTERCOM_TOKEN_<PRODUCT> env var. Add a
# product here and set its token to extend the server — no tool changes required.
KNOWN_HELP_PRODUCTS: list[tuple[str, str]] = [
    ('tutorcruncher', 'https://help.tutorcruncher.com'),
    ('bobbin', 'https://intercom.help/bobbin-355e87537201'),
]


def _require(name: str) -> str:
    """Return a required environment variable or raise a clear error."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f'Missing required environment variable: {name}')
    return value


@dataclass(frozen=True)
class HelpSource:
    """One Intercom help-centre workspace.

    Attributes:
        product: Stable product identifier (e.g. ``tutorcruncher``), surfaced on
            every result so Claude attributes answers to the right product.
        token: Intercom access token for this workspace (never logged).
        help_centre_base: Public help-centre base URL, used for display only.
    """

    product: str
    token: str
    help_centre_base: str


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from the environment.

    Attributes:
        github_client_id: GitHub OAuth App client id.
        github_client_secret: GitHub OAuth App client secret.
        base_url: Public HTTPS base URL of this server (OAuth callback root).
        github_scopes: GitHub OAuth scopes required to verify org membership.
        jwt_signing_key: Signing key for FastMCP-issued JWTs.
        allowed_github_org: If set, only active members of this GitHub org may use
            the tools.
        allow_ungated: Explicit opt-in to run WITHOUT an org gate. When false
            (default) and no org is set, the server refuses to start so a missing
            ALLOWED_GITHUB_ORG fails closed rather than exposing tools to all.
        allowed_redirect_uris: OAuth client redirect URIs permitted during dynamic
            client registration / authorization.
        redis_url: Redis connection URL for persisting OAuth state across restarts.
            When set, OAuth client registrations and tokens survive process restarts
            (essential on hosts with an ephemeral filesystem, e.g. Heroku dyno
            cycling). When unset, FastMCP falls back to its default on-disk store.
        intercom_api_base: Intercom API host (same for every workspace).
        help_sources: Configured Intercom help-centre workspaces (one per product).
        tc_api_docs_repo: owner/name of the API-docs GitHub repo.
        tc_api_docs_ref: Git ref of the API-docs repo to read.
        github_token: Optional token to raise raw-content fetch rate limits.
        cache_ttl_seconds: In-memory cache TTL — latency/rate-limit protection only.
        search_result_limit: Max results returned by search_help.
        port: Port the MCP server binds to.
    """

    github_client_id: str
    github_client_secret: str
    base_url: str
    github_scopes: list[str]
    jwt_signing_key: str
    allowed_github_org: str | None
    allow_ungated: bool
    allowed_redirect_uris: list[str]
    redis_url: str | None
    intercom_api_base: str
    help_sources: list[HelpSource]
    tc_api_docs_repo: str
    tc_api_docs_ref: str
    github_token: str | None
    cache_ttl_seconds: float
    search_result_limit: int
    port: int

    def help_source(self, product: str) -> HelpSource | None:
        """Return the configured help source for a product, or None if absent."""
        for source in self.help_sources:
            if source.product == product:
                return source
        return None


def _load_help_sources() -> list[HelpSource]:
    """Build the live help-source list from known products + their token env vars."""
    sources: list[HelpSource] = []
    for product, base in KNOWN_HELP_PRODUCTS:
        token = os.environ.get(f'INTERCOM_TOKEN_{product.upper()}')
        if token:
            sources.append(HelpSource(product=product, token=token, help_centre_base=base))
    return sources


def load_settings() -> Settings:
    """Build a Settings instance from the current environment."""
    return Settings(
        github_client_id=_require('GITHUB_OAUTH_CLIENT_ID'),
        github_client_secret=_require('GITHUB_OAUTH_CLIENT_SECRET'),
        base_url=_require('BASE_URL').rstrip('/'),
        github_scopes=os.environ.get('GITHUB_SCOPES', 'read:org read:user').split(),
        jwt_signing_key=_require('JWT_SIGNING_KEY'),
        allowed_github_org=os.environ.get('ALLOWED_GITHUB_ORG') or None,
        allow_ungated=os.environ.get('ALLOW_UNGATED', '0') == '1',
        allowed_redirect_uris=os.environ.get(
            'ALLOWED_REDIRECT_URIS', 'https://claude.ai/api/mcp/auth_callback'
        ).split(),
        redis_url=os.environ.get('REDIS_URL') or None,
        intercom_api_base=os.environ.get('INTERCOM_API_BASE', 'https://api.intercom.io').rstrip('/'),
        help_sources=_load_help_sources(),
        tc_api_docs_repo=os.environ.get('TC_API_DOCS_REPO', 'tutorcruncher/tc-api-docs'),
        tc_api_docs_ref=os.environ.get('TC_API_DOCS_REF', 'master'),
        github_token=os.environ.get('GITHUB_TOKEN') or None,
        cache_ttl_seconds=float(os.environ.get('CACHE_TTL_SECONDS', '300')),
        search_result_limit=int(os.environ.get('SEARCH_RESULT_LIMIT', '8')),
        port=int(os.environ.get('PORT', '8000')),
    )
