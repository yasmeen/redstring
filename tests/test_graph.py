import pytest

from redstring.agents import offline
from redstring import db, queries, seed, tools
from redstring.pipeline import Pipeline

EXPECTED_VERDICTS = {
    "byte-builders": "pursue_differentiated",
    "tumble-town": "pursue_differentiated",
    "treble-clef": "pursue_differentiated",
    "northpoint": "pursue_differentiated",
    "page-turn": "borderline",
    "crux": "pursue",
    "second-rise": "pursue",
    "corner-cup": "pursue",
    "still-water": "pursue",
    "good-boy": "pursue",
    "deep-end": "decline",
}


@pytest.fixture(scope="module")
def seeded():
    tools._world_cache = None
    return seed.seed_all()


def test_two_graph_kinds(seeded):
    assert set(db.list_graphs()) >= {"agency", "client:pixel-pond", "client:wet-paint", "client:cannonball"}


def test_q1_verdicts_match_spec(seeded):
    got = {lead: tools.lead_conflict(lead)["verdict"] for lead in EXPECTED_VERDICTS}
    assert got == EXPECTED_VERDICTS


def test_same_category_other_neighborhood_is_not_auto_declined(seeded):
    result = tools.lead_conflict("byte-builders")
    assert result["competitors"] == []
    pixel_pond = next(c for c in result["clients"] if c["client"] == "Pixel Pond Code Club")
    assert pixel_pond["same_category"] is True


def test_same_category_same_neighborhood_declines(seeded):
    result = tools.lead_conflict("deep-end")
    assert result["verdict"] == "decline"
    assert result["competitors"][0]["client"] == "Cannonball Swim School"
    assert result["competitors"][0]["neighborhood"] == "Gramercy Park"


def test_q1_multi_hop_paths(seeded):
    res = tools.lead_conflict("tumble-town")
    wet = next(c for c in res["clients"] if c["client"] == "Wet Paint Kids Studio")
    assert any("->" in p["via"] for p in wet["paths"]), "includes lead -> audience -> overlapping audience -> client"


def test_q0_planted_set_is_wet_paint_signature(seeded):
    planted = set(tools.world()["planted"]["collision_techniques"])
    sig = {s["technique_id"] for s in tools.signatures("wet-paint")}
    assert planted <= sig


def test_fingerprints_carry_no_copy(seeded):
    props = db.rows(db.agency(), "MATCH (f:Fingerprint) RETURN keys(f) AS k LIMIT 1")[0]["k"]
    assert not {"hook", "caption", "spec"} & set(props)


def test_client_graphs_are_isolated(seeded):
    for slug in ("pixel-pond", "wet-paint", "cannonball"):
        ids = [r["id"] for r in db.rows(db.client(slug), "MATCH (p:Post) RETURN p.id AS id")]
        assert ids and all(i.startswith(slug) for i in ids)


@pytest.fixture(scope="module")
def demo():
    tools._world_cache = None
    p = Pipeline("offline", log=None)
    return p.run_demo()


def _chain(demo, key, slot):
    return demo[key]["posts"][slot - 1]


def _demo_drafts(demo):
    for client, key in (
        ("tumble-town", "spec:tumble-town"),
        ("treble-clef", "spec:treble-clef"),
        ("cannonball", "cannonball"),
        ("pixel-pond", "pixel-pond"),
    ):
        for chain in demo[key]["posts"]:
            for draft in chain:
                yield client, draft


def test_offline_shot_and_scene_templates_cover_world():
    world = tools.world()
    assert set(offline.SHOT) == {t["id"] for t in world["techniques"]}
    assert set(offline.SCENE) == {b["category"] for b in world["businesses"]}
    assert len(offline.SCENE) == 12
    assert all(set(scene) == {"subject", "place", "prop", "cta"} for scene in offline.SCENE.values())
    for technique_id, instruction in offline.SHOT.items():
        assert all(f"{{{placeholder}}}" in instruction for placeholder in ("subject", "place", "prop")), technique_id
        instruction.format(subject="subject", place="place", prop="prop")


def test_demo_drafts_have_filmable_shot_lists_with_all_techniques(demo):
    for client, draft in _demo_drafts(demo):
        card = tools.decision_trace(client, draft["draft"])
        spec = card["spec"]
        shot_lines = [line for line in spec.splitlines() if line.partition(" · ")[0].isdigit()]
        assert 4 <= len(shot_lines) <= 6, (client, draft["draft"], spec)
        assert f"“{card['draft']}”" in spec
        assert spec.splitlines()[0].startswith("Voice: ")
        assert spec.splitlines()[-1].startswith("End card: ")
        duration = int(shot_lines[-1].split(" · ")[1].split("–")[1].removesuffix("s"))
        assert 15 <= duration <= 30, (client, draft["draft"], duration)
        technique_names = {t["name"] for t in tools.techniques(draft["techniques"])}
        assert all(name in spec for name in technique_names), (client, draft["draft"], technique_names, spec)


def test_demo_reference_picks_do_not_repeat_within_clients_or_drafts(demo):
    for client in db.client_slugs():
        rows = db.rows(db.client(client), """MATCH (d:Draft)-[:INSPIRED_BY]->(r:Reference)
                                             RETURN d.id AS draft, r.id AS reference, r.creator AS creator""")
        references = [r["reference"] for r in rows]
        assert len(references) == len(set(references)), (client, references)
        by_draft = {}
        for row in rows:
            by_draft.setdefault(row["draft"], []).append(row["creator"])
        for draft, creators in by_draft.items():
            assert len(creators) == len(set(creators)), (client, draft, creators)


def test_demo_reference_picks_match_business_category_when_available(demo):
    for client, draft in _demo_drafts(demo):
        category = tools.business(client)["category"]
        candidates = db.rows(db.agency(), """MATCH (r:Reference)-[:USES]->(t:Technique)
                                             WHERE r.category = $category AND t.id IN $techniques
                                             RETURN count(DISTINCT r) AS count""",
                             {"category": category, "techniques": draft["techniques"]})[0]["count"]
        if candidates:
            cited = db.rows(db.client(client), """MATCH (:Draft {id: $id})-[:INSPIRED_BY]->(r:Reference)
                                                  RETURN collect(DISTINCT r.category) AS categories""",
                            {"id": draft["draft"]})[0]["categories"]
            assert category in cited, (client, draft["draft"], category, draft["techniques"], cited)


def test_tumble_town_spec_collides_with_wet_paint_then_clears(demo):
    chain = _chain(demo, "spec:tumble-town", 2)
    assert [c["status"] for c in chain] == ["flagged", "queued"]
    flagged = {f["with_business"] for f in chain[0]["flags"]}
    assert "Wet Paint Kids Studio" in flagged
    assert chain[0]["flags"][0]["with_business"] == "Wet Paint Kids Studio"


def test_pitch_against_pitch_collision(demo):
    chain = _chain(demo, "spec:treble-clef", 1)
    assert [c["status"] for c in chain] == ["flagged", "queued"]
    assert chain[0]["flags"][0]["with_business"] == "Tumble Town Gym"


def test_cannonball_expected_run(demo):
    chain = demo["cannonball"]["posts"][0]
    assert [c["status"] for c in chain] == ["flagged", "queued"]
    f = chain[0]["flags"][0]
    assert f["with_business"] == "Wet Paint Kids Studio" and len(f["shared_ids"]) == 2
    assert not set(f["shared_ids"]) & set(chain[1]["techniques"]), "revision drops the flagged techniques"


def test_revision_lineage_and_route_card(demo):
    rev = demo["cannonball"]["posts"][0][1]["draft"]
    card = tools.decision_trace("cannonball", rev)
    assert card["goal"] == "Grow the winter waitlist to 150"
    assert card["previous"] and card["flags_on_previous"]
    assert {d["by"] for d in card["decisions"]} >= {"Producer", "Standards"}
    assert card["references"], "draft is INSPIRED_BY library references"


def test_decision_trace_references_include_url_creator_and_category(demo):
    rev = demo["cannonball"]["posts"][0][1]["draft"]
    references = tools.decision_trace("cannonball", rev)["references"]
    assert references
    assert all(isinstance(r, dict) and r.get("url") and r.get("creator") and r.get("category") for r in references)


def test_blocked_fingerprints_stop_counting(demo):
    blocked = demo["cannonball"]["posts"][0][0]["draft"]
    assert db.rows(db.agency(), "MATCH (f:Fingerprint {id: $id}) RETURN f.active AS a", {"id": blocked})[0]["a"] is False


def test_every_artifact_has_a_why(demo):
    """Every agent-written node is AFFECTED by a Decision. Seeded history (posts, signed clients' first goal) is exempt."""
    for slug in db.client_slugs():
        orphans = db.rows(db.client(slug), """
            MATCH (n) WHERE (n:Draft OR n:Plan OR n:TasteProfile OR n:Pitch OR n:Goal OR n:Finding)
                        AND NOT n.id ENDS WITH '-goal-1'
            OPTIONAL MATCH (d:Decision)-[:AFFECTS]->(n)
            WITH n, count(d) AS c WHERE c = 0
            RETURN labels(n)[0] AS label, n.id AS id""")
        assert orphans == [], (slug, orphans)
        unowned = db.rows(db.client(slug), """
            MATCH (d:Decision) WHERE NOT (d)-[:DECIDED_BY]->(:Agent) RETURN d.id AS id""")
        assert unowned == []


def test_pitch_claims_are_sourced(demo):
    pid = tools.pitches("tumble-town")[-1]["id"]
    card = tools.pitch_trace("tumble-town", pid)
    assert card["goal_status"] == "hypothesized"
    assert card["status"] == "approved"
    web = [c for c in card["claims"] if c["kind"] != "audit"]
    assert web and all(c["source_url"] for c in web)
    assert len(card["spec_posts"]) == 3 and all(d["status"] == "queued" for d in card["spec_posts"])


def test_signing_keeps_the_graph(demo):
    assert tools.business("tumble-town")["status"] == "signed"
    assert "client:tumble-town" in db.list_graphs()
    assert tools.findings("tumble-town")


def test_q5_stale_drafts_after_goal_retired(demo):
    stale = tools.stale_drafts("pixel-pond")
    assert len(stale) == 2 and all(s["retired_goal"] == "Fill 40 seats in the spring robotics session" for s in stale)


def test_q3_open_territory_excludes_claimed_signatures(demo):
    wet_sig = {s["technique_id"] for s in tools.signatures("wet-paint")}
    rows = tools.open_territory("tumble-town", "Messy Process", [])
    assert not wet_sig & {r["technique_id"] for r in rows}
