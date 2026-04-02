"""Ingest command - LangGraph single-file pipeline."""
import time
import typer
from datetime import datetime
from pathlib import Path

from maru_lang.graph.ingest import stream_ingest
from maru_lang.utils.file_scanner import scan_directory
from maru_lang.services.admin import get_or_create_admin_user
from maru_lang.services.team import get_or_create_team
from maru_lang.schemas.ingest import FileInfo


async def ingest_function(
    path: Path,
    team: str,
    re_embed: bool = False,
):
    """Ingest a directory (load, split, embed, store to VDB)"""
    if not path.exists() or not path.is_dir():
        typer.secho(f"Directory does not exist: {path}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    # Admin user and Team setup
    admin_user = await get_or_create_admin_user()
    team_obj, team_created = await get_or_create_team(name=team, manager=admin_user)
    if team_created:
        typer.echo(f"Team '{team}' created")

    # Scan files
    typer.secho("\nScanning files...", fg=typer.colors.CYAN, bold=True)
    file_paths = scan_directory(path, recursive=True)
    files = [
        FileInfo(
            fileName=fp.name,
            createdAt=datetime.fromtimestamp(fp.stat().st_ctime),
            absolutePath=str(fp.resolve()),
            size=fp.stat().st_size,
            tempFilePath=None,
        )
        for fp in file_paths
    ]
    typer.echo(f"Found {len(files)} file(s)\n")

    # Run ingest per file
    typer.secho("Starting Ingest Pipeline", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  Path: {path}")
    typer.echo(f"  Team: {team_obj.name}")
    typer.echo(f"  Files: {len(files)}")
    if re_embed:
        typer.echo("  Re-embed: True")
    typer.echo()

    start_time = time.time()
    processed = 0
    failed = 0

    try:
        for file_info in files:
            async for node_name, messages in stream_ingest(
                file=file_info,
                team_id=team_obj.id,
                re_embed=re_embed,
            ):
                for msg in messages:
                    if "ERROR" in msg:
                        typer.secho(f"  {msg}", fg=typer.colors.RED)
                        failed += 1
                    else:
                        typer.secho(f"  {msg}", fg=typer.colors.CYAN)
            processed += 1

    except ValueError as e:
        typer.secho(f"\nIngest failed: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"\nUnexpected error: {e}", fg=typer.colors.RED)
        raise typer.Exit(1)

    elapsed_time = time.time() - start_time
    typer.secho(
        f"\nIngest Complete! {processed}/{len(files)} files ({elapsed_time:.2f}s)",
        fg=typer.colors.GREEN,
        bold=True,
    )
