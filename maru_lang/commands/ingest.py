"""
Ingest command: Ingest files using IngestPipeline
"""
import time
import typer
from datetime import datetime
from pathlib import Path

from maru_lang.pipelines.ingest import IngestPipeline
from maru_lang.pipelines.base import MessageType
from maru_lang.models.vector_db import get_vector_db_config_from_settings
from maru_lang.utils.file_scanner import scan_directory
from maru_lang.services.admin import get_or_create_admin_user
from maru_lang.services.team import get_or_create_team
from maru_lang.schemas.ingest import FileInfo


async def ingest_function(
    path: Path,
    team: str,
    re_embed: bool = False,
):
    """
    Ingest a directory (parse, chunk, embed, store to VDB)

    Args:
        path: Directory path to ingest
        team: Team name that will own the documents
        re_embed: Delete existing embeddings and re-embed from scratch
    """
    # ========== Input validation ==========
    if not path.exists() or not path.is_dir():
        typer.secho(
            f"Directory does not exist or is invalid: {path}",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)

    # ========== Admin user and Team setup ==========
    admin_user = await get_or_create_admin_user()

    team_obj, team_created = await get_or_create_team(
        name=team,
        manager=admin_user,
    )

    if team_created:
        typer.echo(f"Team '{team}' created with admin as manager")

    # ========== Scan files ==========
    typer.echo("\n" + "=" * 50)
    typer.secho("Scanning files...", fg=typer.colors.CYAN, bold=True)
    typer.echo("=" * 50)

    file_paths = scan_directory(path, recursive=True)
    files = [
        FileInfo(
            fileName=file_path.name,
            createdAt=datetime.fromtimestamp(file_path.stat().st_ctime),
            absolutePath=str(file_path.resolve()),
            size=file_path.stat().st_size,
            tempFilePath=None,
        ) for file_path in file_paths
    ]
    typer.echo(f"Found {len(files)} file(s) in {path}")
    typer.echo()

    # ========== Run IngestPipeline ==========
    typer.echo("=" * 50)
    typer.secho("Starting Ingest Pipeline", fg=typer.colors.CYAN, bold=True)
    typer.echo("=" * 50)
    typer.echo(f"Path: {path}")
    typer.echo(f"Team: {team_obj.name}")
    typer.echo(f"Manager: {admin_user.name} ({admin_user.email})")
    typer.echo(f"Files: {len(files)}")
    if re_embed:
        typer.echo("Re-embed: True (delete existing and re-create)")
    typer.echo()

    start_time = time.time()

    try:
        # Create VectorDB config
        vdb_config = get_vector_db_config_from_settings()

        # Create and run pipeline
        pipeline = IngestPipeline(
            team_id=team_obj.id,
            vdb_config=vdb_config,
        )

        result = None
        async for step in pipeline.run(files, re_embed=re_embed):
            if step.message_type == MessageType.COMPLETE:
                result = step.data
                break
            elif step.message_type == MessageType.INFO:
                typer.secho(f"  {step.message}", fg=typer.colors.CYAN)
            elif step.message_type == MessageType.WARNING:
                typer.secho(f"  {step.message}", fg=typer.colors.YELLOW)
            elif step.message_type == MessageType.ERROR:
                typer.secho(f"  {step.message}", fg=typer.colors.RED)

        if result is None:
            raise ValueError("Pipeline did not return a result")

    except ValueError as e:
        typer.secho(f"\nIngest failed: {str(e)}", fg=typer.colors.RED)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"\nUnexpected error: {str(e)}", fg=typer.colors.RED)
        import traceback
        traceback.print_exc()
        raise typer.Exit(1)

    # ========== Completion message ==========
    elapsed_time = time.time() - start_time

    typer.echo("\n" + "=" * 50)
    typer.secho("Ingest Complete!", fg=typer.colors.GREEN, bold=True)
    typer.echo("=" * 50)
    typer.echo(f"Total files: {result.total_files}")
    typer.echo(f"Processed: {result.processed_files} (new or modified)")
    typer.echo(f"Skipped: {result.skipped_files} (unchanged)")
    typer.echo(f"Elapsed time: {elapsed_time:.2f}s")
    typer.secho("All documents are now embedded and searchable!",
                fg=typer.colors.GREEN)
    typer.echo()
