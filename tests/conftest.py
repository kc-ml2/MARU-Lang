"""Common test fixtures.

- Test config loading (defaults, no YAML needed)
- SQLite in-memory DB (Tortoise ORM)
- FastAPI TestClient (httpx AsyncClient)
- Auth helpers (JWT token generation)
"""
import sys
import types
from pathlib import Path

# Bypass maru_lang.__init__.py (avoid heavy app dependencies)
_pkg = types.ModuleType("maru_lang")
_pkg.__path__ = [str(Path(__file__).resolve().parent.parent / "maru_lang")]
_pkg.__package__ = "maru_lang"
sys.modules["maru_lang"] = _pkg

# Force default config (no YAML file needed for tests)
import maru_lang.configs.manager as _cfg_mod
from maru_lang.configs.models import MaruConfig
_cfg_mod._config = MaruConfig(database_url="sqlite://:memory:")

# Remaining imports
import pytest
from httpx import AsyncClient, ASGITransport
from tortoise import Tortoise
from fastapi import FastAPI
from datetime import timedelta

from maru_lang.core.relation_db.models.auth import User, Team, TeamMember
from maru_lang.utils.security import create_jwt_token

MODELS = ["maru_lang.core.relation_db.models"]


@pytest.fixture(autouse=True)
async def init_db():
    """Initialize SQLite in-memory DB per test."""
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": MODELS},
        use_tz=True,
    )
    await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()


@pytest.fixture()
def app() -> FastAPI:
    """Test FastAPI app (routers only, no lifespan)."""
    from maru_lang.api.endpoints.teams import router as teams_router

    test_app = FastAPI()
    test_app.include_router(teams_router)
    return test_app


@pytest.fixture()
async def client(app: FastAPI) -> AsyncClient:
    """httpx AsyncClient for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def make_token(user_id: int) -> str:
    """Generate a test JWT token."""
    token, _ = create_jwt_token(
        data={"sub": str(user_id)},
        expires_delta=timedelta(minutes=30),
    )
    return token


def auth_header(user_id: int) -> dict[str, str]:
    """Return an Authorization header dict."""
    return {"Authorization": f"Bearer {make_token(user_id)}"}


@pytest.fixture()
async def user_alice() -> User:
    return await User.create(name="Alice", email="alice@example.com")


@pytest.fixture()
async def user_bob() -> User:
    return await User.create(name="Bob", email="bob@example.com")


@pytest.fixture()
async def team_with_admin(user_alice: User) -> Team:
    """Team with Alice as admin."""
    team = await Team.create(name="TestTeam", manager=user_alice, is_private=True)
    await TeamMember.create(user=user_alice, team=team, role="admin")
    return team
