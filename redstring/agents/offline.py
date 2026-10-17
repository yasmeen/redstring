"""Deterministic agents. Same tools, same graph writes as the Claude agents, no model calls.

They make the demo reproducible and runnable with no API key. Text they write is templated from the
graph; every number in it comes from a query.
"""
from __future__ import annotations

import json
from statistics import mean

from .. import config, registry, tools

# Hooks for the demo's spec posts and drafts, keyed by (client, slot, version).
HOOKS = {
    ("tumble-town", 1, 1): "Three, two, one... cartwheel.",
    ("tumble-town", 2, 1): "One handstand, 40 frames, a chalk-smear wipe between each.",
    ("tumble-town", 2, 2): "Week 1 vs week 8, cut on every beat.",
    ("tumble-town", 3, 1): "The balance beam challenge, ages 5 to 10.",
    ("treble-clef", 1, 1): "Our whole recital in 15 seconds, spinning.",
    ("treble-clef", 1, 2): "What does a cello sound like from inside the case?",
    ("treble-clef", 2, 1): "A tiny violinist plays three notes. Guess the song.",
    ("treble-clef", 3, 1): "Twinkle Twinkle, played backwards, then forwards.",
    ("cannonball", 1, 1): "Bubbles first: a stop-motion guide to breathing out underwater.",
    ("cannonball", 1, 2): "Swipe through: the five steps of a calm first lesson.",
    ("pixel-pond", 1, 1): "Bug report: the robot that refused to turn left.",
    ("pixel-pond", 2, 1): "Spring robotics, explained in one freeze frame per week.",
}


def _names(ids):
    return {t["id"]: t for t in tools.techniques(ids)}


SCENE = {
    "Bookshop with storytime": {
        "subject": "a bookseller reading to a small group",
        "place": "the storytime corner",
        "prop": "an illustrated picture book",
        "cta": "Join the next storytime session",
    },
    "Kids art": {
        "subject": "a young painter",
        "place": "the paint table",
        "prop": "a loaded paintbrush",
        "cta": "Book a trial art class",
    },
    "Yoga": {
        "subject": "a student holding warrior pose",
        "place": "the studio mat row",
        "prop": "a yoga block",
        "cta": "Book a first class",
    },
    "Cafe": {
        "subject": "a barista making a latte",
        "place": "the espresso bar",
        "prop": "a ceramic mug",
        "cta": "Stop in for a coffee",
    },
    "Climbing gym": {
        "subject": "a beginner climber",
        "place": "the beginner wall",
        "prop": "a chalk bag",
        "cta": "Book an intro session",
    },
    "Kids coding": {
        "subject": "a 7-year-old coder",
        "place": "the coding table",
        "prop": "a small robot",
        "cta": "Book a trial coding class",
    },
    "Kids gymnastics": {
        "subject": "a 7-year-old gymnast",
        "place": "the spring floor",
        "prop": "a chalk bucket",
        "cta": "Book a free trial class",
    },
    "Pet grooming": {
        "subject": "a small dog getting brushed",
        "place": "the grooming station",
        "prop": "a soft brush",
        "cta": "Book a grooming visit",
    },
    "Swim lessons": {
        "subject": "a beginner swimmer",
        "place": "the shallow end",
        "prop": "a kickboard",
        "cta": "Book a first lesson",
    },
    "Tutoring": {
        "subject": "a student solving a math problem",
        "place": "the tutoring table",
        "prop": "a dry-erase marker",
        "cta": "Book a tutoring session",
    },
    "Bakery": {
        "subject": "a baker shaping dough",
        "place": "the prep counter",
        "prop": "a dough scraper",
        "cta": "Order a fresh loaf",
    },
    "Music lessons": {
        "subject": "a young music student",
        "place": "the lesson room",
        "prop": "a music stand",
        "cta": "Book a trial music lesson",
    },
}

SHOT = {
    "hook_result_first": "Frame the finished work at {place}, then pull back to reveal {subject} holding {prop}.",
    "str_overhead_process": "Set the phone above {place} and film {subject} moving {prop} through the first steps.",
    "pace_timelapse": "Lock the phone on a shelf at {place} and time-lapse {subject} using {prop} from start to finish.",
    "pace_stop_motion": "Lock the phone on a stand; shoot {subject} in 20+ stills, moving {prop} a little between each at {place}.",
    "tr_paint_smear": "Swipe washable paint across a clear sheet at {place}, then lift it to reveal {subject} using {prop}.",
    "tr_hand_cover": "Have {subject} cover the phone lens with a clean hand at {place}; uncover it on the next action with {prop}.",
    "txt_handwritten": "Write {subject}'s key word on a card and hold it beside {prop} at {place}.",
    "col_primary_pop": "Put {subject} against a bright color at {place}; lock exposure so {prop} stays clear.",
    "aud_asmr_process": "Move the phone close enough to record {subject} handling {prop} at {place}; mute added music.",
    "fmt_overhead_cam": "Prop the phone overhead at {place} and frame {subject} arranging {prop} below.",
    "hook_myth_bust": "Film {subject} showing the usual wrong step with {prop} at {place}, then demonstrate the safer way.",
    "str_tutorial_steps": "Film {subject} demonstrating one clear step at a time with {prop} at {place}.",
    "pace_slow_reveal": "Start tight on {prop}, then slowly widen to reveal {subject} at {place}.",
    "pace_hold_long": "Hold the phone steady for four seconds as {subject} completes one action with {prop} at {place}.",
    "tr_dissolve": "Film {subject} holding {prop} still at {place}; fade into the next angle in the phone editor.",
    "txt_lower_third": "Add a small name-and-role label at lower left while {subject} demonstrates {prop} at {place}.",
    "txt_checklist": "Overlay three checkboxes for the steps {subject} performs with {prop} at {place}.",
    "col_aqua_grade": "Cool the white balance slightly; keep {subject} and {prop} naturally lit at {place}.",
    "aud_voiceover": "Record one calm voiceover line over {subject} using {prop} at {place}.",
    "fmt_carousel": "Film {subject} using {prop} at {place} from three held angles, then cut between them like cards.",
    "hook_mistake_first": "Show {subject} making a common mistake with {prop} at {place}, then pause before fixing it.",
    "hook_pov_text": "Hold the phone at {subject}'s eye level at {place}, with {prop} filling the near edge of frame.",
    "str_bug_hunt": "Film {subject} checking {prop} at {place}, pointing to the failure, then testing the fix.",
    "pace_jump_cut_talk": "Record {subject} explaining one sentence at {place} while holding {prop}; trim the pauses between phrases.",
    "pace_freeze_frame": "Pause on {subject} holding {prop} at {place}, then circle the detail in the phone editor.",
    "tr_glitch": "Hold on {subject} using {prop} at {place}; insert two very short frame jumps before the next view.",
    "txt_label_callouts": "Draw short arrows from labels to {subject} and {prop} at {place}.",
    "txt_terminal_type": "Type one short instruction above {subject} using {prop} at {place}, in a simple monospace style.",
    "col_mono_accent": "Turn the clip black and white, leaving {prop} as the only color beside {subject} at {place}.",
    "aud_sfx_blips": "Add one quiet electronic blip each time {subject} changes {prop} at {place}.",
    "hook_countdown": "Film {subject} raising three fingers at {place}, with {prop} ready in frame.",
    "str_challenge": "Film {subject} trying one timed task with {prop} at {place}, then show the finish.",
    "pace_fast_cuts": "Record {subject} doing three short actions with {prop} at {place}; trim each to under a second.",
    "pace_beat_sync": "Film {subject} moving {prop} in four beats at {place}; cut on each beat of the sound.",
    "tr_whip_pan": "Whip the camera sideways off {subject} at {place} and land on the next shot mid-blur, with {prop} in frame.",
    "tr_zoom_punch": "Start wide on {subject} with {prop} at {place}, then punch in on the key detail.",
    "tr_spin": "Circle the phone around {prop} held by {subject} at {place}; cut when the object fills the frame.",
    "txt_kinetic_captions": "Show one word at a time from {subject}'s line as they use {prop} at {place}.",
    "col_teal_orange": "Cool the shadows and warm the highlights in the phone editor; keep {subject} and {prop} natural at {place}.",
    "aud_trending_sound": "Choose an in-app sound below speaking volume while {subject} uses {prop} at {place}.",
    "hook_overheard": "Film {subject} at {place} saying a short line while reaching for {prop}.",
    "str_day_in_life": "Record {subject} arriving at {place}, setting down {prop}, then beginning the first task.",
    "str_behind_scenes": "Film {subject} preparing {prop} at {place} before the activity starts.",
    "pace_slow_mo": "Use the phone's slow-motion setting as {subject} moves {prop} through the frame at {place}.",
    "tr_snap_cut": "Film {subject} snapping fingers at {place} with {prop} in frame; cut to the result on the snap.",
    "txt_serif_caption": "Add one small serif caption naming {subject}'s action with {prop} at {place}.",
    "col_warm_film": "Warm the tint slightly in the phone editor; keep {subject} and {prop} in window light at {place}.",
    "aud_lofi_bed": "Add a quiet in-app instrumental under {subject} using {prop} at {place}.",
    "aud_room_tone": "Record two seconds of the real sound at {place} before {subject} handles {prop}.",
    "fmt_photo_dump": "Take three vertical photos of {subject} using {prop} at {place}, then pan through them in the reel.",
    "hook_kid_voice": "Let {subject} say the first sentence to the phone at {place}, holding {prop}.",
    "hook_object_reveal": "Start tight on {prop}, then pull back to reveal {subject} at {place}.",
    "str_seamless_loop": "Film {subject} beginning and ending the same movement with {prop} at {place}, matching the frame.",
    "pace_rewind": "Film {subject} sliding {prop} across the work surface at {place}, then reverse the clip in the editor.",
    "tr_object_pass": "Have {subject} pass {prop} over the phone lens at {place}; start the next angle as it moves away.",
    "tr_jump_through": "Set the phone low at {place}; film {subject} stepping across the frame toward {prop}, then cut at the crossing.",
    "txt_kid_drawn": "Let {subject} draw a label for {prop} on paper at {place}; overlay the drawing beside the clip.",
    "txt_sticker_pop": "Place a small sticker label beside {subject} and {prop} at {place} on each key beat.",
    "col_pastel": "Place {subject} and {prop} against a pale backdrop at {place}; lower saturation slightly.",
    "fmt_pov_cam": "Hold the phone at {subject}'s eye level at {place}, with {prop} near the bottom of frame.",
    "hook_question": "Frame {subject} looking into the phone at {place} while holding {prop}.",
    "str_before_after": "Film {subject} with {prop} before the session at {place}, then repeat the same framing after.",
    "str_parent_interview": "Record {subject} answering one short question beside {prop} at {place}, with the phone at eye level.",
    "str_listicle": "Film {subject} pointing to three useful details of {prop} at {place}, one at a time.",
    "txt_big_number": "Put one large number beside {subject} demonstrating {prop} at {place}.",
    "txt_subtitle_bar": "Add a high-contrast subtitle bar beneath {subject} while they handle {prop} at {place}.",
    "col_brand_block": "Place {subject} against a solid brand-color board at {place}, keeping {prop} in the foreground.",
    "col_natural": "Face {subject} toward a window at {place}; tap to expose for their face and {prop}.",
    "aud_interview_bed": "Record {subject} speaking clearly at {place}, then lay the voice under close shots of {prop}.",
    "fmt_reel_long": "Capture a 30-second vertical take of {subject} using {prop} at {place}; select a clean section for this cut.",
    "hook_cold_open": "Start mid-action as {subject} uses {prop} at {place}; begin recording before the movement finishes.",
    "str_one_take": "Keep recording as {subject} carries {prop} from the entrance of {place} to the work area.",
    "pace_speed_ramp": "Film {subject} starting slowly and accelerating with {prop} at {place}; vary clip speed in the editor.",
    "tr_match_cut": "Frame {prop} in the same spot at {place} before and after {subject} changes the setup; cut on its shape.",
    "tr_body_wipe": "Have {subject} walk close past the phone at {place} to cover the frame, then reveal {prop} from the next angle.",
    "col_neon_night": "Turn on one colored light at {place}; keep {subject} and {prop} visible against the darker background.",
    "col_high_key": "Face {subject} toward a bright window at {place}; expose for a clean background around {prop}.",
    "aud_silence_drop": "Mute the added music as {subject} sets down {prop} at {place}; keep the real sound.",
    "aud_count_in": "Record {subject} clapping four count-in beats beside {prop} at {place}; start the action on the last clap.",
    "fmt_split_screen": "Record {subject} with and without {prop} at {place} from the same angle; place the takes side by side.",
}

_PAD_SHOTS = (
    "Open close on {subject} beginning the action at {place}, with {prop} clearly in frame.",
    "Move the phone closer as {subject} uses {prop} at {place}.",
    "Hold on {subject} finishing the action beside {prop} at {place}.",
    "End the sequence with {subject} setting down {prop} at {place}.",
)


def _shot_list(client: str, technique_ids: list[str], voice: str, hook: str) -> str:
    business = tools.business(client)
    scene = SCENE[business["category"]]
    techniques = _names(technique_ids)
    unique_ids = list(dict.fromkeys(technique_ids))
    unknown = set(unique_ids) - SHOT.keys()
    if unknown:
        raise ValueError(f"missing shot instructions for {sorted(unknown)}")

    hook_ids = [tid for tid in unique_ids if techniques[tid]["category"] == "hook"]
    hook_instruction = " ".join(SHOT[tid].format(**scene) for tid in hook_ids)
    if not hook_instruction:
        hook_instruction = "Open on {subject} beginning the action at {place}, with {prop} clearly in frame.".format(**scene)
    shots = [[hook_ids, hook_instruction]]
    for category in ("structure", "pacing", "transition", "format"):
        for tid in unique_ids:
            if techniques[tid]["category"] == category:
                shots.append([[tid], SHOT[tid].format(**scene)])

    while len(shots) < 4:
        pad = _PAD_SHOTS[(len(shots) - 1) % len(_PAD_SHOTS)].format(**scene)
        shots.append([[], pad])
    if len(shots) > 6:
        for technique_labels, instruction in shots[6:]:
            shots[5][0].extend(technique_labels)
            shots[5][1] += f" Then {instruction}"
        shots = shots[:6]

    shot_lines = []
    start = 0
    for index, (ids, instruction) in enumerate(shots, 1):
        end = start + (3 if index == 1 else 4)
        labels = [techniques[tid]["name"] for tid in ids]
        line = f"{index} · {start}–{end}s · {instruction}"
        if labels:
            line += f" [{'; '.join(labels)}]"
        shot_lines.append(line)
        start = end

    on_screen = [f"“{hook}”"]
    on_screen.extend(f"{SHOT[tid].format(**scene)} [{techniques[tid]['name']}]"
                     for tid in unique_ids if techniques[tid]["category"] == "text")
    colors = [f"{SHOT[tid].format(**scene)} [{techniques[tid]['name']}]"
              for tid in unique_ids if techniques[tid]["category"] == "color"]
    audio = [f"{SHOT[tid].format(**scene)} [{techniques[tid]['name']}]"
             for tid in unique_ids if techniques[tid]["category"] == "audio"]
    color_text = "; ".join(colors) or "Keep the phone's white balance steady for the scene"
    audio_text = "; ".join(audio) or "Keep the room's natural sound"

    return "\n".join([
        f"Voice: {voice}",
        *shot_lines,
        f"On screen: {'; '.join(on_screen)}",
        f"Color: {color_text} · Audio: {audio_text}",
        f"End card: {scene['cta']}",
    ])


# ------------------------------------------------------------------ Scout

def scout(leads: list[str], pursue: list[str]) -> list[dict]:
    out = []
    for lead in leads:
        res = tools.screen_lead(lead)
        out.append(res)
    for slug in pursue:
        verdict = next(r for r in out if r["lead"] == slug)
        tools.pursue(slug, "scout", f"Verdict {verdict['verdict']}: {verdict['reason']}")
    return out


# ------------------------------------------------------------------ Researcher

def researcher(client: str) -> dict:
    path = config.RESEARCH_CACHE / f"{client}.json"
    fids = []
    if path.exists():
        cache = json.loads(path.read_text())
        for f in cache["findings"]:
            fids.append(tools.record_finding(client, f["kind"], f["text"], f["source_url"], "researcher",
                                             f"From {f.get('source_title') or f['source_url']}")["finding"])
    else:
        aud = tools.audiences_of(client)
        fids.append(tools.record_finding(
            client, "audience",
            f"Targets {', '.join(a['audience'] for a in aud)}. [offline placeholder: no cached research; run with an API key for live web research]",
            None, "researcher", "Placeholder finding, labeled as such.")["finding"])
    w = tools.world()
    b = next(x for x in w["businesses"] if x["id"] == client)
    g = b.get("hypothesized_goal") or b["goal"]
    status = "hypothesized" if b["status"] != "signed" else "active"
    goal = tools.record_goal(client, g["text"], g["metric"], g["target"], g["due"], status, fids, "researcher",
                             f"Inferred from {len(fids)} findings on the category and audience; shown in the pitch as a hypothesis.")
    return {"findings": fids, "goal": goal["goal"]}


# ------------------------------------------------------------------ Auditor

def auditor(client: str) -> dict:
    if not tools.posts(client):
        tools.load_client_posts(client)
    ps = tools.posts(client)
    for p in ps:
        p["save_rate"] = p["saves"] / max(1, p["views"])
    names = _names(sorted({t for p in ps for t in p["techniques"]}))
    best = max(ps, key=lambda p: p["views"])
    worst = min(ps, key=lambda p: p["views"])
    avg_views = mean(p["views"] for p in ps)
    worst_hooks = [t for t in worst["techniques"] if names[t]["category"] == "hook"]
    shared_top = set.intersection(*[set(p["techniques"]) for p in sorted(ps, key=lambda p: -p["views"])[:3]])
    found = [
        {"text": f"Best post: \"{best['hook']}\" with {best['views']:,} views ({best['save_rate']:.1%} saves), "
                 f"{best['views'] / avg_views:.1f}x the average of {avg_views:,.0f}."
                 + (f" The top three posts share {', '.join(names[t]['name'] for t in shared_top)}." if shared_top else "")},
        {"text": f"Weakest post: \"{worst['hook']}\" with {worst['views']:,} views ({worst['save_rate']:.1%} saves)."
                 + (" It has no hook technique in the opening seconds." if not worst_hooks else
                    f" Its hook is {names[worst_hooks[0]]['name']}.")},
    ]
    rare_used = sorted({t for p in ps for t in p["techniques"] if names[t]["rarity"] >= config.RARE},
                       key=lambda t: -names[t]["rarity"])
    if rare_used:
        found.append({"text": f"Distinctive moves already in the history: {', '.join(names[t]['name'] for t in rare_used[:4])}."})
    summary = f"Reviewed {len(ps)} posts. Average {avg_views:,.0f} views; best {best['views']:,}, weakest {worst['views']:,}."
    return tools.record_audit(client, summary, [p["id"] for p in ps], found)


# ------------------------------------------------------------------ Style Director

def style_director(client: str, flag: dict | None = None) -> dict:
    style = registry._style_of(client)["primary_style"]
    avoid = list(flag["shared_ids"]) if flag else []
    prev = tools.taste_profile(client)
    if prev:
        avoid = sorted(set(avoid) | {a["id"] for a in prev["avoids"]})
    territory = tools.open_territory(client, style, avoid)
    prefers = {t["technique_id"]: round(min(1.0, 0.4 + t["rarity"] / 2), 2) for t in territory[:6]}
    audit = tools.findings(client, "audit")
    if flag:
        summary = (f"Revised after Double Take: avoid {', '.join(flag['shared'])} ({flag['with_business']}'s territory). "
                   f"Open territory in {style}: {', '.join(t['technique'] for t in territory[:3])}.")
        based = [("CollisionFlag", flag["id"])]
    else:
        summary = f"Home style {style}. Rarest open techniques: {', '.join(t['technique'] for t in territory[:3])}."
        based = [("Finding", f["id"]) for f in audit]
    return tools.set_taste_profile(client, prefers, avoid, summary, based)


# ------------------------------------------------------------------ Strategist

def strategist(client: str, period: str) -> dict:
    gs = [g for g in tools.goals(client) if g["status"] in ("active", "hypothesized")]
    goal = gs[-1]
    tp = tools.taste_profile(client)
    rationale = (f"Serves \"{goal['text']}\" ({goal['status']}). "
                 f"Leans on {', '.join(p['name'] for p in tp['prefers'][:3])} from the taste profile." if tp else
                 f"Serves \"{goal['text']}\".")
    return {**tools.write_plan(client, period, goal["id"], rationale), "goal": goal["id"]}


# ------------------------------------------------------------------ Producer

def producer(client: str, plan_id: str, slot: int, technique_ids: list[str], kind: str,
             revision_of: str | None = None, version: int = 1) -> dict:
    voice = registry._style_of(client)["voice"]
    business = tools.business(client)
    hook = HOOKS.get((client, slot, version)) or f"{business['name']}, take {version}"
    excluded = tools.referenced_reference_ids(client)
    reference_candidates = tools.references_for(
        technique_ids, category=business["category"], exclude=excluded
    )
    excluded_ids = set(excluded)
    available = [r for r in reference_candidates if r["id"] not in excluded_ids]
    category_reference = next((r for r in available if r["category"] == business["category"]), None)
    refs = [category_reference or available[0]] if available else []
    audience = [f["id"] for f in tools.findings(client, "audience")][:2]
    rationale = (f"Built on {', '.join(t['name'] for t in tools.techniques(technique_ids)[:3])}; "
                 f"inspired by {', '.join(r['id'] for r in refs) or 'no references'}.")
    if revision_of:
        rationale = "Revision from open territory after a Double Take block. " + rationale
    return registry._draft(client, plan_id, "reel", hook, _shot_list(client, technique_ids, voice, hook), technique_ids,
                           [r["id"] for r in refs], rationale, kind=kind, revision_of=revision_of,
                           based_on_findings=audience)


def revise_techniques(client: str, old: list[str], flag: dict) -> list[str]:
    """Drop the flagged techniques, then fill from the taste profile's open territory."""
    tp = tools.taste_profile(client)
    avoid = {a["id"] for a in tp["avoids"]} | set(flag["shared_ids"])
    keep = [t for t in old if t not in avoid]
    for p in sorted(tp["prefers"], key=lambda p: -p["weight"]):
        if len(keep) >= len(old):
            break
        if p["id"] not in keep and p["id"] not in avoid:
            keep.append(p["id"])
    return keep


# ------------------------------------------------------------------ Standards

def standards(client: str, draft_id: str) -> dict:
    return tools.check_draft(client, draft_id)


# ------------------------------------------------------------------ Account Manager

def account_manager(client: str) -> dict:
    goal = next(g for g in tools.goals(client) if g["status"] in ("hypothesized", "active"))
    ds = [d for d in tools.drafts(client) if d["status"] in ("queued", "approved") and d["kind"] == "spec"]
    claims = tools.findings(client, "audience")[:3] + tools.findings(client, "channel")[:1] + tools.findings(client, "audit")[:2]
    b = tools.business(client)
    angle = (f"{b['name']}: three spec posts in territory no one else on your parents' feeds is using, "
             f"aimed at \"{goal['text']}\" (our hypothesis).")
    return tools.write_pitch(client, angle, [d["id"] for d in ds], [c["id"] for c in claims], goal["id"],
                             f"{len(claims)} cited findings, {len(ds)} spec posts that cleared Double Take.")
