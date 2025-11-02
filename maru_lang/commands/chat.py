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
from maru_lang.pipelines.base import PipelineMessage, MessageType
from maru_lang.dependencies.chat import get_chat_pipeline
from maru_lang.pipelines.chat import ChatPipeline
from maru_lang.models.agents import AgentSelection, ExecutionResult, ChatResult, ChatProcess
from maru_lang.models.chat import ChatHistory
from maru_lang.configs.manager import get_config_manager
from maru_lang.enums.chat import ChatProcessStep


console = Console()


async def cleanup_resources(chat_pipeline: ChatPipeline):
    """Clean up resources on exit"""
    try:
        if chat_pipeline:
            # Close LLM clients
            if hasattr(chat_pipeline, 'agent_executor') and chat_pipeline.agent_executor:
                from maru_lang.dependencies.llm import get_llm_manager
                llm_manager = await get_llm_manager()
                await llm_manager.close_all()

            # Close generate agent LLM client
            if hasattr(chat_pipeline, 'generate_agent') and chat_pipeline.generate_agent:
                if hasattr(chat_pipeline.generate_agent, 'llm_client'):
                    await chat_pipeline.generate_agent.llm_client.close()

            # Close agent selector LLM client
            if hasattr(chat_pipeline, 'agent_selector') and chat_pipeline.agent_selector:
                if hasattr(chat_pipeline.agent_selector, 'llm_client'):
                    await chat_pipeline.agent_selector.llm_client.close()

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
    chat_pipeline = await get_chat_pipeline()
    if not chat_pipeline:
        console.print("[red]❌ Error: Chat manager not available[/red]")
        return

    console.print("[green]✓ Chat manager ready[/green]")

    # Available agents from selector
    if hasattr(chat_pipeline, 'agent_selector') and chat_pipeline.agent_selector:
        available_agents = chat_pipeline.agent_selector._get_available_agents()
        total_agents = len(available_agents)
        agent_names = [agent['name'] for agent in available_agents[:3]]
        agent_display = ", ".join(agent_names)
        if total_agents > 3:
            agent_display += f" (+{total_agents - 3} more)"
        console.print(
            f"[cyan]🤖 Available agents: {total_agents} - {agent_display}[/cyan]")

    # 세션 정보
    chat_history = ChatHistory(max_turns=max_turns)

    # 그룹 검증 (세션 시작 시 한 번만)
    from maru_lang.core.relation_db.models.documents import DocumentGroup, DocumentGroupInclusion

    if forced_groups == ["__all__"]:
        # 모든 최상위 그룹 가져오기
        top_level_groups = await DocumentGroup.filter(
            included_by__isnull=True
        ).distinct().values_list("name", flat=True)
        actual_forced_groups = list(top_level_groups)
        console.print(f"[dim]✓ Searching across {len(actual_forced_groups)} top-level groups[/dim]")
    else:
        # 특정 그룹이 명시된 경우: 존재하는 그룹인지 검증
        existing_groups = await DocumentGroup.filter(
            name__in=forced_groups
        ).values_list("name", flat=True)
        existing_groups = list(existing_groups)

        invalid_groups = set(forced_groups) - set(existing_groups)
        if invalid_groups:
            console.print(f"[red]❌ Invalid groups: {', '.join(invalid_groups)}[/red]")

            # 사용 가능한 모든 최상위 그룹 표시
            all_top_level = await DocumentGroup.filter(
                included_by__isnull=True
            ).distinct().values_list("name", flat=True)

            if all_top_level:
                console.print("\n[cyan]Available top-level groups:[/cyan]")
                for group in sorted(all_top_level):
                    console.print(f"  - {group}")
            else:
                console.print("[yellow]No document groups found in database[/yellow]")
            return  # 세션 종료

        actual_forced_groups = existing_groups
        if len(existing_groups) < len(forced_groups):
            console.print(f"[yellow]⚠️  Some groups not found - using {len(existing_groups)} valid groups[/yellow]")
        console.print(f"[dim]✓ Using groups: {', '.join(actual_forced_groups)}[/dim]")

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
                    async for step_result in chat_pipeline.process_stream(
                        question=question,
                        chat_history=chat_history,
                        forced_groups=actual_forced_groups
                    ):

                        if isinstance(step_result, PipelineMessage):
                            if step_result.message_type == MessageType.INFO:
                                console.print(
                                    f"[dim]  → {step_result.message}[/dim]")
                            elif step_result.message_type == MessageType.ERROR:
                                console.print(f"[red]❌ {step_result.message}[/red]")
                            elif step_result.message_type == MessageType.WARNING:
                                console.print(f"[yellow]  ⚠️ {step_result.message}[/yellow]")
                            continue
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
                                # Check if execution was successful
                                if execution_data.success:
                                    console.print(
                                        f"[dim]  → [green]✓[/green] Completed: {', '.join(agents_executed)}[/dim]")
                                else:
                                    # Show failed agents
                                    failed_agents = [name for name in agents_executed
                                                   if not execution_data.agent_results[name].success]
                                    if failed_agents:
                                        console.print(
                                            f"[dim]  → [red]✗[/red] Failed: {', '.join(failed_agents)}[/dim]")
                                    # Show successful agents if any
                                    success_agents = [name for name in agents_executed
                                                    if execution_data.agent_results[name].success]
                                    if success_agents:
                                        console.print(
                                            f"[dim]  → [green]✓[/green] Completed: {', '.join(success_agents)}[/dim]")

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
        await cleanup_resources(chat_pipeline)
