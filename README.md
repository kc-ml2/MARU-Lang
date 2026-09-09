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

Give your AI agent access to the files your team already works with—without
copying entire documents into a conversation or building an embedding pipeline.

MARU helps agents browse folders, find filenames, search text, and return download
links to original files. Your agent decides what to look for; MARU returns actual
paths and matching text, within your team's permissions.

## What can I do with it?

- **Find files:** locate a document by name, folder, or filename pattern.
- **Check the evidence:** see which file and line contain the text you need.
- **Get the original:** download a file instead of receiving its contents in chat.
- **Share with a team:** make a storage available only to the teams you choose.
- **Manage through your agent:** team admins can inspect their team and add
  already registered colleagues through MCP.

MARU is a backend for your applications and MCP-compatible agents, not a chat app
or an answer-generating assistant. It searches explicit filenames and text rather
than ranking documents by semantic similarity.

## Use new storage or keep your existing files

| | How it works |
| --- | --- |
| **MARU-managed storage** | MARU creates a storage directory for your team. An operator currently places files there; uploads are not yet supported. |
| **Existing storage** | A server operator registers an existing folder and shares it with selected teams. MARU reads the files in place, without copying them. |

External storage is read-only through MARU. Removing its registration does not
delete the original files. “Shared” means accessible to selected teams—not public
to everyone.

## What does using it look like?

Once connected, you might ask your agent:

> Find `report.pdf` in my team's storage and give me a download link.

The agent discovers your teams and storages, finds matching paths, and requests a
link for the file you choose. For text files, it can also search the contents and
show the matching lines.

Download links expire after a short period. Expiration prevents new downloads;
it does not interrupt a download already in progress.

## Getting started

**Using a server someone else runs?** Ask your operator for the MARU server URL,
and a personal API token, then connect your MCP client with that token. Use your own account;
your team membership determines which storages you can access.

**Running MARU for your team?** Follow the [setup and integration guide](docs/guide.md).
It covers YAML configuration, CLI user/token provisioning, MCP tools, registering existing folders, and team
sharing. Python search is included; ripgrep is an optional faster backend.

## Current scope

MARU is under development. File discovery, original-file downloads, external
storage registration, and basic team management are implemented. File uploads,
file editing tools, and automatic browser-based MCP authorization are not yet
available. PDF and other binary files can be found by filename and downloaded;
MARU does not extract their contents for text search.

For developers, operators, and agents integrating MARU, see the
[technical guide](docs/guide.md).
