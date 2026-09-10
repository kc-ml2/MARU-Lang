# MARU setup and operations

[← README](../README.md)

MARU runs on the host; PostgreSQL stores users, teams, storage links, and token
hashes. Files remain on the filesystem. Commands below assume a Linux server.

## 1. Install

Requirements: **Python 3.11+, ripgrep, PostgreSQL**, and a writable managed-files
directory. Docker Compose is optional if you already have PostgreSQL.

```bash
git clone --branch feat/filesystem-retrieval-server https://github.com/kc-ml2/MARU-Lang.git
cd MARU-Lang
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Ubuntu / Debian
sudo apt-get update
sudo apt-get install -y ripgrep
```

## 2. Start PostgreSQL

In `docker-compose.yaml`, replace `POSTGRES_PASSWORD: "CHANGE_ME"` with a strong
password. `openssl rand -hex 32` generates a URL-safe value.

```bash
chmod 600 docker-compose.yaml
docker compose up -d postgres
docker compose ps
```

Wait for `healthy`. For diagnostics: `docker compose logs --tail=50 postgres`.

- PostgreSQL 17 binds to **127.0.0.1:5432**, not external interfaces.
- Data persists in **`maru-postgres-data`**, separate from team files.
- `docker compose down` preserves data; **`docker compose down -v` deletes it**.
- Changing the Compose password does not update an already initialized DB.
- Separate deployments need different volume names and host ports.

Do not commit real passwords. You may keep a private Compose file outside Git
and use `docker compose -f /path/docker-compose.yaml ...`, or optionally use
`${POSTGRES_PASSWORD}` with a protected `.env`. Docker administrators can inspect
container environment values. Back up the DB; a volume is not a backup.

## 3. Configure and run

```bash
cp config.example.yaml config.yaml
chmod 600 config.yaml

sudo mkdir -p /srv/maru/files
sudo chown "$(id -un):$(id -gn)" /srv/maru/files
```

Edit `config.yaml` (Git-ignored):

```yaml
database:
  url: postgresql://maru:YOUR_DB_PASSWORD@127.0.0.1:5432/maru

auth:
  # Generate separately with: openssl rand -hex 32
  secret_key: "YOUR_RANDOM_SECRET_AT_LEAST_32_CHARACTERS"
  allowed_domains: [kc-ml2.com]

filesystem:
  root: /srv/maru/files

server:
  public_url: http://localhost:8000

# Optional token delivery via STARTTLS
# smtp:
#   host: smtp.example.com
#   port: 587
#   username: maru@example.com
#   password: YOUR_SMTP_PASSWORD
```

Use the same DB password as Compose. Start MARU:

```bash
maru serve
```

In another terminal:

```bash
curl http://127.0.0.1:8000/health
```

Expect `status: ok` and `filesystem_search.backend: ripgrep`. The first startup
creates DB tables. Keep this process running while using the CLI in another
terminal with the same virtual environment and working directory.

**Configuration rules**

- File selection: `maru --config /path/config.yaml ...` → `MARU_CONFIG` →
  `./config.yaml` in the **current working directory**.
- Explicitly selected missing/invalid files fail; they do not fall back.
- Environment variables override YAML. Environment-only setup still works;
  `.env` is not automatically loaded by MARU.
- Run from a trusted directory. Unknown YAML keys are rejected.

`maru serve` uses Uvicorn internally. Default bind: `127.0.0.1:8000`; optional
flags: `--host` and `--port`. Direct Uvicorn factory execution remains supported.

## 4. Register users and connect MCP

```bash
maru add ji@kc-ml2.com -t ml2 -r admin
maru add colleague@kc-ml2.com -t ml2 -r member
```

`add` creates missing users and their personal workspaces, then adds them to the
named team. A new team requires `admin`; that user becomes its owner. Existing
roles are not changed implicitly. Repeating the same membership does not issue
another token unless `--issue-token` is supplied.

New memberships receive an API token, **printed before email delivery**. If SMTP
is absent or fails, registration and token issuance still succeed; the CLI reports
`email_status` and exits **2**. Save the printed token rather than blindly retrying.

Configure your MCP client:

```text
URL:           https://maru.example.com/mcp
Transport:     Streamable HTTP
Authorization: Bearer maru_<token>
```

The client must support a manually configured Bearer header. There is no OTP,
self-service signup, OAuth browser login, or refresh flow. HTTP management APIs
accept the same token. An API token covers **all teams currently accessible to
its user**, not just the team passed to `-t`.

### Token management

```bash
maru token issue ji@kc-ml2.com                   # No expiry
maru token issue ji@kc-ml2.com --expires-in 90d   # Optional expiry
maru token list ji@kc-ml2.com                    # IDs and status only
maru token revoke <token-id>
```

Tokens do not expire by default. Only hashes are stored; lost tokens cannot be
recovered. Issuing another token does **not** revoke old ones. Anyone holding a
token can act as that user until expiry or revocation—protect mailboxes and
console output, and never capture tokens in shared CI logs.

## 5. Share an existing folder

```bash
maru admin list-teams
maru admin register-external --name "Company documents" --path /mnt/company-docs
maru admin list-storages
maru admin share --storage-id <storage-id> --team-id <team-id>
```

The directory must exist and be readable by the MARU process. It must have no
symlink path components and must not overlap the managed root or another external
storage. Files are read in place, not copied. Use read-only OS mounts where useful.

To remove access or registration:

```bash
maru admin unshare --storage-id <storage-id> --team-id <team-id>
maru admin unregister-external --storage-id <storage-id>
```

Remove all shares before unregistering. Unregistering removes metadata, **not
original files**. These commands are trusted local operator operations, not MCP
team-admin privileges. Restrict server credentials and serialize provisioning and
storage registration/sharing operations; there is no external-path allowlist.

## Deployment checklist

- Put an **HTTPS reverse proxy** in front of MARU for non-local use. Set
  `server.public_url` to that public HTTPS base URL and restart MARU; generated
  download links use it. Keep PostgreSQL private.
- For a local client test, use `ssh -N -L 8000:127.0.0.1:8000 user@server`, set
  `public_url: http://localhost:8000`, and connect to `http://localhost:8000/mcp`.
  Cloud-hosted clients cannot reach your local SSH tunnel.
- Run MARU under systemd or another process supervisor. Set its working directory
  or use `maru --config /absolute/path/config.yaml serve`. Do not use reload mode.
- Back up PostgreSQL and managed files separately. Shared folders may include
  hidden credentials such as `.env`; do not expose sensitive directories.

## MCP tools and permissions

| Tool | Purpose |
| --- | --- |
| `list_my_teams` | Discover teams and roles |
| `get_team` | Inspect team details and members |
| `get_my_team_permissions` | Inspect current permissions |
| `add_team_member` | Add an existing user immediately (team admin) |
| `list_storages` | List team-accessible storages |
| `list_storage_tree` | Browse directories |
| `find_storage_files` | Find filenames/globs |
| `search_storage_text` | Search literal text or regex |
| `stat_storage_path` | Inspect path metadata |
| `get_file_download_url` | Generate a short-lived file link |

Start with `list_my_teams`, then `list_storages`. Other tools require `team_id`;
filesystem tools also require `storage_id`. Every operation checks current
membership and storage access. Team admins have no server-wide privileges.

Personal teams cannot receive other members. Ownership does not bypass role
checks, and owners cannot be removed through the member-removal API. Role changes
and ownership transfer are not currently exposed. File uploads/edits are not
implemented; operators place files in managed directories.

MCP member addition needs no acceptance step; notification failure does not undo
it. Tool approval hints are not server-enforced approval. Successful additions emit
`maru.audit` INFO records; configure logging to retain their extra fields. This is
not a durable audit ledger and does not record rejected attempts. Other team/storage
mutations are HTTP-only, except external registration, which is CLI-only.

## Search and downloads

**Search:** ripgrep is required; no fallback exists. Searches are path-sorted,
include hidden files, ignore repository/ambient rg configuration, and do not
follow symlinks. Regex uses Rust regex syntax. `/health` reports the rg version.
Search results contain `path`, `line`, `byte_column`, and `text`.

- Output is streamed with a 10-second deadline and an 8 MiB stdout/stderr budget.
- Result/output limits stop the child and return `truncated: true`; timeouts and
  execution failures return errors. Repeated result text has an estimated 8 MiB
  content budget. These are not hard limits on total memory or JSON response size.
- Newlines in filenames are preserved. Non-UTF-8 text uses replacement characters;
  columns still refer to original bytes. Non-UTF-8 filenames are skipped.
- PDF/binary files can be found and downloaded, but their text is not extracted.

**Downloads:** signed URLs default to 5 minutes; tools may request 30–900 seconds.
Expiry prevents new downloads, not an in-progress transfer. Access and file version
are checked again when the link is used. Links are bearer credentials too: protect
them from public logs. They are separate from API tokens.

## Configuration reference

| YAML key | Environment override | Default / requirement |
| --- | --- | --- |
| `database.url` | `MARU_DATABASE_URL` | Required PostgreSQL URL |
| `auth.secret_key` | `MARU_SECRET_KEY` | Required, ≥32 characters; download signing only |
| `auth.allowed_domains` | `MARU_ALLOWED_DOMAINS` | Unrestricted; YAML list / env comma-separated |
| `filesystem.root` | `MARU_FILESYSTEM_ROOT` | Required absolute writable path |
| `filesystem.ripgrep_path` | `MARU_RIPGREP_PATH` | `rg` from PATH |
| `filesystem.delete_files_on_team_delete` | `MARU_DELETE_FILES_ON_TEAM_DELETE` | `false` |
| `server.public_url` | `MARU_PUBLIC_URL` | `http://localhost:8000` |
| `server.download_url_expire_seconds` | `MARU_DOWNLOAD_URL_EXPIRE_SECONDS` | `300` |
| `smtp.host` | `MARU_SMTP_HOST` | Unset |
| `smtp.port` | `MARU_SMTP_PORT` | `587` |
| `smtp.username` | `MARU_SMTP_USERNAME` | Unset |
| `smtp.password` | `MARU_SMTP_PASSWORD` | Unset |
| `smtp.template_dir` | `MARU_EMAIL_TEMPLATE_DIR` | Built-in notification template |

## Upgrade notes

- Remove `filesystem.search_backend` from older YAML files; ripgrep is now required.
- OTP/login/refresh endpoints and JWT user authentication have been removed. Start
  the updated server, then use `maru token issue` for existing users. Remove old
  salt and access/refresh lifetime keys from YAML; keep the download signing key.
- Startup creates missing tables but is not a general schema migration system.
  Legacy authentication tables are not automatically dropped. Back up before upgrades.
- Do not use a PostgreSQL 16 data volume with image 17 directly; use a supported
  upgrade or backup/restore procedure.
