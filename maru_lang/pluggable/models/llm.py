"""
LLM configuration models
"""
import os
from dataclasses import dataclass, field
from typing import Dict, Any, Optional


@dataclass
class LLMConfig:
    """LLM server configuration"""
    name: str
    provider: str  # "openai", "anthropic", "google", "mistral", "ollama", etc.
    model_name: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None  # For custom endpoints (vLLM, etc.)
    enabled: bool = True
    description: str = ""
    # temperature, max_tokens, etc.
    config: Dict[str, Any] = field(default_factory=dict)
    source_path: str = ""
    is_override: bool = False

    def __post_init__(self):
        """Process environment variables in api_key"""
        if self.api_key and self.api_key.startswith('${') and self.api_key.endswith('}'):
            env_var = self.api_key[2:-1]
            self.api_key = os.getenv(env_var)
