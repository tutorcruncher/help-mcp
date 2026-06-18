"""GitHub OAuth authentication for the MCP server.

Uses FastMCP's GitHubProvider, which makes this server act as an OAuth 2.1
resource/authorization server to Claude's custom connector while proxying the
authorization flow to a GitHub OAuth App. After a user authenticates, the
upstream GitHub access token is retrievable via get_access_token().token —
used by OrgMembershipMiddleware to verify org membership.
"""

from fastmcp.server.auth.providers.github import GitHubProvider

from app.config import Settings


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
    )
