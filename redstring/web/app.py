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

from .. import config, db, queries, registry, tools
from ..pipeline import STEPS, Pipeline, run_step

STATIC = Path(__file__).parent / "static"
MODE = os.environ.get("REDSTRING_MODE", "offline")
# On a public link, REDSTRING_READONLY=1 keeps visitors from resetting the demo or acting as the board.
# The two "try it" inputs still work: they add only synthetic leads and temporary fingerprints.
READONLY = os.environ.get("REDSTRING_READONLY") == "1"

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
                "message": f"Board call: decide whether to pursue {business['name']}",
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
        drafts = {draft["id"]: draft for draft in data["drafts"]}
        seen = set()
        for flag in data["flags"]:
            draft_id = flag["draft"]
            if draft_id in seen:
                continue
            seen.add(draft_id)
            draft = drafts.get(draft_id)
            if not draft or draft.get("status") != "flagged":
                continue
            needs_you.append({
                "type": "blocked",
                "business_id": slug,
                "draft_id": draft_id,
                "message": f"{business['name']}'s draft looked like {flag['with_business']}'s work to the same parents. Revised.",
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

    return {
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
    with _lock:
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


@app.post("/api/board/{slug}/{label}/{target_id}")
def board(slug: str, label: str, target_id: str, body: BoardIn):
    _writable()
    if label not in ("Pitch", "Draft"):
        raise HTTPException(400, label)
    return tools.board_decide(_client_or_404(slug), label, target_id, body.verdict, body.note or f"Board {body.verdict}.")


@app.post("/api/retire/{slug}/{goal_id}")
def retire(slug: str, goal_id: str):
    _writable()
    return tools.retire_goal(_client_or_404(slug), goal_id, "board", "Retired from the board view.")


# ------------------------------------------------------------------ try it: outsider inputs

class LeadIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    category: str = Field(min_length=2, max_length=60)
    targets: dict[str, float]
    neighborhood: str = "n_flatiron"


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
    readonly = READONLY
    slug = f"try-{os.urandom(4).hex()}" if readonly else (
        "try-" + (re.sub(r"[^a-z0-9]+", "-", body.name.lower()).strip("-")[:40] or "lead")
    )
    g = db.agency()
    create_query = """MATCH (n:Neighborhood {id: $neighborhood})
                      CREATE (b:Business {id: $id, name: $name, category: $category, status: 'lead', synthetic: true, user_added: true})-[:LOCATED_IN]->(n)
                      WITH b UNWIND $targets AS t MATCH (a:Audience {id: t.aud}) CREATE (b)-[:TARGETS {weight: t.w}]->(a)"""
    params = {"id": slug, "name": body.name, "category": body.category, "neighborhood": body.neighborhood,
              "targets": [{"aud": k, "w": v} for k, v in targets.items()]}
    if readonly:
        try:
            db.run(g, create_query, params)
            res = tools.lead_conflict(slug)
        finally:
            db.run(g, "MATCH (b:Business {id: $id}) DETACH DELETE b", {"id": slug})
        return {**res, "saved": False}
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
