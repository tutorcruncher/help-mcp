---
paths:
  - "**/*.py"
---

# Documentation Rules

Use docstrings for documentation, not comments. Use type hints throughout.

## Key Points

- Use docstrings for function/class documentation
- Only use comments for complex code that requires explanation
- Use type hints throughout the codebase
- Follow PEP 8 style guidelines

## Comments explain the code, never the PR or process

Comments and docstrings must describe what the code does and why — never reference the
PR, ticket, or delivery process that introduced it. Phrases like "added in this PR" or
"TODO from review" are noise: they're false the moment the code merges. Explain the
code's behaviour instead.

## Docstrings

```python
def make_backend_client() -> ProxyClient:
    """Build a per-request client for the backend github-mcp-server.

    Reads the authenticated user's GitHub token from the active request context
    and forwards it as a bearer credential so the backend acts as that user.

    Returns:
        ProxyClient: A client bound to the backend MCP server for this request.
    """
```

## Type Hints

Always use type hints for function arguments and return values. Use `X | None` instead
of `Optional[X]` (Python 3.12+ supports the `|` syntax natively).

```python
def get_login(token: AccessToken) -> str | None:
    return token.claims.get('login')
```

## Field Documentation

Pydantic / tool-input fields whose purpose isn't obvious from the name alone must be
documented via `description=` — especially for MCP tool schemas, which the model reads
to decide how to call the tool.

```python
class ToolInput(BaseModel):
    repo: str = Field(..., description='owner/name of the repository, e.g. "github/github-mcp-server"')
```

Skip documentation for universally understood fields (`id`, `name`, `email`).
