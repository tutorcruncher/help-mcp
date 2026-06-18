"""Multi-product Intercom Articles client.

One client serves every configured help-centre workspace. Each public method takes
an optional ``product`` filter; unset spans all configured products. Results always
carry their ``product`` so Claude keeps sources distinct and attributes answers
correctly.

The Articles API host is the same for every workspace — only the per-workspace
access token differs (TutorCruncher and Bobbin are separate Intercom workspaces).
"""

import asyncio
import logging
import re

import httpx
from markdownify import markdownify

from app.cache import TTLCache
from app.config import HelpSource

logger = logging.getLogger('tc_help_mcp.intercom')

INTERCOM_VERSION = '2.11'
PER_PAGE = 250
MAX_PAGES = 200
MAX_RETRIES = 2

# Substrings that mark repeated help-centre template boilerplate / chrome appended
# to article bodies. Any line containing one is dropped during cleaning. Verify
# against real articles and extend as needed — keep this conservative so genuine
# content is never removed.
BOILERPLATE_MARKERS = (
    'we run on intercom',
    'powered by intercom',
    'licensed under the apache license',
    'apache license, version 2.0',
)


class IntercomError(RuntimeError):
    """Raised when the Intercom API cannot be reached or returns an error."""


def strip_boilerplate(text: str) -> str:
    """Drop boilerplate lines and collapse runs of blank lines."""
    kept: list[str] = []
    for line in text.splitlines():
        if any(marker in line.lower() for marker in BOILERPLATE_MARKERS):
            continue
        kept.append(line.rstrip())
    collapsed = re.sub(r'\n{3,}', '\n\n', '\n'.join(kept))
    return collapsed.strip()


def clean_html(html: str | None) -> str:
    """Convert an Intercom article body (HTML) to clean markdown.

    Args:
        html: Raw article body HTML, or None for an empty article.

    Returns:
        Boilerplate-stripped markdown preserving headings, lists and code blocks.
    """
    if not html:
        return ''
    markdown = markdownify(html, heading_style='ATX', bullets='-')
    return strip_boilerplate(markdown)


class IntercomClient:
    """Fetch and clean help-centre articles across one or more Intercom workspaces."""

    def __init__(
        self,
        sources: list[HelpSource],
        api_base: str,
        cache: TTLCache,
        search_limit: int,
        timeout: float = 20.0,
    ) -> None:
        self.api_base = api_base
        self.cache = cache
        self.search_limit = search_limit
        self.timeout = timeout
        self._sources = {source.product: source for source in sources}

    def _resolve(self, product: str | None) -> list[HelpSource]:
        """Return the sources to query, validating an explicit product filter."""
        if product is None:
            return list(self._sources.values())
        source = self._sources.get(product)
        if source is None:
            configured = ', '.join(self._sources) or 'none'
            raise IntercomError(f"Unknown product '{product}'. Configured products: {configured}.")
        return [source]

    def _headers(self, source: HelpSource) -> dict[str, str]:
        """Return Intercom auth/version headers for a workspace."""
        return {
            'Authorization': f'Bearer {source.token}',
            'Accept': 'application/json',
            'Intercom-Version': INTERCOM_VERSION,
        }

    async def _get_json(self, client: httpx.AsyncClient, source: HelpSource, path: str, params: dict | None = None):
        """GET a JSON payload, retrying transient 429/5xx responses with backoff."""
        url = f'{self.api_base}{path}'
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = await client.get(url, params=params, headers=self._headers(source))
            except httpx.HTTPError as exc:
                raise IntercomError(f'Intercom request to {path} failed: {exc}') from exc
            if response.status_code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                delay = float(response.headers.get('Retry-After', 2**attempt))
                logger.warning('Intercom %s on %s; retrying in %ss', response.status_code, path, delay)
                await asyncio.sleep(delay)
                continue
            if response.status_code >= 400:
                raise IntercomError(f'Intercom returned {response.status_code} for {path}.')
            return response.json()
        raise IntercomError(f'Intercom remained unavailable for {path} after retries.')

    async def _fetch_all_articles(self, source: HelpSource) -> list[dict]:
        """Page through a workspace's Articles API fully (cached under the TTL)."""

        async def loader() -> list[dict]:
            articles: list[dict] = []
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                for page in range(1, MAX_PAGES + 1):
                    payload = await self._get_json(client, source, '/articles', {'page': page, 'per_page': PER_PAGE})
                    data = payload.get('data') or []
                    articles.extend(data)
                    total_pages = (payload.get('pages') or {}).get('total_pages')
                    if not data or (total_pages is not None and page >= total_pages):
                        break
            return articles

        return await self.cache.get_or_load(('articles', source.product), loader)

    async def _collection_names(self, source: HelpSource) -> dict[str, str]:
        """Map collection id -> name for a workspace (cached, paged).

        Intercom's Help Center exposes collections (including nested ones) via
        ``/help_center/collections``; there is no separate sections resource in the
        current API. Articles with no parent collection are simply left unmapped.
        """

        async def loader() -> dict[str, str]:
            names: dict[str, str] = {}
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                for page in range(1, MAX_PAGES + 1):
                    payload = await self._get_json(
                        client, source, '/help_center/collections', {'page': page, 'per_page': PER_PAGE}
                    )
                    data = payload.get('data') or []
                    for item in data:
                        if item.get('id') is not None and item.get('name'):
                            names[str(item['id'])] = item['name']
                    total_pages = (payload.get('pages') or {}).get('total_pages')
                    if not data or (total_pages is not None and page >= total_pages):
                        break
            return names

        return await self.cache.get_or_load(('collections', source.product), loader)

    async def _catalogue_for(self, source: HelpSource) -> list[dict]:
        """Build the lightweight catalogue for one workspace."""
        articles, collections = await asyncio.gather(self._fetch_all_articles(source), self._collection_names(source))
        catalogue = []
        for article in articles:
            parent = article.get('parent_id')
            catalogue.append(
                {
                    'product': source.product,
                    'id': str(article.get('id')),
                    'title': article.get('title') or '',
                    'description': article.get('description') or '',
                    'url': article.get('url') or '',
                    'collection': collections.get(str(parent)) if parent is not None else None,
                }
            )
        return catalogue

    async def list_articles(self, product: str | None = None) -> list[dict]:
        """Return the catalogue across the selected product(s) (no article bodies)."""
        sources = self._resolve(product)
        per_source = await asyncio.gather(*(self._catalogue_for(source) for source in sources))
        return [entry for catalogue in per_source for entry in catalogue]

    @staticmethod
    def _search_articles(payload: dict) -> list[dict]:
        """Extract article records from a /articles/search payload (shape-tolerant)."""
        data = payload.get('data')
        if isinstance(data, dict):
            return data.get('articles') or []
        if isinstance(data, list):
            return data
        return []

    async def _search_source(self, source: HelpSource, query: str) -> list[dict]:
        """Run Intercom phrase search for one workspace, labelling each hit."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            payload = await self._get_json(client, source, '/articles/search', {'phrase': query, 'state': 'published'})
        results = []
        for article in self._search_articles(payload):
            results.append(
                {
                    'product': source.product,
                    'id': str(article.get('id')),
                    'title': article.get('title') or '',
                    'summary': article.get('description') or '',
                    'url': article.get('url') or '',
                }
            )
        return results

    def _rank(self, items: list[dict], query: str) -> list[dict]:
        """Dedupe by (product, id) and rank by title match, then source order."""
        terms = [term for term in query.lower().split() if term]
        best: dict[tuple[str, str], tuple[int, dict]] = {}
        for position, item in enumerate(items):
            title_hits = sum(1 for term in terms if term in item['title'].lower())
            score = title_hits * 100 - position
            key = (item['product'], item['id'])
            existing = best.get(key)
            if existing is None or score > existing[0]:
                best[key] = (score, item)
        ranked = sorted(best.values(), key=lambda entry: entry[0], reverse=True)
        return [item for _, item in ranked][: self.search_limit]

    async def search(self, query: str, product: str | None = None) -> list[dict]:
        """Search across the selected product(s); return ranked, deduped top results."""
        sources = self._resolve(product)
        per_source = await asyncio.gather(*(self._search_source(source, query) for source in sources))
        merged = [item for results in per_source for item in results]
        return self._rank(merged, query)

    async def get_article(self, product: str, article_id: str) -> dict:
        """Return one article's full cleaned body plus product, title and url."""
        sources = self._resolve(product)
        source = sources[0]
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            article = await self._get_json(client, source, f'/articles/{article_id}')
        return {
            'product': source.product,
            'id': str(article.get('id')),
            'title': article.get('title') or '',
            'url': article.get('url') or '',
            'body': clean_html(article.get('body')),
        }
