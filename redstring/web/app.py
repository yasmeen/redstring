"""Red String web app: pipeline board, route cards, Double Take, the board's approve and veto.

    uvicorn redstring.web.app:app --reload
"""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import config, db, loop, queries, registry, tools
from ..pipeline import STEPS, Pipeline, run_step

STATIC = Path(__file__).parent / "static"
MODE = os.environ.get("REDSTRING_MODE", "offline")
# On a public link, REDSTRING_READONLY=1 keeps visitors from resetting the demo or acting as the board.
# The two "try it" inputs still work: they add only synthetic leads and temporary fingerprints.
READONLY = os.environ.get("REDSTRING_READONLY") == "1"
# Optional walkthrough video shown at the top of /analysis (a YouTube link or an .mp4 URL).
VIDEO_URL = os.environ.get("REDSTRING_VIDEO_URL", "").strip()

app = FastAPI(title="Red String")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
_lock = threading.Lock()
_log: list[str] = []
_done: list[str] = []


def _writable() -> None:
    if READONLY:
        raise HTTPException(403, "this deployment is read-only")


def _client_or_404(slug: str) -> str:
    if slug not in db.client_slugs():
        raise HTTPException(404, f"no private graph for {slug} yet")
    return slug


def _thresholds() -> dict:
    return {
        "rare": config.RARE,
        "flag_risk": config.FLAG_RISK,
        "differentiate": config.DIFFERENTIATE_CONFLICT,
        "borderline": config.BORDERLINE_CONFLICT,
    }


def _studio_context(businesses: list[dict]) -> tuple[list[dict], list[dict]]:
    client_slugs = db.client_slugs()
    client_data = {}
    for slug in client_slugs:
        client_data[slug] = {
            "business": tools.business(slug),
            "goals": tools.goals(slug),
            "pitches": tools.pitches(slug),
            "drafts": tools.drafts(slug),
            "flags": tools.collision_flags(slug),
        }

    clients = [
        {
            "id": slug,
            "name": data["business"]["name"],
            "category": data["business"]["category"],
            "neighborhood": data["business"].get("neighborhood", ""),
            "goals": [goal for goal in data["goals"] if goal.get("status") == "active"],
            "won_pitch": next(
                (
                    {"id": pitch["id"], "angle": pitch["angle"]}
                    for pitch in data["pitches"]
                    if pitch.get("status") in ("approved", "signed")
                ),
                None,
            ),
        }
        for slug, data in client_data.items()
        if data["business"].get("status") == "signed"
    ]

    needs_you = []
    for business in businesses:
        if business.get("status") == "lead" and business.get("verdict") == "borderline":
            needs_you.append({
                "type": "borderline",
                "business_id": business["id"],
                "message": f"Decide whether to pursue {business['name']}",
            })

    verdict_order = {"pursue": 0, "pursue_differentiated": 1}
    ready_ids = [
        business["id"]
        for business in sorted(
            (
                business for business in businesses
                if business.get("status") == "lead"
                and business.get("verdict") in verdict_order
            ),
            key=lambda business: (verdict_order[business["verdict"]], business["name"]),
        )
    ]
    if ready_ids:
        count = len(ready_ids)
        needs_you.append({
            "type": "ready",
            "business_ids": ready_ids,
            "business_id": ready_ids[0],
            "message": f"{count} screened {'lead is' if count == 1 else 'leads are'} cleared to pitch",
        })

    for slug, data in client_data.items():
        business = data["business"]
        for pitch in data["pitches"]:
            if pitch.get("status") == "draft":
                needs_you.append({
                    "type": "pitch",
                    "business_id": slug,
                    "pitch_id": pitch["id"],
                    "message": f"Approve or veto the pitch for {business['name']}",
                })

    for slug, data in client_data.items():
        business = data["business"]
        queued_ids = [draft["id"] for draft in data["drafts"] if draft.get("status") == "queued"]
        if queued_ids:
            count = len(queued_ids)
            needs_you.append({
                "type": "approve_posts",
                "business_id": slug,
                "business": business["name"],
                "draft_ids": queued_ids,
                "message": f"{count} {business['name']} {'post' if count == 1 else 'posts'} cleared Double Take and need your approval",
            })

    for slug, data in client_data.items():
        business = data["business"]
        drafts = {draft["id"]: draft for draft in data["drafts"]}
        by_draft: dict[str, list[dict]] = {}
        for flag in data["flags"]:
            by_draft.setdefault(flag["draft"], []).append(flag)
        for draft_id, flags in by_draft.items():
            draft = drafts.get(draft_id)
            if not draft or draft.get("status") != "flagged":
                continue
            flag = flags[0]
            needs_you.append({
                "type": "blocked",
                "business_id": slug,
                "business": business["name"],
                "with_business": flag["with_business"],
                "with_business_id": flag.get("with_business_id"),
                "also_like": [f["with_business"] for f in flags[1:]],
                "risk": max(float(f.get("risk") or 0) for f in flags),
                "shared": flag.get("shared", []),
                "hook": draft.get("hook", ""),
                "draft_id": draft_id,
                "message": f"{business['name']}'s draft looked like {flag['with_business']}'s work to the same people. Revised.",
            })

    for business in businesses:
        if business.get("status") == "lead" and not business.get("verdict"):
            needs_you.append({
                "type": "unscreened",
                "business_id": business["id"],
                "message": f"Screen {business['name']}",
            })

    return clients, needs_you


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/analysis")
def analysis_page():
    return FileResponse(STATIC / "index.html")


@app.get("/api/overview")
def overview():
    w = tools.world()
    g = db.agency()
    businesses = tools.pipeline_board()
    clients, needs_you = _studio_context(businesses)
    return {
        "agency": w["agency"]["name"],
        "mode": MODE,
        "readonly": READONLY,
        "video_url": VIDEO_URL,
        "day": tools.sim_day(),
        "date": tools.sim_date(),
        "businesses": businesses,
        "clients": clients,
        "needs_you": needs_you,
        "agents": db.rows(g, "MATCH (a:Agent) RETURN a.id AS id, a.name AS name, a.desk AS desk ORDER BY a.name"),
        "audiences": db.rows(g, "MATCH (a:Audience) RETURN a.id AS id, a.name AS name ORDER BY id"),
        "neighborhoods": db.rows(g, "MATCH (n:Neighborhood) RETURN n.id AS id, n.name AS name ORDER BY n.name"),
        "graphs": db.list_graphs(),
        "steps": [{"id": s, "label": l, "done": s in _done} for s, l in STEPS],
        "log": _log[-60:],
        "thresholds": _thresholds(),
    }


@app.post("/api/next-day")
def next_day():
    _writable()
    if not _lock.acquire(blocking=False):
        raise HTTPException(409, "agents are busy")
    try:
        try:
            return loop.next_day(log=_log.append)
        except Exception as e:
            _log.append(f"ERROR in next day: {e}")
            raise HTTPException(500, str(e))
    finally:
        _lock.release()


@app.get("/api/activity")
def activity():
    w = tools.world()
    current_day = tools.sim_day()
    existing = {row["id"] for row in db.rows(db.agency(), "MATCH (b:Business) RETURN b.id AS id")}
    feed_left = [
        {key: business[key] for key in ("id", "name", "category", "arrives")}
        for business in w.get("lead_feed", [])
        if business["id"] not in existing
    ]

    names = {row["id"]: row["name"] for row in db.rows(db.agency(), "MATCH (b:Business) RETURN b.id AS id, b.name AS name")}
    decisions = [*tools.decisions(None, 500)]
    for slug in db.client_slugs():
        decisions.extend({**d, "business_ids": d.get("business_ids") or [slug]} for d in tools.decisions(slug, 500))

    unique = {}
    for decision in decisions:
        business_ids = decision.get("business_ids") or []
        business_id = business_ids[0] if business_ids else None
        key = (decision["day"], decision["by"], decision["text"], decision["rationale"], business_id)
        unique.setdefault(key, {
            "day": decision["day"],
            "agent": decision["by"],
            "text": re.sub(r"\b[a-z0-9]+(?:-[a-z0-9]+)+\b", lambda m: names.get(m.group(0), m.group(0)), decision["text"]),
            "rationale": decision["rationale"],
            "business_id": business_id,
            "at": decision["at"],
        })

    by_day: dict[int, list[dict]] = {}
    for entry in unique.values():
        by_day.setdefault(entry["day"], []).append(entry)
    days = [
        {
            "day": day,
            "date": tools.sim_date(day),
            "entries": sorted(entries, key=lambda entry: entry["at"], reverse=True),
        }
        for day, entries in sorted(by_day.items(), reverse=True)
    ]
    return {
        "day": current_day,
        "date": tools.sim_date(current_day),
        "feed_left": feed_left,
        "can_advance": not READONLY,
        "days": days,
    }


@app.get("/api/analysis")
def analysis():
    graph_names = db.list_graphs()
    graphs = []
    for name in graph_names:
        g = db.graph(name)
        nodes = db.rows(g, "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS c")
        edges = db.rows(g, "MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS c")
        graphs.append({
            "name": name,
            "nodes": {str(row["label"] or "Unlabeled"): row["c"] for row in nodes},
            "edges": {row["t"]: row["c"] for row in edges},
        })

    agency = db.agency()
    screening = []
    for business in db.rows(agency, """MATCH (b:Business)-[:LOCATED_IN]->(n:Neighborhood)
                                       WHERE b.status <> 'signed'
                                       RETURN b.id AS id, b.name AS name, b.category AS category,
                                              b.status AS status, n.name AS neighborhood
                                       ORDER BY b.name"""):
        screening.append({**business, **tools.lead_conflict(business["id"])})

    double_take = []
    for slug in db.client_slugs():
        business = tools.business(slug)
        drafts = {draft["id"]: draft for draft in tools.drafts(slug)}
        for flag in tools.collision_flags(slug):
            draft = drafts.get(flag["draft"], {})
            double_take.append({
                **flag,
                "client_id": slug,
                "client": business["name"],
                "draft_hook": draft.get("hook", ""),
                "draft_status": draft.get("status", ""),
                "flag_risk": config.FLAG_RISK,
            })

    cleared_checks = 0
    for name in graph_names:
        rows = db.rows(db.graph(name), """MATCH (d:Decision)
                                         WHERE d.text STARTS WITH $prefix
                                         RETURN count(d) AS count""",
                       {"prefix": "Double Take: cleared"})
        cleared_checks += rows[0]["count"]

    queries_by_label = {
        name: value for name, value in vars(queries).items()
        if isinstance(value, str)
    }
    named_queries = []
    for tool in registry.TOOLS:
        if not tool.query:
            continue
        cypher = [
            {"constant": name, "text": value}
            for name, value in queries_by_label.items()
            if name.startswith(f"{tool.query}_")
        ]
        named_queries.append({
            "query": tool.query,
            "tool": tool.name,
            "description": tool.description,
            "agents": tool.agents,
            "cypher": cypher,
        })

    agents = {}
    for tool in registry.TOOLS:
        for agent in tool.agents:
            agents.setdefault(agent, []).append(tool.name)

    # The audience graph Q1 walks: who targets which audience, and which audiences overlap.
    audience_graph = {
        "audiences": db.rows(agency, "MATCH (a:Audience) RETURN a.id AS id, a.name AS name ORDER BY a.id"),
        "overlaps": db.rows(agency, """MATCH (a:Audience)-[o:OVERLAPS]->(b:Audience)
                                       RETURN a.id AS a, b.id AS b, o.share AS share"""),
        "targets": db.rows(agency, """MATCH (b:Business)-[t:TARGETS]->(a:Audience)
                                      RETURN b.id AS business_id, a.id AS audience_id, t.weight AS weight"""),
    }

    return {
        "audience_graph": audience_graph,
        "graphs": graphs,
        "screening": screening,
        "double_take": double_take,
        "cleared_checks": cleared_checks,
        "signatures": tools.signatures(),
        "queries": named_queries,
        "agents": agents,
        "thresholds": _thresholds(),
    }


@app.post("/api/step/{step}")
def step(step: str):
    _writable()
    if step not in dict(STEPS):
        raise HTTPException(404, step)
    if not _lock.acquire(blocking=False):
        raise HTTPException(409, "agents are busy")
    try:
        if step != "reset" and step in _done:
            raise HTTPException(409, "already ran; reset first")
        if step != "reset" and step not in _done:
            i = next(i for i, (step_id, _) in enumerate(STEPS) if step_id == step)
            prev_id = STEPS[i - 1][0]
            if prev_id not in _done:
                raise HTTPException(409, f"Run step {i - 1} ({prev_id}) first")
        if step == "reset":
            _log.clear()
            _done.clear()
        p = Pipeline(MODE, log=_log.append)
        try:
            run_step(p, step)
        except Exception as e:
            _log.append(f"ERROR in {step}: {e}")
            raise HTTPException(500, str(e))
        _done.append(step)
    finally:
        _lock.release()
    return {"ok": True, "log": _log[-30:]}


@app.get("/api/business/{slug}")
def business(slug: str):
    b = tools.business(slug)
    out = {"business": b, "audiences": tools.audiences_of(slug), "screening": tools.screening_card(slug),
           "signatures": tools.signatures(slug), "has_graph": slug in db.client_slugs()}
    if out["has_graph"]:
        out.update({
            "goals": tools.goals(slug),
            "findings": tools.findings(slug),
            "posts": tools.posts(slug),
            "taste_profile": tools.taste_profile(slug),
            "drafts": tools.drafts(slug),
            "flags": tools.collision_flags(slug),
            "pitches": tools.pitches(slug),
            "stale": tools.stale_drafts(slug),
            "decisions": tools.decisions(slug, 60),
        })
    return out


@app.get("/api/route/{slug}/{draft_id}")
def route_card(slug: str, draft_id: str):
    card = tools.decision_trace(_client_or_404(slug), draft_id)
    if not card:
        raise HTTPException(404, draft_id)
    return card


@app.get("/api/doubletake/{slug}/{draft_id}")
def doubletake_detail(slug: str, draft_id: str):
    slug = _client_or_404(slug)
    drafts = tools.drafts(slug)
    draft = next((item for item in drafts if item["id"] == draft_id), None)
    if not draft:
        raise HTTPException(404, draft_id)

    flags = tools.collision_flags(slug, draft_id)
    all_technique_ids = {technique_id for technique_id in draft["techniques"] if technique_id}
    for flag in flags:
        all_technique_ids.update(technique_id for technique_id in (flag.get("shared_ids") or []) if technique_id)
    technique_rows = tools.techniques(sorted(all_technique_ids))
    technique_by_id = {item["id"]: item for item in technique_rows}
    reference_counts = tools.reference_counts(sorted(all_technique_ids))

    def technique_list(ids, signature_shares=None, include_signature=False):
        result = []
        for technique_id in ids:
            technique = technique_by_id.get(technique_id)
            if not technique:
                continue
            item = {
                "id": technique_id,
                "name": technique["name"],
                "rarity": technique["rarity"],
            }
            if include_signature:
                item["ref_count"] = reference_counts.get(technique_id, 0)
                item["signature_share"] = (signature_shares or {}).get(technique_id)
            result.append(item)
        return result

    revision_row = next((item for item in drafts if item.get("revision_of") == draft_id), None)
    revision_trace = tools.decision_trace(slug, revision_row["id"]) if revision_row else {}
    revision_clear = bool(revision_row and any(
        item.get("decision") == "Double Take: cleared"
        for item in revision_trace.get("decisions", [])
    ))
    revision = None
    if revision_row:
        revision = {
            "id": revision_row["id"],
            "hook": revision_row["hook"],
            "status": "cleared" if revision_clear else revision_row["status"],
            "techniques": technique_list(revision_row["techniques"], None),
            "cleared": revision_clear,
        }

    decisions = []
    for trace in (tools.decision_trace(slug, draft_id), revision_trace):
        decisions.extend(
            {"by": item.get("by"), "text": item["decision"], "rationale": item.get("rationale"), "at": item.get("at")}
            for item in trace.get("decisions", [])
            if item.get("decision")
        )
    decisions = sorted(
        {(item["by"], item["text"], item["rationale"], item["at"]): item for item in decisions}.values(),
        key=lambda item: item["at"] or "",
    )

    flag_details = []
    for flag in flags:
        other_id = flag["with_business_id"]
        other = tools.business(other_id)
        other_signatures = {
            item["technique_id"]: item["share"] for item in tools.signatures(other_id)
        }
        shared_ids = flag.get("shared_ids") or []
        evidence_records = flag.get("evidence") or []
        world_business = next(
            (item for item in tools.world()["businesses"] if item["id"] == other_id),
            {},
        )
        client_posts = tools.posts(other_id) if other_id in db.client_slugs() else []
        post_records = {item["id"]: item for item in [*world_business.get("posts", []), *client_posts]}
        posts_by_id = post_records.copy()
        other_drafts = tools.drafts(other_id) if other_id in db.client_slugs() else []
        drafts_by_id = {item["id"]: item for item in other_drafts}
        evidence = []
        for item in evidence_records:
            evidence_id = item.get("fingerprint")
            source = posts_by_id.get(evidence_id) or drafts_by_id.get(evidence_id)
            if not source or not source.get("hook"):
                continue
            evidence.append({
                "post_id": evidence_id,
                "hook": source["hook"],
                "views": source.get("views"),
            })
        audience_by_id = {}
        for audience in tools.audience_paths(slug, other_id):
            audience_id = audience["id"]
            path = list(audience.get("path") or [])
            merged = audience_by_id.setdefault(audience_id, {
                "id": audience_id,
                "name": audience["name"],
                "mine": None,
                "theirs": None,
                "path": path,
                "paths": [],
            })
            if path and path not in merged["paths"]:
                merged["paths"].append(path)
            for weight in ("mine", "theirs"):
                value = audience.get(weight)
                if value is not None and (merged[weight] is None or value > merged[weight]):
                    merged[weight] = value
        flag_details.append({
            "business": {"id": other_id, "name": other["name"], "status": other["status"]},
            "shared": technique_list(shared_ids, other_signatures, include_signature=True),
            "evidence": evidence,
            "evidence_total_posts": len(post_records),
            "audiences": sorted(audience_by_id.values(), key=lambda audience: audience["id"]),
            "similarity": flag["similarity"],
            "overlap": flag["overlap"],
            "risk": flag["risk"],
            "limit": config.FLAG_RISK,
        })

    later_blocks = []
    revision_ids = {technique_id for technique_id in revision_row["techniques"] if technique_id} if revision_row else set()
    revision_names = {technique_by_id[technique_id]["name"] for technique_id in revision_ids if technique_id in technique_by_id}
    for other_client in db.client_slugs():
        if other_client == slug:
            continue
        other_client_drafts = {item["id"]: item for item in tools.drafts(other_client)}
        for flag in tools.collision_flags(other_client):
            shared_names = set(flag.get("shared") or [])
            if flag.get("with_business_id") != slug or not shared_names.intersection(revision_names):
                continue
            blocked = other_client_drafts.get(flag["draft"], {})
            client_business = tools.business(other_client)
            later_blocks.append({
                "client_id": other_client,
                "client": client_business["name"],
                "draft_id": flag["draft"],
                "hook": blocked.get("hook"),
                "shared": flag.get("shared") or [],
                "risk": flag["risk"],
            })

    business = tools.business(slug)
    return {
        "draft": {
            "id": draft["id"],
            "hook": draft["hook"],
            "version": draft["version"],
            "status": draft["status"],
            "techniques": technique_list(draft["techniques"], None),
        },
        "business": {"id": slug, "name": business["name"], "status": business["status"]},
        "flags": flag_details,
        "revision": revision,
        "query": {"name": "double_take", "cypher": queries.Q2_DOUBLE_TAKE},
        "reference_total": tools.reference_total(),
        "next": decisions,
        "later_blocks": later_blocks,
    }


@app.get("/api/pitch/{slug}/{pitch_id}")
def pitch_card(slug: str, pitch_id: str):
    card = tools.pitch_trace(_client_or_404(slug), pitch_id)
    if not card:
        raise HTTPException(404, pitch_id)
    return card


@app.get("/api/decisions")
def decisions():
    rows = [dict(r, graph="agency") for r in tools.decisions(None, 40)]
    for s in db.client_slugs():
        rows += [dict(r, graph=f"client:{s}") for r in tools.decisions(s, 40)]
    return sorted(rows, key=lambda r: r["at"], reverse=True)[:80]


class BoardIn(BaseModel):
    verdict: str = Field(pattern="^(approve|veto)$")
    note: str = Field(default="", max_length=500)


class LeadDecisionIn(BaseModel):
    verdict: str = Field(pattern="^(pursue|pass)$")
    note: str = Field(default="", max_length=500)


@app.post("/api/board/{slug}/{label}/{target_id}")
def board(slug: str, label: str, target_id: str, body: BoardIn):
    _writable()
    if label not in ("Pitch", "Draft"):
        raise HTTPException(400, label)
    return tools.board_decide(
        _client_or_404(slug), label, target_id, body.verdict,
        body.note or f"Board {body.verdict}.", source="web_board",
    )


@app.post("/api/lead/{slug}/decide")
def decide_lead(slug: str, body: LeadDecisionIn):
    _writable()
    business = next((b for b in tools.pipeline_board() if b["id"] == slug), None)
    if not business:
        raise HTTPException(404, slug)
    if business.get("status") != "lead" or business.get("verdict") != "borderline":
        raise HTTPException(400, "only borderline leads can be decided by the board")
    if body.verdict == "pursue":
        return tools.pursue(slug, agent="board", rationale=body.note or "Board: pursue.", source="web_board")
    return tools.set_status(slug, "passed", "board", body.note or "Board: pass.", source="web_board")


@app.post("/api/retire/{slug}/{goal_id}")
def retire(slug: str, goal_id: str):
    _writable()
    return tools.retire_goal(
        _client_or_404(slug), goal_id, "board", "Retired from the board view.", source="web_board",
    )


# ------------------------------------------------------------------ try it: outsider inputs

class LeadIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    category: str = Field(min_length=2, max_length=60)
    targets: dict[str, float]
    neighborhood: str = "n_flatiron"
    preview: bool = False


@app.post("/api/try/lead")
def try_lead(body: LeadIn):
    """Screen a new lead live with Q1; persist it only when the deployment is writable."""
    neighborhoods = {n["id"] for n in db.rows(db.agency(), "MATCH (n:Neighborhood) RETURN n.id AS id")}
    if body.neighborhood not in neighborhoods:
        raise HTTPException(400, "unknown neighborhood")
    valid = {a["id"] for a in db.rows(db.agency(), "MATCH (a:Audience) RETURN a.id AS id")}
    targets = {k: max(0.0, min(1.0, float(v))) for k, v in body.targets.items() if k in valid and float(v) > 0}
    if not targets:
        raise HTTPException(400, "pick at least one audience")
    preview = READONLY or body.preview
    slug = f"try-{os.urandom(4).hex()}" if preview else (
        "try-" + (re.sub(r"[^a-z0-9]+", "-", body.name.lower()).strip("-")[:40] or "lead")
    )
    if preview:
        return {**tools.lead_conflict_preview(slug, body.category, body.neighborhood, targets), "saved": False}

    g = db.agency()
    create_query = """MATCH (n:Neighborhood {id: $neighborhood})
                      CREATE (b:Business {id: $id, name: $name, category: $category, status: 'lead', synthetic: true, user_added: true})-[:LOCATED_IN]->(n)
                      WITH b UNWIND $targets AS t MATCH (a:Audience {id: t.aud}) CREATE (b)-[:TARGETS {weight: t.w}]->(a)"""
    params = {"id": slug, "name": body.name, "category": body.category, "neighborhood": body.neighborhood,
              "targets": [{"aud": k, "w": v} for k, v in targets.items()]}
    db.run(g, "MATCH (b:Business {id: $id}) DETACH DELETE b", {"id": slug})
    db.run(g, create_query, params)
    return {**tools.screen_lead(slug), "saved": True}


class DraftIn(BaseModel):
    client: str
    technique_ids: list[str] = Field(min_length=1, max_length=12)


@app.post("/api/try/draft")
def try_draft(body: DraftIn):
    """Double Take on a hypothetical draft, read only: project a temporary fingerprint, run Q2, delete it."""
    tools.business(body.client)
    fid = f"try-{os.urandom(4).hex()}"
    g = db.agency()
    db.run(g, queries.P1_PROJECT_FINGERPRINT, {"draft_id": fid, "kind": "draft", "client": body.client,
                                                "now": tools.now(), "technique_ids": body.technique_ids})
    try:
        results = tools.double_take(body.client, fid)
    finally:
        db.run(g, "MATCH (f:Fingerprint {id: $id}) DETACH DELETE f", {"id": fid})
    return {"results": results, "flagged": any(r["flag"] for r in results), "threshold": config.FLAG_RISK}


@app.get("/api/techniques")
def all_techniques():
    return db.rows(db.agency(), """MATCH (t:Technique)-[:PART_OF]->(s:Style)
                                   RETURN t.id AS id, t.name AS name, t.category AS category, t.rarity AS rarity,
                                          t.ref_count AS ref_count, s.name AS style ORDER BY style, rarity DESC""")


@app.get("/api/territory")
def territory():
    """Each business's techniques (active fingerprints), for the territory map."""
    return db.rows(db.agency(), """MATCH (b:Business)<-[:OF]-(f:Fingerprint)-[:USES]->(t:Technique)
                                   WHERE f.active AND b.status IN ['signed', 'pursued', 'pitched']
                                   RETURN b.id AS business, b.name AS name, b.status AS status,
                                          t.id AS technique, t.rarity AS rarity, count(f) AS uses""")
