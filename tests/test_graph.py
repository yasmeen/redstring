import json

import pytest

from redstring.agents import offline
from redstring import config, db, queries, seed, tools
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
    "deep-end": "pursue_differentiated",
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


def test_same_category_same_neighborhood_competitor_needs_distinct_angle(seeded):
    result = tools.lead_conflict("byte-builders")
    assert result["verdict"] == "pursue_differentiated"
    assert result["reason"] == (
        "Same category as Pixel Pond Code Club in Flatiron: pitch only with a distinct content angle."
    )
    pixel_pond = next(c for c in result["clients"] if c["client"] == "Pixel Pond Code Club")
    assert pixel_pond["same_category"] is True
    assert any(c["client"] == "Pixel Pond Code Club" and c["neighborhood"] == "Flatiron" for c in result["competitors"])


def test_same_category_same_neighborhood_requires_distinct_angle(seeded):
    result = tools.lead_conflict("deep-end")
    assert result["verdict"] == "pursue_differentiated"
    assert result["competitors"][0]["client"] == "Cannonball Swim School"
    assert result["competitors"][0]["neighborhood"] == "Gramercy Park"


def test_q1_multi_hop_paths(seeded):
    res = tools.lead_conflict("tumble-town")
    wet = next(c for c in res["clients"] if c["client"] == "Wet Paint Kids Studio")
    assert any("→ overlaps with" in p["via"] for p in wet["paths"]), "includes the named audience overlap path"


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


def test_write_plan_rejects_unknown_goal_before_writing(seeded):
    graph = db.client("wet-paint")
    before = db.rows(graph, "MATCH (p:Plan) RETURN count(p) AS count")[0]["count"]

    with pytest.raises(ValueError, match="unknown goal"):
        tools.write_plan("wet-paint", "test", "unknown-goal", "test rationale")

    assert db.rows(graph, "MATCH (p:Plan) RETURN count(p) AS count")[0]["count"] == before


def test_write_draft_rejects_missing_plan_and_invented_technique(seeded):
    goal = next(goal for goal in tools.goals("wet-paint") if goal["status"] == "active")
    plan = tools.write_plan("wet-paint", "test", goal["id"], "test rationale")["plan"]
    client_graph = db.client("wet-paint")
    agency = db.agency()
    before_drafts = db.rows(client_graph, "MATCH (d:Draft) RETURN count(d) AS count")[0]["count"]
    before_fingerprints = db.rows(agency, "MATCH (f:Fingerprint) RETURN count(f) AS count")[0]["count"]

    with pytest.raises(ValueError, match="unknown plan"):
        tools.write_draft("wet-paint", "missing-plan", "reel", "hook", "spec", [], [], "rationale")
    with pytest.raises(ValueError, match="unknown technique ids"):
        tools.write_draft("wet-paint", plan, "reel", "hook", "spec", ["invented-technique"], [], "rationale")

    assert db.rows(client_graph, "MATCH (d:Draft) RETURN count(d) AS count")[0]["count"] == before_drafts
    assert db.rows(agency, "MATCH (f:Fingerprint) RETURN count(f) AS count")[0]["count"] == before_fingerprints


def test_taste_profile_weights_are_clamped(seeded):
    technique_ids = [item["id"] for item in tools.world()["techniques"][:2]]
    tools.set_taste_profile(
        "wet-paint",
        {technique_ids[0]: -0.5, technique_ids[1]: 1.5},
        [],
        "test profile",
        [],
    )

    weights = {item["id"]: item["weight"] for item in tools.taste_profile("wet-paint")["prefers"]}

    assert weights[technique_ids[0]] == 0.0
    assert weights[technique_ids[1]] == 1.0


def test_cached_findings_keep_fetch_date_and_require_cached_result_urls(seeded, tmp_path, monkeypatch):
    from redstring.agents import offline

    monkeypatch.setattr(config, "RESEARCH_CACHE", tmp_path)
    (tmp_path / "crux.json").write_text(json.dumps({
        "fetched_at": "2026-10-16",
        "search_result_urls": ["https://source.test/valid"],
        "findings": [
            {"kind": "audience", "text": "valid", "source_url": "https://source.test/valid"},
            {"kind": "audience", "text": "invalid", "source_url": "https://source.test/unseen"},
        ],
    }))

    result = offline.researcher("crux")

    cached = [finding for finding in tools.findings("crux") if finding["kind"] == "audience"]
    assert len(cached) == 1
    assert cached[0]["source_url"] == "https://source.test/valid"
    assert cached[0]["fetched_at"] == "2026-10-16"
    assert result["goal"]


@pytest.fixture(scope="module")
def demo():
    tools._world_cache = None
    p = Pipeline("offline", log=None)
    return p.run_demo()


def _chain(demo, key, slot):
    return demo[key]["posts"][slot - 1]


def _demo_drafts(demo):
    for client, _, _, draft in _positioned_demo_drafts(demo):
        yield client, draft


def _positioned_demo_drafts(demo):
    for client, key in (
        ("tumble-town", "spec:tumble-town"),
        ("treble-clef", "spec:treble-clef"),
        ("cannonball", "cannonball"),
        ("pixel-pond", "pixel-pond"),
    ):
        for slot, chain in enumerate(demo[key]["posts"], 1):
            for version, draft in enumerate(chain, 1):
                yield client, slot, version, draft


def test_offline_shot_and_scene_templates_cover_world():
    world = tools.world()
    assert set(offline.SHOT) == {t["id"] for t in world["techniques"]}
    assert set(offline.SCENE) == {b["category"] for b in world["businesses"]}
    assert len(offline.SCENE) == 12
    assert all(set(scene) == {"subject", "place", "props", "cta", "hooks"} for scene in offline.SCENE.values())
    assert all(2 <= len(scene["props"]) <= 3 for scene in offline.SCENE.values())
    assert all(len(scene["hooks"]) == 8 for scene in offline.SCENE.values())
    assert all(len(hook.split()) <= 12 and "!" not in hook for scene in offline.SCENE.values()
               for hook in scene["hooks"])
    assert all(scene["place"].split(" ", 1)[0] in {"at", "beside", "in", "on"}
               for scene in offline.SCENE.values())
    group_categories = [category for categories in config.CATEGORY_GROUP.values() for category in categories]
    assert set(group_categories) == set(offline.SCENE)
    assert len(group_categories) == len(set(group_categories))
    for technique_id, instruction in offline.SHOT.items():
        assert all(f"{{{placeholder}}}" in instruction for placeholder in ("subject", "place", "prop")), technique_id
        assert "at {place}" not in instruction, technique_id
        instruction.format(subject="subject", place="place", prop="prop")
    assert all("{" not in instruction for instruction in offline.SUMMARY_INSTRUCTIONS.values())
    for technique in world["techniques"]:
        if technique["category"] in {"text", "color", "audio"}:
            assert technique["id"] in offline.SUMMARY_INSTRUCTIONS


def test_fallback_hooks_are_category_specific_and_unique(monkeypatch):
    client = "cannonball"
    category = "Swim lessons"
    used = [{"hook": offline.HOOKS[(client, 1, 1)]}]
    monkeypatch.setattr(tools, "drafts", lambda _client: list(used))
    first_fallback = offline._fallback_hook(client, 2, 1, category)
    assert first_fallback == offline._fallback_hook(client, 2, 1, category)

    outputs = []
    for slot in range(1, 7):
        key = (client, slot, 1)
        if key in offline.HOOKS:
            hook = offline.HOOKS[key]
        elif slot == 2:
            hook = first_fallback
        else:
            hook = offline._fallback_hook(client, slot, 1, category)
        outputs.append(hook)
        used.append({"hook": hook})

    fallback_hooks = outputs[1:]
    assert len(set(outputs)) == 6
    assert all(", take" not in hook for hook in outputs)
    assert set(fallback_hooks) <= set(offline.SCENE[category]["hooks"])


def test_fallback_hooks_remain_unique_after_category_hooks_are_used(monkeypatch):
    client = "cannonball"
    category = "Swim lessons"
    used = [{"hook": hook} for hook in offline.SCENE[category]["hooks"]]
    monkeypatch.setattr(tools, "drafts", lambda _client: list(used))

    hook = offline._fallback_hook(client, 9, 1, category)

    assert hook not in {draft["hook"] for draft in used}
    assert len(hook.split()) <= 12
    assert any(base[0].lower() + base[1:] in hook for base in offline.SCENE[category]["hooks"])
    assert hook.split(": ", 1)[1][0].islower()


def test_fallback_hook_is_in_template_opening_shot(demo):
    client = "cannonball"
    hook = offline.SCENE["Swim lessons"]["hooks"][0]
    technique_id = next(t["id"] for t in tools.world()["techniques"] if t["category"] == "hook")

    spec = offline._shot_list(client, [technique_id], "calm and clear", hook, slot=99)

    assert f"“{hook}”" in spec.splitlines()[1]


def test_demo_drafts_have_filmable_shot_lists_with_all_techniques(demo):
    for client, draft in _demo_drafts(demo):
        card = tools.decision_trace(client, draft["draft"])
        spec = card["spec"]
        shot_lines = [line for line in spec.splitlines() if line.partition(" · ")[0].isdigit()]
        assert 4 <= len(shot_lines) <= 6, (client, draft["draft"], spec)
        assert f"“{card['draft']}”" in spec
        assert spec.splitlines()[0].startswith("Voice: ")
        assert spec.splitlines()[-1].startswith("End card: ")
        assert all(" at on " not in line.lower() and " at in " not in line.lower() for line in spec.splitlines())
        assert len(shot_lines) == len(set(shot_lines)), (client, draft["draft"], shot_lines)
        props = offline.SCENE[tools.business(client)["category"]]["props"]
        for previous, current in zip(shot_lines, shot_lines[1:]):
            previous_props = {prop for prop in props if prop in previous}
            current_props = {prop for prop in props if prop in current}
            assert not previous_props & current_props, (client, draft["draft"], previous, current)
        duration = int(shot_lines[-1].split(" · ")[1].split("–")[1].removesuffix("s"))
        assert 15 <= duration <= 30, (client, draft["draft"], duration)
        technique_names = {t["name"] for t in tools.techniques(draft["techniques"])}
        assert all(name in spec for name in technique_names), (client, draft["draft"], technique_names, spec)


def test_demo_hook_shots_match_the_supplied_lines(demo):
    for client, slot, version, draft in _positioned_demo_drafts(demo):
        key = (client, slot, version)
        if key not in offline.HOOK_SHOT:
            continue
        techniques = {t["id"]: t for t in tools.techniques(draft["techniques"])}
        hook_names = [
            techniques[technique_id]["name"]
            for technique_id in draft["techniques"]
            if techniques[technique_id]["category"] == "hook"
        ]
        bracket = f" [{'; '.join(hook_names)}]" if hook_names else ""
        spec = tools.decision_trace(client, draft["draft"])["spec"]
        first_shot = next(line for line in spec.splitlines() if line.startswith("1 · "))
        assert first_shot == f"1 · 0–3s · {offline.HOOK_SHOT[key]}{bracket}"


def test_demo_reference_picks_do_not_repeat_within_clients_or_drafts(demo):
    for client in db.client_slugs():
        rows = db.rows(db.client(client), """MATCH (d:Draft)-[:INSPIRED_BY]->(r:Reference)
                                             RETURN d.id AS draft, r.id AS reference, r.creator AS creator""")
        references = [r["reference"] for r in rows]
        assert len(references) == len(set(references)), (client, references)
        creators = [r["creator"] for r in rows]
        assert len(creators) == len(set(creators)), (client, creators)
        by_draft = {}
        for row in rows:
            by_draft.setdefault(row["draft"], []).append(row["creator"])
        for draft, creators in by_draft.items():
            assert len(creators) == len(set(creators)), (client, draft, creators)


def test_demo_reference_picks_stay_in_category_group(demo):
    for client in db.client_slugs():
        category = tools.business(client)["category"]
        category_group = next(categories for categories in config.CATEGORY_GROUP.values() if category in categories)
        rows = db.rows(db.client(client), """MATCH (d:Draft)-[:INSPIRED_BY]->(r:Reference)
                                             RETURN d.id AS draft, collect(DISTINCT r.id) AS refs,
                                                    collect(DISTINCT r.category) AS categories""")
        for row in rows:
            assert len(row["refs"]) <= 2, (client, row)
            assert set(row["categories"]) <= set(category_group), (client, category, row)


def test_tumble_town_spec_collides_with_wet_paint_then_clears(demo):
    chain = _chain(demo, "spec:tumble-town", 2)
    assert [c["status"] for c in chain] == ["flagged", "queued"]
    flagged = {f["with_business"] for f in chain[0]["flags"]}
    assert "Wet Paint Kids Studio" in flagged
    assert flagged == {"Wet Paint Kids Studio", "Cannonball Swim School"}


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


def test_needs_you_includes_queued_drafts_for_approval(demo):
    from redstring.web.app import _studio_context

    _, needs_you = _studio_context(tools.pipeline_board())
    item = next(
        item for item in needs_you
        if item["type"] == "approve_posts" and item["business_id"] == "cannonball"
    )
    queued_ids = [draft["id"] for draft in tools.drafts("cannonball") if draft["status"] == "queued"]

    assert item["draft_ids"] == queued_ids
    assert item["message"] == (
        f"{len(queued_ids)} Cannonball Swim School post{'s' if len(queued_ids) != 1 else ''} "
        "cleared Double Take and need your approval"
    )


def test_blocked_fingerprints_stop_counting(demo):
    blocked = demo["cannonball"]["posts"][0][0]["draft"]
    assert db.rows(db.agency(), "MATCH (f:Fingerprint {id: $id}) RETURN f.active AS a", {"id": blocked})[0]["a"] is False


def test_reprojecting_fingerprint_replaces_uses(demo):
    ids = [technique["id"] for technique in tools.world()["techniques"][:3]]
    fingerprint = "test-reproject-fingerprint"
    try:
        params = {
            "draft_id": fingerprint,
            "kind": "draft",
            "client": "tumble-town",
            "now": tools.now(),
            "technique_ids": ids[:2],
        }
        db.run(db.agency(), queries.P1_PROJECT_FINGERPRINT, params)
        params["technique_ids"] = ids[2:]
        db.run(db.agency(), queries.P1_PROJECT_FINGERPRINT, params)
        assert {
            row["id"] for row in db.rows(
                db.agency(),
                "MATCH (:Fingerprint {id: $id})-[:USES]->(t:Technique) RETURN t.id AS id",
                {"id": fingerprint},
            )
        } == {ids[2]}
    finally:
        db.run(db.agency(), "MATCH (f:Fingerprint {id: $id}) DETACH DELETE f", {"id": fingerprint})


def test_q0_combined_clear_and_derive_replaces_stale_signatures(demo):
    expected = tools.derive_signatures()
    common = next(t["id"] for t in tools.world()["techniques"] if t["rarity"] < config.RARE)
    db.run(db.agency(), """MATCH (b:Business {id: 'wet-paint'}), (t:Technique {id: $id})
                           MERGE (b)-[:SIGNATURE]->(t)""", {"id": common})
    assert tools.derive_signatures() == expected


def test_common_techniques_do_not_dilute_q2_similarity(demo):
    blocked = next(d["id"] for d in tools.drafts("tumble-town") if d["status"] == "flagged")
    fingerprint = db.rows(
        db.agency(), "MATCH (f:Fingerprint {id: $id}) RETURN f.active AS active", {"id": blocked}
    )[0]
    existing_ids = {
        row["id"] for row in db.rows(
            db.agency(), "MATCH (:Fingerprint {id: $id})-[:USES]->(t:Technique) RETURN t.id AS id",
            {"id": blocked},
        )
    }
    common_ids = [
        t["id"] for t in tools.world()["techniques"]
        if t["rarity"] < config.RARE and t["id"] not in existing_ids
    ][:12]
    assert len(common_ids) == 12

    db.run(db.agency(), "MATCH (f:Fingerprint {id: $id}) SET f.active = true", {"id": blocked})
    try:
        original = {
            row["business_id"]: row for row in tools.double_take("tumble-town", blocked)
        }
        assert original
        for count in (0, 6, 12):
            ids = common_ids[:count]
            if ids:
                db.run(db.agency(), """MATCH (f:Fingerprint {id: $draft})
                                       UNWIND $ids AS id
                                       MATCH (t:Technique {id: id})
                                       MERGE (f)-[:USES]->(t)""",
                       {"draft": blocked, "ids": ids})
            try:
                expanded = {
                    row["business_id"]: row for row in tools.double_take("tumble-town", blocked)
                }
                assert expanded.keys() == original.keys()
                for business_id, row in original.items():
                    assert expanded[business_id]["similarity"] == row["similarity"]
                    assert expanded[business_id]["risk"] == row["risk"]
            finally:
                if ids:
                    db.run(db.agency(), """MATCH (f:Fingerprint {id: $draft})-[r:USES]->(t:Technique)
                                           WHERE t.id IN $ids DELETE r""",
                           {"draft": blocked, "ids": ids})
    finally:
        db.run(db.agency(), "MATCH (f:Fingerprint {id: $id}) SET f.active = $active",
               {"id": blocked, "active": fingerprint["active"]})


def test_rechecking_blocked_draft_preserves_verdict(demo, monkeypatch):
    blocked = demo["cannonball"]["posts"][0][0]["draft"]
    decisions_before = len(tools.decisions("cannonball"))

    def unexpected_double_take(*_args):
        pytest.fail("a blocked draft should not be rechecked")

    monkeypatch.setattr(tools, "double_take", unexpected_double_take)
    result = tools.check_draft("cannonball", blocked)

    assert result["status"] == "flagged"
    assert result["flags"]
    assert len(tools.decisions("cannonball")) == decisions_before
    assert next(d["status"] for d in tools.drafts("cannonball") if d["id"] == blocked) == "flagged"


def test_check_draft_rejects_unknown_id(demo, monkeypatch):
    decisions_before = len(tools.decisions("cannonball"))

    def unexpected_double_take(*_args):
        pytest.fail("an unknown draft should not be checked")

    monkeypatch.setattr(tools, "double_take", unexpected_double_take)
    with pytest.raises(ValueError, match="unknown draft missing-draft for cannonball"):
        tools.check_draft("cannonball", "missing-draft")

    assert len(tools.decisions("cannonball")) == decisions_before


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


def test_flagged_draft_cannot_be_approved(demo):
    from redstring.web.app import _studio_context

    blocked = demo["cannonball"]["posts"][0][0]["draft"]
    graph = db.client("cannonball")
    status_before = next(draft["status"] for draft in tools.drafts("cannonball") if draft["id"] == blocked)
    flags_before = tools.collision_flags("cannonball", blocked)
    decisions_before = db.rows(graph, "MATCH (d:Decision) RETURN count(d) AS count")[0]["count"]

    with pytest.raises(tools.BoardConflict, match="not queued"):
        tools.board_decide("cannonball", "Draft", blocked, "approve", "Not for this business.")

    status = next(draft["status"] for draft in tools.drafts("cannonball") if draft["id"] == blocked)
    decisions_after = db.rows(graph, "MATCH (d:Decision) RETURN count(d) AS count")[0]["count"]
    _, needs_you = _studio_context(tools.pipeline_board())

    assert status == status_before == "flagged"
    assert tools.collision_flags("cannonball", blocked) == flags_before
    assert decisions_after == decisions_before
    assert blocked in [item["draft_id"] for item in needs_you if item["type"] == "blocked"]


def test_vetoed_draft_fingerprint_is_not_live_work(demo):
    queued = demo["cannonball"]["posts"][0][1]["draft"]
    before = db.rows(db.agency(), "MATCH (f:Fingerprint {id: $id}) RETURN f.active AS active", {"id": queued})[0]
    assert before["active"] is True

    tools.board_decide("cannonball", "Draft", queued, "veto", "Retire this spec.")

    after = db.rows(db.agency(), "MATCH (f:Fingerprint {id: $id}) RETURN f.active AS active", {"id": queued})[0]
    assert after["active"] is False


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
