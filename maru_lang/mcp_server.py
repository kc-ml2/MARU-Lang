"""Authenticated MCP tools for deterministic filesystem access."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP

from maru_lang.context import AppContext
from maru_lang.core.relation_db.models.auth import User, UserToken
from maru_lang.services.auth import is_token_valid
from maru_lang.services.download import create_download_url
from maru_lang.services.filesystem import (
    authorized_storage_root,
    list_tree,
    stat_path,
)

MCP_SCOPE = "filesystem:read"


class MaruTokenVerifier(TokenVerifier):
    """Validate existing MARU access tokens, including server-side revocation."""

    def __init__(self, context: AppContext):
        self.context = context

    async def verify_token(self, token: str) -> AccessToken | None:
        payload = self.context.tokens.decode(token)
        if payload is None or payload.get("sub") is None:
            return None
        try:
            user_id = int(payload["sub"])
        except (TypeError, ValueError):
            return None
        if not await User.exists(id=user_id):
            return None
        if not await is_token_valid(token, UserToken, tokens=self.context.tokens):
            return None
        db_token = await UserToken.get(token_hash=self.context.tokens.hash(token))
        return AccessToken(
            token=token,
            client_id=db_token.device_id,
            scopes=[MCP_SCOPE],
            expires_at=int(db_token.expires_at.timestamp()),
            subject=str(user_id),
        )


async def _request_user() -> User:
    access_token = get_access_token()
    if access_token is None or access_token.subject is None:
        raise PermissionError("MCP bearer authentication is required")
    user = await User.get_or_none(id=int(access_token.subject))
    if user is None:
        raise PermissionError("authenticated user no longer exists")
    return user


async def _storage_root(
    context: AppContext, team_id: int, storage_id: str
) -> Path:
    return await authorized_storage_root(
        context.settings.filesystem_root,
        team_id=team_id,
        storage_id=storage_id,
        requester=await _request_user(),
    )


def create_mcp_server(context: AppContext) -> FastMCP:
    """Build MARU's stateless Streamable HTTP MCP resource server."""
    public_url = context.settings.public_url
    server = FastMCP(
        "MARU Filesystem",
        instructions=(
            "Use explicit team-scoped tools to inspect files. Results are bounded and "
            "path-sorted. Start with list_storages, then list_tree or find_files, and "
            "use search_text for exact content evidence."
        ),
        token_verifier=MaruTokenVerifier(context),
        auth=AuthSettings(
            issuer_url=f"{public_url}/",
            resource_server_url=f"{public_url}/mcp",
            required_scopes=[MCP_SCOPE],
        ),
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )

    @server.tool(description="List storages accessible to one of the user's teams.")
    async def list_storages(team_id: int) -> dict[str, object]:
        from maru_lang.services.authorization import require_team_member
        from maru_lang.services.storage import list_team_storages

        user = await _request_user()
        await require_team_member(team_id, user)
        storages = await list_team_storages(team_id)
        return {
            "results": [
                {
                    "storage_id": storage.id,
                    "name": storage.name,
                    "owner_type": storage.owner_type.value,
                    "access": "owner" if storage.owner_team_id == team_id else "read",
                }
                for storage in storages
            ]
        }

    @server.tool(description="Return a stable, depth-limited storage tree.")
    async def list_storage_tree(
        team_id: int,
        storage_id: str,
        path: str = ".",
        max_depth: int = 2,
        max_results: int = 500,
    ) -> dict[str, object]:
        root = await _storage_root(context, team_id, storage_id)
        result = await asyncio.to_thread(
            list_tree,
            root,
            path=path,
            max_depth=max_depth,
            max_results=max_results,
        )
        return {"results": list(result.results), "truncated": result.truncated}

    @server.tool(description="Find files using explicit glob filters.")
    async def find_storage_files(
        team_id: int,
        storage_id: str,
        path: str = ".",
        name_glob: str | None = None,
        include_globs: list[str] | None = None,
        exclude_globs: list[str] | None = None,
        max_results: int = 200,
    ) -> dict[str, object]:
        root = await _storage_root(context, team_id, storage_id)
        result = await asyncio.to_thread(
            context.search.find_files,
            root,
            path=path,
            name_glob=name_glob,
            include_globs=include_globs or (),
            exclude_globs=exclude_globs or (),
            max_results=max_results,
        )
        return {
            "backend": result.backend,
            "results": list(result.results),
            "truncated": result.truncated,
        }

    @server.tool(description="Return metadata for one file, directory, or symlink.")
    async def stat_storage_path(
        team_id: int,
        storage_id: str,
        path: str,
    ) -> dict[str, object]:
        root = await _storage_root(context, team_id, storage_id)
        return await asyncio.to_thread(stat_path, root, path=path)

    @server.tool(
        description=(
            "Create a short-lived signed URL for downloading one file. URL expiration "
            "only limits when a download may start; it does not stop an active transfer."
        )
    )
    async def get_file_download_url(
        team_id: int,
        storage_id: str,
        path: str,
        expires_in_seconds: int | None = None,
    ) -> dict[str, object]:
        return await create_download_url(
            context,
            requester=await _request_user(),
            team_id=team_id,
            storage_id=storage_id,
            path=path,
            expires_in_seconds=expires_in_seconds,
        )

    @server.tool(description="Search text and return exact path, line, byte column, and evidence.")
    async def search_storage_text(
        team_id: int,
        storage_id: str,
        pattern: str,
        path: str = ".",
        mode: Literal["literal", "regex"] = "literal",
        case_sensitive: bool = True,
        include_globs: list[str] | None = None,
        exclude_globs: list[str] | None = None,
        max_results: int = 200,
    ) -> dict[str, object]:
        root = await _storage_root(context, team_id, storage_id)
        result = await asyncio.to_thread(
            context.search.search_text,
            root,
            pattern,
            path=path,
            mode=mode,
            case_sensitive=case_sensitive,
            include_globs=include_globs or (),
            exclude_globs=exclude_globs or (),
            max_results=max_results,
        )
        return {
            "backend": result.backend,
            "results": list(result.results),
            "truncated": result.truncated,
        }

    return server
