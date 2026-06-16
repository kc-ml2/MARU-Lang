"""Status command - show DB and VectorDB state."""
import typer

from maru_lang.core.relation_db.models.documents import Document
from maru_lang.core.relation_db.models.auth import Team
from maru_lang.enums.documents import DocumentStatus


async def show_status(verbose: bool = False):
    """Display system status: teams, documents, and vector DB."""

    typer.echo("=" * 50)
    typer.echo("System Status")
    typer.echo("=" * 50)

    # --- Teams ---
    teams = await Team.all().prefetch_related("manager")
    typer.echo(f"\nTeams: {len(teams)}")

    for team in teams:
        doc_count = await Document.filter(group__team=team).count()
        manager = team.manager.name if team.manager else "N/A"
        typer.echo(f"  {team.name}: {doc_count} docs, manager: {manager}")

    # --- Documents ---
    total = await Document.all().count()
    active = await Document.filter(status=DocumentStatus.ACTIVE).count()
    processing = await Document.filter(status=DocumentStatus.PROCESSING).count()
    inactive = await Document.filter(status=DocumentStatus.INACTIVE).count()

    typer.echo(f"\nDocuments: {total}")
    typer.echo(f"  ACTIVE:     {active}")
    typer.echo(f"  PROCESSING: {processing}")
    typer.echo(f"  INACTIVE:   {inactive}")

    # --- VectorDB ---
    typer.echo(f"\nVectorDB")
    typer.echo("-" * 50)

    try:
        from maru_lang.core.vector_db import get_vector_db
        vdb = get_vector_db()
        all_meta = vdb.get_all_metadata()

        # Aggregate by team_id
        team_stats: dict[str, dict] = {}
        for meta in all_meta:
            tid = str(meta.get("team_id", "unknown"))
            if tid not in team_stats:
                team_stats[tid] = {"docs": set(), "chunks": 0}
            team_stats[tid]["docs"].add(meta.get("document_id", ""))
            team_stats[tid]["chunks"] += 1

        total_chunks = sum(s["chunks"] for s in team_stats.values())
        total_vdb_docs = sum(len(s["docs"]) for s in team_stats.values())
        typer.echo(f"  Total: {total_vdb_docs} documents, {total_chunks} chunks")

        if verbose and team_stats:
            for tid, stats in sorted(team_stats.items()):
                typer.echo(f"  Team {tid}: {len(stats['docs'])} docs, {stats['chunks']} chunks")

    except Exception as e:
        typer.secho(f"  Error: {e}", fg=typer.colors.RED)
        return

    # --- Consistency ---
    if active != total_vdb_docs:
        typer.echo(f"\nWarning: RDB active ({active}) != VDB docs ({total_vdb_docs})")
    if processing > 0:
        typer.echo(f"Warning: {processing} documents still processing")
