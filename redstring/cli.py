"""redstring <command>

    world            generate data/world.json (deterministic)
    seed             seed agency + client graphs from world.json
    demo             run the whole demo pipeline (--mode offline|claude)
    step NAME        run one demo step
    check            print the seven queries' key results on the current graph
    serve            run the web app
    mcp              run the MCP server (stdio, or --http PORT)
    import-refs F    import an Instinct export (CSV/JSON) into data/references.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="redstring", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("world")
    sub.add_parser("seed")
    d = sub.add_parser("demo")
    d.add_argument("--mode", default="offline", choices=["offline", "claude"])
    s = sub.add_parser("step")
    s.add_argument("name")
    s.add_argument("--mode", default="offline", choices=["offline", "claude"])
    sub.add_parser("check")
    sv = sub.add_parser("serve")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--host", default="127.0.0.1")
    m = sub.add_parser("mcp")
    m.add_argument("--http", type=int)
    i = sub.add_parser("import-refs")
    i.add_argument("path", type=Path)
    i.add_argument("--limit", type=int)
    a = ap.parse_args(argv)

    if a.cmd == "world":
        from . import worldgen
        w = worldgen.write()
        print(f"wrote data/world.json: {len(w['businesses'])} businesses, "
              f"{sum(len(b['posts']) for b in w['businesses'])} posts, planted {w['planted']['collision_techniques']}")
    elif a.cmd == "seed":
        from . import seed
        print(seed.seed_all())
    elif a.cmd == "demo":
        from .pipeline import Pipeline
        Pipeline(a.mode).run_demo()
    elif a.cmd == "step":
        from .pipeline import Pipeline, run_step
        run_step(Pipeline(a.mode), a.name)
    elif a.cmd == "check":
        check()
    elif a.cmd == "serve":
        import uvicorn
        uvicorn.run("redstring.web.app:app", host=a.host, port=a.port)
    elif a.cmd == "mcp":
        from . import mcp_server
        sys.argv = ["redstring-mcp"] + (["--http", str(a.http)] if a.http else [])
        mcp_server.main()
    elif a.cmd == "import-refs":
        from . import extract
        print(extract.import_references(a.path, a.limit))


def check() -> None:
    """The Thursday-night checkpoint: P1 and Q0-Q5 return the expected results on the seed."""
    from . import tools
    print("Q0 signatures (Wet Paint):", [s["technique"] for s in tools.signatures("wet-paint")])
    for lead in ("byte-builders", "tumble-town", "page-turn", "crux"):
        r = tools.lead_conflict(lead)
        print(f"Q1 {lead:<14} {r['verdict']:<22} max conflict {r['max_conflict']}")
    planted = tools.world()["planted"]["collision_techniques"]
    from . import db, queries
    db.run(db.agency(), queries.P1_PROJECT_FINGERPRINT, {"draft_id": "check-draft", "kind": "draft", "client": "cannonball",
                                                         "now": tools.now(), "technique_ids": planted[:2] + ["tr_dissolve", "txt_checklist"]})
    print("P1 + Q2 Cannonball test draft:", json.dumps([{k: r[k] for k in ("business", "shared_rare", "risk", "flag")}
                                                        for r in tools.double_take("cannonball", "check-draft")]))
    db.run(db.agency(), "MATCH (f:Fingerprint {id: 'check-draft'}) DETACH DELETE f")
    print("Q3 open territory (Cannonball, Calm Explainer):",
          [r["technique"] for r in tools.open_territory("cannonball", "Calm Explainer", planted)][:5])
    for slug in db.client_slugs():
        if tools.drafts(slug):
            d = tools.drafts(slug)[-1]
            card = tools.decision_trace(slug, d["id"])
            print(f"Q4 {slug} {d['id']}: goal={card['goal']!r}, {len(card['decisions'])} decisions, {len(card['sources'])} sources")
            break
    print("Q5 stale drafts:", {s: len(tools.stale_drafts(s)) for s in db.client_slugs()})


if __name__ == "__main__":
    main()
