"""
Builtin agents - core system agents
These agents are not customizable by users and are part of the core system
"""
from maru_lang.pluggable.agents.builtin.group_classifier import GroupClassifierAgent
from maru_lang.pluggable.agents.builtin.intent_extractor import IntentExtractorAgent
from maru_lang.pluggable.agents.builtin.keyword_extractor import KeywordExtractorAgent
from maru_lang.pluggable.agents.builtin.response_agent import ResponseAgent
from maru_lang.pluggable.agents.builtin.knowledge_search import KnowledgeSearchAgent

__all__ = [
    "GroupClassifierAgent",
    "IntentExtractorAgent",
    "KeywordExtractorAgent",
    "ResponseAgent",
    "KnowledgeSearchAgent",
]
