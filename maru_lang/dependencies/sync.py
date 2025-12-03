from fastapi import WebSocket
from maru_lang.core.sync import SyncConnectionManager

# Singleton instance
_sync_manager: SyncConnectionManager | None = None


def get_sync_manager() -> SyncConnectionManager:
    """
    Get the global SyncConnectionManager instance.

    This follows the dependency injection pattern used in other parts of the codebase.
    """
    global _sync_manager
    if _sync_manager is None:
        _sync_manager = SyncConnectionManager()
    return _sync_manager


def reset_sync_manager():
    """Reset the SyncConnectionManager instance (useful for testing or cleanup)"""
    global _sync_manager
    _sync_manager = None


def get_user_connection(user_id: int) -> WebSocket | None:
    """Get the user's connection"""
    return get_sync_manager().get_connection(user_id)