"""Technique rarity, computed in app code at seed time and stored on each Technique."""
import math
from collections import Counter


def rarity(n_refs: int, n_using: int) -> float:
    """rarity(t) = log(N / (1 + n_t)) / log N, clamped to [0, 1]."""
    if n_refs <= 1:
        return 0.0
    r = math.log(n_refs / (1 + n_using)) / math.log(n_refs)
    return round(max(0.0, min(1.0, r)), 4)


def compute(references: list[dict], technique_ids: list[str]) -> dict[str, dict]:
    counts = Counter(t for r in references for t in set(r["techniques"]))
    n = len(references)
    return {t: {"ref_count": counts.get(t, 0), "rarity": rarity(n, counts.get(t, 0))} for t in technique_ids}
