"""
Migration utilities for automatic database migrations.
"""
import asyncio
from pathlib import Path
from typing import Optional
from aerich import Command
from maru_lang.configs.system_config import get_system_config


def get_migrations_location() -> str:
    """Get the migrations directory location inside the package."""
    # Get the directory where this file is located
    current_dir = Path(__file__).parent
    migrations_dir = current_dir / "migrations"
    return str(migrations_dir)


async def run_migrations(location: str = None, app: str = "models") -> bool:
    """
    Run pending migrations programmatically.

    Args:
        location: Path to migrations directory (defaults to package internal directory)
        app: App name in TORTOISE_ORM config

    Returns:
        True if migrations were applied successfully, False otherwise
    """
    try:
        # Use package-internal migrations directory if not specified
        if location is None:
            location = get_migrations_location()

        config = get_system_config()

        tortoise_config = {
            "connections": {"default": config.database.get_database_url()},
            "apps": {
                "models": {
                    "models": ["maru_lang.core.relation_db.models", "aerich.models"],
                    "default_connection": "default",
                },
            },
            "use_tz": True,
        }

        # Initialize aerich command
        command = Command(
            tortoise_config=tortoise_config,
            app=app,
            location=location
        )

        # Initialize aerich (creates aerich table if not exists)
        await command.init()

        # Check if there are pending migrations
        migrations = await command.upgrade()

        if migrations:
            print(f"✅ Applied {len(migrations)} migration(s):")
            for migration in migrations:
                print(f"   - {migration}")
        else:
            print("✅ Database is up to date (no pending migrations)")

        return True

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        return False


def run_migrations_sync(location: str = None, app: str = "models") -> bool:
    """
    Synchronous wrapper for run_migrations.

    Args:
        location: Path to migrations directory (defaults to package internal directory)
        app: App name in TORTOISE_ORM config

    Returns:
        True if migrations were applied successfully, False otherwise
    """
    return asyncio.run(run_migrations(location, app))


async def check_migrations_status(location: str = None, app: str = "models") -> dict:
    """
    Check the status of migrations without applying them.

    Args:
        location: Path to migrations directory (defaults to package internal directory)
        app: App name in TORTOISE_ORM config

    Returns:
        Dictionary with migration status information
    """
    try:
        # Use package-internal migrations directory if not specified
        if location is None:
            location = get_migrations_location()

        config = get_system_config()

        tortoise_config = {
            "connections": {"default": config.database.get_database_url()},
            "apps": {
                "models": {
                    "models": ["maru_lang.core.relation_db.models", "aerich.models"],
                    "default_connection": "default",
                },
            },
            "use_tz": True,
        }

        command = Command(
            tortoise_config=tortoise_config,
            app=app,
            location=location
        )

        await command.init()

        # Get migration history
        history = await command.history()

        return {
            "status": "ok",
            "history": history,
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
        }
