"""CLI chat command - LangGraph 기반"""
from rich.console import Console
from rich.prompt import Prompt
from rich.panel import Panel
from rich.markdown import Markdown
from rich.live import Live

from langchain_core.messages import HumanMessage, AIMessageChunk

from maru_lang.dependencies.llm import get_model_with_fallbacks
from maru_lang.graph import create_graph
from maru_lang.core.relation_db.models.auth import Team
from maru_lang.services.document import get_group_names_by_team_id

console = Console()


async def chat_session(
    team_names: str,
    max_turns: int = 0,
):
    """Interactive chat session using LangGraph.

    Args:
        team_names: Team names to access documents (comma-separated)
        max_turns: (unused, kept for CLI compat)
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
    model = get_model_with_fallbacks()
    if not model:
        console.print("[red]Error: No LLM available[/red]")
        return

    graph = create_graph(model)
    thread_id = f"cli-{'-'.join(team_name_list)}"
    config = {"configurable": {"thread_id": thread_id}}

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

                # LangGraph 입력
                graph_input = {
                    "messages": [HumanMessage(content=question)],
                    "team_ids": [t.id for t in teams],
                    "team_names": [t.name for t in teams],
                    "accessible_groups": accessible_groups,
                    "retrieved_documents": [],
                }

                # 스트리밍 응답
                console.print("\n[bold green]Assistant:[/bold green]")
                answer = ""

                with Live(console=console, refresh_per_second=10) as live:
                    async for event, metadata in graph.astream(
                        graph_input,
                        config=config,
                        stream_mode="messages",
                    ):
                        if isinstance(event, AIMessageChunk) and event.content:
                            answer += event.content
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
