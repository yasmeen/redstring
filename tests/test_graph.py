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
    assert all(len(scene["hooks"]) == 5 for scene in offline.SCENE.values())
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

    hook = offline._fallback_hook(client, 7, 1, category)

    assert hook not in {draft["hook"] for draft in used}
    assert len(hook.split()) <= 12
    assert any(base in hook for base in offline.SCENE[category]["hooks"])


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


def test_vetoed_draft_is_not_a_needs_you_double_take_block(demo):
    from redstring.web.app import _studio_context

    blocked = demo["cannonball"]["posts"][0][0]["draft"]
    tools.board_decide("cannonball", "Draft", blocked, "veto", "Not for this business.")

    status = next(draft["status"] for draft in tools.drafts("cannonball") if draft["id"] == blocked)
    _, needs_you = _studio_context(tools.pipeline_board())

    assert status == "vetoed"
    assert blocked not in [item["draft_id"] for item in needs_you if item["type"] == "blocked"]


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
