import math

from redstring import config, rarity, references, worldgen


def test_rarity_matches_spec_examples():
    assert math.isclose(rarity.rarity(200, 2), 0.79, abs_tol=0.01)
    assert math.isclose(rarity.rarity(200, 40), 0.30, abs_tol=0.01)
    # "Rare" (>= 0.75) is about 2 or fewer of 200 references.
    assert rarity.rarity(200, 2) >= config.RARE > rarity.rarity(200, 3)


def test_world_is_deterministic():
    assert worldgen.generate() == worldgen.generate()


def test_world_shape():
    w = worldgen.generate()
    assert len(w["businesses"]) == 14
    assert sum(len(b["posts"]) for b in w["businesses"]) == 63
    assert sum(b["status"] == "signed" for b in w["businesses"]) == 3
    neighborhoods = {n["id"] for n in w["neighborhoods"]}
    assert neighborhoods == {"n_flatiron", "n_nomad", "n_gramercy", "n_chelsea"}
    assert all(b["neighborhood"] in neighborhoods for b in w["businesses"])
    assert len(w["techniques"]) == 80 and len(w["references"]) == len(references.load())
    assert all(b["synthetic"] for b in w["businesses"])


def test_planted_collision():
    w = worldgen.generate()
    tech = {t["id"]: t for t in w["techniques"]}
    planted = w["planted"]["collision_techniques"]
    assert len(planted) == 3 and all(tech[t]["rarity"] >= config.PLANT_RARITY for t in planted)
    assert len({tech[t]["style"] for t in planted}) == 1
    for slug in ("wet-paint", "cannonball"):
        posts = next(b for b in w["businesses"] if b["id"] == slug)["posts"]
        hits = [p for p in posts if set(planted) <= set(p["technique_ids"])]
        assert len(hits) == 4
        top4 = sorted(posts, key=lambda p: -p["views"])[:4]
        assert {p["id"] for p in hits} == {p["id"] for p in top4}, "planted posts are each history's best"
