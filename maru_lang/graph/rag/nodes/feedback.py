"""Feedback nodes — collect a score and (optionally) a reason for the answer."""
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.types import interrupt

from maru_lang.constants import FEEDBACK_REASON_THRESHOLD
from maru_lang.graph.rag.state import RagState


def feedback_route(state: RagState) -> str:
    """After generate: go to score in feedback mode, else to summarize (terminal)."""
    if state.get("function") == "feedback":
        return "score"
    return "summarize"


def score_node(state: RagState) -> dict:
    """Interrupt to collect a 1-5 rating from the user for the last answer."""
    score_raw = interrupt({"type": "feedback_score"})
    try:
        score = max(1, min(5, int(str(score_raw).strip())))
    except (ValueError, TypeError):
        score = None
    return {"feedback_score": score}


def score_route(state: RagState) -> str:
    """Route to reason if score is low, otherwise to summarize (terminal)."""
    score = state.get("feedback_score")
    if score is not None and score <= FEEDBACK_REASON_THRESHOLD:
        return "reason"
    return "summarize"


def make_reason_node(model: BaseChatModel):
    """Collect the reason for a low score, then generate a personalized thank-you."""
    async def reason_node(state: RagState) -> dict:
        reason = interrupt({"type": "feedback_reason"})
        response = await model.ainvoke([
            HumanMessage(content=(
                f"사용자가 답변에 낮은 점수를 주었고 그 이유는 다음과 같습니다: {reason}\n\n"
                "이 피드백을 받아들이고 개선하겠다는 내용을 한두 문장으로 짧게 답해주세요."
            ))
        ])
        return {"messages": [response], "feedback_reason": reason}
    return reason_node
