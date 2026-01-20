"""
Chat Pipeline dependency
"""
from typing import Optional
from maru_lang.pluggable.agents.agent_executor import AgentExecutor
from maru_lang.pluggable.agents.agent_factory import AgentFactory
from maru_lang.pluggable.agents.agent_selector import AgentSelector
from maru_lang.pipelines.chat import ChatPipeline


class ChatPipelineManager:
    """Singleton manager for ChatPipeline instance"""
    _instance: Optional[ChatPipeline] = None
    _initialized: bool = False

    @classmethod
    def get_instance(cls) -> ChatPipeline | None:
        """Get or create ChatPipeline singleton instance"""
        if not cls._initialized:
            cls._instance = cls._create_pipeline()
            cls._initialized = True
        return cls._instance

    @classmethod
    def _create_pipeline(cls) -> ChatPipeline | None:
        """Create ChatPipeline instance with all dependencies"""
        try:
            # Register all agents from config
            agents = AgentFactory().create_agents_from_config()

            # Create executor and register agents
            agent_executor = AgentExecutor()
            for agent in agents.values():
                agent_executor.register_agent(agent)

            # Create selector
            agent_selector = AgentSelector()

            if not all([agent_selector, agent_executor]):
                return None

            return ChatPipeline(agent_selector, agent_executor)
        except Exception as e:
            print(f"❌ Failed to create ChatPipeline: {e}")
            return None

    @classmethod
    def reset(cls):
        """Reset singleton instance (useful for testing)"""
        cls._instance = None
        cls._initialized = False


def get_chat_pipeline() -> ChatPipeline | None:
    """Dependency to get ChatPipeline singleton instance"""
    return ChatPipelineManager.get_instance()
