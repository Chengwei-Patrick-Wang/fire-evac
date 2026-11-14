"""LLM features (spec 7.5): the report card, and decisions for LLM-driven agents (sim C7, C8).

    report(batch_or_run, building) -> str                       markdown; never raises
    report_card(batch_or_run, building, allow_llm=True) -> (markdown, ai_written)
    decide(obs) -> dict | None                                  one agent (sim.brain.LLMBrain, C7)
    decide_batch(observations) -> list[dict | None]             many agents, one model call (C8)

Report card. Every number is built here, in code, from the batch/v0 or run/v0 (and the building, for
names). The model sees only the weak spots, the headline numbers and door and room names, and
writes just the headline and one fix per spot: {headline, fixes: [{id, fix}]}. A headline with a
number that is not in those facts (or the word "panic") gives way to the template headline; a fix
for an unknown id is ignored, a missing or bad one is the per-kind template fix, and a long one is
cut to 25 words. With the model off, down or slow the whole card is the template. Spots are
batch.top[:3], or for a run the 3 doors with the most person-seconds of waiting. Smoke exposure
(D10: run metrics.exposure, batch runs[].smokeSeconds and dosed; D11: batch whatIf[]) leads when
present, evacuation time second: propping the stair doors moved t90 by +0.2 s on average but smoke
exposure by +22% (measured Sat 3 AM). Long waits are framed as gaps in the building, never as
traits of people (spec 12), and the card ends with the limits line and the writer line.

Decisions. `obs` is sim/brain.py's: {idx, t, floor, x, y, profile, visibility, speed, current,
trigger, options: [{id, kind, name, dist, queue, flow, tail, assist?}]}. A decision is
{target: one of the obs's option ids, action: "go" | "reroute" | "wait", reason: str}, or None,
which means "use the rules". decide_batch makes one model call for the whole list (same length
and order back); decide(obs) is decide_batch([obs])[0]. Actions are normalized to the obs: "go"
when there is no current target, "wait" when the target is the current one, else "reroute". Each
call uses thinking "minimal" (1-5 s on gemini-3.5-flash against 5-13 s at its default) and the
client's timeout, retry and fallback rules; anything that fails is None.

    python -m backend.llm.features report [result.json [building.json]]   (default: example batch)
    python -m backend.llm.features decide                                   (three sample agents)
"""
from __future__ import annotations

import json
import math
import re
import sys
import time
from pathlib import Path

from . import client

ROOT = Path(__file__).resolve().parents[2]

# ------------------------------------------------------------------ report card

REPORT_TIMEOUT = 45.0  # s per model call (the client tries a second model after that)
REPORT_THINKING = "low"
SPOTS = 3
FIX_WORDS = 25
HEADLINE_WORDS = 30
LIMITS = (
    "Numbers come from the simulation, not the model. Illustrative fire model; rule-based agents; "
    "fixes are ideas to check with a fire protection engineer, not a compliance result."
)
WRITTEN_BY = {"gemini": "Written by Gemini", "claude": "Written by Claude"}
TEMPLATE_WRITER = "Template summary (AI unavailable)"
PRIVATE_WRITER = "Template summary (private building, not sent to AI)"
GAPS_NOTE = "Queues mark where the building runs short of capacity, not how people behave."
TEMPLATE_FIX = {
    "stair": "Keep this stair door self-closing, with any hold-open released by the alarm; test a wider "
             "door or a second stair route to cut the queue.",
    "door": "Test a wider door or a second opening here, so fewer people funnel through one doorway on "
            "the way out.",
    "exit": "Spread the load: make the other exits as easy to find and reach as this one (signs, "
            "lighting, clear routes), or widen this exit.",
    "corridor": "Widen or clear this corridor, or open a second route around it, so the flow toward the "
                "exits does not bunch up.",
    "room": "Fires starting here hurt the evacuation most: check detection and alarm coverage, and "
            "whether nearby rooms need a second way out.",
}
REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "fixes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "fix": {"type": "string"}},
                "required": ["id", "fix"],
            },
        },
    },
    "required": ["headline", "fixes"],
}

_NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
_LENGTH_UNIT = re.compile(r"\s?(?:m|cm|mm|ft|in|meters?|metres?|feet|foot|inch(?:es)?)\b", re.I)


def _num(x) -> float | None:
    """x as a finite float, else None (a bool is not a number)."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    x = float(x)
    return x if math.isfinite(x) else None


def _s(x: float) -> str:
    return f"{x:,.0f} s"


def _plural(n: float, word: str, plural: str | None = None) -> str:
    return f"{n:,.0f} {word if n == 1 else (plural or word + 's')}"


def _inside(x: float, y: float, polygon) -> bool:
    """Even-odd point-in-polygon test on a ring of [x, y] points."""
    try:
        pts = [(float(p[0]), float(p[1])) for p in polygon]
    except (TypeError, ValueError, IndexError):
        return False
    inside = False
    for (x1, y1), (x2, y2) in zip(pts, pts[-1:] + pts[:-1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


class _Names:
    """Room, door, exit and stair names of a building/v0, looked up by (floor id, id)."""

    def __init__(self, building):
        b = building if isinstance(building, dict) else {}
        self.name = str(b.get("name") or b.get("id") or "this building")
        self.rooms: dict[tuple[str, str], dict] = {}
        self.doors: dict[tuple[str, str], dict] = {}
        self.exits: dict[tuple[str, str], dict] = {}  # keyed by the exit's door id
        self.stairs: dict[tuple[str, str], dict] = {}  # keyed by the stair group
        self.stair_rooms: set[tuple[str, str]] = set()
        for f in b.get("floors") or []:
            if not isinstance(f, dict):
                continue
            fid = str(f.get("id"))
            for r in f.get("rooms") or []:
                if isinstance(r, dict) and r.get("id") is not None:
                    self.rooms[fid, str(r["id"])] = r
            for d in f.get("doors") or []:
                if isinstance(d, dict) and d.get("id") is not None:
                    self.doors[fid, str(d["id"])] = d
            for e in f.get("exits") or []:
                if isinstance(e, dict) and e.get("door") is not None:
                    self.exits[fid, str(e["door"])] = e
            for s in f.get("stairs") or []:
                if isinstance(s, dict):
                    self.stairs[fid, str(s.get("group"))] = s
                    if s.get("room") is not None:
                        self.stair_rooms.add((fid, str(s["room"])))

    def room_label(self, floor: str, rid: str) -> str:
        name = (self.rooms.get((floor, rid)) or {}).get("name")
        return f"{name} ({rid})" if name and str(name) != rid else str(rid)

    def _connects(self, floor: str, did: str) -> list[str]:
        return [str(c) for c in (self.doors.get((floor, did)) or {}).get("connects") or []]

    def _is_stair_room(self, floor: str, rid: str) -> bool:
        return (self.rooms.get((floor, rid)) or {}).get("type") == "stair" or (floor, rid) in self.stair_rooms

    def door_kind(self, floor: str, did: str) -> str:
        connects = self._connects(floor, did)
        if "outside" in connects or (floor, did) in self.exits:
            return "exit"
        if any(self._is_stair_room(floor, c) for c in connects):
            return "stair"
        return "door"

    def place(self, kind: str, floor: str, sid: str) -> str:
        """Where a weak spot is, in words: 'stair door between Corridor 2 (C2) and Stair B (SB2)'."""
        if kind == "room":
            return f"fires starting in {self.room_label(floor, sid)}"
        if kind == "corridor":
            return self.room_label(floor, sid)
        connects = self._connects(floor, sid)
        inside = [c for c in connects if c != "outside"]
        if "outside" in connects or kind == "exit":
            name = (self.exits.get((floor, sid)) or {}).get("name")
            text = f"{name}, exit" if name else "exit"
            return text + (f" from {self.room_label(floor, inside[0])}" if inside else "") + " to outside"
        noun = "stair door" if kind == "stair" else "door"
        if len(inside) >= 2:
            return f"{noun} between {self.room_label(floor, inside[0])} and {self.room_label(floor, inside[1])}"
        return noun

    def title(self, kind: str, floor: str, sid: str) -> str:
        """A weak spot's short name, for the template headline: 'the Stair B door DSB2 on F2'."""
        on = f" on {floor}" if floor else ""
        if kind == "room":
            return f"fires starting in {self.room_label(floor, sid)}{on}"
        if kind == "corridor":
            return f"{self.room_label(floor, sid)}{on}"
        if kind == "exit":
            name = (self.exits.get((floor, sid)) or {}).get("name")
            return f"exit {sid}" + (f" ({name})" if name else "") + on
        if kind == "stair":
            stair = next((self.rooms[floor, c].get("name") for c in self._connects(floor, sid)
                          if self._is_stair_room(floor, c) and (floor, c) in self.rooms), None)
            return f"the {stair} door {sid}{on}" if stair else f"stair door {sid}{on}"
        return f"door {sid}{on}"

    def stair_name(self, floor: str, group) -> str:
        stair = self.stairs.get((floor, str(group))) or {}
        room = self.rooms.get((floor, str(stair.get("room")))) or {}
        return str(room.get("name") or f"Stair {group}")

    def room_at(self, floor: str, x, y) -> str | None:
        x, y = _num(x), _num(y)
        if x is None or y is None:
            return None
        for (fid, rid), room in self.rooms.items():
            if fid == floor and _inside(x, y, room.get("polygon") or []):
                return rid
        return None


# ---------------------------------------------------------------- the facts


def _spot(names: _Names, kind: str, floor: str, sid: str, why: str) -> dict:
    return {"id": sid, "kind": kind, "floor": floor, "why": why,
            "place": names.place(kind, floor, sid), "title": names.title(kind, floor, sid)}


def _median(values: list[float]) -> float:
    """Median of values in which math.inf stands for "not reached"."""
    v = sorted(values)
    mid = len(v) // 2
    if len(v) % 2:
        return v[mid]
    a, b = v[mid - 1], v[mid]
    return (a + b) / 2 if math.isfinite(a) and math.isfinite(b) else math.inf


def _base_smoke(entry: dict, runs: list[dict]) -> float | None:
    """Mean baseline person-seconds in smoke for a what-if, when its pairs are the batch's own runs
    (or D's entry says so itself); else None, and the line gives absolute numbers only."""
    given = _num(entry.get("baseSmokeSeconds"))
    if given:
        return given
    values = [_num(r.get("smokeSeconds")) for r in runs]
    if not values or any(v is None for v in values) or entry.get("n") != len(values):
        return None
    mean = sum(values) / len(values)
    return mean if mean > 0 else None


def _whatifs(batch: dict, runs: list[dict]) -> list[dict]:
    """D11's whatIf entries as {label, smoke, t90, parts}: smoke exposure first, evacuation second."""
    out = []
    for w in batch.get("whatIf") or []:
        if not isinstance(w, dict):
            continue
        smoke, dosed = _num(w.get("dSmokeSeconds")), _num(w.get("dDosed"))
        dt90, dtrapped = _num(w.get("dT90")), _num(w.get("dTrapped"))
        smoke_text = t90_text = None
        if smoke is not None:
            base = _base_smoke(w, runs)
            per_fire = f"{smoke:+,.0f} person-seconds in smoke per fire"
            smoke_text = f"smoke exposure {100 * smoke / base:+.0f}% ({per_fire})" if base else per_fire
        if dt90 is not None:
            t90_text = f"90% out {abs(dt90):.1f} s {'later' if dt90 >= 0 else 'sooner'} on average"
            n, slower = w.get("n"), w.get("slower")
            if isinstance(n, int) and isinstance(slower, int):
                t90_text += f" (slower in {slower} of {n} fires)"
        parts = [smoke_text] if smoke_text else []
        if dosed is not None:
            parts.append(f"{dosed:+.1f} people per fire at an illustrative smoke dose of 1")
        parts += [t90_text] if t90_text else []
        if dtrapped is not None:
            parts.append(f"trapped {dtrapped:+.1f} per fire")
        if parts:
            out.append({"label": str(w.get("label") or w.get("id") or "What-if"), "smoke": smoke_text,
                        "t90": t90_text, "parts": parts})
    return out


def _batch_facts(batch: dict, names: _Names) -> dict:
    runs = [r for r in batch.get("runs") or [] if isinstance(r, dict)]
    n = len(runs)
    base = batch.get("base") if isinstance(batch.get("base"), dict) else {}
    max_time = _num(base.get("maxTime"))
    ignitions = {(str(r["ignition"].get("floor")), str(r["ignition"].get("room")))
                 for r in runs if isinstance(r.get("ignition"), dict)}
    seeds = {str(r.get("seed")) for r in runs if r.get("seed") is not None}
    sentences = [f"{_plural(n, 'fire')} simulated ({_plural(len(ignitions), 'room')} × {_plural(len(seeds), 'seed')})"]

    smoke = [_num(r.get("smokeSeconds")) for r in runs]
    dosed = [_num(r.get("dosed")) for r in runs]
    has_smoke = n > 0 and all(v is not None for v in smoke)
    has_dosed = n > 0 and all(v is not None for v in dosed)
    smoke_lead = None
    if has_smoke or has_dosed:
        clauses = []
        if has_smoke:
            mean_smoke = sum(smoke) / n
            clauses.append(f"{mean_smoke:,.0f} person-seconds in smoke per fire on average")
            smoke_lead = f"{mean_smoke:,.0f} person-seconds in smoke per fire on average across {_plural(n, 'simulated fire')}"
        if has_dosed:
            hit = sum(1 for v in dosed if v > 0)
            clauses.append(f"{sum(dosed) / n:.1f} people per fire at an illustrative smoke dose of 1 "
                           f"(in {hit} of {n} fires)")
        sentences.append("Smoke: " + "; ".join(clauses))

    if n:
        t90 = [_num(r.get("t90")) for r in runs]
        reached = [t for t in t90 if t is not None]
        missing = n - len(reached)
        median = _median(reached + [math.inf] * missing)
        limit = f"within {_s(max_time)}" if max_time else "by the end of the run"
        text = "90% out: median " + (_s(median) if math.isfinite(median) else f"not reached {limit}")
        if missing:
            text += f"; not reached {limit} in {missing} of {n} fires"
        else:
            text += f", worst {_s(max(reached))}"
        sentences.append(text)
        trapped = sum(1 for r in runs if (_num(r.get("trapped")) or 0) > 0)
        sentences.append(f"People trapped in {trapped} of {n} fires" if trapped else "No one trapped in any fire")

    spots = []
    for item in (batch.get("top") or [])[:SPOTS]:
        if isinstance(item, dict) and item.get("id") is not None:
            sid, floor = str(item["id"]), str(item.get("floor") or "")
            kind = str(item.get("kind") or names.door_kind(floor, sid))
            spots.append(_spot(names, kind, floor, sid, str(item.get("why") or "").strip()))

    whatifs = _whatifs(batch, runs)
    story = next((w for w in whatifs if w["smoke"]), None)  # the what-if story leads with exposure
    if story:
        headline = f"{story['label']}: {story['smoke']}" + (f", while {story['t90']}" if story["t90"] else "") + "."
    elif spots:
        where = spots[0]["title"]
        headline = (f"Smoke first: {smoke_lead}; the worst spot is {where}." if smoke_lead
                    else f"Worst spot across {_plural(n, 'simulated fire')}: {where}.")
    else:
        headline = f"{_plural(n, 'fire')} simulated; no weak spot stood out."
    return {
        "kind": "batch",
        "result": f"{_plural(n, 'simulated fire')}, one per ignition room and seed",
        "numbers": ". ".join(sentences) + ".",
        "smoke": has_smoke or has_dosed or story is not None,
        "whatif_story": story is not None,
        "whatif": [f"**{w['label']}:** " + "; ".join(w["parts"]) + "." for w in whatifs],
        "spots": spots,
        "headline": headline,
        "placeholder": bool(batch.get("placeholder")),
        "llm_agents": False,  # batches are rule-based only (spec 7.4)
    }


def _run_facts(run: dict, names: _Names) -> dict:
    m = run.get("metrics") if isinstance(run.get("metrics"), dict) else {}
    agents = _num(m.get("agents"))
    if agents is None:
        agents = float(len(run.get("agents") or []))
    evacuated, trapped = _num(m.get("evacuated")), _num(m.get("trapped"))
    t50, t90 = _num(m.get("t50")), _num(m.get("t90"))
    fire = run.get("fire") if isinstance(run.get("fire"), dict) else {}
    floor = str(fire.get("floor") or "")
    room = names.room_at(floor, fire.get("x"), fire.get("y")) if floor else None
    where = (f"fire in {names.room_label(floor, room)} on {floor}" if room
             else f"fire on {floor}" if floor else "one fire")
    seed = f"; seed {run['seed']}" if run.get("seed") is not None else ""
    sentences = [f"1 fire simulated ({where}{seed}; {_plural(agents, 'person', 'people')})"]

    exposure = m.get("exposure") if isinstance(m.get("exposure"), dict) else None
    smoke_lead = None
    clauses: list[str] = []
    if exposure:
        in_smoke, people = _num(exposure.get("personSecondsInSmoke")), _num(exposure.get("agentsInSmoke"))
        dosed = _num(exposure.get("dosed"))
        if in_smoke is not None:
            clauses.append(f"{in_smoke:,.0f} person-seconds in smoke")
        if people is not None:
            clauses.append(f"{people:,.0f} of {agents:,.0f} people in smoke at some point")
            smoke_lead = f"{people:,.0f} of {agents:,.0f} people spent time in smoke"
        if dosed is not None:
            clauses.append(f"{dosed:,.0f} at an illustrative smoke dose of 1")
        stairs = sorted(
            ((_num(s.get("smokeAt")), str(s.get("floor")), s.get("group"))
             for s in exposure.get("stairs") or [] if isinstance(s, dict) and _num(s.get("smokeAt")) is not None),
            key=lambda s: s[0])
        for at, sfloor, group in stairs[:2]:
            clauses.append(f"{names.stair_name(sfloor, group)} on {sfloor} smoky from {_s(at)}")
        if clauses:
            sentences.append("Smoke: " + "; ".join(clauses))

    out = []
    if evacuated is not None:
        out.append(f"{evacuated:,.0f} of {agents:,.0f} out")
    if t90 is not None:
        out.append(f"90% out at {_s(t90)}" + (f" (50% at {_s(t50)})" if t50 is not None else ""))
    else:
        frames = run.get("frames") or []
        end = _num(frames[-1].get("t")) if frames and isinstance(frames[-1], dict) else None
        out.append("90% not out " + (f"by {_s(end)}" if end else "by the end of the run"))
    sentences.append("Evacuation: " + "; ".join(out))
    if trapped is not None:
        sentences.append(f"Trapped: {trapped:,.0f}" if trapped else "No one trapped")

    doors = [d for d in m.get("doors") or []
             if isinstance(d, dict) and d.get("id") is not None and (_num(d.get("waitPersonSeconds")) or 0) > 0]
    doors.sort(key=lambda d: (-_num(d["waitPersonSeconds"]), -(_num(d.get("peakQueue")) or 0), str(d["id"])))
    spots = []
    for d in doors[:SPOTS]:
        sid, dfloor = str(d["id"]), str(d.get("floor") or "")
        why = (f"Door {sid}: peak queue {(_num(d.get('peakQueue')) or 0):,.0f}; "
               f"{_num(d['waitPersonSeconds']):,.0f} person-seconds of waiting")
        smoke_wait = _num(d.get("smokeWait"))  # D12, optional
        if smoke_wait is not None and smoke_wait >= 1:
            why += f", {smoke_wait:,.0f} of them in smoke"
        spots.append(_spot(names, names.door_kind(dfloor, sid), dfloor, sid, why))

    if spots:
        where = spots[0]["title"]
        headline = (f"{smoke_lead}; the longest queue formed at {where}." if smoke_lead
                    else f"The longest queue in this fire formed at {where}.")
    else:
        got_out = f"{evacuated:,.0f} of {agents:,.0f} people got out" if evacuated is not None else "no queue"
        headline = f"No door queued in this fire: {got_out}."
    return {
        "kind": "run",
        "result": "one simulated fire",
        "numbers": ". ".join(sentences) + ".",
        "smoke": bool(clauses),
        "whatif_story": False,
        "whatif": [],
        "spots": spots,
        "headline": headline[:1].upper() + headline[1:],
        "placeholder": False,
        "llm_agents": any(isinstance(a, dict) and a.get("llm") for a in run.get("agents") or []),
    }


def _facts(result: dict, building) -> dict | None:
    names = _Names(building)
    version = str(result.get("version") or "")
    if version.startswith("batch/") or ("top" in result and "runs" in result):
        facts = _batch_facts(result, names)
    elif version.startswith("run/") or isinstance(result.get("metrics"), dict):
        facts = _run_facts(result, names)
    else:
        return None
    facts["building"] = names.name
    return facts


# ------------------------------------------------------------ model and render


def _clean(text) -> str:
    """One line of plain text: whitespace collapsed, markdown marks and quotes trimmed."""
    if not isinstance(text, str):
        return ""
    return " ".join(text.split()).strip("*_#>`\"' ")


def _numbers(text: str) -> list[float]:
    return [float(m.replace(",", "")) for m in _NUMBER.findall(text)]


def _known(value: float, known: set[float]) -> bool:
    return any(abs(value - k) < 1e-9 or abs(value - round(k)) < 1e-9 or abs(value - round(k, 1)) < 1e-9
               for k in known)


def _good_headline(text: str, known: set[float]) -> bool:
    return (bool(text) and len(text.split()) <= HEADLINE_WORDS and "panic" not in text.lower()
            and all(_known(v, known) for v in _numbers(text)))


def _good_fix(text: str, known: set[float]) -> bool:
    """No invented statistics: each number is in the facts, a length (1.2 m), or a small count."""
    if not text or "panic" in text.lower():
        return False
    for m in _NUMBER.finditer(text):
        value = float(m.group().replace(",", ""))
        after = text[m.end():]
        if _known(value, known) or _LENGTH_UNIT.match(after):
            continue
        if value in (1, 2, 3) and not after.lstrip().startswith("%"):
            continue
        return False
    return True


def _cut(text: str, words: int) -> str:
    parts = text.split()
    if len(parts) <= words:
        return text
    return " ".join(parts[:words]).rstrip(",;:") + "..."


def _prompt(facts: dict) -> tuple[str, str]:
    """(prompt, facts text). The facts text is all the model may take numbers from."""
    payload = {
        "building": facts["building"],
        "result": facts["result"],
        "numbers": facts["numbers"],
        "whatIf": [w.replace("**", "") for w in facts["whatif"]],
        "spots": [{"id": s["id"], "kind": s["kind"], "floor": s["floor"], "where": s["place"], "why": s["why"]}
                  for s in facts["spots"]],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    first_spot = "Name the first spot (spots are listed worst first, by the simulation's ranking)"
    if facts["whatif_story"]:
        focus = "State the most striking what-if result: smoke exposure first, evacuation time second."
    elif facts["smoke"]:
        focus = ("Lead with smoke exposure, evacuation time second; you may also name the first spot "
                 "(spots are listed worst first, by the simulation's ranking).")
    else:
        focus = f"{first_spot}."
    prompt = (
        f'You write two parts of a report card for a fire evacuation simulation of the building "{facts["building"]}". '
        "The facts below come from the simulation and are already shown to the reader next to your text.\n\n"
        "Write:\n"
        f"1. headline: one sentence of at most 25 words. {focus} "
        "Use only numbers that appear in the facts, copied exactly; no number is fine too. Keep each "
        "number with what it describes: a building-wide number is not about one spot.\n"
        f"2. fixes: one per spot id, at most {FIX_WORDS} words each: a concrete change to the building "
        "at that spot, for example a wider or double door, a second door or stair route, signs that "
        "steer people to a less-used exit or stair, a layout change, or faster alarm and detection "
        "coverage. Fit each fix to its own spot instead of repeating one idea. No statistics and no "
        "predicted effects.\n\n"
        "Rules: treat long waits as gaps in the building (capacity, layout, signs), never as traits or "
        "behavior of the people in it, and never use the word panic. Stair and fire doors stay "
        "self-closing during a fire: never suggest propping or holding them open (in this simulation "
        "that lets smoke into the stairs). Plain text, no markdown. This is an illustrative "
        "simulation, not a compliance assessment.\n\n"
        f"Facts:\n{text}\n"
    )
    return prompt, text


def _ask(facts: dict) -> tuple[str | None, dict[str, str]]:
    """The model's headline (or None) and fixes by spot id, each checked; ({} and None) on failure."""
    prompt, text = _prompt(facts)
    answer = client.complete(prompt, schema=REPORT_SCHEMA, timeout=REPORT_TIMEOUT, thinking=REPORT_THINKING)
    if not isinstance(answer, dict):
        return None, {}
    known = set(_numbers(text))
    headline = _clean(answer.get("headline"))
    if headline and not _good_headline(headline, known):
        print(f"LLM report: headline dropped (number not in the facts, or too long): {headline[:120]!r}",
              file=sys.stderr)
        headline = ""
    ids = {s["id"] for s in facts["spots"]}
    fixes: dict[str, str] = {}
    for item in answer.get("fixes") or []:
        if not isinstance(item, dict):
            continue
        sid = str(item.get("id") or "").strip()
        fix = _cut(_clean(item.get("fix")), FIX_WORDS)
        if sid in ids and sid not in fixes and _good_fix(fix, known):
            fixes[sid] = fix
    return headline or None, fixes


def _render(facts: dict, headline: str, fixes: dict[str, str], writer: str) -> str:
    lines = [f"### Report card: {facts['building']}", "", f"**{headline}**", ""]
    if facts["placeholder"]:
        lines += ["*Placeholder data: these numbers are not from a simulation.*", ""]
    lines += [facts["numbers"], ""]
    if facts["spots"]:
        lines += ["#### Top weak spots", ""]
        for k, s in enumerate(facts["spots"], 1):
            where = s["place"] + (f", {s['floor']}" if s["floor"] else "")
            fix = fixes.get(s["id"]) or TEMPLATE_FIX.get(s["kind"], TEMPLATE_FIX["door"])
            lines += [f"{k}. **{s['id']}** · {where}"]
            if s["why"]:
                lines += [f"   - {s['why']}"]
            lines += [f"   - **Fix:** {fix}"]
        lines += ["", GAPS_NOTE, ""]
    else:
        lines += ["No door or stair queued in this result.", ""]
    if facts["whatif"]:
        lines += ["#### What-ifs", ""] + [f"- {w}" for w in facts["whatif"]] + [""]
    limits = LIMITS.replace("rule-based agents", "rule-based and LLM-guided agents") if facts["llm_agents"] else LIMITS
    lines += ["---", "", f"*{limits}*", "", f"*{writer}*"]
    return "\n".join(lines) + "\n"


def report_card(batch_or_run: dict, building: dict, allow_llm: bool = True) -> tuple[str, bool]:
    """(markdown, ai_written). allow_llm=False keeps the card a template (private buildings: their
    names and numbers never leave the laptop). Never raises."""
    try:
        facts = _facts(batch_or_run if isinstance(batch_or_run, dict) else {}, building)
        if facts is None:
            text = ("### Report card\n\nThis result has neither batch nor run numbers to report.\n\n"
                    f"---\n\n*{LIMITS}*\n\n*{TEMPLATE_WRITER}*\n")
            return text, False
        headline, fixes = None, {}
        if allow_llm:
            try:
                headline, fixes = _ask(facts)
            except Exception as e:  # a bug in the checks above: keep the template
                print(f"LLM report: model answer unusable ({type(e).__name__}: {e})", file=sys.stderr)
        ai = bool(headline or fixes)
        if ai:
            writer = WRITTEN_BY.get(client.provider(), "Written by AI")
        else:
            writer = TEMPLATE_WRITER if allow_llm else PRIVATE_WRITER
        return _render(facts, headline or facts["headline"], fixes, writer), ai
    except Exception as e:
        print(f"LLM report: template fallback ({type(e).__name__}: {e})", file=sys.stderr)
        return (f"### Report card\n\nThe report could not be built for this result.\n\n---\n\n*{LIMITS}*\n\n"
                f"*{TEMPLATE_WRITER}*\n"), False


def report(batch_or_run: dict, building: dict, allow_llm: bool = True) -> str:
    """Markdown report card for a batch/v0 or run/v0 on its building/v0. Never raises."""
    return report_card(batch_or_run, building, allow_llm)[0]


# ------------------------------------------------------------------ decisions

DECIDE_TIMEOUT = 30.0  # s per model call; sim.brain.LLMBrain stops waiting sooner (4 s, C8: 12 s)
DECIDE_THINKING = "minimal"
REASON_CHARS = 160
DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "i": {"type": "integer"},
                    "action": {"type": "string", "enum": ["go", "reroute", "wait"]},
                    "target": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["i", "action", "target", "reason"],
            },
        }
    },
    "required": ["decisions"],
}
_off_noted = False


def _round(x, digits: int = 1, default: float = 0.0) -> float:
    v = _num(x)
    return round(v, digits) if v is not None else default


def _compact(i: int, obs) -> dict | None:
    """What the model sees of one obs (None if it has no usable option). estS is the rules' own
    cost: walk + queue wait + the stair's extra time."""
    if not isinstance(obs, dict):
        return None
    speed = max(_num(obs.get("speed")) or 1.0, 0.2)
    options = []
    for o in obs.get("options") or []:
        if not isinstance(o, dict) or o.get("id") is None:
            continue
        dist = _num(o.get("dist")) or 0.0
        queue = _num(o.get("queue")) or 0.0
        wait = queue / max(_num(o.get("flow")) or 1.0, 0.1)
        est = dist / speed + wait + (_num(o.get("tail")) or 0.0)
        opt = {"id": str(o["id"]), "kind": o.get("kind"), "name": o.get("name"), "distM": round(dist, 1),
               "queue": round(queue), "queueWaitS": round(wait, 1), "estS": round(est, 1)}
        if o.get("assist"):
            opt["assist"] = True
        options.append(opt)
    if not options:
        return None
    current = obs.get("current")
    return {"i": i, "trigger": obs.get("trigger"), "floor": obs.get("floor"), "profile": obs.get("profile"),
            "visibilityM": _round(obs.get("visibility"), 1, 30.0), "speed": round(speed, 2),
            "current": None if current is None else str(current), "options": options}


def _decide_prompt(compact: list[dict]) -> str:
    return (
        "You steer occupants in a building fire evacuation simulation. For each observation pick one of "
        "its options (exits and stairs on that person's floor).\n"
        "Fields: i = observation index; trigger = why the person decides now (start, arrive = reached a "
        "new floor, blocked = their route is cut off, smoke = first time in thick smoke, queue = long "
        "queue at their target, tick = routine check); visibilityM = how far they can see (30 = clear "
        "air); speed in m/s; current = their current target id or null; per option: distM walking "
        "distance, queue = people waiting there, queueWaitS = expected wait, estS = estimated seconds "
        "to get through (walk + wait), assist = they need help on the stairs there.\n"
        "Choose as a sensible person would: usually the lowest estS; keep the current target unless "
        "another is clearly faster (about 20%) or the current one is smoky or blocked; in thick smoke "
        "prefer nearer options.\n"
        "Reply with one decision per observation: i; action (go when current is null, reroute to "
        "switch, wait to keep the current target); target (an option id of that observation); reason "
        "(at most 12 words, about the route: distance, queue, smoke; never about panic).\n"
        "Observations:\n" + "\n".join(json.dumps(c, separators=(",", ":"), ensure_ascii=False) for c in compact)
    )


def _decision(item, compact: dict, obs: dict) -> dict | None:
    """The model's decision checked against its obs: a known target and a consistent action."""
    ids = [o["id"] for o in compact["options"]]
    current = obs.get("current")
    current = None if current is None else str(current)
    target = str(item.get("target") or "").strip()
    action = str(item.get("action") or "").strip().lower()
    if action == "wait" and current in ids:
        target = current
    if target not in ids:
        return None
    if current is None:
        action = "go"
    elif target == current:
        action = "wait"
    else:
        action = "reroute"
    reason = " ".join(str(item.get("reason") or "").split())[:REASON_CHARS] or "model gave no reason"
    return {"target": target, "action": action, "reason": reason}


def decide_batch(observations: list[dict]) -> list[dict | None]:
    """One model call for every obs in the list; returns a list of the same length and order, each
    a decision {target, action, reason} or None (use the rules). Never raises."""
    global _off_noted
    try:
        observations = list(observations)
    except Exception:
        return []
    out: list[dict | None] = [None] * len(observations)
    try:
        if not observations:
            return out
        if client.provider() == "off":
            if not _off_noted:
                _off_noted = True
                print("LLM: LLM_PROVIDER=off; agent decisions use the rules", file=sys.stderr)
            return out
        compact = [_compact(i, o) for i, o in enumerate(observations)]
        asked = [c for c in compact if c is not None]
        if not asked:
            return out
        answer = client.complete(_decide_prompt(asked), schema=DECISION_SCHEMA,
                                 timeout=DECIDE_TIMEOUT, thinking=DECIDE_THINKING)
        if not isinstance(answer, dict):
            return out
        for item in answer.get("decisions") or []:
            if not isinstance(item, dict):
                continue
            i = item.get("i")
            if isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(out):
                continue
            if out[i] is None and compact[i] is not None:
                out[i] = _decision(item, compact[i], observations[i])
        return out
    except Exception as e:
        print(f"LLM decide: no decisions ({type(e).__name__}: {e})", file=sys.stderr)
        return [None] * len(observations)


def decide(obs: dict) -> dict | None:
    """One agent's decision {target, action, reason}, or None (use the rules). Never raises."""
    try:
        return decide_batch([obs])[0]
    except Exception:
        return None


# ------------------------------------------------------------------------ cli

SAMPLE_OBS = [  # shapes as sim/run.py builds them (values illustrative)
    {"idx": 0, "t": 30.0, "floor": "F1", "x": 5.0, "y": 5.0, "profile": "typical", "visibility": 30.0,
     "speed": 1.2, "current": None, "trigger": "start",
     "options": [{"id": "E1", "kind": "exit", "name": "Main entrance", "dist": 12.0, "queue": 2, "flow": 1.3, "tail": 0},
                 {"id": "E2", "kind": "exit", "name": "East stair exit", "dist": 30.0, "queue": 0, "flow": 1.3, "tail": 0}]},
    {"idx": 7, "t": 95.0, "floor": "F2", "x": 9.0, "y": 8.0, "profile": "older", "visibility": 3.5,
     "speed": 0.8, "current": "SA", "trigger": "smoke",
     "options": [{"id": "SA", "kind": "stair", "name": "Stair A", "dist": 6.0, "queue": 18, "flow": 1.1, "tail": 20},
                 {"id": "SB", "kind": "stair", "name": "Stair B", "dist": 16.0, "queue": 3, "flow": 1.1, "tail": 20}]},
    {"idx": 12, "t": 140.0, "floor": "F1", "x": 14.0, "y": 7.0, "profile": "visitor", "visibility": 30.0,
     "speed": 1.1, "current": "E1", "trigger": "blocked",
     "options": [{"id": "E2", "kind": "exit", "name": "East stair exit", "dist": 9.0, "queue": 4, "flow": 1.3, "tail": 0}]},
]


def _building_for(building_id) -> tuple[dict, bool]:
    """(building, private) for the CLI: data/private, then data/buildings, then the contracts example."""
    for folder, private in ((ROOT / "data" / "private", True), (ROOT / "data" / "buildings", False)):
        path = folder / f"{building_id}.json"
        if building_id and path.is_file():
            return json.loads(path.read_text(encoding="utf-8")), private
    example = ROOT / "contracts" / "building.example.json"
    return (json.loads(example.read_text(encoding="utf-8")) if example.is_file() else {}), False


def _main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # the card has × and ·; a Windows pipe is cp1252
    except Exception:
        pass
    command = argv[0] if argv else "report"
    t0 = time.time()
    if command == "report":
        path = Path(argv[1]) if len(argv) > 1 else ROOT / "contracts" / "batch.example.json"
        result = json.loads(path.read_text(encoding="utf-8"))
        if len(argv) > 2:
            building, private = json.loads(Path(argv[2]).read_text(encoding="utf-8")), False
        else:
            building, private = _building_for(result.get("buildingId"))
        markdown, ai = report_card(result, building, allow_llm=not private)
        print(markdown, end="")
        print(f"({client.provider()}, {'model ' + str(client.last_model) if ai else 'template'}, "
              f"{time.time() - t0:.1f} s)", file=sys.stderr)
        return 0
    if command == "decide":
        decisions = decide_batch(SAMPLE_OBS)
        for obs, decision in zip(SAMPLE_OBS, decisions):
            print(f"agent {obs['idx']} ({obs['trigger']}, current {obs['current']}): {decision}")
        print(f"({client.provider()}, model {client.last_model}, {time.time() - t0:.1f} s)", file=sys.stderr)
        return 0 if any(decisions) else 1
    print("usage: python -m backend.llm.features report [result.json [building.json]] | decide", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
