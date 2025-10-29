import asyncio
from typing import Dict, Any, Optional, List, Callable
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi_pagination import add_pagination

from maru_lang.core.relation_db import get_register_orm
from maru_lang.dependencies.llm import get_llm_manager
from maru_lang.tracing import get_tracing_status
from maru_lang.configs.manager import get_config_manager
from maru_lang.api.endpoints.auth import router as auth_router
from maru_lang.api.endpoints.chat import router as chat_router



class MaruLangApp(FastAPI):
    """확장 가능한 MaruLang 애플리케이션 클래스

    다른 프로젝트에서 이 클래스를 상속받아 커스텀 기능을 추가할 수 있습니다.
    """

    def __init__(
        self,
        title: str = "MaruLang API",
        description: str = "Advanced AI Agent Framework with RAG capabilities",
        version: str = "1.0.0",
        cors_origins: Optional[List[str]] = None,
        include_default_routers: bool = True,
        **fastapi_kwargs
    ):
        # 커스텀 훅들 초기화 (FastAPI.__init__ 전에)
        self._startup_hooks: List[Callable] = []
        self._shutdown_hooks: List[Callable] = []
        self._middleware_hooks: List[Callable] = []
        self._router_hooks: List[Callable] = []

        self.cors_origins = cors_origins or self._get_default_cors_origins()
        self.include_default_routers = include_default_routers

        # Lifespan 컨텍스트 매니저 생성
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            # 앱 시작 시
            await self._startup_sequence()
            yield
            # 앱 종료 시
            await self._shutdown_sequence()

        # FastAPI 초기화
        super().__init__(
            title=title,
            description=description,
            version=version,
            lifespan=lifespan,
            **fastapi_kwargs
        )

        # FastAPI extensions 및 middleware 설정
        add_pagination(self)
        self._setup_middleware()
        self._setup_routers()

    def _get_default_cors_origins(self) -> List[str]:
        """기본 CORS origins 반환"""
        return [
            "*",
        ]


    async def _startup_sequence(self):
        """앱 시작 시퀀스"""
        # 기본 시작 로직
        await self._default_startup()

        # 커스텀 시작 훅 실행
        for hook in self._startup_hooks:
            if asyncio.iscoroutinefunction(hook):
                await hook(self)
            else:
                hook(self)

    async def _shutdown_sequence(self):
        """앱 종료 시퀀스"""
        # 기본 종료 로직
        await self._default_shutdown()

        # 커스텀 종료 훅 실행
        for hook in self._shutdown_hooks:
            if asyncio.iscoroutinefunction(hook):
                await hook(self.app)
            else:
                hook(self.app)

    async def _default_startup(self):
        """기본 시작 로직"""
        # TODO 로깅 시스템 초기화
        config_manager = get_config_manager()
        config_manager.load_all()

        # 설정 검증
        validation_status = config_manager.validate_all()
        if not validation_status['valid']:
            print("❌ Configuration validation failed:")
            for error in validation_status['errors']:
                print(f"  - {error}")
            # Critical errors should stop the app
            if validation_status['errors']:
                raise RuntimeError("Critical configuration errors found")

        # 설정 요약 출력
        summary = config_manager.get_summary()
        print(f"  ✅ LLM: {summary['llm']['total']} servers")
        print(f"  ✅ Prompts: {summary['prompt']['total']} templates")
        print(f"  ✅ Groups: {len(config_manager.group_loader.all_groups)} groups")
        print(f"  ✅ Tools: {summary['tool']['total']} tools")

        # 2. ORM 등록
        print("🗄️ Initializing Databases...")
        register_orm = get_register_orm()
        async with register_orm(self):

            # 3. LLM 서버 초기화 (새로운 설정 시스템 사용)
            print("🤖 Initializing LLM Servers...")
            llm_manager = get_llm_manager()
            # LLMServerManager는 이미 ConfigLoader를 사용하도록 업데이트됨
            await llm_manager.initialize_servers()
            print(f"  ✅ Active servers: {llm_manager.get_active_servers_count()}/{llm_manager.get_all_servers_count()}")

            # Store config manager in app state for access in endpoints
            self.state.config_manager = config_manager

            # 4. Tracing 상태 확인
            tracing_status = get_tracing_status()
            print(f"📈 Tracing: {tracing_status['status']}")

            print("=" * 60)
            print("✨ Application startup complete!")
            print("=" * 60)

    async def _default_shutdown(self):
        """기본 종료 로직"""
        # DB 연결 해제 등의 정리 작업
        pass

    def _setup_middleware(self):
        """미들웨어 설정"""
        # 로깅 미들웨어 추가

        # 기본 액세스 토큰 미들웨어
        @self.middleware("http")
        async def add_access_token_header(request: Request, call_next):
            response = await call_next(request)
            if hasattr(request.state, "new_access_token"):
                response.headers["X-Access-Token"] = request.state.new_access_token
            return response

        # CORS 미들웨어
        self.add_middleware(
            CORSMiddleware,
            allow_origins=self.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Access-Token"],
        )

        # 커스텀 미들웨어 훅 실행
        for hook in self._middleware_hooks:
            hook(self.app)

    def _setup_routers(self):
        """라우터 설정"""
        # 기본 헬스체크 엔드포인트
        @self.get("/health")
        async def health_check():
            return {"status": "ok"}

        # 기본 라우터들 포함
        if self.include_default_routers:
            self.include_router(chat_router)
            self.include_router(auth_router)

        # 커스텀 라우터 훅 실행
        for hook in self._router_hooks:
            hook(self.app)

    # 확장 메서드들
    def add_startup_hook(self, func: Callable):
        """앱 시작 시 실행할 함수 추가"""
        self._startup_hooks.append(func)
        return self

    def add_shutdown_hook(self, func: Callable):
        """앱 종료 시 실행할 함수 추가"""
        self._shutdown_hooks.append(func)
        return self

    def add_middleware_hook(self, func: Callable):
        """미들웨어 설정 함수 추가"""
        self._middleware_hooks.append(func)
        return self

    def add_router_hook(self, func: Callable):
        """라우터 설정 함수 추가"""
        self._router_hooks.append(func)
        return self

    def get_fastapi_app(self) -> FastAPI:
        """내부 FastAPI 앱 인스턴스 반환"""
        return self

    def on_event(self, event_type: str):
        """이벤트 데코레이터 (deprecated in newer FastAPI, but kept for compatibility)"""
        if hasattr(super(), 'on_event'):
            return super().on_event(event_type)
        else:
            # For newer FastAPI versions, use startup/shutdown hooks
            if event_type == "startup":
                def decorator(func):
                    self.add_startup_hook(func)
                    return func
                return decorator
            elif event_type == "shutdown":
                def decorator(func):
                    self.add_shutdown_hook(func)
                    return func
                return decorator
            else:
                raise ValueError(f"Unsupported event type: {event_type}")

    def startup(self):
        """시작 이벤트 데코레이터"""
        def decorator(func):
            self.add_startup_hook(func)
            return func
        return decorator

    def shutdown(self):
        """종료 이벤트 데코레이터"""
        def decorator(func):
            self.add_shutdown_hook(func)
            return func
        return decorator


# 편의를 위한 기본 앱 인스턴스
def create_app(**kwargs) -> MaruLangApp:
    """기본 MaruLang 앱 생성"""
    return MaruLangApp(**kwargs)


default_app = create_app()
