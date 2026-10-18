import threading

import pytest
from fastapi.testclient import TestClient

from redstring import config, db, seed, tools, worldgen
from redstring.agents import offline
from redstring.loop import _post_for_client, _run_day, next_day
from redstring.pipeline import Pipeline


@pytest.fixture
def demo():
    tools._world_cache = None
    tools._sim_day_cache = None
    return Pipeline("offline", log=None).run_demo()


def _all_decisions():
    rows = list(tools.decisions(None, 500))
    for slug in db.client_slugs():
        rows.extend(tools.decisions(slug, 500))
    return rows


def test_lead_feed_is_deterministic_and_separate_from_businesses():
    world = worldgen.generate()
    committed = seed.load_world()
    assert world["businesses"] == committed["businesses"]
    assert world["lead_feed"] == committed["lead_feed"]
    assert [business["arrives"] for business in world["lead_feed"]] == list(range(1, 7))
    assert len(world["lead_feed"]) == 6


def test_seed_all_clears_simulation_caches():
    world = seed.load_world()
    tools._world_cache = {"stale": True}
    tools._sim_day_cache = 99

    seed.seed_all(world)

    assert tools._world_cache == world
    assert tools._sim_day_cache is None


def test_loop_uses_configured_mode(demo, monkeypatch):
    import redstring.loop as loop

    observed = {}

    class StubPipeline:
        def __init__(self, mode, log):
            observed["mode"] = mode

    monkeypatch.setattr(config, "MODE", "claude")
    monkeypatch.setattr(loop, "Pipeline", StubPipeline)
    monkeypatch.setattr(tools, "pipeline_board", lambda: [])

    _run_day({"lead_feed": []}, 3)

    assert observed["mode"] == "claude"


def test_next_day_processes_missed_feed_arrivals(demo):
    tools.set_sim_day(3)

    result = next_day()

    expected = [business["id"] for business in tools.world()["lead_feed"] if business["arrives"] <= 4]
    assert result["arrived"] == expected


def test_feed_categories_support_offline_helpers(demo, monkeypatch):
    used = {}
    monkeypatch.setattr(
        tools, "drafts",
        lambda client: [{"hook": hook} for hook in used.get(client, [])],
    )
    for lead in tools.world()["lead_feed"]:
        category = lead["category"]
        hooks = []
        used[lead["id"]] = hooks
        monkeypatch.setattr(tools, "business", lambda _client, category=category: {"category": category})
        for slot in range(1, 4):
            hook = offline._fallback_hook(lead["id"], slot, 1, category)
            assert hook in offline.SCENE[category]["hooks"]
            assert hook not in hooks
            hooks.append(hook)
        spec = offline._shot_list(lead["id"], lead["posts"][0]["technique_ids"],
                                  lead["voice"], hooks[0], slot=1)
        assert hooks[0] in spec
        references = tools.references_for(lead["posts"][0]["technique_ids"], category=category)
        assert isinstance(references, list)


def test_loop_post_slot_counts_all_non_revision_drafts(demo):
    client = "tumble-town"
    existing = [draft for draft in tools.drafts(client) if not draft.get("revision_of")]
    existing_hooks = {draft["hook"] for draft in existing}

    result = _post_for_client(Pipeline(mode="offline", log=None), client, 1)

    assert result["slot"] == len(existing) + 1
    posted = next(draft for draft in tools.drafts(client) if draft["id"] == result["draft"])
    assert posted["hook"] not in existing_hooks


def test_next_day_arrival_and_decision_day_stamps(demo):
    before = {decision["id"] for decision in _all_decisions()}

    result = next_day()

    assert result["day"] == 1
    assert result["date"] == tools.sim_date(1)
    assert "half-moon-yoga" in result["arrived"]
    business = next(b for b in tools.pipeline_board() if b["id"] == "half-moon-yoga")
    assert business["status"] == "lead"
    assert business["verdict"] is not None
    new_decisions = [decision for decision in _all_decisions() if decision["id"] not in before]
    assert new_decisions
    assert all(decision["day"] == 1 for decision in new_decisions)


def test_saved_try_lead_does_not_create_client_graph_on_next_day(demo, monkeypatch):
    import redstring.web.app as web

    monkeypatch.setattr(web, "READONLY", False)
    day = tools.sim_day()
    c = TestClient(web.app)
    lead = c.post("/api/try/lead", json={
        "name": "Try Dance Studio",
        "category": "Kids dance",
        "targets": {"A1": 1},
        "neighborhood": "n_flatiron",
    })

    assert lead.status_code == 200
    assert lead.json()["saved"] is True
    slug = lead.json()["lead"]
    assert slug.startswith("try-")

    response = c.post("/api/next-day")

    assert response.status_code == 200
    assert tools.sim_day() == day + 1
    assert f"client:{slug}" not in db.list_graphs()


def test_failed_next_day_does_not_advance_clock(demo, monkeypatch):
    from redstring import loop

    day = tools.sim_day()

    def fail_arrival(*_args, **_kwargs):
        raise RuntimeError("arrival failed")

    monkeypatch.setattr(loop, "_arrive", fail_arrival)
    with pytest.raises(RuntimeError, match="arrival failed"):
        next_day()

    assert tools.sim_day() == day


def test_six_days_respect_capacity_and_human_gates(demo):
    feed_ids = {business["id"] for business in tools.world()["lead_feed"]}
    approved_before = {
        (slug, pitch["id"])
        for slug in db.client_slugs()
        for pitch in tools.pitches(slug)
        if pitch["status"] == "approved"
    }
    arrived = set()

    for _ in range(6):
        result = next_day()
        arrived.update(result["arrived"])
        board = tools.pipeline_board()
        assert sum(b["status"] in ("pursued", "pitched") for b in board) <= config.MAX_OPEN_PURSUITS
        assert all(b["status"] != "signed" for b in board if b["id"] in feed_ids)
        assert all(
            (slug, pitch["id"]) in approved_before or pitch["status"] != "approved"
            for slug in db.client_slugs()
            for pitch in tools.pitches(slug)
        )
        assert all(
            b["status"] == "lead"
            for b in board if b.get("verdict") == "borderline"
        )

    assert arrived == feed_ids


def test_approved_loop_pitch_signs_on_the_next_tick(demo):
    approved = None
    for _ in range(8):
        next_day()
        approved = next(
            (
                (slug, pitch)
                for slug in db.client_slugs()
                for pitch in tools.pitches(slug)
                if pitch["status"] == "draft" and slug != "tumble-town"
            ),
            None,
        )
        if approved:
            break

    assert approved is not None
    slug, pitch = approved
    tools.board_decide(slug, "Pitch", pitch["id"], "approve", "Approved after review.")

    result = next_day()

    assert tools.business(slug)["status"] == "signed"
    assert {"business": slug, "stage": "signed"} in result["advanced"]
    assert any(goal["status"] == "active" for goal in tools.goals(slug))


def test_signed_client_rotation_creates_a_double_take_checked_draft(demo):
    signed = sorted(b["id"] for b in tools.pipeline_board() if b["status"] == "signed")
    expected = signed[1]
    before = {draft["id"] for draft in tools.drafts(expected)}

    result = next_day()

    assert result["posted"][0]["business"] == expected
    created = [draft for draft in tools.drafts(expected) if draft["id"] not in before]
    assert created
    assert all(draft["status"] in ("queued", "flagged") for draft in created)


def test_clock_reset_and_activity_endpoint_are_readonly_aware(demo, monkeypatch):
    import redstring.web.app as web

    tools.set_sim_day(4)
    Pipeline("offline", log=None).reset()
    assert tools.sim_day() == 0

    client = TestClient(web.app)
    monkeypatch.setattr(web, "READONLY", False)
    overview = client.get("/api/overview").json()
    assert overview["day"] == 0
    assert overview["date"] == tools.sim_date(0)
    activity = client.get("/api/activity").json()
    assert len(activity["feed_left"]) == 6
    assert all(set(lead) == {"id", "name", "category", "arrives"} for lead in activity["feed_left"])
    assert activity["can_advance"] is True

    monkeypatch.setattr(web, "READONLY", True)
    assert client.post("/api/next-day").status_code == 403
    activity = client.get("/api/activity").json()
    assert activity["can_advance"] is False
    assert tools.sim_day() == 0


def test_reset_api_returns_to_day_zero(demo):
    import redstring.web.app as web

    tools.set_sim_day(3)
    response = TestClient(web.app).post("/api/step/reset")

    assert response.status_code == 200
    assert tools.sim_day() == 0


def test_reads_during_reset_return_resetting_503(demo, monkeypatch):
    import redstring.web.app as web

    entered = threading.Event()
    release = threading.Event()
    client = TestClient(web.app)
    monkeypatch.setattr(web, "READONLY", False)
    monkeypatch.setattr(web, "run_step", lambda *_args: (entered.set(), release.wait(5)))
    web._done.clear()
    worker = threading.Thread(target=lambda: client.post("/api/step/reset"))
    worker.start()
    try:
        assert entered.wait(2)
        response = client.get("/api/overview")
        assert response.status_code == 503
        assert response.json()["detail"] == "resetting"
    finally:
        release.set()
        worker.join(timeout=5)
