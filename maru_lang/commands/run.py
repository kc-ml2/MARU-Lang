"""Run command — start server + interactive WebSocket chat CLI."""
import asyncio
import json
import os
import signal
import subprocess
import sys
import websockets
from pathlib import Path

import httpx
from rich.console import Console
from rich.markdown import Markdown
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

console = Console()


class _QuitSignal(Exception):
    pass


async def run_session(
    team_names: list[str],
    host: str,
    port: int,
    skip_migrations: bool,
):
    """Main entry: start server, connect WebSocket, run REPL."""
    base_url = f"http://{host}:{port}"
    ws_url = f"ws://{host}:{port}/chat/connect"

    # 1. Start server
    server_proc = _start_server(host, port, skip_migrations)
    console.print(f"[dim]Starting server on {host}:{port}...[/dim]")

    try:
        # 2. Wait for server ready
        if not await _wait_for_health(base_url, timeout=30):
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
        await _run_repl(base_url, ws_url, current_teams)

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
    finally:
        _stop_server(server_proc)
        console.print("[dim]Server stopped.[/dim]")


def _start_server(host: str, port: int, skip_migrations: bool) -> subprocess.Popen:
    """Start uvicorn as a background subprocess."""
    env = os.environ.copy()
    cwd = os.getcwd()
    python_path = env.get("PYTHONPATH", "")
    maru_app_path = os.path.join(cwd, "maru_app")
    paths = [cwd]
    if os.path.exists(maru_app_path):
        paths.append(maru_app_path)
    if python_path:
        paths.append(python_path)
    env["PYTHONPATH"] = os.pathsep.join(paths)

    cmd = [
        sys.executable, "-m", "uvicorn",
        "main:app",
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
            console.print(f"[red]Token error: {resp.text}[/red]")
        except Exception as e:
            console.print(f"[red]Token request failed: {e}[/red]")
    return None


async def _connect_ws(ws_url: str, chat_token: str):
    """Connect WebSocket and authenticate. Returns (ws, error_msg)."""
    ws = await websockets.connect(ws_url)

    await ws.send(json.dumps({"type": "auth", "chat_token": chat_token}))

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


async def _run_repl(base_url: str, ws_url: str, current_teams: list[str]):
    """Interactive REPL with WebSocket chat and slash commands."""

    # Initial connection
    token_data = await _get_cli_token(base_url, current_teams)
    if not token_data:
        console.print("[red]Failed to get CLI token.[/red]")
        return

    access_token = token_data["access_token"]
    team_map = {t["name"]: t["id"] for t in token_data["teams"]}

    ws, err = await _connect_ws(ws_url, token_data["chat_token"])
    if err:
        console.print(f"[red]Connection failed: {err}[/red]")
        return
    team_display = ", ".join(current_teams) if current_teams else "none"

    console.print(Panel.fit(
        "[bold cyan]MARU Run[/bold cyan]\n"
        f"[yellow]Teams: {team_display}[/yellow]\n"
        "[dim]Type /help for commands, /quit to exit[/dim]",
        border_style="cyan",
    ))

    try:
        while True:
            try:
                user_input = Prompt.ask("\n[bold blue]You[/bold blue]")
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
                    ws, err = await _connect_ws(ws_url, new_token["chat_token"])
                    if err:
                        console.print(f"[red]Switch failed: {err}[/red]")
                        continue
                    current_teams = new_teams
                    access_token = new_token["access_token"]
                    team_map = {t["name"]: t["id"] for t in new_token["teams"]}
                    team_display = ", ".join(current_teams)
                    console.print(f"[green]Switched to team: {team_display}[/green]")
                    continue

                elif cmd == "/ingest":
                    await _api_ingest(base_url, access_token, args, current_teams, team_map)
                    continue

                elif cmd == "/status":
                    await _api_status(base_url, access_token, current_teams, team_map)
                    continue

                elif cmd == "/llms":
                    await _api_llms(base_url)
                    continue

                else:
                    console.print(f"[red]Unknown command: {cmd}[/red]")
                    console.print("[dim]Type /help for available commands[/dim]")
                    continue

            # Chat message via WebSocket
            try:
                await ws.send(json.dumps({"type": "message", "content": stripped}))
            except websockets.exceptions.ConnectionClosed:
                console.print("[red]Connection lost. Reconnecting...[/red]")
                token_data = await _get_cli_token(base_url, current_teams)
                if not token_data:
                    console.print("[red]Reconnection failed.[/red]")
                    break
                access_token = token_data["access_token"]
                ws, err = await _connect_ws(ws_url, token_data["chat_token"])
                if err:
                    console.print(f"[red]Reconnection failed: {err}[/red]")
                    break
                await ws.send(json.dumps({"type": "message", "content": stripped}))

            # Receive streamed response
            console.print("\n[bold green]Assistant:[/bold green]")
            answer = ""
            got_error = False

            with Live(console=console, refresh_per_second=10) as live:
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

                    if msg_type == "stream":
                        answer += msg.get("content", "")
                        live.update(Markdown(answer))
                    elif msg_type == "thinking":
                        live.update("[dim]Thinking...[/dim]")
                    elif msg_type == "retrieve":
                        docs = msg.get("documents", [])
                        if docs:
                            names = [f"[dim]{d.get('document_name', '?')}[/dim]" for d in docs]
                            live.update(f"[cyan]Retrieved {len(docs)} docs:[/cyan] {', '.join(names)}")
                    elif msg_type == "complete":
                        break
                    elif msg_type == "error":
                        live.update("")
                        console.print(f"[red]Error: {msg.get('content', 'Unknown')}[/red]")
                        got_error = True
                        break

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
        "  [yellow]/ingest[/yellow] <path>      — Ingest files via API (uses current team)\n"
        "  [yellow]/status[/yellow]             — Show document status via API\n"
        "  [yellow]/llms[/yellow]               — Show available LLM models\n"
        "  [yellow]/help[/yellow]               — Show this help\n"
        "  [yellow]/quit[/yellow]               — Exit and stop server"
    )
    console.print(Panel(help_text, border_style="dim"))


# ── API-based slash commands ──


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

    async with httpx.AsyncClient(timeout=60) as client:
        for fp in files:
            try:
                with open(fp, "rb") as f:
                    resp = await client.post(
                        f"{base_url}/ingest/upload",
                        headers=headers,
                        files={"file": (fp.name, f)},
                        data={
                            "team_id": str(team_id),
                            "folder_path": "",
                            "mtime": str(fp.stat().st_mtime),
                        },
                    )
                if resp.status_code == 200:
                    data = resp.json()
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
