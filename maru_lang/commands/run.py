"""Run command — start server + interactive WebSocket chat CLI."""
import asyncio
import json
import os
import signal
import subprocess
import sys
import websockets
from contextlib import nullcontext
from pathlib import Path

import httpx
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion, PathCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import InMemoryHistory
from rich.console import Console
from rich.markdown import Markdown
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

console = Console()

# Slash commands available in the chat REPL (used for autocomplete + help).
_SLASH_COMMANDS = [
    "/ingest", "/team", "/scope", "/anchor", "/status", "/retry", "/llms", "/graphs", "/function", "/help", "/clear", "/quit", "/exit",
]


class _ChatCompleter(Completer):
    """Context-aware completion for the chat REPL.

    - bare `/...`      → slash command names
    - `/ingest <path>` → filesystem path completion
    - `/function <x>`  → feedback | off
    - `/team <names>`  → current team names (comma-separated)
    """

    def __init__(self, teams_getter):
        self._path = PathCompleter(expanduser=True)
        self._teams_getter = teams_getter  # callable -> list[str]

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return

        if " " not in text:  # still typing the command itself
            for cmd in _SLASH_COMMANDS:
                if cmd.startswith(text):
                    yield Completion(cmd, start_position=-len(text))
            return

        cmd, _, arg = text.partition(" ")
        if cmd == "/ingest":
            sub = Document(arg, cursor_position=len(arg))
            yield from self._path.get_completions(sub, complete_event)
        elif cmd == "/function":
            for opt in ("feedback", "off"):
                if opt.startswith(arg.strip()):
                    yield Completion(opt, start_position=-len(arg))
        elif cmd in ("/scope", "/anchor"):
            for opt in ("team", "all") if cmd == "/scope" else ("on", "off"):
                if opt.startswith(arg.strip()):
                    yield Completion(opt, start_position=-len(arg))
        elif cmd in ("/team", "/graphs"):
            # /graphs completes the team name (first arg) too.
            if cmd == "/graphs" and " " in arg:
                return
            frag = arg.rsplit(",", 1)[-1].lstrip()
            for name in self._teams_getter():
                if name.startswith(frag):
                    yield Completion(name, start_position=-len(frag))


class _QuitSignal(Exception):
    pass


def _parse_edit_command(line: str) -> dict:
    """Parse a doc-graph edit command line into a resume op dict.

    Grammars: `edit <id> <feedback>` | `add [after <id>] <text>` |
    `delete <id>` | `reorder <id,id,..>` | `finalize` (default).
    """
    parts = (line or "").strip().split(maxsplit=1)
    if not parts:
        return {"op": "finalize"}
    cmd = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""
    if cmd == "edit":
        bid, _, fb = rest.partition(" ")
        return {"op": "edit", "block_id": bid.strip(), "feedback": fb.strip()}
    if cmd == "delete":
        return {"op": "delete", "block_id": rest.strip()}
    if cmd == "reorder":
        return {"op": "reorder", "order": [x.strip() for x in rest.split(",") if x.strip()]}
    if cmd == "add":
        after = None
        if rest.lower().startswith("after "):
            after_id, _, rest = rest[len("after "):].partition(" ")
            after = after_id.strip()
        return {"op": "add", "after_block_id": after, "content": rest.strip()}
    return {"op": "finalize"}


def _canvas_block_texts(canvas: dict) -> dict:
    """Map block_id -> text for every block in a canvas payload (for diffing)."""
    out = {}
    for section in (canvas or {}).get("sections", []):
        for b in section.get("blocks", []):
            out[str(b.get("block_id"))] = b.get("text", "")
    return out


def _render_canvas(canvas: dict, prev: dict | None) -> None:
    """Print the canvas (sections→blocks) to the terminal.

    When `prev` is given, mark what changed since the last render: new blocks get
    a green ＋, edited blocks a yellow ~, deleted block_ids a trailing note. The
    first render of a doc passes prev=None, so it prints clean with no markers.
    """
    prev_texts = _canvas_block_texts(prev) if prev is not None else None

    title = canvas.get("title") or canvas.get("metadata", {}).get("title") or ""
    if title:
        console.print(f"[bold underline]{title}[/bold underline]")
    parties = (canvas.get("metadata") or {}).get("parties") or []
    if parties:
        shown = "  ·  ".join(
            f"{p.get('label', '')}: {p.get('name') or '(미입력)'}" for p in parties
        )
        console.print(f"[dim]{shown}[/dim]")

    for section in canvas.get("sections", []):
        art = section.get("metadata", {}).get("article_no", "")
        head = " ".join(x for x in [art, section.get("title", "")] if x)
        if head:
            console.print(f"[bold cyan]{head}[/bold cyan]")
        for b in section.get("blocks", []):
            bid = str(b.get("block_id"))
            text = b.get("text", "")
            refs = b.get("source_refs", [])
            ref_s = f" [dim](출처 {len(refs)})[/dim]" if refs else ""
            if prev_texts is None:
                tag, style = "  ", None
            elif bid not in prev_texts:
                tag, style = "[green]＋[/green] ", "green"
            elif prev_texts[bid] != text:
                tag, style = "[yellow]~[/yellow] ", "yellow"
            else:
                tag, style = "  ", None
            body = f"[{style}]{text}[/{style}]" if style else text
            console.print(
                f"{tag}[bold]{bid}[/bold] [dim]{b.get('block_type')}[/dim]{ref_s}\n    {body}\n"
            )

    if prev_texts is not None:
        removed = [bid for bid in prev_texts if bid not in _canvas_block_texts(canvas)]
        if removed:
            console.print(f"[red]삭제됨: {', '.join(removed)}[/red]")

    missing = canvas.get("missing_terms", [])
    if missing:
        labels = ", ".join(m.get("label", "?") for m in missing)
        console.print(f"[yellow]미정 항목: {labels}[/yellow]")


def _collect_parties(missing: list[dict]) -> dict:
    """Interactively collect 갑/을 party info → a `set_parties` resume op.

    Mirrors the browser's parties form: one prompt group per still-blank party,
    each with 상호/성명·대표자·주소. Blank answers are kept (skipped) so the loop
    stays fast; the server matches by `label`.
    """
    parties = []
    for p in missing:
        label = p.get("label") or "당사자"
        role = f" ({p.get('role')})" if p.get("role") else ""
        console.print(f"[bold]{label}{role}[/bold] [dim](엔터로 건너뛰기)[/dim]")
        parties.append({
            "label": p.get("label"),
            "name": Prompt.ask("  상호/성명", default="").strip(),
            "representative": Prompt.ask("  대표자", default="").strip(),
            "address": Prompt.ask("  주소", default="").strip(),
        })
    return {"op": "set_parties", "parties": parties}


def _collect_terms(missing_terms: list[dict]) -> dict:
    """Interactively collect undetermined values → a `set_terms` resume op.

    One prompt per missing_term (label + description); the server fills each into
    the doc's {{label}} token and drops it from missing_terms. Blank answers are
    skipped (that term stays open).
    """
    terms = []
    for t in missing_terms:
        label = t.get("label")
        if not label:
            continue
        desc = f" [dim]— {t.get('description')}[/dim]" if t.get("description") else ""
        console.print(f"[bold]{label}[/bold]{desc}")
        value = Prompt.ask("  값 (엔터로 건너뛰기)", default="").strip()
        if value:
            terms.append({"label": label, "value": value})
    return {"op": "set_terms", "terms": terms}


def _message_payload(
    content: str, scope: str, current_teams: list[str], team_map: dict[str, int],
    verbose: bool = False, anchor_only: bool = False,
) -> dict:
    """Build the chat `message` payload, scoping document search per `scope`.

    - scope == "team": include `team_ids` for the currently selected teams, so
      the server searches only those teams' documents.
    - scope == "all": omit `team_ids` — the server falls back to every team the
      CLI admin user can access (all accumulated memberships).
    - verbose: ask the server to stream every node's LLM tokens (debug).
    - anchor_only: doc graph grounds on the chosen anchor only (skip fuzzy RAG).
    """
    payload = {"type": "message", "content": content}
    if scope == "team":
        team_ids = [team_map[name] for name in current_teams if name in team_map]
        if team_ids:
            payload["team_ids"] = team_ids
    if verbose:
        payload["verbose"] = True
    if anchor_only:
        payload["anchor_only"] = True
    return payload


async def run_session(
    team_names: list[str],
    host: str,
    port: int,
    worker_count: int = 0,
    attach: bool = False,
    verbose: bool = False,
):
    """Main entry: start server, connect WebSocket, run REPL.

    When worker_count > 0 (and the task queue is enabled) that many ARQ ingest
    workers are co-launched as sibling subprocesses and torn down with the server.

    With attach=True no server (or worker) is spawned — the REPL connects to an
    already-running maru server (e.g. a systemd `maru serve`) and leaves it
    running on exit. This is safe because the REPL is a pure HTTP/WS client:
    all DB work (schema setup, admin bootstrap, graph compilation) lives in the
    server process, which the running service has already done.
    """
    base_url = f"http://{host}:{port}"
    ws_url = f"ws://{host}:{port}/chat/connect"

    # 1. Start server — or attach to one that's already running.
    server_proc = None
    worker_procs = []
    if attach:
        console.print(f"[dim]Attaching to running server at {host}:{port}...[/dim]")
    else:
        server_proc = _start_server(host, port)
        console.print(f"[dim]Starting server on {host}:{port}...[/dim]")
        # 1b. Optionally co-launch ingest worker(s).
        worker_procs = _start_workers(worker_count)

    try:
        # 2. Wait for server ready (attach: just verify it's reachable)
        if not await _wait_for_health(base_url, timeout=5 if attach else 30):
            if attach:
                console.print(
                    f"[red]No maru server responding at {base_url}.[/red]\n"
                    "Is the service running? (systemctl status <service>) "
                    "Or drop --attach to start one here."
                )
            else:
                console.print("[red]Server failed to start within 30 seconds.[/red]")
                # Show server stderr for debugging
                if server_proc.stderr:
                    stderr = server_proc.stderr.read()
                    if stderr:
                        console.print(f"[red]Server log:[/red]\n{stderr.decode(errors='replace')}")
            return

        console.print("[green]Server ready.[/green]\n")

        # 3. Connect and run REPL
        current_teams = list(team_names)
        await _run_repl(base_url, ws_url, current_teams, verbose=verbose)

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
    finally:
        for p in worker_procs:
            _stop_server(p)
        if worker_procs:
            console.print(f"[dim]Worker(s) stopped ({len(worker_procs)}).[/dim]")
        if server_proc is not None:
            _stop_server(server_proc)
            console.print("[dim]Server stopped.[/dim]")
        elif attach:
            console.print("[dim]Detached (server left running).[/dim]")


def _start_server(host: str, port: int) -> subprocess.Popen:
    """Start uvicorn as a background subprocess."""
    env = os.environ.copy()
    cwd = os.getcwd()
    python_path = env.get("PYTHONPATH", "")
    maru_app_path = os.path.join(cwd, "maru_app")
    paths = [cwd]
    if python_path:
        paths.append(python_path)
    env["PYTHONPATH"] = os.pathsep.join(paths)

    # Use package-style import so relative imports in maru_app/ work
    app_module = "maru_app.main:app" if os.path.exists(maru_app_path) else "main:app"

    cmd = [
        sys.executable, "-m", "uvicorn",
        app_module,
        "--host", host,
        "--port", str(port),
        "--log-level", "warning",
    ]

    return subprocess.Popen(
        cmd,
        env=env,
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _start_workers(count: int) -> list:
    """Start `count` ARQ ingest workers as sibling subprocesses.

    Returns [] for count<=0 or when the task queue isn't enabled (the CLI
    already fails fast on --worker without a queue; this is a belt-and-suspenders
    guard for direct callers).
    """
    if count <= 0:
        return []

    from maru_lang.configs import get_config
    from maru_lang.commands.worker import spawn_worker

    cfg = get_config()
    if not cfg.queue_enabled:
        console.print(
            "[yellow]--worker ignored:[/yellow] task_queue_enabled + redis_url not set."
        )
        return []

    console.print(f"[dim]Starting {count} ingest worker(s) (redis={cfg.redis_url})...[/dim]")
    return [spawn_worker() for _ in range(count)]


def _stop_server(proc: subprocess.Popen):
    """Gracefully stop the server subprocess."""
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


async def _wait_for_health(base_url: str, timeout: int = 30) -> bool:
    """Poll /health until server is ready."""
    async with httpx.AsyncClient() as client:
        for _ in range(timeout * 4):
            try:
                resp = await client.get(f"{base_url}/health", timeout=2)
                if resp.status_code == 200:
                    return True
            except (httpx.ConnectError, httpx.ReadError):
                pass
            await asyncio.sleep(0.25)
    return False


async def _get_cli_token(base_url: str, team_names: list[str]) -> dict | None:
    """Request CLI tokens (chat_token + access_token) from the server."""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{base_url}/internal/cli-token",
                json={"teams": team_names},
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json()
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            console.print(f"[red]{detail}[/red]")
        except Exception as e:
            console.print(f"[red]Token request failed: {e}[/red]")
    return None


async def _get_or_create_session(base_url: str, access_token: str) -> str | None:
    """Fetch the user's most recent session (creating one if none). Returns its id."""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{base_url}/sessions/last",
                headers=_auth_headers(access_token),
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json()["id"]
            console.print(f"[red]Session error: {resp.text}[/red]")
        except Exception as e:
            console.print(f"[red]Session request failed: {e}[/red]")
    return None


async def _connect_ws(ws_url: str, chat_token: str, session_id: str):
    """Connect WebSocket and authenticate. Returns (ws, error_msg)."""
    ws = await websockets.connect(ws_url)

    await ws.send(json.dumps({
        "type": "auth", "chat_token": chat_token, "session_id": session_id,
    }))

    # Check for immediate error (e.g. graph creation failure)
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=3)
        msg = json.loads(raw)
        if msg.get("type") == "error":
            await ws.close()
            return None, msg.get("content", "Unknown error")
        return ws, None
    except asyncio.TimeoutError:
        # No immediate response = auth succeeded
        return ws, None
    except websockets.exceptions.ConnectionClosed:
        return None, "Connection closed during authentication"


def _auth_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


async def _run_repl(base_url: str, ws_url: str, current_teams: list[str], verbose: bool = False):
    """Interactive REPL with WebSocket chat and slash commands."""

    # Initial connection
    token_data = await _get_cli_token(base_url, current_teams)
    if not token_data:
        console.print("[red]Failed to get CLI token.[/red]")
        return

    access_token = token_data["access_token"]
    team_map = {t["name"]: t["id"] for t in token_data["teams"]}

    session_id = await _get_or_create_session(base_url, access_token)
    if not session_id:
        console.print("[red]Failed to get a chat session.[/red]")
        return

    ws, err = await _connect_ws(ws_url, token_data["chat_token"], session_id)
    if err:
        console.print(f"[red]Connection failed: {err}[/red]")
        return
    team_display = ", ".join(current_teams) if current_teams else "none"

    # Document-search scope: "team" (only the selected teams) or "all" (every
    # team the CLI admin can access). Default to "team" so search stays scoped
    # to the chosen team; toggle at runtime with /scope.
    scope = "team"

    # Doc graph grounding: when on, the draft grounds on the chosen anchor
    # (standard) document only and skips fuzzy RAG over other team docs.
    # Session-level toggle (/anchor), applied to each turn's message payload.
    anchor_only = False

    console.print(Panel.fit(
        "[bold cyan]MARU Run[/bold cyan]\n"
        f"[yellow]Teams: {team_display}[/yellow]\n"
        f"[yellow]Scope: {scope}[/yellow] [dim](search the selected team only; /scope all for every team)[/dim]\n"
        + ("[magenta]Verbose: on[/magenta] [dim](streaming every graph node's tokens)[/dim]\n" if verbose else "")
        + "[dim]Type /help for commands, /quit to exit · Tab for autocomplete[/dim]",
        border_style="cyan",
    ))

    # prompt_toolkit session: Tab autocomplete (slash commands, /ingest paths) + history.
    session = PromptSession(
        history=InMemoryHistory(),
        completer=_ChatCompleter(lambda: current_teams),
    )

    # Last canvas rendered in the terminal, kept across turns so each new doc
    # version can be diffed against it (new/edited/removed blocks highlighted).
    prev_canvas = None

    try:
        while True:
            try:
                user_input = await session.prompt_async(HTML("\n<ansiblue><b>You</b></ansiblue> ❯ "))
            except (EOFError, KeyboardInterrupt):
                break

            if not user_input.strip():
                continue

            stripped = user_input.strip()

            # Slash commands
            if stripped.startswith("/"):
                parts = stripped.split(maxsplit=1)
                cmd = parts[0].lower()
                args = parts[1] if len(parts) > 1 else ""

                if cmd in ("/quit", "/exit"):
                    console.print("[yellow]Goodbye![/yellow]")
                    break

                elif cmd == "/help":
                    _print_help()
                    continue

                elif cmd == "/team":
                    if not args.strip():
                        console.print(f"[cyan]Current teams: {team_display}[/cyan]")
                        continue
                    new_teams = [t.strip() for t in args.split(",") if t.strip()]
                    console.print(f"[dim]Switching to team: {', '.join(new_teams)}...[/dim]")
                    new_token = await _get_cli_token(base_url, new_teams)
                    if not new_token:
                        console.print("[red]Failed to switch team.[/red]")
                        continue
                    await ws.close()
                    ws, err = await _connect_ws(ws_url, new_token["chat_token"], session_id)
                    if err:
                        console.print(f"[red]Switch failed: {err}[/red]")
                        continue
                    current_teams = new_teams
                    access_token = new_token["access_token"]
                    team_map = {t["name"]: t["id"] for t in new_token["teams"]}
                    team_display = ", ".join(current_teams)
                    console.print(f"[green]Switched to team: {team_display}[/green]")
                    continue

                elif cmd == "/scope":
                    val = args.strip().lower()
                    if not val:
                        console.print(
                            f"[cyan]Current scope: {scope}[/cyan] "
                            "[dim](team=selected teams only, all=every accessible team)[/dim]"
                        )
                        continue
                    if val not in ("team", "all"):
                        console.print("[red]Usage: /scope team|all[/red]")
                        continue
                    scope = val
                    desc = "selected teams only" if scope == "team" else "every accessible team"
                    console.print(f"[green]Search scope: {scope}[/green] [dim]({desc})[/dim]")
                    continue

                elif cmd == "/anchor":
                    val = args.strip().lower()
                    if not val:
                        console.print(
                            f"[cyan]Anchor-only: {'on' if anchor_only else 'off'}[/cyan] "
                            "[dim](on=고른 표준 문서만으로 작성, RAG 끔)[/dim]"
                        )
                        continue
                    if val not in ("on", "off"):
                        console.print("[red]Usage: /anchor on|off[/red]")
                        continue
                    anchor_only = (val == "on")
                    desc = "고른 표준만 사용 (RAG off)" if anchor_only else "표준 + RAG (기본)"
                    console.print(f"[green]Anchor-only: {'on' if anchor_only else 'off'}[/green] [dim]({desc})[/dim]")
                    continue

                elif cmd == "/ingest":
                    await _api_ingest(base_url, access_token, args, current_teams, team_map)
                    continue

                elif cmd == "/status":
                    await _api_status(base_url, access_token, current_teams, team_map)
                    continue

                elif cmd == "/graphs":
                    await _api_graphs(base_url, access_token, args, current_teams, team_map)
                    continue

                elif cmd == "/retry":
                    await _api_retry(base_url, access_token, args, current_teams, team_map)
                    continue

                elif cmd == "/llms":
                    await _api_llms(base_url)
                    continue

                elif cmd == "/function":
                    func_value = args.strip() or None
                    if func_value in ("off", "none"):
                        func_value = None
                    await ws.send(json.dumps({"type": "configure", "function": func_value}))
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5)
                        msg = json.loads(raw)
                        if msg.get("type") == "configured":
                            status = f"[green]{func_value} 활성화[/green]" if func_value else "[green]비활성화[/green]"
                            console.print(f"Function {status}")
                        else:
                            console.print(f"[red]Configure failed: {msg}[/red]")
                    except asyncio.TimeoutError:
                        console.print("[red]Configure timeout[/red]")
                    continue

                else:
                    console.print(f"[red]Unknown command: {cmd}[/red]")
                    console.print("[dim]Type /help for available commands[/dim]")
                    continue

            # Chat message via WebSocket. Scope document search per /scope:
            # "team" sends team_ids (selected teams only), "all" omits it.
            payload = _message_payload(stripped, scope, current_teams, team_map, verbose, anchor_only)
            try:
                await ws.send(json.dumps(payload))
            except websockets.exceptions.ConnectionClosed:
                console.print("[red]Connection lost. Reconnecting...[/red]")
                token_data = await _get_cli_token(base_url, current_teams)
                if not token_data:
                    console.print("[red]Reconnection failed.[/red]")
                    break
                access_token = token_data["access_token"]
                team_map = {t["name"]: t["id"] for t in token_data["teams"]}
                ws, err = await _connect_ws(ws_url, token_data["chat_token"], session_id)
                if err:
                    console.print(f"[red]Reconnection failed: {err}[/red]")
                    break
                await ws.send(json.dumps(_message_payload(stripped, scope, current_teams, team_map, verbose, anchor_only)))

            # Receive streamed response (re-enters on interrupt)
            got_error = False
            while True:
                console.print("\n[bold green]Assistant:[/bold green]")
                answer = ""
                interrupted = False
                interrupt_content = None
                # verbose: the current node whose tokens are printing, so a header
                # prints only when it changes.
                last_node = None

                # Non-verbose gets a clean in-place Markdown region via Live. Verbose
                # streams every node's tokens incrementally instead — a Live region
                # would fight the interleaved DEBUG log lines and reprint endlessly.
                live_cm = nullcontext() if verbose else Live(console=console, refresh_per_second=10)
                with live_cm as live:
                    while True:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=120)
                            msg = json.loads(raw)
                        except asyncio.TimeoutError:
                            console.print("[red]Response timeout.[/red]")
                            got_error = True
                            break
                        except Exception:
                            break

                        msg_type = msg.get("type")

                        if msg_type == "routed":
                            gid = msg.get("graph_id")
                            if gid:
                                # printed above the live region; persists with the answer
                                console.print(f"[dim]🧭 graph: {gid}[/dim]")
                            if gid == "doc":
                                # Interactive editing runs right here in the terminal:
                                # each canvas version prints inline (with a diff vs the
                                # last), and edit commands are read at the prompt.
                                console.print("[green]📝 문서 편집 모드 — 터미널에서 진행합니다.[/green]")
                        elif msg_type == "stream":
                            content = msg.get("content", "")
                            answer += content
                            if verbose:
                                if last_node != "generate":
                                    console.print("\n[bold green]⟨generate⟩[/bold green]")
                                    last_node = "generate"
                                print(content, end="", flush=True)
                            else:
                                live.update(Markdown(answer))
                        elif msg_type == "node_stream":
                            # verbose only: an internal node's LLM token stream,
                            # printed under a per-node header so you can see which
                            # node is running and how long each call takes.
                            if verbose:
                                node = msg.get("node") or "?"
                                if last_node != node:
                                    console.print(f"\n[dim cyan]⟨{node}⟩[/dim cyan]")
                                    last_node = node
                                print(msg.get("content", ""), end="", flush=True)
                        elif msg_type == "thinking":
                            if live is not None:
                                live.update("[dim]Thinking...[/dim]")
                        elif msg_type == "retrieve":
                            docs = msg.get("documents", [])
                            if docs:
                                names = [f"[dim]{d.get('document_name', '?')}[/dim]" for d in docs]
                                summary = f"[cyan]Retrieved {len(docs)} docs:[/cyan] {', '.join(names)}"
                                if live is not None:
                                    live.update(summary)
                                else:
                                    console.print(summary)
                        elif msg_type == "canvas":
                            canvas = msg.get("canvas") or {}
                            # Render the current canvas (sections→blocks) in the
                            # terminal, highlighting the diff vs the last version.
                            if live is not None:
                                live.update("")
                            _render_canvas(canvas, prev_canvas)
                            prev_canvas = canvas
                        elif msg_type == "complete":
                            break
                        elif msg_type == "interrupt":
                            interrupted = True
                            interrupt_content = msg.get("content")
                            break
                        elif msg_type == "error":
                            live.update("")
                            console.print(f"[red]Error: {msg.get('content', 'Unknown')}[/red]")
                            got_error = True
                            break

                if got_error or not interrupted:
                    break

                interrupt_type = interrupt_content.get("type", "") if isinstance(interrupt_content, dict) else ""
                if interrupt_type == "feedback_score":
                    console.print()
                    resume_content = Prompt.ask("[bold cyan]방금 답변에 점수를 매겨주세요 (1-5점)[/bold cyan]")
                elif interrupt_type == "feedback_reason":
                    resume_content = Prompt.ask("[bold yellow]이유를 알려주세요[/bold yellow]")
                elif interrupt_type == "awaiting_anchor_choice":
                    # doc graph: pick a baseline/standard document among candidates.
                    cands = interrupt_content.get("candidates", []) if isinstance(interrupt_content, dict) else []
                    console.print("[bold]기준 문서를 선택하세요 (여러 표준 문서가 있습니다):[/bold]")
                    for i, c in enumerate(cands):
                        console.print(f"  [cyan]{i}[/cyan] {c.get('name')} [dim](관련도 {c.get('score')})[/dim]")
                    console.print("[dim]번호 입력(여러 개는 쉼표, 예: 0,2) · 뒤에 ! = 이 표준만 사용(RAG 없이, 예: 0!) · skip[/dim]")
                    pick = Prompt.ask("[bold]선택[/bold]").strip().lower()
                    # A trailing '!' forces anchor-only grounding for the chosen docs.
                    anchor_only_pick = pick.endswith("!")
                    tok = pick[:-1].strip() if anchor_only_pick else pick
                    # Comma-separated indices → one or more chosen standards' document_ids.
                    idxs = [int(t) for t in tok.split(",") if t.strip().isdigit()]
                    doc_ids = [cands[i]["document_id"] for i in idxs if 0 <= i < len(cands)]
                    if tok == "skip" or not doc_ids:
                        resume_content = {"skip": True}
                    else:
                        resume_content = {"document_ids": doc_ids}
                        if anchor_only_pick:
                            resume_content["anchor_only"] = True
                elif interrupt_type == "awaiting_edit":
                    # doc graph: parse a simple edit command line into a resume dict.
                    #   edit <id> <feedback> | add [after <id>] <text> | delete <id>
                    #   reorder <id,id,...> | parties | terms | finalize
                    if isinstance(interrupt_content, dict) and interrupt_content.get("error"):
                        console.print(f"[red]이전 편집 실패: {interrupt_content['error']}[/red]")
                    missing = (
                        interrupt_content.get("missing_parties")
                        if isinstance(interrupt_content, dict) else None
                    ) or []
                    # Undetermined values ({{label}} tokens) come on the canvas, not
                    # the interrupt — read them from the last rendered canvas.
                    missing_terms = (prev_canvas or {}).get("missing_terms") or []
                    if missing:
                        labels = ", ".join(p.get("label", "?") for p in missing)
                        console.print(
                            f"[yellow]당사자 정보가 비어 있습니다: {labels}[/yellow] "
                            "[dim]— parties 로 입력[/dim]"
                        )
                    if missing_terms:
                        labels = ", ".join(m.get("label", "?") for m in missing_terms)
                        console.print(
                            f"[yellow]미정 항목: {labels}[/yellow] [dim]— terms 로 입력[/dim]"
                        )
                    console.print(
                        "[dim]편집: edit <id> <피드백> | add [after <id>] <내용> | "
                        "delete <id> | reorder <id,id,..> | "
                        + ("parties | " if missing else "")
                        + ("terms | " if missing_terms else "")
                        + "finalize[/dim]"
                    )
                    line = Prompt.ask("[bold]편집 명령[/bold]")
                    cmd = line.strip().lower()
                    if cmd == "parties" and missing:
                        resume_content = _collect_parties(missing)
                    elif cmd == "terms" and missing_terms:
                        resume_content = _collect_terms(missing_terms)
                    else:
                        resume_content = _parse_edit_command(line)
                else:
                    resume_content = Prompt.ask("[bold]입력해주세요[/bold]")
                await ws.send(json.dumps({"type": "resume", "content": resume_content, "verbose": verbose}))

            if not answer and not got_error:
                console.print("[dim]No response received.[/dim]")

    except _QuitSignal:
        pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass


def _print_help():
    """Print available slash commands."""
    help_text = (
        "[bold cyan]Available Commands[/bold cyan]\n\n"
        "  [yellow]/team[/yellow] [name]        — Show or switch team (comma-separated for multiple)\n"
        "  [yellow]/scope[/yellow] team|all     — Limit document search to selected team(s) or all accessible\n"
        "  [yellow]/anchor[/yellow] on|off      — Doc: ground on the chosen standard only (skip RAG)\n"
        "  [yellow]/ingest[/yellow] <path>      — Ingest files via API (uses current team)\n"
        "  [yellow]/status[/yellow]             — Show document status via API\n"
        "  [yellow]/retry[/yellow] [force]      — Re-ingest failed docs (force: ACTIVE too)\n"
        "  [yellow]/llms[/yellow]               — Show available LLM models\n"
        "  [yellow]/graphs[/yellow] [team] [ids]  — Show or set a team's usable graphs (admin; ids: csv|all|default)\n"
        "  [yellow]/function[/yellow] <name>|off  — Enable/disable feedback collection mode\n"
        "  [yellow]/help[/yellow]               — Show this help\n"
        "  [yellow]/quit[/yellow]               — Exit and stop server"
    )
    console.print(Panel(help_text, border_style="dim"))


# ── API-based slash commands ──


async def _api_graphs(
    base_url: str,
    access_token: str,
    args: str,
    current_teams: list[str],
    team_map: dict[str, int],
):
    """Show or set a team's usable graphs via the Teams API.

    /graphs                            → list available graphs + each team's setting
    /graphs <team> <ids|all|default>   → set that team's allowed graphs (admin only)
    """
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                f"{base_url}/teams/available-graphs",
                headers=_auth_headers(access_token), timeout=10,
            )
            available = resp.json() if resp.status_code == 200 else []
        except Exception as e:
            console.print(f"[red]Failed to fetch graphs: {e}[/red]")
            return
        available_ids = [g["id"] for g in available]

        parts = args.split()
        if not parts:
            console.print("[bold]Available graphs[/bold]")
            for g in available:
                console.print(f"  [cyan]{g['id']}[/cyan] — [dim]{g.get('description', '')}[/dim]")
            console.print("[bold]Team settings[/bold] [dim](empty = default)[/dim]")
            for name in current_teams:
                tid = team_map.get(name)
                if not tid:
                    continue
                try:
                    d = await client.get(f"{base_url}/teams/{tid}",
                                         headers=_auth_headers(access_token), timeout=10)
                    allowed = d.json().get("allowed_graphs", []) if d.status_code == 200 else []
                except Exception:
                    allowed = []
                shown = ", ".join(allowed) if allowed else "(default)"
                console.print(f"  {name}: [green]{shown}[/green]")
            console.print("[dim]Set: /graphs <team> chat,doc | all | default[/dim]")
            return

        team_name = parts[0]
        team_id = team_map.get(team_name)
        if not team_id:
            console.print(f"[red]Team '{team_name}' not found. Use /team to switch first.[/red]")
            return
        raw = " ".join(parts[1:]).replace(",", " ").split()
        if not raw:
            console.print("[red]Usage: /graphs <team> chat,doc | all | default[/red]")
            return
        low = [t.lower() for t in raw]
        if low in (["all"], ["*"]):
            graphs = available_ids
        elif low[0] in ("default", "none", "clear", "reset"):
            graphs = []
        else:
            graphs = raw

        try:
            resp = await client.put(
                f"{base_url}/teams/{team_id}/graphs",
                headers=_auth_headers(access_token),
                json={"graphs": graphs}, timeout=10,
            )
        except Exception as e:
            console.print(f"[red]Failed to set graphs: {e}[/red]")
            return
        if resp.status_code == 200:
            allowed = resp.json().get("allowed_graphs", [])
            shown = ", ".join(allowed) if allowed else "(default)"
            console.print(f"[green]{team_name} graphs set:[/green] {shown}")
            console.print(f"[dim]재연결 시 적용됩니다 — /team {team_name} 으로 재인증하세요.[/dim]")
        else:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            console.print(f"[red]{detail}[/red]")


async def _api_ingest(
    base_url: str,
    access_token: str,
    args: str,
    current_teams: list[str],
    team_map: dict[str, int],
):
    """Upload files via POST /ingest/upload API."""
    if not args.strip():
        console.print("[red]Usage: /ingest <path> [--team <name>][/red]")
        return

    parts = args.strip().split()
    path_str = parts[0]

    # Parse --team option
    team_name = None
    for i, part in enumerate(parts):
        if part in ("--team", "-t") and i + 1 < len(parts):
            team_name = parts[i + 1]
            break

    if not team_name and current_teams:
        team_name = current_teams[0]

    if not team_name:
        console.print("[red]No team specified. Use --team or /team first.[/red]")
        return

    team_id = team_map.get(team_name)
    if not team_id:
        console.print(f"[red]Team '{team_name}' not found. Use /team to switch first.[/red]")
        return

    path = Path(path_str).resolve()
    if not path.exists():
        console.print(f"[red]Path does not exist: {path}[/red]")
        return

    # Collect files
    if path.is_file():
        files = [path]
    else:
        from maru_lang.utils.file_scanner import scan_directory
        files = scan_directory(path, recursive=True)

    headers = _auth_headers(access_token)

    # Check which files actually need uploading
    check_payload = {
        "team_id": team_id,
        "files": [
            {
                "fileName": fp.name,
                "absolutePath": str(fp.resolve()),
                "size": fp.stat().st_size,
                "mtime": fp.stat().st_mtime,
            }
            for fp in files
        ],
    }

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            check_resp = await client.post(
                f"{base_url}/ingest/check",
                headers=headers,
                json=check_payload,
            )
            if check_resp.status_code == 200:
                indices = check_resp.json().get("indices_to_upload", [])
                skipped = len(files) - len(indices)
                files = [files[i] for i in indices]
                if skipped:
                    console.print(f"[dim]{skipped} file(s) already up-to-date, skipped.[/dim]")
            else:
                console.print(f"[yellow]Check failed ({check_resp.status_code}), uploading all.[/yellow]")
        except Exception as e:
            console.print(f"[yellow]Check failed: {e}, uploading all.[/yellow]")

    if not files:
        console.print("[green]All files are up-to-date.[/green]")
        return

    console.print(f"[cyan]Uploading {len(files)} file(s) to team '{team_name}'...[/cyan]")

    uploaded = 0
    failed = 0

    # Generous timeout: with the queue off the server embeds in-process and the
    # response waits for it (the first file also loads the embedding model).
    async with httpx.AsyncClient(timeout=300) as client:
        for fp in files:
            try:
                with open(fp, "rb") as f:
                    resp = await client.post(
                        f"{base_url}/ingest/upload",
                        headers=headers,
                        files={"file": (fp.name, f)},
                        data={
                            "team_id": str(team_id),
                            # Real parent dir: upload identity/fingerprint then
                            # matches /ingest/check's absolutePath, and the group
                            # is named after the actual folder.
                            "folder_path": str(fp.resolve().parent),
                            "mtime": str(fp.stat().st_mtime),
                        },
                    )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "error":
                        console.print(f"  [red]FAIL[/red] {fp.name}: {data.get('error') or 'embedding failed'}")
                        failed += 1
                    else:
                        console.print(f"  [green]OK[/green] {fp.name} (id: {data.get('document_id', '?')})")
                        uploaded += 1
                else:
                    console.print(f"  [red]FAIL[/red] {fp.name}: {resp.text}")
                    failed += 1
            except Exception as e:
                console.print(f"  [red]FAIL[/red] {fp.name}: {e}")
                failed += 1

    console.print(f"\n[{'green' if not failed else 'yellow'}]Ingest done: {uploaded} uploaded, {failed} failed[/]")


async def _api_status(
    base_url: str,
    access_token: str,
    current_teams: list[str],
    team_map: dict[str, int],
):
    """Show document status via GET /ingest/status API."""
    if not current_teams:
        console.print("[red]No team selected. Use /team first.[/red]")
        return

    headers = _auth_headers(access_token)

    async with httpx.AsyncClient(timeout=10) as client:
        for team_name in current_teams:
            team_id = team_map.get(team_name)
            if not team_id:
                console.print(f"[red]Team '{team_name}' not found.[/red]")
                continue

            try:
                resp = await client.get(
                    f"{base_url}/ingest/status",
                    headers=headers,
                    params={"team_id": team_id},
                )
            except Exception as e:
                console.print(f"[red]Status request failed: {e}[/red]")
                continue

            if resp.status_code != 200:
                console.print(f"[red]Status error ({team_name}): {resp.text}[/red]")
                continue

            data = resp.json()
            docs = data.get("documents", [])

            table = Table(title=f"Team: {team_name} ({data.get('total', 0)} docs)")
            table.add_column("Name", style="cyan")
            table.add_column("Status", style="yellow")
            table.add_column("Size", justify="right")
            table.add_column("Error", style="red")

            for doc in docs:
                size = doc.get("file_size", 0)
                size_str = f"{size:,}" if size else "-"
                table.add_row(
                    doc.get("name", "?"),
                    doc.get("status", "?"),
                    size_str,
                    doc.get("error") or "",
                )

            console.print(table)


async def _api_retry(
    base_url: str,
    access_token: str,
    args: str,
    current_teams: list[str],
    team_map: dict[str, int],
):
    """Re-ingest failed documents via POST /ingest/{id}/retry, one per request.

    `/retry` retries the current team's ERROR documents; `/retry force` also
    re-ingests ACTIVE ones (full re-parse/re-embed). Mirrors /ingest: the client
    loops documents and each response carries the real per-document outcome.
    """
    force = args.strip() == "force"
    if args.strip() and not force:
        console.print("[red]Usage: /retry [force][/red]")
        return
    if not current_teams:
        console.print("[red]No team selected. Use /team first.[/red]")
        return

    headers = _auth_headers(access_token)
    target_statuses = {"error", "active"} if force else {"error"}

    # Generous timeout: with the queue off the server re-embeds synchronously.
    async with httpx.AsyncClient(timeout=300) as client:
        for team_name in current_teams:
            team_id = team_map.get(team_name)
            if not team_id:
                console.print(f"[red]Team '{team_name}' not found.[/red]")
                continue

            try:
                resp = await client.get(
                    f"{base_url}/ingest/status",
                    headers=headers,
                    params={"team_id": team_id},
                )
                docs = resp.json().get("documents", []) if resp.status_code == 200 else []
            except Exception as e:
                console.print(f"[red]Status request failed: {e}[/red]")
                continue

            targets = [d for d in docs if d.get("status") in target_statuses]
            if not targets:
                console.print(f"[green]{team_name}: nothing to retry.[/green]")
                continue

            console.print(f"[cyan]Retrying {len(targets)} document(s) in '{team_name}'...[/cyan]")
            ok = failed = 0
            for d in targets:
                try:
                    r = await client.post(
                        f"{base_url}/ingest/{d['id']}/retry",
                        headers=headers,
                        params={"team_id": team_id, "force": str(force).lower()},
                    )
                    body = r.json() if r.status_code == 200 else {}
                    if r.status_code == 200 and body.get("status") != "error":
                        console.print(f"  [green]OK[/green] {d['name']} ({body.get('status')})")
                        ok += 1
                    else:
                        detail = body.get("error") or r.text
                        console.print(f"  [red]FAIL[/red] {d['name']}: {detail}")
                        failed += 1
                except Exception as e:
                    console.print(f"  [red]FAIL[/red] {d['name']}: {e}")
                    failed += 1
            console.print(f"[{'green' if not failed else 'yellow'}]Retry done: {ok} ok, {failed} failed[/]")


async def _api_llms(base_url: str):
    """Show available LLM models via GET /internal/llms."""
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(f"{base_url}/internal/llms")
        except Exception as e:
            console.print(f"[red]LLMs request failed: {e}[/red]")
            return

        if resp.status_code != 200:
            console.print(f"[red]LLMs error: {resp.text}[/red]")
            return

        llms = resp.json().get("llms", [])
        if not llms:
            console.print("[yellow]No LLM models available.[/yellow]")
            return

        table = Table(title=f"Available LLMs ({len(llms)})")
        table.add_column("Name", style="cyan")
        table.add_column("Provider", style="yellow")
        table.add_column("Model", style="green")

        for llm in llms:
            table.add_row(
                llm.get("name", "?"),
                llm.get("provider", "?"),
                llm.get("model", "?"),
            )

        console.print(table)
