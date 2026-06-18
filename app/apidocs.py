"""Client for the TutorCruncher API reference (tc-api-docs GitHub repo).

The repo is an *index + content files* layout (Task 0, "Outcome B"):

    pages/api.yml          -> info_sections[] + endpoint_sections[]  (each {title, id, layout})
    pages/<sec>/<sec>.yml  -> sections[]  (subsections referencing separate files)
        description -> .md   attributes/filters -> .yml   response -> .json   code -> .py

Paths inside the YAML are repo-absolute under ``pages/`` (e.g. ``/clients/clients.yml``
-> ``pages/clients/clients.yml``). ``get_section`` resolves a whole section, fans out
over every subsection's referenced files (cached, concurrency-capped) and assembles one
clean markdown document.
"""

import asyncio
import logging

import httpx
import yaml

from app.cache import TTLCache

logger = logging.getLogger('tc_help_mcp.apidocs')

PAGES_ROOT = 'pages'
FETCH_CONCURRENCY = 8
MAX_RETRIES = 2
MAX_SEARCH_RESULTS = 25


class ApiDocsError(RuntimeError):
    """Raised when the API-docs repo cannot be reached or a file is missing."""


def _resolve(path: str) -> str:
    """Turn a repo-absolute YAML reference into a raw repo path under pages/."""
    return f'{PAGES_ROOT}/{path.lstrip("/")}'


def _render_attributes(attributes: list[dict], indent: int = 0) -> list[str]:
    """Render an attributes/filters list as a nested markdown bullet list."""
    lines: list[str] = []
    prefix = '  ' * indent
    for attr in attributes:
        name = attr.get('name', '')
        type_ = attr.get('type')
        description = attr.get('description')
        line = f'{prefix}- **{name}**'
        if type_:
            line += f' (`{type_}`)'
        if description:
            line += f' — {description}'
        lines.append(line)
        children = attr.get('children')
        if children:
            lines.extend(_render_attributes(children, indent + 1))
    return lines


class ApiDocsClient:
    """Fetch and assemble TutorCruncher API reference sections from GitHub."""

    def __init__(self, repo: str, ref: str, github_token: str | None, cache: TTLCache, timeout: float = 20.0) -> None:
        self.raw_base = f'https://raw.githubusercontent.com/{repo}/{ref}'
        self.github_token = github_token
        self.cache = cache
        self.timeout = timeout

    @property
    def _headers(self) -> dict[str, str]:
        """Return request headers, adding a token to raise rate limits if present."""
        if self.github_token:
            return {'Authorization': f'Bearer {self.github_token}'}
        return {}

    async def _http_get_text(self, repo_path: str) -> str:
        """Fetch one raw file's text, retrying transient errors with backoff."""
        url = f'{self.raw_base}/{repo_path}'
        for attempt in range(MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.get(url, headers=self._headers)
            except httpx.HTTPError as exc:
                raise ApiDocsError(f'API-docs request for {repo_path} failed: {exc}') from exc
            if response.status_code == 404:
                raise ApiDocsError(f'API-docs file not found: {repo_path}')
            if response.status_code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                delay = float(response.headers.get('Retry-After', 2**attempt))
                logger.warning('GitHub %s on %s; retrying in %ss', response.status_code, repo_path, delay)
                await asyncio.sleep(delay)
                continue
            if response.status_code >= 400:
                raise ApiDocsError(f'API-docs fetch returned {response.status_code} for {repo_path}.')
            return response.text
        raise ApiDocsError(f'API-docs remained unavailable for {repo_path} after retries.')

    async def _fetch_text(self, repo_path: str, sem: asyncio.Semaphore | None = None) -> str:
        """Return a raw file's text (cached under the TTL)."""

        async def loader() -> str:
            if sem is not None:
                async with sem:
                    return await self._http_get_text(repo_path)
            return await self._http_get_text(repo_path)

        return await self.cache.get_or_load(('text', repo_path), loader)

    async def _fetch_yaml(self, repo_path: str, sem: asyncio.Semaphore | None = None) -> dict:
        """Return a raw YAML file parsed to a dict (cached under the TTL)."""

        async def loader() -> dict:
            text = await self._fetch_text(repo_path, sem)
            return yaml.safe_load(text) or {}

        return await self.cache.get_or_load(('yaml', repo_path), loader)

    async def _index_sections(self) -> list[dict]:
        """Return all sections from api.yml as {id, title, kind, layout}."""
        index = await self._fetch_yaml(f'{PAGES_ROOT}/api.yml')
        sections: list[dict] = []
        for kind, key in (('info', 'info_sections'), ('endpoint', 'endpoint_sections')):
            for entry in index.get(key) or []:
                sections.append(
                    {
                        'id': entry.get('id'),
                        'title': entry.get('title') or '',
                        'kind': kind,
                        'layout': entry.get('layout'),
                    }
                )
        return sections

    async def list_sections(self) -> list[dict]:
        """Return the lightweight list of API sections (no content)."""
        sections = await self._index_sections()
        return [{'id': s['id'], 'title': s['title'], 'kind': s['kind']} for s in sections]

    async def _subsection_titles(self, section: dict, sem: asyncio.Semaphore) -> list[str]:
        """Return the subsection titles for a section (empty on fetch failure)."""
        if not section.get('layout'):
            return []
        try:
            layout = await self._fetch_yaml(_resolve(section['layout']), sem)
        except ApiDocsError as exc:
            logger.warning('layout fetch failed for %s: %s', section['id'], exc)
            return []
        return [sub.get('title') for sub in layout.get('sections') or [] if sub.get('title')]

    async def search(self, query: str) -> list[dict]:
        """Filter sections by keyword over section and subsection titles.

        Matching is whole-section: a hit on any subsection title surfaces its parent
        section. Returns ``{id, title, kind, subsections}`` ranked by match count.
        """
        terms = [term for term in query.lower().split() if term]
        if not terms:
            return []
        sections = await self._index_sections()
        sem = asyncio.Semaphore(FETCH_CONCURRENCY)
        titles = await asyncio.gather(*(self._subsection_titles(section, sem) for section in sections))
        scored: list[tuple[int, dict]] = []
        for section, subs in zip(sections, titles, strict=True):
            haystack = ' '.join([section['title'], *subs]).lower()
            score = sum(1 for term in terms if term in haystack)
            if score:
                match = {
                    'id': section['id'],
                    'title': section['title'],
                    'kind': section['kind'],
                    'subsections': subs,
                }
                scored.append((score, match))
        scored.sort(key=lambda entry: entry[0], reverse=True)
        return [item for _, item in scored][:MAX_SEARCH_RESULTS]

    async def _fetch_fields(self, sub: dict, fields: tuple[str, ...], sem: asyncio.Semaphore) -> dict[str, str]:
        """Fetch the present text fields of a subsection concurrently, keyed by field."""
        present = [field for field in fields if sub.get(field)]
        values = await asyncio.gather(*(self._fetch_text(_resolve(sub[field]), sem) for field in present))
        return dict(zip(present, values, strict=True))

    async def _fetch_yaml_fields(self, sub: dict, fields: tuple[str, ...], sem: asyncio.Semaphore) -> dict[str, dict]:
        """Fetch the present YAML fields of a subsection concurrently, keyed by field."""
        present = [field for field in fields if sub.get(field)]
        values = await asyncio.gather(*(self._fetch_yaml(_resolve(sub[field]), sem) for field in present))
        return dict(zip(present, values, strict=True))

    async def _render_subsection(self, sub: dict, sem: asyncio.Semaphore) -> str:
        """Assemble one subsection (description, params, example request/response)."""
        texts = await self._fetch_fields(sub, ('description', 'code', 'response'), sem)
        yamls = await self._fetch_yaml_fields(sub, ('attributes', 'filters'), sem)

        parts: list[str] = []
        if sub.get('title'):
            parts.append(f'## {sub["title"]}')
        if sub.get('code_type') and sub.get('code_url'):
            parts.append(f'`{sub["code_type"]}` `{sub["code_url"]}`')
        if texts.get('description'):
            parts.append(texts['description'].strip())
        if yamls.get('attributes', {}).get('attributes'):
            parts.append('**Attributes**\n' + '\n'.join(_render_attributes(yamls['attributes']['attributes'])))
        if yamls.get('filters', {}).get('attributes'):
            parts.append('**Query parameters**\n' + '\n'.join(_render_attributes(yamls['filters']['attributes'])))
        if texts.get('code'):
            parts.append('**Example request**\n```python\n' + texts['code'].strip() + '\n```')
        if texts.get('response'):
            if sub.get('response_title'):
                label = sub['response_title'].title()
            else:
                label = 'Example response'
            parts.append(f'**{label}**\n```json\n' + texts['response'].strip() + '\n```')
        return '\n\n'.join(parts)

    async def get_section(self, section_id: str) -> dict:
        """Return one whole section assembled to markdown.

        Args:
            section_id: A section id from ``api.yml`` (e.g. ``clients``).

        Returns:
            ``{id, title, kind, content}`` where content is assembled markdown.
        """
        sections = await self._index_sections()
        section = next((s for s in sections if s['id'] == section_id), None)
        if section is None:
            available = ', '.join(s['id'] for s in sections)
            raise ApiDocsError(f"Unknown API section '{section_id}'. Available sections: {available}.")
        sem = asyncio.Semaphore(FETCH_CONCURRENCY)
        layout = await self._fetch_yaml(_resolve(section['layout']), sem)
        subsections = layout.get('sections') or []
        blocks = await asyncio.gather(*(self._render_subsection(sub, sem) for sub in subsections))
        body = '\n\n'.join([f'# {section["title"]}', *[block for block in blocks if block]])
        return {'id': section['id'], 'title': section['title'], 'kind': section['kind'], 'content': body}
