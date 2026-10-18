"""Map Instinct or other analyzer exports onto the closed technique vocabulary.

Rarity only works if the vocabulary is closed, so extraction returns technique ids only. Anything that
doesn't fit goes to a proposed queue (data/proposed_techniques.json) for Yaz to approve once; extraction
never mints a Technique on its own. After approving additions to data/techniques.json, re-run the import.

Input: a CSV or JSON export with at least url and analysis; creator, platform, format, category, city,
posted_at, analyzed_at, views and duration_s are kept when present. Media is never stored.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from . import config, references

PROPOSED_PATH = config.DATA / "proposed_techniques.json"


def read_export(path: Path) -> list[dict]:
    if path.suffix.lower() == ".csv":
        with path.open(newline="") as f:
            return list(csv.DictReader(f))
    data = json.loads(path.read_text())
    return data if isinstance(data, list) else data.get("items", [])


def _models(ids: tuple[str, ...]):
    TechId = Literal[ids]  # type: ignore[valid-type]
    Category = Literal[tuple(references.load_vocab()["categories"])]  # type: ignore[valid-type]

    class Proposed(BaseModel):
        name: str
        category: Category
        why: str

    class Extraction(BaseModel):
        technique_ids: list[TechId]
        proposed: list[Proposed]

    return Extraction


def extract_one(client, analysis: str, vocab: dict, Extraction) -> dict:
    lines = "\n".join(f"{t['id']}: {t['name']} ({t['category']})" for t in vocab["techniques"])
    resp = client.messages.parse(
        model=config.MODEL,
        max_tokens=4000,
        output_config={"effort": "low"},
        system=("You map a short-form video analysis onto a closed vocabulary of creative techniques. Return only ids from "
                "the list that the analysis clearly describes. If the analysis describes a technique that is not on the "
                "list and is not a near-synonym of one that is, put it in proposed instead. 'Fast pan transition' is "
                "tr_whip_pan, not a new technique.\n\nVocabulary:\n" + lines),
        messages=[{"role": "user", "content": analysis}],
        output_format=Extraction,
    )
    out = resp.parsed_output
    return {"technique_ids": sorted(set(out.technique_ids)), "proposed": [p.model_dump() for p in out.proposed]}


def import_references(path: Path, limit: int | None = None, source: str = "Instinct", client=None) -> dict:
    vocab = references.load_vocab()
    Extraction = _models(tuple(t["id"] for t in vocab["techniques"]))
    if client is None:
        import anthropic
        client = anthropic.Anthropic()
    rows = read_export(path)[:limit]
    refs = json.loads(config.REFERENCES_PATH.read_text()) if config.REFERENCES_PATH.exists() else []
    proposed = json.loads(PROPOSED_PATH.read_text()) if PROPOSED_PATH.exists() else []
    by_url = {reference["url"]: reference for reference in refs if reference.get("url")}
    used_ids = {reference["id"] for reference in refs if reference.get("id")}
    next_id = 1
    added = 0
    for i, r in enumerate(rows, 1):
        if not r.get("url") or not r.get("analysis"):
            continue
        if r["url"] in by_url:
            continue
        try:
            ex = extract_one(client, r["analysis"], vocab, Extraction)
            views = r.get("views") or r.get("plays")
            duration = r.get("duration_s")
            while f"ref_{next_id:03d}" in used_ids:
                next_id += 1
            reference = {
                "id": f"ref_{next_id:03d}",
                "url": r["url"],
                "creator": r.get("creator") or r.get("author"),
                "platform": r.get("platform"),
                "format": r.get("format"),
                "category": r.get("category"),
                "city": r.get("city"),
                "posted_at": r.get("posted_at"),
                "duration_s": int(float(duration)) if duration not in (None, "") else None,
                "analyzed_by": source,
                "analyzed_at": r.get("analyzed_at"),
                "views": int(float(views)) if views not in (None, "") else None,
                "analysis": r["analysis"],
                "techniques": ex["technique_ids"],
            }
        except Exception as exc:
            print(f"Skipping import row {i} ({r['url']}): {exc}", file=sys.stderr)
            continue
        refs.append(reference)
        by_url[r["url"]] = reference
        used_ids.add(reference["id"])
        next_id += 1
        proposed.extend(
            candidate for candidate in ({**item, "reference": r["url"]} for item in ex["proposed"])
            if not any(old.get("reference") == candidate["reference"] and old.get("name") == candidate["name"]
                       for old in proposed)
        )
        config.REFERENCES_PATH.write_text(json.dumps(refs, indent=1) + "\n")
        PROPOSED_PATH.write_text(json.dumps(proposed, indent=1) + "\n")
        added += 1
    return {"references": len(refs), "proposed": len(proposed), "added": added}
