"""Named graph tools. Agents reach FalkorDB only through these, never raw Cypher.

The one rule: every agent write also writes a Decision with DECIDED_BY, so every artifact has a why.
Reads that feed the product are P1 and Q0-Q5 from queries.py; the writes below fill the schema around them.
"""
from __future__ import annotations

import json
import uuid
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, timedelta, timezone

from . import config, db, queries, seed

AGENT_NAMES = {
    "scout": "Scout", "researcher": "Researcher", "auditor": "Auditor", "style_director": "Style Director",
    "strategist": "Strategist", "producer": "Producer", "standards": "Standards",
    "account_manager": "Account Manager", "board": "Yaz",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


_world_cache: dict | None = None
_sim_day_cache: int | None = None
_sim_day_override: ContextVar[int | None] = ContextVar("redstring_sim_day_override", default=None)


def world() -> dict:
    global _world_cache
    if _world_cache is None:
        _world_cache = seed.load_world()
    return _world_cache


def sim_day() -> int:
    override = _sim_day_override.get()
    if override is not None:
        return override
    global _sim_day_cache
    if _sim_day_cache is None:
        rows = db.rows(db.agency(), "MATCH (c:Clock {id: 'studio'}) RETURN c.day AS day")
        _sim_day_cache = int(rows[0]["day"]) if rows else 0
    return _sim_day_cache


@contextmanager
def sim_day_at(day: int):
    token = _sim_day_override.set(day)
    try:
        yield
    finally:
        _sim_day_override.reset(token)


def set_sim_day(day: int) -> int:
    global _sim_day_cache
    db.run(db.agency(), "MERGE (c:Clock {id: 'studio'}) SET c.day = $day", {"day": day})
    _sim_day_cache = day
    return day


def sim_date(day: int | None = None) -> str:
    current = sim_day() if day is None else day
    return (date.fromisoformat(world()["world_date"]) + timedelta(days=current)).isoformat()


def business(slug: str) -> dict:
    rows = db.rows(db.agency(), """MATCH (b:Business {id: $id})-[:LOCATED_IN]->(n:Neighborhood)
                                   RETURN b, n.name AS neighborhood""", {"id": slug})
    if not rows:
        raise ValueError(f"unknown business {slug}")
    biz = rows[0]["b"]
    biz["neighborhood"] = rows[0]["neighborhood"]
    return biz


# ------------------------------------------------------------------ decisions

def _decide(g, agent: str, text: str, rationale: str, affects: list[tuple[str, str]],
            based_on: list[tuple[str, str]] = ()) -> str:
    """Write a Decision, DECIDED_BY the agent, AFFECTS each (label, id), BASED_ON each (label, id)."""
    did = _id("dec")
    db.run(g, """MERGE (a:Agent {id: $agent}) ON CREATE SET a.name = $name
                 CREATE (d:Decision {id: $id, text: $text, rationale: $rationale, at: $at, day: $day})
                 -[:DECIDED_BY]->(a)""",
           {"agent": agent, "name": AGENT_NAMES.get(agent, agent), "id": did, "text": text,
            "rationale": rationale, "at": now(), "day": sim_day()})
    for label, nid in affects:
        db.run(g, f"MATCH (d:Decision {{id: $d}}), (n:{label} {{id: $n}}) CREATE (d)-[:AFFECTS]->(n)", {"d": did, "n": nid})
    for label, nid in based_on:
        db.run(g, f"MATCH (d:Decision {{id: $d}}), (n:{label} {{id: $n}}) CREATE (d)-[:BASED_ON]->(n)", {"d": did, "n": nid})
    return did


# ------------------------------------------------------------------ agency directory

def pipeline_board() -> list[dict]:
    return db.rows(db.agency(), queries.PIPELINE)


def audiences_of(client: str) -> list[dict]:
    return db.rows(db.agency(), """MATCH (b:Business {id: $id})-[t:TARGETS]->(a:Audience)
                                   RETURN a.id AS id, a.name AS audience, t.weight AS weight ORDER BY weight DESC""",
                   {"id": client})


def list_styles() -> list[dict]:
    return db.rows(db.agency(), queries.STYLES)


def techniques(ids: list[str]) -> list[dict]:
    return db.rows(db.agency(), """MATCH (t:Technique)-[:PART_OF]->(s:Style) WHERE t.id IN $ids
                                   RETURN t.id AS id, t.name AS name, t.category AS category,
                                          t.rarity AS rarity, s.name AS style""", {"ids": ids})


def signatures(slug: str | None = None) -> list[dict]:
    q = """MATCH (b:Business)-[s:SIGNATURE]->(t:Technique) WHERE $id IS NULL OR b.id = $id
           RETURN b.id AS business_id, b.name AS business, t.id AS technique_id, t.name AS technique,
                  t.rarity AS rarity, s.share AS share ORDER BY business, share DESC"""
    return db.rows(db.agency(), q, {"id": slug})


def audience_paths(a: str, b: str) -> list[dict]:
    return db.rows(db.agency(), queries.Q2_AUDIENCE_PATHS, {"a": a, "b": b})


def reference_counts(ids: list[str]) -> dict[str, int]:
    rows = db.rows(db.agency(), queries.Q2_REFERENCE_COUNTS, {"ids": ids})
    return {row["id"]: row["ref_count"] for row in rows}


def reference_total() -> int:
    rows = db.rows(db.agency(), queries.Q2_REFERENCE_TOTAL)
    return rows[0]["reference_total"] if rows else 0


# ------------------------------------------------------------------ Q1: Scout

def _lead_conflict_result(lead: str, paths: list[dict], competitors: list[dict]) -> dict:
    per = defaultdict(lambda: {"conflict": 0.0, "same_category": False, "paths": []})
    for p in paths:
        c = per[p["client"]]
        c["client_id"] = p["client_id"]
        c["conflict"] += p["conflict"]
        c["same_category"] |= bool(p["same_category"])
        via = f"{p['hop']} -> {p['via']}" if p["hop"] else p["via"]
        c["paths"].append({"via": via, "conflict": round(p["conflict"], 3)})
    clients = sorted(({"client": k, **v, "conflict": round(v["conflict"], 3)} for k, v in per.items()),
                     key=lambda x: -x["conflict"])
    top = clients[0]["conflict"] if clients else 0.0
    if competitors:
        verdict, reason = "decline", f"Same category as {competitors[0]['client']} in {competitors[0]['neighborhood']}: a direct competitor of a client."
    elif top >= config.DIFFERENTIATE_CONFLICT:
        verdict, reason = "pursue_differentiated", f"Overlaps {clients[0]['client']} on the same parents (conflict {top:.2f}); pitch only with differentiated territory."
    elif top >= config.BORDERLINE_CONFLICT:
        verdict, reason = "borderline", f"Partial overlap with {clients[0]['client']} (conflict {top:.2f}); board call."
    else:
        verdict, reason = "pursue", "Little or no audience overlap with signed clients." if not clients else f"Light overlap (max {top:.2f}); clear to pitch."
    return {"lead": lead, "verdict": verdict, "reason": reason, "max_conflict": round(top, 3),
            "competitors": competitors, "clients": clients}


def lead_conflict(lead: str) -> dict:
    """Q1 plus the same-category, same-neighborhood rule. Returns per-client conflict and the audience paths."""
    g = db.agency()
    paths = db.rows(g, queries.Q1_LEAD_CONFLICT, {"lead": lead})
    competitors = db.rows(g, queries.Q1_SAME_AREA_COMPETITOR, {"lead": lead})
    return _lead_conflict_result(lead, paths, competitors)


def lead_conflict_preview(lead: str, category: str, neighborhood: str, targets: dict[str, float]) -> dict:
    g = db.agency()
    audiences = [{"id": audience, "weight": weight} for audience, weight in targets.items()]
    paths = db.rows(g, queries.Q1_LEAD_CONFLICT_PREVIEW, {"audiences": audiences, "category": category})
    competitors = db.rows(g, queries.Q1_SAME_AREA_COMPETITOR_PREVIEW,
                          {"category": category, "neighborhood": neighborhood})
    return _lead_conflict_result(lead, paths, competitors)


def record_screening(lead: str, verdict: str, reason: str, paths: list | None = None, agent: str = "scout") -> dict:
    g = db.agency()
    db.run(g, """MATCH (a:Agent {id: $agent}), (b:Business {id: $lead})
                 OPTIONAL MATCH (a)-[old:SCREENED]->(b) DELETE old""", {"agent": agent, "lead": lead})
    db.run(g, """MATCH (a:Agent {id: $agent}), (b:Business {id: $lead})
                 CREATE (a)-[:SCREENED {at: $at, verdict: $verdict, reason: $reason, paths: $paths}]->(b)""",
           {"agent": agent, "lead": lead, "at": now(), "verdict": verdict, "reason": reason,
            "paths": json.dumps(paths or [])})
    did = _decide(g, agent, f"Screened {lead}: {verdict}", reason, [("Business", lead)])
    return {"lead": lead, "verdict": verdict, "decision": did}


def screen_lead(lead: str) -> dict:
    """Scout's whole move: run Q1, write the SCREENED verdict and its Decision."""
    res = lead_conflict(lead)
    record_screening(lead, res["verdict"], res["reason"], res["clients"])
    return res


def screening_card(lead: str) -> dict:
    rows = db.rows(db.agency(), """MATCH (a:Agent)-[s:SCREENED]->(b:Business {id: $id})
                                   RETURN b.name AS business, s.verdict AS verdict, s.reason AS reason,
                                          s.at AS at, s.paths AS paths, a.name AS by""", {"id": lead})
    if not rows:
        return {}
    r = rows[0]
    r["paths"] = json.loads(r["paths"] or "[]")
    return r


# ------------------------------------------------------------------ lifecycle

def set_status(slug: str, status: str, agent: str, rationale: str) -> dict:
    g = db.agency()
    extra = ", b.passed_at = $at" if status == "passed" else ""
    db.run(g, f"MATCH (b:Business {{id: $id}}) SET b.status = $status{extra}", {"id": slug, "status": status, "at": now()})
    if status in ("pursued", "pitched", "signed"):
        db.run(g, """MATCH (a:Agent {id: 'account_manager'}), (b:Business {id: $id})
                     MERGE (a)-[o:OWNS]->(b) ON CREATE SET o.since = $at""", {"id": slug, "at": now()})
    did = _decide(g, agent, f"{slug} is now {status}", rationale, [("Business", slug)])
    if config.client_graph_name(slug) in db.list_graphs():
        cg = db.client(slug)
        _decide(cg, agent, f"Status: {status}", rationale, [("Business", slug)])
    return {"business": slug, "status": status, "decision": did}


def pursue(slug: str, agent: str = "scout", rationale: str = "") -> dict:
    """Create the prospect's private graph and move it to pursued. Signing later changes a status, not a graph."""
    if config.client_graph_name(slug) not in db.list_graphs():
        seed.create_client_graph(world(), slug, include_posts=False)
    return set_status(slug, "pursued", agent, rationale or "Screened and chosen for pursuit.")


# ------------------------------------------------------------------ Researcher

def record_finding(client: str, kind: str, text: str, source_url: str | None, agent: str = "researcher",
                   rationale: str = "") -> dict:
    g = db.client(client)
    fid = _id("find")
    db.run(g, "CREATE (:Finding {id: $id, kind: $kind, text: $text, source_url: $url, at: $at})",
           {"id": fid, "kind": kind, "text": text, "url": source_url, "at": now()})
    _decide(g, agent, f"Recorded {kind} finding", rationale or text, [("Finding", fid)])
    return {"finding": fid}


def record_goal(client: str, text: str, metric: str, target: float, due: str, status: str,
                based_on_findings: list[str], agent: str = "researcher", rationale: str = "") -> dict:
    g = db.client(client)
    gid = _id("goal")
    db.run(g, """CREATE (:Goal {id: $id, text: $text, metric: $metric, target: $target, due: $due, status: $status})""",
           {"id": gid, "text": text, "metric": metric, "target": target, "due": due, "status": status})
    _decide(g, agent, f"Goal ({status}): {text}", rationale or "Inferred from the findings.", [("Goal", gid)],
            [("Finding", f) for f in based_on_findings])
    return {"goal": gid}


def retire_goal(client: str, goal_id: str, agent: str = "board", rationale: str = "") -> dict:
    g = db.client(client)
    db.run(g, "MATCH (g:Goal {id: $id}) SET g.status = 'retired', g.retired_at = $at", {"id": goal_id, "at": now()})
    _decide(g, agent, "Retired goal", rationale or "Goal changed.", [("Goal", goal_id)])
    return {"goal": goal_id, "stale_drafts": stale_drafts(client)}


def findings(client: str, kind: str | None = None) -> list[dict]:
    return db.rows(db.client(client), """MATCH (f:Finding) WHERE $kind IS NULL OR f.kind = $kind
                                         RETURN f.id AS id, f.kind AS kind, f.text AS text, f.source_url AS source_url
                                         ORDER BY f.at""", {"kind": kind})


def goals(client: str) -> list[dict]:
    return db.rows(db.client(client), """MATCH (g:Goal) RETURN g.id AS id, g.text AS text, g.metric AS metric,
                                         g.target AS target, g.due AS due, g.status AS status""")


def activate_goal(client: str, goal_id: str, agent: str = "account_manager",
                  rationale: str = "The approved pitch was accepted.") -> dict:
    g = db.client(client)
    db.run(g, "MATCH (goal:Goal {id: $id}) SET goal.status = 'active'", {"id": goal_id})
    goal = next((item for item in goals(client) if item["id"] == goal_id), None)
    if goal is None:
        raise ValueError(f"unknown goal {goal_id} for {client}")
    decision = _decide(g, agent, f"Goal active: {goal['text']}", rationale, [("Goal", goal_id)])
    return {"goal": goal_id, "status": "active", "decision": decision}


# ------------------------------------------------------------------ Auditor

def load_client_posts(client: str) -> int:
    """At pursuit the prospect's public posts move into its private graph for the audit."""
    return seed.load_posts(world(), client)


def posts(client: str) -> list[dict]:
    return db.rows(db.client(client), """MATCH (p:Post) OPTIONAL MATCH (p)-[:USES]->(t:Technique)
                                         RETURN p.id AS id, p.hook AS hook, p.format AS format, p.views AS views,
                                                p.saves AS saves, p.posted_at AS posted_at, collect(t.id) AS techniques
                                         ORDER BY posted_at""")


def record_audit(client: str, summary: str, reviewed: list[str], audit_findings: list[dict],
                 agent: str = "auditor") -> dict:
    g = db.client(client)
    aid = _id("audit")
    db.run(g, "CREATE (:Audit {id: $id, at: $at, summary: $summary})", {"id": aid, "at": now(), "summary": summary})
    db.run(g, "MATCH (a:Audit {id: $id}), (p:Post) WHERE p.id IN $posts CREATE (a)-[:REVIEWED]->(p)",
           {"id": aid, "posts": reviewed})
    fids = []
    for f in audit_findings:
        fid = _id("find")
        db.run(g, """MATCH (a:Audit {id: $aid})
                     CREATE (a)-[:FOUND]->(:Finding {id: $id, kind: 'audit', text: $text, source_url: $url, at: $at})""",
               {"aid": aid, "id": fid, "text": f["text"], "url": f.get("source_url"), "at": now()})
        fids.append(fid)
    _decide(g, agent, f"Audited {len(reviewed)} posts", summary, [("Finding", f) for f in fids])
    return {"audit": aid, "findings": fids}


# ------------------------------------------------------------------ Style Director (Q3)

def open_territory(client: str, style: str, avoid: list[str] | None = None) -> list[dict]:
    """Q3: techniques in a style no overlapping business has claimed as a signature, rarest first."""
    return db.rows(db.agency(), queries.Q3_OPEN_TERRITORY, {"client": client, "style": style, "avoid": avoid or []})


def set_taste_profile(client: str, prefers: dict[str, float], avoids: list[str], summary: str,
                      based_on: list[tuple[str, str]], agent: str = "style_director") -> dict:
    g = db.client(client)
    ver = (db.rows(g, "MATCH (t:TasteProfile) RETURN max(t.version) AS v")[0]["v"] or 0) + 1
    tid = f"{client}-taste-v{ver}"
    names = {t["id"]: t["name"] for t in world()["techniques"]}
    db.run(g, "CREATE (:TasteProfile {id: $id, version: $v, summary: $s, at: $at})", {"id": tid, "v": ver, "s": summary, "at": now()})
    db.run(g, """MATCH (tp:TasteProfile {id: $id}) UNWIND $rows AS r
                 MERGE (t:Technique {id: r.tid}) ON CREATE SET t.name = r.name
                 CREATE (tp)-[:PREFERS {weight: r.w}]->(t)""",
           {"id": tid, "rows": [{"tid": k, "w": v, "name": names.get(k, k)} for k, v in prefers.items()]})
    db.run(g, """MATCH (tp:TasteProfile {id: $id}) UNWIND $rows AS r
                 MERGE (t:Technique {id: r.tid}) ON CREATE SET t.name = r.name
                 CREATE (tp)-[:AVOIDS]->(t)""",
           {"id": tid, "rows": [{"tid": k, "name": names.get(k, k)} for k in avoids]})
    _decide(g, agent, f"Taste profile v{ver}", summary, [("TasteProfile", tid)], based_on)
    return {"taste_profile": tid, "version": ver}


def taste_profile(client: str) -> dict:
    g = db.client(client)
    rows = db.rows(g, """MATCH (tp:TasteProfile) WITH tp ORDER BY tp.version DESC LIMIT 1
                         OPTIONAL MATCH (tp)-[p:PREFERS]->(t:Technique)
                         WITH tp, collect({id: t.id, name: t.name, weight: p.weight}) AS prefers
                         OPTIONAL MATCH (tp)-[:AVOIDS]->(x:Technique)
                         RETURN tp.id AS id, tp.version AS version, tp.summary AS summary, prefers,
                                collect({id: x.id, name: x.name}) AS avoids""")
    if not rows:
        return {}
    r = rows[0]
    r["prefers"] = [p for p in r["prefers"] if p["id"]]
    r["avoids"] = [a for a in r["avoids"] if a["id"]]
    return r


# ------------------------------------------------------------------ Strategist

def write_plan(client: str, period: str, goal_id: str, rationale: str, agent: str = "strategist") -> dict:
    g = db.client(client)
    pid = _id("plan")
    db.run(g, """MATCH (goal:Goal {id: $goal}) CREATE (p:Plan {id: $id, period: $period, at: $at})-[:SERVES]->(goal)""",
           {"goal": goal_id, "id": pid, "period": period, "at": now()})
    tp = taste_profile(client)
    _decide(g, agent, f"Plan for {period}", rationale, [("Plan", pid)],
            [("Goal", goal_id)] + ([("TasteProfile", tp["id"])] if tp else []))
    return {"plan": pid}


# ------------------------------------------------------------------ Producer (P1)

def referenced_reference_ids(client: str) -> list[str]:
    rows = db.rows(db.client(client), """MATCH (:Draft)-[:INSPIRED_BY]->(r:Reference)
                                         RETURN DISTINCT r.id AS id""")
    return [r["id"] for r in rows if r.get("id")]


def referenced_reference_creators(client: str) -> list[str]:
    rows = db.rows(db.client(client), """MATCH (:Draft)-[:INSPIRED_BY]->(r:Reference)
                                         RETURN DISTINCT r.creator AS creator""")
    return [r["creator"] for r in rows if r.get("creator")]


def references_for(technique_ids: list[str], limit: int = 3, category: str | None = None,
                   exclude: list[str] | None = None,
                   exclude_creators: list[str] | None = None) -> list[dict]:
    if limit <= 0 or not technique_ids:
        return []

    params = {"techniques": technique_ids, "category": category, "exclude": list(dict.fromkeys(exclude or [])),
              "exclude_creators": list(dict.fromkeys(exclude_creators or [])),
              "fetch": limit * 6}
    selected, seen_ids, seen_creators = [], set(), set()

    def add_unique(rows):
        for reference in rows:
            reference_id = reference.get("id")
            creator = reference.get("creator")
            if not reference_id or reference_id in seen_ids or creator in seen_creators:
                continue
            selected.append(reference)
            seen_ids.add(reference_id)
            seen_creators.add(creator)
            if len(selected) == limit:
                break

    add_unique(db.rows(db.agency(), queries.REFERENCES_FOR, params))
    if len(selected) < limit and (params["exclude"] or params["exclude_creators"]):
        add_unique(db.rows(db.agency(), queries.REFERENCES_FOR, params | {"exclude": []}))
    return selected


def write_draft(client: str, plan_id: str, fmt: str, hook: str, spec: str, technique_ids: list[str],
                reference_ids: list[str], rationale: str, kind: str = "draft", revision_of: str | None = None,
                based_on: list[tuple[str, str]] = (), agent: str = "producer") -> dict:
    """Write a Draft in the client graph, project its Fingerprint into agency (P1), and log the Decision."""
    g = db.client(client)
    version = 1
    if revision_of:
        prev = db.rows(g, "MATCH (d:Draft {id: $id}) RETURN d.version AS v", {"id": revision_of})
        version = (prev[0]["v"] if prev else 0) + 1
    did = _id("draft")
    names = {t["id"]: t["name"] for t in world()["techniques"]}
    db.run(g, """MATCH (p:Plan {id: $plan})
                 CREATE (p)-[:INCLUDES]->(d:Draft {id: $id, format: $fmt, hook: $hook, spec: $spec,
                         status: 'queued', version: $v, kind: $kind, at: $at})""",
           {"plan": plan_id, "id": did, "fmt": fmt, "hook": hook, "spec": spec, "v": version, "kind": kind, "at": now()})
    db.run(g, """MATCH (d:Draft {id: $id}) UNWIND $rows AS r
                 MERGE (t:Technique {id: r.id}) ON CREATE SET t.name = r.name
                 CREATE (d)-[:USES]->(t)""",
           {"id": did, "rows": [{"id": t, "name": names.get(t, t)} for t in technique_ids]})
    refs = db.rows(db.agency(), """MATCH (r:Reference) WHERE r.id IN $ids
                                  RETURN r.id AS id, r.url AS url, r.creator AS creator, r.category AS category""",
                   {"ids": reference_ids})
    db.run(g, """MATCH (d:Draft {id: $id}) UNWIND $rows AS r
                 MERGE (ref:Reference {id: r.id})
                 ON CREATE SET ref.url = r.url, ref.creator = r.creator, ref.category = r.category, ref.name = r.id
                 ON MATCH SET ref.url = coalesce(ref.url, r.url),
                              ref.creator = coalesce(ref.creator, r.creator),
                              ref.category = coalesce(ref.category, r.category)
                 CREATE (d)-[:INSPIRED_BY]->(ref)""", {"id": did, "rows": refs})
    if revision_of:
        db.run(g, "MATCH (d:Draft {id: $id}), (p:Draft {id: $prev}) CREATE (d)-[:REVISION_OF]->(p)",
               {"id": did, "prev": revision_of})
        db.run(db.agency(), queries.RETIRE_FINGERPRINT, {"id": revision_of, "now": now()})
    db.run(db.agency(), queries.P1_PROJECT_FINGERPRINT,
           {"draft_id": did, "kind": kind, "client": client, "now": now(), "technique_ids": technique_ids})
    sources = list(based_on) + [("Reference", r["id"]) for r in refs]
    if revision_of:
        sources.append(("Draft", revision_of))
    _decide(g, agent, f"Draft v{version}: {hook}", rationale, [("Draft", did), ("Plan", plan_id)], sources)
    return {"draft": did, "version": version, "fingerprint": did}


def drafts(client: str) -> list[dict]:
    return db.rows(db.client(client), """MATCH (pl:Plan)-[:INCLUDES]->(d:Draft)
                                         OPTIONAL MATCH (d)-[:USES]->(t:Technique)
                                         OPTIONAL MATCH (d)-[:REVISION_OF]->(prev:Draft)
                                         RETURN d.id AS id, d.hook AS hook, d.status AS status, d.version AS version,
                                                d.kind AS kind, d.format AS format, prev.id AS revision_of,
                                                d.at AS at, collect(t.id) AS techniques
                                         ORDER BY at""")


# ------------------------------------------------------------------ Standards (Q2, Q0)

def audience_overlap(a: str, b: str) -> float:
    rows = db.rows(db.agency(), queries.AUDIENCE_OVERLAP, {"a": a, "b": b})
    return round(min(1.0, sum(r["conflict"] for r in rows)), 3)


def double_take(client: str, draft_id: str) -> list[dict]:
    """Q2: similarity on rare techniques, times audience overlap. Read only."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=config.PASSED_COOLDOWN_DAYS)).isoformat()
    rows = db.rows(db.agency(), queries.Q2_DOUBLE_TAKE,
                   {"draft": draft_id, "rare": config.RARE, "cooldown_cutoff": cutoff})
    for r in rows:
        r["similarity"] = round(r["similarity"], 3)
        r["overlap"] = audience_overlap(client, r["business_id"])
        r["risk"] = round(r["similarity"] * r["overlap"], 3)
        r["flag"] = r["risk"] >= config.FLAG_RISK
    order = {b["id"]: i for i, b in enumerate(world()["businesses"])}
    return sorted(rows, key=lambda r: (-r["risk"], order.get(r["business_id"], len(order))))


def check_draft(client: str, draft_id: str, agent: str = "standards") -> dict:
    """Standards' whole move: run Q2, and either clear the draft or block it with a CollisionFlag."""
    draft = next((d for d in drafts(client) if d["id"] == draft_id), None)
    if draft is None:
        raise ValueError(f"unknown draft {draft_id} for {client}")
    if draft["status"] in {"blocked", "flagged", "vetoed", "retired"}:
        flags = collision_flags(client, draft_id)
        results = []
        for flag in flags:
            other = business(flag["with_business_id"])
            results.append({
                "business": flag["with_business"],
                "business_id": flag["with_business_id"],
                "status": other["status"],
                "shared_rare": flag["shared"],
                "shared_ids": flag["shared_ids"],
                "similarity": flag["similarity"],
                "overlap": flag["overlap"],
                "risk": flag["risk"],
                "flag": True,
                "evidence": flag["evidence"],
            })
        return {"draft": draft_id, "status": draft["status"], "results": results, "flags": flags}

    results = double_take(client, draft_id)
    flagged = [r for r in results if r["flag"]]
    g = db.client(client)
    if not flagged:
        db.run(g, "MATCH (d:Draft {id: $id}) SET d.status = 'queued', d.cleared_at = $at", {"id": draft_id, "at": now()})
        top = results[0] if results else None
        why = (f"Closest is {top['business']} at risk {top['risk']:.2f}, under {config.FLAG_RISK}." if top
               else "Shares no rare techniques with any business on the same audience.")
        _decide(g, agent, "Double Take: cleared", why, [("Draft", draft_id)])
        derive_signatures()
        return {"draft": draft_id, "status": "cleared", "results": results, "flags": []}

    flags = []
    for r in flagged:
        cf = _id("flag")
        evidence = db.rows(db.agency(), queries.Q2_EVIDENCE, {"other": r["business_id"], "shared": r["shared_ids"]})
        db.run(g, """MATCH (d:Draft {id: $draft})
                     CREATE (cf:CollisionFlag {id: $id, with_business: $with, with_business_id: $with_id,
                             shared_techniques: $shared, shared_ids: $shared_ids, similarity: $sim, overlap: $ov,
                             risk: $risk, evidence: $ev, at: $at})-[:FLAGS]->(d)""",
               {"draft": draft_id, "id": cf, "with": r["business"], "with_id": r["business_id"],
                "shared": r["shared_rare"], "shared_ids": r["shared_ids"], "sim": r["similarity"],
                "ov": r["overlap"], "risk": r["risk"], "ev": json.dumps(evidence), "at": now()})
        flags.append({"flag": cf, **r, "evidence": evidence})
    db.run(g, "MATCH (d:Draft {id: $id}) SET d.status = 'flagged'", {"id": draft_id})
    # A blocked draft never goes out, so its fingerprint stops counting against anyone.
    db.run(db.agency(), queries.RETIRE_FINGERPRINT, {"id": draft_id, "now": now()})
    worst = flags[0]
    _decide(g, agent, f"Double Take: blocked, resembles {worst['business']}",
            f"Shares {', '.join(worst['shared_rare'])} with {worst['business']} ({worst['status']}); "
            f"similarity {worst['similarity']:.2f} x audience overlap {worst['overlap']:.2f} = risk {worst['risk']:.2f}, "
            f"over {config.FLAG_RISK}.",
            [("Draft", draft_id)], [("CollisionFlag", f["flag"]) for f in flags])
    return {"draft": draft_id, "status": "flagged", "results": results, "flags": flags}


def derive_signatures() -> list[dict]:
    """Q0, after clearing stale signatures."""
    g = db.agency()
    db.run(g, queries.Q0_CLEAR_SIGNATURES)
    return db.rows(g, queries.Q0_DERIVE_SIGNATURES, {"rare": config.RARE, "share": config.SIGNATURE_SHARE})


def collision_flags(client: str, draft_id: str | None = None) -> list[dict]:
    rows = db.rows(db.client(client), """MATCH (cf:CollisionFlag)-[:FLAGS]->(d:Draft)
                                         WHERE $id IS NULL OR d.id = $id
                                         RETURN cf.id AS id, d.id AS draft, cf.with_business AS with_business,
                                                cf.with_business_id AS with_business_id, cf.shared_techniques AS shared,
                                                cf.shared_ids AS shared_ids, cf.similarity AS similarity,
                                                cf.overlap AS overlap, cf.risk AS risk, cf.evidence AS evidence""",
                   {"id": draft_id})
    for r in rows:
        r["evidence"] = json.loads(r["evidence"] or "[]")
    return rows


# ------------------------------------------------------------------ Account Manager and the board

def write_pitch(client: str, angle: str, draft_ids: list[str], finding_ids: list[str], goal_id: str,
                rationale: str, agent: str = "account_manager") -> dict:
    g = db.client(client)
    pid = _id("pitch")
    db.run(g, "CREATE (:Pitch {id: $id, angle: $angle, status: 'draft', created_at: $at})", {"id": pid, "angle": angle, "at": now()})
    db.run(g, "MATCH (p:Pitch {id: $id}), (d:Draft) WHERE d.id IN $ids CREATE (p)-[:SHOWS]->(d)", {"id": pid, "ids": draft_ids})
    db.run(g, "MATCH (p:Pitch {id: $id}), (f:Finding) WHERE f.id IN $ids CREATE (p)-[:CITES]->(f)", {"id": pid, "ids": finding_ids})
    db.run(g, "MATCH (p:Pitch {id: $id}), (goal:Goal {id: $goal}) CREATE (p)-[:SERVES]->(goal)", {"id": pid, "goal": goal_id})
    _decide(g, agent, f"Pitch angle: {angle}", rationale, [("Pitch", pid)],
            [("Finding", f) for f in finding_ids] + [("Goal", goal_id)])
    return {"pitch": pid}


def board_decide(client: str, target_label: str, target_id: str, verdict: str, note: str) -> dict:
    """The board (Yaz). An approve or veto becomes a Decision DECIDED_BY Yaz; agents treat it as a rule."""
    assert verdict in ("approve", "veto")
    g = db.client(client)
    if target_label == "Pitch":
        db.run(g, "MATCH (p:Pitch {id: $id}) SET p.status = $s", {"id": target_id, "s": "approved" if verdict == "approve" else "draft"})
    elif target_label == "Draft":
        db.run(g, "MATCH (d:Draft {id: $id}) SET d.status = $s", {"id": target_id, "s": "approved" if verdict == "approve" else "vetoed"})
        if verdict == "veto":
            db.run(db.agency(), queries.RETIRE_FINGERPRINT, {"id": target_id, "now": now()})
    did = _decide(g, "board", f"Board {verdict}: {target_label}", note, [(target_label, target_id)])
    return {"decision": did, "verdict": verdict}


def board_rules(client: str) -> list[dict]:
    return db.rows(db.client(client), """MATCH (d:Decision)-[:DECIDED_BY]->(:Agent {id: 'board'})
                                         RETURN d.text AS text, d.rationale AS note, d.at AS at ORDER BY d.at""")


# ------------------------------------------------------------------ route cards (Q4, Q5)

def _clean(items: list[dict], key: str) -> list[dict]:
    return [i for i in items if i.get(key)]


def decision_trace(client: str, draft_id: str) -> dict:
    """Q4, plus lineage and flags: the route card for a draft."""
    g = db.client(client)
    rows = db.rows(g, queries.Q4_DECISION_TRACE, {"draft": draft_id})
    if not rows:
        return {}
    card = rows[0]
    card["decisions"] = sorted(_clean(card["decisions"], "decision"), key=lambda d: d["at"])
    card["sources"] = _clean(card["sources"], "kind")
    card["references"] = [r for r in card["references"] if r and r.get("url")]
    lin = db.rows(g, queries.DRAFT_LINEAGE, {"draft": draft_id})[0]
    card["previous"] = _clean(lin["previous"], "id")
    card["flags_on_previous"] = _clean(lin["flags"], "with")
    card["techniques"] = lin["techniques"]
    ids = [r["id"] for r in card["references"] if r.get("id")]
    media = {m["id"]: m for m in db.rows(db.agency(), """MATCH (r:Reference) WHERE r.id IN $ids
        RETURN r.id AS id, r.platform AS platform, r.format AS format, r.analysis AS analysis""", {"ids": ids})} if ids else {}
    for r in card["references"]:
        r.update({k: v for k, v in media.get(r.get("id"), {}).items() if v is not None})
    kinds = db.rows(db.agency(), "MATCH (t:Technique) RETURN t.name AS name, t.category AS category")
    card["technique_kinds"] = {k["name"]: k["category"] for k in kinds if k["category"]}
    card["flags"] = collision_flags(client, draft_id)
    card["draft_id"] = draft_id
    card["client"] = client
    return card


def pitch_trace(client: str, pitch_id: str) -> dict:
    rows = db.rows(db.client(client), queries.PITCH_TRACE, {"pitch": pitch_id})
    if not rows:
        return {}
    card = rows[0]
    card["claims"] = _clean(card["claims"], "id")
    card["spec_posts"] = _clean(card["spec_posts"], "id")
    card["decisions"] = sorted(_clean(card["decisions"], "decision"), key=lambda d: d["at"])
    return card


def pitches(client: str) -> list[dict]:
    return db.rows(db.client(client), "MATCH (p:Pitch) RETURN p.id AS id, p.angle AS angle, p.status AS status ORDER BY p.created_at")


def stale_drafts(client: str) -> list[dict]:
    """Q5."""
    return db.rows(db.client(client), queries.Q5_STALE_DRAFTS)


def decisions(client: str | None = None, limit: int = 200) -> list[dict]:
    g = db.client(client) if client else db.agency()
    return db.rows(g, """MATCH (d:Decision)-[:DECIDED_BY]->(a:Agent)
                         OPTIONAL MATCH (d)-[:AFFECTS]->(n)
                         OPTIONAL MATCH (d)-[:AFFECTS]->(b:Business)
                         RETURN d.id AS id, d.text AS text, d.rationale AS rationale, d.at AS at,
                                coalesce(d.day, 0) AS day, a.name AS by,
                                collect(DISTINCT labels(n)[0]) AS affects, collect(DISTINCT b.id) AS business_ids
                         ORDER BY at DESC LIMIT $limit""", {"limit": limit})
