"""
Group configuration models
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List


@dataclass
class GroupConfig:
    """Group configuration for chatbot categorization"""
    name: str
    description: str = ""
    force_rag: bool = False
    permissions: List[str] = field(default_factory=list)
    prompts: List[str] = field(default_factory=list)
    priority: str = "normal"  # high, normal, low
    weight: float = 1.0
    settings: Dict[str, Any] = field(default_factory=dict)
    source_path: str = ""
    is_override: bool = False


@dataclass
class GroupsConfig:
    """Complete groups configuration including priorities"""
    group_priorities: Dict[str, Any] = field(default_factory=dict)
    groups: Dict[str, GroupConfig] = field(default_factory=dict)
    tool_choice_reason: Dict[str, str] = field(default_factory=dict)
    source_path: str = ""
    is_override: bool = False