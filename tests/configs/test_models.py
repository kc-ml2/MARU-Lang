"""Config models unit tests."""
import os

import pytest

from maru_lang.configs.manager import _validate_auth_security
from maru_lang.configs.models import LLMConfig, MaruConfig, AuthConfig, ServerConfig


class TestLLMConfig:
    def test_env_var_substitution(self, monkeypatch):
        monkeypatch.setenv("TEST_API_KEY", "sk-test")
        config = LLMConfig(api_key="${TEST_API_KEY}")
        assert config.api_key == "sk-test"

    def test_env_var_not_set(self):
        config = LLMConfig(api_key="${NONEXISTENT_VAR_12345}")
        assert config.api_key is None

    def test_normal_api_key_unchanged(self):
        config = LLMConfig(api_key="sk-plain")
        assert config.api_key == "sk-plain"

    def test_defaults(self):
        config = LLMConfig()
        assert config.name == ""
        assert config.provider == ""
        assert config.enabled is True
        assert config.config == {}


class TestMaruConfig:
    def test_from_dict_full(self):
        data = {
            "production": True,
            "database_url": "sqlite:///test.db",
            "vector_db_url": "chroma://data/chroma/test",
            "storage_dir": "data/storage/test",
            "embedding_model": "custom-model",
            "retriever_top_k": 10,
            "retriever_search_method": "hybrid",
            "system_prompt": "You are a helpful assistant.",
            "evaluate_method": "llm",
            "reranker_enabled": True,
            "reranker_type": "llm",
            "reranker_model": "custom-reranker",
            "reranker_top_k": 3,
            "server": {"host": "0.0.0.0", "port": 9000},
            "auth": {"secret_key": "new-secret", "allowed_domains": ["example.com"]},
        }
        config = MaruConfig.from_dict(data)
        assert config.production is True
        assert config.database_url == "sqlite:///test.db"
        assert config.embedding_model == "custom-model"
        assert config.retriever_top_k == 10
        assert config.retriever_search_method == "hybrid"
        assert config.system_prompt == "You are a helpful assistant."
        assert config.evaluate_method == "llm"
        assert config.reranker_enabled is True
        assert config.server.host == "0.0.0.0"
        assert config.server.port == 9000
        assert config.auth.secret_key == "new-secret"
        assert config.auth.allowed_domains == ["example.com"]

    def test_from_dict_partial(self):
        data = {"embedding_model": "custom"}
        config = MaruConfig.from_dict(data)
        assert config.embedding_model == "custom"
        assert config.server.host == "127.0.0.1"
        assert config.server.port == 8000

    def test_from_dict_empty(self):
        config = MaruConfig.from_dict({})
        assert config.embedding_model == "BAAI/bge-m3"
        assert config.production is False
        assert config.llms == []
        assert config.server.host == "127.0.0.1"
        assert config.retriever_top_k == 5

    def test_from_dict_llm_parsing(self):
        data = {
            "llms": [
                {
                    "name": "gpt4",
                    "provider": "openai",
                    "model_name": "gpt-4",
                    "api_key": "sk-abc123",
                }
            ]
        }
        config = MaruConfig.from_dict(data)
        assert len(config.llms) == 1
        llm = config.llms[0]
        assert isinstance(llm, LLMConfig)
        assert llm.name == "gpt4"
        assert llm.provider == "openai"
        assert llm.model_name == "gpt-4"
        assert llm.api_key == "sk-abc123"

    def test_from_dict_ignores_unknown_keys(self):
        data = {"unknown_key": "value", "another_unknown": 42}
        config = MaruConfig.from_dict(data)
        assert config.embedding_model == "BAAI/bge-m3"

    def test_get_database_url_absolute(self):
        config = MaruConfig(database_url="sqlite:///chatbot.db")
        result = config.get_database_url_absolute()
        assert "sqlite:///" in result
        assert result.startswith("sqlite:///")
        # The path should be absolute (not just "chatbot.db")
        path_part = result[len("sqlite:///"):]
        assert os.path.isabs(path_part)

    def test_parse_vector_db_url_chroma(self):
        config = MaruConfig(vector_db_url="chroma://data/chroma/maru")
        scheme, path, name = config.parse_vector_db_url()
        assert scheme == "chroma"
        assert path == "data/chroma"
        assert name == "maru"


class TestAuthConfig:
    def test_is_domain_allowed_empty_list(self):
        auth = AuthConfig(allowed_domains=[])
        assert auth.is_domain_allowed("user@anything.com") is True

    def test_is_domain_allowed_match(self):
        auth = AuthConfig(allowed_domains=["example.com"])
        assert auth.is_domain_allowed("user@example.com") is True

    def test_is_domain_allowed_no_match(self):
        auth = AuthConfig(allowed_domains=["example.com"])
        assert auth.is_domain_allowed("user@blocked.com") is False

    def test_is_domain_allowed_case_insensitive(self):
        auth = AuthConfig(allowed_domains=["Example.COM"])
        assert auth.is_domain_allowed("user@example.com") is True


class TestServerConfig:
    def test_defaults(self):
        config = ServerConfig()
        assert config.host == "127.0.0.1"
        assert config.port == 8000


class TestAuthSecurityValidation:
    """`_validate_auth_security` must fail-fast on insecure production credentials."""

    _VALID_SECRET = "x" * 32  # >= 32 chars, not a known default
    _VALID_SALT = "y" * 16    # >= 16 chars, not a known default

    def test_non_production_skips_validation(self):
        cfg = MaruConfig(production=False, auth=AuthConfig(secret_key="", salt=""))
        _validate_auth_security(cfg)  # must not raise

    def test_production_empty_secret_raises(self):
        cfg = MaruConfig(
            production=True,
            auth=AuthConfig(secret_key="", salt=self._VALID_SALT),
        )
        with pytest.raises(ValueError, match="secret_key"):
            _validate_auth_security(cfg)

    def test_production_default_secret_raises(self):
        cfg = MaruConfig(
            production=True,
            auth=AuthConfig(
                secret_key="your-secret-key-change-in-production",
                salt=self._VALID_SALT,
            ),
        )
        with pytest.raises(ValueError, match="secret_key"):
            _validate_auth_security(cfg)

    def test_production_short_secret_raises(self):
        cfg = MaruConfig(
            production=True,
            auth=AuthConfig(secret_key="short", salt=self._VALID_SALT),
        )
        with pytest.raises(ValueError, match="secret_key"):
            _validate_auth_security(cfg)

    def test_production_empty_salt_raises(self):
        cfg = MaruConfig(
            production=True,
            auth=AuthConfig(secret_key=self._VALID_SECRET, salt=""),
        )
        with pytest.raises(ValueError, match="salt"):
            _validate_auth_security(cfg)

    def test_production_default_salt_raises(self):
        cfg = MaruConfig(
            production=True,
            auth=AuthConfig(secret_key=self._VALID_SECRET, salt="some-salt"),
        )
        with pytest.raises(ValueError, match="salt"):
            _validate_auth_security(cfg)

    def test_production_short_salt_raises(self):
        cfg = MaruConfig(
            production=True,
            auth=AuthConfig(secret_key=self._VALID_SECRET, salt="tiny"),
        )
        with pytest.raises(ValueError, match="salt"):
            _validate_auth_security(cfg)

    def test_production_valid_credentials_pass(self):
        cfg = MaruConfig(
            production=True,
            auth=AuthConfig(secret_key=self._VALID_SECRET, salt=self._VALID_SALT),
        )
        _validate_auth_security(cfg)  # must not raise


class TestGetConfigCaching:
    """`get_config` must not cache insecure production configs (regression for P1 review)."""

    def test_config_parse_failure_raises_not_fallback(self, tmp_path, monkeypatch):
        """If maru_config.yaml exists but is malformed, startup must fail closed
        instead of silently falling back to insecure defaults (production=False)."""
        import maru_lang.configs.manager as mgr

        monkeypatch.setattr(mgr, "_config", None)

        app_dir = tmp_path / "maru_app"
        app_dir.mkdir()
        # Malformed YAML — unquoted tab char in value causes parse error
        (app_dir / "maru_config.yaml").write_text(
            "production: true\n"
            "auth:\n"
            "  secret_key: [unclosed\n",  # Malformed list
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)

        with pytest.raises(Exception):
            mgr.get_config()

        # _config must remain None so next call re-attempts
        assert mgr._config is None

    def test_insecure_production_config_not_cached_on_failure(self, tmp_path, monkeypatch):
        """ValueError from security validation must leave `_config` untouched so the
        next call re-reads and re-validates instead of returning the insecure config."""
        import maru_lang.configs.manager as mgr

        monkeypatch.setattr(mgr, "_config", None)

        app_dir = tmp_path / "maru_app"
        app_dir.mkdir()
        (app_dir / "maru_config.yaml").write_text(
            "production: true\n"
            "auth:\n"
            "  secret_key: your-secret-key-change-in-production\n"
            "  salt: some-salt\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)

        with pytest.raises(ValueError):
            mgr.get_config()

        # Regression: _config MUST NOT have been assigned the insecure candidate
        assert mgr._config is None, (
            "insecure production config leaked into cache — subsequent get_config() "
            "calls would bypass security validation"
        )


