"""The reference library.

Real references come from Instinct (URL plus analysis, never media) and go through
`scripts/import_references.py`, which maps each analysis onto the closed vocabulary.

Until that export is in hand, `placeholder_library()` builds a stand-in library of 200
references with a realistic long-tail technique distribution. Every placeholder is marked
`placeholder: true` and points at example.com, so nothing fake can pass for a real post.
"""
from __future__ import annotations

import json
import random

from . import config

# Per-style occurrence counts, most to least common. With N = 200 these give rarities from
# about 0.29 (45 refs) to 0.87 (1 ref), so each style has a few rare techniques.
STYLE_COUNTS = [45, 32, 24, 18, 13, 9, 6, 3, 2, 1]

# Pinned counts make the planted collision's ingredients rare enough (rarity >= 0.75).
PINNED = {
    "tr_paint_smear": 1,
    "pace_stop_motion": 2,
    "txt_handwritten": 2,
    "tr_spin": 1,
    "txt_kinetic_captions": 2,
    "hook_countdown": 3,
}

PLATFORMS = ["instagram", "tiktok"]
FORMATS = ["reel", "reel", "reel", "carousel", "short"]


def load_vocab() -> dict:
    return json.loads(config.TECHNIQUES_PATH.read_text())


def placeholder_library(n: int = 200, seed: int = 7) -> list[dict]:
    vocab = load_vocab()
    rng = random.Random(seed)
    styles = [s["id"] for s in vocab["styles"]]
    by_style = {s: [t for t in vocab["techniques"] if t["style"] == s] for s in styles}
    names = {t["id"]: t["name"] for t in vocab["techniques"]}

    refs = [
        {
            "id": f"ref_{i + 1:03d}",
            "primary_style": styles[i % len(styles)],
            "techniques": [],
        }
        for i in range(n)
    ]
    home = {s: [r for r in refs if r["primary_style"] == s] for s in styles}

    for s in styles:
        techs = by_style[s][:]
        rng.shuffle(techs)
        free = [c for c in STYLE_COUNTS]
        pinned = [t for t in techs if t["id"] in PINNED]
        for t in pinned:
            free.remove(min(free, key=lambda c: abs(c - PINNED[t["id"]])))
        counts = {t["id"]: PINNED[t["id"]] for t in pinned}
        for t, c in zip([t for t in techs if t["id"] not in PINNED], free):
            counts[t["id"]] = c
        for tid, c in counts.items():
            n_home = round(c * 0.8)
            chosen = rng.sample(home[s], min(n_home, len(home[s])))
            others = [r for r in refs if r["primary_style"] != s and r not in chosen]
            chosen += rng.sample(others, c - len(chosen))
            for r in chosen:
                r["techniques"].append(tid)

    # Every reference shows at least 3 techniques; top up from its style's commonest ones.
    common = {s: sorted(by_style[s], key=lambda t: -sum(t["id"] in r["techniques"] for r in refs)) for s in styles}
    for r in refs:
        for t in common[r["primary_style"]]:
            if len(r["techniques"]) >= 3:
                break
            if t["id"] not in r["techniques"] and t["id"] not in PINNED:
                r["techniques"].append(t["id"])

    out = []
    for i, r in enumerate(refs):
        tech = sorted(set(r["techniques"]))
        out.append({
            "id": r["id"],
            "url": f"https://example.com/placeholder/reference/{r['id']}",
            "creator": f"@placeholder_creator_{(i * 37) % 61 + 1:02d}",
            "platform": PLATFORMS[i % 2],
            "format": FORMATS[i % len(FORMATS)],
            "analyzed_by": "Instinct",
            "analyzed_at": f"2026-0{1 + i % 9}-{1 + i % 27:02d}",
            "views": int(rng.lognormvariate(10.5, 1.2)),
            "analysis": "Placeholder analysis. Uses: " + "; ".join(names[t] for t in tech) + ".",
            "techniques": tech,
            "placeholder": True,
        })
    return out


def load() -> list[dict]:
    if config.REFERENCES_PATH.exists():
        return json.loads(config.REFERENCES_PATH.read_text())
    return placeholder_library()
