"""Safe CLI deletion commands for ingested documents and folders."""

import typer

from maru_lang.core.relation_db.connection import run_with_orm_context
from maru_lang.core.relation_db.models.documents import Document, DocumentGroup
from maru_lang.enums.documents import DocumentStatus
from maru_lang.services.document import get_all_descendant_groups
from maru_lang.services.ingest import delete_document_by_id, delete_group_documents

remove_app = typer.Typer(help="Delete ingested documents or folder subtrees safely.")


async def _remove_document(target: str, team_id: int, force: bool) -> None:
    """Resolve a document ID/path and remove its DB, vector, and storage data."""
    doc = await Document.get_or_none(id=target, group__team_id=team_id)
    if doc is None:
        # A path is often easier to obtain than the generated document ID. Match
        # the exact stored path only; names alone can be ambiguous.
        doc = await Document.get_or_none(file_path=target, group__team_id=team_id)
    if doc is None:
        typer.secho(
            f"Document '{target}' was not found in team {team_id}.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)

    status = DocumentStatus(doc.status).name.lower()
    typer.echo(f"Document: {doc.name}")
    typer.echo(f"ID:       {doc.id}")
    typer.echo(f"Path:     {doc.file_path or '-'}")
    typer.echo(f"Status:   {status}")
    if not force and not typer.confirm("Delete this document and all of its embeddings?"):
        typer.echo("Deletion cancelled.")
        return

    in_flight = doc.status in {DocumentStatus.UPLOADING, DocumentStatus.PROCESSING}
    await delete_document_by_id(doc.id, team_id, user_id=None)
    if in_flight:
        typer.secho(
            "Deletion requested. The ingest worker will finalize this in-flight document.",
            fg=typer.colors.YELLOW,
        )
    else:
        typer.secho("Document deleted.", fg=typer.colors.GREEN)


async def _remove_group(group_id: int, team_id: int, force: bool) -> None:
    """Remove a folder subtree using the same safe semantics as the API."""
    group = await DocumentGroup.get_or_none(id=group_id, team_id=team_id)
    if group is None:
        typer.secho(
            f"Folder {group_id} was not found in team {team_id}.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1)

    groups = await get_all_descendant_groups(group)
    group_ids = [item.id for item in groups]
    document_count = await Document.filter(group_id__in=group_ids).count()
    typer.echo(f"Folder:      {group.name} (ID: {group.id})")
    typer.echo(f"Subtree:     {len(groups)} folder(s)")
    typer.echo(f"Documents:   {document_count}")
    if not force and not typer.confirm("Delete this folder subtree and all of its documents?"):
        typer.echo("Deletion cancelled.")
        return

    result = await delete_group_documents(group_id, team_id, user_id=None)
    typer.secho(
        f"Deletion complete: {result['deleted']} deleted, "
        f"{result['deferred']} deferred.",
        fg=typer.colors.GREEN if not result["deferred"] else typer.colors.YELLOW,
    )
    if not result["group_removed"]:
        typer.echo("The folder will remain until in-flight document deletion is finalized.")


@remove_app.command("document")
def remove_document(
    target: str = typer.Argument(..., help="Document ID or exact stored file path"),
    team_id: int = typer.Option(..., "--team-id", "-t", help="Owning team ID"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """Delete one document, its embeddings, and its stored file."""
    run_with_orm_context(_remove_document, target, team_id, force)


@remove_app.command("group")
def remove_group(
    group_id: int = typer.Argument(..., help="Folder (DocumentGroup) ID"),
    team_id: int = typer.Option(..., "--team-id", "-t", help="Owning team ID"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """Delete a folder subtree and every document it contains."""
    run_with_orm_context(_remove_group, group_id, team_id, force)
