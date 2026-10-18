"""Seed the shared `agency` graph and one private `client:<slug>` graph per signed client from world.json."""
from __future__ import annotations

import json
import re

from . import config, db, queries

AGENCY_INDEXES = [
    "CREATE INDEX FOR (n:Business) ON (n.id)",
    "CREATE INDEX FOR (n:Technique) ON (n.id)",
    "CREATE INDEX FOR (n:Fingerprint) ON (n.id)",
    "CREATE INDEX FOR (n:Reference) ON (n.id)",
    "CREATE INDEX FOR (n:Audience) ON (n.id)",
    "CREATE INDEX FOR (n:Agent) ON (n.id)",
    "CREATE INDEX FOR (n:Style) ON (n.name)",
]
CLIENT_INDEXES = [
    "CREATE INDEX FOR (n:Draft) ON (n.id)",
    "CREATE INDEX FOR (n:Post) ON (n.id)",
    "CREATE INDEX FOR (n:Goal) ON (n.id)",
    "CREATE INDEX FOR (n:Finding) ON (n.id)",
    "CREATE INDEX FOR (n:Decision) ON (n.id)",
    "CREATE INDEX FOR (n:Technique) ON (n.id)",
    "CREATE INDEX FOR (n:Agent) ON (n.id)",
    "CREATE INDEX FOR (n:Reference) ON (n.id)",
    "CREATE INDEX FOR (n:Pitch) ON (n.id)",
]


def load_world(path=config.WORLD_PATH) -> dict:
    return json.loads(path.read_text())


def find_business(world: dict, slug: str) -> dict:
    for business in world["businesses"]:
        if business["id"] == slug:
            return business
    for business in world.get("lead_feed", []):
        if business["id"] == slug:
            return business
    raise ValueError(f"unknown business {slug}")


def validate_business_slug(world: dict, slug: str) -> dict:
    if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9-]+", slug):
        raise ValueError(f"invalid business slug {slug!r}")
    return find_business(world, slug)


def _indexes(g, stmts):
    for s in stmts:
        try:
            db.run(g, s)
        except Exception:  # index already exists
            pass


def seed_agency(world: dict) -> None:
    db.drop(config.AGENCY_GRAPH)
    g = db.agency()
    _indexes(g, AGENCY_INDEXES)

    db.run(g, "UNWIND $rows AS r CREATE (:Agent {id: r.id, name: r.name, desk: r.desk, model: r.model})",
           {"rows": world["agents"]})
    db.run(g, "UNWIND $rows AS r CREATE (:Neighborhood {id: r.id, name: r.name})",
           {"rows": world["neighborhoods"]})
    db.run(g, "UNWIND $rows AS r CREATE (:Audience {id: r.id, name: r.name, description: r.description})",
           {"rows": world["audiences"]})
    db.run(g, """UNWIND $rows AS r MATCH (a:Audience {id: r.a}), (b:Audience {id: r.b})
                 CREATE (a)-[:OVERLAPS {share: r.share}]->(b)""", {"rows": world["overlaps"]})

    db.run(g, "UNWIND $rows AS r CREATE (:Style {id: r.id, name: r.name})", {"rows": world["styles"]})
    db.run(g, """UNWIND $rows AS r MATCH (s:Style {id: r.style})
                 CREATE (:Technique {id: r.id, name: r.name, category: r.category,
                                     rarity: r.rarity, ref_count: r.ref_count})-[:PART_OF]->(s)""",
           {"rows": world["techniques"]})
    refs = [{k: r.get(k) for k in ("id", "url", "creator", "category", "platform", "format", "analyzed_by",
                                    "analyzed_at", "views", "analysis", "techniques", "placeholder")}
            for r in world["references"]]
    db.run(g, """UNWIND $rows AS r
                 CREATE (ref:Reference {id: r.id, url: r.url, creator: r.creator, platform: r.platform,
                         category: r.category, format: r.format, analyzed_by: r.analyzed_by, analyzed_at: r.analyzed_at,
                         views: r.views, analysis: r.analysis, placeholder: coalesce(r.placeholder, false)})
                 WITH ref, r UNWIND r.techniques AS tid
                 MATCH (t:Technique {id: tid}) CREATE (ref)-[:USES]->(t)""", {"rows": refs})

    biz = [{"id": b["id"], "name": b["name"], "category": b["category"], "status": b["status"],
            "voice": b["voice"], "neighborhood": b["neighborhood"],
            "targets": [{"aud": a, "w": w} for a, w in b["targets"].items()]} for b in world["businesses"]]
    db.run(g, """UNWIND $rows AS r MATCH (n:Neighborhood {id: r.neighborhood})
                 CREATE (b:Business {id: r.id, name: r.name, category: r.category, status: r.status,
                                     voice: r.voice, synthetic: true})-[:LOCATED_IN]->(n)
                 WITH b, r UNWIND r.targets AS t MATCH (a:Audience {id: t.aud})
                 CREATE (b)-[:TARGETS {weight: t.w}]->(a)""", {"rows": biz})
    db.run(g, """MATCH (a:Agent {id: 'account_manager'}), (b:Business {status: 'signed'})
                 CREATE (a)-[:OWNS {since: '2026-06-01'}]->(b)""")

    # Every past post, lead or client, is public: project its technique fingerprint now.
    for b in world["businesses"]:
        for p in b["posts"]:
            db.run(g, queries.P1_PROJECT_FINGERPRINT, {
                "draft_id": p["id"], "kind": "post", "client": b["id"],
                "now": p["posted_at"], "technique_ids": p["technique_ids"]})

    db.run(g, queries.Q0_CLEAR_SIGNATURES)
    db.run(g, queries.Q0_DERIVE_SIGNATURES, {"rare": config.RARE, "share": config.SIGNATURE_SHARE})


def create_client_graph(world: dict, slug: str, include_posts: bool = True) -> None:
    """A business's private graph. Created at pursuit (or at seed for signed clients) and kept through signing."""
    b = validate_business_slug(world, slug)
    db.drop(config.client_graph_name(slug))
    g = db.client(slug)
    _indexes(g, CLIENT_INDEXES)
    db.run(g, "MERGE (:Business {id: $id, name: $name, category: $category})", b)
    db.run(g, """UNWIND $rows AS t
                 CREATE (:Technique {id: t.id, name: t.name, category: t.category, rarity: t.rarity})""",
           {"rows": world["techniques"]})
    if include_posts:
        load_posts(world, slug)
    if b["status"] == "signed":
        goal = {"id": f"{slug}-goal-1", "status": "active", **b["goal"]}
        db.run(g, """CREATE (:Goal {id: $id, text: $text, metric: $metric, target: $target,
                                    due: $due, status: $status})""", goal)


def load_posts(world: dict, slug: str) -> int:
    g = db.client(slug)
    b = find_business(world, slug)
    tech = {t["id"]: t["name"] for t in world["techniques"]}
    posts = [{k: v for k, v in p.items() if not k.startswith("_")} for p in b["posts"]]
    for p in posts:
        p["transitions"] = ",".join(p["transitions"])
        p["techniques"] = [{"id": t, "name": tech[t]} for t in p["technique_ids"]]
    db.run(g, """UNWIND $rows AS p
                 MERGE (post:Post {id: p.id})
                 SET post.format = p.format, post.hook = p.hook, post.caption = p.caption,
                     post.views = p.views, post.saves = p.saves, post.posted_at = p.posted_at,
                     post.structure = p.structure, post.pacing = p.pacing, post.transitions = p.transitions,
                     post.text_treatment = p.text_treatment, post.color = p.color, post.audio = p.audio
                 WITH post, p UNWIND p.techniques AS t
                 MERGE (tech:Technique {id: t.id}) ON CREATE SET tech.name = t.name
                 MERGE (post)-[:USES]->(tech)""", {"rows": posts})
    return len(posts)


def seed_all(world: dict | None = None) -> dict:
    world = world or load_world()
    from . import tools
    tools._world_cache = world
    tools._sim_day_cache = None
    for slug in db.client_slugs():
        db.drop(config.client_graph_name(slug))
    seed_agency(world)
    signed = [b["id"] for b in world["businesses"] if b["status"] == "signed"]
    for slug in signed:
        create_client_graph(world, slug)
    return {"agency": config.AGENCY_GRAPH, "clients": [config.client_graph_name(s) for s in signed]}
