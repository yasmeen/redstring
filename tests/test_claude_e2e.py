import ast
import json
import re
from types import SimpleNamespace

from jsonschema import validate

from redstring import config, registry, tools
from redstring.agents import claude
from redstring.pipeline import Pipeline


class ScriptedClaude:
    def __init__(self):
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))
        self._next_id = 0
        self._names = {}
        self.emitted = []
        self.tool_results = []
        self.search_urls = set()

    def _outputs(self, messages):
        outputs = []
        seen = set()
        for message in messages:
            content = message.get("content")
            if message.get("role") != "user" or not isinstance(content, list):
                continue
            for item in content:
                if item.get("type") != "tool_result" or item["tool_use_id"] in seen:
                    continue
                seen.add(item["tool_use_id"])
                self.tool_results.append(item)
                name = self._names[item["tool_use_id"]]
                outputs.append((name, json.loads(item["content"])))
        return outputs

    def _use(self, name, input):
        validate(instance=input, schema=registry.BY_NAME[name].schema)
        self._next_id += 1
        tool_use_id = f"fake-tool-{self._next_id}"
        self._names[tool_use_id] = name
        self.emitted.append((name, input))
        return SimpleNamespace(type="tool_use", id=tool_use_id, name=name, input=input)

    @staticmethod
    def _text():
        return SimpleNamespace(type="text", text="Completed the requested graph work.")

    def _response(self, *blocks):
        return SimpleNamespace(content=list(blocks), stop_reason="tool_use")

    def _finish(self):
        return SimpleNamespace(content=[self._text()], stop_reason="end_turn")

    @staticmethod
    def _client(task):
        return next(
            business["id"]
            for business in tools.world()["businesses"]
            if business["id"] in task
        )

    @staticmethod
    def _techniques(task):
        match = re.search(r"technique ids.*?: (\[.*?\])", task, re.IGNORECASE)
        return ast.literal_eval(match.group(1)) if match else []

    def _search_result(self, url):
        self.search_urls.add(url)
        return (
            SimpleNamespace(type="server_tool_use", id="fake-search", name="web_search", input={}),
            SimpleNamespace(type="web_search_tool_result", content=[{"url": url}]),
        )

    def _scout(self, task, outputs):
        leads = [business["id"] for business in tools.world()["businesses"] if business["status"] == "lead"]
        screened = {result["lead"] for name, result in outputs if name == "record_screening"}
        conflicts = {result["lead"]: result for name, result in outputs if name == "lead_conflict"}
        if len(conflicts) < len(leads):
            pending = [lead for lead in leads if lead not in conflicts][:2]
            return self._response(*[
                self._use("lead_conflict", {"lead": lead}) for lead in pending
            ])
        if len(screened) < len(leads):
            pending = [lead for lead in leads if lead not in screened][:2]
            return self._response(*[
                self._use("record_screening", {
                    "lead": lead,
                    "verdict": conflicts[lead]["verdict"],
                    "reason": conflicts[lead]["reason"],
                    "paths": conflicts[lead]["clients"],
                }) for lead in pending
            ])
        pursued = tools.world()["demo"]["pursue"]
        pursued_done = sum(name == "pursue" for name, _ in outputs)
        if pursued_done < len(pursued):
            return self._response(*[
                self._use("pursue", {
                    "slug": slug,
                    "rationale": f"Screened {slug}; pursue with the recorded verdict.",
                }) for slug in pursued[pursued_done:]
            ])
        return self._finish()

    def _researcher(self, task, outputs):
        client = self._client(task)
        findings = [result for name, result in outputs if name == "record_finding"]
        if not findings:
            url = f"https://example.test/research/{client}"
            search_use, search_result = self._search_result(url)
            return self._response(
                search_use,
                search_result,
                self._use("record_finding", {
                    "client": client,
                    "kind": "audience",
                    "text": f"Public category research for {client}.",
                    "source_url": url,
                    "rationale": "The source describes the category audience.",
                }),
            )
        if not any(name == "record_goal" for name, _ in outputs):
            return self._response(self._use("record_goal", {
                "client": client,
                "text": f"Grow {client}'s local audience.",
                "metric": "enrollments",
                "target": 100,
                "due": "2026-12-31",
                "status": "hypothesized",
                "based_on_findings": [result["finding"] for result in findings],
                "rationale": "Inferred from the category and audience research.",
            }))
        return self._finish()

    def _auditor(self, task, outputs):
        client = self._client(task)
        if any(name == "record_audit" for name, _ in outputs):
            return self._finish()
        posts = next((result for name, result in outputs if name == "posts"), None)
        if posts is None:
            return self._response(self._use("posts", {"client": client}))
        return self._response(self._use("record_audit", {
            "client": client,
            "summary": f"Reviewed the past posts for {client}.",
            "reviewed": [post["id"] for post in posts],
            "audit_findings": [
                {"text": "The strongest post earned the most views."},
                {"text": "The weakest post needs a clearer opening."},
                {"text": "The history has distinctive technique choices."},
            ],
        }))

    def _style_director(self, task, outputs):
        client = self._client(task)
        if any(name == "set_taste_profile" for name, _ in outputs):
            return self._finish()
        style = next((result for name, result in outputs if name == "style_of"), None)
        if style is None:
            return self._response(self._use("style_of", {"client": client}))
        territory = next((result for name, result in outputs if name == "open_territory"), None)
        if territory is None:
            avoid = []
            match = re.search(r"for sharing (\[.*?\]) with", task)
            if match:
                avoid = ast.literal_eval(match.group(1))
            return self._response(self._use("open_territory", {
                "client": client,
                "style": style["primary_style"],
                "avoid": avoid,
            }))
        findings = next((result for name, result in outputs if name == "findings"), None)
        if findings is None:
            return self._response(self._use("findings", {"client": client, "kind": None}))
        flags = []
        match = re.search(r"CollisionFlag ([\w-]+)", task)
        if match:
            flags = [match.group(1)]
        prefers = [
            {"technique_id": item["technique_id"], "weight": 0.8}
            for item in territory[:6]
        ]
        return self._response(self._use("set_taste_profile", {
            "client": client,
            "prefers": prefers,
            "avoids": (
                ast.literal_eval(re.search(r"for sharing (\[.*?\]) with", task).group(1))
                if "was blocked" in task else []
            ),
            "summary": f"Open territory for {client}.",
            "based_on_findings": [item["id"] for item in findings] if not flags else [],
            "based_on_flags": flags,
        }))

    def _strategist(self, task, outputs):
        client = self._client(task)
        if any(name == "write_plan" for name, _ in outputs):
            return self._finish()
        goals = next((result for name, result in outputs if name == "goals"), None)
        if goals is None:
            return self._response(self._use("goals", {"client": client}))
        profile = next((result for name, result in outputs if name == "taste_profile"), None)
        if profile is None:
            return self._response(self._use("taste_profile", {"client": client}))
        goal = next(goal for goal in goals if goal["status"] in ("active", "hypothesized"))
        period = re.search(r"period '([^']+)'", task)
        return self._response(self._use("write_plan", {
            "client": client,
            "period": period.group(1) if period else "Claude plan",
            "goal_id": goal["id"],
            "rationale": f"Serves {goal['text']}.",
        }))

    def _producer(self, task, outputs):
        client = self._client(task)
        if any(name == "write_draft" for name, _ in outputs):
            return self._finish()
        refs = next((result for name, result in outputs if name == "references_for"), None)
        technique_ids = self._techniques(task)
        if refs is None:
            return self._response(self._use("references_for", {
                "technique_ids": technique_ids,
                "limit": 10,
                "category": tools.business(client)["category"],
                "exclude": [],
                "exclude_creators": [],
            }))
        plan = re.search(r"in plan ([\w-]+)", task).group(1)
        slot = int(re.search(r"post (\d+)", task).group(1))
        kind = re.search(r"kind (spec|draft)", task).group(1)
        revision = re.search(r"revision_of=([\w-]+)", task)
        return self._response(self._use("write_draft", {
            "client": client,
            "plan_id": plan,
            "format": "reel",
            "hook": f"Claude scripted {kind} {slot}",
            "spec": "A scripted shot-by-shot creative specification.",
            "technique_ids": technique_ids,
            "reference_ids": [item["id"] for item in refs[:2]],
            "rationale": "Built from the requested creative brief.",
            "kind": kind,
            "revision_of": revision.group(1) if revision else None,
            "based_on_findings": [],
        }))

    def _standards(self, task, outputs):
        if not outputs:
            client = self._client(task)
            draft = re.search(r"draft (draft-[\w-]+)", task).group(1)
            return self._response(self._use("check_draft", {"client": client, "draft_id": draft}))
        return self._finish()

    def _account_manager(self, task, outputs):
        client = self._client(task)
        if any(name == "write_pitch" for name, _ in outputs):
            return self._finish()
        drafts = next((result for name, result in outputs if name == "drafts"), None)
        if drafts is None:
            return self._response(self._use("drafts", {"client": client}))
        findings = next((result for name, result in outputs if name == "findings"), None)
        if findings is None:
            return self._response(self._use("findings", {"client": client, "kind": None}))
        goals = next((result for name, result in outputs if name == "goals"), None)
        if goals is None:
            return self._response(self._use("goals", {"client": client}))
        goal = next(goal for goal in goals if goal["status"] in ("active", "hypothesized"))
        draft_ids = [
            draft["id"] for draft in drafts
            if draft["status"] in ("queued", "approved") and draft["kind"] == "spec"
        ]
        return self._response(self._use("write_pitch", {
            "client": client,
            "angle": f"{client}: a differentiated creative plan built for the local audience.",
            "draft_ids": draft_ids,
            "finding_ids": [finding["id"] for finding in findings[:6]],
            "goal_id": goal["id"],
            "rationale": "Cites the client's findings and cleared spec drafts.",
        }))

    def create(self, **kwargs):
        messages = kwargs["messages"]
        agent = next(name for name, role in claude.ROLES.items() if kwargs["system"].startswith(role))
        task = messages[0]["content"]
        outputs = self._outputs(messages)
        handlers = {
            "scout": self._scout,
            "researcher": self._researcher,
            "auditor": self._auditor,
            "style_director": self._style_director,
            "strategist": self._strategist,
            "producer": self._producer,
            "standards": self._standards,
            "account_manager": self._account_manager,
        }
        return handlers[agent](task, outputs)


def test_claude_mode_runs_end_to_end_with_a_scripted_client(monkeypatch, tmp_path):
    fake = ScriptedClaude()
    monkeypatch.setattr(claude, "_client", fake)
    monkeypatch.setattr(config, "RESEARCH_CACHE", tmp_path / "research")
    tools._world_cache = None

    Pipeline("claude", log=None).run_demo()

    blocked = {
        business["id"]
        for business in tools.world()["businesses"]
        if tools.collision_flags(business["id"])
    }
    diagnostic = {
        slug: {
            "drafts": [(d["status"], d["techniques"]) for d in tools.drafts(slug)],
            "flags": tools.collision_flags(slug),
            "emitted": [args["technique_ids"] for name, args in fake.emitted
                        if name == "write_draft" and args["client"] == slug],
        }
        for slug in ("cannonball", "treble-clef", "tumble-town")
    }
    assert blocked == {"cannonball", "treble-clef", "tumble-town"}, diagnostic
    assert tools.business("tumble-town")["status"] == "signed"
    assert len(tools.stale_drafts("pixel-pond")) == 2
    screened_paths = {
        args["lead"]: args["paths"]
        for name, args in fake.emitted
        if name == "record_screening"
    }
    assert len(screened_paths) == 11
    assert any(screened_paths.values())
    for lead, paths in screened_paths.items():
        card = tools.screening_card(lead)
        assert card
        assert card["paths"] == paths
    assert all(
        args["source_url"] in fake.search_urls
        for name, args in fake.emitted
        if name == "record_finding"
    )
    assert not [result for result in fake.tool_results if result.get("is_error")]
    assert fake.emitted
