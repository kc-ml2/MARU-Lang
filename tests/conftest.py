"""
공통 테스트 fixtures
- 테스트 전용 config 로드 (test_config.yaml)
- SQLite in-memory DB (Tortoise ORM)
- FastAPI TestClient (httpx AsyncClient)
- 인증 헬퍼 (JWT 토큰 발급)
"""
import sys
import types
from pathlib import Path

# ── maru_lang.__init__.py 우회 (app.py → LLM 등 무거운 의존성 방지) ──
_pkg = types.ModuleType("maru_lang")
_pkg.__path__ = [str(Path(__file__).resolve().parent.parent / "maru_lang")]
_pkg.__package__ = "maru_lang"
sys.modules["maru_lang"] = _pkg

# ── 테스트 config 로드 ──
from maru_lang.configs.system_config import _system_config_loader

_test_config_path = Path(__file__).parent / "test_config.yaml"
_system_config_loader.config_path = _test_config_path
_system_config_loader.config = None
_system_config_loader.load()

# ── 나머지 import ──
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
    """매 테스트마다 SQLite in-memory DB 초기화 + 스키마 생성"""
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
    """테스트용 FastAPI 앱 (라우터만 등록, lifespan 제외)"""
    from maru_lang.api.endpoints.teams import router as teams_router

    test_app = FastAPI()
    test_app.include_router(teams_router)
    return test_app


@pytest.fixture()
async def client(app: FastAPI) -> AsyncClient:
    """httpx AsyncClient for testing"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def make_token(user_id: int) -> str:
    """테스트용 JWT 토큰 생성 헬퍼"""
    token, _ = create_jwt_token(
        data={"sub": str(user_id)},
        expires_delta=timedelta(minutes=30),
    )
    return token


def auth_header(user_id: int) -> dict[str, str]:
    """Authorization 헤더 딕셔너리 반환"""
    return {"Authorization": f"Bearer {make_token(user_id)}"}


@pytest.fixture()
async def user_alice() -> User:
    """테스트 사용자 Alice"""
    return await User.create(name="Alice", email="alice@example.com")


@pytest.fixture()
async def user_bob() -> User:
    """테스트 사용자 Bob"""
    return await User.create(name="Bob", email="bob@example.com")


@pytest.fixture()
async def team_with_admin(user_alice: User) -> Team:
    """Alice가 admin인 팀"""
    team = await Team.create(name="TestTeam", manager=user_alice, is_private=True)
    await TeamMember.create(user=user_alice, team=team, role="admin")
    return team
