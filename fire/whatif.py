"""Paired, rule-based what-if sweeps with illustrative smoke exposure."""
from copy import deepcopy

from fire.batch import door_label, run_many
from fire.presets import sprinklers_matter


def stair_doors(building: dict) -> list[str]:
    result = []
    for floor in building["floors"]:
        stairs = {s["room"] for s in floor.get("stairs", [])}
        stairs.update(r["id"] for r in floor["rooms"] if r.get("type") == "stair")
        result.extend(d["id"] for d in floor["doors"]
                      if "outside" not in d["connects"] and stairs.intersection(d["connects"]))
    return result


def default_variants(building: dict, base: dict, runs: list[dict]) -> list[dict]:
    sprinklers = base.get("sprinklers", False)
    variants = [{"id": "proppedStairs", "label": "Stair doors propped open",
                 "doors": dict.fromkeys(stair_doors(building), "propped"), "sprinklers": sprinklers}]
    exits = [{**e, "floor": f["id"]} for f in building["floors"] for e in f.get("exits", [])]
    widths = {d["id"]: d["width"] for f in building["floors"] for d in f["doors"]}
    if len(exits) >= 2:
        # Counts use exit ids; scenario overrides use the associated door ids.
        chosen = min(exits, key=lambda e: (
            -sum(r.get("exitCounts", {}).get(e["id"], 0) for r in runs),
            -widths[e["door"]], e["id"]))
        variants.append({"id": "blockedExit", "label": f"{door_label(building, chosen['floor'], chosen['door'])[1]} blocked",
                         "doors": {chosen["door"]: "blocked"}, "sprinklers": sprinklers})
    if sprinklers_matter(base):
        variants.append({"id": "sprinklers", "label": "Sprinklers on", "doors": {}, "sprinklers": True})
    return variants


def _key(run):
    return run["ignition"]["floor"], run["ignition"]["room"], run["seed"]


def compare(base: dict, baseline_runs: list[dict], variant_runs: list[dict]) -> dict:
    baseline = {_key(r): r for r in baseline_runs if r.get("ok", True)}
    pairs = [(baseline[_key(r)], r) for r in variant_runs
             if r.get("ok", True) and _key(r) in baseline]
    n = len(pairs)

    def effective(run):
        return run["t90"] if run["t90"] is not None else base["maxTime"]

    times = [effective(v) - effective(b) for b, v in pairs]
    result = {"n": n, "dT90": sum(times) / n if n else 0.0,
              "dT90Min": min(times, default=0.0), "dT90Max": max(times, default=0.0),
              "slower": sum(t > 1 for t in times), "faster": sum(t < -1 for t in times),
              "dTrapped": sum(v["trapped"] - b["trapped"] for b, v in pairs) / n if n else 0.0}
    for source, target in (("dosed", "dDosed"), ("smokeSeconds", "dSmokeSeconds")):
        if pairs and all(source in b and source in v for b, v in pairs):
            result[target] = sum(v[source] - b[source] for b, v in pairs) / n
    return result


def smoke_base(baseline_runs: list[dict], variant_runs: list[dict], stats: dict) -> dict:
    """baseSmokeSeconds and smokePct of one comparison, from the baseline side of its pairs.

    The mean covers exactly the baseline runs that a successful variant run matches (the pairs
    `compare` used); smokePct is null when that mean is 0. Empty without dSmokeSeconds.
    """
    if "dSmokeSeconds" not in stats:
        return {}
    baseline = {_key(r): r for r in baseline_runs if r.get("ok", True)}
    matched = [baseline[_key(r)] for r in variant_runs if r.get("ok", True) and _key(r) in baseline]
    mean = sum(r["smokeSeconds"] for r in matched) / len(matched)
    return {"baseSmokeSeconds": mean,
            "smokePct": 100 * stats["dSmokeSeconds"] / mean if mean > 0 else None}


def _opens_onto(building: dict, floor_id: str, room_id: str, doors) -> str | None:
    """"exit" when one of `doors` joins the room to outside, "door" when one joins it to another room, else None."""
    floor = next((f for f in building.get("floors", []) if f["id"] == floor_id), {})
    ids = {doors} if isinstance(doors, str) else set(doors)
    joins = [d.get("connects", []) for d in floor.get("doors", []) if d["id"] in ids and room_id in d.get("connects", [])]
    if any("outside" in connects for connects in joins):
        return "exit"
    return "door" if joins else None


def room_deltas(baseline_runs: list[dict], variant_runs: list[dict], key="trapped",
                building: dict | None = None, doors=()) -> list[dict]:
    """Where a paired change comes from: the summed variant-minus-baseline `key` per ignition room.

    Pairs are `compare`'s (same floor, room and seed; failed runs dropped). Rooms whose fires sum to zero are
    left out and the rest come largest change first (then floor, room). `label` is `<room name> (<id>)` from
    `building` (the id alone without a name), `fires` the matched fires in the room, and `opensOnto` says what
    one of `doors` (door ids, as a variant's or a fix's overrides) joins the room to: "exit" (outside), "door"
    (another room) or None.
    """
    baseline = {_key(r): r for r in baseline_runs if r.get("ok", True)}
    names = {(f["id"], r["id"]): r.get("name")
             for f in (building or {}).get("floors", []) for r in f.get("rooms", [])}
    totals = {}
    for run in variant_runs:
        if not run.get("ok", True) or _key(run) not in baseline:
            continue
        before = baseline[_key(run)]
        if key not in before or key not in run:
            continue
        total = totals.setdefault(_key(run)[:2], [0, 0])
        total[0] += run[key] - before[key]
        total[1] += 1
    rows = []
    for (floor, room), (delta, fires) in totals.items():
        delta = round(delta, 6)
        if delta == 0:
            continue
        name = names.get((floor, room))
        label = f"{name} ({room})" if name and name != room else room
        rows.append({"floor": floor, "room": room, "label": label.encode("ascii", "replace").decode("ascii"),
                     "delta": delta, "fires": fires,
                     "opensOnto": _opens_onto(building, floor, room, doors) if building else None})
    return sorted(rows, key=lambda row: (-abs(row["delta"]), row["floor"], row["room"]))


def trapped_note(stats: dict) -> str:
    """"(47 of 47 in fires in Lobby (L1), which this exit opens onto)": the fires behind a trapped number, or "".

    The total is `round(dTrapped * n)`. A note needs a total of at least 1 person and a first `dTrappedRooms`
    row of the same sign that holds at least half of it and no more than all of it (so the "of" never exceeds
    the total). "which this exit|door opens onto" follows the row's `opensOnto` and is left out when it is null.
    """
    rows = stats.get("dTrappedRooms") or []
    total = round(stats.get("dTrapped", 0.0) * stats.get("n", 0))
    if not rows or abs(total) < 1:
        return ""
    first = rows[0]
    if first["delta"] * total <= 0 or 2 * abs(first["delta"]) < abs(total) or abs(first["delta"]) > abs(total):
        return ""
    opens = {"exit": ", which this exit opens onto", "door": ", which this door opens onto"}.get(first.get("opensOnto"), "")
    return f"({round(abs(first['delta']))} of {abs(total)} in fires in {first.get('label') or first['room']}{opens})"


def _why(label, stats):
    if not stats["n"]:
        return f"{label}: no successful matched fires (0 pairs).".encode("ascii", "replace").decode("ascii")
    text = (f"{label}: 90% out {abs(stats['dT90']):.0f} s "
            f"{'later' if stats['dT90'] >= 0 else 'sooner'} on average "
            f"(slower in {stats['slower']} of {stats['n']} fires); ")
    clauses = []
    if "dSmokeSeconds" in stats:
        clause = f"{stats['dSmokeSeconds']:+,.0f} person-seconds in smoke"
        if stats.get("smokePct") is not None:
            clause += f" ({round(stats['smokePct']):+d}%)"
        clauses.append(clause)
    if "dDosed" in stats:
        clauses.append(f"{stats['dDosed']:+.1f} people at an illustrative smoke dose of 1")
    note = trapped_note(stats)
    clauses.append(f"{stats['dTrapped']:+.1f} trapped per fire{' ' + note if note else ''}.")
    return (text + ", ".join(clauses)).encode("ascii", "replace").decode("ascii")


def add_whatif(building: dict, base: dict, batch: dict, variants=None, rooms=None,
               workers=None, timeout_s=7200, progress=True) -> dict:
    """Return a copy with comparisons; each variant has its own batch deadline."""
    if rooms is not None and rooms < 0:
        raise ValueError("rooms must be non-negative")
    baseline = batch["runs"]
    if rooms is not None:
        ranked = sorted(batch["rooms"], key=lambda r: -(
            r["riskT90"] if r["riskT90"] is not None else base["maxTime"]))[:rooms]
        selected = {(r["floor"], r["id"]) for r in ranked}
        baseline = [r for r in baseline if _key(r)[:2] in selected]
    # Preserve the batch's ignition order, including when a room subset is used.
    ignitions = [dict(floor=f, room=r) for f, r in dict.fromkeys(_key(r)[:2] for r in baseline)]
    seeds = sorted({r["seed"] for r in baseline})
    if variants is None:
        variants = default_variants(building, base, batch["runs"])
    result = deepcopy(batch)
    result["whatIf"] = []
    for variant in variants:
        scenario = deepcopy(base)
        scenario.update(id=f"{base['id']}-{variant['id']}",
                        doors={**base.get("doors", {}), **variant["doors"]},
                        sprinklers=variant["sprinklers"])
        rerun = run_many(building, scenario, ignitions, seeds, workers, timeout_s, progress)
        stats = compare(base, baseline, rerun["runs"])
        stats.update(smoke_base(baseline, rerun["runs"], stats))
        rows = room_deltas(baseline, rerun["runs"], "trapped", building, variant["doors"])
        if rows:  # where the trapped change comes from: the three rooms that move it most
            stats["dTrappedRooms"] = rows[:3]
        result["whatIf"].append({**deepcopy(variant), **stats, "why": _why(variant["label"], stats)})
    return result
