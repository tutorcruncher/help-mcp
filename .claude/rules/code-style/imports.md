---
paths:
  - "**/*.py"
---

# Import Rules

All imports must be at the module level. Never use imports inside functions.

## Key Points

- All imports at module level
- No function-level imports unless technically necessary
- Use `TYPE_CHECKING` for type-only imports to avoid circular imports
- No imports in `__init__.py` files — import directly from module files

## Module-Level Imports

### ✅ Correct
```python
from fastmcp.server.dependencies import get_access_token

def current_github_token() -> str:
    return get_access_token().token
```

### ❌ Wrong
```python
def current_github_token() -> str:
    from fastmcp.server.dependencies import get_access_token  # Wrong - import inside function
    return get_access_token().token
```

## Circular Import Resolution

Only use local imports when necessary to avoid circular imports, guarded by `TYPE_CHECKING`:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.server import build_server
```

## Import Order

Follow PEP 8 import ordering, separated by a blank line between groups:

1. Standard library imports
2. Third party imports
3. Local application imports (`app.*`)

## Never use `from __future__ import annotations`

Don't add `from __future__ import annotations` to any file. Python 3.12 supports
PEP 604 unions (`X | Y`) and PEP 585 generics (`list[int]`) natively, and the
deferred-evaluation behaviour breaks tools that rely on real annotations at import
time (pydantic, FastMCP tool schema generation).
