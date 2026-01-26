"""
CLI chat command
"""
from rich.console import Console
from rich.prompt import Prompt
from rich.panel import Panel
from rich.markdown import Markdown
from rich.live import Live
from maru_lang.pipelines.base import MessageType
from maru_lang.dependencies.chat import get_chat_pipeline
from maru_lang.models.chat import ChatHistory
from maru_lang.configs.manager import get_config_manager
from maru_lang.core.relation_db.models.auth import Team
from maru_lang.services.document import get_group_names_by_team_id


console = Console()


async def chat_session(
    team_names: str,
    max_turns: int = 0
):
    """
    Interactive chat session

    Args:
        team_names: Team names to access documents (comma-separated)
        max_turns: Maximum number of turns to keep in history
    """

    # Parse comma-separated team names
    team_name_list = [
        name.strip()
        for name in team_names.split(",") if name.strip()]
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
        console.print(
            f"[red]Error: Teams not found: {', '.join(not_found)}[/red]")
        # Show available teams
        all_teams = await Team.all().values_list("name", flat=True)
        if all_teams:
            console.print("\n[cyan]Available teams:[/cyan]")
            for t in sorted(all_teams):
                console.print(f"  - {t}")
        return

    if not teams:
        console.print("[red]Error: No valid teams found[/red]")
        return

    # Get accessible groups for these teams
    accessible_groups = []
    for team in teams:
        groups = await get_group_names_by_team_id(team.id)
        accessible_groups.extend(groups)
    accessible_groups = list(set(accessible_groups))  # Remove duplicates

    team_display = ", ".join([t.name for t in teams])

    # Initialize
    console.print(Panel.fit(
        "[bold cyan]MARU Chat CLI[/bold cyan]\n"
        f"[yellow]Teams: {team_display}[/yellow]\n"
        f"[dim]Accessible groups: {len(accessible_groups)}[/dim]\n"
        "Type 'exit' or 'quit' to end the session\n"
        "Type 'clear' to clear the screen",
        border_style="cyan"
    ))

    console.print(
        f"[green]Session started (Teams: {team_display})[/green]\n")

    # ConfigManager 초기화
    console.print("[cyan]📋 Initializing configurations...[/cyan]")
    config_manager = get_config_manager()

    try:
        config_manager.load_all()
        config_status = config_manager.validate_all()

        # Always show configuration summary
        console.print("[green]✓ Configurations loaded successfully[/green]")

        # Show warnings and errors if any exist
        warnings = config_status.get('warnings', [])
        errors = config_status.get('errors', [])

        if warnings or errors:
            console.print("")  # Add blank line
            if warnings:
                console.print("[yellow]⚠️  Configuration warnings:[/yellow]")
                for warning in warnings:
                    # Handle multi-line warnings
                    if isinstance(warning, str) and '\n' in warning:
                        lines = warning.split('\n')
                        for line in lines:
                            console.print(f"  {line}")
                    else:
                        console.print(f"  - {warning}")

            if errors:
                console.print("[red]❌ Configuration errors:[/red]")
                for error in errors:
                    console.print(f"  - {error}")

    except Exception as e:
        console.print(f"[red]❌ Configuration error: {str(e)}[/red]")
        return

    # LLM 서버 상태 확인 및 표시
    enabled_llms = config_manager.llm_loader.get_enabled_configs()
    total_llms = len(config_manager.llm_loader.configs)

    if enabled_llms:
        llm_names = [llm.name for llm in enabled_llms[:3]]
        llm_display = ", ".join(llm_names)
        if len(enabled_llms) > 3:
            llm_display += f" (+{len(enabled_llms) - 3} more)"
        console.print(
            f"[cyan]📊 Active LLM servers: {len(enabled_llms)}/{total_llms} - {llm_display}[/cyan]")
    else:
        console.print("[yellow]⚠️  No enabled LLM servers found[/yellow]")
        console.print(
            "[dim]Chat will return a message until LLM servers are configured.[/dim]")

    # ChatManager 가져오기
    console.print("[cyan]🤖 Initializing chat manager...[/cyan]")
    chat_pipeline = get_chat_pipeline()
    if not chat_pipeline:
        console.print("[red]❌ Error: Chat manager not available[/red]")
        return

    console.print("[green]✓ Chat manager ready[/green]")

    # Show available agents
    agent_names = chat_pipeline.get_available_agent_names()
    if agent_names:
        console.print(
            f"[cyan]Available agents: {', '.join(agent_names)}[/cyan]")

    # Session info
    chat_history = ChatHistory(max_turns=max_turns)

    try:
        # Chat loop
        while True:
            try:
                # User input
                question = Prompt.ask("\n[bold blue]You[/bold blue]")

                # Special commands
                if question.lower() in ['exit', 'quit', 'q']:
                    console.print("[yellow]Goodbye![/yellow]")
                    break

                if question.lower() == 'clear':
                    console.clear()
                    console.print(Panel.fit(
                        "[bold cyan]MARU Chat CLI[/bold cyan]",
                        border_style="cyan"
                    ))
                    continue

                # Process chat
                answer = ""

                with console.status("[cyan]Processing...[/cyan]", spinner="dots"):
                    async for msg in chat_pipeline.run(
                        teams=teams,
                        question=question,
                        chat_history=chat_history,
                    ):
                        if msg.message_type == MessageType.INFO:
                            console.print(f"[dim]<INFO>[/dim]")
                            if msg.data and 'selected_agents' in msg.data:
                                agents = msg.data['selected_agents']
                                if agents:
                                    console.print(
                                        f"[bold cyan]Selected agents: {', '.join(agents)}[/bold cyan]")
                            console.print(f"[cyan]{msg.message}[/cyan]")
                            console.print(f"[dim]</INFO>[/dim]")
                        elif msg.message_type == MessageType.DEBUG:
                            console.print(f"[dim]<DEBUG>[/dim]")
                            console.print(f"[dim]{msg.message}[/dim]")
                            console.print(f"[dim]</DEBUG>[/dim]")
                        elif msg.message_type == MessageType.NORMAL:
                            if msg.data == "answer":
                                answer = msg.message

                        elif msg.message_type == MessageType.ERROR:
                            console.print(f"[dim]<Error>[/dim]")
                            console.print(f"[red]{msg.message}[/red]")
                            console.print(f"[dim]</Error>[/dim]")

                        elif msg.message_type == MessageType.WARNING:
                            console.print(f"[dim]<Warning>[/dim]")
                            console.print(f"[yellow]{msg.message}[/yellow]")
                            console.print(f"[dim]</Warning>[/dim]")
                        elif msg.message_type == MessageType.COMPLETE:
                            break

                # Display result
                if answer:
                    console.print("\n[bold green]Assistant:[/bold green]")

                    if isinstance(answer, str):
                        # Direct string response
                        md = Markdown(answer)
                        console.print(md)
                        final_answer = answer
                    else:
                        # Streaming response (AsyncGenerator)
                        final_answer = ""
                        with Live(console=console, refresh_per_second=10) as live:
                            async for chunk in answer:
                                final_answer += chunk
                                live.update(Markdown(final_answer))

                    # Save to history
                    chat_history.add_turn(question, final_answer)
                else:
                    console.print("[red]Failed to generate response[/red]")

            except KeyboardInterrupt:
                console.print(
                    "\n[yellow]Interrupted. Type 'exit' to quit.[/yellow]")
                continue
            except Exception as e:
                console.print(f"\n[red]Error: {str(e)}[/red]")
                continue

    except (KeyboardInterrupt, SystemExit):
        console.print("\n[yellow]Goodbye![/yellow]")
