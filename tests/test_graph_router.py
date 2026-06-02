"""Graph router (L1) tests: select_graph + team→graph access resolution."""
import pytest

from maru_lang.core.relation_db.models.auth import Team, TeamMember
from maru_lang.services.team import resolve_user_graph_ids


class TestSelectGraph:
    async def test_single_returns_without_llm(self):
        from maru_lang.graph.router import select_graph
        # "chat" is the only registered graph; no LLM call needed.
        assert await select_graph("아무거나", ["chat"], model=None) == "chat"

    async def test_empty_raises(self):
        from maru_lang.graph.router import select_graph
        with pytest.raises(ValueError):
            await select_graph("hi", [], model=None)

    async def test_filters_unregistered(self):
        from maru_lang.graph.router import select_graph
        # unknown ids are dropped; only "chat" remains → returned.
        assert await select_graph("hi", ["ghost", "chat"], model=None) == "chat"

    async def test_multi_llm_pick(self, monkeypatch):
        from unittest.mock import MagicMock, AsyncMock
        from langchain_core.messages import AIMessage
        import maru_lang.graph.router as router
        from maru_lang.graph.registry import GraphSpec

        fake = {
            "a": GraphSpec("a", "desc a", lambda **k: None),
            "b": GraphSpec("b", "desc b", lambda **k: None),
        }
        monkeypatch.setattr(router, "GRAPH_REGISTRY", fake)
        model = MagicMock()
        model.ainvoke = AsyncMock(return_value=AIMessage(content="b"))

        assert await router.select_graph("...", ["a", "b"], model) == "b"

    async def test_multi_fallback_on_unparseable(self, monkeypatch):
        from unittest.mock import MagicMock, AsyncMock
        from langchain_core.messages import AIMessage
        import maru_lang.graph.router as router
        from maru_lang.graph.registry import GraphSpec

        fake = {
            "a": GraphSpec("a", "desc a", lambda **k: None),
            "b": GraphSpec("b", "desc b", lambda **k: None),
        }
        monkeypatch.setattr(router, "GRAPH_REGISTRY", fake)
        model = MagicMock()
        model.ainvoke = AsyncMock(return_value=AIMessage(content="???"))

        assert await router.select_graph("...", ["a", "b"], model) == "a"  # fallback = first


class TestResolveUserGraphIds:
    async def test_empty_allowed_means_default_only(self, user_alice):
        team = await Team.create(name="T1", manager=user_alice)  # allowed_graphs default []
        await TeamMember.create(user=user_alice, team=team, role="member")
        # empty → default graph only (= "chat"), not "all registered"
        assert await resolve_user_graph_ids(user_alice) == ["chat"]

    async def test_empty_does_not_auto_grant_new_graphs(self, user_alice, monkeypatch):
        # With 2 graphs registered, an empty team still gets only the default.
        import maru_lang.graph.registry as reg
        from maru_lang.graph.registry import GraphSpec
        monkeypatch.setattr(reg, "GRAPH_REGISTRY", {
            "chat": GraphSpec("chat", "default", lambda **k: None),
            "report": GraphSpec("report", "reports", lambda **k: None),
        })
        monkeypatch.setattr(reg, "DEFAULT_GRAPH_ID", "chat")

        team = await Team.create(name="T1", manager=user_alice)  # empty
        await TeamMember.create(user=user_alice, team=team, role="member")
        assert await resolve_user_graph_ids(user_alice) == ["chat"]  # "report" NOT auto-granted

    async def test_explicit_intersected_with_registry(self, user_alice):
        team = await Team.create(name="T2", manager=user_alice, allowed_graphs=["chat", "ghost"])
        await TeamMember.create(user=user_alice, team=team, role="member")
        assert await resolve_user_graph_ids(user_alice) == ["chat"]  # "ghost" dropped

    async def test_explicit_opt_in_to_extra_graph(self, user_alice, monkeypatch):
        import maru_lang.graph.registry as reg
        from maru_lang.graph.registry import GraphSpec
        monkeypatch.setattr(reg, "GRAPH_REGISTRY", {
            "chat": GraphSpec("chat", "default", lambda **k: None),
            "report": GraphSpec("report", "reports", lambda **k: None),
        })
        monkeypatch.setattr(reg, "DEFAULT_GRAPH_ID", "chat")

        team = await Team.create(name="T2", manager=user_alice, allowed_graphs=["chat", "report"])
        await TeamMember.create(user=user_alice, team=team, role="member")
        assert await resolve_user_graph_ids(user_alice) == ["chat", "report"]
