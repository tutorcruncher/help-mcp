---
paths:
  - "tests/**/*.py"
---

# Test Code Style Rules

Tests should be clean, readable, and follow consistent style patterns.

## Key Points

- No inline comments except docstrings at the top of functions
- Maximum line length: 120 characters
- Use `@patch` decorator instead of `with patch()` blocks
- Keep coverage high (aim for ~95%+); 100% on auth/token-handling paths

## No Inline Comments

### ✅ Correct
```python
assert headers == {
    'Authorization': 'Bearer gho_test',
    'X-MCP-Toolsets': 'repos,issues',
}
```

### ❌ Wrong
```python
assert headers == {
    'Authorization': 'Bearer gho_test',  # the user's GitHub token
    'X-MCP-Toolsets': 'repos,issues',    # selected toolsets
}
```

## Docstrings Only

```python
def test_backend_headers_include_user_token():
    """The backend factory forwards the request user's GitHub token as a bearer."""
    ...
```

## Mocking Patterns

### ✅ Good - Using @patch decorator
```python
from unittest.mock import patch

@patch('app.backend.get_access_token')
def test_injects_token(mock_get_token):
    mock_get_token.return_value = FakeToken(token='gho_test')
    ...
```

### ❌ Bad - Using with patch() blocks
```python
def test_injects_token():
    with patch('app.backend.get_access_token') as mock_get_token:
        ...
```

## Running Tests

Always run pytest with `-n auto` (pytest-xdist) — single-file, single-test, coverage,
everything.

```bash
uv run pytest -n auto
uv run pytest -n auto -k "test_injects_token"
uv run pytest -n auto --cov=app --cov-report=term-missing
```
