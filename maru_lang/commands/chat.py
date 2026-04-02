"""CLI chat command - LangGraph 기반"""
from rich.console import Console
from rich.prompt import Prompt
from rich.panel import Panel
from rich.markdown import Markdown
from rich.live import Live

from maru_lang.graph import create_chat_graph, stream_chat
from maru_lang.core.relation_db.models.auth import Team
from maru_lang.services.document import get_group_names_by_team_id

console = Console()


async def chat_session(
    team_names: str,
):
    """Interactive chat session using LangGraph.

    Args:
        team_names: Team names to access documents (comma-separated).
    """
    # Parse team names
    team_name_list = [name.strip() for name in team_names.split(",") if name.strip()]
    if not team_name_list:
        console.print("[red]Error: No team names provided[/red]")
        return

    # Get Teams from database
    teams = []
    not_found = []
    for name in team_name_list:
        team = await Team.get_or_none(name=name)
        if team:
            teams.append(team)
        else:
            not_found.append(name)

    if not_found:
        console.print(f"[red]Error: Teams not found: {', '.join(not_found)}[/red]")
        all_teams = await Team.all().values_list("name", flat=True)
        if all_teams:
            console.print("\n[cyan]Available teams:[/cyan]")
            for t in sorted(all_teams):
                console.print(f"  - {t}")
        return

    if not teams:
        console.print("[red]Error: No valid teams found[/red]")
        return

    # Get accessible groups
    accessible_groups = []
    for team in teams:
        groups = await get_group_names_by_team_id(team.id)
        accessible_groups.extend(groups)
    accessible_groups = list(set(accessible_groups))

    team_display = ", ".join([t.name for t in teams])

    # Initialize LangGraph
    console.print("[cyan]Initializing LangGraph...[/cyan]")
    try:
        graph = create_chat_graph()
    except RuntimeError as e:
        console.print(f"[red]Error: {e}[/red]")
        return
    thread_id = f"cli-{'-'.join(team_name_list)}"
    config = {"configurable": {"thread_id": thread_id}}

    team_ids = [t.id for t in teams]
    team_name_values = [t.name for t in teams]

    console.print(Panel.fit(
        "[bold cyan]MARU Chat CLI (LangGraph)[/bold cyan]\n"
        f"[yellow]Teams: {team_display}[/yellow]\n"
        f"[dim]Accessible groups: {len(accessible_groups)}[/dim]\n"
        "Type 'exit' or 'quit' to end the session\n"
        "Type 'clear' to clear the screen",
        border_style="cyan",
    ))
    console.print(f"[green]Session started[/green]\n")

    try:
        while True:
            try:
                question = Prompt.ask("\n[bold blue]You[/bold blue]")

                if question.lower() in ("exit", "quit", "q"):
                    console.print("[yellow]Goodbye![/yellow]")
                    break

                if question.lower() == "clear":
                    console.clear()
                    continue

                # 스트리밍 응답
                console.print("\n[bold green]Assistant:[/bold green]")
                answer = ""

                with Live(console=console, refresh_per_second=10) as live:
                    async for event_type, content in stream_chat(
                        message=question,
                        team_ids=team_ids,
                        team_names=team_name_values,
                        accessible_groups=accessible_groups,
                        graph=graph,
                        config=config,
                    ):
                        if event_type == "token":
                            answer += content
                            live.update(Markdown(answer))

                if not answer:
                    console.print("[red]Failed to generate response[/red]")

            except KeyboardInterrupt:
                console.print("\n[yellow]Interrupted. Type 'exit' to quit.[/yellow]")
                continue
            except Exception as e:
                console.print(f"\n[red]Error: {str(e)}[/red]")
                continue

    except (KeyboardInterrupt, SystemExit):
        console.print("\n[yellow]Goodbye![/yellow]")
