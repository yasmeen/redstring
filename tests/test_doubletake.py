import pytest
from fastapi.testclient import TestClient

from redstring import config, db, queries, tools
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
    assert detail["reference_total"] == db.rows(db.agency(), "MATCH (r:Reference) RETURN count(DISTINCT r) AS count")[0]["count"]
    assert detail["revision"] and detail["revision"]["status"] == "cleared"
    assert detail["revision"]["cleared"] is True
    for flag in detail["flags"]:
        expected = expected_flags[flag["business"]["id"]]
        assert {item["id"] for item in flag["shared"]} == set(expected["shared_ids"])
        assert flag["risk"] == expected["risk"]
        audience_ids = [item["id"] for item in flag["audiences"]]
        assert len(audience_ids) == len(set(audience_ids))
        raw_audiences = tools.audience_paths("tumble-town", flag["business"]["id"])
        for audience in flag["audiences"]:
            matching = [item for item in raw_audiences if item["id"] == audience["id"]]
            assert audience["mine"] == max(item["mine"] for item in matching)
            assert audience["theirs"] == max(item["theirs"] for item in matching)
            assert {tuple(path) for path in audience["paths"]} == {
                tuple(item["path"]) for item in matching
            }
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


def test_try_draft_preview_matches_saved_q2_for_planted_drafts(seeded_demo):
    client = TestClient(web.app)
    for slug in ("cannonball", "treble-clef", "tumble-town"):
        draft = next(item for item in tools.drafts(slug) if item["status"] == "flagged" and item["version"] == 1)
        saved = tools.collision_flags(slug, draft["id"])
        preview = client.post("/api/try/draft", json={
            "client": slug,
            "technique_ids": draft["techniques"],
        })
        assert preview.status_code == 200
        saved_by_business = {item["with_business_id"]: item for item in saved}
        preview_by_business = {item["business_id"]: item for item in preview.json()["results"]}
        for business_id, result in saved_by_business.items():
            assert preview_by_business[business_id]["risk"] == result["risk"]
            assert preview_by_business[business_id]["similarity"] == result["similarity"]
            assert set(preview_by_business[business_id]["shared_ids"]) == set(result["shared_ids"])


def test_try_draft_preview_does_not_write_under_readonly(seeded_demo, monkeypatch):
    monkeypatch.setattr(web, "READONLY", True)
    client = TestClient(web.app)
    draft = next(item for item in tools.drafts("tumble-town") if item["status"] == "flagged")
    agency = db.agency()
    before = db.rows(agency, "MATCH (n) RETURN count(n) AS count")[0]["count"]

    response = client.post("/api/try/draft", json={
        "client": "tumble-town",
        "technique_ids": draft["techniques"],
    })

    assert response.status_code == 200
    assert db.rows(agency, "MATCH (n) RETURN count(n) AS count")[0]["count"] == before


def test_try_draft_unknown_client_returns_404(seeded_demo):
    client = TestClient(web.app)
    response = client.post("/api/try/draft", json={
        "client": "unknown-client",
        "technique_ids": ["pace_stop_motion"],
    })

    assert response.status_code == 404


def test_try_lead_preview_rejects_unknown_neighborhood_and_audience(seeded_demo, monkeypatch):
    monkeypatch.setattr(web, "READONLY", True)
    client = TestClient(web.app)
    payload = {"name": "New Studio", "category": "Kids art", "targets": {"A1": 0.5}, "preview": True}

    unknown_neighborhood = client.post("/api/try/lead", json=payload | {"neighborhood": "unknown"})
    unknown_audience = client.post(
        "/api/try/lead",
        json=payload | {"neighborhood": "n_flatiron", "targets": {"unknown-audience": 0.5}},
    )

    assert unknown_neighborhood.status_code == 422
    assert unknown_audience.status_code == 422


def test_unknown_business_and_pitch_return_404(seeded_demo):
    client = TestClient(web.app)
    assert client.get("/api/business/unknown-business").status_code == 404
    assert client.get("/api/pitch/tumble-town/unknown-pitch").status_code == 404


def test_q2_includes_business_on_one_overlapping_audience_hop(seeded_demo):
    draft = next(
        item for item in tools.drafts("tumble-town")
        if item["status"] == "queued" and item["version"] == 1
    )
    source = db.agency()
    target = db.rows(
        source,
        "MATCH (:Business {id: 'tumble-town'})-[:TARGETS]->(a:Audience) RETURN a.id AS id LIMIT 1",
    )[0]["id"]
    db.run(source, """CREATE (:Audience {id: 'q2-overlap-audience'})
                      CREATE (:Business {id: 'q2-neighbor', name: 'Q2 Neighbor', status: 'signed'})
                      WITH 1 AS ignored
                      MATCH (other:Business {id: 'q2-neighbor'}), (aud:Audience {id: 'q2-overlap-audience'})
                      CREATE (other)-[:TARGETS {weight: 1.0}]->(aud)
                      WITH other, aud
                      MATCH (mine:Audience {id: $target})
                      CREATE (mine)-[:OVERLAPS {share: 0.8}]->(aud)""", {"target": target})
    shared_id = db.rows(
        source,
        """MATCH (f:Fingerprint {id: $draft})-[:USES]->(t:Technique)
           WHERE t.rarity >= $rare RETURN t.id AS id LIMIT 1""",
        {"draft": draft["id"], "rare": config.RARE},
    )[0]["id"]
    db.run(source, queries.P1_PROJECT_FINGERPRINT, {
        "draft_id": "q2-neighbor-fingerprint",
        "kind": "post",
        "client": "q2-neighbor",
        "now": tools.now(),
        "technique_ids": [shared_id],
    })

    results = tools.double_take("tumble-town", draft["id"])

    assert any(result["business_id"] == "q2-neighbor" for result in results)
