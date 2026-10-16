# Red String

An agent-run creative agency that wins clients by doing the work first. It screens local businesses, researches and audits each one, and pitches with spec content made for that business, with every claim traced to its source in FalkorDB. What sets it apart from scrape-and-pitch pipelines: when two pitches, or a pitch and an existing client, reach the same people, they never look alike.

- **Red String** is the software.
- **Double Take** is its collision check (Q2).
- **Threads** are the route cards: the string from an answer back to its sources.
- **Corkboard Studio** is a placeholder name for the agency running Red String in the demo. It is not the product.

**Live demo:** [Red String](https://redstring-production-84af.up.railway.app) is read-only; the step runner is hidden there and runs locally.

## What is real and what is synthetic

| Real | Synthetic, and labeled as such |
| --- | --- |
| The agent pipeline, the graph, the seven queries; the real NYC neighborhoods Flatiron, NoMad, Gramercy Park, and Chelsea | All 14 businesses, their 63 past posts, and their goals |
| Category and audience research with source URLs (`data/research/`) | The reference library, **for now**: `data/references.json` does not exist yet, so the build uses 200 placeholder references (`placeholder: true`, `example.com` URLs) with a realistic long-tail distribution. Run `redstring import-refs` on the Instinct export to replace them. |

Every business name is invented. Search each one before the demo and swap any that match a real business in these neighborhoods.

**Spot-check the research cache.** The findings in `data/research/*.json` were gathered from search results matched to specific URLs. The pages themselves could not be loaded from the build environment, so each file carries a `verification` note. Open every `source_url` before recording.

## Quickstart

```sh
uv venv && uv pip install -e ".[dev]"            # or: pip install -e ".[dev]"

# FalkorDB: either Docker (adds FalkorDB Browser on :3000)...
docker compose up -d falkordb
# ...or no Docker, using the binaries bundled in the falkordblite wheel
./scripts/falkordb-local.sh &

redstring world      # regenerate data/world.json (already committed; deterministic, seed 1015)
redstring seed       # agency + client:pixel-pond, client:wet-paint, client:cannonball
redstring check      # the Thursday-night checkpoint: P1 and Q0-Q5 on the seed
redstring demo       # the whole demo, offline agents (no API key)
redstring serve      # http://localhost:8000: pipeline board, threads, Double Take, step runner
redstring mcp        # the named tools as an MCP server (stdio; --http 8765 for HTTP)
pytest               # boots its own throwaway FalkorDB
```

**Agents.** `REDSTRING_MODE=offline` (the default) runs deterministic agents that write the same nodes through the same tools, with templated text. `REDSTRING_MODE=claude` (or `redstring demo --mode claude`) runs each agent as a Claude tool-use loop (`claude-opus-5-5`, adaptive thinking, server-side refusal fallback) whose only graph access is its slice of the tool registry. The Researcher also gets web search, and its findings are cached to `data/research/<slug>.json` so reruns replay them. Set `ANTHROPIC_API_KEY` first. Claude mode has only been exercised against a scripted fake client so far; run it once with a real key before relying on it.

**Deploy.** Set `REDSTRING_READONLY=1` on a public link: visitors can still use both try-it inputs, but cannot reset the demo or act as the board. `docker compose up` runs both services. For a hosted demo, point `FALKORDB_HOST`, `FALKORDB_PORT`, `FALKORDB_USERNAME` and `FALKORDB_PASSWORD` at FalkorDB Cloud and deploy the `Dockerfile`. It seeds on boot.

## Graph architecture

Each prospect or client gets its own private FalkorDB graph, `client:<slug>`. A shared `agency` graph holds only what the agency needs to compare clients: businesses, audiences, techniques, references, and **fingerprints**. When Producer writes a Draft in a client graph, P1 projects a Fingerprint into `agency` that holds technique ids only, with no copy and no assets. Cross-client checks run only on `agency`. Threads and stale-draft checks run inside the client's own graph.

Lifecycle: **lead** (a Business node in `agency`) → **screened** (`SCREENED` edge with verdict) → **pursued** (the private graph is created; Researcher and Auditor fill it, including a *hypothesized* goal) → **spec work** (3 spec posts through Double Take) → **pitched** (the board approves before anything is sent; in this build nothing is ever sent) → **signed** (status changes, graph and history stay) or **passed** (the graph stays; its spec fingerprints keep counting in Q2 for 90 days).

The one rule: **every agent write also writes a `Decision` with `DECIDED_BY`**, so every artifact has a why. `tests/test_graph.py::test_every_artifact_has_a_why` enforces it.

The schema follows the spec (Oct 15). Additions: `Decision` nodes also live in `agency` (for Scout's screenings, which happen before a private graph exists); `Fingerprint.active` (a blocked or superseded draft stops counting); `SCREENED.paths` (the audience paths behind the verdict, as JSON); `CollisionFlag.risk`, `.overlap` and `.evidence` (which of the other business's fingerprints carry the shared techniques).

## Technique vocabulary and rarity

There are 80 techniques in 8 categories (`data/techniques.json`), each in exactly one of 8 styles. The vocabulary is closed: `redstring import-refs` maps each Instinct analysis onto these ids with Claude structured outputs (an enum of ids), and anything that doesn't fit goes to `data/proposed_techniques.json` for Yaz to approve. Extraction never mints a Technique.

`rarity(t) = log(N / (1 + n_t)) / log N`, computed at seed time. With N = 200, 2 references give 0.79 and 40 give 0.30. **Rare** means at least 0.6, about 7 or fewer of 200. A **signature** is a technique that is rare and appears in 30% or more of one business's active fingerprints. Every threshold lives in `redstring/config.py`.

## The seven queries

Each one is a named tool (`redstring/registry.py`), served over MCP, so agents never write raw Cypher. Lines marked `CHANGE` differ from the spec. Each change came from running the query on the seed:

1. P1 takes `kind` as a parameter and sets `active = true`. A revision or a Double Take block retires the old fingerprint, so a draft that never ships stops counting against anyone.
2. Q0 clears stale `SIGNATURE` edges first, and counts only active fingerprints.
3. Q1 stores `OVERLAPS` once per pair and matches it undirected. The same-category, same-neighborhood decline rule is its own small query. Verdicts sum conflict per signed client: at least 0.9 means pursue only with differentiated territory, at least 0.5 means borderline, and anything lower means pursue. On the seed this reproduces every verdict in the spec's lead table.
4. Q2 counts only active fingerprints, and passed prospects count until their cooldown ends. Risk = similarity × audience overlap. Overlap uses Q1's paths between the two businesses, clamped to 1. A draft is flagged at risk 0.35 or more.
5. Q3 treats open pursuits as claimants too, so two pitches don't converge. It also takes `$avoid` (the flagged techniques) and requires at least one reference as evidence.
6. Q4 also labels Draft, Audit and CollisionFlag sources.

**P1. Fingerprint projection** (agency; Producer)
```cypher
MERGE (f:Fingerprint {id: $draft_id})
SET f.kind = $kind, f.business_id = $client, f.created_at = $now, f.active = true
WITH f
MATCH (b:Business {id: $client})
MERGE (f)-[:OF]->(b)
WITH f
UNWIND $technique_ids AS tid
MATCH (t:Technique {id: tid})
MERGE (f)-[:USES]->(t)
```

**Q0. Derive signatures** (agency; Standards)
```cypher
MATCH (b:Business)<-[:OF]-(f:Fingerprint)
WHERE f.active
WITH b, count(f) AS total
MATCH (b)<-[:OF]-(f:Fingerprint)-[:USES]->(t:Technique)
WHERE f.active AND t.rarity >= $rare
WITH b, t, total, count(f) AS uses
WHERE toFloat(uses) / total >= $share
MERGE (b)-[s:SIGNATURE]->(t)
SET s.share = toFloat(uses) / total
RETURN b.name AS business, t.name AS technique, t.id AS technique_id, s.share AS share
ORDER BY business, share DESC
```

**Q1. Lead conflict check** (agency; Scout). The second half is the multi-hop path: lead → audience → overlapping audience → client.
```cypher
MATCH (lead:Business {id: $lead})-[tl:TARGETS]->(a:Audience)<-[tc:TARGETS]-(c:Business {status: 'signed'})
RETURN c.id AS client_id, c.name AS client, c.category = lead.category AS same_category,
       a.name AS via, null AS hop, tl.weight * tc.weight AS conflict
UNION ALL
MATCH (lead:Business {id: $lead})-[tl:TARGETS]->(la:Audience)-[o:OVERLAPS]-(a:Audience)<-[tc:TARGETS]-(c:Business {status: 'signed'})
RETURN c.id AS client_id, c.name AS client, c.category = lead.category AS same_category,
       a.name AS via, la.name AS hop, tl.weight * tc.weight * o.share AS conflict
```

**Q2. Double Take** (agency; Standards)
```cypher
MATCH (d:Fingerprint {id: $draft})-[:OF]->(me:Business)-[:TARGETS]->(:Audience)<-[:TARGETS]-(other:Business)
WHERE other <> me AND (other.status IN ['signed', 'pursued', 'pitched']
      OR (other.status = 'passed' AND other.passed_at >= $cooldown_cutoff))
WITH DISTINCT d, other
MATCH (d)-[:USES]->(t:Technique)<-[:USES]-(of:Fingerprint)-[:OF]->(other)
WHERE t.rarity >= $rare AND of.active
WITH d, other, collect(DISTINCT t) AS shared
MATCH (d)-[:USES]->(mine:Technique)
WITH other, shared, sum(mine.rarity) AS total
RETURN other.id AS business_id, other.name AS business, other.status AS status,
       [t IN shared | t.id] AS shared_ids, [t IN shared | t.name] AS shared_rare,
       reduce(s = 0.0, t IN shared | s + t.rarity) / total AS similarity
ORDER BY similarity DESC
```

**Q3. Open territory** (agency; Style Director)
```cypher
MATCH (me:Business {id: $client})
OPTIONAL MATCH (me)-[:TARGETS]->(:Audience)<-[:TARGETS]-(other:Business)
WHERE other <> me AND other.status IN ['signed', 'pursued', 'pitched']
OPTIONAL MATCH (other)-[:SIGNATURE]->(claimed:Technique)
WITH collect(DISTINCT claimed.id) AS taken
MATCH (t:Technique)-[:PART_OF]->(:Style {name: $style})
WHERE NOT t.id IN taken AND NOT t.id IN $avoid
OPTIONAL MATCH (t)<-[:USES]-(r:Reference)
WITH t, count(r) AS examples
WHERE examples > 0
RETURN t.id AS technique_id, t.name AS technique, t.category AS category, t.rarity AS rarity, examples
ORDER BY rarity DESC, examples DESC
LIMIT 12
```

**Q4. Decision trace** (client graph; feeds the thread)
```cypher
MATCH (d:Draft {id: $draft})
OPTIONAL MATCH (d)<-[:INCLUDES]-(:Plan)-[:SERVES]->(g:Goal)
OPTIONAL MATCH (dec:Decision)-[:AFFECTS]->(d)
OPTIONAL MATCH (dec)-[:DECIDED_BY]->(a:Agent)
OPTIONAL MATCH (dec)-[:BASED_ON]->(src)
OPTIONAL MATCH (d)-[:INSPIRED_BY]->(r:Reference)
RETURN d.hook AS draft, d.status AS status, g.text AS goal, g.status AS goal_status,
       collect(DISTINCT {decision: dec.text, by: a.name, at: dec.at, rationale: dec.rationale}) AS decisions,
       collect(DISTINCT {kind: labels(src)[0], text: coalesce(src.text, src.url, src.summary, src.hook, src.with_business), source_url: src.source_url}) AS sources,
       collect(DISTINCT r.url) AS references
```

**Q5. Stale drafts after a goal changes** (client graph)
```cypher
MATCH (g:Goal {status: 'retired'})<-[:SERVES]-(:Plan)-[:INCLUDES]->(d:Draft)
WHERE d.status IN ['queued', 'approved']
RETURN d.id AS draft, d.hook AS hook, g.text AS retired_goal
```

## Agents and their tools

Eight agents and one human board. The revision loop is the core: Producer drafts → Standards flags → Style Director pulls open territory and writes a new TasteProfile version → Producer revises with `REVISION_OF` → Standards re-checks (`redstring/pipeline.py`). Each agent reads what the previous one wrote in the graph. Board approvals and vetoes are Decisions `DECIDED_BY` Yaz, and Claude agents load them as standing rules.

| Tool | Query | Agents |
| --- | --- | --- |
| `project_fingerprint` | P1 | producer |
| `derive_signatures` | Q0 | standards |
| `lead_conflict` | Q1 | scout |
| `double_take` | Q2 | standards, style_director |
| `open_territory` | Q3 | style_director |
| `decision_trace` | Q4 | account_manager, board |
| `stale_drafts` | Q5 | board, strategist |
| `pipeline_board` |  | scout, account_manager |
| `audiences_of` |  | scout, researcher, style_director |
| `style_of` |  | style_director, producer |
| `list_styles` |  | style_director |
| `signatures` |  | style_director, standards |
| `findings` |  | style_director, strategist, account_manager, producer |
| `goals` |  | researcher, strategist, style_director, account_manager |
| `posts` |  | auditor |
| `taste_profile` |  | strategist, producer, style_director |
| `drafts` |  | producer, account_manager, standards |
| `references_for` |  | producer |
| `techniques` |  | producer, style_director, standards |
| `collision_flags` |  | style_director, producer |
| `creative_brief` |  | producer |
| `record_screening` |  | scout |
| `pursue` |  | scout |
| `record_finding` |  | researcher |
| `record_goal` |  | researcher |
| `record_audit` |  | auditor |
| `set_taste_profile` |  | style_director |
| `write_plan` |  | strategist |
| `write_draft` |  | producer |
| `check_draft` | Q2 | standards |
| `write_pitch` |  | account_manager |

## The demo, as it runs on the seed

The step runner at the top of the web app plays these in order. `redstring demo` runs them all.

1. **Seed.** 14 businesses, 3 signed clients, 8 agents plus the board, 63 post fingerprints. Q0 finds Wet Paint's signature: Stop motion, Paint smear wipe, Handwritten titles. These are the planted set, in 4 of Wet Paint's posts and 4 of Cannonball's, and they are each history's best performers. That is the ghostwriter story.
2. **Scout** declines Deep End Swim Club (same category as Cannonball, both in Gramercy Park). Byte Builders shares Pixel Pond's category but is in Chelsea, so Scout screens it on audience: pursue differentiated (conflict 1.464). It flags Tumble Town (conflict 1.58 with Wet Paint), Treble Clef and Northpoint for differentiated territory, calls Page Turn borderline (0.72), and clears the rest. It pursues Tumble Town and Treble Clef. Each verdict's thread shows its audience paths.
3. **Researcher and Auditor** fill both private graphs: sourced findings, a hypothesized goal, and 3 audit findings computed from the posts.
4. **Spec posts.** Tumble Town's post 2 is blocked: it resembles Wet Paint (and Cannonball), with risk 0.55. Treble Clef's post 1 is blocked against **Tumble Town's open pitch**, with risk 0.46. Both are revised from open territory and pass on re-check.
5. **Account Manager** assembles the Tumble Town pitch. Every claim opens to its source, and the goal is marked as our hypothesis.
6. **The board approves.** Nothing is sent.
7. **Tumble Town signs.** It is the same graph, now a client, with its history intact.
8. **Cannonball's monthly draft** hits the planted collision (risk ≈ 0.5 against Wet Paint). Q3 offers Calm Explainer open territory, and the revision clears.
9. **Retire Pixel Pond's goal.** Q5 surfaces its 2 queued drafts as stale.

Then close on the graph itself in FalkorDB Browser (`docker compose up` serves it on :3000).

The two collisions are **planted**, and this README says so. `world.json` carries `spec_seeds` and `draft_seeds`: the first technique set Producer starts from for each demo post. Two seeds deliberately borrow another business's moves. Revisions are not planted: they come from Q3 at run time. The demo never depends on a fresh LLM run producing the same collision.

## Try it as an outsider

The web app has two live inputs. *Screen a new lead* adds a synthetic lead with your audience weights and runs Q1; on a read-only deployment it screens the lead without saving it. *Double Take a draft* projects a temporary fingerprint for any technique mix, runs Q2, and deletes it.

## AI-use disclosure

Claude helped design and write this codebase. In Claude mode the agents are Claude models calling the tools above, and Claude does the Instinct-analysis extraction. The synthetic world is generated by a seeded script, not by an LLM. The research cache was gathered by a Claude agent with web search and needs a human spot-check.

## Layout

```
data/techniques.json      closed vocabulary, 80 techniques, 8 styles
data/world.json           the synthetic world (generated, committed)
data/research/*.json      cached, sourced research findings
redstring/queries.py      P1, Q0-Q5 and supporting Cypher
redstring/tools.py        named graph tools; every write writes a Decision
redstring/registry.py     tool schemas + which agent may call which
redstring/agents/         offline.py (deterministic) and claude.py (tool-use loops)
redstring/pipeline.py     the demo pipeline and revision loop
redstring/mcp_server.py   MCP server over the registry
redstring/web/            FastAPI app + static UI
redstring/worldgen.py     generates world.json
redstring/extract.py      Instinct export → closed-vocabulary references
```
