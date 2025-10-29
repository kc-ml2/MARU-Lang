"""
LLM configuration models
"""
from dataclasses import dataclass, field
from typing import Dict, Any, Optional


@dataclass
class LLMConfig:
    """LLM server configuration"""
    name: str
    url: str
    model_name: str = ""
    description: str = ""
    api_key: Optional[str] = None
    timeout: float = 30.0
    enabled: bool = True
    max_retries: int = 3
    health_check_endpoint: str = "/health"
    headers: Dict[str, str] = field(default_factory=dict)
    config: Dict[str, Any] = field(default_factory=dict)
    health_check: Dict[str, Any] = field(default_factory=dict)
    cost_tracking: Dict[str, Any] = field(default_factory=dict)
    limits: Dict[str, Any] = field(default_factory=dict)
    retry: Dict[str, Any] = field(default_factory=dict)
    log_level: str = "INFO"
    source_path: str = ""
    is_override: bool = False

    def __post_init__(self):
        """Process environment variables in api_key"""
        if self.api_key and self.api_key.startswith('${') and self.api_key.endswith('}'):
            import os
            env_var = self.api_key[2:-1]
            self.api_key = os.getenv(env_var)