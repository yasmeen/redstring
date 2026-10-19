"""Generate the synthetic world once, deterministically, into data/world.json.

The NYC neighborhood names are real; the 14 businesses, their past posts, and their goals
are invented. The demo seeds from the committed world.json, so it never depends on a fresh
LLM run producing the same collision.
"""
from __future__ import annotations

import json
import random
from datetime import date, timedelta

from . import config, rarity, references

SEED = 1015
WORLD_DATE = date(2026, 10, 15)
AGENCY_NAME = "Corkboard Studio"  # placeholder; the agency is not the product
NEIGHBORHOODS = [
    {"id": "n_flatiron", "name": "Flatiron"},
    {"id": "n_nomad", "name": "NoMad"},
    {"id": "n_gramercy", "name": "Gramercy Park"},
    {"id": "n_chelsea", "name": "Chelsea"},
]
OWN_RNG = {"deep-end"}  # added later; own RNG so the pinned world doesn't reshuffle

AUDIENCES = [
    {"id": "A1", "name": "Parents of kids 3 to 6", "description": "Preschool and kindergarten families"},
    {"id": "A2", "name": "Parents of kids 7 to 12", "description": "Elementary and middle-school families"},
    {"id": "A3", "name": "Working parents who need after-school coverage", "description": "Weekday 3 to 6pm problem solvers"},
    {"id": "A4", "name": "Homeschool families", "description": "Daytime enrichment and co-ops"},
    {"id": "A5", "name": "Teens 13 to 17 and their parents", "description": "Teens choose, parents pay"},
    {"id": "A6", "name": "Local adults without kids", "description": "Neighbors, commuters, regulars"},
    {"id": "A7", "name": "Office workers near Madison Square Park", "description": "Weekday lunch and after-work crowd in Flatiron and NoMad"},
]
# Stored once per pair; queries match OVERLAPS undirected.
OVERLAPS = [("A1", "A2", 0.3), ("A1", "A3", 0.5), ("A2", "A3", 0.6), ("A2", "A4", 0.4), ("A2", "A5", 0.2),
            ("A6", "A7", 0.5)]

AGENTS = [
    {"id": "scout", "name": "Scout", "desk": "New business", "model": config.MODEL},
    {"id": "researcher", "name": "Researcher", "desk": "Research", "model": config.MODEL},
    {"id": "auditor", "name": "Auditor", "desk": "Research", "model": config.MODEL},
    {"id": "style_director", "name": "Style Director", "desk": "Creative", "model": config.MODEL},
    {"id": "strategist", "name": "Strategist", "desk": "Strategy", "model": config.MODEL},
    {"id": "producer", "name": "Producer", "desk": "Creative", "model": config.MODEL},
    {"id": "standards", "name": "Standards", "desk": "Standards", "model": config.MODEL},
    {"id": "account_manager", "name": "Account Manager", "desk": "Accounts", "model": config.MODEL},
    {"id": "board", "name": "Board", "desk": "Board", "model": "human"},
]

# Every name is a placeholder: search each before use and swap any that match a real business.
BUSINESSES = [
    # ---- signed clients
    dict(id="pixel-pond", name="Pixel Pond Code Club", category="Kids coding", status="signed",
         neighborhood="n_flatiron",
         targets={"A2": 0.8, "A3": 0.6, "A4": 0.4, "A5": 0.3},
         style="sty_nerd_deadpan", secondary="sty_night_glow",
         voice="Dry, nerdy, proud of kid projects",
         goal=dict(text="Fill 40 seats in the spring robotics session", metric="spring robotics seats", target=40, due="2027-02-01"),
         hooks=["Maya, 9, wrote a bug. Then she fixed it. Here's the bug.",
                "POV: your robot was supposed to turn left.",
                "Things our 10-year-olds shipped this week, ranked by beeps.",
                "This servo cost $4. The lesson was free.",
                "We asked a 7-year-old to explain a for-loop. She used snacks.",
                "Spring robotics: 40 seats. 12 robots already named Kevin.",
                "Your kid's first line of code, frame by frame.",
                "The robot did not win the race. It did finish.",
                "Debugging, as performed by four 8-year-olds and a tape measure.",
                "Spring robotics registration is open."],
         weak=[9]),
    dict(id="wet-paint", name="Wet Paint Kids Studio", category="Kids art", status="signed",
         neighborhood="n_chelsea",
         targets={"A1": 0.8, "A2": 0.5, "A3": 0.5},
         style="sty_messy_process", secondary="sty_cozy_local",
         voice="Messy, joyful",
         goal=dict(text="Book 12 birthday parties a month", metric="birthday parties per month", target=12, due="2027-01-31"),
         hooks=["We said one more color. It was six more colors.",
                "Birthday party, minute 1 vs minute 90.",
                "Glitter has been located in the ceiling.",
                "A 4-year-old's sunflower, start to finish.",
                "Rate this splatter wall, honestly.",
                "The aprons survived. The aprons are heroes.",
                "Painting with spaghetti: a documentary.",
                "Every kid leaves with a masterpiece and one blue elbow.",
                "Party packages for this fall.",
                "Clay day. Squish, roll, flop, repeat."],
         weak=[8]),
    dict(id="cannonball", name="Cannonball Swim School", category="Swim lessons", status="signed",
         neighborhood="n_gramercy",
         targets={"A1": 0.7, "A2": 0.6, "A3": 0.4},
         style="sty_calm_explainer", secondary="sty_parent_proof",
         voice="Calm, safety first",
         goal=dict(text="Grow the winter waitlist to 150", metric="winter waitlist size", target=150, due="2026-12-15"),
         hooks=["Three things to check before your child's first lesson.",
                "Myth: floaties teach kids to swim.",
                "From clinging to the wall to a full length, in six weeks.",
                "What a calm first lesson looks like.",
                "Our instructor ratio is 1 to 4. Here's why.",
                "Why we teach floating before kicking.",
                "Winter waitlist update.",
                "Bubbles first: how we start every lesson.",
                "One kid, one noodle, one very proud dad.",
                "The water safety rule we repeat every lesson."],
         weak=[6]),
    # ---- leads
    dict(id="byte-builders", name="Byte Builders Academy", category="Kids coding", status="lead",
         neighborhood="n_flatiron",
         targets={"A2": 0.8, "A4": 0.5}, style="sty_nerd_deadpan", secondary="sty_parent_proof",
         voice="Earnest, credential-forward",
         hypothesized_goal=dict(text="Enroll 30 students in the winter coding camp", metric="camp enrollments", target=30, due="2026-12-20"),
         hooks=["Is your kid ready for Python?", "Our coding camp in 30 seconds", "Meet our new robotics kits"]),
    dict(id="tumble-town", name="Tumble Town Gym", category="Kids gymnastics", status="lead",
         neighborhood="n_chelsea",
         targets={"A1": 0.8, "A2": 0.6}, style="sty_hype_montage", secondary="sty_kid_pov",
         voice="High energy, cheer-squad proud",
         hypothesized_goal=dict(text="Fill weekday after-school classes for ages 5 to 10", metric="weekday class enrollment", target=60, due="2027-01-15"),
         hooks=["Cartwheel progress: week 1 vs week 8", "Open gym Saturday, here's the vibe", "Can your kid do this balance beam challenge?"]),
    dict(id="treble-clef", name="Treble Clef Music School", category="Music lessons", status="lead",
         neighborhood="n_gramercy",
         targets={"A2": 0.6, "A1": 0.4}, style="sty_kid_pov", secondary="sty_cozy_local",
         voice="Warm, a little theatrical",
         hypothesized_goal=dict(text="Book 25 new trial lessons before the winter recital", metric="trial lessons booked", target=25, due="2026-12-10"),
         hooks=["First recital nerves, and how we handle them", "Guess the song from three notes", "Our tiniest violinist"]),
    dict(id="northpoint", name="Northpoint Tutoring", category="Tutoring", status="lead",
         neighborhood="n_flatiron",
         targets={"A2": 0.7, "A5": 0.6, "A4": 0.3}, style="sty_parent_proof", secondary="sty_calm_explainer",
         voice="Reassuring, results-focused",
         hypothesized_goal=dict(text="Sign 20 families to semester math packages", metric="semester packages", target=20, due="2027-01-20"),
         hooks=["Fractions in 20 seconds", "What a tutoring session actually looks like", "Report card season: three tips"]),
    dict(id="page-turn", name="Page Turn Books", category="Bookshop with storytime", status="lead",
         neighborhood="n_gramercy",
         targets={"A1": 0.6, "A6": 0.5}, style="sty_cozy_local", secondary="sty_kid_pov",
         voice="Bookish, gentle humor",
         hypothesized_goal=dict(text="Double Saturday storytime attendance", metric="storytime attendance", target=40, due="2027-01-31"),
         hooks=["Storytime this Saturday", "Staff picks for 5-year-olds", "What our booksellers are reading"]),
    dict(id="crux", name="Crux Climbing", category="Climbing gym", status="lead",
         neighborhood="n_chelsea",
         targets={"A5": 0.7, "A6": 0.6}, style="sty_night_glow", secondary="sty_hype_montage",
         voice="Stoked, community first",
         hypothesized_goal=dict(text="Sell 80 teen climb-night passes this winter", metric="teen passes", target=80, due="2027-02-28"),
         hooks=["Can you send this V2?", "Teen climb night recap", "First time on the wall"]),
    dict(id="second-rise", name="Second Rise Bakery", category="Bakery", status="lead",
         neighborhood="n_nomad",
         targets={"A6": 0.6, "A3": 0.3, "A7": 0.5}, style="sty_cozy_local", secondary="sty_messy_process",
         voice="Early-morning warm",
         hypothesized_goal=dict(text="Grow weekday preorders to 50 a day", metric="weekday preorders", target=50, due="2027-01-31"),
         hooks=["4am, first loaves out", "Croissant lamination, slowed down", "What's fresh this weekend"]),
    dict(id="corner-cup", name="Corner Cup Cafe", category="Cafe", status="lead",
         neighborhood="n_flatiron",
         targets={"A6": 0.8, "A3": 0.3, "A7": 0.7}, style="sty_cozy_local", secondary="sty_night_glow",
         voice="Friendly regulars' spot",
         hypothesized_goal=dict(text="Lift weekday afternoon sales by 20%", metric="weekday afternoon sales", target=20, due="2027-01-31"),
         hooks=["Latte art fail compilation", "Meet our regulars", "New fall menu"]),
    dict(id="still-water", name="Still Water Yoga", category="Yoga", status="lead",
         neighborhood="n_nomad",
         targets={"A6": 0.9, "A7": 0.4}, style="sty_calm_explainer", secondary="sty_cozy_local",
         voice="Quiet, unhurried",
         hypothesized_goal=dict(text="Sell 40 new intro-month passes", metric="intro passes", target=40, due="2027-01-31"),
         hooks=["Five-minute desk stretch", "Sunrise class, no talking", "What to bring to your first class"]),
    dict(id="good-boy", name="Good Boy Grooming", category="Pet grooming", status="lead",
         neighborhood="n_gramercy",
         targets={"A6": 0.7}, style="sty_kid_pov", secondary="sty_parent_proof",
         voice="Goofy, dog-obsessed",
         hypothesized_goal=dict(text="Book 30 new-client grooms a month", metric="new-client grooms", target=30, due="2027-01-31"),
         hooks=["Before and after: Biscuit's spa day", "Nail trim without the drama", "Our groomers' favorite breeds"]),
    dict(id="deep-end", name="Deep End Swim Club", category="Swim lessons", status="lead",
         neighborhood="n_gramercy",
         targets={"A1": 0.6, "A2": 0.5}, style="sty_parent_proof", secondary="sty_kid_pov",
         voice="Brisk, coach-like",
         hypothesized_goal=dict(text="Fill 24 spots in the winter learn-to-swim block", metric="winter block enrollments", target=24, due="2027-01-10"),
         hooks=["Three calm steps to your first swim lesson", "Kick, float, smile: a swimmer's first win", "Water confidence starts with one splash"]),
]

FEED = [
    dict(id="half-moon-yoga", name="Half Moon Yoga", category="Yoga", status="lead", neighborhood="n_nomad",
         targets={"A6": 0.8, "A7": 0.6}, style="sty_calm_explainer", secondary="sty_cozy_local",
         voice="Quiet, neighborly, unhurried",
         hypothesized_goal=dict(text="Sell 28 first-month passes before the December schedule begins",
                                metric="intro-month passes", target=28, due="2026-12-01"),
         hooks=["Three slow breaths, then the shoulders drop.",
                "The first balance pose wobbles too.",
                "An evening class with room to breathe."], arrives=1),
    dict(id="paper-moon-art", name="Paper Moon Art Lab", category="Kids art", status="lead",
         neighborhood="n_gramercy", targets={"A1": 0.7, "A2": 0.5},
         style="sty_messy_process", secondary="sty_cozy_local",
         voice="Playful, process-loving, reassuring",
         hypothesized_goal=dict(text="Book 18 children into the winter paper-making workshop",
                                metric="winter workshop bookings", target=18, due="2026-12-15"),
         hooks=["A blue mark becomes a paper garden.",
                "First the fold, then the tiny roof.",
                "The paper crane finally holds its wings."], arrives=2),
    dict(id="rolling-pin", name="Rolling Pin Bakehouse", category="Bakery", status="lead",
         neighborhood="n_flatiron", targets={"A6": 0.7, "A7": 0.7},
         style="sty_cozy_local", secondary="sty_messy_process",
         voice="Early-rising, warm, ingredient-proud",
         hypothesized_goal=dict(text="Take 40 holiday bread preorders by the end of November",
                                metric="holiday bread preorders", target=40, due="2026-11-30"),
         hooks=["The cinnamon knot comes from one long fold.",
                "First steam, then the crackle of crust.",
                "Today's loaves started before the streetlights."], arrives=3),
    dict(id="count-on-us", name="Count On Us Tutoring", category="Tutoring", status="lead",
         neighborhood="n_gramercy", targets={"A2": 0.7, "A3": 0.6, "A4": 0.3},
         style="sty_parent_proof", secondary="sty_calm_explainer",
         voice="Patient, encouraging, focused on small wins",
         hypothesized_goal=dict(text="Book 25 math trial sessions before winter break",
                                metric="math trial sessions", target=25, due="2026-12-18"),
         hooks=["The answer changes when the sign flips.",
                "Try the problem backward this time.",
                "One clear step makes the fraction click."], arrives=4),
    dict(id="fetch-and-fluff", name="Fetch & Fluff", category="Pet grooming", status="lead",
         neighborhood="n_chelsea", targets={"A6": 0.9},
         style="sty_kid_pov", secondary="sty_parent_proof",
         voice="Goofy, gentle, dog-first",
         hypothesized_goal=dict(text="Book 24 first-time grooming visits before the holiday week",
                                metric="first-time grooming visits", target=24, due="2026-12-20"),
         hooks=["One gentle brush finds the little tangle.",
                "The muddy paws are clean again.",
                "A towel wrap earns one slow tail wag."], arrives=5),
    dict(id="bright-lane-swim", name="Bright Lane Swim", category="Swim lessons", status="lead",
         neighborhood="n_flatiron", targets={"A1": 0.6, "A2": 0.6},
         style="sty_calm_explainer", secondary="sty_parent_proof",
         voice="Calm, safety-first, parent reassuring",
         hypothesized_goal=dict(text="Enroll 30 beginners in the December swim session",
                                metric="December beginner enrollments", target=30, due="2026-12-05"),
         hooks=["First bubbles, then a face above water.",
                "Five fingers guide the first float.",
                "The kick reaches the pool wall today."], arrives=6),
]

CTA = {
    "pixel-pond": "Spring robotics seats are open. Link in bio.",
    "wet-paint": "Book a messy birthday. Link in bio.",
    "cannonball": "Join the winter waitlist. Link in bio.",
}


def _tech_index(vocab):
    return {t["id"]: t for t in vocab["techniques"]}


def _fields(tids: list[str], idx: dict) -> dict:
    by_cat: dict[str, list[str]] = {}
    for t in tids:
        by_cat.setdefault(idx[t]["category"], []).append(t)
    fmt = by_cat.get("format", [None])[0]
    return {
        "format": {"fmt_carousel": "carousel", "fmt_photo_dump": "carousel"}.get(fmt, "reel"),
        "hook_technique": by_cat.get("hook", [None])[0],
        "structure": by_cat.get("structure", [None])[0],
        "pacing": by_cat.get("pacing", [None])[0],
        "transitions": by_cat.get("transition", []),
        "text_treatment": by_cat.get("text", [None])[0],
        "color": by_cat.get("color", [None])[0],
        "audio": by_cat.get("audio", [None])[0],
    }


def generate() -> dict:
    rng = random.Random(SEED)
    vocab = references.load_vocab()
    idx = _tech_index(vocab)
    refs = references.load()
    rar = rarity.compute(refs, list(idx))
    for t in vocab["techniques"]:
        t.update(rar[t["id"]])

    def in_style(style, rare=None, exclude=()):
        out = [t for t in vocab["techniques"] if t["style"] == style and t["id"] not in exclude]
        if rare is True:
            out = [t for t in out if t["rarity"] >= config.RARE]
        elif rare is False:
            out = [t for t in out if t["rarity"] < config.RARE]
        return [t["id"] for t in out]

    by_id = {b["id"]: b for b in BUSINESSES}

    # The planted collision: 3 techniques with rarity >= 0.75 from Wet Paint's own style cluster.
    planted = sorted(
        [t for t in in_style(by_id["wet-paint"]["style"]) if idx[t]["rarity"] >= config.PLANT_RARITY],
        key=lambda t: -idx[t]["rarity"],
    )[:3]
    assert len(planted) == 3, "need 3 techniques with rarity >= 0.75 in Wet Paint's style; re-tune the library"

    # The pitch-against-pitch collision: Tumble Town's house moves, the rarest in its style.
    tumble_rare = sorted(in_style(by_id["tumble-town"]["style"], rare=True), key=lambda t: -idx[t]["rarity"])[:3]

    reserved = set(planted)
    posts_out: dict[str, list[dict]] = {}
    for b in BUSINESSES:
        brng = random.Random(f"{SEED}:{b['id']}") if b["id"] in OWN_RNG else rng
        n = len(b["hooks"])
        weak = set(b.get("weak", []))
        own = in_style(b["style"], exclude=reserved)
        sec_common = in_style(b["secondary"], rare=False, exclude=reserved)
        plant_slots: set[int] = set()
        if b["id"] in ("wet-paint", "cannonball"):
            plant_slots = set(brng.sample([i for i in range(n) if i not in weak], 4))
        posts = []
        for i, hook in enumerate(b["hooks"]):
            if i in weak:
                commonest = sorted(in_style(b["style"], rare=False, exclude=reserved), key=lambda t: idx[t]["rarity"])
                tids = [t for t in commonest if idx[t]["category"] != "hook"][:2] + brng.sample(sec_common, 1)
            else:
                tids = brng.sample(own, brng.choice([4, 5])) + brng.sample(sec_common, brng.choice([1, 2]))
                if b["id"] == "tumble-town" and i < 2:
                    tids += [t for t in tumble_rare[:2] if t not in tids]
                if i in plant_slots:
                    tids = [t for t in tids if t in own][:3] + planted
            tids = list(dict.fromkeys(tids))
            posts.append({
                "id": f"{b['id']}-post-{i + 1:02d}",
                "hook": hook,
                "technique_ids": tids,
                **_fields(tids, idx),
                "caption": f"{hook} {CTA.get(b['id'], '')}".strip(),
                "posted_at": (WORLD_DATE - timedelta(days=7 * (n - i) + brng.randint(0, 3))).isoformat(),
                "_weak": i in weak,
                "_planted": i in plant_slots,
            })
        # Engagement: planted posts are each history's best, weak posts its worst.
        base = {"signed": 9.0, "lead": 7.6}[b["status"]]
        for p in posts:
            v = brng.lognormvariate(base, 0.35)
            if p["_planted"]:
                v *= 3.2
            if p["_weak"]:
                v *= 0.18
            p["views"] = int(v)
        # Planted posts are strictly each history's best.
        others = [p["views"] for p in posts if not p["_planted"]]
        for p in posts:
            if p["_planted"]:
                p["views"] = max(p["views"], int(max(others) * brng.uniform(1.3, 1.9)))
        for p in posts:
            save_rate = 0.045 if p["_planted"] else (0.006 if p["_weak"] else brng.uniform(0.012, 0.03))
            p["saves"] = int(p["views"] * save_rate)
        posts_out[b["id"]] = posts

    lead_feed = []
    for b in FEED:
        brng = random.Random(f"{SEED}:{b['id']}")
        own = in_style(b["style"], exclude=reserved)
        sec_common = in_style(b["secondary"], rare=False, exclude=reserved)
        posts = []
        for i, hook in enumerate(b["hooks"]):
            tids = brng.sample(own, brng.choice([4, 5])) + brng.sample(sec_common, brng.choice([1, 2]))
            tids = list(dict.fromkeys(tids))
            posts.append({
                "id": f"{b['id']}-post-{i + 1:02d}",
                "hook": hook,
                "technique_ids": tids,
                **_fields(tids, idx),
                "caption": hook,
                "posted_at": (WORLD_DATE - timedelta(days=7 * (len(b["hooks"]) - i) + brng.randint(0, 3))).isoformat(),
            })
        for post in posts:
            post["views"] = int(brng.lognormvariate(7.6, 0.35))
        for post in posts:
            post["saves"] = int(post["views"] * brng.uniform(0.012, 0.03))
        out = dict(b)
        out["synthetic"] = True
        out["posts"] = posts
        lead_feed.append(out)

    # Spec seeds: the first technique set Producer starts from for each planned spec post.
    # Two are planted collisions; README says so. Revisions come from Q3 at run time, not from here.
    def seed(style, base_rare, k_common, extra=(), exclude=()):
        commons = [t for t in in_style(style, rare=False, exclude=reserved | set(exclude))]
        return list(dict.fromkeys(list(base_rare) + rng.sample(commons, k_common) + list(extra)))

    tt, tc = by_id["tumble-town"], by_id["treble-clef"]
    kid_rare = sorted(in_style(tc["style"], rare=True), key=lambda t: -idx[t]["rarity"])
    calm_common = in_style(by_id["cannonball"]["style"], rare=False)
    spec_seeds = {
        "tumble-town": [
            {"techniques": seed(tt["style"], tumble_rare[:2], 3), "note": "Tumble Town's own house moves"},
            {"techniques": seed(tt["style"], planted[:2], 3), "note": "PLANTED: borrows the best-performing kids-art moves in Chelsea (Wet Paint's signature)"},
            {"techniques": seed(tt["style"], tumble_rare[1:3], 3), "note": "Tumble Town's own house moves"},
        ],
        "treble-clef": [
            {"techniques": seed(tt["style"], tumble_rare[:2], 2, extra=kid_rare[:1]), "note": "PLANTED: built from the same style slice as Tumble Town's spec work"},
            {"techniques": seed(tc["style"], kid_rare[1:3], 3), "note": "Treble Clef's own territory"},
            {"techniques": seed(tc["style"], kid_rare[2:4], 3), "note": "Treble Clef's own territory"},
        ],
    }
    draft_seeds = {
        "cannonball": [
            {"techniques": list(dict.fromkeys(planted[:2] + rng.sample(calm_common, 4))), "note": "PLANTED: reuses what worked best in Cannonball's history, which is Wet Paint's signature"},
        ],
    }

    businesses = []
    for b in BUSINESSES:
        out = {k: v for k, v in b.items() if k not in ("hooks", "weak")}
        out["synthetic"] = True
        out["neighborhood"] = b["neighborhood"]
        out["posts"] = posts_out[b["id"]]
        businesses.append(out)

    return {
        "_note": "SYNTHETIC. NYC neighborhood names are real; all 14 businesses, their posts, and their goals are invented for the demo.",
        "generated_with_seed": SEED,
        "world_date": WORLD_DATE.isoformat(),
        "agency": {"name": AGENCY_NAME},
        "neighborhoods": NEIGHBORHOODS,
        "audiences": AUDIENCES,
        "overlaps": [{"a": a, "b": b, "share": s} for a, b, s in OVERLAPS],
        "agents": AGENTS,
        "styles": vocab["styles"],
        "techniques": vocab["techniques"],
        "references": refs,
        "businesses": businesses,
        "lead_feed": lead_feed,
        "planted": {
            "collision_techniques": planted,
            "collision_between": ["wet-paint", "cannonball"],
            "pitch_collision_techniques": tumble_rare[:2],
            "pitch_collision_between": ["tumble-town", "treble-clef"],
        },
        "spec_seeds": spec_seeds,
        "draft_seeds": draft_seeds,
        "demo": {"pursue": ["tumble-town", "treble-clef"], "sign": "tumble-town"},
    }


def write(path=config.WORLD_PATH) -> dict:
    world = generate()
    path.write_text(json.dumps(world, indent=1) + "\n")
    return world
