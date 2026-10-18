"""Deterministic agents. Same tools, same graph writes as the Claude agents, no model calls.

They make the demo reproducible and runnable with no API key. Text they write is templated from the
graph; every number in it comes from a query.
"""
from __future__ import annotations

import hashlib
import json
from statistics import mean

from .. import config, registry, seed, tools

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

HOOK_SHOT = {
    ("tumble-town", 1, 1): "Low angle on the spring floor: a gymnast counts down on her fingers, three, two, one, then cartwheels out of frame.",
    ("tumble-town", 2, 1): "Phone on a tripod facing the mat: a gymnast kicks up into a handstand, shot one still frame at a time.",
    ("tumble-town", 2, 2): "Split screen: a wobbly week-1 forward roll on the left, the clean week-8 roll on the right.",
    ("tumble-town", 3, 1): "Wide on the low beam: three kids, ages 5 to 10, line up, and the youngest steps on first.",
    ("treble-clef", 1, 1): "From the back of the recital room, turn slowly with the phone as the students take a bow.",
    ("treble-clef", 1, 2): "Lay the phone lens-up inside an open cello case, then a student lifts the cello out over it.",
    ("treble-clef", 2, 1): "Close on a small violinist's bow hand: three notes, then cut to her raised eyebrows.",
    ("treble-clef", 3, 1): "Overhead on the piano keys: a student plays the last bar of Twinkle Twinkle.",
    ("cannonball", 1, 1): "Just under the surface at the shallow end: a swimmer's face blowing a long stream of bubbles.",
    ("cannonball", 1, 2): "At the pool edge, the instructor holds up five fingers, one for each step.",
    ("pixel-pond", 1, 1): "Overhead on the coding table: the robot rolls forward, tries to turn left, and turns right instead.",
    ("pixel-pond", 2, 1): "Overhead on the build table: the half-built robot from week 1, then freeze the frame.",
}


def _names(ids):
    return {t["id"]: t for t in tools.techniques(ids)}


SCENE = {
    "Bookshop with storytime": {
        "subject": "a bookseller reading to a small group",
        "place": "in the storytime corner",
        "props": ["a picture book", "a felt bookmark", "a finger puppet"],
        "cta": "Join the next storytime session",
        "hooks": [
            "Why does this page have a tiny door?",
            "The puppet picked the book today.",
            "Three voices, one sleepy dragon.",
            "Find the hidden moon before the story ends.",
            "This picture changes when you turn the page.",
            "The dragon tiptoes past the last row.",
            "A felt bookmark becomes the dragon's tail.",
            "Everyone whispers when the moon comes out.",
        ],
    },
    "Kids art": {
        "subject": "a young painter",
        "place": "at the paint table",
        "props": ["a paintbrush", "a watercolor sheet", "a colored pencil"],
        "cta": "Book a trial art class",
        "hooks": [
            "One blue brushstroke becomes a whole sky.",
            "Which color appears when these two meet?",
            "Watch the blank paper fill from corner to corner.",
            "The paint made a shape nobody planned.",
            "A tiny line turns into a garden path.",
            "A yellow wash dries into a sunny doorway.",
            "The paper stays white where the tape was.",
            "Two brushstrokes meet at the edge.",
        ],
    },
    "Yoga": {
        "subject": "a student holding warrior pose",
        "place": "on the studio mat row",
        "props": ["a yoga block", "a yoga strap", "a folded blanket"],
        "cta": "Book a first class",
        "hooks": [
            "Can you balance through one quiet breath?",
            "Feet planted, then the whole room slows down.",
            "One small shift makes this pose steadier.",
            "Hold the pose until the breath settles.",
            "First the wobble, then the stillness.",
            "The heel settles after one careful breath.",
            "A block brings the floor a little closer.",
            "The room is quiet between each side.",
        ],
    },
    "Cafe": {
        "subject": "a barista making a latte",
        "place": "at the espresso bar",
        "props": ["a ceramic mug", "a milk pitcher", "a coffee filter"],
        "cta": "Stop in for a coffee",
        "hooks": [
            "That first pour makes a little leaf.",
            "Listen for the espresso to finish its song.",
            "The milk turns the coffee one shade lighter.",
            "One spoon, one swirl, no rush.",
            "Steam clears and the cup is ready.",
            "The crema settles before the first sip.",
            "A cold glass fogs beside the grinder.",
            "The filter blooms when the water lands.",
        ],
    },
    "Climbing gym": {
        "subject": "a beginner climber",
        "place": "beside the beginner wall",
        "props": ["a chalk bag", "a climbing shoe", "a chalk brush"],
        "cta": "Book an intro session",
        "hooks": [
            "Find the hold hiding just above your shoulder.",
            "One foot moves; the other hand waits.",
            "Can you reach the blue hold without rushing?",
            "Three moves, then a careful step down.",
            "The route starts easier than it looks.",
            "A chalked thumb tests the small blue hold.",
            "The beginner wall ends with both feet down.",
            "A quiet reach finds the next foothold.",
        ],
    },
    "Kids coding": {
        "subject": "a 7-year-old coder",
        "place": "at the coding table",
        "props": ["a small robot", "a coding card", "a USB cable"],
        "cta": "Book a trial coding class",
        "hooks": [
            "The robot keeps turning the wrong way.",
            "One small code change makes the wheels turn.",
            "Can the robot reach the paper flag?",
            "The bug is one arrow pointing backward.",
            "Watch the sensor stop the robot at the line.",
            "The wheels stop when the sensor sees tape.",
            "A single block sends the robot backward.",
            "The paper flag waits at the end of the maze.",
        ],
    },
    "Kids gymnastics": {
        "subject": "a 7-year-old gymnast",
        "place": "on the spring floor",
        "props": ["a chalk bucket", "a foam block", "a stretch band"],
        "cta": "Book a free trial class",
        "hooks": [
            "Count on your fingers, then try the roll.",
            "The beam looks wider from this end.",
            "One soft landing after three quick steps.",
            "The cartwheel starts with a careful hand.",
            "Can you stay balanced for one slow count?",
            "The foam block marks where the hands land.",
            "One bent knee turns a cartwheel into a safe finish.",
            "The smallest gymnast waits for the signal.",
        ],
    },
    "Pet grooming": {
        "subject": "a small dog getting brushed",
        "place": "at the grooming station",
        "props": ["a soft brush", "a wide-tooth comb", "a clean towel"],
        "cta": "Book a grooming visit",
        "hooks": [
            "The dog finally holds still for the brush.",
            "One quick comb finds the knot behind the ear.",
            "The towel comes off and the curls spring up.",
            "Watch the paws dry one at a time.",
            "The brush finds the soft spot every time.",
            "A damp comb smooths the curls behind one ear.",
            "The towel catches the last drops from the paws.",
            "A soft brush pauses when the dog looks up.",
        ],
    },
    "Swim lessons": {
        "subject": "a beginner swimmer",
        "place": "in the shallow end",
        "props": ["a kickboard", "a pair of goggles", "a pool noodle"],
        "cta": "Book a first lesson",
        "hooks": [
            "Blow bubbles first, then lift your face.",
            "Five fingers mark the steps to a first float.",
            "The kickboard stays still while the feet move.",
            "One breath, one reach, then a rest.",
            "Watch the bubbles reach the wall.",
            "The kickboard touches the wall after three kicks.",
            "A slow exhale sends bubbles past the goggles.",
            "The first float lasts one breath longer.",
        ],
    },
    "Tutoring": {
        "subject": "a student solving a math problem",
        "place": "at the tutoring table",
        "props": ["a dry-erase marker", "a number card", "a workbook"],
        "cta": "Book a tutoring session",
        "hooks": [
            "One changed sign fixes the whole problem.",
            "The last line finally matches the first.",
            "Check the answer by working backward.",
            "Two ways to solve the same question.",
            "A scratch-paper mistake shows where to look.",
            "A number line makes the distance visible.",
            "The student circles the sign before solving.",
            "One fraction bar shows why the halves match.",
        ],
    },
    "Bakery": {
        "subject": "a baker shaping dough",
        "place": "at the prep counter",
        "props": ["a dough scraper", "a proofing basket", "a loaf pan"],
        "cta": "Order a fresh loaf",
        "hooks": [
            "The dough springs back after one gentle press.",
            "Listen for the crust as the loaf cools.",
            "One fold turns the sticky dough smooth.",
            "The steam lifts when the oven door opens.",
            "That flour mark shows how far it rose.",
            "The dough seam faces down before the second rise.",
            "A floury thumb leaves one clear print.",
            "The loaf sounds hollow after it cools.",
        ],
    },
    "Music lessons": {
        "subject": "a young music student",
        "place": "in the lesson room",
        "props": ["a violin", "a cello bow", "a flute"],
        "cta": "Book a trial music lesson",
        "hooks": [
            "Three notes, then the bow stops together.",
            "The last note hangs in the room.",
            "One string rings louder than the others.",
            "Listen for the melody under the warm-up.",
            "A shaky start finds its rhythm by bar four.",
            "The bow rests before the violinist counts in.",
            "A cello string hums under one gentle pluck.",
            "The flute holds one note past the piano chord.",
        ],
    },
}


def _fallback_hook(client: str, slot: int, version: int, category: str) -> str:
    hooks = SCENE[category]["hooks"]
    start = int.from_bytes(hashlib.sha256(f"{client}:{slot}:{version}".encode()).digest()[:8], "big") % len(hooks)
    used = {draft["hook"] for draft in tools.drafts(client)}
    for offset in range(len(hooks)):
        hook = hooks[(start + offset) % len(hooks)]
        if hook not in used:
            return hook
    for prefix in ("One more try:", "In close-up:", "From above:", "At half speed:", "Hold the finish:"):
        for offset in range(len(hooks)):
            hook = hooks[(start + offset) % len(hooks)]
            variation = f"{prefix} {hook[0].lower()}{hook[1:]}"
            if variation not in used and len(variation.split()) <= 12:
                return variation
    raise ValueError(f"No unused fallback hooks remain for {client} ({category})")


SHOT = {
    "hook_result_first": "Begin with the finished piece in frame; pull back to reveal {subject} {place} with {prop}.",
    "str_overhead_process": "Hold the phone overhead, framing {subject} {place} as the first steps with {prop} unfold.",
    "pace_timelapse": "Set the phone on a shelf; time-lapse {subject} {place} working through {prop} from setup to finish.",
    "pace_stop_motion": "Brace the phone on a stand; take 20 stills of {subject} {place} shifting {prop} a little between frames.",
    "tr_paint_smear": "Swipe washable paint across a clear acrylic sheet, then lift it to reveal {subject} {place} with {prop}.",
    "tr_hand_cover": "Let {subject} cover the lens with a clean hand; uncover on the next action {place} with {prop} in view.",
    "txt_handwritten": "Write one opening word on a card; pair it with {subject} {place} and {prop}.",
    "col_primary_pop": "Place {subject} against a bold color; lock exposure while {prop} stays visible {place}.",
    "aud_asmr_process": "Move close enough to capture the real sound of {subject} handling {prop} {place}; mute added music.",
    "fmt_overhead_cam": "Mount the phone overhead and frame {subject} {place} arranging {prop} below.",
    "hook_myth_bust": "Show the common mistake with {prop}, then cut to {subject} {place} doing it the safe way.",
    "str_tutorial_steps": "Film one clear step at a time as {subject} {place} demonstrates {prop}.",
    "pace_slow_reveal": "Start tight on {prop}; pull back until {subject} {place} comes into view.",
    "pace_hold_long": "Hold a steady four-second take of {subject} {place} finishing one action with {prop}.",
    "tr_dissolve": "Match two still angles of {subject} {place} holding {prop}; blend them with a short dissolve.",
    "txt_lower_third": "Place a small name tag in the lower-left corner beside {subject} {place} and {prop}.",
    "txt_checklist": "Reveal three checkboxes one by one as {subject} {place} marks each step with {prop}.",
    "col_aqua_grade": "Cool the white balance slightly while {subject} and {prop} stay true-to-life {place}.",
    "aud_voiceover": "Record one calm voiceover line over {subject} using {prop} {place}.",
    "fmt_carousel": "Film {subject} {place} using {prop} from three held angles; cut between them like cards.",
    "hook_mistake_first": "Show {subject} {place} making a common mistake with {prop}; hold before the correction.",
    "hook_pov_text": "Set the phone at eye level; keep {prop} near the lower frame edge as {subject} looks into the lens {place}.",
    "str_bug_hunt": "Film {subject} checking {prop} {place}; point out the snag, then show one small fix.",
    "pace_jump_cut_talk": "Record {subject} explaining one useful point {place} with {prop} in hand; trim the pauses.",
    "pace_freeze_frame": "Pause on the exact moment {subject} uses {prop} {place}; circle the detail in the phone editor.",
    "tr_glitch": "Hold on {subject} using {prop} {place}; add two brief frame jumps before the next angle.",
    "txt_label_callouts": "Draw a short arrow to the important detail beside {subject} and {prop} {place}.",
    "txt_terminal_type": "Set one short instruction in monospace above {subject} and {prop} {place}.",
    "col_mono_accent": "Make the clip black and white; leave {prop} as the only accent beside {subject} {place}.",
    "aud_sfx_blips": "Add one quiet electronic blip when {subject} changes {prop} {place}.",
    "hook_countdown": "Frame {subject} {place} counting down with fingers; keep {prop} ready for the first move.",
    "str_challenge": "Give {subject} a timed task {place}; show the clock, {prop}, and the finish in quick cuts.",
    "pace_fast_cuts": "Follow {subject} through three distinct actions {place} with {prop}; trim each to under a second.",
    "pace_beat_sync": "Cut on four beats as {subject} {place} moves {prop} through the frame.",
    "tr_whip_pan": "Whip the phone away from {subject} {place}; land on {prop} mid-blur in the next angle.",
    "tr_zoom_punch": "Start wide on {subject} {place} with {prop}; punch into one small detail on the beat.",
    "tr_spin": "Arc the phone around {subject} {place} holding {prop}; cut when the object fills the frame.",
    "txt_kinetic_captions": "Caption each word as {subject} speaks while using {prop} {place}.",
    "col_teal_orange": "Cool the shadows and warm the highlights; keep {subject} and {prop} natural {place}.",
    "aud_trending_sound": "Set an in-app sound below the speaking voice as {subject} uses {prop} {place}.",
    "hook_overheard": "Catch {subject} saying one short line {place} while reaching for {prop}.",
    "str_day_in_life": "Follow {subject} through one real task {place}; begin with {prop} ready on the work surface.",
    "str_behind_scenes": "Film the setup before the activity starts: {subject} {place} laying out {prop}.",
    "pace_slow_mo": "Use the phone's slow-motion setting for one safe movement as {subject} works with {prop} {place}.",
    "tr_snap_cut": "Cut on a finger snap from {subject} {place} to the result, with {prop} already in frame.",
    "txt_serif_caption": "Set one small serif caption beside {subject} {place} and {prop}.",
    "col_warm_film": "Warm the tint gently in the phone editor; keep {subject}'s skin tones and {prop} true {place}.",
    "aud_lofi_bed": "Lay a quiet lo-fi instrumental under {subject} using {prop} {place}.",
    "aud_room_tone": "Record two seconds of natural sound {place} before {subject} handles {prop}.",
    "fmt_photo_dump": "Take three vertical photos of {subject} {place} with {prop}; pan slowly across them in the reel.",
    "hook_kid_voice": "Let {subject} say the opening line straight to the phone {place}; keep {prop} within reach.",
    "hook_object_reveal": "Start tight on {prop}; pull back to reveal {subject} {place} already in action.",
    "str_seamless_loop": "Film {subject} beginning and ending the same movement with {prop} {place}; match the first and last frame.",
    "pace_rewind": "Film {subject} moving {prop} in one smooth direction {place}; reverse the clip for a quick reset.",
    "tr_object_pass": "Move {prop} close until it fills the frame; start the next angle as it clears, with {subject} continuing {place}.",
    "tr_jump_through": "Set the phone low on a stable surface; follow {subject} moving across the frame {place}, with {prop} visible nearby, then cut at the edge of frame.",
    "txt_kid_drawn": "Overlay a hand-drawn label beside {subject} and {prop} {place}.",
    "txt_sticker_pop": "Pop a small sticker label beside {subject} and {prop} {place} on each key beat.",
    "col_pastel": "Lower saturation slightly; keep {subject} and {prop} against a pale background {place}.",
    "fmt_pov_cam": "Hold the phone near a child's eye line; keep {prop} low in frame as {subject} works {place}.",
    "hook_question": "Have {subject} ask one direct question to the lens {place}, with {prop} in hand.",
    "str_before_after": "Film {subject} with {prop} before the session and repeat the framing afterward {place}.",
    "str_parent_interview": "Ask one parent a short question beside {subject} {place}; keep {prop} softly in the background.",
    "str_listicle": "Keep the framing steady as {subject} points out three details of {prop} {place}, one per cut.",
    "txt_big_number": "Set one large number beside {subject} demonstrating {prop} {place}.",
    "txt_subtitle_bar": "Add a high-contrast subtitle bar under {subject} handling {prop} {place}.",
    "col_brand_block": "Use a solid brand-color card; frame {subject} and {prop} against it {place}.",
    "col_natural": "Correct exposure for {subject}'s face; keep daylight and {prop} neutral {place}.",
    "aud_interview_bed": "Record {subject} speaking clearly {place}, then lay the voice under close shots of {prop}.",
    "fmt_reel_long": "Record a full 30-second vertical take of {subject} {place} using {prop}; trim the cleanest section.",
    "hook_cold_open": "Start mid-action as {subject} {place} uses {prop}; begin recording before the movement ends.",
    "str_one_take": "Keep one unbroken take of {subject} completing the route that ends {place}, with {prop} in frame.",
    "pace_speed_ramp": "Film {subject} starting slowly and speeding up with {prop} {place}; vary the clip speed in the editor.",
    "tr_match_cut": "Frame {prop} in the same spot before and after {subject} changes the setup {place}; cut on its shape.",
    "tr_body_wipe": "Set the phone on a dry surface; catch {subject} crossing close in front of it {place}, then reveal {prop} from the next angle.",
    "col_neon_night": "Apply a restrained colored tint in the grade; keep detail visible around {subject} and {prop} {place}.",
    "col_high_key": "Lift the whites without clipping; keep {subject} and {prop} clear {place}.",
    "aud_silence_drop": "Drop the added music as {subject} sets down {prop} {place}; keep the real sound.",
    "aud_count_in": "Keep four clear count-in beats before {subject} starts with {prop} {place}.",
    "fmt_split_screen": "Record {subject} with and without {prop} from the same locked angle {place}; place the takes side by side.",
}

SUMMARY_INSTRUCTIONS = {
    "txt_handwritten": "Use a handwritten title card for the opening phrase.",
    "txt_lower_third": "Place a small name-and-role label in the lower-left corner.",
    "txt_checklist": "Reveal each checklist item as the action is completed.",
    "txt_label_callouts": "Add short labels with arrows pointing to key details.",
    "txt_terminal_type": "Set one short instruction in a clean monospace typeface.",
    "txt_kinetic_captions": "Captions appear one word at a time as the line is spoken.",
    "txt_serif_caption": "Set one short caption in a small serif typeface.",
    "txt_kid_drawn": "Overlay a hand-drawn label beside the action.",
    "txt_sticker_pop": "Pop a small sticker label in on the beat.",
    "txt_big_number": "Set one large number beside the action.",
    "txt_subtitle_bar": "Use a high-contrast subtitle bar with comfortable screen padding.",
    "col_primary_pop": "Boost the primary colors slightly; protect skin tones.",
    "col_aqua_grade": "Cool the white balance slightly; keep neutrals clean.",
    "col_mono_accent": "Make the clip monochrome and preserve one accent color.",
    "col_teal_orange": "Cool the shadows and warm the highlights.",
    "col_warm_film": "Warm the midtones gently; keep whites neutral.",
    "col_pastel": "Lower saturation slightly and lift the brightest tones.",
    "col_brand_block": "Hold a clean brand-color frame behind the title.",
    "col_natural": "Correct exposure on faces and keep daylight neutral.",
    "col_neon_night": "Apply one restrained colored tint while preserving detail.",
    "col_high_key": "Lift the whites without clipping the highlights.",
    "aud_asmr_process": "Keep the close handling sounds; mute added music.",
    "aud_voiceover": "Record one calm voiceover line above the room tone.",
    "aud_sfx_blips": "Add a quiet electronic blip on each state change.",
    "aud_trending_sound": "Set the selected in-app track below the speaking voice.",
    "aud_lofi_bed": "Add a quiet lo-fi instrumental under the dialogue.",
    "aud_room_tone": "Keep two seconds of natural room tone before the first cue.",
    "aud_interview_bed": "Keep the speaker clear above a low, even instrumental bed.",
    "aud_silence_drop": "Drop the added music on the key action; retain the real sound.",
    "aud_count_in": "Keep four clear count-in beats before the action.",
}

_PAD_SHOTS = (
    "Start on the hands as {subject} sets {prop} into position {place}.",
    "Shift to a side angle while {subject} makes one clean pass with {prop} {place}.",
    "Track the movement for a beat, then hold on {subject} finishing with {prop} {place}.",
    "Cut to a quiet detail: {prop} beside {subject} before the next action {place}.",
)


def _shot_list(client: str, technique_ids: list[str], voice: str, hook: str,
               slot: int | None = None, version: int = 1) -> str:
    business = tools.business(client)
    scene = SCENE[business["category"]]
    techniques = _names(technique_ids)
    unique_ids = list(dict.fromkeys(technique_ids))
    unknown = set(unique_ids) - SHOT.keys()
    if unknown:
        raise ValueError(f"missing shot instructions for {sorted(unknown)}")

    def render(instruction: str, shot_number: int) -> str:
        prop = scene["props"][(shot_number - 1) % len(scene["props"])]
        return instruction.format(subject=scene["subject"], place=scene["place"], prop=prop, hook=hook)

    hook_ids = [tid for tid in unique_ids if techniques[tid]["category"] == "hook"]
    custom_hook = HOOK_SHOT.get((client, slot, version)) if slot is not None else None
    if custom_hook:
        shots = [{"ids": hook_ids, "literal": custom_hook, "templates": []}]
    else:
        hook_templates = [SHOT[tid] for tid in hook_ids]
        if not hook_templates:
            hook_templates = [
                f"Open on {{subject}} beginning the action {{place}}, with {{prop}} ready as “{hook}” appears on screen."
            ]
        else:
            hook_templates.append(f"Keep “{hook}” on screen during the opening action.")
        shots = [{"ids": hook_ids, "literal": None, "templates": hook_templates}]

    for category in ("structure", "pacing", "transition", "format"):
        for tid in unique_ids:
            if techniques[tid]["category"] == category:
                shots.append({"ids": [tid], "literal": None, "templates": [SHOT[tid]]})

    pad_index = 0
    while len(shots) < 4:
        shots.append({"ids": [], "literal": None, "templates": [_PAD_SHOTS[pad_index]]})
        pad_index += 1
    if len(shots) > 6:
        for extra in shots[6:]:
            shots[5]["ids"].extend(extra["ids"])
            shots[5]["templates"].extend(extra["templates"])
        shots = shots[:6]

    shot_lines = []
    start = 0
    for index, shot in enumerate(shots, 1):
        end = start + (3 if index == 1 else 4)
        instruction = shot["literal"] or " ".join(
            render(template, index) for template in shot["templates"]
        )
        labels = [techniques[tid]["name"] for tid in shot["ids"]]
        line = f"{index} · {start}–{end}s · {instruction}"
        if labels:
            line += f" [{'; '.join(labels)}]"
        shot_lines.append(line)
        start = end

    on_screen = [f"“{hook}”"]
    on_screen.extend(f"{SUMMARY_INSTRUCTIONS[tid]} [{techniques[tid]['name']}]"
                     for tid in unique_ids if techniques[tid]["category"] == "text")
    colors = [f"{SUMMARY_INSTRUCTIONS[tid]} [{techniques[tid]['name']}]"
              for tid in unique_ids if techniques[tid]["category"] == "color"]
    audio = [f"{SUMMARY_INSTRUCTIONS[tid]} [{techniques[tid]['name']}]"
             for tid in unique_ids if techniques[tid]["category"] == "audio"]
    color_text = "; ".join(colors) or "Keep exposure consistent and preserve natural skin tones."
    audio_text = "; ".join(audio) or "Keep the room's natural sound clear."

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
        fetched_at = cache.get("fetched_at") or cache.get("researched_at")
        result_urls = set(cache.get("search_result_urls") or
                          (finding.get("source_url") for finding in cache.get("findings", [])))
        for f in cache["findings"]:
            if f.get("source_url") not in result_urls:
                continue
            fids.append(tools.record_finding(client, f["kind"], f["text"], f["source_url"], "researcher",
                                             f"From {f.get('source_title') or f['source_url']}; cached {fetched_at}",
                                             fetched_at=fetched_at)["finding"])
    else:
        aud = tools.audiences_of(client)
        audience_names = [a["audience"] for a in aud]
        audience_text = (
            audience_names[0] if len(audience_names) == 1 else
            f"{audience_names[0]} and {audience_names[1]}" if len(audience_names) == 2 else
            f"{', '.join(audience_names[:-1])}, and {audience_names[-1]}"
        )
        fids.append(tools.record_finding(
            client, "audience",
            f"Targets {audience_text}, from the lead's screening.",
            None, "researcher", "From the screening's audience paths; no web research cached.")["finding"])
    w = tools.world()
    b = seed.find_business(w, client)
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
    hook = HOOKS.get((client, slot, version)) or _fallback_hook(client, slot, version, business["category"])
    excluded = tools.referenced_reference_ids(client)
    excluded_creators = tools.referenced_reference_creators(client)
    reference_candidates = tools.references_for(
        technique_ids, limit=10, category=business["category"], exclude=excluded,
        exclude_creators=excluded_creators,
    )
    excluded_ids = set(excluded)
    used_creators = set(excluded_creators)
    available = [
        r for r in reference_candidates
        if r["id"] not in excluded_ids and r.get("creator") not in used_creators
    ]
    category = business["category"]
    group = next((categories for categories in config.CATEGORY_GROUP.values() if category in categories), [category])
    refs = [r for r in available if r["category"] == category][:2]
    if len(refs) < 2:
        selected_ids = {r["id"] for r in refs}
        group_refs = [
            r for r in available
            if r["category"] in group and r["category"] != category and r["id"] not in selected_ids
        ]
        refs.extend(group_refs[:2 - len(refs)])
    audience = [f["id"] for f in tools.findings(client, "audience")][:2]
    reference_note = (
        f"inspired by {', '.join(r['id'] for r in refs)}"
        if refs else "no close reference in the library"
    )
    rationale = f"Built on {', '.join(t['name'] for t in tools.techniques(technique_ids)[:3])}; {reference_note}."
    if revision_of:
        rationale = "Revision from open territory after a Double Take block. " + rationale
    spec = _shot_list(client, technique_ids, voice, hook, slot=slot, version=version)
    return registry._draft(client, plan_id, "reel", hook, spec, technique_ids,
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
