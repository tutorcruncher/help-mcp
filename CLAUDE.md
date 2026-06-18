# tc-help-mcp — project guide for Claude

## What this is

A **remote MCP server** that gives the team's Claude.ai workspace live, always-current
access to product documentation across the portfolio — **TutorCruncher** and **Bobbin**.
It is a general product-docs assistant, not a single-product one, and is built to extend
to further products by config alone.

Unlike the sibling `git-mcp` (which *proxies* the official github-mcp-server), this server
**defines its own tools** with FastMCP and fetches docs from source on every request:

- **Help docs** — Intercom Articles API, one workspace token per product (TutorCruncher +
  Bobbin are separate Intercom workspaces → separate tokens).
- **API docs** — the public `tutorcruncher/tc-api-docs` GitHub repo (TutorCruncher only at
  launch; the tools are product-agnostic so a future source slots in).

Auth is identical to git-mcp: FastMCP's `GitHubProvider` runs Claude's connector OAuth flow
and `OrgMembershipMiddleware` gates tools to active members of the configured GitHub org.

## Core principle — live, never a second source of truth

The docs themselves are the only source of truth. There is **no local index and no persisted
copy**. Each query reads from the live source. A short in-memory **TTL cache** (default 300s,
`CACHE_TTL_SECONDS`) exists *only* for latency/rate-limit protection and re-fetches on expiry.

Claude is the retrieval brain: the server exposes cheap list/search + fat fetch tools and lets
Claude do the semantic matching. **Do not add embeddings, a vector store, a crawler, or a
nested LLM** — if that seems necessary, stop and raise it.

## Key files

- `app/config.py` — env-backed `Settings` + the multi-product help-source registry.
- `app/auth.py` / `app/access.py` — GitHub OAuth + org-membership gate (copied from git-mcp).
- `app/cache.py` — generic async per-key TTL cache.
- `app/intercom.py` — multi-source Intercom client (catalogue, search, fetch, HTML cleaning).
- `app/apidocs.py` — tc-api-docs client (parse `api.yml` index → layouts → content files).
- `app/server.py` — FastMCP server, tool definitions, entry point.

## tc-api-docs structure (Outcome B — index + separate content files)

`pages/api.yml` is an **index**, not self-contained:

```
pages/api.yml          info_sections[] + endpoint_sections[]  → each {title, id, layout}
pages/<sec>/<sec>.yml  layout: sections[]  → each subsection references separate files:
    description: /<sec>/x.md     (markdown prose)
    attributes:  /<sec>/x.yml    ({attributes: [{name, type, description, children?}]})
    filters:     /<sec>/x.yml    (same shape — query params)
    response:    /<sec>/x.json   (example JSON)
    code:        /<sec>/x.py     (example request) + code_type (GET/POST) + code_url
```

Paths in the YAML are repo-absolute under `pages/` (e.g. `/clients/clients.yml` →
`pages/clients/clients.yml`). `get_api_section` resolves a whole section, fans out over every
subsection's referenced files (cached, concurrency-capped), and assembles one markdown doc.

## Stack & workflow

- Python 3.12+, managed with **`uv`**. Lint/format with **`ruff`**, type-check with **`ty`**,
  test with **`pytest`** (always `-n auto`).
- `make install-dev` — install deps + pre-commit hooks.
- `make lint` — ruff check + format check + ty. **Always run `make lint` after changing code.**
- `make test` / `make test-cov` — run tests.
- `make run-dev` — run this MCP server (set `ALLOW_UNGATED=1` for local use without an org).

## Conventions

Code style and testing rules live in `.claude/rules/`:
- `code-style/` — module-level imports, docstrings over comments, type hints, no ternaries for
  non-trivial branches, never `from __future__ import annotations`.
- `testing/` — assert whole structures, `@patch` decorator, no inline comments in tests, drive
  real code paths E2E and mock only external boundaries (Intercom, GitHub raw).

## Pinning

`fastmcp` is version-sensitive (auth/provider APIs changed across v2→v3); this repo targets
v3.4.2+. Keep it pinned.
