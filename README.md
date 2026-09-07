<p align="center">
  <picture>
    <source media="(prefers-color-scheme: light)" srcset="https://ml2-ai-product.s3.ap-northeast-2.amazonaws.com/MARU/MARU_Black_full.png">
    <source media="(prefers-color-scheme: dark)" srcset="https://ml2-ai-product.s3.ap-northeast-2.amazonaws.com/MARU/MARU_White_full.png">
    <img alt="MARU" src="https://ml2-ai-product.s3.ap-northeast-2.amazonaws.com/MARU/MARU_black.png" width="90%">
  </picture>
</p>
<p align="center">
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
</p>

# 🦊 MARU-Lang

**A deterministic, team-scoped filesystem access layer for AI agents.**

MARU gives agents fast, precise, and authorized filesystem discovery. It exposes
small, composable operations for listing directory trees, finding files, searching
text, inspecting metadata, and reading bounded file ranges. The agent decides how
to combine those operations; MARU executes explicit search parameters and returns
evidence rather than guessing what is relevant.

MARU is not a semantic retriever or RAG framework. It does not chunk documents,
generate embeddings, perform vector similarity search, or generate answers.

## Team-scoped storage

Every user receives a personal team and its writable filesystem storage. Users
may also create collaborative teams and add existing MARU users as members.

```text
Team
  └── TeamStorageLink
        └── SourceStorage
              └── files and directories
```

A team-owned storage is writable only by its owner team. Linked storages are
read-only. System storages such as `help` are automatically linked read-only to
personal teams. Every filesystem operation must first verify that the requesting
team has a storage link.

## Deterministic filesystem operations

The filesystem service currently provides the core operations that MCP and HTTP
transports can share:

- `list_tree`: stable path ordering, bounded depth, and a result limit
- `find_files`: exact file discovery with explicit glob filters
- `search_text`: literal or regular-expression content search with line and
  byte-column evidence
- safe path resolution that rejects absolute paths, `..`, and symlink escapes

File and content search always have a portable Python backend. If
[ripgrep](https://github.com/BurntSushi/ripgrep) (`rg`) is available, the default
`auto` mode selects it once at startup as a faster backend. MARU invokes `rg`
directly without a shell, disables ambient configuration and ignore files, uses
explicit case and glob options, and sorts output by path.

The active backend is returned by search tools and `/health`, so fallback never
silently changes the execution engine. Literal searches share the same result
shape. Regex syntax follows the selected engine: Python `re` for `python`, and
Rust regex syntax for `ripgrep`.

## Run

MARU is configured exclusively through environment variables and always applies
production validation. Start it with Uvicorn factory mode:

```bash
MARU_DATABASE_URL='postgresql://maru:password@localhost:5432/maru' \
MARU_SECRET_KEY='replace-with-at-least-32-characters' \
MARU_SALT='replace-with-at-least-16-characters' \
MARU_FILESYSTEM_ROOT='/srv/maru/files' \
uvicorn --factory maru_lang:create_app --host 0.0.0.0 --port 8000
```

Required variables:

- `MARU_DATABASE_URL`: PostgreSQL connection URL; PostgreSQL stores identity,
  team, and storage authorization metadata
- `MARU_SECRET_KEY`: at least 32 characters
- `MARU_SALT`: at least 16 characters
- `MARU_FILESYSTEM_ROOT`: absolute source-storage path

Optional variables:

- `MARU_PUBLIC_URL` (default `http://localhost:8000`): externally visible base
  URL used in MCP metadata and generated download URLs
- `MARU_DOWNLOAD_URL_EXPIRE_SECONDS` (default `300`): how long a generated URL
  may be used to start a download; it does not limit or interrupt transfer time
- `MARU_SEARCH_BACKEND` (`auto`, `python`, or `ripgrep`; default `auto`)
- `MARU_RIPGREP_PATH`: optional explicit path to the `rg` executable
- `MARU_ACCESS_TOKEN_EXPIRE_MINUTES` (default `120`)
- `MARU_REFRESH_TOKEN_EXPIRE_MINUTES` (default `43200`)
- `MARU_ALLOWED_DOMAINS` (comma-separated)
- `MARU_DELETE_FILES_ON_TEAM_DELETE` (default `false`)
- `MARU_SMTP_HOST`, `MARU_SMTP_PORT`, `MARU_SMTP_USERNAME`, `MARU_SMTP_PASSWORD`
- `MARU_EMAIL_TEMPLATE_DIR`

## Runtime architecture

The filesystem is the source of truth for file contents. PostgreSQL stores users,
teams, storage ownership, and team-to-storage access links. HTTP and MCP share one
application-owned context and the same authorization and filesystem services.

## MCP authentication

The Streamable HTTP endpoint is available at `/mcp`. Send the same short-lived
MARU access token used by the HTTP API:

```http
Authorization: Bearer <access-token>
```

The MCP server validates the JWT and its non-revoked `UserToken` database record
on every request. Every filesystem tool then checks both team membership and the
team-to-storage link. Access tokens are never accepted in tool arguments or URLs.

`get_file_download_url` returns a separate signed capability URL for a particular
file version. Its expiration controls the latest time a download request may
start. Once the server has accepted the request and begun sending the file, URL
expiration does not stop that active transfer. The default URL validity is five
minutes, and the allowed range is 30–900 seconds.

MARU currently acts as an OAuth-compatible protected resource and publishes its
protected-resource metadata, but login remains MARU's existing email OTP flow.
A full OAuth 2.1 authorization-server flow can be added later for clients that
require automatic browser-based discovery and authorization.
