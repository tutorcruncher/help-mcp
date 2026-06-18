---
paths:
  - "tests/**/*.py"
---

# Test Assertion Rules

Check entire data structures in test responses, not just individual keys.

## Key Points

- Assert complete data structures, not individual fields
- Inline expected values directly in assertions
- Don't check key existence before asserting values (KeyError provides the same info)

## Complete Structure Checks

### ✅ Good - Checking entire structure
```python
def test_backend_headers():
    headers = build_backend_headers(token='gho_test', toolsets='repos,issues')
    assert headers == {
        'Authorization': 'Bearer gho_test',
        'X-MCP-Toolsets': 'repos,issues',
    }
```

### ❌ Bad - Checking only individual keys
```python
def test_backend_headers():
    headers = build_backend_headers(token='gho_test', toolsets='repos,issues')
    assert headers['Authorization'] == 'Bearer gho_test'  # Missing other keys
```

## No Redundant Existence Checks

### ✅ Good - Direct value assertions
```python
assert headers['X-MCP-Toolsets'] == 'repos,issues'
```

### ❌ Bad - Redundant checks
```python
assert 'X-MCP-Toolsets' in headers  # Redundant - KeyError tells you this
assert headers['X-MCP-Toolsets'] == 'repos,issues'
```

If the key doesn't exist, Python raises `KeyError` which fails the test with a clear message.
