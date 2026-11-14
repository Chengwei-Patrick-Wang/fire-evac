"""Refresh the headline numbers after C14 (smoke-aware exit choice) and C13b (stair arrivals).

Runs the same rooms and seeds twice on the same code: once with C14's exit-choice terms off (the "legacy" side)
and once with them on (the "current" side), each with its what-ifs and measured fixes, then reports which
headline numbers moved and why. It writes data/runs/batch-<id>.json, batch-<id>-c14off.json,
headlines-<id>.json and headlines-<id>-c14off.json; an existing batch-<id>.json or headlines-<id>.json is renamed
to <name>.prev.json first (never deleted). The model is illustrative; these are ideas to check, not a compliance result.

Run from the repo root:
  python -m fire.refresh BUILDING SCENARIO [--occupants N] [--fire-type T] [--rooms 12] [--seeds 1,2,3] [--workers N] [--check] [--resume]
Exit codes: 0 done (or --check), 1 a file is missing, 3 nothing to refresh yet (C14 or, on the office, C13b is missing).
"""
import argparse
from collections import Counter
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time

from fire.batch import _ignitions, _init, _run_one, _tasks, _workers, apply_overrides, door_label, run_many
from fire.fixes import add_fixes, planned_fix_runs
from fire.headlines import _clean, _modified, _shown, build_headlines
from fire.whatif import add_whatif, default_variants

SMOKE_PCT_POINTS = 5.0        # smokePct moves by at least this many points
DT90_S = 5.0                  # dT90 moves by at least this many seconds
TRAPPED = 0.5                 # dTrapped moves by at least this many people per fire
SMOKE_SECONDS_SHARE = 0.10    # dSmokeSeconds (when there is no smokePct) moves by this share of the larger value
EXIT_SHARE = 0.05             # an exit's use moves by this share of the evacuees
EPS = 1e-9
TAIL = "with C14's exit-choice terms on"
SIDES = (("legacy", "C14 terms off"), ("current", "C14 terms on"))
PROBE = {"floor": "F1", "room": "R106", "seed": 2, "door": "D$77wwb", "occupants": 250, "maxTime": 240}
RUNS_DIR = Path("data/runs")


def _ascii(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


def sim_features() -> dict:
    """Which pieces of C14 this checkout has, read from the simulator's source (JuPedSim is not imported)."""
    def source(module):
        spec = importlib.util.find_spec(module)
        return Path(spec.origin).read_text(encoding="utf-8") if spec and spec.origin else ""

    return {"smokeAwareExits": bool(re.search(r"^SMOKE_BETA\s*=", source("sim.brain"), re.M))
            or "exitChoice" in source("sim.run")}


def stair_probe(office: dict, base: dict) -> bool:
    """C13b: D15's repro. A kitchen fire in R106, seed 2, 250 occupants, exit D$77wwb blocked, maxTime 240.

    Before C13b it raised `too close to geometry boundaries` (a stair arrival next to the blocked exit).
    Returns True when the run finishes, False for that error, and raises for any other error.
    """
    scenario = apply_overrides(base, occupants=PROBE["occupants"], fire_type="kitchen")
    scenario["doors"] = {**scenario.get("doors", {}), PROBE["door"]: "blocked"}
    scenario["maxTime"] = PROBE["maxTime"]
    task = _tasks(office, scenario, [{"floor": PROBE["floor"], "room": PROBE["room"]}], [PROBE["seed"]])[0]
    _init(office)
    record = _run_one(task)
    if record["ok"]:
        return True
    if "geometry boundar" in record["error"]:
        return False
    raise RuntimeError(f"stair probe failed for another reason: {record['error']}")


def terms_off(base: dict) -> dict:
    """A copy of `base` with C14's exit-choice terms off (not "before C14": its smoke trigger is separate)."""
    result = deepcopy(base)
    result["exitChoice"] = {"smoke": 0, "unfamiliar": 0}
    result["id"] = f"{base['id']}-c14off"
    return result


def refresh(building: dict, base: dict, ignitions: list[dict], seeds, workers: int | None = None,
            timeout_s: float = 7200, progress: bool = True, on_stage=None, resume: dict | None = None,
            retries: int = 1) -> dict:
    """Both sides on the same code: {"legacy": batch, "current": batch}.

    Same rooms, seeds and what-if variants on both sides (the variants come from the current baseline, so
    `blockedExit` blocks the same door); the scenarios differ only in `exitChoice` and the id. The order is
    both baselines, then each variant on both sides in turn (so a stopped run still holds paired what-ifs),
    then the fixes, the current side first (it is the side the demo quotes). `on_stage(side, stage, batch)`,
    when given, is called after every finished stage with that side's batch so far.

    A baseline or what-if stage whose runs did not all finish (a worker died: on a shared laptop a pool can
    break) is run again, up to `retries` times, and the attempt with the most finished runs is kept. `resume`
    is `{side: batch}` from the checkpoints of a stopped run: stages it holds in full are not run again.
    """
    scenarios = {"legacy": terms_off(base), "current": deepcopy(base)}
    planned = {(i["floor"], i["room"], int(s)) for i in ignitions for s in seeds}
    batches = {}

    def done(side, stage, batch):
        batches[side] = batch
        if on_stage is not None:
            on_stage(side, stage, batch)

    def say(text):
        if progress:
            print(f"[refresh {time.strftime('%H:%M:%S')}] {text}", flush=True)

    def whole(batch):
        keys = {(r["ignition"]["floor"], r["ignition"]["room"], r["seed"]) for r in batch["runs"]}
        return not batch.get("failed") and keys == planned

    for side, label in SIDES:
        batch = deepcopy((resume or {}).get(side))
        if batch is not None and batch.get("base") != scenarios[side]:
            raise ValueError(f"the {side} checkpoint was made with another scenario (its base differs)")
        if batch is not None and whole(batch):
            say(f"{label}: baseline taken from the checkpoint")
        else:
            batch = None
            for attempt in range(1 + retries):
                say(f"{label}: baseline, {len(ignitions)} rooms x {len(seeds)} seeds" + (" (again)" if attempt else ""))
                result = run_many(building, scenarios[side], ignitions, seeds, workers, timeout_s, progress)
                if batch is None or len(result["runs"]) > len(batch["runs"]):
                    batch = result
                if whole(result):
                    break
                say(f"{label}: {len(result['failed'])} of {len(planned)} baseline runs failed")
        done(side, "baseline", batch)
    variants = default_variants(building, base, batches["current"]["runs"])
    order = {v["id"]: i for i, v in enumerate(variants)}
    for variant in variants:
        for side, label in SIDES:
            batch, fires = batches[side], len(batches[side]["runs"])
            if any(w["id"] == variant["id"] and w["n"] == fires for w in batch.get("whatIf", [])):
                say(f"{label}: what-if {variant['id']} taken from the checkpoint")
                continue
            others = [w for w in batch.get("whatIf", []) if w["id"] != variant["id"]]
            stage = None
            for attempt in range(1 + retries):
                say(f"{label}: what-if {variant['id']}" + (" (again)" if attempt else ""))
                result = add_whatif(building, scenarios[side], batch, variants=[variant],
                                    workers=workers, timeout_s=timeout_s, progress=progress)
                if stage is None or result["whatIf"][0]["n"] > stage["whatIf"][0]["n"]:
                    stage = result
                if result["whatIf"][0]["n"] == fires:
                    break
                say(f"{label}: what-if {variant['id']} paired {result['whatIf'][0]['n']} of {fires} fires")
            entries = sorted([*others, *stage["whatIf"]], key=lambda w: order.get(w["id"], len(order)))
            # Fixes measured against an earlier what-if of this side are stale now.
            done(side, f"what-if {variant['id']}", {**{k: v for k, v in stage.items() if k not in ("fixes", "fixesSkipped")},
                                                    "whatIf": entries})
    for side, label in reversed(SIDES):
        if "fixes" in batches[side]:
            say(f"{label}: fixes taken from the checkpoint")
            continue
        say(f"{label}: fixes")
        done(side, "fixes", add_fixes(building, scenarios[side], batches[side],
                                      workers=workers, timeout_s=timeout_s, progress=progress))
    return {"legacy": batches["legacy"], "current": batches["current"]}


def _entry(key, label, old, new, changed, why) -> dict:
    """One compared number; floats are rounded to 2 decimals (`changed` was decided on the exact values)."""
    rounded = lambda value: round(value, 2) if isinstance(value, float) else value
    return {"key": key, "label": label, "old": rounded(old), "new": rounded(new),
            "changed": bool(changed), "why": _ascii(why)}


def _pct(value):
    return f"{round(value):+d}%"


def _smoke_seconds(value):
    return f"{value:+,.0f} person-seconds"


def _seconds(value):
    return f"{round(value):+d} s"


def _people(value):
    return f"{round(value, 1) + 0.0:+.1f}"


def _yes(value):
    return "yes" if value else "no"


def _fires(old, new) -> str:
    if old is None or new is None:
        return ""
    plural = lambda n: f"{n} fire{'' if n == 1 else 's'}"
    return f" (same {plural(new)})" if old == new else f" ({plural(old)}, then {new})"


def _moved(field, old, new) -> bool:
    delta = abs(new - old)
    if field == "smokePct":
        return delta >= SMOKE_PCT_POINTS - EPS
    if field == "dSmokeSeconds":
        return delta > EPS and delta >= SMOKE_SECONDS_SHARE * max(abs(old), abs(new)) - EPS
    if field == "dT90":
        return delta >= DT90_S - EPS
    return delta >= TRAPPED - EPS  # dTrapped


def _item_entries(section: str, old: dict, new: dict) -> list[dict]:
    """The compared numbers of one what-if or fix that both sides measured."""
    ident = new["id"]
    label = new.get("label") or old.get("label") or ident
    fires = _fires(old.get("n"), new.get("n"))
    smoke = next(((field, fmt) for field, fmt in (("smokePct", _pct), ("dSmokeSeconds", _smoke_seconds))
                  if field in old and field in new), None)
    specs = [(smoke[0], "smoke exposure", smoke[1])] if smoke else []
    specs += [(field, name, fmt) for field, name, fmt in (("dT90", "90% out time", _seconds),
                                                          ("dTrapped", "trapped per fire", _people))
              if field in old and field in new]
    entries = []
    for field, name, fmt in specs:
        text = f"{label}, {name}"
        entries.append(_entry(f"{section}.{ident}.{field}", text, old[field], new[field],
                              _moved(field, old[field], new[field]),
                              f"{text}: {fmt(old[field])} -> {fmt(new[field])} {TAIL}{fires}."))
    if "helps" in old and "helps" in new:
        text = f"{label}, helps"
        entries.append(_entry(f"{section}.{ident}.helps", text, bool(old["helps"]), bool(new["helps"]),
                              bool(old["helps"]) != bool(new["helps"]),
                              f"{text}: {_yes(old['helps'])} -> {_yes(new['helps'])} {TAIL}{fires}."))
    return entries


def diff_headlines(old: dict, new: dict) -> list[dict]:
    """What moved between two D18 packs: [{key, label, old, new, changed, why}], old pack = C14 terms off.

    Compares the ids of the top 3 weak spots in order and, for every what-if and fix id, `smokePct` (else
    `dSmokeSeconds`), `dT90`, `dTrapped` and, for fixes, `helps`. A number counts as changed when it moves by
    at least SMOKE_PCT_POINTS (dSmokeSeconds: SMOKE_SECONDS_SHARE of the larger value), DT90_S or TRAPPED, when
    `helps` flips, when the top 3 differ, or when an id was measured on one side only.
    """
    entries = []
    top = [[s["id"] for s in pack.get("weakSpots", [])[:3]] for pack in (old, new)]
    if top[0] or top[1]:
        names = [", ".join(s.get("label") or s["id"] for s in pack.get("weakSpots", [])[:3]) or "none"
                 for pack in (old, new)]
        why = (f"Top 3 weak spots: {names[0]}, the same {TAIL}." if top[0] == top[1]
               else f"Top 3 weak spots: {names[0]} -> {names[1]} {TAIL}.")
        entries.append(_entry("top3", "Top 3 weak spots", top[0], top[1], top[0] != top[1], why))
    for section in ("whatIf", "fixes"):
        before = {item["id"]: item for item in old.get(section, [])}
        after = {item["id"]: item for item in new.get(section, [])}
        for ident in [*before, *(i for i in after if i not in before)]:
            if ident in before and ident in after:
                entries += _item_entries(section, before[ident], after[ident])
                continue
            item = before.get(ident) or after[ident]
            label = item.get("label") or ident
            side = "off" if ident in before else "on"
            entries.append(_entry(f"{section}.{ident}", label, before[ident].get("why") if ident in before else None,
                                  after[ident].get("why") if ident in after else None, True,
                                  f"{label}: measured only with C14's exit-choice terms {side}."))
    return entries


def exit_shift(legacy: dict, current: dict, building: dict) -> dict:
    """One more `changes` entry (key `exitUse`): how many people used each exit across the baseline fires.

    Sums `runs[].exitCounts` per exit on each side. It is `changed` when an exit moves by EXIT_SHARE of the
    evacuees or more, and its `why` names the two largest moves.
    """
    where = {e["id"]: (f["id"], e["door"]) for f in building.get("floors", []) for e in f.get("exits", [])}

    def label(exit_id):
        floor, door = where.get(exit_id, (None, exit_id))
        return door_label(building, floor, door)[1] if floor is not None else f"Exit {exit_id}"

    def total(batch):
        counts = Counter()
        for run in batch.get("runs", []):
            counts.update(run.get("exitCounts", {}))
        return counts

    before, after = total(legacy), total(current)
    evacuees = max(sum(before.values()), sum(after.values()))
    moves = sorted(((abs(after[k] - before[k]), label(k), before[k], after[k]) for k in {*before, *after}),
                   key=lambda m: (-m[0], m[1]))
    shown = [f"{name} {a} -> {b}" for move, name, a, b in moves[:2] if move > 0]
    if shown:
        shown[0] += " people"
    changed = bool(moves) and evacuees > 0 and moves[0][0] >= EXIT_SHARE * evacuees - EPS
    return _entry("exitUse", "Exit use across the baseline fires",
                  {label(k): before[k] for k in sorted(before)}, {label(k): after[k] for k in sorted(after)},
                  changed, "Exit use across the baseline fires: " + (", ".join(shown) if shown else "no exit moved") + ".")


def _archive(path: Path) -> Path | None:
    """Rename an existing file to <name>.prev.json (.prev2.json, ... when taken); nothing is overwritten."""
    if not path.exists():
        return None
    number, target = 1, path.with_name(f"{path.stem}.prev.json")
    while target.exists():
        number += 1
        target = path.with_name(f"{path.stem}.prev{number}.json")
    path.rename(target)
    return target


def _write_atomic(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_name(path.name + ".tmp")
    scratch.write_text(text, encoding="utf-8")
    os.replace(scratch, path)


def _ascii_value(value):
    if isinstance(value, str):
        return _ascii(value)
    if isinstance(value, list):
        return [_ascii_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _ascii_value(v) for k, v in value.items()}
    return value


def _with_changes(pack: dict, features: dict, legacy_headline: str | None, changes: list[dict]) -> dict:
    """The current pack plus optional `features`, `legacyHeadline` and `changes` (the changed entries only)."""
    extra = _ascii_value(_clean({"features": features, "legacyHeadline": legacy_headline,
                                 "changes": [_clean(c) for c in changes if c["changed"]] or None}))
    result = {}
    for key, value in pack.items():
        if key == "scenario" and "features" in extra:
            result["features"] = extra["features"]
        result[key] = value
        if key == "headline":
            result.update({k: extra[k] for k in ("legacyHeadline", "changes") if k in extra})
    for key in ("features", "legacyHeadline", "changes"):
        if key in extra and key not in result:
            result[key] = extra[key]
    return result


def output_paths(building_id: str, runs_dir: Path = RUNS_DIR) -> dict:
    """{side: (batch path, headlines path)} for the two sides."""
    return {"current": (runs_dir / f"batch-{building_id}.json", runs_dir / f"headlines-{building_id}.json"),
            "legacy": (runs_dir / f"batch-{building_id}-c14off.json", runs_dir / f"headlines-{building_id}-c14off.json")}


def publish(building: dict, result: dict, features: dict, runs_dir: Path = RUNS_DIR,
            compare: dict | None = None) -> list[dict]:
    """Compare the two sides, rename earlier files to .prev, write both batches and both packs, and report.

    `features` goes into the current pack (`smokeAwareExits`, and on the office `stairArrivalsFixed`). Returns
    the compared entries, changed or not; the pack's `changes` holds only the changed ones. `compare` (default:
    `result`) is for a stopped run that finished more on one side than the other: the two batches to compare,
    cut down to what both sides finished. The files always get `result`.
    """
    targets = output_paths(building["id"], runs_dir)
    basis = compare or result
    # Everything that can fail is computed before any file is renamed or written.
    trial = {side: build_headlines(building, basis[side]) for side in basis}
    changes = diff_headlines(trial["legacy"], trial["current"]) + [exit_shift(basis["legacy"], basis["current"], building)]
    archived = {path: _archive(path) for pair in targets.values() for path in pair}
    previous = archived[targets["current"][1]]
    previous_headline = json.loads(previous.read_text(encoding="utf-8")).get("headline") if previous else None
    written = []
    for side in ("legacy", "current"):
        batch_path, pack_path = targets[side]
        _write_atomic(batch_path, json.dumps(result[side], separators=(",", ":")))
        sources = {"batch": _clean({"file": _shown(batch_path), "id": result[side].get("id"),
                                    "modified": _modified(batch_path)})}
        pack = build_headlines(building, result[side], sources=sources)
        if side == "current":
            pack = _with_changes(pack, features, trial["legacy"].get("headline"), changes)
        data = json.dumps(pack, indent=1, allow_nan=False).encode("utf-8")
        pack_path.write_bytes(data)  # bytes, so Windows keeps LF and the size below is the file's
        written.append(f"wrote {batch_path.as_posix()} ({len(result[side]['runs'])} runs, "
                       f"{len(result[side]['failed'])} failed) and {pack_path.as_posix()} ({len(data)} bytes)")
    for path, moved in archived.items():
        if moved:
            print(f"renamed {path.as_posix()} to {moved.as_posix()}", flush=True)
    if previous_headline:
        print(f"previous pack: {previous_headline}", flush=True)
    print(f"C14 terms off: {trial['legacy'].get('headline', '(no headline)')}", flush=True)
    print(f"C14 terms on:  {trial['current'].get('headline', '(no headline)')}", flush=True)
    changed = [c for c in changes if c["changed"]]
    print(f"{len(changed)} of {len(changes)} compared numbers changed:", flush=True)
    for change in changed:
        print(change["why"], flush=True)
    quiet = [c["key"] for c in changes if not c["changed"]]
    if quiet:
        print(f"unchanged: {', '.join(quiet)}", flush=True)
    for line in written:
        print(line, flush=True)
    return changes


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("building", type=Path)
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--occupants", type=int, help="override total occupants, preserving the mix")
    parser.add_argument("--fire-type", help="override the fire preset and remove growth overrides")
    parser.add_argument("--rooms", type=int, default=12, help="ignition rooms, sampled as in fire.batch (default 12)")
    parser.add_argument("--seeds", default="1,2,3")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--check", action="store_true",
                        help="print which of C14 and C13b this checkout has, and exit 0")
    parser.add_argument("--resume", action="store_true",
                        help="continue a stopped run from its checkpoints (data/runs/batch-<id>[-c14off].partial.json)")
    args = parser.parse_args(argv)
    for path in (args.building, args.scenario):
        if not path.is_file():
            print(f"no such file: {path.as_posix()}", file=sys.stderr)
            return 1
    building = json.loads(args.building.read_text(encoding="utf-8"))
    base = json.loads(args.scenario.read_text(encoding="utf-8"))
    try:
        base = apply_overrides(base, args.occupants, args.fire_type)
    except ValueError as error:
        parser.error(str(error))
    seeds = tuple(sorted({int(seed) for seed in args.seeds.split(",")}))
    workers = _workers(args.workers)
    if workers < 1 or args.rooms < 1:
        parser.error("--workers and --rooms must be positive")

    features = sim_features()
    stairs = stair_probe(building, base) if building["id"] == "office" else None
    print(f"C14 smoke-aware exit choice: {_yes(features['smokeAwareExits'])}; C13b stair arrivals: "
          f"{'n/a' if stairs is None else _yes(stairs)}", flush=True)
    if args.check:
        return 0
    if not features["smokeAwareExits"] or stairs is False:
        print("nothing to refresh yet", flush=True)
        return 3

    started = time.perf_counter()
    ignitions = _ignitions(building, base, args.rooms)
    fires = len(ignitions) * len(seeds)
    sweeps = len(default_variants(building, base, [])) + planned_fix_runs(building, base)
    print(f"refresh plan: {len(ignitions)} rooms x {len(seeds)} seeds = {fires} fires per side; up to {sweeps} "
          f"paired reruns of each -> about {2 * fires * (1 + sweeps)} runs on {workers} workers", flush=True)
    partial = {side: batch.with_name(batch.stem + ".partial.json") for side, (batch, _) in output_paths(building["id"]).items()}

    def checkpoint(side, stage, batch):
        _write_atomic(partial[side], json.dumps(batch, separators=(",", ":")))
        print(f"checkpoint {partial[side].as_posix()}: {dict(SIDES)[side]}, {stage} done", flush=True)

    resume = None
    if args.resume:
        resume = {side: json.loads(path.read_text(encoding="utf-8")) for side, path in partial.items() if path.is_file()}
        print(f"resuming from {', '.join(p.as_posix() for s, p in partial.items() if s in resume) or 'no checkpoints'}", flush=True)
    result = refresh(building, base, ignitions, seeds, workers, on_stage=checkpoint, resume=resume)
    publish(building, result, {"smokeAwareExits": features["smokeAwareExits"],
                               **({} if stairs is None else {"stairArrivalsFixed": stairs})})
    for path in partial.values():
        path.unlink(missing_ok=True)  # only this run's own checkpoints
    print(f"runtime {time.perf_counter() - started:.1f} s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
