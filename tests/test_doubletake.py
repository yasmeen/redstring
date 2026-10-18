import pytest
from fastapi.testclient import TestClient

from redstring import queries, tools
from redstring.pipeline import Pipeline
import redstring.web.app as web


@pytest.fixture
def seeded_demo():
    tools._world_cache = None
    return Pipeline("offline", log=None).run_demo()


def _tumble_blocked_draft():
    return next(
        draft for draft in tools.drafts("tumble-town")
        if draft["status"] == "flagged" and draft["version"] == 1
    )


def test_doubletake_detail_matches_analysis_and_uses_client_evidence(seeded_demo):
    client = TestClient(web.app)
    draft = _tumble_blocked_draft()

    response = client.get(f"/api/doubletake/tumble-town/{draft['id']}")
    assert response.status_code == 200
    detail = response.json()
    analysis = client.get("/api/analysis").json()
    expected_flags = {
        flag["with_business_id"]: flag
        for flag in analysis["double_take"]
        if flag["client_id"] == "tumble-town" and flag["draft"] == draft["id"]
    }

    assert detail["query"]["cypher"] == queries.Q2_DOUBLE_TAKE
    assert detail["revision"] and detail["revision"]["status"] == "cleared"
    assert detail["revision"]["cleared"] is True
    for flag in detail["flags"]:
        expected = expected_flags[flag["business"]["id"]]
        assert {item["id"] for item in flag["shared"]} == set(expected["shared_ids"])
        assert flag["risk"] == expected["risk"]
        owned_posts = {post["id"] for post in tools.posts(flag["business"]["id"])}
        world_business = next(
            business for business in tools.world()["businesses"]
            if business["id"] == flag["business"]["id"]
        )
        owned_posts.update(post["id"] for post in world_business.get("posts", []))
        owned_drafts = {item["id"] for item in tools.drafts(flag["business"]["id"])}
        assert flag["evidence"]
        assert all(item["post_id"] in owned_posts | owned_drafts for item in flag["evidence"])
        assert all(item["hook"] for item in flag["evidence"])


def test_doubletake_detail_works_readonly_and_returns_404_for_unknown_records(seeded_demo, monkeypatch):
    client = TestClient(web.app)
    draft = _tumble_blocked_draft()
    monkeypatch.setattr(web, "READONLY", True)

    assert client.get(f"/api/doubletake/tumble-town/{draft['id']}").status_code == 200
    assert client.get("/api/doubletake/unknown-client/draft-unknown").status_code == 404
    assert client.get("/api/doubletake/tumble-town/draft-unknown").status_code == 404
