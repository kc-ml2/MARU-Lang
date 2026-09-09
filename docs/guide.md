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

# MARU setup and integration guide

[← Product overview](../README.md)

This document is for operators, developers, and agents integrating MARU.

- [Quick start](#quick-start)
- [MCP tools](#mcp-tools)
- [Team management](#management-through-mcp)
- [External storage administration](#local-system-administration)
- [Configuration](#configuration-reference)
- [Security](#security-notes)

**A deterministic, team-scoped filesystem access layer for AI agents.**

MARU is a shared backend for applications and AI agents, not an end-user client.
HTTP provides identity, team, and storage management; MCP provides agent-facing
file discovery. Both use the same application services and authorization rules.
The current release uses MARU's own identities; external identity-provider
integration and delegated service accounts are not yet implemented.

MARU lets an AI agent find files in team storage using explicit filesystem
operations instead of semantic guesses. The agent can inspect a directory tree,
filter filenames, search exact text or regular expressions, and give the user a
short-lived URL to download the original file.

```text
Your request
    ↓
AI agent
    ↓ MCP tools
MARU: authorize → list/find/search → return evidence or download URL
    ↓
Team filesystem
```

MARU is useful when an agent needs fast, verifiable answers to questions such as:

- Which files match this exact name or glob?
- Where does this literal string occur?
- Which file contains a matching configuration key or code pattern?
- What is the path, size, and modification time of this file?
- Can I download the original file rather than receiving its contents in chat?

MARU is **not** a semantic retriever or RAG framework. It does not chunk files,
generate embeddings, rank by vector similarity, or generate answers.

## What using MARU looks like

A typical agent workflow is:

1. Call `list_my_teams` to discover your team IDs, then `list_storages` to see
   what the selected team can access.
2. Call `list_storage_tree` to understand the relevant directory structure.
3. Call `find_storage_files` to narrow candidates by path or filename glob.
4. Call `search_storage_text` to collect exact path, line, column, and text evidence.
5. Call `get_file_download_url` when the user needs the complete original file.

The agent chooses which tools to call. MARU performs only the explicit operation
requested and returns bounded, path-sorted results.

> Concrete end-user scenarios and example conversations will be added as the
> intended workflows are finalized.

## MCP tools

| Tool | Purpose |
| --- | --- |
| `list_my_teams` | Discover your teams, roles, and personal workspace |
| `get_team` | Inspect a team's details and members |
| `get_my_team_permissions` | Inspect your current permissions in a particular team |
| `add_team_member` | Immediately add an existing user to a collaboration team (team admin) |
| `list_storages` | List storages available to a team |
| `list_storage_tree` | Inspect a stable, depth-limited directory tree |
| `find_storage_files` | Find files using filename and include/exclude globs |
| `search_storage_text` | Search literal text or a regular expression |
| `stat_storage_path` | Inspect file, directory, or symlink metadata |
| `get_file_download_url` | Create a short-lived URL for the original file |

Except for `list_my_teams`, every tool is scoped by `team_id`; filesystem tools
also require `storage_id`.
MARU verifies both team membership and the team's link to that storage before
accessing the filesystem.

Search responses identify the engine that produced them:

```json
{
  "backend": "ripgrep",
  "results": [
    {
      "path": "src/settings.py",
      "line": 42,
      "byte_column": 5,
      "text": "DATABASE_URL = ..."
    }
  ],
  "truncated": false
}
```

## Quick start

### Requirements

- Python 3.11 or newer (the current implementation uses `enum.StrEnum`)
- PostgreSQL
- A filesystem directory MARU may manage
- SMTP configuration to deliver operator-issued API tokens by email
- Optional: [ripgrep](https://github.com/BurntSushi/ripgrep) for faster search

### Install

```bash
git clone https://github.com/kc-ml2/MARU-Lang.git
cd MARU-Lang
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Configure and run

Copy `config.example.yaml` to `/etc/maru/config.yaml`, replace credentials,
and restrict it with `chmod 600`. Python 3.11+ is required.

```bash
export MARU_CONFIG=/etc/maru/config.yaml
uvicorn --factory maru_lang:create_app --host 127.0.0.1 --port 8000
```

Put an HTTPS reverse proxy in front for remote clients. `server.public_url` must
be the externally reachable HTTPS base URL. The managed filesystem root must be
writable by the server user. Environment variables override YAML values; there
is no automatic `.env` loading. Unknown YAML keys are rejected.

Verify the server and selected search backend:

```bash
curl http://localhost:8000/health
```

```json
{
  "status": "ok",
  "filesystem_search": {
    "backend": "ripgrep",
    "version": "ripgrep 15.x.x",
    "regex_supported": true
  }
}
```

### Provision users and connect MCP

Start the server once to initialize tables, then run the trusted local CLI with
the same configuration and filesystem permissions:

```bash
maru --config /etc/maru/config.yaml add ji@kc-ml2.com -t ml2 -r admin
# Or export MARU_CONFIG once and omit --config:
maru add colleague@kc-ml2.com -t ml2 -r member
```

`add` registers the user if absent, provisions their personal workspace, and adds
them to the named collaborative team. New teams require the first user to be
`admin`; that user becomes owner. Personal teams cannot receive additional members.
Existing roles are not changed implicitly. Repeat calls for the same membership
are idempotent and do not issue another token unless `--issue-token` is supplied.
Operators must serialize provisioning operations.

A newly added membership receives a random API token. Its plaintext is flushed to
console **before** email delivery. Only its SHA-256 hash is stored in the database.
Tokens are user-scoped (all currently authorized teams), not bound to the `-t` team.
The operator can authenticate as that user: this is credential provisioning, not
proof of email ownership. There is no self-service signup, OTP, or refresh flow.

```text
Endpoint:      https://maru.example.com/mcp
Authorization: Bearer maru_<random-token>
Transport:     Streamable HTTP
```

Tokens have **no expiry by default** and require no refresh. Optional expiry and
individual revocation are supported:

```bash
maru token issue ji@kc-ml2.com --expires-in 90d
maru token list ji@kc-ml2.com
maru token revoke <token-id>
```

Issuing a replacement does not revoke previous tokens; revoke old IDs explicitly.
Listing never returns plaintext or hashes. Lost tokens cannot be recovered.
HTTP team/storage APIs accept the same Bearer token. Team permissions are checked
live on every operation; removing a team membership removes access to that team.

If SMTP is absent or fails, registration and token issuance remain committed and
the token is still available in console output. The CLI reports `email_status`
and exits with code **2** (partial delivery failure); do not blindly retry issuance.
Protect console output, mailboxes, configuration, and server credentials. Never
capture token output in shared CI logs. A leaked non-expiring token remains usable
until revoked. SMTP uses STARTTLS (normally port 587).

### Upgrading from OTP authentication

Old JWT access/refresh tokens are no longer accepted. `/auth/login`, OTP verify,
logout, and refresh routes have been removed. Issue API tokens for existing users
with `maru token issue`. Restart the updated server first to create the new
`apitoken` table. Legacy authentication tables are not automatically dropped;
back up the database and remove them separately if desired. Existing users, teams,
and storage links are retained. General schema migration support is still absent.
Remove obsolete salt and access/refresh lifetime keys from YAML. `MARU_SECRET_KEY`
is retained only for short-lived signed download URLs, not API-token validation.

## Team storage model

Each user receives a personal team and its writable storage. Users can also
create collaborative teams and invite existing MARU users.

Personal teams accept no additional members. Authorization also denies access
through any pre-existing non-owner personal-team membership (records are not
automatically deleted). Team discovery hides those memberships.

`manager_id` identifies the accountable team owner, not a separate permission
role. Access is checked through `TeamMember.role` (`admin` or `member`); ownership
does not bypass membership checks. Creators become admins, and owners cannot be
removed through the member-removal API. Ownership transfer and role editing are
not yet exposed. Team listing and detail responses include `manager_id` and
`is_personal`.

```text
Team
  └── TeamStorageLink
        └── SourceStorage
              └── files and directories
```

A storage owned by a team is writable only by that team. A storage linked from
another team is read-only. System storages, such as `help`, may be attached
read-only to personal teams.

The filesystem remains the source of truth for file contents. PostgreSQL stores
users, teams, storage ownership, access links, and authentication state.

> **Current scope:** MARU provisions server-local storage directories but does
> not yet expose a file upload API or MCP write tools. Files must currently be
> placed or mounted into the provisioned storage by the operator or another
> application.

## Management through MCP

Management support is being introduced incrementally. For now, an agent can use
`list_my_teams`, `get_team`, and `get_my_team_permissions` to inspect the user's
teams and management permissions. `add_team_member(team_id, email)` is the first
management mutation exposed through MCP. It immediately adds an already registered
user as a member; there is no acceptance step. Personal teams reject additions.
Other team and storage mutations remain HTTP-only.

The tool uses the same service and live admin checks as HTTP. Operator-issued API
tokens authenticate the caller; no separate management-token scope exists
yet. Tool annotations and approval instructions guide clients, but are not a
server-enforced human-approval mechanism.

Successful additions emit `maru.audit` INFO logs containing actor, team, and target
user IDs. Operators must configure logging to retain these records and serialize
extra fields. This is not a durable transactional audit ledger; rejected attempts
are not yet recorded. Email notification failure does not undo a successful
membership addition.

MARU admins are **team-scoped**, not server-wide superusers. Being an admin in one
team grants no privileges in another. Permission discovery is informational;
subsequent operations must check current membership and resource constraints
again. Personal teams do not allow additional members or team deletion.

## Managed and external storage

- **Managed**: MARU creates the directory for a team (or for system content such
  as `help`). File upload is not yet implemented.
- **External**: a local system operator registers an existing absolute directory.
  MARU reads it in place, without copying, provisioning, or deleting its contents.
  External storage is system-managed and read-only through MARU. Only explicitly
  shared teams can access it; "shared" does not mean publicly accessible.

Storage responses expose `storage_type` independently of `owner_type`. External
physical paths are only shown in the local administration CLI, not team responses.

### Local system administration

Start the server once to initialize a fresh database. With the same configuration/environment
and server filesystem access, install/update the CLI with `pip install -e .`:

```bash
maru admin list-teams
maru admin register-external --name "Company documents" --path /mnt/company-docs
maru admin list-storages
maru admin share --storage-id <returned-id> --team-id 12
maru admin unshare --storage-id <returned-id> --team-id 12
maru admin unregister-external --storage-id <returned-id>
```

Alternatively use `python -m maru_lang.cli admin ...`. This is a trusted local
operator entry point, not an MCP client or a team-admin privilege. Restrict access
to server credentials and the CLI environment. JSON output identifies the local
OS user for operational logging; it is not a tamper-proof audit record.

The registered directory must exist, must not use symlink path components, and
must not overlap MARU's managed root or another external storage. Use a read-only
OS mount and filesystem permissions when appropriate. There is no external-path
allowlist yet: registering paths is restricted operationally to trusted server
operators. Registration and sharing operations should be serialized by operators.
Unregistering requires removing all team shares first and deletes only metadata.
External storage cannot be registered or removed through team HTTP/MCP tools.

## Search backends

MARU always includes a portable Python search backend. The default `auto` mode
uses ripgrep when `rg` is available at startup and otherwise selects Python.
Backend selection happens once; MARU does not switch engines between requests.

```bash
# Automatically prefer ripgrep
MARU_SEARCH_BACKEND=auto

# Never require an external executable
MARU_SEARCH_BACKEND=python

# Require ripgrep and fail startup if it is unavailable
MARU_SEARCH_BACKEND=ripgrep

# Optionally use a specific binary
MARU_RIPGREP_PATH=/usr/local/bin/rg
```

Both engines return the same result shape and stable path ordering. Literal
searches have equivalent intent. Regex syntax depends on the active engine:
Python `re` for `python`, and Rust regex syntax for `ripgrep`. The active backend
is always shown in `/health` and search responses.

When using ripgrep, MARU invokes it without a shell and supplies explicit options:

- ignore ambient ripgrep configuration
- do not apply repository ignore files implicitly
- include hidden files
- sort results by path
- do not follow symlinks

## Download URLs

`get_file_download_url` produces a signed URL for one authorized file version:

```json
{
  "url": "https://maru.example/files/download?token=...",
  "path": "documents/report.pdf",
  "size": 1839201,
  "modified_at_ns": 1740000000000000000,
  "url_expires_at": "2025-09-02T12:05:00+00:00",
  "url_valid_for_seconds": 300
}
```

Expiration controls when a download may **start**. It is not a transfer timeout:
if an accepted download is still transferring when the URL expires, MARU does
not interrupt it. URLs are valid for five minutes by default, and a tool call may
request between 30 and 900 seconds.

MARU checks authorization again when the URL is used. If access was removed or
the file changed after URL creation, the original URL will no longer download a
different file version.

## Configuration reference

### Required

| Variable | Description |
| --- | --- |
| `MARU_DATABASE_URL` | PostgreSQL connection URL |
| `MARU_SECRET_KEY` | Download URL signing secret, at least 32 characters |
| `MARU_FILESYSTEM_ROOT` | Absolute path containing MARU storage |

### Optional

| Variable | Default | Description |
| --- | --- | --- |
| `MARU_CONFIG` | unset | YAML configuration file path |
| `MARU_PUBLIC_URL` | `http://localhost:8000` | Public base URL used in MCP metadata and download URLs |
| `MARU_DOWNLOAD_URL_EXPIRE_SECONDS` | `300` | Default validity of a generated download URL |
| `MARU_SEARCH_BACKEND` | `auto` | `auto`, `python`, or `ripgrep` |
| `MARU_RIPGREP_PATH` | PATH lookup | Explicit path to `rg` |
| `MARU_ALLOWED_DOMAINS` | unrestricted | Comma-separated allowed user email domains |
| `MARU_DELETE_FILES_ON_TEAM_DELETE` | `false` | Remove owned files when a team is deleted |
| `MARU_SMTP_HOST` | unset | SMTP host for token delivery |
| `MARU_SMTP_PORT` | `587` | SMTP port |
| `MARU_SMTP_USERNAME` | unset | SMTP username |
| `MARU_SMTP_PASSWORD` | unset | SMTP password |
| `MARU_EMAIL_TEMPLATE_DIR` | built in | Custom email-template directory |

## Security notes

- MCP and HTTP management requests require an operator-issued Bearer API token.
- Token expiry (when set) and server-side revocation are checked on every request.
- Filesystem access requires current team membership and a current storage link.
- Absolute paths, `..` traversal, and symlink escapes are rejected.
- Download capability URLs are separate from API tokens and expire quickly.
- Use HTTPS for every non-local deployment because download URLs are bearer
  capabilities and may appear in client or proxy logs.

MARU publishes protected-resource metadata for the MCP endpoint, but is not an
OAuth authorization server. Clients must support a manually configured Bearer
header; automatic browser login and refresh are not provided.
