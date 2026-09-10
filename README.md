<p align="center">
  <picture>
    <source media="(prefers-color-scheme: light)" srcset="https://ml2-ai-product.s3.ap-northeast-2.amazonaws.com/MARU/MARU_Black_full.png">
    <source media="(prefers-color-scheme: dark)" srcset="https://ml2-ai-product.s3.ap-northeast-2.amazonaws.com/MARU/MARU_White_full.png">
    <img alt="MARU" src="https://ml2-ai-product.s3.ap-northeast-2.amazonaws.com/MARU/MARU_black.png" width="90%">
  </picture>
</p>

# MARU-Lang

**A team-scoped filesystem MCP server for AI agents.**

Connect your agent to your team's files. MARU browses folders, finds filenames,
searches text with ripgrep, and returns short-lived download links—without an
embedding pipeline, vector database, or LLM API key.

> Find `report.pdf` in my team's storage and give me a download link.

## How it works

```text
MCP client → API token → team permissions → filesystem
```

- **Existing folders:** register and share them with selected teams; files stay
  in place and are read-only through MARU.
- **Managed storage:** MARU creates team directories; operators place files there.
- **Simple access:** operators provision users and issue revocable API tokens.
  Tokens do not expire by default and need no refresh.

MARU returns paths and matching text, not generated answers or semantic rankings.
It currently supports file discovery and downloads, not uploads or file editing.
PDFs can be found and downloaded, but their contents are not extracted for search.

## Run a server

Requires **Python 3.11+, PostgreSQL, and ripgrep**. The included Compose file runs
PostgreSQL 17; MARU runs on the host. SMTP is optional for emailing tokens.

After installing and configuring the database and `config.yaml`:

```bash
maru serve
```

MARU reads `./config.yaml` automatically and serves HTTP/MCP on
`127.0.0.1:8000`. Use an HTTPS reverse proxy for remote access.

**[Follow the setup guide →](docs/guide.md)**

## Connect a client

Ask your operator for the server URL and your API token. Configure a client that
supports **Streamable HTTP with a custom Authorization header**:

```text
URL:           https://maru.example.com/mcp
Authorization: Bearer maru_<your-token>
```

Then ask the agent to list your teams and storages. There is no browser login,
OTP, or automatic OAuth setup; the token grants your current user permissions.
Keep it private.

[Setup and operations](docs/guide.md) · [MIT license](LICENSE)
