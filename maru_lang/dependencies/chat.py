"""
Chat Pipeline dependency
"""
from maru_lang.pluggable.agents.agent_executor import AgentExecutor
from maru_lang.pluggable.agents.agent_factory import AgentFactory
from maru_lang.pluggable.agents.agent_selector import AgentSelector
from maru_lang.pipelines.chat import ChatPipeline

async def get_chat_manager() -> ChatPipeline | None:
    """Get ChatPipeline instance with all dependencies"""

    # Register all agents from config
    agents = AgentFactory().create_agents_from_config()

    # Create executor and factory
    agent_executor = AgentExecutor()
    for agent in agents.values():
        agent_executor.register_agent(agent)

    # Create selector
    agent_selector = AgentSelector()

    if not all([agent_selector, agent_executor]):
        return None

    return ChatPipeline(agent_selector, agent_executor)
