"""KorDoc MCP loader - parse documents via a persistent KorDoc MCP server.

KorDoc (https://github.com/chrisryugj/kordoc) parses Korean document formats
(HWP/HWPX/HWPML, PDF, XLS/XLSX, DOCX) into Markdown. It is run locally as an
MCP server over stdio (`npx -y kordoc mcp`) and exposes a `parse_document` tool
that takes an absolute file path and returns the extracted text.

To avoid respawning the Node process for every document (slow under bulk
ingest), one server process is kept alive per event loop and reused. The MCP
stdio session lives inside a single dedicated task that owns its whole lifecycle
and serves parse requests off a queue — opening and closing the session in the
same task, which is required (anyio cancel scopes can't be exited from a
different task than they were entered). Requests are serialized; the KorDoc
parser is single-threaded CPU work anyway, so this also avoids piling up Node
processes. The session restarts transparently on transport failure or timeout.
"""
import asyncio
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from maru_lang.configs import get_config
from maru_lang.graph.ingest.exceptions import KordocParseError

# Name of the KorDoc MCP tool we call. Private to this client — kept local rather
# than in ingest/constants.py since nothing else references it.
PARSE_TOOL = "parse_document"


def _extract_text(result) -> str:
    """Join the text content blocks of an MCP tool result."""
    parts = []
    for block in getattr(result, "content", None) or []:
        if getattr(block, "type", None) == "text" and getattr(block, "text", None):
            parts.append(block.text)
    return "\n".join(parts).strip()


def _strip_header(text: str) -> str:
    """Drop KorDoc's `[meta]` + outline/warning header, keeping only the body.

    parse_document prepends a `[포맷: …]` meta line and optional `📑 문서 구조:` /
    `⚠️ 경고:` blocks (all single-newline separated), then `\\n\\n` + the Markdown
    body. So the first blank line separates header from body. Only strip when the
    text actually starts with the meta header, to avoid dropping real content if
    KorDoc's output format changes.
    """
    if not text.startswith("["):
        return text
    sep = text.find("\n\n")
    if sep == -1:
        return text
    return text[sep + 2:].strip()


class _KordocClient:
    """Per-process persistent KorDoc MCP session, reused across parse calls."""

    def __init__(self):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._requests: asyncio.Queue | None = None
        self._lock = asyncio.Lock()

    async def parse(self, file_path: Path) -> str:
        """Parse a file and return its Markdown body (header stripped).

        Raises:
            KordocParseError: On parse error, transport failure, or timeout.
        """
        timeout = get_config().kordoc_mcp_timeout
        loop = asyncio.get_running_loop()
        await self._ensure_worker(loop)

        fut: asyncio.Future = loop.create_future()
        await self._requests.put((file_path, fut))
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            # The Node process is likely stuck on this document — kill it so the
            # next call starts a fresh session instead of queueing behind a hang.
            await self._restart()
            raise KordocParseError(
                f"KorDoc timed out after {timeout}s parsing {file_path.name}"
            )

    async def close(self) -> None:
        """Shut the session down (e.g. on worker shutdown)."""
        await self._restart(_recreate=False)

    async def _ensure_worker(self, loop: asyncio.AbstractEventLoop) -> None:
        async with self._lock:
            if self._loop is not loop:
                # First use, or a different loop (new process/loop): reset.
                await self._stop_locked()
                self._loop = loop
            if self._task is None or self._task.done():
                self._requests = asyncio.Queue()
                self._task = loop.create_task(self._run(self._requests))

    async def _restart(self, _recreate: bool = True) -> None:
        async with self._lock:
            await self._stop_locked()
            if not _recreate:
                self._loop = None

    async def _stop_locked(self) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except BaseException:
                pass

    async def _run(self, requests: asyncio.Queue) -> None:
        """Own the MCP session for its whole lifetime and serve parse requests."""
        try:
            cfg = get_config()
            params = StdioServerParameters(
                command=cfg.kordoc_mcp_command,
                args=list(cfg.kordoc_mcp_args),
                env=None,
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    await self._serve(session, requests)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # Startup/transport failure: surface it to anyone still waiting
            # instead of letting them hang until their own timeout.
            self._fail_pending(requests, e)
        finally:
            self._fail_pending(requests, KordocParseError("KorDoc session closed"))

    async def _serve(self, session, requests: asyncio.Queue) -> None:
        while True:
            file_path, fut = await requests.get()
            if fut.done():  # caller already timed out / was cancelled
                continue
            try:
                result = await session.call_tool(
                    PARSE_TOOL, {"file_path": str(file_path.resolve())}
                )
            except Exception as e:
                # Treat any call failure as a possibly-dead transport: fail this
                # request and exit so the session is torn down and rebuilt.
                if not fut.done():
                    fut.set_exception(e)
                raise
            text = _extract_text(result)
            if fut.done():
                continue
            if getattr(result, "isError", False):
                fut.set_exception(
                    KordocParseError(text or f"KorDoc failed to parse {file_path.name}")
                )
            else:
                fut.set_result(_strip_header(text))

    @staticmethod
    def _fail_pending(requests: asyncio.Queue, exc: BaseException) -> None:
        while not requests.empty():
            try:
                _, fut = requests.get_nowait()
            except asyncio.QueueEmpty:
                break
            if not fut.done():
                fut.set_exception(exc)


_client = _KordocClient()


async def parse_with_kordoc(file_path: Path) -> str:
    """Parse a file via the persistent KorDoc MCP server, returning Markdown.

    Reuses one KorDoc server process per event loop; the call is bounded by
    kordoc_mcp_timeout. The first call may also download the KorDoc npm package.

    Raises:
        KordocParseError: On parse error, transport failure, or timeout.
    """
    return await _client.parse(file_path)


async def close_kordoc_client() -> None:
    """Tear down the persistent KorDoc session (call on process shutdown)."""
    await _client.close()
