"""Ingest command - process local files via LangGraph pipeline."""
import time
import typer
from datetime import datetime
from pathlib import Path

from maru_lang.graph.ingest import stream_ingest
from maru_lang.utils.file_scanner import scan_directory
from maru_lang.utils.file_storage import save_file
from maru_lang.utils.document import new_ulid
from maru_lang.services.admin import get_or_create_admin_user
from maru_lang.services.team import get_or_create_team
from maru_lang.schemas.ingest import FileInfo


async def ingest_function(
    path: Path,
    team: str,
    re_embed: bool = False,
):
    """Ingest files: save to storage, then load/split/embed/store."""
    if not path.exists():
        typer.secho(f"Path does not exist: {path}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    admin_user = await get_or_create_admin_user()
    team_obj, team_created = await get_or_create_team(name=team, manager=admin_user)
    if team_created:
        typer.echo(f"Team '{team}' created")

    # Collect files
    if path.is_file():
        file_paths = [path]
    else:
        typer.secho("\nScanning files...", fg=typer.colors.CYAN, bold=True)
        file_paths = scan_directory(path, recursive=True)
    typer.echo(f"Found {len(file_paths)} file(s)\n")

    typer.secho("Starting Ingest Pipeline", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  Path: {path}")
    typer.echo(f"  Team: {team_obj.name}")
    typer.echo(f"  Files: {len(file_paths)}")
    if re_embed:
        typer.echo("  Re-embed: True")
    typer.echo()

    start_time = time.time()
    processed = 0
    failed = 0

    try:
        for fp in file_paths:
            # Save to permanent storage
            doc_id = new_ulid()
            storage_path = save_file(fp, team_obj.id, doc_id)

            file_info = FileInfo(
                fileName=fp.name,
                createdAt=datetime.fromtimestamp(fp.stat().st_ctime),
                absolutePath=str(fp.resolve()),
                size=fp.stat().st_size,
                tempFilePath=storage_path,
            )

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
        f"\nIngest Complete! {processed}/{len(file_paths)} files ({elapsed_time:.2f}s)",
        fg=typer.colors.GREEN,
        bold=True,
    )
