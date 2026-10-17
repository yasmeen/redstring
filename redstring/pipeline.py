"""The pipeline: agents run in order, each reading what the last one wrote in the graph.

`mode="offline"` runs the deterministic agents (no API key). `mode="claude"` runs each step as a
Claude tool-use loop over the same named tools. Either way the pipeline reads outcomes from the graph,
never from model text, and the revision loop is the same:

    Producer drafts -> Standards flags -> Style Director pulls open territory -> Producer revises -> Standards re-checks
"""
from __future__ import annotations

from typing import Callable

import json

from . import config, seed, tools
from .agents import offline

MAX_ROUNDS = 3
Log = Callable[[str], None]


def _say(log: Log | None, msg: str) -> None:
    if log:
        log(msg)


class Pipeline:
    def __init__(self, mode: str = "offline", log: Log | None = print):
        self.mode = mode
        self.log = log
        if mode == "claude":
            from .agents import claude
            self.claude = claude
        self.w = tools.world()

    # -------------------------------------------------------------- agent dispatch

    def _agent(self, agent: str, task: str, offline_fn, *args, **kw):
        if self.mode == "claude":
            return self.claude.run_agent(agent, task, log=self.log)
        return offline_fn(*args, **kw)

    def _latest_draft(self, client: str) -> dict:
        return tools.drafts(client)[-1]

    # -------------------------------------------------------------- steps

    def reset(self) -> dict:
        tools._world_cache = None
        self.w = tools.world()
        out = seed.seed_all(self.w)
        _say(self.log, f"Seeded {out['agency']} and {', '.join(out['clients'])}")
        return out

    def screen(self) -> list[dict]:
        leads = [b["id"] for b in self.w["businesses"] if b["status"] == "lead"]
        pursue = self.w["demo"]["pursue"]
        if self.mode == "claude":
            self.claude.run_agent("scout", (
                f"Screen these leads one by one with lead_conflict and record each verdict with record_screening: {', '.join(leads)}. "
                f"Then pursue {', '.join(pursue)} (the agency has capacity for two pursuits this month), "
                f"giving each pursuit's rationale from its screening."), log=self.log)
            res = [tools.screening_card(lead) | {"lead": lead} for lead in leads]
        else:
            res = offline.scout(leads, pursue)
        for r in res:
            _say(self.log, f"Scout: {r['lead']:<14} {r.get('verdict') or 'not screened':<22} {r.get('reason', '')}")
        return res

    def research(self, client: str) -> dict:
        r = self._agent("researcher", (
            f"Research the category and audience for {client} on the public web. Record 4 to 6 findings with record_finding, "
            f"each with the exact source URL you read. Then record a hypothesized goal with record_goal based on those findings."),
            offline.researcher, client)
        a = self._agent("auditor", (
            f"Audit {client}'s past posts (call posts). Record one audit with record_audit with 3 findings: what worked, "
            f"what was weakest and why, and what is distinctive. Cite views and saves."),
            offline.auditor, client)
        cache = config.RESEARCH_CACHE / f"{client}.json"
        if self.mode == "claude" and not cache.exists():
            # Cache live research so later runs, and the demo, replay the same sourced findings.
            fs = [f for f in tools.findings(client) if f["kind"] != "audit"]
            cache.parent.mkdir(exist_ok=True)
            cache.write_text(json.dumps({"business": client, "researched_at": tools.now()[:10],
                                         "note": "Live research by the Researcher agent (web search).",
                                         "findings": [{k: f[k] for k in ("kind", "text", "source_url")} for f in fs]}, indent=1))
        _say(self.log, f"Researcher + Auditor filled client:{client}: {len(tools.findings(client))} findings, goal hypothesized")
        return {"research": r, "audit": a}

    def produce_and_check(self, client: str, plan_id: str, slot: int, technique_ids: list[str], kind: str) -> list[dict]:
        """One post through the revision loop. Returns the chain of versions with their Double Take results."""
        chain = []
        version, prev = 1, None
        while True:
            if self.mode == "claude":
                self.claude.run_agent("producer", (
                    f"Write {kind} post {slot} for {client} in plan {plan_id} with write_draft (kind {kind}). "
                    + (f"Use exactly these technique ids from the creative brief: {technique_ids}. " if version == 1 else
                       f"This revises draft {prev}: use exactly these technique ids from the new taste profile: {technique_ids}, "
                       f"and pass revision_of={prev}. ")
                    + "Pick 2 references with references_for, write the hook and a shot-by-shot spec in the client's voice."),
                    log=self.log)
                draft = self._latest_draft(client)["id"]
            else:
                draft = offline.producer(client, plan_id, slot, technique_ids, kind, revision_of=prev, version=version)["draft"]
            check = self._agent("standards", f"Run check_draft on {client} draft {draft}.", offline.standards, client, draft)
            status = next(d["status"] for d in tools.drafts(client) if d["id"] == draft)
            flags = tools.collision_flags(client, draft)
            chain.append({"draft": draft, "version": version, "status": status, "techniques": technique_ids, "flags": flags})
            if status != "flagged":
                if status == "queued":
                    _say(self.log, f"  Standards: {client} post {slot} v{version} cleared")
                else:
                    _say(self.log, f"  Standards: {client} post {slot} v{version} is {status}")
                return chain
            f = flags[0]
            _say(self.log, f"  Standards: {client} post {slot} v{version} BLOCKED, resembles {f['with_business']} "
                           f"({', '.join(f['shared'])}; risk {f['risk']:.2f})")
            if version >= MAX_ROUNDS:
                _say(self.log, "  Out of revision rounds; left for the board.")
                return chain
            self._agent("style_director", (
                f"Draft {draft} for {client} was blocked by CollisionFlag {f['id']} for sharing {f['shared_ids']} with "
                f"{f['with_business']}. Pull open_territory for the client's home style (style_of) with those ids in avoid, "
                f"and write a new taste profile version with set_taste_profile that avoids them, based_on_flags [{f['id']}]."),
                offline.style_director, client, f)
            technique_ids = offline.revise_techniques(client, technique_ids, f)
            prev, version = draft, version + 1

    def spec_work(self, client: str) -> dict:
        self._agent("style_director", (
            f"Set {client}'s first taste profile: read findings and style_of, pull open_territory for its home style, "
            f"and write set_taste_profile preferring the rarest open techniques. Base it on the audit findings."),
            offline.style_director, client)
        plan = self._agent("strategist", (
            f"Write a plan for {client} with write_plan, period 'Spec work: 3 posts + 30-day plan', serving its hypothesized goal."),
            offline.strategist, client, "Spec work: 3 posts + 30-day plan")
        plan_id = plan["plan"] if isinstance(plan, dict) and "plan" in plan else tools.db.rows(
            tools.db.client(client), "MATCH (p:Plan) RETURN p.id AS id ORDER BY p.at DESC LIMIT 1")[0]["id"]
        seeds = self.w["spec_seeds"].get(client, [])
        posts = []
        for i, s in enumerate(seeds, 1):
            posts.append(self.produce_and_check(client, plan_id, i, s["techniques"], "spec"))
        return {"plan": plan_id, "posts": posts}

    def pitch(self, client: str) -> dict:
        p = self._agent("account_manager", (
            f"Assemble {client}'s pitch with write_pitch: show every spec draft that cleared Double Take, cite the audience, "
            f"channel and audit findings it rests on (check each with decision_trace), and serve its hypothesized goal. "
            f"Name the goal as our hypothesis in the angle."),
            offline.account_manager, client)
        tools.set_status(client, "pitched", "account_manager", "Pitch assembled; waiting on the board. Nothing is sent before approval.")
        pid = tools.pitches(client)[-1]["id"]
        _say(self.log, f"Account Manager: pitch {pid} for {client} is waiting on the board")
        return {"pitch": pid}

    def approve(self, client: str, note: str = "Approved. The hackathon build sends nothing.") -> dict:
        pid = tools.pitches(client)[-1]["id"]
        return tools.board_decide(client, "Pitch", pid, "approve", note)

    def sign(self, client: str) -> dict:
        return tools.set_status(client, "signed", "board", "Signed. Same graph, now a client; history intact.")

    def client_month(self, client: str) -> dict:
        """A signed client's monthly content run: the expected Cannonball collision lives here."""
        self._agent("style_director", f"Set {client}'s taste profile from open_territory for its home style.",
                    offline.style_director, client)
        plan = self._agent("strategist", f"Write {client}'s November 2026 plan with write_plan, serving its active goal.",
                           offline.strategist, client, "November 2026")
        plan_id = tools.db.rows(tools.db.client(client), "MATCH (p:Plan) RETURN p.id AS id ORDER BY p.at DESC LIMIT 1")[0]["id"]
        seeds = self.w["draft_seeds"].get(client)
        if seeds:
            sets = [s["techniques"] for s in seeds]
        else:
            tp = [p["id"] for p in sorted(tools.taste_profile(client)["prefers"], key=lambda p: -p["weight"])]
            sets = [tp[:5], tp[1:6]]
        return {"plan": plan_id, "posts": [self.produce_and_check(client, plan_id, i, s, "draft") for i, s in enumerate(sets, 1)]}

    def retire_goal(self, client: str) -> dict:
        goal = next(g for g in tools.goals(client) if g["status"] == "active")
        res = tools.retire_goal(client, goal["id"], "board", "The spring session moved; this goal no longer holds.")
        _say(self.log, f"Board retired \"{goal['text']}\"; {len(res['stale_drafts'])} drafts now stale (Q5)")
        return res

    # -------------------------------------------------------------- the whole demo

    def run_demo(self) -> dict:
        self.reset()
        out = {"screen": self.screen()}
        for c in self.w["demo"]["pursue"]:
            out[f"research:{c}"] = self.research(c)
        for c in self.w["demo"]["pursue"]:
            out[f"spec:{c}"] = self.spec_work(c)
        sign = self.w["demo"]["sign"]
        out["pitch"] = self.pitch(sign)
        out["approve"] = self.approve(sign)
        out["sign"] = self.sign(sign)
        out["cannonball"] = self.client_month("cannonball")
        out["pixel-pond"] = self.client_month("pixel-pond")
        out["retire"] = self.retire_goal("pixel-pond")
        return out


STEPS = [
    ("reset", "Seed both graph kinds from world.json"),
    ("screen", "Scout screens 11 leads and pursues two"),
    ("research", "Researcher and Auditor fill the prospects' graphs"),
    ("spec", "Spec posts through Double Take, with revisions"),
    ("pitch", "Account Manager assembles the Tumble Town pitch"),
    ("approve", "The board approves the pitch (nothing is sent)"),
    ("sign", "Tumble Town signs: same graph, now a client"),
    ("client_month", "Cannonball's monthly drafts hit the planted collision"),
    ("retire_goal", "Retire Pixel Pond's goal: stale drafts appear"),
]


def run_step(p: Pipeline, step: str) -> dict:
    w = p.w
    if step == "reset":
        return p.reset()
    if step == "screen":
        return {"screened": p.screen()}
    if step == "research":
        return {c: p.research(c) for c in w["demo"]["pursue"]}
    if step == "spec":
        return {c: p.spec_work(c) for c in w["demo"]["pursue"]}
    if step == "pitch":
        return p.pitch(w["demo"]["sign"])
    if step == "approve":
        return p.approve(w["demo"]["sign"])
    if step == "sign":
        return p.sign(w["demo"]["sign"])
    if step == "client_month":
        return {c: p.client_month(c) for c in ("cannonball", "pixel-pond")}
    if step == "retire_goal":
        return p.retire_goal("pixel-pond")
    raise ValueError(step)
