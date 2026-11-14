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


def _why(label, stats):
    if not stats["n"]:
        return f"{label}: no successful matched fires (0 pairs).".encode("ascii", "replace").decode("ascii")
    text = (f"{label}: 90% out {abs(stats['dT90']):.0f} s "
            f"{'later' if stats['dT90'] >= 0 else 'sooner'} on average "
            f"(slower in {stats['slower']} of {stats['n']} fires); ")
    clauses = []
    if "dSmokeSeconds" in stats:
        clauses.append(f"{stats['dSmokeSeconds']:+,.0f} person-seconds in smoke")
    if "dDosed" in stats:
        clauses.append(f"{stats['dDosed']:+.1f} people at an illustrative smoke dose of 1")
    clauses.append(f"{stats['dTrapped']:+.1f} trapped per fire.")
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
        result["whatIf"].append({**deepcopy(variant), **stats, "why": _why(variant["label"], stats)})
    return result
