"""Optional Logfire observability, fully opt-in via the LOGFIRE_TOKEN env var.

``configure_observability()`` is called once from ``main()``. With no token set it
configures Logfire in local-only mode (``send_to_logfire='if-token-present'``) so the
server, tests and local runs are unaffected; nothing is exported. With a token it
instruments httpx — tracing every Intercom and GitHub call with status and latency —
and tool calls get a span via ``tool_span``.

httpx instrumentation uses the conservative defaults (no header or body capture), so
the per-workspace Intercom tokens and GitHub credentials are never sent to Logfire.
"""

import contextlib

import logfire

_configured = False


def configure_observability() -> None:
    """Configure Logfire once. A no-op exporter unless LOGFIRE_TOKEN is set."""
    global _configured
    logfire.configure(
        send_to_logfire='if-token-present',
        service_name='tc-help-mcp',
        console=False,
    )
    logfire.instrument_httpx()
    _configured = True


def tool_span(tool_name: str):
    """Return a span for a tool call, or a no-op context if Logfire is not configured."""
    if not _configured:
        return contextlib.nullcontext()
    return logfire.span('tool {tool_name}', tool_name=tool_name)
