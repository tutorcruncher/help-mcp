# Conditional Expressions

Prefer multi-line `if`/`else` over ternary expressions, even for simple value assignments.

## Why

Multi-line `if`/`else` reads top-to-bottom and surfaces both branches with equal weight. Inline ternaries hide one branch in the middle of the line and become unreadable once the condition has any complexity (`any(...)`, multiple operands, a method call).

## Examples

### ✅ Good

```python
if any(f.severity == FlagSeverity.SEVERE for f in flags):
    highest_severity = FlagSeverity.SEVERE.value
else:
    highest_severity = FlagSeverity.LOW.value
```

```python
if auto_now:
    onupdate = lambda: datetime.now(tz=timezone.utc)
else:
    onupdate = None
```

### ❌ Bad

```python
highest_severity = (
    FlagSeverity.SEVERE.value if any(f.severity == FlagSeverity.SEVERE for f in flags) else FlagSeverity.LOW.value
)
```

```python
onupdate = lambda: datetime.now(tz=timezone.utc) if auto_now else None
```

## Acceptable Exceptions

Trivial value substitution where both branches are short identifiers or literals — typically inside an argument list or a dict literal where pulling out an `if` block would be more disruptive than the ternary itself:

```python
return {'count': total, 'status': 'ok' if total > 0 else 'empty'}
```

If the expression on either side is anything more complex than a name, a literal, or a single attribute access, expand to `if`/`else`.
