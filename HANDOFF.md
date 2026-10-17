# Handoff: what's left before the Friday 7pm ET freeze

Work from branch `main`. Before anything is pushed:

- `pytest` passes. It boots its own FalkorDB, so it needs no setup.
- `redstring check` and `redstring demo` both run clean.

Don't edit `data/world.json` by hand. Change `redstring/worldgen.py`, then run `redstring world`.

## 1. Yaz only (decisions and checks no agent should make)

- [ ] **Names.** Search all 14 business names, including Deep End Swim Club, plus "Corkboard Studio". Swap any that match a real business. The neighborhoods are real, so check names against actual businesses in Flatiron, NoMad, Gramercy Park and Chelsea. Business names live in `BUSINESSES` and neighborhood names in `NEIGHBORHOODS` in `redstring/worldgen.py`. After a swap, run `redstring world` and then `pytest`.
- [ ] **Research sources.** Open each `source_url` in `data/research/tumble-town.json` and `data/research/treble-clef.json`. The findings were taken from search snippets, not read from the pages. Fix or delete anything wrong. The after-school figure has two values: 29.6M in the file, 22.6M in the research agent's summary.
- [ ] **Hosting.** FalkorDB Cloud, or a small self-hosted server.
- [ ] **Agency and repo name.** Both are placeholders.
- [ ] **Keys.** An Anthropic API key, plus FalkorDB Cloud credentials if you choose Cloud. Give them to agents through their secrets settings, never in chat or a commit.
- [ ] **Vocabulary.** After the import (task 4), approve or reject what lands in `data/proposed_techniques.json`. Add approved techniques to `data/techniques.json` yourself. 506 proposals waiting.

## 2. Muse: the reference export

Done with a Muse export instead of Instinct (`data/reference_export.json`, 251 refs). RARE retuned to 0.75 in config.py; Q1 verdicts unchanged; all 3 collisions still fire and clear.

- [x] Export 251 analyzed short-form videos as JSON.
  - Required columns: `url`, `analysis`.
  - Kept if present: `creator`, `platform`, `format`, `analyzed_at`, `views`.
  - URLs and text only. No media.
- [x] Put the file at `data/reference_export.json`. The public-URL export was approved for commit.

## 3. Coding agent: Docker and local stack

- [ ] Run `docker compose up --build` and fix the `Dockerfile` or `docker-compose.yml` if either fails. Neither has been run yet: the build environment had no Docker.
- [ ] **Done when:**
  - http://localhost:8000 loads, and the step runner plays steps 0 to 8 without errors.
  - FalkorDB Browser at http://localhost:3000 shows `agency` plus five `client:*` graphs after step 8.

## 4. Coding agent: real references (Muse export)

Done with a Muse export instead of Instinct (`data/reference_export.json`, 251 refs). RARE retuned to 0.75 in config.py; Q1 verdicts unchanged; all 3 collisions still fire and clear.

- [x] Run `redstring import-refs data/reference_export.json --source Muse`. It writes `data/references.json` and `data/proposed_techniques.json`.
- [x] Run `redstring world && redstring seed && redstring check`.
- [ ] If `redstring world` fails its assertion ("need 3 techniques with rarity >= 0.75 in Wet Paint's style"), the real library has no rare cluster that fits Wet Paint. Fix it by changing Wet Paint's `style` in `worldgen.py` to a style that does have three. Don't touch the rarity formula.
- [x] Retune thresholds only in `redstring/config.py`, until all of the following hold:
  - `tests/test_graph.py` passes. It pins the Q1 verdict table and the three expected collisions.
  - `redstring demo` shows exactly 3 BLOCKED lines, and each one clears on revision.
- [x] Update the risk numbers quoted in `README.md` ("The demo, as it runs on the seed") to match the new run.

## 5. Coding agent: Claude mode with a real key

- [ ] Run `ANTHROPIC_API_KEY=... redstring demo --mode claude`. This path has only been tested against a scripted fake model.
- [ ] Fix any API errors in `redstring/agents/claude.py`. The likeliest spots are the `fallbacks` parameter, the `web_search_20260209` tool, and tool input schemas.
- [ ] Keep the model `claude-opus-5-5`.
- [ ] **Done when:**
  - The run finishes, and the same 3 collisions fire (their first drafts are seeded, so they should).
  - Each new pursued lead gets a `data/research/<slug>.json` with real URLs.
  - `pytest` still passes.
- [ ] Spot-check the new research files the same way as task 1.

## 6. Coding agent: deploy

- [ ] Deploy the `Dockerfile` (Render, Fly or Railway are all fine) against the FalkorDB you chose.
- [ ] Set these environment variables:
  - `FALKORDB_HOST`, `FALKORDB_PORT`, `FALKORDB_USERNAME`, `FALKORDB_PASSWORD`
  - `REDSTRING_READONLY=1` on the public link
- [ ] Keep a second, non-read-only instance, or a local run, for recording the video. The step runner is hidden in read-only mode.
- [ ] Test the public link from a logged-out browser with 3 different inputs:
  - Screen a new lead with kid-heavy audiences. Expect "pursue differentiated".
  - Screen a new lead with adults only. Expect "pursue".
  - Double Take Cannonball with Stop motion + Paint smear wipe + Handwritten titles. Expect "would be blocked".

## 7. If Friday goes well (optional)

- [ ] Territory map: the data is already served at `/api/territory`.
- [ ] Note on cooldown: a passed prospect's spec fingerprints count in Q2 for 90 days. It's implemented but not demoed.

## Saturday (Yaz)

- [ ] Video, final README pass, blog post, AI-use disclosure check. Submit by noon ET and screenshot the confirmation.
