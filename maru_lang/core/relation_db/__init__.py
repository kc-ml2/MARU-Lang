from .connection import get_register_orm, orm_context
from maru_lang.configs.system_config import get_system_config

# Get system configuration
config = get_system_config()

# Tortoise ORM configuration for Aerich
TORTOISE_ORM = {
    "connections": {"default": config.database.get_database_url()},
    "apps": {
        "models": {
            "models": ["maru_lang.models", "aerich.models"],
            "default_connection": "default",
        },
    },
    "use_tz": True,
}

__all__ = [
    "get_register_orm",
    "orm_context",
    "TORTOISE_ORM",
]
