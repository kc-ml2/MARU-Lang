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

MARU-Lang is a filesystem retrieval server exposed through HTTP API and MCP.
PostgreSQL and pgvector provide metadata and retrieval persistence.

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

## Storage model

Each user receives a personal team with an owned filesystem storage. System
storages such as `help` are read-only and automatically linked to every personal
team. Documents and chunks belong to storages, while `TeamStorageLink` controls
access without duplicating retrieval data.

PostgreSQL is the sole database and pgvector is the retrieval persistence layer.
HTTP and MCP share one application-owned service context.
