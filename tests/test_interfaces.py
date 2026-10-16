import asyncio
import inspect
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from redstring import registry, seed, tools


def test_every_spec_query_is_a_named_tool():
    assert {t.query for t in registry.TOOLS if t.query} == {"P1", "Q0", "Q1", "Q2", "Q3", "Q4", "Q5"}


def test_tool_properties_match_function_parameters():
    for tool in registry.TOOLS:
        assert set(tool.properties) <= set(inspect.signature(tool.fn).parameters), tool.name


def test_audiences_of_tool_accepts_client_argument():
    tools._world_cache = None
    seed.seed_all()
    tool = next(t for t in registry.TOOLS if t.name == "audiences_of")
    assert tool.call({"client": "wet-paint"})


def test_mcp_server_lists_and_calls_tools():
    from redstring.mcp_server import server
    tools._world_cache = None
    seed.seed_all()

    async def go():
        listed = await server.list_tools()
        out = await server.call_tool("lead_conflict", {"lead": "byte-builders"})
        return listed, out

    listed, out = asyncio.run(go())
    assert len(listed) == len(registry.TOOLS)
    assert '"verdict": "pursue_differentiated"' in str(out)


def test_web_try_inputs():
    from redstring.web.app import app
    tools._world_cache = None
    seed.seed_all()
    c = TestClient(app)
    overview = c.get("/api/overview")
    assert overview.status_code == 200
    assert any(a["id"] == "A7" for a in overview.json()["audiences"])
    assert {n["id"] for n in overview.json()["neighborhoods"]} == {
        "n_flatiron", "n_nomad", "n_gramercy", "n_chelsea"
    }
    r = c.post("/api/try/lead", json={"name": "Sprout Dance", "category": "Kids dance", "targets": {"A1": 1},
                                     "neighborhood": "n_flatiron"}).json()
    assert r["verdict"] == "pursue_differentiated"
    r = c.post("/api/try/lead", json={"name": "Adult Culture Club", "category": "Community events",
                                     "targets": {"A6": 1}, "neighborhood": "n_flatiron"}).json()
    assert r["verdict"] == "pursue"
    r = c.post("/api/try/lead", json={"name": "Swim Prospect", "category": "Swim lessons",
                                     "targets": {"A1": 0.6}, "neighborhood": "n_gramercy"}).json()
    assert r["verdict"] == "decline"
    assert c.post("/api/try/lead", json={"name": "Unknown Place", "category": "Kids dance",
                                        "targets": {"A1": 1}, "neighborhood": "n_unknown"}).status_code == 400
    planted = tools.world()["planted"]["collision_techniques"]
    r = c.post("/api/try/draft", json={"client": "cannonball", "technique_ids": planted}).json()
    assert r["flagged"]
    assert c.post("/api/try/lead", json={"name": "xx", "category": "yy", "targets": {}}).status_code == 400


def test_step_api_enforces_order():
    import redstring.web.app as web
    web._done.clear()
    web._log.clear()
    c = TestClient(web.app)

    assert c.post("/api/step/reset").status_code == 200
    r = c.post("/api/step/retire_goal")
    assert r.status_code == 409
    assert "client_month" in r.json()["detail"]
    assert c.post("/api/step/screen").status_code == 200


class FakeMessages:
    """Scripted model: calls lead_conflict, then record_screening, then finishes."""

    def __init__(self):
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        n = len(self.calls)
        if n == 1:
            return SimpleNamespace(stop_reason="tool_use", content=[
                SimpleNamespace(type="tool_use", id="t1", name="lead_conflict", input={"lead": "crux"})])
        if n == 2:
            res = json.loads(kw["messages"][-1]["content"][0]["content"])
            return SimpleNamespace(stop_reason="tool_use", content=[
                SimpleNamespace(type="tool_use", id="t2", name="record_screening",
                                input={"lead": "crux", "verdict": res["verdict"], "reason": res["reason"]})])
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="Screened crux.")])


def test_claude_agent_loop_uses_only_its_tools(monkeypatch):
    from redstring.agents import claude
    tools._world_cache = None
    seed.seed_all()
    fake = FakeMessages()
    monkeypatch.setattr(claude, "_client", SimpleNamespace(beta=SimpleNamespace(messages=fake)))
    out = claude.run_agent("scout", "Screen crux.", log=None)
    assert out == "Screened crux."
    names = {t["name"] for t in fake.calls[0]["tools"]}
    assert names == {t.name for t in registry.for_agent("scout")}
    assert fake.calls[0]["model"] == "claude-opus-5-5"
    assert tools.screening_card("crux")["verdict"] == "pursue"
