"""Generate node — produce the final answer (optionally using retrieved context)."""
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import SystemMessage

from maru_lang.constants import SYSTEM_PROMPT
from maru_lang.graph.rag.state import RagState


def make_generate_node(llm: BaseChatModel, system_prompt: str = ""):
    """Produce the final answer, injecting memory and (if searched) retrieved context."""
    prompt = system_prompt or SYSTEM_PROMPT

    async def generate_node(state: RagState) -> dict:
        history = [m for m in state.get("messages", []) if not isinstance(m, SystemMessage)]

        prompt_msgs = [SystemMessage(content=prompt)]
        memory = state.get("memory_context")
        if memory:
            prompt_msgs.append(SystemMessage(content=f"이전 대화 맥락:\n\n{memory}"))
        result = state.get("result")
        if result:
            prompt_msgs.append(SystemMessage(
                content=f"다음은 내부 문서 검색 결과다. 이를 근거로 답하라:\n\n{result}"
            ))
        prompt_msgs += history

        response = await llm.ainvoke(prompt_msgs)
        # Keep the answer in state so the write-back tail uses this generated
        # answer (not, e.g., the reason node's follow-up thank-you message).
        return {"messages": [response], "answer": response.content}

    return generate_node
