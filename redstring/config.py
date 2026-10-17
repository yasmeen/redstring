"""Thresholds and names in one place, so tuning after seeding is a one-file change."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
WORLD_PATH = DATA / "world.json"
TECHNIQUES_PATH = DATA / "techniques.json"
REFERENCES_PATH = DATA / "references.json"
RESEARCH_CACHE = DATA / "research"

FALKORDB_HOST = os.environ.get("FALKORDB_HOST", "localhost")
FALKORDB_PORT = int(os.environ.get("FALKORDB_PORT", "6379"))
FALKORDB_USERNAME = os.environ.get("FALKORDB_USERNAME") or None
FALKORDB_PASSWORD = os.environ.get("FALKORDB_PASSWORD") or None

AGENCY_GRAPH = "agency"
CLIENT_PREFIX = "client:"

CATEGORY_GROUP = {
    "kids_family": [
        "Kids coding", "Kids art", "Music lessons", "Kids gymnastics",
        "Swim lessons", "Tutoring", "Bookshop with storytime",
    ],
    "food": ["Cafe", "Bakery"],
    "fitness": ["Yoga", "Climbing gym"],
    "pets": ["Pet grooming"],
}

# Rarity: rarity(t) = log(N / (1 + n_t)) / log N
RARE = 0.75           # about 2 or fewer of 200-250 references
PLANT_RARITY = 0.75   # the planted collision uses techniques at least this rare
SIGNATURE_SHARE = 0.3 # rare and in 30% or more of a business's fingerprints

# Double Take (Q2): risk = similarity x audience overlap
FLAG_RISK = 0.35

# Scout (Q1): summed conflict per signed client
DIFFERENTIATE_CONFLICT = 0.9  # at or above: pursue, but only with differentiated territory
BORDERLINE_CONFLICT = 0.5     # at or above: borderline, the board decides

# Passed prospects' spec fingerprints stop counting in Q2 after this many days
PASSED_COOLDOWN_DAYS = 90

MODEL = os.environ.get("REDSTRING_MODEL", "claude-opus-5-5")


def client_graph_name(slug: str) -> str:
    return f"{CLIENT_PREFIX}{slug}"
