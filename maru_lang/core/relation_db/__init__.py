from .connection import get_register_orm, orm_context


# def get_tortoise_orm():
#     """
#     Get Tortoise ORM configuration lazily.
#
#     This function is called by Aerich when needed, avoiding issues with
#     configuration loading at import time.
#     """
#     from maru_lang.configs.system_config import get_system_config
#
#     config = get_system_config()
#     if not config:
#         raise RuntimeError(
#             "System configuration not found. Please run 'maru install' first."
#         )
#
#     return {
#         "connections": {"default": config.database.get_database_url()},
#         "apps": {
#             "models": {
#                 "models": ["maru_lang.models", "aerich.models"],
#                 "default_connection": "default",
#             },
#         },
#         "use_tz": True,
#     }


# Tortoise ORM configuration for Aerich
# This is evaluated lazily - only accessed when needed by Aerich commands
# try:
#     TORTOISE_ORM = get_tortoise_orm()
# except RuntimeError:
#     # If config not available at import time, set to None
#     # It will be initialized later when needed
#     TORTOISE_ORM = None

__all__ = [
    "get_register_orm",
    "orm_context",
    # "TORTOISE_ORM",
    # "get_tortoise_orm",
]
