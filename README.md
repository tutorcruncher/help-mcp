# tc-help-mcp

A remote [MCP](https://modelcontextprotocol.io) server that gives the team's Claude.ai
workspace live, always-current access to product documentation across the portfolio —
**TutorCruncher** and **Bobbin** — with room to add more products by config alone.

It is a **general product-docs assistant**: the team adds it once as a remote connector and
asks questions; Claude calls the tools, the server fetches from source on demand, and Claude
reasons over the returned content. There is no local index and no persisted copy of the docs —
the docs are the only source of truth, so answers never drift. A short in-memory TTL cache
(default 300s) exists purely for latency/rate-limit protection.

Sources at launch:

1. **TutorCruncher help docs** — Intercom help centre, via the Intercom Articles API.
2. **Bobbin help docs** — Intercom help centre (separate Intercom workspace → separate token).
3. **TutorCruncher API docs** — the public [`tutorcruncher/tc-api-docs`](https://github.com/tutorcruncher/tc-api-docs) repo.

## Tools

Help tools take an optional `product` filter (`"tutorcruncher"` | `"bobbin"`); unset spans all
configured products. Every result carries its `product` so answers stay correctly attributed.

| Tool | Purpose |
|---|---|
| `list_help_articles(product=None)` | Lightweight catalogue (product, id, title, description, url, collection). No bodies. |
| `search_help(query, product=None)` | Server-side Intercom search across product(s); deduped, ranked, top N `{product, id, title, summary, url}`. |
| `get_help_article(product, id)` | Full cleaned article body (markdown, boilerplate stripped) + title and url. |
| `list_api_sections()` | All API sections from `api.yml` (`{id, title, kind}`). |
| `search_api_docs(query)` | Keyword filter over section and subsection titles → matching whole sections. |
| `get_api_section(id)` | Whole section assembled to markdown: endpoints, params, request/response examples, version notes. |

## tc-api-docs structure (Outcome B)

`pages/api.yml` is an index (`info_sections` + `endpoint_sections`), each entry pointing to a
`layout` file (e.g. `pages/clients/clients.yml`). A layout's `sections:` list references separate
content files per subsection: `description` (`.md`), `attributes`/`filters` (`.yml`), `response`
(`.json`), and `code` (`.py`) plus `code_type`/`code_url`. Paths are repo-absolute under
`pages/`. `get_api_section` resolves a section, fetches its layout, fans out over the referenced
files (cached, concurrency-capped) and assembles one clean markdown document.

## Configuration

All configuration is via environment variables (see [`.env.example`](.env.example)). Never
commit values. Each Intercom workspace has its own token — one token does not span both products.

| Variable | Default | Purpose |
|---|---|---|
| `GITHUB_OAUTH_CLIENT_ID` / `GITHUB_OAUTH_CLIENT_SECRET` | — | GitHub OAuth App credentials. |
| `BASE_URL` | — | Public HTTPS base URL of this server (callback `<BASE_URL>/auth/callback`). |
| `GITHUB_SCOPES` | `read:org read:user` | Scopes needed to verify org membership. |
| `ALLOWED_GITHUB_ORG` | — | Only active members of this org may use the tools. |
| `ALLOW_UNGATED` | `0` | Set `1` to run without an org gate (local dev only). |
| `ALLOWED_REDIRECT_URIS` | `https://claude.ai/api/mcp/auth_callback` | Permitted OAuth client redirect URIs. |
| `JWT_SIGNING_KEY` | — | Signing key for FastMCP-issued JWTs. |
| `INTERCOM_API_BASE` | `https://api.intercom.io` | Intercom API host (same for both workspaces). |
| `INTERCOM_TOKEN_TUTORCRUNCHER` | — | TutorCruncher Intercom workspace token. |
| `INTERCOM_TOKEN_BOBBIN` | — | Bobbin Intercom workspace token. |
| `TC_API_DOCS_REPO` | `tutorcruncher/tc-api-docs` | API-docs repo. |
| `TC_API_DOCS_REF` | `master` | API-docs git ref. |
| `GITHUB_TOKEN` | — | Optional, raises raw-content fetch rate limits (distinct from the OAuth creds). |
| `CACHE_TTL_SECONDS` | `300` | In-memory cache TTL (latency/rate-limit protection only). |
| `SEARCH_RESULT_LIMIT` | `8` | Max `search_help` results. |
| `PORT` | `8000` | Bind port (Heroku sets this automatically). |

### Adding another product

A product is one line in `KNOWN_HELP_PRODUCTS` in `app/config.py` (`(product, help_centre_base)`)
plus an `INTERCOM_TOKEN_<PRODUCT>` env var. Products whose token is unset are skipped. No tool
changes are needed.

## Local development

```bash
make install-dev          # deps + pre-commit hooks
cp .env.example .env       # fill in tokens; set ALLOW_UNGATED=1 for local use
make lint                  # ruff + ty
make test                  # pytest -n auto
make run-dev               # serve on 0.0.0.0:$PORT
```

## Deployment

Built as a single-stage Docker image and released to Heroku (container stack) by
`.github/workflows/deploy.yml` on push to `main`. Set secrets via Heroku config, never the repo:

Deploys run via `.github/workflows/deploy.yml` (GitHub Actions builds the image and
releases it to the container-stack Heroku app `help-mcp` on push to `main`). The repo
needs a `HEROKU_API_KEY` secret; the Heroku app needs its config vars set:

```bash
heroku stack:set container -a help-mcp
heroku config:set -a help-mcp \
  GITHUB_OAUTH_CLIENT_ID=... GITHUB_OAUTH_CLIENT_SECRET=... \
  BASE_URL=https://help-mcp-5710e51f90a5.herokuapp.com \
  JWT_SIGNING_KEY="$(openssl rand -hex 32)" \
  ALLOWED_GITHUB_ORG=tutorcruncher \
  INTERCOM_TOKEN_TUTORCRUNCHER=... INTERCOM_TOKEN_BOBBIN=...
```

Then register `https://help-mcp-5710e51f90a5.herokuapp.com/mcp` as a remote connector in
the team's Claude.ai workspace.
