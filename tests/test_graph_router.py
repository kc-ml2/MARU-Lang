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

    async def test_routes_authoring_request_to_doc(self, monkeypatch):
        # With the real registry (chat + doc), an authoring request routes to doc.
        from unittest.mock import MagicMock, AsyncMock
        from langchain_core.messages import AIMessage
        from maru_lang.graph.router import select_graph

        model = MagicMock()
        model.ainvoke = AsyncMock(return_value=AIMessage(content="doc"))
        assert await select_graph("계약서 초안 작성해줘", ["chat", "doc"], model) == "doc"

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


class TestGraphSpecHooks:
    """The per-graph payload-handling contract the chat endpoint relies on."""

    def test_chat_defaults_are_inert(self):
        from maru_lang.graph.registry import GRAPH_REGISTRY
        chat = GRAPH_REGISTRY["chat"]
        assert chat.claims({"canvas_id": "x"}) is False  # chat never claims
        assert chat.extract_inputs({"canvas_id": "x", "canvas_type": "c"}) == {}

    def test_doc_claims_only_with_canvas_id(self):
        from maru_lang.graph.registry import GRAPH_REGISTRY
        doc = GRAPH_REGISTRY["doc"]
        assert doc.claims({"content": "계약서 작성"}) is False  # initial request: L1 routes
        assert doc.claims({"canvas_id": "c1"}) is True         # edit follow-up: doc claims

    def test_doc_extracts_canvas_inputs(self):
        from maru_lang.graph.registry import GRAPH_REGISTRY
        doc = GRAPH_REGISTRY["doc"]
        assert doc.extract_inputs({"canvas_id": "c1", "canvas_type": "contract"}) == {
            "canvas_id": "c1", "canvas_type": "contract",
        }


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
        monkeypatch.setattr(reg, "DEFAULT_GRAPH_IDS", ["chat"])

        team = await Team.create(name="T1", manager=user_alice)  # empty
        await TeamMember.create(user=user_alice, team=team, role="member")
        assert await resolve_user_graph_ids(user_alice) == ["chat"]  # "report" NOT auto-granted

    async def test_explicit_intersected_with_registry(self, user_alice):
        team = await Team.create(name="T2", manager=user_alice, allowed_graphs=["chat", "ghost"])
        await TeamMember.create(user=user_alice, team=team, role="member")
        assert await resolve_user_graph_ids(user_alice) == ["chat"]  # "ghost" dropped

    async def test_opt_in_to_doc_graph(self, user_alice):
        # doc is a real registered graph; a team can opt into it explicitly.
        team = await Team.create(name="T3", manager=user_alice, allowed_graphs=["chat", "doc"])
        await TeamMember.create(user=user_alice, team=team, role="member")
        assert set(await resolve_user_graph_ids(user_alice)) == {"chat", "doc"}

    async def test_set_team_allowed_graphs_admin_then_resolve(self, user_alice):
        from maru_lang.services.team import set_team_allowed_graphs
        team = await Team.create(name="G1", manager=user_alice)
        await TeamMember.create(user=user_alice, team=team, role="admin")
        saved = await set_team_allowed_graphs(team.id, ["doc", "chat"], user_alice)
        assert saved == ["chat", "doc"]  # stored in registry order
        assert set(await resolve_user_graph_ids(user_alice)) == {"chat", "doc"}

    async def test_set_team_allowed_graphs_unknown_raises(self, user_alice):
        from maru_lang.services.team import set_team_allowed_graphs
        team = await Team.create(name="G2", manager=user_alice)
        await TeamMember.create(user=user_alice, team=team, role="admin")
        with pytest.raises(ValueError):
            await set_team_allowed_graphs(team.id, ["ghost"], user_alice)

    async def test_set_team_allowed_graphs_non_admin_forbidden(self, user_alice):
        from maru_lang.services.team import set_team_allowed_graphs
        team = await Team.create(name="G3", manager=user_alice)
        await TeamMember.create(user=user_alice, team=team, role="member")
        with pytest.raises(PermissionError):
            await set_team_allowed_graphs(team.id, ["chat"], user_alice)

    async def test_empty_reset_falls_back_to_default(self, user_alice):
        from maru_lang.services.team import set_team_allowed_graphs
        team = await Team.create(name="G4", manager=user_alice, allowed_graphs=["chat", "doc"])
        await TeamMember.create(user=user_alice, team=team, role="admin")
        assert await set_team_allowed_graphs(team.id, [], user_alice) == []  # reset
        assert await resolve_user_graph_ids(user_alice) == ["chat"]  # default set

    async def test_explicit_opt_in_to_extra_graph(self, user_alice, monkeypatch):
        import maru_lang.graph.registry as reg
        from maru_lang.graph.registry import GraphSpec
        monkeypatch.setattr(reg, "GRAPH_REGISTRY", {
            "chat": GraphSpec("chat", "default", lambda **k: None),
            "report": GraphSpec("report", "reports", lambda **k: None),
        })
        monkeypatch.setattr(reg, "DEFAULT_GRAPH_IDS", ["chat"])

        team = await Team.create(name="T2", manager=user_alice, allowed_graphs=["chat", "report"])
        await TeamMember.create(user=user_alice, team=team, role="member")
        assert await resolve_user_graph_ids(user_alice) == ["chat", "report"]
