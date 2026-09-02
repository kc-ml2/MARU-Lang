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

**MARU-Lang is a team-based filesystem retriever for AI applications and agents.**

It is designed to provide the same retrieval capabilities through HTTP API and
MCP. Files are shared through team storage links, and every search is restricted
to storages accessible to the requesting team. PostgreSQL is the canonical
metadata and retrieval backend, with pgvector providing semantic search.

MARU provides retrieval orchestration, not answer generation. A separate
application or agent can use retrieved chunks to implement Retrieval-Augmented
Generation (RAG).
In that term, **retrieval-augmented** means that generation is supplemented with
information retrieved from an external knowledge source.

## Team-based retrieval

Every user receives a personal team and its writable filesystem storage. Users
may also create collaborative teams and add existing MARU users as members.

A team accesses documents through storage links:

```text
Team
  └── TeamStorageLink
        └── SourceStorage
              └── Document
                    └── DocumentChunk
```

A team-owned storage is writable only by its owner team. Linked storages are
read-only. System storages such as `help` are automatically linked read-only to
personal teams. Documents and chunks remain attached to their source storage,
so linking the same storage to multiple teams does not duplicate retrieval data.

## Stable, inspectable pipelines

MARU owns a stable pipeline order rather than exposing a general workflow
engine:

```text
Indexing:  scan → parse → chunk → embed → index
Retrieval: authorize → lexical → vector → fuse → results
```

AI agents can inspect the active configuration, change validated options, and
request a rerun from a specific indexing stage. They cannot reorder stages or
execute arbitrary code. Configuration changes and runs require owner-team admin
access; linked and system storages remain read-only.

Each storage keeps two tunable options—target chunk size and overlap—and every
run stores a snapshot of those values in PostgreSQL. Authentication, teams, and
storage management continue to work when no indexing executor is configured.
Concrete parsing, chunking, embedding, PostgreSQL indexing, base search, and MCP
tools are the next PoC layer.

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

- `MARU_DATABASE_URL`: PostgreSQL connection URL; PostgreSQL is the only DB
- `MARU_SECRET_KEY`: at least 32 characters
- `MARU_SALT`: at least 16 characters
- `MARU_FILESYSTEM_ROOT`: absolute source-storage path

Optional variables:

- `MARU_ACCESS_TOKEN_EXPIRE_MINUTES` (default `120`)
- `MARU_REFRESH_TOKEN_EXPIRE_MINUTES` (default `43200`)
- `MARU_ALLOWED_DOMAINS` (comma-separated)
- `MARU_DELETE_FILES_ON_TEAM_DELETE` (default `false`)
- `MARU_SMTP_HOST`, `MARU_SMTP_PORT`, `MARU_SMTP_USERNAME`, `MARU_SMTP_PASSWORD`
- `MARU_EMAIL_TEMPLATE_DIR`

## Runtime architecture

PostgreSQL is MARU's sole metadata database. HTTP and MCP share one
application-owned service context, the same optional indexing/retrieval
capabilities, and the same team-based access rules.
