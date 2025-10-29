import asyncio
from typing import List, Optional
from pathlib import Path
from .client import LLMServerClient
from maru_lang.configs.manager import get_config_manager


class LLMServerManager:
    """LLM 서버 관리를 위한 클래스"""

    def __init__(self):
        """
        Args:
            config_manager: Unified config manager for all configurations
        """
        self.config_manager = get_config_manager()
        self.active_servers: List[LLMServerClient] = []
        self.all_servers: List[LLMServerClient] = []

    async def initialize_servers(self) -> None:
        """서버 초기화: yaml 파일에서 서버 설정을 로드하고 헬스체크 수행"""

        # 1. 설정 파일 로드
        import logging
        logging.info(f"🔄 Loading LLM server configurations...")

        # ConfigManager를 통해 모든 설정 로드
        self.config_manager.ensure_loaded()

        # LLM 설정만 가져오기
        llm_configs = list(self.config_manager.llm_loader.get_all().values())

        if not llm_configs:
            logging.error(
                f"❌ No server configurations found. Please add YAML configuration files.")
            return

        # 2. 각 설정에서 LLMServerClient 생성
        self.all_servers = [
            LLMServerClient(config)
            for config in llm_configs
        ]
        logging.info(f"📝 Loaded {len(self.all_servers)} server configurations")

        # 3. 헬스체크를 통해 활성 서버만 필터링
        logging.info(f"🔍 Health checking {len(self.all_servers)} servers...")
        await self.update_active_servers()

    async def update_active_servers(self, servers: List[LLMServerClient] = None) -> None:
        """헬스체크를 통해 활성 서버 목록을 업데이트"""
        if servers is None:
            servers = self.all_servers

        # 병렬로 헬스체크 수행
        health_check_tasks = [self._check_server_health(
            client) for client in servers]
        health_results = await asyncio.gather(*health_check_tasks, return_exceptions=True)

        # 활성 서버만 필터링
        self.active_servers = []
        for client, is_healthy in zip(servers, health_results):
            if is_healthy is True:
                self.active_servers.append(client)
                import logging
                logging.debug(
                    f"✅ LLM Server '{client.config.name}' is healthy")
            else:
                import logging
                logging.warning(
                    f"❌ LLM Server '{client.config.name}' is not responding")

    async def _check_server_health(self, client: LLMServerClient) -> bool:
        """개별 서버의 헬스체크"""
        try:
            return await client.health_check()
        except Exception as e:
            import logging
            logging.error(f"Health check failed for {client.config.name}: {e}")
            return False

    async def get_active_server(self) -> Optional[LLMServerClient]:
        """활성 서버 중 첫 번째 서버 반환 (향후 로드밸런싱 로직으로 확장 가능)"""
        if not self.active_servers:
            # 활성 서버가 없으면 다시 헬스체크 시도
            await self.update_active_servers()

        return self.active_servers[0] if self.active_servers else None

    def get_active_servers_count(self) -> int:
        """활성 서버 개수 반환"""
        return len(self.active_servers)

    def get_all_servers_count(self) -> int:
        """전체 서버 개수 반환"""
        return len(self.all_servers)

    async def reload_configurations(self) -> None:
        """설정 파일을 다시 로드하고 서버를 재초기화"""
        import logging
        logging.info("🔄 Reloading server configurations...")

        # 기존 클라이언트들을 정리
        for client in self.all_servers:
            await client.close()

        self.all_servers = []
        self.active_servers = []

        # ConfigManager를 통해 설정 재로드
        self.config_manager.reload_all()

        # 서버 재초기화
        await self.initialize_servers()

    async def close_all(self) -> None:
        """모든 서버 클라이언트를 안전하게 종료"""
        for client in self.all_servers:
            await client.close()

    def get_server_by_name(self, name: str) -> Optional[LLMServerClient]:
        """이름으로 서버 찾기"""
        for server in self.active_servers:
            if server.config.name == name:
                return server
        return None

    def get_server_by_model(self, model_name: str) -> Optional[LLMServerClient]:
        """모델 이름으로 서버 찾기"""
        for server in self.active_servers:
            if server.config.model_name == model_name:
                return server
        return None

    def list_active_servers(self) -> List[dict]:
        """활성 서버 목록 반환"""
        return [
            {
                "name": server.config.name,
                "url": server.config.url,
                "model": server.config.model_name
            }
            for server in self.active_servers
        ]

    def get_config_summary(self) -> dict:
        """설정 요약 정보 반환"""
        summary = self.config_manager.llm_loader.get_summary()
        summary.update({
            "active_servers": self.get_active_servers_count(),
            "all_servers": self.get_all_servers_count(),
            "active_list": [s.config.name for s in self.active_servers]
        })
        return summary

    async def add_server_from_file(self, yaml_path: str) -> bool:
        """새 yaml 파일에서 서버 추가"""
        try:
            # 설정 파일 로드 - ConfigManager를 통해 다시 로드
            self.config_manager.reload_all()

            # 새로 추가된 설정 찾기
            path = Path(yaml_path)
            config_name = path.stem

            config = self.config_manager.llm_loader.get(config_name)
            if config:
                client = LLMServerClient(config)

                # 헬스체크
                if await client.health_check():
                    self.all_servers.append(client)
                    self.active_servers.append(client)
                    import logging
                    logging.info(
                        f"✅ Added and activated server: {config.name}")
                    return True
                else:
                    self.all_servers.append(client)
                    import logging
                    logging.warning(
                        f"⚠️ Added server but not active: {config.name}")
                    return False

        except Exception as e:
            import logging
            logging.error(f"❌ Failed to add server from {yaml_path}: {e}")

        return False
