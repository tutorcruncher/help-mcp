---
paths:
  - "tests/**/*.py"
---

# End-to-End Tests

Tests should exercise real code paths end-to-end, not unit-test internal helpers in
isolation. Drive the behaviour through the entry point that actually invokes it (the
MCP server, the client factory, the auth provider). The only boundary that should be
mocked is the external service the feature can't run without — GitHub, the backend
github-mcp-server process, or the OAuth provider's network calls.

## Why

- Unit tests on a helper pass even when the helper is wired up wrong (or not wired up
  at all). E2E tests catch the wiring bugs.
- A passing E2E test is real evidence the feature works.
- E2E tests survive refactors of internal structure without churn.

## How

### ✅ Good — drive the real path, mock only the external boundary

```python
@patch('app.backend.get_access_token')
def test_factory_builds_client_with_user_token(mock_token):
    """The proxy client factory forwards the request user's GitHub token."""
    mock_token.return_value = FakeToken(token='gho_user1')

    client = make_backend_client()

    transport = client.transport
    assert transport.headers['Authorization'] == 'Bearer gho_user1'
```

### ❌ Bad — testing a trivial helper in isolation

```python
def test_header_dict():
    assert {'Authorization': 'Bearer x'} == {'Authorization': 'Bearer x'}
```

## Boundaries to mock

- GitHub's API and OAuth endpoints.
- The backend github-mcp-server process / transport.
- Anything reached over the network.

Everything inside the app — config loading, the client factory, header construction —
should run for real.
