<p align="center"><strong>MARU-Lang</strong></p>

# MARU-Lang

MARU-Lang is being redesigned as a **filesystem retrieval server** exposed
through both an HTTP API and MCP. LLM generation, LangGraph, the old ingest
pipeline, generated applications, and the project CLI have been removed.

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

## Storage direction

PostgreSQL is the sole database and retrieval persistence target. The project is
prepared for pgvector; the embedding dimension and search repository will be
added together with the new indexing/retrieval contract. HTTP and MCP will share
one application-owned service context.
