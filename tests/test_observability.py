import contextlib

from app.observability import tool_span


def test_tool_span_is_noop_without_configuration():
    """Until Logfire is configured (only in main()), tool_span is a no-op context."""
    span = tool_span('list_help_articles')

    assert isinstance(span, contextlib.nullcontext)
    with span:
        pass
