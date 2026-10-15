"""Deterministic agents. Same tools, same graph writes as the Claude agents, no model calls.

They make the demo reproducible and runnable with no API key. Text they write is templated from the
graph; every number in it comes from a query.
"""
from __future__ import annotations

import json
from statistics import mean

from .. import config, registry, tools

# Hooks for the demo's spec posts and drafts, keyed by (client, slot, version).
HOOKS = {
    ("tumble-town", 1, 1): "Three, two, one... cartwheel.",
    ("tumble-town", 2, 1): "One handstand, 40 frames, a chalk-smear wipe between each.",
    ("tumble-town", 2, 2): "Week 1 vs week 8, cut on every beat.",
    ("tumble-town", 3, 1): "The balance beam challenge, ages 5 to 10.",
    ("treble-clef", 1, 1): "Our whole recital in 15 seconds, spinning.",
    ("treble-clef", 1, 2): "What does a cello sound like from inside the case?",
    ("treble-clef", 2, 1): "A tiny violinist plays three notes. Guess the song.",
    ("treble-clef", 3, 1): "Twinkle Twinkle, played backwards, then forwards.",
    ("cannonball", 1, 1): "Bubbles first: a stop-motion guide to breathing out underwater.",
    ("cannonball", 1, 2): "Swipe through: the five steps of a calm first lesson.",
    ("pixel-pond", 1, 1): "Bug report: the robot that refused to turn left.",
    ("pixel-pond", 2, 1): "Spring robotics, explained in one freeze frame per week.",
}


def _names(ids):
    return {t["id"]: t for t in tools.techniques(ids)}


def _spec_text(technique_ids: list[str], voice: str) -> str:
    t = _names(technique_ids)
    by = {}
    for tid in technique_ids:
        by.setdefault(t[tid]["category"], []).append(t[tid]["name"])
    parts = [f"{cat.capitalize()}: {', '.join(v)}." for cat, v in by.items()]
    return f"Voice: {voice}. " + " ".join(parts)


# ------------------------------------------------------------------ Scout

def scout(leads: list[str], pursue: list[str]) -> list[dict]:
    out = []
    for lead in leads:
        res = tools.screen_lead(lead)
        out.append(res)
    for slug in pursue:
        verdict = next(r for r in out if r["lead"] == slug)
        tools.pursue(slug, "scout", f"Verdict {verdict['verdict']}: {verdict['reason']}")
    return out


# ------------------------------------------------------------------ Researcher

def researcher(client: str) -> dict:
    path = config.RESEARCH_CACHE / f"{client}.json"
    fids = []
    if path.exists():
        cache = json.loads(path.read_text())
        for f in cache["findings"]:
            fids.append(tools.record_finding(client, f["kind"], f["text"], f["source_url"], "researcher",
                                             f"From {f.get('source_title') or f['source_url']}")["finding"])
    else:
        aud = tools.audiences_of(client)
        fids.append(tools.record_finding(
            client, "audience",
            f"Targets {', '.join(a['audience'] for a in aud)}. [offline placeholder: no cached research; run with an API key for live web research]",
            None, "researcher", "Placeholder finding, labeled as such.")["finding"])
    w = tools.world()
    b = next(x for x in w["businesses"] if x["id"] == client)
    g = b.get("hypothesized_goal") or b["goal"]
    status = "hypothesized" if b["status"] != "signed" else "active"
    goal = tools.record_goal(client, g["text"], g["metric"], g["target"], g["due"], status, fids, "researcher",
                             f"Inferred from {len(fids)} findings on the category and audience; shown in the pitch as a hypothesis.")
    return {"findings": fids, "goal": goal["goal"]}


# ------------------------------------------------------------------ Auditor

def auditor(client: str) -> dict:
    if not tools.posts(client):
        tools.load_client_posts(client)
    ps = tools.posts(client)
    for p in ps:
        p["save_rate"] = p["saves"] / max(1, p["views"])
    names = _names(sorted({t for p in ps for t in p["techniques"]}))
    best = max(ps, key=lambda p: p["views"])
    worst = min(ps, key=lambda p: p["views"])
    avg_views = mean(p["views"] for p in ps)
    worst_hooks = [t for t in worst["techniques"] if names[t]["category"] == "hook"]
    shared_top = set.intersection(*[set(p["techniques"]) for p in sorted(ps, key=lambda p: -p["views"])[:3]])
    found = [
        {"text": f"Best post: \"{best['hook']}\" with {best['views']:,} views ({best['save_rate']:.1%} saves), "
                 f"{best['views'] / avg_views:.1f}x the average of {avg_views:,.0f}."
                 + (f" The top three posts share {', '.join(names[t]['name'] for t in shared_top)}." if shared_top else "")},
        {"text": f"Weakest post: \"{worst['hook']}\" with {worst['views']:,} views ({worst['save_rate']:.1%} saves)."
                 + (" It has no hook technique in the opening seconds." if not worst_hooks else
                    f" Its hook is {names[worst_hooks[0]]['name']}.")},
    ]
    rare_used = sorted({t for p in ps for t in p["techniques"] if names[t]["rarity"] >= config.RARE},
                       key=lambda t: -names[t]["rarity"])
    if rare_used:
        found.append({"text": f"Distinctive moves already in the history: {', '.join(names[t]['name'] for t in rare_used[:4])}."})
    summary = f"Reviewed {len(ps)} posts. Average {avg_views:,.0f} views; best {best['views']:,}, weakest {worst['views']:,}."
    return tools.record_audit(client, summary, [p["id"] for p in ps], found)


# ------------------------------------------------------------------ Style Director

def style_director(client: str, flag: dict | None = None) -> dict:
    style = registry._style_of(client)["primary_style"]
    avoid = list(flag["shared_ids"]) if flag else []
    prev = tools.taste_profile(client)
    if prev:
        avoid = sorted(set(avoid) | {a["id"] for a in prev["avoids"]})
    territory = tools.open_territory(client, style, avoid)
    prefers = {t["technique_id"]: round(min(1.0, 0.4 + t["rarity"] / 2), 2) for t in territory[:6]}
    audit = tools.findings(client, "audit")
    if flag:
        summary = (f"Revised after Double Take: avoid {', '.join(flag['shared'])} ({flag['with_business']}'s territory). "
                   f"Open territory in {style}: {', '.join(t['technique'] for t in territory[:3])}.")
        based = [("CollisionFlag", flag["id"])]
    else:
        summary = f"Home style {style}. Rarest open techniques: {', '.join(t['technique'] for t in territory[:3])}."
        based = [("Finding", f["id"]) for f in audit]
    return tools.set_taste_profile(client, prefers, avoid, summary, based)


# ------------------------------------------------------------------ Strategist

def strategist(client: str, period: str) -> dict:
    gs = [g for g in tools.goals(client) if g["status"] in ("active", "hypothesized")]
    goal = gs[-1]
    tp = tools.taste_profile(client)
    rationale = (f"Serves \"{goal['text']}\" ({goal['status']}). "
                 f"Leans on {', '.join(p['name'] for p in tp['prefers'][:3])} from the taste profile." if tp else
                 f"Serves \"{goal['text']}\".")
    return {**tools.write_plan(client, period, goal["id"], rationale), "goal": goal["id"]}


# ------------------------------------------------------------------ Producer

def producer(client: str, plan_id: str, slot: int, technique_ids: list[str], kind: str,
             revision_of: str | None = None, version: int = 1) -> dict:
    voice = registry._style_of(client)["voice"]
    hook = HOOKS.get((client, slot, version)) or f"{tools.business(client)['name']}, take {version}"
    refs = tools.references_for(technique_ids, 2)
    audience = [f["id"] for f in tools.findings(client, "audience")][:2]
    rationale = (f"Built on {', '.join(t['name'] for t in tools.techniques(technique_ids)[:3])}; "
                 f"inspired by {', '.join(r['id'] for r in refs) or 'no references'}.")
    if revision_of:
        rationale = "Revision from open territory after a Double Take block. " + rationale
    return registry._draft(client, plan_id, "reel", hook, _spec_text(technique_ids, voice), technique_ids,
                           [r["id"] for r in refs], rationale, kind=kind, revision_of=revision_of,
                           based_on_findings=audience)


def revise_techniques(client: str, old: list[str], flag: dict) -> list[str]:
    """Drop the flagged techniques, then fill from the taste profile's open territory."""
    tp = tools.taste_profile(client)
    avoid = {a["id"] for a in tp["avoids"]} | set(flag["shared_ids"])
    keep = [t for t in old if t not in avoid]
    for p in sorted(tp["prefers"], key=lambda p: -p["weight"]):
        if len(keep) >= len(old):
            break
        if p["id"] not in keep and p["id"] not in avoid:
            keep.append(p["id"])
    return keep


# ------------------------------------------------------------------ Standards

def standards(client: str, draft_id: str) -> dict:
    return tools.check_draft(client, draft_id)


# ------------------------------------------------------------------ Account Manager

def account_manager(client: str) -> dict:
    goal = next(g for g in tools.goals(client) if g["status"] in ("hypothesized", "active"))
    ds = [d for d in tools.drafts(client) if d["status"] in ("queued", "approved") and d["kind"] == "spec"]
    claims = tools.findings(client, "audience")[:3] + tools.findings(client, "channel")[:1] + tools.findings(client, "audit")[:2]
    b = tools.business(client)
    angle = (f"{b['name']}: three spec posts in territory no one else on your parents' feeds is using, "
             f"aimed at \"{goal['text']}\" (our hypothesis).")
    return tools.write_pitch(client, angle, [d["id"] for d in ds], [c["id"] for c in claims], goal["id"],
                             f"{len(claims)} cited findings, {len(ds)} spec posts that cleared Double Take.")
