import asyncio
import inspect
import json
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from redstring import db, queries, registry, seed, tools


def test_every_spec_query_is_a_named_tool():
    assert {t.query for t in registry.TOOLS if t.query} == {"P1", "Q0", "Q1", "Q2", "Q3", "Q4", "Q5"}


def test_tool_properties_match_function_parameters():
    for tool in registry.TOOLS:
        assert set(tool.properties) <= set(inspect.signature(tool.fn).parameters), tool.name


def test_audiences_of_tool_accepts_client_argument():
    tools._world_cache = None
    seed.seed_all()
    audiences = next(t for t in registry.TOOLS if t.name == "audiences_of")
    signatures = next(t for t in registry.TOOLS if t.name == "signatures")
    assert audiences.call({"client": "wet-paint"}, caller="style_director", scope="cannonball")
    assert signatures.call({"slug": "wet-paint"}, caller="style_director", scope="cannonball")


def test_private_client_reads_remain_pinned_to_run_scope():
    tools._world_cache = None
    seed.seed_all()
    findings = next(t for t in registry.TOOLS if t.name == "findings")

    with pytest.raises(ValueError, match="client is pinned to cannonball"):
        findings.call({"client": "wet-paint"}, caller="style_director", scope="cannonball")


def test_mcp_pursue_schema_hides_server_identity_and_source():
    from redstring.mcp_server import build_server

    async def go():
        return await build_server(allow_writes=True).list_tools()

    pursue = next(tool for tool in asyncio.run(go()) if tool.name == "pursue")
    assert not {"agent", "by", "source"} & set(pursue.input_schema["properties"])


def test_scout_cannot_set_web_board_source(monkeypatch):
    tools._world_cache = None
    seed.seed_all()
    captured = {}
    monkeypatch.setattr(db, "list_graphs", lambda: [])
    monkeypatch.setattr(seed, "create_client_graph", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        tools,
        "set_status",
        lambda slug, status, agent, rationale, source=None: captured.update(
            slug=slug, status=status, agent=agent, source=source
        ),
    )

    registry.BY_NAME["pursue"].call(
        {"slug": "crux", "rationale": "Pursue.", "source": "web_board"},
        caller="scout",
        allowed_slugs={"crux"},
        allowed_pursuits={"crux"},
    )

    assert captured == {"slug": "crux", "status": "pursued", "agent": "scout", "source": None}


def test_mcp_server_lists_and_calls_tools():
    from redstring.mcp_server import server
    tools._world_cache = None
    seed.seed_all()

    async def go():
        listed = await server.list_tools()
        out = await server.call_tool("lead_conflict", {"lead": "byte-builders"})
        return listed, out

    listed, out = asyncio.run(go())
    assert len(listed) == len([tool for tool in registry.TOOLS if not tool.writable])
    assert '"verdict": "decline"' in str(out)


def test_mcp_writes_are_opt_in_and_identity_is_server_set():
    from redstring.mcp_server import build_server, server
    tools._world_cache = None
    seed.seed_all()

    async def go():
        read_only = {tool.name for tool in await server.list_tools()}
        writable_server = build_server(allow_writes=True)
        all_tools = {tool.name for tool in await writable_server.list_tools()}
        result = await writable_server.call_tool("record_finding", {
            "client": "wet-paint",
            "kind": "audience",
            "text": "Audience note.",
            "source_url": "https://example.test/audience",
            "rationale": "Recorded from MCP.",
            "agent": "board",
        })
        return read_only, all_tools, result

    read_only, all_tools, _ = asyncio.run(go())
    assert "record_finding" not in read_only
    assert "record_finding" in all_tools
    rows = db.rows(db.client("wet-paint"), """MATCH (d:Decision)-[:DECIDED_BY]->(a:Agent)
                                             RETURN a.id AS agent ORDER BY d.at DESC LIMIT 1""")
    assert rows[0]["agent"] == "mcp"


def test_claude_rejects_tool_outside_agent_slice(monkeypatch):
    from redstring.agents import claude

    class Messages:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return SimpleNamespace(stop_reason="tool_use", content=[
                    SimpleNamespace(type="tool_use", id="t1", name="record_finding", input={
                        "client": "crux", "kind": "audience", "text": "Nope.",
                        "source_url": "https://example.test/nope",
                    })])
            if len(self.calls) == 2:
                result = self.calls[-1]["messages"][-1]["content"][0]
                assert result["is_error"] is True
                assert "not your tool" in result["content"]
                return SimpleNamespace(stop_reason="end_turn", content=[
                    SimpleNamespace(type="text", text="Rejected.")])
            raise AssertionError("unexpected extra model call")

    tools._world_cache = None
    seed.seed_all()
    fake = Messages()
    monkeypatch.setattr(claude, "_client", SimpleNamespace(beta=SimpleNamespace(messages=fake)))
    assert claude.run_agent("scout", "Screen crux.", log=None) == "Rejected."


def test_single_client_run_rejects_mismatched_client_before_recording(monkeypatch):
    from redstring.agents import claude

    class Messages:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return SimpleNamespace(stop_reason="tool_use", content=[
                    SimpleNamespace(type="server_tool_use", name="web_search"),
                    SimpleNamespace(type="web_search_tool_result", content=[
                        SimpleNamespace(url="https://example.test/wrong"),
                    ]),
                    SimpleNamespace(type="tool_use", id="t1", name="record_finding", input={
                        "client": "wet-paint", "kind": "audience", "text": "Wrong client.",
                        "source_url": "https://example.test/wrong",
                    })])
            result = self.calls[-1]["messages"][-1]["content"][0]
            assert result["is_error"] is True
            assert "client is pinned to crux" in result["content"]
            return SimpleNamespace(stop_reason="end_turn", content=[
                SimpleNamespace(type="text", text="Rejected.")])

    tools._world_cache = None
    seed.seed_all()
    before = len(tools.findings("wet-paint"))
    fake = Messages()
    monkeypatch.setattr(claude, "_client", SimpleNamespace(beta=SimpleNamespace(messages=fake)))
    assert claude.run_agent("researcher", "Research crux.", log=None, slug="crux") == "Rejected."
    assert len(tools.findings("wet-paint")) == before


def test_single_client_run_rejects_mismatched_private_client(monkeypatch):
    from redstring.agents import claude

    class Messages:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return SimpleNamespace(stop_reason="tool_use", content=[
                    SimpleNamespace(type="tool_use", id="t1", name="findings", input={
                        "client": "wet-paint",
                    })])
            result = self.calls[-1]["messages"][-1]["content"][0]
            assert result["is_error"] is True
            assert "client is pinned to crux" in result["content"]
            return SimpleNamespace(stop_reason="end_turn", content=[
                SimpleNamespace(type="text", text="Rejected.")])

    tools._world_cache = None
    seed.seed_all()
    fake = Messages()
    monkeypatch.setattr(claude, "_client", SimpleNamespace(beta=SimpleNamespace(messages=fake)))
    assert claude.run_agent("style_director", "Read signatures for crux.", log=None, slug="crux") == "Rejected."


def test_scout_rejects_lead_and_pursuit_outside_allowed_set(monkeypatch):
    from redstring.agents import claude

    class Messages:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return SimpleNamespace(stop_reason="tool_use", content=[
                    SimpleNamespace(type="tool_use", id="t1", name="record_screening", input={
                        "lead": "page-turn", "verdict": "pursue", "reason": "Wrong lead",
                    })])
            if len(self.calls) == 2:
                result = self.calls[-1]["messages"][-1]["content"][0]
                assert result["is_error"] is True
                assert "allowed leads" in result["content"]
                return SimpleNamespace(stop_reason="tool_use", content=[
                    SimpleNamespace(type="tool_use", id="t2", name="pursue", input={
                        "slug": "page-turn", "rationale": "Wrong pursuit",
                    })])
            result = self.calls[-1]["messages"][-1]["content"][0]
            assert result["is_error"] is True
            assert "allowed leads" in result["content"]
            return SimpleNamespace(stop_reason="end_turn", content=[
                SimpleNamespace(type="text", text="Rejected.")])

    tools._world_cache = None
    seed.seed_all()
    fake = Messages()
    monkeypatch.setattr(claude, "_client", SimpleNamespace(beta=SimpleNamespace(messages=fake)))
    assert claude.run_agent("scout", "Screen crux.", log=None, allowed_leads={"crux"}) == "Rejected."
    assert tools.screening_card("page-turn") == {}


def test_scout_can_screen_any_lead_but_only_pursue_explicit_targets(monkeypatch):
    from redstring.agents import claude

    class Messages:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return SimpleNamespace(stop_reason="tool_use", content=[
                    SimpleNamespace(type="tool_use", id="screen", name="record_screening", input={
                        "lead": "page-turn", "verdict": "pursue", "reason": "Good fit.",
                    })])
            if len(self.calls) == 2:
                result = self.calls[-1]["messages"][-1]["content"][0]
                assert result.get("is_error") is not True
                return SimpleNamespace(stop_reason="tool_use", content=[
                    SimpleNamespace(type="tool_use", id="pursue", name="pursue", input={
                        "slug": "page-turn", "rationale": "Good fit.",
                    })])
            result = self.calls[-1]["messages"][-1]["content"][0]
            assert result["is_error"] is True
            assert "allowed pursuits" in result["content"]
            return SimpleNamespace(stop_reason="end_turn", content=[
                SimpleNamespace(type="text", text="Rejected.")])

    tools._world_cache = None
    seed.seed_all()
    fake = Messages()
    monkeypatch.setattr(claude, "_client", SimpleNamespace(beta=SimpleNamespace(messages=fake)))

    assert claude.run_agent(
        "scout",
        "Screen page-turn; pursue crux only.",
        log=None,
        allowed_leads={"crux", "page-turn"},
        allowed_pursuits={"crux"},
    ) == "Rejected."
    assert tools.screening_card("page-turn")["verdict"] == "pursue"
    assert "client:page-turn" not in db.list_graphs()


def test_invalid_business_slug_is_rejected_before_graph_operations():
    tools._world_cache = None
    world = seed.load_world()
    seed.seed_all(world)
    before = set(db.list_graphs())
    with pytest.raises(ValueError, match="invalid business slug"):
        seed.create_client_graph(world, "Not A Slug", include_posts=False)
    assert set(db.list_graphs()) == before


def test_board_rules_are_web_decisions_in_quoted_user_data(monkeypatch):
    from redstring.agents import claude

    tools._world_cache = None
    seed.seed_all()
    tools.board_decide("wet-paint", "Draft", "internal", "approve", "Internal decision.")
    tools.board_decide("wet-paint", "Draft", "web", "approve", "Web board decision.", source="web_board")

    class Messages:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(stop_reason="end_turn", content=[
                SimpleNamespace(type="text", text="Done.")])

    fake = Messages()
    monkeypatch.setattr(claude, "_client", SimpleNamespace(beta=SimpleNamespace(messages=fake)))
    assert claude.run_agent("researcher", "Research wet-paint.", log=None, slug="wet-paint") == "Done."
    request = fake.calls[0]
    assert "Web board decision." in request["messages"][0]["content"]
    assert "Internal decision." not in request["messages"][0]["content"]
    assert "Web board decision." not in request["system"]


def test_full_demo_marks_board_actions_as_web_board_decisions():
    from redstring.pipeline import Pipeline

    tools._world_cache = None
    seed.seed_all()
    Pipeline("offline", log=None).run_demo()

    assert tools.board_rules("tumble-town")
    assert tools.board_rules("pixel-pond")


def test_web_try_inputs(monkeypatch):
    import redstring.web.app as web
    monkeypatch.setattr(web, "READONLY", False)
    tools._world_cache = None
    seed.seed_all()
    c = TestClient(web.app)
    overview = c.get("/api/overview")
    assert overview.status_code == 200
    assert any(a["id"] == "A7" for a in overview.json()["audiences"])
    assert {n["id"] for n in overview.json()["neighborhoods"]} == {
        "n_flatiron", "n_nomad", "n_gramercy", "n_chelsea"
    }
    r = c.post("/api/try/lead", json={"name": "Sprout Dance", "category": "Kids dance", "targets": {"A1": 1},
                                     "neighborhood": "n_flatiron"}).json()
    assert r["verdict"] == "pursue_differentiated"
    assert r["saved"] is True
    r = c.post("/api/try/lead", json={"name": "Adult Culture Club", "category": "Community events",
                                     "targets": {"A6": 1}, "neighborhood": "n_flatiron"}).json()
    assert r["verdict"] == "pursue"
    r = c.post("/api/try/lead", json={"name": "Swim Prospect", "category": "Swim lessons",
                                     "targets": {"A1": 0.6}, "neighborhood": "n_gramercy"}).json()
    assert r["verdict"] == "decline"
    before_preview = db.rows(db.agency(), "MATCH (b:Business) RETURN count(b) AS count")[0]["count"]
    preview = c.post("/api/try/lead", json={"name": "Preview Client", "category": "Cafe",
                                           "targets": {"A6": 0.5}, "neighborhood": "n_nomad", "preview": True}).json()
    assert preview["saved"] is False
    assert db.rows(db.agency(), "MATCH (b:Business) RETURN count(b) AS count")[0]["count"] == before_preview
    assert c.post("/api/try/lead", json={"name": "Unknown Place", "category": "Kids dance",
                                        "targets": {"A1": 1}, "neighborhood": "n_unknown"}).status_code == 422
    planted = tools.world()["planted"]["collision_techniques"]
    r = c.post("/api/try/draft", json={"client": "cannonball", "technique_ids": planted}).json()
    assert r["flagged"]
    assert c.post("/api/try/lead", json={"name": "xx", "category": "yy", "targets": {}}).status_code == 422


def test_web_try_lead_readonly_saves_nothing(monkeypatch):
    import redstring.web.app as web
    tools._world_cache = None
    seed.seed_all()
    monkeypatch.setattr(web, "READONLY", True)
    c = TestClient(web.app)

    def counts():
        g = db.agency()
        return (
            db.rows(g, "MATCH (b:Business) RETURN count(b) AS count")[0]["count"],
            db.rows(g, "MATCH (d:Decision) RETURN count(d) AS count")[0]["count"],
            db.rows(g, "MATCH ()-[s:SCREENED]->() RETURN count(s) AS count")[0]["count"],
        )

    before = counts()
    original_rows = db.rows
    observed_business_counts = []

    def observe_rows(graph, query, params=None):
        if query in (queries.Q1_LEAD_CONFLICT, queries.Q1_LEAD_CONFLICT_PREVIEW):
            observed_business_counts.append(
                original_rows(db.agency(), "MATCH (b:Business) RETURN count(b) AS count")[0]["count"]
            )
        return original_rows(graph, query, params)

    monkeypatch.setattr(db, "rows", observe_rows)
    r = c.post("/api/try/lead", json={"name": "Sprout Dance", "category": "Kids dance", "targets": {"A1": 1},
                                     "neighborhood": "n_flatiron"}).json()
    assert r["verdict"] == "pursue_differentiated"
    assert r["saved"] is False
    r = c.post("/api/try/lead", json={"name": "Swim Prospect", "category": "Swim lessons",
                                     "targets": {"A1": 0.6}, "neighborhood": "n_gramercy"}).json()
    assert r["verdict"] == "decline"
    assert r["saved"] is False
    assert observed_business_counts == [before[0], before[0]]
    assert counts() == before


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


def test_completed_step_cannot_be_rerun(monkeypatch):
    import redstring.web.app as web
    monkeypatch.setattr(web, "READONLY", False)
    web._done.clear()
    web._log.clear()
    c = TestClient(web.app)

    try:
        for step, _ in web.STEPS:
            assert c.post(f"/api/step/{step}").status_code == 200
        assert tools.business("tumble-town")["status"] == "signed"

        response = c.post("/api/step/pitch")

        assert response.status_code == 409
        assert response.json()["detail"] == "already ran; reset first"
        assert tools.business("tumble-town")["status"] == "signed"
    finally:
        web._done.clear()
        web._log.clear()


def test_step_returns_immediately_when_agents_are_busy(monkeypatch):
    import redstring.web.app as web

    monkeypatch.setattr(web, "READONLY", False)
    monkeypatch.setattr(web, "run_step", lambda *_args: None)
    monkeypatch.setattr(web.loop, "next_day", lambda **_kwargs: None)
    client = TestClient(web.app)

    for path in ("/api/step/reset", "/api/next-day"):
        held = threading.Event()
        release = threading.Event()

        def hold_writer_lock():
            with web._lock:
                held.set()
                release.wait(timeout=0.75)

        holder = threading.Thread(target=hold_writer_lock)
        holder.start()
        assert held.wait(timeout=1)
        started = time.monotonic()
        try:
            response = client.post(path)
        finally:
            release.set()
            holder.join(timeout=1)

        assert response.status_code == 409
        assert response.json()["detail"] == "agents are busy"
        assert time.monotonic() - started < 0.5


def test_overview_groups_cleared_to_pitch_leads(monkeypatch):
    import redstring.web.app as web
    monkeypatch.setattr(web, "READONLY", False)
    tools._world_cache = None
    web._done.clear()
    web._log.clear()
    c = TestClient(web.app)

    assert c.post("/api/step/reset").status_code == 200
    assert c.post("/api/step/screen").status_code == 200
    overview = c.get("/api/overview").json()

    ready = [item for item in overview["needs_you"] if item["type"] == "ready"]
    assert len(ready) == 1
    priority = {"pursue": 0, "pursue_differentiated": 1}
    expected = sorted(
        (
            business for business in overview["businesses"]
            if business["status"] == "lead" and business["verdict"] in priority
        ),
        key=lambda business: (priority[business["verdict"]], business["name"]),
    )
    assert ready[0]["business_ids"] == [business["id"] for business in expected]
    assert ready[0]["business_id"] == expected[0]["id"]
    assert ready[0]["message"] == (
        f"{len(expected)} screened "
        f"{'lead is' if len(expected) == 1 else 'leads are'} cleared to pitch"
    )


def test_borderline_lead_can_be_pursued(monkeypatch):
    import redstring.web.app as web
    monkeypatch.setattr(web, "READONLY", False)
    tools._world_cache = None
    seed.seed_all()
    from redstring.pipeline import Pipeline
    Pipeline("offline", log=None).screen()

    response = TestClient(web.app).post(
        "/api/lead/page-turn/decide",
        json={"verdict": "pursue", "note": "Start research."},
    )

    assert response.status_code == 200
    assert tools.business("page-turn")["status"] == "pursued"
    assert "client:page-turn" in db.list_graphs()


def test_borderline_lead_can_be_passed(monkeypatch):
    import redstring.web.app as web
    monkeypatch.setattr(web, "READONLY", False)
    tools._world_cache = None
    seed.seed_all()
    from redstring.pipeline import Pipeline
    Pipeline("offline", log=None).screen()

    response = TestClient(web.app).post(
        "/api/lead/page-turn/decide",
        json={"verdict": "pass", "note": "Not now."},
    )

    assert response.status_code == 200
    assert tools.business("page-turn")["status"] == "passed"


def test_borderline_lead_decision_is_readonly_guarded(monkeypatch):
    import redstring.web.app as web
    tools._world_cache = None
    seed.seed_all()
    from redstring.pipeline import Pipeline
    Pipeline("offline", log=None).screen()
    monkeypatch.setattr(web, "READONLY", True)

    response = TestClient(web.app).post(
        "/api/lead/page-turn/decide",
        json={"verdict": "pursue"},
    )

    assert response.status_code == 403
    assert tools.business("page-turn")["status"] == "lead"


def test_nonborderline_lead_cannot_be_decided(monkeypatch):
    import redstring.web.app as web
    monkeypatch.setattr(web, "READONLY", False)
    tools._world_cache = None
    seed.seed_all()
    from redstring.pipeline import Pipeline
    Pipeline("offline", log=None).screen()

    response = TestClient(web.app).post(
        "/api/lead/crux/decide",
        json={"verdict": "pursue"},
    )

    assert response.status_code == 400


def test_analysis_views_are_readonly(monkeypatch):
    import redstring.web.app as web
    tools._world_cache = None
    seed.seed_all()
    monkeypatch.setattr(web, "READONLY", True)
    c = TestClient(web.app)

    agency = db.agency()
    before = db.rows(agency, "MATCH (b:Business) RETURN count(b) AS count")[0]["count"]
    response = c.get("/api/analysis")
    assert response.status_code == 200
    result = response.json()
    assert {
        "graphs", "screening", "double_take", "cleared_checks", "signatures",
        "queries", "agents", "thresholds",
    } <= result.keys()
    assert any(graph["name"] == "agency" for graph in result["graphs"])
    assert {"P1", "Q0", "Q1", "Q2"} <= {query["query"] for query in result["queries"]}
    assert db.rows(agency, "MATCH (b:Business) RETURN count(b) AS count")[0]["count"] == before

    page = c.get("/analysis")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]


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


@pytest.mark.parametrize("stop_reason", ["refusal", "model_context_window_exceeded"])
def test_claude_refusal_and_context_limit_record_declined(stop_reason, monkeypatch):
    from redstring.agents import claude

    class DecliningMessages:
        def create(self, **_kwargs):
            return SimpleNamespace(stop_reason=stop_reason, stop_details="model stopped", content=[])

    recorded = []
    monkeypatch.setattr(claude, "_client", SimpleNamespace(beta=SimpleNamespace(messages=DecliningMessages())))
    monkeypatch.setattr(tools, "record_declined", lambda *args, **kwargs: recorded.append((args, kwargs)))

    result = claude.run_agent("researcher", "Research.", log=None, slug="crux")

    assert result.startswith("Declined:")
    assert recorded == [(("researcher", "model stopped"), {"slug": "crux"})]


def test_claude_max_tokens_fails_loudly(monkeypatch):
    from redstring.agents import claude

    class TruncatedMessages:
        def create(self, **_kwargs):
            return SimpleNamespace(stop_reason="max_tokens", content=[])

    monkeypatch.setattr(claude, "_client", SimpleNamespace(beta=SimpleNamespace(messages=TruncatedMessages())))

    with pytest.raises(RuntimeError, match="reached max_tokens"):
        claude.run_agent("researcher", "Research.", log=None)


def test_claude_limits_searches_and_validates_finding_urls(monkeypatch):
    from redstring.agents import claude

    class SearchMessages:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
            index = len(self.calls)
            if index == 3:
                return SimpleNamespace(stop_reason="end_turn", content=[
                    SimpleNamespace(type="text", text="Finished."),
                ])
            url = f"https://source.test/{index}"
            source_url = url if index == 1 else "https://unseen.test/"
            return SimpleNamespace(stop_reason="tool_use", content=[
                SimpleNamespace(type="server_tool_use", name="web_search"),
                SimpleNamespace(type="web_search_tool_result", content=[SimpleNamespace(url=url)]),
                SimpleNamespace(type="tool_use", id=f"finding-{index}", name="record_finding", input={
                    "client": "crux", "kind": "audience", "text": "Finding",
                    "source_url": source_url, "rationale": "Source",
                }),
            ])

    messages = SearchMessages()
    registered_calls = []
    search_urls = set()
    monkeypatch.setattr(claude, "_client", SimpleNamespace(beta=SimpleNamespace(messages=messages)))
    monkeypatch.setattr(registry, "call", lambda name, args, **kwargs: (
        registered_calls.append((name, args)) or json.dumps({"ok": True})
    ))

    claude.run_agent("researcher", "Research.", log=None, slug="crux", on_search_urls=search_urls.update)

    web_search_uses = [
        next(tool["max_uses"] for tool in call["tools"] if tool.get("name") == "web_search")
        for call in messages.calls
    ]
    assert web_search_uses == [8, 7, 6]
    assert registered_calls == [("record_finding", {
        "client": "crux", "kind": "audience", "text": "Finding",
        "source_url": "https://source.test/1", "rationale": "Source",
    })]
    assert search_urls == {"https://source.test/1", "https://source.test/2"}
    assert messages.calls[2]["messages"][-1]["content"][0]["is_error"] is True
    assert all(tool.get("strict") is True for tool in messages.calls[0]["tools"] if tool.get("name") != "web_search")


def test_claude_tool_output_truncation_is_marked(monkeypatch):
    from redstring.agents import claude

    class ToolMessages:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
            if len(self.calls) == 1:
                return SimpleNamespace(stop_reason="tool_use", content=[
                    SimpleNamespace(type="tool_use", id="board", name="pipeline_board", input={}),
                ])
            return SimpleNamespace(stop_reason="end_turn", content=[
                SimpleNamespace(type="text", text="Done."),
            ])

    messages = ToolMessages()
    monkeypatch.setattr(claude, "_client", SimpleNamespace(beta=SimpleNamespace(messages=messages)))
    monkeypatch.setattr(registry, "call", lambda *_args, **_kwargs: json.dumps("x" * 21000))

    claude.run_agent("scout", "Check the board.", log=None)

    result = messages.calls[1]["messages"][-1]["content"][0]["content"]
    assert "[truncated at 20000 characters]" in result


def test_pipeline_uses_draft_id_returned_by_write_tool(monkeypatch):
    from redstring.pipeline import Pipeline

    pipeline = Pipeline("claude", log=None)
    monkeypatch.setattr(
        pipeline.claude,
        "run_agent",
        lambda _agent, _task, tool_results=None, **_kwargs: (
            tool_results.update({"write_draft": {"draft": "new-draft"}}) if tool_results is not None else None
        ),
    )
    monkeypatch.setattr(tools, "drafts", lambda _client: [
        {"id": "new-draft", "status": "queued"},
        {"id": "older-later-draft", "status": "flagged"},
    ])
    monkeypatch.setattr(tools, "collision_flags", lambda *_args: [])

    result = pipeline.produce_and_check("wet-paint", "plan", 1, ["tr_whip_pan"], "spec")

    assert result[0]["draft"] == "new-draft"
    assert result[0]["status"] == "queued"


def test_claude_auditor_request_includes_loaded_top_post_ids(monkeypatch, tmp_path):
    from redstring import config
    from redstring.agents import claude
    from redstring.pipeline import Pipeline

    tools._world_cache = None
    world = tools.world()
    seed.seed_all(world)
    seed.create_client_graph(world, "crux", include_posts=False)
    monkeypatch.setattr(config, "RESEARCH_CACHE", tmp_path)

    class MessageRecorder:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text="Reviewed the supplied posts.")],
            )

    recorder = MessageRecorder()
    monkeypatch.setattr(claude, "_client", SimpleNamespace(beta=SimpleNamespace(messages=recorder)))
    pipeline = Pipeline("claude", log=None)
    run_agent = pipeline.claude.run_agent

    def offline_researcher_for_test(agent, task, offline_fn, *args, **kwargs):
        if agent == "researcher":
            kwargs.pop("tool_results", None)
            kwargs.pop("on_search_urls", None)
            return offline_fn(*args, **kwargs)
        return run_agent(agent, task, log=None)

    monkeypatch.setattr(pipeline, "_agent", offline_researcher_for_test)
    pipeline.research("crux")

    posts = sorted(tools.posts("crux"), key=lambda post: post["views"], reverse=True)
    assert posts
    first_request = recorder.calls[0]
    prompt = first_request["messages"][0]["content"]
    assert all(post["id"] in prompt for post in posts[:3])
    assert "post IDs in descending view order" in prompt
    assert any(tool["name"] == "posts" for tool in first_request["tools"])


def test_overview_exposes_walkthrough_video(monkeypatch):
    import redstring.web.app as web
    tools._world_cache = None
    seed.seed_all()
    c = TestClient(web.app)
    monkeypatch.setattr(web, "VIDEO_URL", "")
    assert c.get("/api/overview").json()["video_url"] == ""
    monkeypatch.setattr(web, "VIDEO_URL", "https://youtu.be/abc123XYZ")
    assert c.get("/api/overview").json()["video_url"] == "https://youtu.be/abc123XYZ"
