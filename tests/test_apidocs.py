import pytest

from app.apidocs import ApiDocsClient, ApiDocsError
from app.cache import TTLCache

RAW_BASE = 'https://raw.githubusercontent.com/tutorcruncher/tc-api-docs/master'

FILES = {
    'pages/api.yml': """
title: TutorCruncher API
info_sections:
  - title: Introduction
    id: introduction
    layout: /introduction/introduction.yml
endpoint_sections:
  - title: Clients
    id: clients
    layout: /clients/clients.yml
""",
    'pages/introduction/introduction.yml': """
sections:
  - description: /introduction/intro.md
    code: /introduction/intro.txt
    code_type: BASE URL
""",
    'pages/introduction/intro.md': 'Welcome to the API.',
    'pages/introduction/intro.txt': 'https://secure.tutorcruncher.com',
    'pages/clients/clients.yml': """
sections:
  - title: Client Object
    id: client-object
    description: /clients/object.md
    attributes: /clients/object.yml
    response: /clients/object.json
    response_title: OBJECT
  - title: List all Clients
    id: list-all-clients
    description: /clients/list.md
    filters: /clients/filters.yml
    code: /clients/list.py
    code_type: GET
    code_url: /api/clients/
    response: /clients/list.json
""",
    'pages/clients/object.md': 'The client object.',
    'pages/clients/object.yml': """
attributes:
  - name: id
    type: integer
    description: Unique id.
  - name: user
    type: object
    description: User info.
    children:
      - name: email
        type: string
        description: Email.
""",
    'pages/clients/object.json': '{"id": 3}',
    'pages/clients/list.md': 'Returns all clients.',
    'pages/clients/filters.yml': """
attributes:
  - name: page
    type: integer
    description: Page number.
""",
    'pages/clients/list.py': "requests.get('/api/clients/')",
    'pages/clients/list.json': '{"results": []}',
}

EXPECTED_CLIENTS = """# Clients

## Client Object

The client object.

**Attributes**
- **id** (`integer`) — Unique id.
- **user** (`object`) — User info.
  - **email** (`string`) — Email.

**Object**
```json
{"id": 3}
```

## List all Clients

`GET` `/api/clients/`

Returns all clients.

**Query parameters**
- **page** (`integer`) — Page number.

**Example request**
```python
requests.get('/api/clients/')
```

**Example response**
```json
{"results": []}
```"""


class FakeResponse:
    def __init__(self, status_code=200, text='', headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


class FakeAsyncClient:
    def __init__(self, files):
        self._files = files

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, headers=None):
        repo_path = url[len(RAW_BASE) + 1 :]
        if repo_path not in self._files:
            return FakeResponse(status_code=404)
        return FakeResponse(text=self._files[repo_path])


def build_client(monkeypatch, files=FILES):
    monkeypatch.setattr('app.apidocs.httpx.AsyncClient', lambda *a, **k: FakeAsyncClient(files))
    return ApiDocsClient('tutorcruncher/tc-api-docs', 'master', None, TTLCache(ttl=300.0))


async def test_list_sections_enumerates_index(monkeypatch):
    """list_sections returns info then endpoint sections with id/title/kind."""
    client = build_client(monkeypatch)

    sections = await client.list_sections()

    assert sections == [
        {'id': 'introduction', 'title': 'Introduction', 'kind': 'info'},
        {'id': 'clients', 'title': 'Clients', 'kind': 'endpoint'},
    ]


async def test_get_section_assembles_whole_section(monkeypatch):
    """get_section fans out over subsection files and assembles one markdown doc."""
    client = build_client(monkeypatch)

    section = await client.get_section('clients')

    assert section == {
        'id': 'clients',
        'title': 'Clients',
        'kind': 'endpoint',
        'content': EXPECTED_CLIENTS,
    }


async def test_search_matches_section_and_subsection_titles(monkeypatch):
    """A subsection-title hit surfaces the whole parent section with its subsections."""
    client = build_client(monkeypatch)

    results = await client.search('list')

    assert results == [
        {
            'id': 'clients',
            'title': 'Clients',
            'kind': 'endpoint',
            'subsections': ['Client Object', 'List all Clients'],
        }
    ]


async def test_search_title_only_misses_field_names(monkeypatch):
    """Search matches titles only — a field name buried in attributes is not a hit."""
    client = build_client(monkeypatch)

    assert await client.search('email') == []


async def test_get_section_unknown_id_raises(monkeypatch):
    """An unknown section id raises a clear error listing available sections."""
    client = build_client(monkeypatch)

    with pytest.raises(ApiDocsError, match='Unknown API section'):
        await client.get_section('invoices')


async def test_missing_file_raises(monkeypatch):
    """A referenced file that 404s surfaces as a readable ApiDocsError."""
    files = {k: v for k, v in FILES.items() if k != 'pages/clients/object.md'}
    client = build_client(monkeypatch, files)

    with pytest.raises(ApiDocsError, match='not found'):
        await client.get_section('clients')
