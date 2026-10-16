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

from .. import config, db, queries, tools
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


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/overview")
def overview():
    w = tools.world()
    g = db.agency()
    return {
        "agency": w["agency"]["name"],
        "mode": MODE,
        "readonly": READONLY,
        "businesses": tools.pipeline_board(),
        "agents": db.rows(g, "MATCH (a:Agent) RETURN a.id AS id, a.name AS name, a.desk AS desk ORDER BY a.name"),
        "audiences": db.rows(g, "MATCH (a:Audience) RETURN a.id AS id, a.name AS name ORDER BY id"),
        "neighborhoods": db.rows(g, "MATCH (n:Neighborhood) RETURN n.id AS id, n.name AS name ORDER BY n.name"),
        "graphs": db.list_graphs(),
        "steps": [{"id": s, "label": l, "done": s in _done} for s, l in STEPS],
        "log": _log[-60:],
        "thresholds": {"rare": config.RARE, "flag_risk": config.FLAG_RISK,
                       "differentiate": config.DIFFERENTIATE_CONFLICT, "borderline": config.BORDERLINE_CONFLICT},
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
