"""
CLI 채팅 명령어
"""
import asyncio
from datetime import datetime
from typing import Optional, List
from rich.console import Console
from rich.prompt import Prompt
from rich.panel import Panel
from rich.markdown import Markdown
from maru_lang.dependencies.chat import get_chat_manager
from maru_lang.pipelines.chat import ChatPipeline
from maru_lang.models.agents import AgentSelection, ExecutionResult, ChatResult, ChatProcess
from maru_lang.models.chat import ChatHistory
from maru_lang.configs.manager import get_config_manager
from maru_lang.enums.chat import ChatProcessStep


console = Console()


async def cleanup_resources(chat_manager: ChatPipeline):
    """Clean up resources on exit"""
    try:
        if chat_manager:
            # Close LLM clients
            if hasattr(chat_manager, 'agent_executor') and chat_manager.agent_executor:
                from maru_lang.dependencies.llm import get_llm_manager
                llm_manager = await get_llm_manager()
                await llm_manager.close_all()

            # Close generate agent LLM client
            if hasattr(chat_manager, 'generate_agent') and chat_manager.generate_agent:
                if hasattr(chat_manager.generate_agent, 'llm_client'):
                    await chat_manager.generate_agent.llm_client.close()

            # Close agent selector LLM client
            if hasattr(chat_manager, 'agent_selector') and chat_manager.agent_selector:
                if hasattr(chat_manager.agent_selector, 'llm_client'):
                    await chat_manager.agent_selector.llm_client.close()

        console.print("[dim]Resources cleaned up[/dim]")
    except Exception as e:
        # Ignore cleanup errors during shutdown
        pass


async def chat_session(
    forced_groups: List[str],
    max_turns: int = 0
):
    """
    인터랙티브 어드민 채팅 세션

    Args:
        document_groups: 검색할 문서 그룹 리스트
    """

    # 그룹 설정 및 표시
    if forced_groups == ["__all__"]:
        display_groups = "ALL"
    else:
        display_groups = ", ".join(forced_groups)

    # 초기화
    console.print(Panel.fit(
        "[bold cyan]🤖 LLM Chatbot Admin CLI[/bold cyan]\n"
        f"[yellow]Document Groups: {display_groups}[/yellow]\n"
        "Type 'exit' or 'quit' to end the session\n"
        "Type 'clear' to clear the screen\n"
        "Type 'history' to view conversation history",
        border_style="cyan"
    ))

    console.print(
        f"[green]✓ Admin session started (Groups: {display_groups})[/green]\n")

    # ConfigManager 초기화
    console.print("[cyan]📋 Initializing configurations...[/cyan]")
    config_manager = get_config_manager()

    try:
        config_results = config_manager.load_all()
        config_status = config_manager.validate_all()

        # Always show configuration summary
        console.print("[green]✓ Configurations loaded successfully[/green]")

        # LLM servers with names
        llm_configs = config_results.get('llm', {})
        llm_names = list(llm_configs.keys())[:3]  # 최대 3개
        llm_display = ", ".join(llm_names)
        if len(llm_configs) > 3:
            llm_display += f" (+{len(llm_configs) - 3} more)"
        console.print(
            f"  - LLM Servers ({len(llm_configs)}): {llm_display}" if llm_configs else "  - LLM Servers: None")

        # Agents with names (exclude builtin agents)
        agent_configs = config_results.get('agent', {})
        # Filter out builtin agents
        user_agents = {name: config for name, config in agent_configs.items()
                      if config.type != 'builtin'}
        agent_names = list(user_agents.keys())[:3]  # 최대 3개
        agent_display = ", ".join(agent_names)
        if len(user_agents) > 3:
            agent_display += f" (+{len(user_agents) - 3} more)"
        console.print(
            f"  - Agents ({len(user_agents)}): {agent_display}" if user_agents else "  - Agents: None")

        # Groups with document/user separation
        # TODO: 그룹 설정 파일 분리
        group_configs = config_results.get('group', {})
        if group_configs:
            # Collect all document groups
            doc_groups = []

            for group_config in group_configs.values():
                if hasattr(group_config, 'groups'):
                    for group_name, group_info in group_config.groups.items():
                        doc_groups.append(group_name)

            # Display document groups
            doc_display = ", ".join(doc_groups[:3])
            if len(doc_groups) > 3:
                doc_display += f" (+{len(doc_groups) - 3} more)"
            console.print(
                f"  - Filtered groups applied ({len(doc_groups)}): {doc_display}" if doc_groups else "  - Filtered groups applied: None")
        else:
            console.print("  - Filtered groups applied: None")

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

    # LLM 서버 상태 확인
    enabled_llms = config_manager.llm_loader.get_enabled_configs()
    if not enabled_llms:
        console.print("[yellow]❌ No enabled LLM servers found[/yellow]")
        return

    total_llms = len(config_manager.llm_loader.configs)

    llm_names = [llm.name for llm in enabled_llms[:3]]
    llm_display = ", ".join(llm_names)
    if len(enabled_llms) > 3:
        llm_display += f" (+{len(enabled_llms) - 3} more)"
    console.print(
        f"[cyan]📊 Active LLM servers: {len(enabled_llms)}/{total_llms} - {llm_display}[/cyan]")

    # ChatManager 가져오기
    console.print("[cyan]🤖 Initializing chat manager...[/cyan]")
    chat_manager = await get_chat_manager()
    if not chat_manager:
        console.print("[red]❌ Error: Chat manager not available[/red]")
        return

    console.print("[green]✓ Chat manager ready[/green]")

    # 세션 정보
    chat_history = ChatHistory(max_turns=max_turns)  # 최근 0턴만 유지

    try:
        # 채팅 루프
        while True:
            try:
                # 사용자 입력
                question = Prompt.ask("\n[bold blue]You[/bold blue]")

                # 특수 명령어 처리
                if question.lower() in ['exit', 'quit', 'q']:
                    console.print("[yellow]👋 Goodbye![/yellow]")
                    break

                if question.lower() == 'clear':
                    console.clear()
                    console.print(Panel.fit(
                        "[bold cyan]🤖 LLM Chatbot CLI[/bold cyan]",
                        border_style="cyan"
                    ))
                    continue

                # 채팅 처리 (yield 방식)
                answer = ""
                result: ChatResult = None
                with console.status("[cyan]🤔 Selecting agents...[/cyan]", spinner="dots") as status:
                    async for step_result in chat_manager.process_stream(
                        question=question,
                        chat_history=chat_history,
                        forced_groups=forced_groups if forced_groups != ["__all__"] else None
                    ):
                        step = step_result.step

                        # 단계별 상태 표시
                        if step == ChatProcessStep.AGENT_SELECTION:
                            selection: AgentSelection = step_result.data
                            if not selection.selected_agents:
                                console.print(
                                    "[dim]  → No agents selected[/dim]")
                                console.print(
                                    f"[dim]  → {selection.reasoning}[/dim]")
                                continue

                            selected_agents = selection.selected_agents
                            # 더 눈에 띄게 에이전트 선택 표시
                            agent_display = ' | '.join(
                                [f"[bold yellow]{agent}[/bold yellow]" for agent in selected_agents])
                            console.print(
                                f"  [green]✓[/green] Selected Agents: {agent_display}")
                            console.print(
                                f"[dim]  → {selection.reasoning}[/dim]")
                            status.update(
                                "[cyan]⚙️  Executing agents...[/cyan]")


                        elif step == ChatProcessStep.AGENT_EXECUTION:
                            execution_data: ExecutionResult = step_result.data
                            agents_executed = list(
                                execution_data.agent_results.keys())
                            
                            if agents_executed:
                                console.print(
                                    f"[dim]  → Running: {', '.join(agents_executed)}[/dim]")

                            status.update(
                                "[cyan]✍️  Generating answer...[/cyan]")

                        elif step == ChatProcessStep.ANSWER_GENERATION:
                            answer = step_result.data

                        elif step == ChatProcessStep.COMPLETED:
                            result = step_result.data
                            break

                # 결과 처리
                if answer:
                    # 답변 출력
                    console.print("\n[bold green]Assistant:[/bold green]")

                    # Markdown 형식으로 답변 렌더링
                    md = Markdown(answer)
                    console.print(md)

                    # 참조 문서 표시 (있는 경우)
                    # if result.get("documents"):
                    #     console.print(
                    #         f"\n[dim]📚 Referenced {len(result['documents'])} documents[/dim]")

                    # 대화 기록 저장
                    chat_history.add_turn(question, answer)
                else:
                    console.print("[red]❌ Failed to generate response[/red]")

                # TODO
                if result:
                    pass
                    # console.print(f"[dim]📚 Referenced {len(result.documents)} documents[/dim]")

            except KeyboardInterrupt:
                console.print(
                    "\n[yellow]⚠️  Interrupted. Type 'exit' to quit.[/yellow]")
                continue
            except Exception as e:
                console.print(f"\n[red]❌ Error: {str(e)}[/red]")
                continue

    except (KeyboardInterrupt, SystemExit):
        console.print("\n[yellow]👋 Goodbye![/yellow]")
    finally:
        # Cleanup on exit
        await cleanup_resources(chat_manager)
