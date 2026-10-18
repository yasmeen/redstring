"""One registry of named graph tools, shared by the MCP server and the Claude agents.

Each entry: the function, a description written for the model, a JSON schema, and the agents allowed
to call it. An agent's only graph access is its slice of this registry.
"""
from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Callable

from . import seed, tools


@dataclass
class Tool:
    name: str
    fn: Callable[..., Any]
    description: str
    properties: dict
    required: list[str]
    agents: list[str] = field(default_factory=list)
    query: str | None = None  # which spec query it wraps, for the README and UI
    writable: bool = False
    scoped: bool = True

    @property
    def schema(self) -> dict:
        return {"type": "object", "properties": self.properties, "required": self.required,
                "additionalProperties": False}

    def call(self, args: dict, *, caller: str | None = None, scope: str | None = None,
             allowed_slugs: set[str] | None = None,
             allowed_pursuits: set[str] | None = None) -> Any:
        kwargs = dict(args)
        kwargs.pop("agent", None)
        kwargs.pop("by", None)
        kwargs.pop("source", None)

        if scope is not None and self.scoped:
            for key in ("client", "slug"):
                if key not in self.properties:
                    continue
                requested = kwargs.get(key)
                if requested not in (None, scope):
                    raise ValueError(f"{self.name}: {key} is pinned to {scope}")
                kwargs[key] = scope

        for key in ("client", "slug"):
            requested = kwargs.get(key)
            if requested is not None:
                seed.validate_business_slug(tools.world(), requested)

        if allowed_slugs is not None:
            for key in ("lead", "slug"):
                if key not in self.properties:
                    continue
                requested = kwargs.get(key)
                if requested is not None and requested not in allowed_slugs:
                    raise ValueError(f"{self.name}: {key} must be one of the allowed leads")

        if allowed_pursuits is not None and self.name == "pursue" and kwargs.get("slug") not in allowed_pursuits:
            raise ValueError(f"{self.name}: slug must be one of the allowed pursuits")

        if caller is not None and "agent" in inspect.signature(self.fn).parameters:
            kwargs["agent"] = caller
        return self.fn(**kwargs)


S = {"type": "string"}
SL = {"type": "array", "items": {"type": "string"}}
N = {"type": "number"}
CLIENT = {"type": "string", "description": "Business slug, for example tumble-town. Its private graph is client:<slug>."}


def _brief(client: str) -> dict:
    """Spec seeds and draft seeds from world.json: the creative brief's starting technique sets."""
    w = tools.world()
    seeds = w["spec_seeds"].get(client) or w["draft_seeds"].get(client) or []
    names = {t["id"]: t["name"] for t in w["techniques"]}
    b = seed.find_business(w, client)
    return {"business": b["name"], "voice": b["voice"], "category": b["category"],
            "posts": [{"slot": i + 1, "technique_ids": s["techniques"],
                       "techniques": [names[t] for t in s["techniques"]]} for i, s in enumerate(seeds)]}


def _style_of(client: str) -> dict:
    w = tools.world()
    b = seed.find_business(w, client)
    styles = {s["id"]: s["name"] for s in w["styles"]}
    return {"primary_style": styles[b["style"]], "secondary_style": styles[b["secondary"]], "voice": b["voice"]}


def _taste(client: str, prefers: list[dict], avoids: list[str], summary: str,
           based_on_findings: list[str] | None = None, based_on_flags: list[str] | None = None,
           agent: str = "style_director") -> dict:
    based = [("Finding", f) for f in based_on_findings or []] + [("CollisionFlag", f) for f in based_on_flags or []]
    return tools.set_taste_profile(client, {p["technique_id"]: p["weight"] for p in prefers}, avoids, summary,
                                    based, agent=agent)


def _draft(client: str, plan_id: str, format: str, hook: str, spec: str, technique_ids: list[str],
           reference_ids: list[str], rationale: str, kind: str = "draft", revision_of: str | None = None,
           based_on_findings: list[str] | None = None, agent: str = "producer") -> dict:
    tp = tools.taste_profile(client)
    based = [("Finding", f) for f in based_on_findings or []] + ([("TasteProfile", tp["id"])] if tp else [])
    return tools.write_draft(client, plan_id, format, hook, spec, technique_ids, reference_ids, rationale,
                             kind=kind, revision_of=revision_of, based_on=based, agent=agent)


def _project(draft_id: str, client: str, kind: str, technique_ids: list[str]) -> dict:
    from . import db, queries
    tools.validate_technique_ids(technique_ids)
    db.run(db.agency(), queries.P1_PROJECT_FINGERPRINT,
           {"draft_id": draft_id, "kind": kind, "client": client, "now": tools.now(), "technique_ids": technique_ids})
    return {"fingerprint": draft_id}


TOOLS: list[Tool] = [
    # ---- the seven product queries
    Tool("project_fingerprint", _project, "P1. Project a draft's technique ids into the shared agency graph as a Fingerprint. No copy or assets leave the client graph. write_draft already does this; use it directly only to backfill.",
         {"draft_id": S, "client": CLIENT, "kind": {"type": "string", "enum": ["post", "draft", "spec"]}, "technique_ids": SL},
         ["draft_id", "client", "kind", "technique_ids"], ["producer"], "P1", writable=True),
    Tool("derive_signatures", tools.derive_signatures, "Q0. Recompute every business's signature techniques: rare (rarity >= 0.75) and in 30% or more of its active fingerprints.",
         {}, [], ["standards"], "Q0", writable=True),
    Tool("lead_conflict", tools.lead_conflict, "Q1. Audience conflict between a lead and each signed client, including multi-hop paths through overlapping audiences, plus the same-category same-neighborhood rule. Returns a suggested verdict.",
         {"lead": CLIENT}, ["lead"], ["scout"], "Q1"),
    Tool("double_take", tools.double_take, "Q2, read only. Compare a draft's fingerprint with every business on a shared audience. Similarity is shared rare-technique rarity divided by the draft's total rare-technique rarity; common moves do not dilute it. Risk = similarity x audience overlap; flag at risk >= 0.35.",
         {"client": CLIENT, "draft_id": S}, ["client", "draft_id"], ["standards", "style_director"], "Q2"),
    Tool("open_territory", tools.open_territory, "Q3. Techniques in a style that no business on an overlapping audience has claimed as a signature, rarest first. Pass the flagged techniques as avoid.",
         {"client": CLIENT, "style": {"type": "string", "description": "Style name, for example Hype Montage"}, "avoid": SL},
         ["client", "style", "avoid"], ["style_director"], "Q3"),
    Tool("decision_trace", tools.decision_trace, "Q4. The route card for a draft: its goal, every decision with who made it, the findings and references it rests on, its lineage and flags.",
         {"client": CLIENT, "draft_id": S}, ["client", "draft_id"], ["account_manager", "board"], "Q4"),
    Tool("stale_drafts", tools.stale_drafts, "Q5. Queued or approved drafts whose plan serves a retired goal.",
         {"client": CLIENT}, ["client"], ["board", "strategist"], "Q5"),

    # ---- reads
    Tool("pipeline_board", tools.pipeline_board, "Every business in the agency directory with status, owner and screening verdict.", {}, [], ["scout", "account_manager"]),
    Tool("audiences_of", tools.audiences_of, "The audience segments a business targets, with weights.", {"client": CLIENT}, ["client"], ["scout", "researcher", "style_director"], scoped=False),
    Tool("style_of", _style_of, "The business's home style slice and voice.", {"client": CLIENT}, ["client"], ["style_director", "producer"]),
    Tool("list_styles", tools.list_styles, "All styles (technique clusters) with average rarity.", {}, [], ["style_director"]),
    Tool("signatures", tools.signatures, "Signature techniques, for one business or all.", {"slug": {"type": ["string", "null"]}}, [], ["style_director", "standards"], scoped=False),
    Tool("findings", tools.findings, "Findings in the client graph, optionally one kind (audience, competitor, channel, audit).",
         {"client": CLIENT, "kind": {"type": ["string", "null"]}}, ["client"], ["style_director", "strategist", "account_manager", "producer"]),
    Tool("goals", tools.goals, "Goals in the client graph with status (active, hypothesized, retired).", {"client": CLIENT}, ["client"], ["researcher", "strategist", "style_director", "account_manager"]),
    Tool("posts", tools.posts, "The business's past posts with views, saves and technique ids.", {"client": CLIENT}, ["client"], ["auditor"]),
    Tool("taste_profile", tools.taste_profile, "The latest TasteProfile: PREFERS (with weights) and AVOIDS.", {"client": CLIENT}, ["client"], ["strategist", "producer", "style_director"]),
    Tool("drafts", tools.drafts, "Drafts in the client graph with status, version and techniques.", {"client": CLIENT}, ["client"], ["producer", "account_manager", "standards"]),
    Tool("references_for", tools.references_for, "References from the library that show these techniques, prioritizing the business category.",
         {"technique_ids": SL, "limit": {"type": "integer"}, "category": S, "exclude": SL,
          "exclude_creators": SL},
         ["technique_ids"], ["producer"]),
    Tool("techniques", tools.techniques, "Look up techniques by id: name, category, rarity, style.", {"ids": SL}, ["ids"], ["producer", "style_director", "standards"]),
    Tool("collision_flags", tools.collision_flags, "CollisionFlags in the client graph, optionally for one draft.", {"client": CLIENT, "draft_id": {"type": ["string", "null"]}}, ["client"], ["style_director", "producer"]),
    Tool("creative_brief", _brief, "The creative brief: starting technique sets for each planned post.", {"client": CLIENT}, ["client"], ["producer"]),

    # ---- writes (each writes a Decision with DECIDED_BY)
    Tool("record_screening", tools.record_screening, "Write Scout's SCREENED verdict on a lead, with the reason and audience paths.",
         {"lead": CLIENT, "verdict": {"type": "string", "enum": ["decline", "pursue", "pursue_differentiated", "borderline"]}, "reason": S,
          "paths": {"type": "array", "items": {
              "type": "object",
              "properties": {
                  "client_id": S, "client": S, "same_category": {"type": "boolean"},
                  "via": S, "hop": {"type": ["string", "null"]}, "conflict": N,
              },
              "required": ["client_id", "client", "same_category", "via", "hop", "conflict"],
              "additionalProperties": False,
          }}}, ["lead", "verdict", "reason"], ["scout"], writable=True),
    Tool("pursue", tools.pursue, "Create the prospect's private graph and set its status to pursued.", {"slug": CLIENT, "rationale": S}, ["slug", "rationale"], ["scout"], writable=True),
    Tool("record_finding", tools.record_finding, "Record a Finding with its source URL. Use only URLs you actually read.",
         {"client": CLIENT, "kind": {"type": "string", "enum": ["audience", "competitor", "channel"]}, "text": S, "source_url": S, "rationale": S},
         ["client", "kind", "text", "source_url", "rationale"], ["researcher"], writable=True),
    Tool("record_goal", tools.record_goal, "Record a Goal. For a prospect use status hypothesized: it is your inference and the pitch shows it as such.",
         {"client": CLIENT, "text": S, "metric": S, "target": N, "due": S, "status": {"type": "string", "enum": ["hypothesized", "active"]},
          "based_on_findings": SL, "rationale": S}, ["client", "text", "metric", "target", "due", "status", "based_on_findings", "rationale"], ["researcher"], writable=True),
    Tool("record_audit", tools.record_audit, "Record an Audit: which posts you reviewed and what you found (each finding becomes a Finding).",
         {"client": CLIENT, "summary": S, "reviewed": SL,
          "audit_findings": {"type": "array", "items": {"type": "object", "properties": {"text": S}, "required": ["text"], "additionalProperties": False}}},
         ["client", "summary", "reviewed", "audit_findings"], ["auditor"], writable=True),
    Tool("set_taste_profile", _taste, "Write a new TasteProfile version: techniques the client PREFERS (weight 0 to 1) and AVOIDS.",
         {"client": CLIENT, "prefers": {"type": "array", "items": {"type": "object", "properties": {"technique_id": S, "weight": N}, "required": ["technique_id", "weight"], "additionalProperties": False}},
          "avoids": SL, "summary": S, "based_on_findings": SL, "based_on_flags": SL}, ["client", "prefers", "avoids", "summary"], ["style_director"], writable=True),
    Tool("write_plan", tools.write_plan, "Write a Plan that SERVES a goal.", {"client": CLIENT, "period": S, "goal_id": S, "rationale": S},
         ["client", "period", "goal_id", "rationale"], ["strategist"], writable=True),
    Tool("write_draft", _draft, "Write a Draft in the client graph and project its Fingerprint into agency (P1). For a revision pass revision_of.",
         {"client": CLIENT, "plan_id": S, "format": {"type": "string", "enum": ["reel", "carousel"]}, "hook": S,
          "spec": {"type": "string", "description": "Shot-by-shot creative spec in the client's voice"},
         "technique_ids": SL, "reference_ids": SL, "rationale": S,
          "kind": {"type": "string", "enum": ["draft", "spec"]}, "revision_of": {"type": ["string", "null"]}, "based_on_findings": SL},
         ["client", "plan_id", "format", "hook", "spec", "technique_ids", "reference_ids", "rationale", "kind"], ["producer"], writable=True),
    Tool("check_draft", tools.check_draft, "Standards' Double Take: run Q2 and either clear the draft or block it with a CollisionFlag.",
         {"client": CLIENT, "draft_id": S}, ["client", "draft_id"], ["standards"], "Q2", writable=True),
    Tool("write_pitch", tools.write_pitch, "Assemble a Pitch: the spec drafts it SHOWS, the findings it CITES, the goal it SERVES. It is sent only after board approval.",
         {"client": CLIENT, "angle": S, "draft_ids": SL, "finding_ids": SL, "goal_id": S, "rationale": S},
         ["client", "angle", "draft_ids", "finding_ids", "goal_id", "rationale"], ["account_manager"], writable=True),
]

BY_NAME = {t.name: t for t in TOOLS}


def for_agent(agent: str) -> list[Tool]:
    return [t for t in TOOLS if agent in t.agents]


def call(name: str, args: dict, *, caller: str | None = None, scope: str | None = None,
         allowed_slugs: set[str] | None = None,
         allowed_pursuits: set[str] | None = None) -> str:
    out = BY_NAME[name].call(args, caller=caller, scope=scope, allowed_slugs=allowed_slugs,
                              allowed_pursuits=allowed_pursuits)
    return json.dumps(out, default=str)
