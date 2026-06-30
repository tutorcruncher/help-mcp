import pytest

from app.cache import TTLCache
from app.config import HelpSource
from app.intercom import IntercomClient, IntercomError, clean_html, parse_images, strip_boilerplate

API_BASE = 'https://api.intercom.io'

SOURCES = [
    HelpSource('tutorcruncher', 'tc-token', 'https://help.tutorcruncher.com'),
    HelpSource('bobbin', 'bobbin-token', 'https://intercom.help/bobbin-355e87537201'),
]


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text='', headers=None):
        self.status_code = status_code
        self._json = json_data
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._json


class FakeAsyncClient:
    def __init__(self, handler):
        self._handler = handler

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, params=None, headers=None):
        return self._handler(url, params or {}, headers or {})

    async def request(self, method, url, json=None, headers=None):
        # Writes reuse the same handler; method + body are passed via the params dict
        # (a GET has no 'method' key, so handlers branch on params.get('method')).
        return self._handler(url, {'method': method, 'json': json}, headers or {})


def patch_http(monkeypatch, handler):
    monkeypatch.setattr('app.intercom.httpx.AsyncClient', lambda *a, **k: FakeAsyncClient(handler))


def build_client():
    return IntercomClient(SOURCES, API_BASE, TTLCache(ttl=300.0), search_limit=8)


def catalogue_handler(url, params, headers):
    path = url[len(API_BASE) :]
    is_tc = 'tc-token' in headers.get('Authorization', '')
    if path == '/articles':
        if is_tc:
            article = {
                'id': 10,
                'title': 'Refunds',
                'description': 'How refunds work',
                'url': 'https://help.tutorcruncher.com/refunds',
                'parent_id': 5,
            }
        else:
            article = {
                'id': 20,
                'title': 'Lesson reports',
                'description': 'Reports',
                'url': 'https://intercom.help/bobbin/lesson-reports',
                'parent_id': 7,
            }
        return FakeResponse(json_data={'data': [article], 'pages': {'total_pages': 1}})
    if path == '/help_center/collections':
        collections = [{'id': 5, 'name': 'Billing'}] if is_tc else [{'id': 7, 'name': 'Teaching'}]
        return FakeResponse(json_data={'data': collections, 'pages': {'total_pages': 1}})
    raise AssertionError(f'unexpected path {path}')


def test_strip_boilerplate_removes_markers_and_collapses_blanks():
    """Boilerplate lines are dropped and runs of blank lines collapse to one."""
    text = '## Refunds\n\nBody text.\n\n\n\nWe run on Intercom\nPowered by Intercom'
    assert strip_boilerplate(text) == '## Refunds\n\nBody text.'


def test_clean_html_to_markdown_strips_chrome():
    """HTML converts to markdown with headings/content kept and boilerplate removed."""
    html = '<h2>Refunds</h2><p>Issue a refund from the invoice.</p><p>We run on Intercom</p>'
    cleaned = clean_html(html)
    assert '## Refunds' in cleaned
    assert 'Issue a refund from the invoice.' in cleaned
    assert 'Intercom' not in cleaned


def test_clean_html_empty_is_empty():
    """A missing body cleans to an empty string."""
    assert clean_html(None) == ''


async def test_list_articles_assembles_catalogue_across_products(monkeypatch):
    """The catalogue spans both products, labelled, with collection names mapped."""
    patch_http(monkeypatch, catalogue_handler)
    client = build_client()

    catalogue = await client.list_articles()

    assert catalogue == [
        {
            'product': 'tutorcruncher',
            'id': '10',
            'title': 'Refunds',
            'description': 'How refunds work',
            'url': 'https://help.tutorcruncher.com/refunds',
            'collection': 'Billing',
        },
        {
            'product': 'bobbin',
            'id': '20',
            'title': 'Lesson reports',
            'description': 'Reports',
            'url': 'https://intercom.help/bobbin/lesson-reports',
            'collection': 'Teaching',
        },
    ]


async def test_list_articles_product_filter(monkeypatch):
    """A product filter restricts the catalogue to that workspace."""
    patch_http(monkeypatch, catalogue_handler)
    client = build_client()

    catalogue = await client.list_articles('bobbin')

    assert [entry['product'] for entry in catalogue] == ['bobbin']


async def test_unknown_product_raises(monkeypatch):
    """Filtering on an unconfigured product raises a clear error."""
    patch_http(monkeypatch, catalogue_handler)
    client = build_client()

    with pytest.raises(IntercomError, match='Unknown product'):
        await client.list_articles('acme')


async def test_search_ranks_title_matches_and_dedupes(monkeypatch):
    """Search merges sources, boosts title matches and caps to the search limit."""

    def handler(url, params, headers):
        assert url == f'{API_BASE}/articles/search'
        assert params == {'phrase': 'refund', 'state': 'published'}
        if 'tc-token' in headers.get('Authorization', ''):
            articles = [
                {'id': 1, 'title': 'Cancellation policy', 'description': 'no match', 'url': 'u1'},
                {'id': 2, 'title': 'Refund a payment', 'description': 'about refunds', 'url': 'u2'},
            ]
        else:
            articles = [{'id': 3, 'title': 'Refunds in Bobbin', 'description': 'b', 'url': 'u3'}]
        return FakeResponse(json_data={'data': {'articles': articles}})

    patch_http(monkeypatch, handler)
    client = build_client()

    results = await client.search('refund')

    assert [(r['product'], r['id']) for r in results] == [
        ('tutorcruncher', '2'),
        ('bobbin', '3'),
        ('tutorcruncher', '1'),
    ]
    assert results[0] == {
        'product': 'tutorcruncher',
        'id': '2',
        'title': 'Refund a payment',
        'summary': 'about refunds',
        'url': 'u2',
    }


async def test_get_article_returns_cleaned_body(monkeypatch):
    """get_article routes to the product's workspace and cleans the body."""

    def handler(url, params, headers):
        assert url == f'{API_BASE}/articles/10'
        assert 'tc-token' in headers.get('Authorization', '')
        return FakeResponse(
            json_data={
                'id': 10,
                'title': 'Refunds',
                'url': 'https://help.tutorcruncher.com/refunds',
                'body': '<h1>Refunds</h1><p>Steps here.</p><p>We run on Intercom</p>',
            }
        )

    patch_http(monkeypatch, handler)
    client = build_client()

    article = await client.get_article('tutorcruncher', '10')

    assert article['product'] == 'tutorcruncher'
    assert article['id'] == '10'
    assert article['title'] == 'Refunds'
    assert article['url'] == 'https://help.tutorcruncher.com/refunds'
    assert article['body'] == '# Refunds\n\nSteps here.'


async def test_retries_then_raises_on_persistent_429(monkeypatch):
    """A persistent 429 surfaces as a readable IntercomError after retries."""
    monkeypatch.setattr('app.intercom.asyncio.sleep', _no_sleep)

    def handler(url, params, headers):
        return FakeResponse(status_code=429, headers={'Retry-After': '0'})

    patch_http(monkeypatch, handler)
    client = build_client()

    with pytest.raises(IntercomError, match='429'):
        await client.list_articles('tutorcruncher')


async def _no_sleep(_seconds):
    return None


# ─── Image parsing ────────────────────────────────────────────────────────────


def test_parse_images_extracts_context_and_heading():
    """Each <img> is returned with its src, alt, filename, nearest heading and prose."""
    html = (
        '<h2>Billing settings</h2>'
        '<p>Go to Settings then Billing to see your plan.</p>'
        '<img src="https://downloads.intercomcdn.com/abc.png" alt="Billing page">'
        '<h2>Lessons</h2><img src="https://x.example/logo.svg">'
    )

    images = parse_images(html)

    assert len(images) == 2
    assert images[0] == {
        'img_src': 'https://downloads.intercomcdn.com/abc.png',
        'alt': 'Billing page',
        'filename': 'abc.png',
        'heading': 'Billing settings',
        'surrounding_text': 'Billing settings Go to Settings then Billing to see your plan.',
    }
    assert images[1]['heading'] == 'Lessons'
    assert images[1]['filename'] == 'logo.svg'
    assert images[1]['alt'] == ''


def test_parse_images_empty_body():
    """A missing or empty body yields no images."""
    assert parse_images(None) == []
    assert parse_images('') == []


# ─── Write / raw tools (all draft-only) ───────────────────────────────────────


async def test_get_article_raw_returns_html_and_images(monkeypatch):
    """get_article_raw preserves the exact HTML and lists parsed images."""

    def handler(url, params, headers):
        assert url == f'{API_BASE}/articles/10'
        assert 'tc-token' in headers.get('Authorization', '')
        return FakeResponse(
            json_data={
                'id': 10,
                'title': 'Refunds',
                'state': 'published',
                'parent_id': 5,
                'url': 'https://help.tutorcruncher.com/refunds',
                'body': '<h2>Refunds</h2><p>See the invoice screen.</p><img src="https://cdn/i/old.png" alt="invoice">',
            }
        )

    patch_http(monkeypatch, handler)
    client = build_client()

    article = await client.get_article_raw('tutorcruncher', '10')

    assert article['body_html'].startswith('<h2>Refunds</h2>')
    assert article['state'] == 'published'
    assert article['parent_id'] == 5
    assert [img['img_src'] for img in article['images']] == ['https://cdn/i/old.png']


async def test_update_article_forces_draft_state(monkeypatch):
    """update_article PUTs only the provided fields and always coerces state=draft."""
    captured = {}

    def handler(url, params, headers):
        captured['url'] = url
        captured['method'] = params.get('method')
        captured['json'] = params.get('json')
        return FakeResponse(json_data={'id': 10, 'title': 'Refunds', 'state': 'draft', 'url': 'u'})

    patch_http(monkeypatch, handler)
    client = build_client()

    result = await client.update_article('tutorcruncher', '10', body_html='<p>new</p>')

    assert captured['method'] == 'PUT'
    assert captured['url'] == f'{API_BASE}/articles/10'
    assert captured['json'] == {'state': 'draft', 'body': '<p>new</p>'}
    assert result == {'product': 'tutorcruncher', 'id': '10', 'title': 'Refunds', 'url': 'u', 'state': 'draft'}


async def test_create_article_uses_author_and_draft(monkeypatch):
    """create_article posts the workspace author id and forces state=draft."""
    captured = {}

    def handler(url, params, headers):
        captured['url'] = url
        captured['method'] = params.get('method')
        captured['json'] = params.get('json')
        return FakeResponse(json_data={'id': 99, 'title': 'New', 'state': 'draft', 'url': 'u'})

    patch_http(monkeypatch, handler)
    sources = [HelpSource('tutorcruncher', 'tc-token', 'https://help.tutorcruncher.com', author_id=42)]
    client = IntercomClient(sources, API_BASE, TTLCache(ttl=300.0), search_limit=8)

    result = await client.create_article('tutorcruncher', 'New', '<p>hi</p>', parent_id='7')

    assert captured['method'] == 'POST'
    assert captured['url'] == f'{API_BASE}/articles'
    assert captured['json'] == {
        'title': 'New',
        'body': '<p>hi</p>',
        'author_id': 42,
        'state': 'draft',
        'parent_id': '7',
    }
    assert result['id'] == '99'


async def test_create_article_without_author_raises(monkeypatch):
    """Creating an article with no configured/explicit author id fails clearly."""
    patch_http(monkeypatch, lambda *a: FakeResponse(json_data={}))
    client = build_client()  # SOURCES carry no author_id

    with pytest.raises(IntercomError, match='no author id'):
        await client.create_article('tutorcruncher', 'New', '<p>hi</p>')


async def test_replace_article_image_swaps_all_and_drafts(monkeypatch):
    """replace_article_image swaps every occurrence and saves a draft."""
    state = {}

    def handler(url, params, headers):
        if params.get('method') is None:  # the GET of the current body
            return FakeResponse(json_data={'id': 10, 'body': '<img src="OLD"> then <img src="OLD">'})
        state['json'] = params.get('json')  # the PUT
        return FakeResponse(json_data={'id': 10, 'title': 'T', 'state': 'draft', 'url': 'u'})

    patch_http(monkeypatch, handler)
    client = build_client()

    result = await client.replace_article_image('tutorcruncher', '10', 'OLD', 'NEW')

    assert state['json'] == {'body': '<img src="NEW"> then <img src="NEW">', 'state': 'draft'}
    assert result['replaced'] == 2
    assert result['state'] == 'draft'


async def test_replace_article_image_missing_src_raises(monkeypatch):
    """A src that isn't present errors rather than silently writing an unchanged draft."""

    def handler(url, params, headers):
        return FakeResponse(json_data={'id': 10, 'body': '<p>no images here</p>'})

    patch_http(monkeypatch, handler)
    client = build_client()

    with pytest.raises(IntercomError, match='not found'):
        await client.replace_article_image('tutorcruncher', '10', 'OLD', 'NEW')
