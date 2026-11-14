"""Demo precompute: the runs, batches and report cards the static site shows (spec 8, task A5).

    python tools/precompute_demo.py --building example-office --propped-door DSA1 --rooms R101,R102
    python tools/precompute_demo.py --all --thin          every public building with its demo defaults
    python tools/precompute_demo.py --building office --batch data/runs/batch-office.json
                                                          D's finished batch instead of a batch of our own
    python tools/precompute_demo.py --live-reports        new report cards with Gemini, no simulation
    python tools/precompute_demo.py --refresh-reports     the template cards again (its wording changed), no simulation

Per building it makes
    1. one batch (fire.batch.run_many): a fire in every room that is not a corridor or a stair
       (--max-rooms N keeps N evenly spaced ones), seeds 1, 2, 3, rule-based agents;
    2. the what-if sweep and the measured fixes on the worst rooms (--sweep-rooms N, --no-sweeps);
    3. a baseline and a "propped" run for each of the 4 highest-riskT90 rooms plus the first kitchen (a
       building with no kitchen room, like the NIBS office, gets the room its scenario file lights the fire
       in) or the --rooms you name: same seed and same people, scenario doors that differ only in --propped-door,
       closed against propped (default: the stair door with the highest batch score, never an
       exterior one). The index lists the pair whose propped run adds the most person-seconds in smoke
       first, because the demo's tour plays a building's first baseline and its propped partner as the
       what-if scene; --rooms keeps the order you give;
    4. the batch's report card, written from the template: LLM_PROVIDER is forced to off here.
   --live-reports is a separate mode: it rewrites report-*.md with Gemini from the batches already
   in the demo folder, never simulating and never replacing a card by a worse one (see live_reports).

Files go to frontend/public/demo/ (or --out), next to what frontend/scripts/sync-demo.mjs keeps there:
    building-ID.json         a copy of the public building (building.example.json for the example, the
                             name sync-demo uses, so the two never rewrite each other's index entry)
    run-ID-ROOM-base.json    baseline run (ID is the building id)
    run-ID-ROOM-propped.json the same fire with --propped-door propped
    batch-ID.json            batch/v0 with whatIf and fixes when the sweeps ran
    report-ID.md             the report card
    headlines-ID.json        D18's headline numbers pack, only when fire/headlines.py is on the branch; made from
                             this very batch, never copied from an older file
    index.json               demo-index/v0, merged by id: entries of other buildings, and of the files
                             sync-demo writes, are kept; the placeholder example batch is dropped as
                             soon as a real batch exists for its building (the same rule sync-demo has)
A rerun for a building replaces its earlier run-, batch- and report- files, so nothing stale is left, and
keeps the other keys of its batch entry. With the default --out the batch is also saved as
data/runs/batch-ID.json (gitignored): the file sync-demo.mjs --runs (E28) copies into the demo, so this tool is
its writer of record and the copy changes nothing; a batch of D's found there is kept as batch-ID.prev.json.

Guards (each aborts before anything is written): a file over 8 MB or the folder over 60 MB (rerun
with --thin); a run whose buildingId is not its building's; agent positions in 3 sample frames more
than 0.5 m outside the building's walkable area (a run made on an older building file); a private
building, or any text that mentions UMass, in the output. A building that load_buildings() flags
private is refused: "skipped private: ID".

--thin keeps every 2nd agent frame (frameInterval 1.0) and every 3rd smoke frame (interval 6).
--resume reuses the raw batch (data/runs/precompute-ID-batch.json) and the sweeps (precompute-ID-sweeps.json)
of an earlier run when they were made from the same building file, scenario, seeds and rooms. Those are the slow
parts: with them a new --propped-door, --rooms or --top takes minutes. A batch that loses more than 3% of its
fires (a pool whose workers died, for example out of memory) is repeated with half the processes, or refused;
--workers defaults to cores - 2, at most 10, because the sim is memory bound.
A10 adds --llm-showcase here: write_run() is what it should call for its one brain: "llm" run.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import copy
import json
import math
import multiprocessing
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # `python tools/precompute_demo.py`: the repo root is not on the path yet
    sys.path.insert(0, str(ROOT))

DEMO_DIR = ROOT / "frontend" / "public" / "demo"
CACHE_DIR = ROOT / "data" / "runs"  # gitignored: checkpoints for --resume, and the batch of record (see write_record)
INDEX_VERSION = "demo-index/v0"

MB = 1_000_000
MAX_FILE_BYTES = 8 * MB  # the guards of task A5
MAX_FOLDER_BYTES = 60 * MB
TARGET_FOLDER_BYTES = 15 * MB  # a warning, not an abort: the aim for the static payload
SAMPLE_TOLERANCE_M = 0.5
DEFAULT_SEEDS = (1, 2, 3)
TOP_ROOMS = 4
SWEEP_ROOMS = 12  # rooms (the highest risk first) the what-if sweep and the fixes rerun
BATCH_TIMEOUT_S = 6 * 3600  # run_many's deadline: this runs unattended, a slow machine must not cut a batch
FAILED_OK = 0.03  # share of batch fires that may fail before the batch is repeated or refused
JOBS_TIMEOUT_S = 3600  # the baseline and propped runs together (a few minutes when nothing hangs)
DEFAULT_MIX = {"typical": 0.85, "older": 0.1, "visitor": 0.05}

# Demo defaults by building id; the command line wins over them, and they over the scenario file.
PRESETS = {
    # D15's demo base for the real office: 250 occupants (120 barely queues) and the kitchen preset.
    # (The blocked-exit what-if used to be left out here: stair arrivals next to a blocked exit crashed the
    # sim until C13b. A fire that still fails is dropped from its pair and counted, so it stays in;
    # "--skip-variants blockedExit" leaves it out again.)
    "office": {"occupants": 250, "fire_type": "kitchen"},
    # the clinic's design occupancy (D21: 3,910 m2 of walkable floor / 13.9 m2 per person, rounded to 10) and the same
    # kitchen preset. A clinic run is 2-4 MB and minutes long, so its demo is one pair (--rooms R1AC1, the waiting
    # room C18 measured) and a smaller batch (--max-rooms 24, --sweep-rooms 3)
    "clinic": {"occupants": 280, "fire_type": "kitchen"},
    # DSA1 is the stair door of the demo story; 2 rooms and the kitchen keep the static payload under its 15 MB aim;
    # home_point: the kitchen baseline is the very fire of contracts/run.example.json, which sync-demo lists too
    "example-office": {"propped_door": "DSA1", "top": 2, "home_point": True},
}


def say(message: str = "") -> None:
    print(message, flush=True)


def fail(message: str, code: int = 1):
    print(f"ERROR: {message}", file=sys.stderr, flush=True)
    raise SystemExit(code)


def human(n: int) -> str:
    return f"{n / MB:.2f} MB" if n >= MB else f"{n / 1000:.0f} KB"


# ----------------------------------------------------------------------------- buildings


def find_building(building_id: str):
    """(building, source path, None) for a public building, (None, None, reason) for one that is not.
    The source path is the file the demo copy is made from."""
    from backend.app.store import BUILDING_EXAMPLE, BUILDINGS_DIR, PRIVATE_DIR, load_buildings

    found = load_buildings()
    if building_id not in found:
        public = sorted(bid for bid, (b, private) in found.items() if not private and b.get("private") is not True)
        return None, None, f"unknown building {building_id!r} (available: {', '.join(public) or 'none'})"
    building, private = found[building_id]
    if private or building.get("private") is True:
        return None, None, "private"
    source = None
    for path in [BUILDING_EXAMPLE, *sorted(BUILDINGS_DIR.glob("*.json"))]:  # load_buildings' order: the last wins
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and str(data.get("id")) == building_id and isinstance(data.get("floors"), list):
            source = path
    if source is None or PRIVATE_DIR in source.parents:
        return None, None, "private"
    return building, source, None


def public_building_ids() -> list[str]:
    from backend.app.store import load_buildings

    return [bid for bid, (b, private) in load_buildings().items() if not private and b.get("private") is not True]


def building_file_name(building_id: str, source: Path) -> str:
    """Where the demo copy lives: the name sync-demo.mjs gives it, or its index entry would flip back and forth."""
    from backend.app.store import BUILDING_EXAMPLE

    return "building.example.json" if source == BUILDING_EXAMPLE else f"building-{safe_name(building_id)}.json"


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(text))


def room_table(building: dict) -> dict[str, tuple[str, dict]]:
    """room id -> (floor id, room); the first floor wins when two floors reuse an id."""
    table: dict[str, tuple[str, dict]] = {}
    for floor in building["floors"]:
        for room in floor["rooms"]:
            table.setdefault(str(room["id"]), (floor["id"], room))
    return table


def room_label(building: dict, room_id: str) -> str:
    """The room's name, with its id when another room of the building has the same name."""
    _, room = room_table(building)[room_id]
    name = str(room.get("name") or room_id)
    same = sum(1 for f in building["floors"] for r in f["rooms"] if str(r.get("name") or r["id"]) == name)
    return name if same == 1 else f"{name} ({room_id})"


def stair_door_ids(building: dict) -> set[str]:
    """Doors between a stair room and the rest of the building (not the exterior door at its foot)."""
    ids = set()
    for floor in building["floors"]:
        stairs = {s["room"] for s in floor.get("stairs", [])} | {r["id"] for r in floor["rooms"] if r.get("type") == "stair"}
        for door in floor["doors"]:
            if "outside" not in door["connects"] and stairs & set(door["connects"]):
                ids.add(door["id"])
    return ids


def door_floor(building: dict, door_id: str) -> str | None:
    return next((f["id"] for f in building["floors"] for d in f["doors"] if d["id"] == door_id), None)


# ----------------------------------------------------------------------------- scenario


def representative_point(room: dict) -> tuple[float, float]:
    """The point fire.batch ignites a room's fire at, to the last digit: rounded to 0.01 m the same fire runs
    a second longer (measured: R118b, seed 1, t90 138.41 s against 139.49 s), and the demo's baseline run
    should be the batch's own fire."""
    from shapely.geometry import Polygon

    point = Polygon(room["polygon"]).representative_point()
    return point.x, point.y


def base_scenario(building: dict, source: Path, args, preset: dict, seeds: list[int]) -> dict:
    """The scenario the batch varies. Order: scenario file next to the building, else the contracts
    example for the example building, else the app's own default; then the preset, then the options."""
    from backend.app.store import BUILDING_EXAMPLE

    candidates = [source.with_name(source.stem + ".scenario.json")]
    if source == BUILDING_EXAMPLE:
        candidates = [ROOT / "contracts" / "scenario.example.json"]
    base = None
    for path in candidates:
        if path.is_file():
            base = json.loads(path.read_text(encoding="utf-8"))
            say(f"  scenario: {path.relative_to(ROOT).as_posix()}")
            break
    if base is None:
        say("  scenario: built-in default (no scenario file next to the building)")
        base = {"version": "scenario/v0", "seed": 1, "occupants": {"total": 160, "mix": dict(DEFAULT_MIX)},
                "fire": {"type": "kitchen", "start": 0}, "sprinklers": False, "doors": {}, "alarmTime": 30,
                "maxTime": 400}
    base = copy.deepcopy(base)
    base["fire"] = dict(base.get("fire") or {"type": "kitchen", "start": 0})
    occupants = args.occupants if args.occupants is not None else preset.get("occupants")
    if occupants is not None:
        mix = (base.get("occupants") or {}).get("mix") or dict(DEFAULT_MIX)
        base["occupants"] = {"total": int(occupants), "mix": mix}  # a per-room count would override the total
    fire_type = args.fire_type or preset.get("fire_type")
    if fire_type:
        from fire.presets import fire_params

        base["fire"]["type"] = fire_type
        base["fire"].pop("growth", None)  # the override is the preset's own growth
        try:
            fire_params(base["fire"])
        except ValueError as error:
            fail(f"--fire-type: {error}", 2)
    base.update(version="scenario/v0", id=f"{building['id']}-demo", buildingId=building["id"], seed=seeds[0],
                brain="rules")  # batches and what-ifs are rule-based only (spec 7.4)
    base.setdefault("doors", {})
    base.setdefault("sprinklers", False)
    base.setdefault("alarmTime", 30)
    base.setdefault("maxTime", 400)
    return base


def ignition_rooms(building: dict, max_rooms: int | None, forced: list[str]) -> list[dict]:
    """Every room that is not a corridor or a stair, or max_rooms evenly spaced ones, plus the forced rooms."""
    rooms = [{"floor": f["id"], "room": r["id"]} for f in building["floors"] for r in f["rooms"]
             if r.get("type") not in ("corridor", "stair")]
    if max_rooms is not None and max_rooms < len(rooms):
        picks = sorted({round(i * (len(rooms) - 1) / max(1, max_rooms - 1)) for i in range(max_rooms)})
        chosen = [rooms[i] for i in picks]
    else:
        chosen = rooms
    table = room_table(building)
    for rid in forced:
        floor_id, _ = table[rid]
        if not any(c["room"] == rid and c["floor"] == floor_id for c in chosen):
            chosen.append({"floor": floor_id, "room": rid})
    order = {(f["id"], r["id"]): n for n, (f, r) in enumerate((f, r) for f in building["floors"] for r in f["rooms"])}
    return sorted(chosen, key=lambda c: order[(c["floor"], c["room"])])


# ----------------------------------------------------------------------------- batch


def checkpoint_path(building_id: str, stage: str = "batch") -> Path:
    return CACHE_DIR / f"precompute-{safe_name(building_id)}-{stage}.json"


def run_batch(building: dict, source: Path, base: dict, ignitions: list[dict], seeds: list[int], workers: int,
              resume: bool) -> dict:
    """fire.batch.run_many, or the raw batch of an earlier run (--resume) when it still fits."""
    from backend.app.jobs import _json_default

    path = checkpoint_path(building["id"])
    request = {"base": base, "seeds": seeds, "ignitions": ignitions}
    if resume and path.is_file():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        reason = None
        if saved.get("request") != json.loads(json.dumps(request)):
            reason = "scenario, seeds or rooms changed"
        elif path.stat().st_mtime < source.stat().st_mtime:
            reason = "the building file is newer"
        if reason is None:
            batch = saved["batch"]
            say(f"  --resume: reusing the batch saved {datetime.fromtimestamp(path.stat().st_mtime):%Y-%m-%d %H:%M} "
                f"({len(batch['runs'])} runs)")
            return batch
        say(f"  --resume: not reusing the saved batch ({reason})")
    from fire.batch import run_many

    n = len(ignitions) * len(seeds)
    say(f"  batch: {len(ignitions)} rooms x {len(seeds)} seeds = {n} fires, {workers} workers")
    t0 = time.perf_counter()
    batch = run_many(building, base, ignitions, seeds, workers, BATCH_TIMEOUT_S, True)
    say(f"  batch done in {(time.perf_counter() - t0) / 60:.1f} min")
    lost = len(batch.get("failed") or [])
    if lost > FAILED_OK * n and workers > 2:
        # a pool that loses its workers (out of memory, a native crash) fails every run still queued; a ranking
        # made of what is left is worse than none, so the whole batch goes again with half the processes
        say(f"  WARNING: {lost} of {n} fires failed (first: {batch['failed'][0].get('error')}); "
            f"again, with {max(2, workers // 2)} workers")
        batch = run_many(building, base, ignitions, seeds, max(2, workers // 2), BATCH_TIMEOUT_S, True)
        lost = len(batch.get("failed") or [])
        say(f"  batch done in {(time.perf_counter() - t0) / 60:.1f} min in all")
    if not batch.get("runs"):
        first = (batch.get("failed") or [{}])[0]
        fail(f"{building['id']}: every batch run failed; first: {first.get('scenarioId')}: {first.get('error')}")
    if lost > FAILED_OK * n:
        fail(f"{building['id']}: {lost} of {n} fires failed (first: {batch['failed'][0].get('error')}); a ranking from "
             f"the rest would mislead. Try --workers {max(1, workers // 2)}, or a smaller --max-rooms.")
    if lost:
        say(f"  WARNING: {lost} of {n} fires failed and are left out; first: {batch['failed'][0].get('error')}")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"request": request, "batch": batch}, default=_json_default, separators=(",", ":"))
    path.write_text(text, encoding="utf-8")
    to_text(batch)  # raises on a NaN, which the final file could not hold; the checkpoint is already saved
    return batch


def load_given_batch(path: Path, building: dict) -> dict:
    """--batch: a finished batch/v0 of this building (D's `python -m fire.batch ... --out`, or fire.demo's), used
    as it is. Its `base` becomes the scenario of the baseline and propped runs, so a baseline is one of its fires."""
    try:
        batch = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        fail(f"--batch {path}: {error}", 2)
    problem = None
    if not isinstance(batch, dict) or batch.get("version") != "batch/v0":
        problem = "not a batch/v0 file"
    elif batch.get("buildingId") != building["id"]:
        problem = f"it is for building {batch.get('buildingId')!r}, not {building['id']!r}"
    elif batch.get("placeholder") is True:
        problem = "it is a placeholder batch"
    elif not (batch.get("runs") and batch.get("rooms") and isinstance(batch.get("base"), dict)):
        problem = "it has no runs, rooms or base scenario"
    if problem:
        fail(f"--batch {path}: {problem}", 2)
    return batch


def run_sweeps(building: dict, source: Path, base: dict, batch: dict, skip: set[str], args, workers: int) -> dict:
    """D's paired what-if sweep and measured fixes on the worst rooms. Each is optional: a failure
    keeps the batch without it (this runs unattended) and says so. --resume reuses the result of
    the last run when it was made from this very batch."""
    rooms = min(args.sweep_rooms, len(batch["rooms"]))
    if args.no_sweeps or rooms < 1:
        return batch
    path = checkpoint_path(building["id"], "sweeps")
    request = {"base": base, "rooms": rooms, "skip": sorted(skip), "runs": batch["runs"]}
    if args.resume and path.is_file() and path.stat().st_mtime >= source.stat().st_mtime:
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        if saved.get("request") == json.loads(json.dumps(request)):
            say(f"  --resume: reusing the sweeps saved {datetime.fromtimestamp(path.stat().st_mtime):%Y-%m-%d %H:%M}")
            return saved["batch"]
        say("  --resume: not reusing the saved sweeps (the batch, scenario or rooms changed)")
    worst = sorted(batch["rooms"], key=lambda r: -(r["riskT90"] if r["riskT90"] is not None else base["maxTime"]))
    say(f"  sweeps on the {rooms} highest-risk rooms: {', '.join(r['id'] for r in worst[:rooms])}")
    try:
        from fire.whatif import add_whatif, default_variants

        variants = [v for v in default_variants(building, base, batch["runs"]) if v["id"] not in skip]
        say(f"  what-if variants: {', '.join(v['id'] for v in variants) or 'none'}"
            + (f" (skipped: {', '.join(sorted(skip))})" if skip else ""))
        t0 = time.perf_counter()
        batch = add_whatif(building, base, batch, variants=variants, rooms=rooms, workers=workers,
                           timeout_s=BATCH_TIMEOUT_S)
        say(f"  what-if sweep done in {(time.perf_counter() - t0) / 60:.1f} min")
        for item in batch["whatIf"]:
            say(f"    {item['why']}")
    except Exception as error:  # noqa: BLE001 - optional stage
        say(f"  WARNING: what-if sweep failed, the batch has no whatIf: {type(error).__name__}: {error}")
        traceback.print_exc()
    try:
        from fire.fixes import add_fixes

        t0 = time.perf_counter()
        batch = add_fixes(building, base, batch, rooms=rooms, workers=workers, timeout_s=BATCH_TIMEOUT_S)
        say(f"  measured fixes done in {(time.perf_counter() - t0) / 60:.1f} min")
        for item in batch["fixes"]:
            say(f"    {item['why']}")
    except Exception as error:  # noqa: BLE001 - optional stage
        say(f"  WARNING: measured fixes failed, the batch has no fixes: {type(error).__name__}: {error}")
        traceback.print_exc()
    picked = {(r["floor"], r["id"]) for r in worst[:rooms]}
    expected = sum(1 for r in batch["runs"] if (r["ignition"]["floor"], r["ignition"]["room"]) in picked)
    for item in [*batch.get("whatIf", []), *batch.get("fixes", [])]:
        if "derivedFrom" not in item and item.get("n", expected) < 0.9 * expected:  # compare() drops a pair whose run failed
            say(f"  WARNING: {item.get('label')}: only {item.get('n')} of {expected} paired fires finished; its numbers are thinner")
    if "whatIf" in batch or "fixes" in batch:
        from backend.app.jobs import _json_default

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"request": request, "batch": batch}, default=_json_default, separators=(",", ":")),
                        encoding="utf-8")
    return batch


# ----------------------------------------------------------------------------- choosing the runs


def pick_rooms(building: dict, batch: dict, base: dict, args, preset: dict) -> list[tuple[str, str]]:
    """(floor, room) pairs that get a baseline and a propped run, in index order."""
    table = room_table(building)
    if args.rooms:
        unknown = [r for r in args.rooms if r not in table]
        if unknown:
            fail(f"--rooms: no such room in {building['id']}: {', '.join(unknown)}", 2)
        return [(table[r][0], r) for r in args.rooms]
    max_time = base["maxTime"]
    ranked = sorted(batch["rooms"], key=lambda r: (-(r["riskT90"] if r["riskT90"] is not None else max_time),
                                                     -(r["riskTrapped"] or 0), str(r["id"])))
    top = args.top if args.top is not None else preset.get("top", TOP_ROOMS)
    chosen = [(r["floor"], r["id"]) for r in ranked[:top]]
    kitchen = next(((f["id"], r["id"]) for f in building["floors"] for r in f["rooms"] if r.get("type") == "kitchen"), None)
    if kitchen is None:
        # no kitchen room (the NIBS buildings have none): the room the scenario file lights its fire in stands in for
        # it, which is also where the app's default fire is, so "Run" and a precomputed run line up
        home = str((base.get("fire") or {}).get("room") or "")
        if home in table and table[home][1].get("type") not in ("corridor", "stair"):
            kitchen = (table[home][0], home)
    if kitchen and kitchen not in chosen:
        chosen.append(kitchen)
    return chosen


def pick_door(building: dict, batch: dict, preset: dict, args) -> str | None:
    """--propped-door, else the preset's, else the stair door with the highest score in batch.doors."""
    stairs = stair_door_ids(building)
    explicit = args.propped_door or preset.get("propped_door")
    if explicit:
        if door_floor(building, explicit) is None:
            fail(f"--propped-door: no door {explicit!r} in {building['id']}", 2)
        if explicit not in stairs:
            say(f"  WARNING: {explicit} is not a door between a stair and the building; propping it may change nothing")
        return explicit
    scored = [d for d in batch["doors"] if d["id"] in stairs]
    if not scored:
        return None
    return max(scored, key=lambda d: (d["score"], d.get("meanWait", 0), str(d["id"])))["id"]


def run_key(building_id: str, room: str, variant: str) -> str:
    return f"{building_id}-{room}-{variant}"


def build_jobs(building: dict, base: dict, rooms: list[tuple[str, str]], door: str | None,
               home_point: bool = False) -> list[dict]:
    """A baseline job and, with a door, a propped job per room: same seed, doors differ only in `door`.
    home_point keeps the scenario file's own fire point in the room that file names (the example building:
    sync-demo lists contracts/run.example.json, a baseline of that very fire, so ours must be the same fire)."""
    table = room_table(building)
    jobs = []
    for floor_id, room_id in rooms:
        x, y = representative_point(table[room_id][1])
        home = base.get("fire") or {}
        if home_point and home.get("room") == room_id and home.get("x") is not None and home.get("y") is not None:
            x, y = float(home["x"]), float(home["y"])
        for variant, state in (("base", "closed"), ("propped", "propped")):
            if variant == "propped" and door is None:
                continue
            scenario = copy.deepcopy(base)
            scenario["id"] = run_key(building["id"], room_id, variant)
            scenario["fire"].update(floor=floor_id, room=room_id, x=x, y=y)
            if door is not None:
                scenario["doors"] = {**base.get("doors", {}), door: state}
            jobs.append({"key": scenario["id"], "room": room_id, "floor": floor_id, "variant": variant,
                         "scenario": scenario})
    return jobs


def _simulate_job(job: dict) -> dict:
    """Pool worker (top level, so it pickles under spawn): one run, as backend.app.jobs.simulate makes it."""
    started = time.perf_counter()
    try:
        from backend.app.jobs import simulate

        run = simulate(job["building"], job["scenario"])
        return {"key": job["key"], "run": run, "wallS": time.perf_counter() - started}
    except Exception as error:  # noqa: BLE001 - reported by the caller, which decides what a failure costs
        return {"key": job["key"], "error": f"{type(error).__name__}: {error}", "trace": traceback.format_exc()[-1500:],
                "wallS": time.perf_counter() - started}


def _pool_round(jobs: list[dict], workers: int, done, timeout_s: float) -> list[dict]:
    """One pool over the jobs; returns the jobs whose worker died (a native crash takes the pool down with it)."""
    died: list[dict] = []
    pool = concurrent.futures.ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn"))
    futures = {pool.submit(_simulate_job, job): job for job in jobs}
    try:
        for future in concurrent.futures.as_completed(futures, timeout=timeout_s):
            try:
                result = future.result()
            except Exception:  # noqa: BLE001 - BrokenProcessPool: this job, and the ones still queued, never ran
                died.append(futures[future])
                continue
            done(result)
    except concurrent.futures.TimeoutError:
        for future, job in futures.items():
            if not future.done():
                done({"key": job["key"], "error": f"no result after {timeout_s:.0f} s", "trace": "", "wallS": timeout_s})
        for child in list((getattr(pool, "_processes", None) or {}).values()):  # private, as fire.batch uses it
            child.terminate()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return died


def simulate_jobs(building: dict, jobs: list[dict], workers: int) -> dict[str, dict]:
    """Run the jobs in a process pool and print progress; key -> result (a run, or an error). A job whose
    worker died gets one more try in a fresh pool; the whole set has JOBS_TIMEOUT_S."""
    for job in jobs:
        job["building"] = building
    results: dict[str, dict] = {}
    started = time.perf_counter()

    def done(result: dict) -> None:
        results[result["key"]] = result
        if "run" in result:
            m = result["run"]["metrics"]
            outcome = f"t90={m.get('t90')} trapped={m.get('trapped')}"
        else:
            outcome = f"FAILED {result['error']}"
        elapsed = time.perf_counter() - started
        say(f"  [{len(results)}/{len(jobs)}] {result['key']} {outcome} ({result['wallS']:.0f} s run, {elapsed:.0f} s elapsed)")

    pending = list(jobs)
    for attempt in (1, 2):
        pool_size = max(1, min(workers, len(pending)))
        if pool_size == 1 and attempt == 1:  # nothing to share: no pool, no spawn
            for job in pending:
                done(_simulate_job(job))
            pending = []
        else:
            left = max(60.0, JOBS_TIMEOUT_S - (time.perf_counter() - started))
            pending = _pool_round(pending, pool_size, done, left)
        if not pending:
            break
        say(f"  {len(pending)} run(s) lost to a worker that died; {'trying them again' if attempt == 1 else 'giving up on them'}")
    for job in pending:
        done({"key": job["key"], "error": "its worker died twice", "trace": "", "wallS": 0.0})
    for job in jobs:
        job.pop("building", None)
    return results


# ----------------------------------------------------------------------------- guards and shaping


def check_run(run: dict, building: dict) -> None:
    """Abort on a run that does not belong to its building (task A5's two run guards)."""
    if run.get("buildingId") != building["id"]:
        fail(f"run {run.get('id')} is for building {run.get('buildingId')!r}, not {building['id']!r}")
    from shapely.geometry import Point, Polygon
    from shapely.ops import unary_union
    from shapely.prepared import prep

    walkable = {}
    for floor in building["floors"]:
        polygons = []
        for ring in floor.get("walkable") or []:
            polygon = Polygon(ring["outer"], ring.get("holes") or [])
            polygons.append(polygon if polygon.is_valid else polygon.buffer(0))
        walkable[floor["id"]] = unary_union(polygons)
    prepared = {floor_id: prep(geometry) for floor_id, geometry in walkable.items()}
    frames = [f for f in run["frames"] if f["a"]]
    if not frames:
        fail(f"run {run.get('id')} has no agent frames")
    sample = [frames[len(frames) // 4], frames[len(frames) // 2], frames[(3 * len(frames)) // 4]]
    for frame in sample:
        for idx, x, y, floor_index, _status in frame["a"]:
            floor_id = run["floors"][floor_index]
            point = Point(x, y)
            if prepared[floor_id].covers(point):
                continue
            distance = walkable[floor_id].distance(point)
            if distance > SAMPLE_TOLERANCE_M:
                fail(f"run {run.get('id')}: agent {idx} at ({x}, {y}) on {floor_id} is {distance:.2f} m outside the "
                     f"walkable area at t={frame['t']} (a run made on an older building file?)")


def thin(run: dict) -> dict:
    """--thin: every 2nd agent frame (the last one stays, so the replay keeps its length) and every
    3rd smoke frame. Events and metrics stay as the sim made them."""
    frames = run["frames"]
    kept = frames[::2]
    if frames and kept[-1] is not frames[-1]:
        kept.append(frames[-1])
    run["frames"] = kept
    run["frameInterval"] = round(run["frameInterval"] * 2, 6)
    for layer in run.get("smoke") or []:
        layer["frames"] = layer["frames"][::3]
        layer["interval"] = round(layer.get("interval", 2) * 3, 6)
    return run


def to_text(obj, indent: int | None = None) -> str:
    """JSON text of a run, batch or index; numpy numbers allowed, NaN refused."""
    from backend.app.jobs import _json_default

    if indent is None:
        return json.dumps(obj, default=_json_default, separators=(",", ":"), allow_nan=False)
    return json.dumps(_js_numbers(obj), default=_json_default, indent=indent, ensure_ascii=False, allow_nan=False) + "\n"


def _js_numbers(obj):
    """8.0 becomes 8: JavaScript prints whole numbers that way, and sync-demo.mjs rewrites index.json
    whenever its text differs from what it would write."""
    if isinstance(obj, float) and math.isfinite(obj) and obj.is_integer():
        return int(obj)
    if isinstance(obj, dict):
        return {k: _js_numbers(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_js_numbers(v) for v in obj]
    return obj


def check_private(files: dict[str, str | bytes], building_ids: list[str]) -> None:
    """Abort if anything about to be written mentions UMass (spec 12: tools/check_all.py greps for the same)."""
    for name, content in files.items():
        text = content.decode("utf-8", "replace") if isinstance(content, bytes) else content
        at = text.lower().find("umass")
        if "umass" in name.lower() or at >= 0:
            context = f" (…{text[max(0, at - 30):at + 35]!r}…)" if at >= 0 else ""
            fail(f"{name} mentions UMass{context}; nothing derived from the UMass building may go into the static site")
    for bid in building_ids:
        if "umass" in bid.lower():
            fail(f"building id {bid!r} names UMass")


# ----------------------------------------------------------------------------- index


def load_index(demo: Path) -> dict:
    path = demo / "index.json"
    index = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    index.setdefault("version", INDEX_VERSION)
    for key in ("buildings", "runs", "batches"):
        index.setdefault(key, [])
    return index


def upsert(entries: list[dict], entry: dict) -> None:
    """sync-demo's rule: an entry with the same id or file is replaced where the earliest one stood;
    a new one goes last."""
    position = -1
    for i in range(len(entries) - 1, -1, -1):
        if entries[i].get("id") == entry["id"] or entries[i].get("file") == entry["file"]:
            position = i
            del entries[i]
    if position < 0:
        entries.append(entry)
    else:
        entries.insert(position, entry)


def folder_bytes(demo: Path) -> dict[str, int]:
    return {p.relative_to(demo).as_posix(): p.stat().st_size for p in demo.rglob("*") if p.is_file()}


def write_atomic(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    if isinstance(content, str):
        tmp.write_text(content, encoding="utf-8", newline="\n")
    else:
        tmp.write_bytes(content)
    os.replace(tmp, path)


def run_entry(key: str, building: dict, scenario: dict, run: dict, file: str, variant: str, door: str | None) -> dict:
    metrics = run.get("metrics") or {}
    fire = scenario["fire"]
    label = room_label(building, fire["room"]) + (", baseline" if variant == "base" else f", {door} propped")
    return {
        "id": key,
        "buildingId": building["id"],
        "label": label,
        "file": file,
        "whatIf": None if variant == "base" else "propped",
        "fire": {"floor": fire["floor"], "room": fire["room"], "x": round(fire["x"], 2), "y": round(fire["y"], 2),
                 "type": fire["type"]},
        "doors": dict(scenario.get("doors") or {}),
        "metrics": {"t50": metrics.get("t50"), "t90": metrics.get("t90"), "t100": metrics.get("t100"),
                    "evacuated": metrics.get("evacuated"), "trapped": metrics.get("trapped")},
    }


def write_run(run: dict, building: dict, scenario: dict, variant: str, door: str | None, args) -> tuple[dict, str, str]:
    """(index entry, file name, JSON text) of one finished run; the guards run here. A10's showcase
    run goes through this too."""
    key = scenario["id"]
    run["id"] = key
    run["scenarioId"] = key
    check_run(run, building)
    if args.thin:
        thin(run)
    name = f"run-{safe_name(building['id'])}-{safe_name(scenario['fire']['room'])}-{variant}.json"
    return run_entry(key, building, scenario, run, name, variant, door), name, to_text(run)


# ----------------------------------------------------------------------------- one building


def batch_match_note(batch: dict, scenario: dict, run: dict) -> str | None:
    """The baseline run is the batch's own fire for that room and seed; say so, or say how it differs."""
    fire = scenario["fire"]
    for row in batch["runs"]:
        if row["ignition"] == {"floor": fire["floor"], "room": fire["room"]} and row["seed"] == scenario["seed"]:
            m = run["metrics"]
            same = row["t90"] == m.get("t90") and row["t100"] == m.get("t100") and row["trapped"] == m.get("trapped")
            if same:
                return f"matches the batch's own fire (t90 {m.get('t90')})"
            return (f"DIFFERS from the batch's fire (batch t90 {row['t90']}, t100 {row['t100']}, trapped {row['trapped']}; "
                    f"run t90 {m.get('t90')}, t100 {m.get('t100')}, trapped {m.get('trapped')})")
    return None


def smoke_seconds(metrics: dict) -> float | None:
    value = (metrics.get("exposure") or {}).get("personSecondsInSmoke")
    return float(value) if isinstance(value, (int, float)) else None


def order_by_story(runs: list[dict]) -> list[dict]:
    """The demo's tour (scene 4) takes the first baseline listed for a building and its propped partner, so the
    pair whose propped run adds the most person-seconds in smoke goes first: a what-if that shows something.
    The rest keep their risk order, and so does everything when --rooms names the order."""
    by_room: dict[str, dict[str, dict]] = {}
    for item in runs:
        by_room.setdefault(item["entry"]["fire"]["room"], {})[item["entry"]["whatIf"] or "base"] = item
    gain: dict[str, float] = {}
    for room, pair in by_room.items():
        if "base" in pair and "propped" in pair:
            a, b = smoke_seconds(pair["base"]["metrics"]), smoke_seconds(pair["propped"]["metrics"])
            if a is not None and b is not None:
                gain[room] = b - a
    order = sorted(by_room, key=lambda room: -gain.get(room, float("-inf")))  # stable: ties and gaps keep their order
    if order != list(by_room):
        say("  order in the index (what-if that adds the most smoke first): "
            + ", ".join(f"{room} ({gain[room]:+,.0f})" if room in gain else room for room in order))
    return [item for room in order for kind in ("base", "propped") if (item := by_room[room].get(kind))]


def pair_story(a: dict, b: dict) -> str:
    """One line on a baseline/propped pair from the runs' metrics: smoke exposure, the stair that fills first, t90."""
    parts = []
    ea, eb = a.get("exposure") or {}, b.get("exposure") or {}
    if ea.get("personSecondsInSmoke") is not None and eb.get("personSecondsInSmoke") is not None:
        base, now = ea["personSecondsInSmoke"], eb["personSecondsInSmoke"]
        pct = f" ({100 * (now - base) / base:+.0f}%)" if base > 0 else ""
        parts.append(f"person-seconds in smoke {base:,.0f} -> {now:,.0f}{pct}")
        gains = []
        for sa in ea.get("stairs") or []:
            sb = next((x for x in eb.get("stairs") or [] if (x["floor"], x["group"]) == (sa["floor"], sa["group"])), None)
            if sb and sa.get("smokeAt") is not None and sb.get("smokeAt") is not None and sa["smokeAt"] > sb["smokeAt"]:
                gains.append((sa["smokeAt"] - sb["smokeAt"], f"Stair {sa['group']} on {sa['floor']} fills {sa['smokeAt'] - sb['smokeAt']:.0f} s sooner"))
        if gains:
            parts.append(max(gains)[1])
    parts.append(f"t90 {a.get('t90')} -> {b.get('t90')}, trapped {a.get('trapped')} -> {b.get('trapped')}")
    return "; ".join(parts)


def make_report(batch: dict, building: dict) -> str:
    """The report card as markdown, or "" when A7's backend.llm.features is not there. LLM_PROVIDER is off
    (main sets it), so the card is the template and its writer line says so."""
    try:
        from backend.llm.features import report_card
    except ImportError as error:
        say(f"  WARNING: no report card, backend.llm.features does not import ({error})")
        return ""
    return report_card(batch, building, allow_llm=True)[0]


def make_headlines(batch: dict, building: dict) -> dict | None:
    """D18's headline numbers pack for the batch, or None while fire/headlines.py is not on this branch.
    The pack only restates the batch, so it is made here, from the batch that is written, and never taken from
    an older file: a pack from another batch would show other numbers than the risk map."""
    try:
        from fire.headlines import build_headlines
    except ImportError:
        say("  no headlines pack: fire/headlines.py (D18) is not on this branch")
        return None
    try:
        return build_headlines(building, batch)
    except Exception as error:  # noqa: BLE001 - optional
        say(f"  WARNING: no headlines pack, build_headlines failed: {type(error).__name__}: {error}")
        return None


def warn_stale_pack(building_id: str, batch: dict, wrote_pack: bool) -> None:
    """sync-demo.mjs (npm run build) copies data/runs/headlines-ID.json into the demo whenever it exists and names
    it on the building's batch. A pack that was not made from this batch must not travel with it."""
    path = CACHE_DIR / f"headlines-{safe_name(building_id)}.json"
    if wrote_pack or not path.is_file():
        return
    try:
        made_from = ((json.loads(path.read_text(encoding="utf-8")).get("sources") or {}).get("batch") or {}).get("id")
    except (OSError, ValueError, AttributeError):
        made_from = None
    if made_from != batch.get("id"):
        say(f"  WARNING: {path.relative_to(ROOT).as_posix()} was made from batch {made_from!r}, not from this one "
            f"({batch.get('id')!r}); `npm run build` would copy it into the demo next to this batch. Delete it, or "
            f"rerun python -m fire.headlines on this batch.")


def process_building(building_id: str, args, demo: Path, state: dict) -> bool:
    """Everything for one building. Returns False when it was skipped. Writes its files and merges
    its entries into index.json at the end, so a later building's failure keeps this one's."""
    say(f"== {building_id}")
    building, source, problem = find_building(building_id)
    if problem == "private":
        say(f"skipped private: {building_id}")
        return False
    if problem:
        fail(problem, 2)
    preset = PRESETS.get(building_id, {})
    seeds = sorted(set(args.seeds))
    workers = args.workers or default_workers()
    base = base_scenario(building, source, args, preset, seeds)
    say(f"  {base['occupants'].get('total', '?')} occupants, {base['fire']['type']} fire, seeds {','.join(map(str, seeds))}, "
        f"maxTime {base['maxTime']} s")
    unknown = [r for r in args.rooms or [] if r not in room_table(building)]
    if unknown:
        fail(f"--rooms: no such room in {building_id}: {', '.join(unknown)}", 2)

    t_start = time.perf_counter()
    given = load_given_batch(args.batch, building) if args.batch else None
    if given:
        # D's finished batch: its base is the scenario the runs use, so each baseline is one of its own fires
        base = copy.deepcopy(given["base"])
        base.update(buildingId=building_id, brain="rules", seed=min(r["seed"] for r in given["runs"]))
        base.setdefault("doors", {})
        base.setdefault("maxTime", 400)
        batch = given
        say(f"  --batch {args.batch}: {len(batch['runs'])} fires in {len(batch['rooms'])} rooms, "
            f"{base['occupants'].get('total', '?')} occupants, {base['fire']['type']} fire; "
            f"whatIf: {'yes' if batch.get('whatIf') else 'no'}, fixes: {'yes' if batch.get('fixes') else 'no'}; no batch is run")
    else:
        ignitions = ignition_rooms(building, args.max_rooms, args.rooms or [])
        batch = run_batch(building, source, base, ignitions, seeds, workers, args.resume)

    rooms = pick_rooms(building, batch, base, args, preset)
    door = pick_door(building, batch, preset, args)
    say(f"  runs: {', '.join(r for _, r in rooms)}; propped door: {door or 'none (no stair door found)'}")
    jobs = build_jobs(building, base, rooms, door, home_point=bool(preset.get("home_point")))
    results = simulate_jobs(building, jobs, workers)

    runs, dropped = [], []
    for job in jobs:
        result = results[job["key"]]
        if "run" not in result:
            dropped.append(job["key"])
            say(f"  WARNING: {job['key']} failed ({result['error']}); no run for it")
            if result.get("trace"):
                say(result["trace"])
            continue
        if job["variant"] == "propped" and run_key(building_id, job["room"], "base") in dropped:
            dropped.append(job["key"])
            say(f"  WARNING: {job['key']} dropped: its baseline failed")
            continue
        entry, name, text = write_run(result["run"], building, job["scenario"], job["variant"], door, args)
        note = batch_match_note(batch, job["scenario"], result["run"]) if job["variant"] == "base" else None
        runs.append({"entry": entry, "name": name, "text": text, "note": note, "metrics": result["run"]["metrics"]})
    if not runs:
        fail(f"{building_id}: no run finished")
    if not args.rooms:
        runs = order_by_story(runs)

    # the sweeps come last: they are the optional, slow part, and a guard that fails above should fail early
    skip = set(args.skip_variants if args.skip_variants is not None else preset.get("skip_variants", []))
    if not given:
        batch = run_sweeps(building, source, base, batch, skip, args, workers)
        batch["id"] = f"{building_id}-batch"
    if batch.get("buildingId") != building_id:
        fail(f"the batch is for building {batch.get('buildingId')!r}, not {building_id!r}")

    building_file = building_file_name(building_id, source)
    batch_file = f"batch-{safe_name(building_id)}.json"
    report_file = f"report-{safe_name(building_id)}.md"
    report = make_report(batch, building)
    headlines = make_headlines(batch, building)
    headlines_file = f"headlines-{safe_name(building_id)}.json"
    files: dict[str, str | bytes] = {building_file: source.read_bytes()}  # the public file as it is, like sync-demo's copy
    files.update({item["name"]: item["text"] for item in runs})
    files[batch_file] = to_text(batch)
    if report:
        files[report_file] = report
    if headlines:
        files[headlines_file] = to_text(headlines)
    entries = {
        "building": {"id": building_id, "name": building["name"], "file": building_file,
                     **({"credits": building["credits"]} if building.get("credits") is not None else {})},
        "runs": [item["entry"] for item in runs],
        "batch": {"id": batch["id"], "buildingId": building_id, "file": batch_file,
                  **({"report": report_file} if report else {}), **({"headlines": headlines_file} if headlines else {})},
    }
    commit_building(building_id, files, entries, demo, state)
    if demo == DEMO_DIR.resolve():
        warn_stale_pack(building_id, batch, bool(headlines))
    say(f"  {building_id} done in {(time.perf_counter() - t_start) / 60:.1f} min")
    for item in runs:
        if item["note"]:
            say(f"  {item['entry']['id']}: {item['note']}")
    pairs: dict[str, dict] = {}
    for item in runs:
        e = item["entry"]
        pairs.setdefault(e["fire"]["room"], {})[e["whatIf"] or "base"] = item["metrics"]
    for room, pair in pairs.items():
        if "propped" in pair:
            say(f"  {room}, baseline -> {door} propped: {pair_story(pair['base'], pair['propped'])}")
    return True


def default_workers() -> int:
    """Cores - 2, at most 10: a worker holds about 0.6 GB of committed memory and the sim is memory bound, so
    more of them do not finish sooner (14 workers on 8 cores took 105 s a run against 45 s alone)."""
    return max(1, min(10, (os.cpu_count() or 2) - 2))


def commit_building(building_id: str, files: dict, entries: dict, demo: Path, state: dict) -> None:
    """Check the guards on the finished set, write the files, then index.json, then delete the files of the
    building's earlier precompute that this one did not write."""
    check_private(files, [building_id])
    index = load_index(demo)
    existing = folder_bytes(demo)

    def mine(e: dict, prefix: str) -> bool:  # an entry this tool wrote for the building (sync-demo's never start so)
        return e.get("buildingId") == building_id and str(e.get("file", "")).startswith(prefix)

    stale = [e["file"] for e in index["runs"] if mine(e, "run-")]
    for e in index["batches"]:
        if mine(e, "batch-"):
            stale += [e["file"], *([e["report"]] if e.get("report") else []), *([e["headlines"]] if e.get("headlines") else [])]
    stale = [name for name in dict.fromkeys(stale) if name not in files]

    sizes = {name: len(content.encode("utf-8") if isinstance(content, str) else content) for name, content in files.items()}
    big = [(n, s) for n, s in sizes.items() if s > MAX_FILE_BYTES]
    if big:
        fail("; ".join(f"{n} is {human(s)}" for n, s in big) + f" (limit {MAX_FILE_BYTES // MB} MB): rerun with --thin")
    projected = {**{n: s for n, s in existing.items() if n not in stale}, **sizes}
    if sum(projected.values()) > MAX_FOLDER_BYTES:
        fail(f"{demo} would hold {human(sum(projected.values()))} (limit {MAX_FOLDER_BYTES // MB} MB): rerun with --thin")

    for name, content in files.items():
        path = demo / name
        state["listed"][name] = sizes[name]
        if isinstance(content, bytes) and path.is_file() and path.read_bytes() == content:
            say(f"  {name}  {human(sizes[name])} (unchanged)")
            continue
        write_atomic(path, content)
        say(f"  {name}  {human(sizes[name])}")

    upsert(index["buildings"], entries["building"])
    index["runs"] = [e for e in index["runs"] if not mine(e, "run-")]
    # the app opens a building on the first baseline listed for it and the tour pairs that one with its propped
    # partner: ours (best what-if story first) go before any other run of the building, such as sync-demo's example
    first = next((i for i, e in enumerate(index["runs"]) if e.get("buildingId") == building_id), len(index["runs"]))
    index["runs"][first:first] = entries["runs"]
    # loadBatch takes the first batch listed for a building: ours goes before any other of its building, and
    # a placeholder (sync-demo's example batch) goes altogether, as sync-demo itself would drop it
    old = next((e for e in index["batches"] if mine(e, "batch-")), {})
    # keeps keys of the old entry that this tool does not own; `report` and `headlines` are rewritten with the batch
    batch_entry = {**{k: v for k, v in old.items() if k not in ("report", "headlines")}, **entries["batch"]}
    batches = [e for e in index["batches"] if not mine(e, "batch-")
               and not (e.get("buildingId") == building_id and is_placeholder(demo / str(e.get("file", ""))))]
    first = next((i for i, e in enumerate(batches) if e.get("buildingId") == building_id), len(batches))
    batches.insert(first, batch_entry)
    index["batches"] = batches
    index = {"version": index["version"], "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             **{k: v for k, v in index.items() if k not in ("version", "generated")}}
    write_atomic(demo / "index.json", to_text(index, indent=2))
    for name in stale:
        (demo / name).unlink(missing_ok=True)
        say(f"  removed stale {name}")
    if demo == DEMO_DIR.resolve():
        write_record(building_id, entries["batch"]["id"], files[entries["batch"]["file"]])
        pack = entries["batch"].get("headlines")
        if pack:  # sync-demo copies data/runs/headlines-ID.json too: the pack of this batch must be the one it finds
            write_atomic(CACHE_DIR / pack, files[pack])
            say(f"  data/runs/{pack}  (same bytes, for the same reason)")
    state["runs"] += len(entries["runs"])
    state["batches"] += 1


def write_record(building_id: str, batch_id: str, text: str) -> None:
    """data/runs/batch-ID.json is where frontend/scripts/sync-demo.mjs --runs (E28) looks for a building's batch
    and copies it into the demo, so this tool is its writer of record: the same bytes go there, and the copy
    finds nothing to change. A batch of D's in the way is kept as batch-ID.prev.json, not lost."""
    path = CACHE_DIR / f"batch-{safe_name(building_id)}.json"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        try:
            ours = json.loads(path.read_text(encoding="utf-8")).get("id") == batch_id
        except (OSError, ValueError, AttributeError):
            ours = False
        if not ours:
            backup = path.with_name(path.stem + ".prev.json")
            os.replace(path, backup)
            say(f"  {path.relative_to(ROOT).as_posix()} was not this tool's batch: kept as {backup.name}")
    write_atomic(path, text)
    say(f"  {path.relative_to(ROOT).as_posix()}  (the batch of record: sync-demo --runs copies this file, same bytes)")


def verify_index(demo: Path) -> list[str]:
    """What frontend/scripts/check-demo.mjs checks, without Node: every file the index lists exists, is the
    kind of file it is listed as, and belongs to the building it is listed under."""
    problems: list[str] = []
    index = load_index(demo)
    ids = {b["id"] for b in index["buildings"]}

    def head(name: str) -> str:  # version and buildingId come first in every file this tool writes
        path = demo / name
        if not path.is_file():
            problems.append(f"{name}: listed in index.json but missing")
            return ""
        with open(path, "rb") as f:
            return f.read(4096).decode("utf-8", "replace")

    def field(text: str, key: str) -> str | None:
        found = re.search(r'"%s"\s*:\s*"([^"]*)"' % key, text)
        return found.group(1) if found else None

    for entry in index["buildings"]:
        text = head(entry["file"])
        if text and field(text, "version") != "building/v0":
            problems.append(f"{entry['file']}: not a building/v0 file")
    for kind, version, entries in (("run", "run/v0", index["runs"]), ("batch", "batch/v0", index["batches"])):
        for entry in entries:
            if entry["buildingId"] not in ids:
                problems.append(f"{kind} {entry['id']}: its building {entry['buildingId']} is not in the index")
            text = head(entry["file"])
            if text and field(text, "version") != version:
                problems.append(f"{entry['file']}: not a {version} file")
            if text and field(text, "buildingId") != entry["buildingId"]:
                problems.append(f"{entry['file']}: for building {field(text, 'buildingId')}, listed under {entry['buildingId']}")
            if entry.get("report"):
                head(entry["report"])
    return problems


def is_placeholder(path: Path) -> bool:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("placeholder") is True
    except (OSError, ValueError, AttributeError):
        return False


# ----------------------------------------------------------------------------- live report cards


def live_reports(args, demo: Path, live: bool = True) -> int:
    """Rewrite report-*.md from the batches already in the demo folder: no simulation. live=True asks Gemini and a card
    only replaces the file when the model wrote it (a template, from quota, busy or no key, leaves the old one);
    live=False (--refresh-reports) writes the template card again, with no model call, for when its wording changed."""
    if live:
        if os.environ.get("LLM_PROVIDER", "").strip().lower() == "off":
            del os.environ["LLM_PROVIDER"]  # a shell that exports off must not win here; .env decides again
    else:
        os.environ["LLM_PROVIDER"] = "off"
    from backend.llm import client  # loads .env: after the lines above, so its LLM_PROVIDER counts
    from backend.llm.features import report_card

    provider = client.provider()
    if live and provider == "off":
        fail("LLM_PROVIDER is off in .env; set it to gemini (or claude) for --live-reports")
    index = load_index(demo)
    wanted = set(args.building or [])
    entries = [b for b in index["batches"] if not wanted or b["buildingId"] in wanted]
    if not entries:
        fail("no batch in the demo index" + (f" for {', '.join(sorted(wanted))}" if wanted else ""))
    if live:
        say(f"live report cards with {provider} ({len(entries)} batch{'es' if len(entries) != 1 else ''}); "
            "the free tier allows 20 requests a day per model")
    else:
        say(f"template report cards, no model call ({len(entries)} batch{'es' if len(entries) != 1 else ''})")
    changed = 0
    for entry in entries:
        building_entry = next((b for b in index["buildings"] if b["id"] == entry["buildingId"]), None)
        if building_entry is None:
            say(f"  {entry['id']}: its building is not in the index, skipped")
            continue
        batch = json.loads((demo / entry["file"]).read_text(encoding="utf-8"))
        building = json.loads((demo / building_entry["file"]).read_text(encoding="utf-8"))
        if building.get("private") is True or batch.get("placeholder"):
            say(f"  {entry['id']}: private or placeholder data, skipped")
            continue
        markdown, ai = report_card(batch, building, allow_llm=True)
        name = entry.get("report") or f"report-{safe_name(entry['buildingId'])}.md"
        path = demo / name
        if live and not ai and path.is_file():
            say(f"  {name}: the model gave nothing usable (quota, busy or no key); kept the card as it was")
            continue
        check_private({name: markdown}, [entry["buildingId"]])
        write_atomic(path, markdown)
        entry["report"] = name
        changed += 1
        headline = next((ln.strip("* ") for ln in markdown.splitlines() if ln.startswith("**")), "")
        say(f"  {name}: {'written by ' + provider if ai else 'template' + (' (no model answer, no earlier card)' if live else '')}")
        say(f"    {headline}")
    if changed:
        write_atomic(demo / "index.json", to_text(index, indent=2))
    say(f"OK: {changed} report card{'s' if changed != 1 else ''} written")
    return 0


# ----------------------------------------------------------------------------- main


def parse_args(argv):
    head, _, rest = __doc__.partition("\n\n")
    p = argparse.ArgumentParser(description=head, epilog=rest, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--building", action="append", metavar="ID", help="building id (repeat for several)")
    p.add_argument("--all", action="store_true", help="every public building")
    p.add_argument("--rooms", type=lambda s: [r for r in s.split(",") if r], metavar="R1,R2",
                   help="fire rooms for the baseline and propped runs, in this order (default: the 4 highest-risk plus the first kitchen)")
    p.add_argument("--top", type=int, metavar="N", help=f"how many highest-risk rooms get runs (default {TOP_ROOMS}, example 3)")
    p.add_argument("--max-rooms", type=int, metavar="N", help="batch: N evenly spaced fire rooms instead of every room")
    p.add_argument("--propped-door", metavar="DOOR", help="door that is closed in the baseline and propped in the what-if")
    p.add_argument("--batch", type=Path, metavar="FILE",
                   help="use this finished batch/v0 of the building (D's fire.batch or fire.demo output) instead of running "
                        "one: its base scenario drives the runs, and no sweeps are run on it")
    p.add_argument("--seeds", type=lambda s: [int(x) for x in s.split(",") if x], default=list(DEFAULT_SEEDS),
                   help="batch seeds (default 1,2,3); the runs use the lowest")
    p.add_argument("--occupants", type=int, metavar="N", help="total occupants (office default 250)")
    p.add_argument("--fire-type", metavar="TYPE", help="kitchen, bedroom, battery, trash or liquid (office default kitchen)")
    p.add_argument("--thin", action="store_true", help="every 2nd agent frame, every 3rd smoke frame")
    p.add_argument("--sweep-rooms", type=int, default=SWEEP_ROOMS, metavar="N",
                   help=f"rooms the what-if sweep and fixes rerun (default {SWEEP_ROOMS})")
    p.add_argument("--no-sweeps", action="store_true", help="skip the what-if sweep and the measured fixes")
    p.add_argument("--skip-variants", type=lambda s: [] if s == "none" else [v for v in s.split(",") if v], metavar="ID,ID",
                   help="what-if variants to leave out (office default blockedExit; 'none' keeps them all)")
    p.add_argument("--workers", type=int, metavar="N", help="processes (default: cores - 2, at most 10)")
    p.add_argument("--resume", action="store_true", help="reuse the raw batch of the last run when it still fits")
    p.add_argument("--live-reports", action="store_true", help="instead of simulating: rewrite report-*.md with Gemini from the batches already in --out")
    p.add_argument("--refresh-reports", action="store_true", help="instead of simulating: write report-*.md again as template cards (no model) from the batches already in --out")
    p.add_argument("--out", type=Path, default=DEMO_DIR, metavar="DIR", help="output folder (default frontend/public/demo)")
    args = p.parse_args(argv)
    if args.live_reports and args.refresh_reports:
        p.error("--live-reports and --refresh-reports are separate modes")
    if not args.live_reports and not args.refresh_reports and not args.building and not args.all:
        p.error("give --building ID (or --all)")
    if args.batch and (args.all or len(args.building or []) != 1):
        p.error("--batch needs exactly one --building")
    if (args.top is not None and args.top < 0) or (args.max_rooms is not None and args.max_rooms < 1) or args.sweep_rooms < 0:
        p.error("--top and --sweep-rooms cannot be negative, --max-rooms must be at least 1")
    if not args.seeds:
        p.error("--seeds needs at least one seed")
    return args


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):  # a Windows console may not encode every room name
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args = parse_args(argv)
    demo = args.out.resolve()
    if args.live_reports or args.refresh_reports:
        return live_reports(args, demo, live=args.live_reports)
    os.environ["LLM_PROVIDER"] = "off"  # the template card; the sim's rule agents never ask a model anyway

    ids = public_building_ids() if args.all else list(dict.fromkeys(args.building))
    state = {"listed": {}, "runs": 0, "batches": 0}
    started = time.perf_counter()
    for building_id in ids:
        process_building(building_id, args, demo, state)
    if not state["batches"]:
        say("nothing was written")
        return 1
    problems = verify_index(demo)
    if problems:
        fail("index.json does not match the files:\n  " + "\n  ".join(problems))
    total = sum(folder_bytes(demo).values())
    say(f"{demo.name}/ holds {human(total)} in all, {(time.perf_counter() - started) / 60:.1f} min for this run")
    if total > TARGET_FOLDER_BYTES:
        say(f"WARNING: over the {TARGET_FOLDER_BYTES // MB} MB aim for the static site (--thin, fewer rooms with --top, or --rooms)")
    say(f"OK: {state['runs']} runs, {state['batches']} batch{'es' if state['batches'] != 1 else ''}, "
        f"{sum(state['listed'].values()) / MB:.1f} MB")
    return 0


if __name__ == "__main__":  # Windows spawns the pool's workers by importing this file: main() must not run there
    sys.exit(main())
