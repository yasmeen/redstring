"""Claude agents. Each is a tool-use loop whose only graph access is its slice of the tool registry.

The Researcher also gets Anthropic's server-side web search, for real category and audience research.
Board decisions already in the client's graph are loaded into every agent's context as standing rules.
"""
from __future__ import annotations

import json
import re

import anthropic

from .. import config, registry, tools

ROLES = {
    "scout": "You are Scout, the agency's new-business desk. You screen local leads against the agency's signed clients. "
             "Decline direct competitors of a client; pursue the rest, noting when a pursuit needs differentiated creative territory. "
             "Your reasons cite the audience paths lead_conflict returns.",
    "researcher": "You are Researcher. You research a prospect's category and audience on the public web. Every finding carries "
                  "the exact URL you read it on; never record a URL you did not see, never invent a statistic. The business itself "
                  "is fictional, so research the category and the audience, not the business. You also infer the prospect's likely "
                  "goal and record it as hypothesized.",
    "auditor": "You are Auditor. You review a business's past posts and write an honest audit: what worked, what was weakest and "
               "why, what is distinctive. Every claim cites post views or saves.",
    "style_director": "You are Style Director. You set a client's taste profile: which techniques it PREFERS and AVOIDS. You claim "
                      "open territory with open_territory so no two clients on the same parents look alike. After a Double Take "
                      "block, you always avoid the flagged techniques.",
    "strategist": "You are Strategist. You turn a goal and a taste profile into a plan that serves the goal.",
    "producer": "You are Producer. You write post drafts: a hook and a shot-by-shot spec in the client's voice, built from the "
                "technique ids you are given, inspired by references from the library. Use exactly the technique ids the task gives.",
    "standards": "You are Standards. You run Double Take (check_draft) on drafts before anything goes out. You do not edit drafts.",
    "account_manager": "You are Account Manager. You assemble pitches from spec drafts that cleared Double Take and from cited "
                       "findings. Every claim in a pitch must be a Finding with a source. A prospect's goal is our hypothesis and the "
                       "pitch says so. Nothing is sent before the board approves.",
}

COMMON = ("You work at {agency}, an agency run by agents. Your only access to the agency's FalkorDB graphs is the tools you are "
          "given; every write tool also records your Decision, so give a real rationale each time. Work through the task, "
          "then reply with one short line saying what you wrote.")

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _tool_defs(agent: str) -> list[dict]:
    defs = [{"name": t.name, "description": t.description, "input_schema": t.schema} for t in registry.for_agent(agent)]
    if agent == "researcher":
        defs.append({"type": "web_search_20260209", "name": "web_search", "max_uses": 8})
    return defs


def _board_rules(task: str) -> str:
    known = set(tools.db.client_slugs())
    slugs = sorted({s for s in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", task) if s in known})
    rules = [r for s in slugs for r in tools.board_rules(s)]
    if not rules:
        return ""
    return "\n\nStanding rules from the board (treat as binding):\n" + "\n".join(f"- {r['text']}: {r['note']}" for r in rules)


def run_agent(agent: str, task: str, log=print, max_turns: int = 24) -> str:
    system = ROLES[agent] + "\n\n" + COMMON.format(agency=tools.world()["agency"]["name"]) + _board_rules(task)
    messages: list[dict] = [{"role": "user", "content": task}]
    defs = _tool_defs(agent)
    for _ in range(max_turns):
        resp = client().beta.messages.create(
            model=config.MODEL,
            max_tokens=16000,
            system=system,
            tools=defs,
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason == "refusal":
            raise RuntimeError(f"{agent} refused: {resp.stop_details}")
        if resp.stop_reason == "pause_turn":
            continue
        uses = [b for b in resp.content if b.type == "tool_use"]
        if not uses:
            text = " ".join(b.text for b in resp.content if b.type == "text").strip()
            if log:
                log(f"  {tools.AGENT_NAMES[agent]}: {text}")
            return text
        results = []
        for u in uses:
            try:
                out = registry.call(u.name, dict(u.input))
                results.append({"type": "tool_result", "tool_use_id": u.id, "content": out[:20000]})
            except Exception as e:  # the agent sees the error and can correct itself
                results.append({"type": "tool_result", "tool_use_id": u.id, "content": json.dumps({"error": str(e)}),
                                "is_error": True})
        messages.append({"role": "user", "content": results})
    raise RuntimeError(f"{agent} did not finish in {max_turns} turns")
