"""The offline agency's human-gated day-by-day work loop."""
from __future__ import annotations

from . import config, db, queries, seed, tools
from .agents import offline
from .pipeline import Pipeline


def _say(log, message: str) -> None:
    if log:
        log(message)


def _arrive(world: dict, slug: str, log=None) -> None:
    business = seed.find_business(world, slug)
    g = db.agency()
    db.run(g, """MATCH (n:Neighborhood {id: $neighborhood})
                 CREATE (b:Business {id: $id, name: $name, category: $category, status: $status,
                                     voice: $voice, synthetic: true})-[:LOCATED_IN]->(n)
                 WITH b, $targets AS targets UNWIND targets AS t
                 MATCH (a:Audience {id: t.aud})
                 CREATE (b)-[:TARGETS {weight: t.w}]->(a)""",
           {"id": slug, "name": business["name"], "category": business["category"],
            "status": "lead", "voice": business["voice"], "neighborhood": business["neighborhood"],
            "targets": [{"aud": audience, "w": weight} for audience, weight in business["targets"].items()]})
    for post in business["posts"]:
        db.run(g, queries.P1_PROJECT_FINGERPRINT, {
            "draft_id": post["id"], "kind": "post", "client": slug,
            "now": post["posted_at"], "technique_ids": post["technique_ids"],
        })
    tools.derive_signatures()
    tools._decide(g, "scout", f"New lead: {business['name']}",
                  "Arrived in the studio's lead feed.", [("Business", slug)])
    _say(log, f"Scout: new lead {business['name']} arrived")


def _waiting_count() -> int:
    businesses = tools.pipeline_board()
    waiting = sum(
        business.get("status") == "lead" and business.get("verdict") == "borderline"
        for business in businesses
    )
    for slug in db.client_slugs():
        waiting += sum(pitch.get("status") == "draft" for pitch in tools.pitches(slug))
        waiting += bool(any(draft.get("status") == "queued" for draft in tools.drafts(slug)))
    return int(waiting)


def _new_plan(pipeline: Pipeline, client: str, day: int) -> str:
    tool_results: dict = {}
    result = pipeline._agent(
        "strategist",
        f"Write a plan for {client} with write_plan, period 'Day {day}', serving its active goal.",
        offline.strategist, client, f"Day {day}", tool_results=tool_results,
    )
    if isinstance(result, dict) and result.get("plan"):
        return result["plan"]
    return pipeline._tool_id(tool_results, "write_plan", "plan")


def _post_for_client(pipeline: Pipeline, client: str, day: int, log=None) -> dict:
    graph = db.client(client)
    plan_rows = db.rows(graph, "MATCH (p:Plan) RETURN p.id AS id ORDER BY p.at DESC LIMIT 1")
    plan_id = plan_rows[0]["id"] if plan_rows else _new_plan(pipeline, client, day)

    profile = tools.taste_profile(client)
    if not profile.get("prefers"):
        pipeline._agent(
            "style_director",
            f"Set {client}'s taste profile from open_territory for its home style.",
            offline.style_director, client,
        )
        profile = tools.taste_profile(client)
    preferences = [item["id"] for item in sorted(profile["prefers"], key=lambda item: -item["weight"])]
    if not preferences:
        raise ValueError(f"{client} has no techniques in its taste profile")

    non_revision_drafts = [
        draft for draft in tools.drafts(client)
        if not draft.get("revision_of")
    ]
    slot = len(non_revision_drafts) + 1
    width = min(5, len(preferences))
    start = (slot - 1) % len(preferences)
    technique_ids = [preferences[(start + offset) % len(preferences)] for offset in range(width)]
    chain = pipeline.produce_and_check(client, plan_id, slot, technique_ids, "draft")
    final = chain[-1]
    _say(log, f"Producer: {client} day {day} post {slot} is {final['status']}")
    return {"business": client, "slot": slot, "draft": final["draft"], "status": final["status"]}


def next_day(log=None) -> dict:
    world = tools.world()
    day = tools.sim_day() + 1
    with tools.sim_day_at(day):
        result = _run_day(world, day, log)
        tools.set_sim_day(day)
    return result


def _run_day(world: dict, day: int, log=None) -> dict:
    date = tools.sim_date(day)
    pipeline = Pipeline(mode=config.MODE, log=log)
    _say(log, f"Day {day} · {date}")

    arrived = []
    existing = {business["id"] for business in tools.pipeline_board()}
    for business in world.get("lead_feed", []):
        if business.get("arrives", 0) <= day and business["id"] not in existing:
            _arrive(world, business["id"], log)
            existing.add(business["id"])
            arrived.append(business["id"])

    screened = []
    for business in tools.pipeline_board():
        if business.get("status") == "lead" and not business.get("verdict"):
            result = tools.screen_lead(business["id"])
            screened.append(business["id"])
            _say(log, f"Scout: {business['name']} {result['verdict']} — {result['reason']}")

    pursued = []
    businesses = tools.pipeline_board()
    open_count = sum(business.get("status") in ("pursued", "pitched") for business in businesses)
    feed_arrivals = {business["id"]: business["arrives"] for business in world.get("lead_feed", [])}
    candidates = [
        business for business in businesses
        if business.get("status") == "lead"
        and not business["id"].startswith("try-")
        and business.get("verdict") in ("pursue", "pursue_differentiated")
        and feed_arrivals.get(business["id"], 0) < day
    ]
    candidates.sort(key=lambda business: (-feed_arrivals.get(business["id"], 0), business["name"]))
    if open_count < config.MAX_OPEN_PURSUITS and candidates:
        business = candidates[0]
        tools.pursue(business["id"], "scout", business.get("reason") or "Scout recommended pursuit.")
        pursued.append(business["id"])
        _say(log, f"Scout: pursued {business['name']}; {business.get('reason', '')}")

    advanced = []
    current = [b for b in tools.pipeline_board() if b.get("status") in ("pursued", "pitched")]
    for business in current:
        slug = business["id"]
        if slug in pursued:
            continue
        if business["status"] == "pursued":
            if not tools.findings(slug):
                pipeline.research(slug)
                stage = "research"
            elif not any(draft.get("kind") == "spec" for draft in tools.drafts(slug)):
                pipeline.spec_work(slug)
                stage = "spec"
            else:
                pipeline.pitch(slug)
                stage = "pitch"
            advanced.append({"business": slug, "stage": stage})
        else:
            approved = next((pitch for pitch in tools.pitches(slug) if pitch.get("status") == "approved"), None)
            if not approved:
                continue
            tools.set_status(slug, "signed", "account_manager", "Prospect accepted the approved pitch.")
            active_goals = [goal for goal in tools.goals(slug) if goal.get("status") == "active"]
            if not active_goals:
                hypothesis = next((goal for goal in tools.goals(slug) if goal.get("status") == "hypothesized"), None)
                if hypothesis:
                    tools.activate_goal(slug, hypothesis["id"])
            stage = "signed"
            advanced.append({"business": slug, "stage": stage})
            _say(log, f"Account Manager: {slug} signed after pitch approval")

    posted = []
    signed = sorted(
        business["id"] for business in tools.pipeline_board()
        if business.get("status") == "signed"
    )
    if signed:
        posted.append(_post_for_client(pipeline, signed[day % len(signed)], day, log))

    result = {
        "day": day,
        "date": date,
        "arrived": arrived,
        "screened": screened,
        "pursued": pursued,
        "advanced": advanced,
        "posted": posted,
        "waiting": _waiting_count(),
    }
    _say(log, f"Day {day} complete: {result['waiting']} items waiting on the board")
    return result
