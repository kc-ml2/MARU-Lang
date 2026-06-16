"""Tests for config-driven checkpointer target resolution."""
from pathlib import Path

from maru_lang.configs.models import MaruConfig


class TestResolveCheckpointTarget:
    def test_sqlite_derives_sibling_file_and_absolute(self):
        scheme, target = MaruConfig(database_url="sqlite:///chatbot.db").resolve_checkpoint_target()
        assert scheme == "sqlite"
        p = Path(target)
        assert p.is_absolute()
        # Separate file from the relational DB, derived from its name.
        assert p.name == "chatbot.db.checkpoints"
        assert p.name != "chatbot.db"

    def test_sqlite_memory_stays_in_memory(self):
        scheme, target = MaruConfig(database_url="sqlite://:memory:").resolve_checkpoint_target()
        assert (scheme, target) == ("sqlite", ":memory:")

    def test_explicit_checkpoint_url_is_used_verbatim(self):
        scheme, target = MaruConfig(
            database_url="sqlite:///chatbot.db",
            checkpoint_db_url="sqlite:///custom.db",
        ).resolve_checkpoint_target()
        assert scheme == "sqlite"
        # Explicit path is not turned into a sibling .checkpoints file.
        assert Path(target).name == "custom.db"

    def test_postgres_normalizes_scheme_for_psycopg(self):
        scheme, target = MaruConfig(
            database_url="postgres://u:p@host:5432/maru"
        ).resolve_checkpoint_target()
        assert scheme == "postgres"
        assert target == "postgresql://u:p@host:5432/maru"

    def test_postgresql_scheme_passthrough(self):
        scheme, target = MaruConfig(
            database_url="postgresql://u:p@host/maru"
        ).resolve_checkpoint_target()
        assert scheme == "postgres"
        assert target == "postgresql://u:p@host/maru"
