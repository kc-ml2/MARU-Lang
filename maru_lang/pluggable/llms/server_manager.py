import asyncio
from typing import List, Optional
from pathlib import Path
from .client import LLMServerClient
from maru_lang.configs.manager import get_config_manager


class LLMServerManager:
    """Manage lifecycle and health of configured LLM servers."""

    def __init__(self):
        """
        Args:
            config_manager: Unified config manager for all configurations
        """
        self.config_manager = get_config_manager()
        self.active_servers: List[LLMServerClient] = []
        self.all_servers: List[LLMServerClient] = []

    async def initialize_servers(self) -> None:
        """Load LLM configurations and perform health checks."""

        # 1. Load configuration files
        import logging
        logging.info(f"🔄 Loading LLM server configurations...")

        # Ensure the config manager has loaded every configuration
        self.config_manager.ensure_loaded()

        # Retrieve only LLM configurations
        llm_configs = list(self.config_manager.llm_loader.get_all().values())

        if not llm_configs:
            logging.error(
                f"❌ No server configurations found. Please add YAML configuration files.")
            return

        # 2. Create clients for each configuration
        self.all_servers = [
            LLMServerClient(config)
            for config in llm_configs
        ]
        logging.info(f"📝 Loaded {len(self.all_servers)} server configurations")

        # 3. Filter out unhealthy servers via health checks
        logging.info(f"🔍 Health checking {len(self.all_servers)} servers...")
        await self.update_active_servers()

    async def update_active_servers(self, servers: List[LLMServerClient] = None) -> None:
        """Refresh the list of active servers using health checks."""
        if servers is None:
            servers = self.all_servers

        # Run health checks concurrently
        health_check_tasks = [self._check_server_health(
            client) for client in servers]
        health_results = await asyncio.gather(*health_check_tasks, return_exceptions=True)

        # Keep only healthy servers
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
        """Run a health check against a single server."""
        try:
            return await client.health_check()
        except Exception as e:
            import logging
            logging.error(f"Health check failed for {client.config.name}: {e}")
            return False

    async def get_active_server(self) -> Optional[LLMServerClient]:
        """Return the first active server (placeholder for load-balancing)."""
        if not self.active_servers:
            # Refresh active servers when none are available
            await self.update_active_servers()

        return self.active_servers[0] if self.active_servers else None

    def get_active_servers_count(self) -> int:
        """Return the number of active servers."""
        return len(self.active_servers)

    def get_all_servers_count(self) -> int:
        """Return the total number of configured servers."""
        return len(self.all_servers)

    async def reload_configurations(self) -> None:
        """Reload configuration files and reinitialize servers."""
        import logging
        logging.info("🔄 Reloading server configurations...")

        # Close existing clients
        for client in self.all_servers:
            await client.close()

        self.all_servers = []
        self.active_servers = []

        # Reload all configurations via the config manager
        self.config_manager.reload_all()

        # Reinitialize servers
        await self.initialize_servers()

    async def close_all(self) -> None:
        """Close every server client gracefully."""
        for client in self.all_servers:
            await client.close()

    def get_server_by_name(self, name: str) -> Optional[LLMServerClient]:
        """Return an active server by name."""
        for server in self.active_servers:
            if server.config.name == name:
                return server
        return None

    def get_server_by_model(self, model_name: str) -> Optional[LLMServerClient]:
        """Return an active server by model name."""
        for server in self.active_servers:
            if server.config.model_name == model_name:
                return server
        return None

    def list_active_servers(self) -> List[dict]:
        """Return metadata for active servers."""
        return [
            {
                "name": server.config.name,
                "url": server.config.url,
                "model": server.config.model_name
            }
            for server in self.active_servers
        ]

    def get_config_summary(self) -> dict:
        """Return a summary of server configuration and health."""
        summary = self.config_manager.llm_loader.get_summary()
        summary.update({
            "active_servers": self.get_active_servers_count(),
            "all_servers": self.get_all_servers_count(),
            "active_list": [s.config.name for s in self.active_servers]
        })
        return summary

    async def add_server_from_file(self, yaml_path: str) -> bool:
        """Add a server configuration from a newly created YAML file."""
        try:
            # Reload configurations through the config manager
            self.config_manager.reload_all()

            # Locate the newly added configuration
            path = Path(yaml_path)
            config_name = path.stem

            config = self.config_manager.llm_loader.get(config_name)
            if config:
                client = LLMServerClient(config)

                # Perform a health check before marking as active
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
