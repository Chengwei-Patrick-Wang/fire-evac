"""Measured, paired building improvements; illustrative ideas, not designs."""
from contextlib import redirect_stderr
from copy import deepcopy
import io
import math

from buildings.normalize import plan_to_building
from fire.batch import door_label, run_many
from fire.presets import sprinklers_matter
from fire.whatif import _key, compare, stair_doors


def renormalize(building: dict) -> dict:
    plan = deepcopy(building)
    plan["version"] = "plan/v0"
    for floor in plan["floors"]:
        for key in ("walkable", "stairs", "exits"):
            floor.pop(key, None)
        for door in floor["doors"]:
            door.pop("connects", None)
    with redirect_stderr(io.StringIO()):
        return plan_to_building(plan)


def widen_door(building: dict, door_id: str, extra=0.5) -> dict:
    if not math.isfinite(extra) or extra <= 0:
        raise ValueError("extra width must be positive and finite")
    result = deepcopy(building)
    found = next(((f, d) for f in result["floors"] for d in f["doors"] if d["id"] == door_id), None)
    if found is None:
        raise ValueError(f"unknown door {door_id}")
    floor, door = found
    connects, pieces = set(door["connects"]), len(floor["walkable"])
    dx, dy = (door["b"][i] - door["a"][i] for i in (0, 1))
    length = math.hypot(dx, dy)
    if length == 0:
        raise ValueError(f"door {door_id} has no opening")
    u = (dx / length, dy / length)
    door["a"] = [v - extra / 2 * u[i] for i, v in enumerate(door["a"])]
    door["b"] = [v + extra / 2 * u[i] for i, v in enumerate(door["b"])]
    door["width"] = round(door["width"] + extra, 3)
    if door.get("rect"):
        center = [sum(p[i] for p in door["rect"]) / len(door["rect"]) for i in (0, 1)]
        door["rect"] = [[v + (1 if sum((p[j] - center[j]) * u[j] for j in (0, 1)) >= 0 else -1)
                         * extra / 2 * u[i] for i, v in enumerate(p)] for p in door["rect"]]
    result = renormalize(result)
    rebuilt = next(f for f in result["floors"] if f["id"] == floor["id"])
    opening = next((d for d in rebuilt["doors"] if d["id"] == door_id), None)
    if opening is None or set(opening["connects"]) != connects or len(rebuilt["walkable"]) != pieces:
        raise ValueError(f"widening {door_id} changes room connections or walkable pieces")
    return result


def _inverse(variant):
    stats = {key: deepcopy(variant[key]) for key in
             ("n", "dT90", "dT90Min", "dT90Max", "slower", "faster", "dTrapped", "dDosed", "dSmokeSeconds")
             if key in variant}
    for key in list(stats):
        if key.startswith("d"):
            stats[key] = -stats[key]
    stats["dT90Min"], stats["dT90Max"] = stats["dT90Max"], stats["dT90Min"]
    stats["slower"], stats["faster"] = stats["faster"], stats["slower"]
    return stats


def candidate_fixes(building: dict, base: dict, batch: dict, top=2) -> tuple[list, list]:
    fixes, skipped = [], []
    doors = {d["id"]: (f, d) for f in building["floors"] for d in f["doors"]}
    ranked = [d for d in batch.get("top", []) if d["kind"] in ("door", "stair", "exit")][:top]
    for item in ranked:
        did = item["id"]
        try:
            widen_door(building, did)
            floor, door = doors[did]
            label = door_label(building, floor["id"], did)[1]
            fixes.append(dict(id=f"widen-{did}", kind="widen", door=did, floor=floor["id"],
                              width=round(door["width"] + 0.5, 3),
                              label=f"Widen {label} from {door['width']:.2f} m to {door['width'] + .5:.2f} m"))
        except ValueError as error:
            skipped.append(dict(id=f"widen-{did}", reason=str(error)))
    if sprinklers_matter(base):
        fixes.append(dict(id="sprinklers", kind="sprinklers", label="Sprinklers", sprinklers=True))
    else:
        skipped.append(dict(id="sprinklers", reason="Sprinklers already on or preset peak does not exceed the sprinkler cap."))
    overrides = base.get("doors", {})
    open_stairs = [did for did in stair_doors(building)
                   if overrides.get(did, doors[did][1]["state"]) in ("open", "propped")]
    variants = {v["id"]: v for v in batch.get("whatIf", [])}
    if open_stairs:
        fixes.append(dict(id="selfClosers", kind="selfClosers", label="Self-closers on stair doors",
                          doors=dict.fromkeys(open_stairs, "closed")))
    elif "proppedStairs" in variants:
        fixes.append(dict(id="selfClosers", kind="selfClosers", label="Self-closers on stair doors (vs propped open)",
                          derivedFrom="whatIf.proppedStairs", **_inverse(variants["proppedStairs"])))
    else:
        skipped.append(dict(id="selfClosers", reason="No open stair doors or propped-stair comparison."))
    for did, state in overrides.items():
        if state == "blocked":
            if did not in doors:
                skipped.append(dict(id=f"keepClear-{did}", reason="Unknown blocked door."))
                continue
            floor, door = doors[did]
            fixes.append(dict(id=f"keepClear-{did}", kind="keepClear", door=did, floor=floor["id"],
                              label=f"Keep {door_label(building, floor['id'], did)[1]} clear", doors={did: door["state"]}))
    blocked = variants.get("blockedExit")
    if blocked:
        for did, state in blocked.get("doors", {}).items():
            if state != "blocked" or overrides.get(did) == "blocked" or did not in doors:
                continue
            floor, _ = doors[did]
            fixes.append(dict(id=f"keepClear-{did}", kind="keepClear", door=did, floor=floor["id"],
                              label=f"Keep {door_label(building, floor['id'], did)[1]} clear (vs blocked)",
                              derivedFrom="whatIf.blockedExit", **_inverse(blocked)))
    return fixes, skipped


def _why(fix):
    if not fix["n"]:
        text = f"{fix['label']}: no successful matched fires (0 pairs)."
    else:
        text = (f"{fix['label']}: 90% out {abs(fix['dT90']):.0f} s "
                f"{'sooner' if fix['dT90'] < 0 else 'later'} on average")
        if "dSmokeSeconds" in fix:
            if fix["smokePct"] is not None:
                text += f" and {abs(fix['smokePct']):.0f}% {'less' if fix['dSmokeSeconds'] < 0 else 'more'} time in smoke"
            else:
                text += (f" and {abs(fix['dSmokeSeconds']):.0f} "
                         f"{'fewer' if fix['dSmokeSeconds'] < 0 else 'more'} person-seconds in smoke")
        text += f" across {fix['n']} fires (faster in {fix['faster']}); {fix['dTrapped']:+.1f} trapped per fire."
    return text.encode("ascii", "replace").decode("ascii")


def add_fixes(building: dict, base: dict, batch: dict, rooms=None, top=2,
              workers=None, timeout_s=7200, progress=True) -> dict:
    if rooms is not None and rooms < 0:
        raise ValueError("rooms must be non-negative")
    baseline = batch["runs"]
    if rooms is not None:
        ranked = sorted(batch["rooms"], key=lambda r: -(r["riskT90"] if r["riskT90"] is not None else base["maxTime"]))[:rooms]
        selected = {(r["floor"], r["id"]) for r in ranked}
        baseline = [r for r in baseline if _key(r)[:2] in selected]
    ignitions = [dict(floor=f, room=r) for f, r in dict.fromkeys(_key(r)[:2] for r in baseline)]
    seeds = sorted({r["seed"] for r in baseline})
    result = deepcopy(batch)
    fixes, result["fixesSkipped"] = candidate_fixes(building, base, batch, top)
    for fix in fixes:
        fix["smokePct"] = None
        if "derivedFrom" not in fix:
            scenario = deepcopy(base)
            scenario["id"] = f"{base['id']}-{fix['id']}"
            scenario["doors"] = {**base.get("doors", {}), **fix.get("doors", {})}
            if "sprinklers" in fix:
                scenario["sprinklers"] = fix["sprinklers"]
            changed = widen_door(building, fix["door"]) if fix["kind"] == "widen" else building
            rerun = run_many(changed, scenario, ignitions, seeds, workers, timeout_s, progress)
            fix.update(compare(base, baseline, rerun["runs"]))
            good = {_key(r) for r in rerun["runs"] if r.get("ok", True)}
            matched = [r for r in baseline if r.get("ok", True) and _key(r) in good]
            if matched and "dSmokeSeconds" in fix and all("smokeSeconds" in r for r in matched):
                mean = sum(r["smokeSeconds"] for r in matched) / len(matched)
                if mean > 0:
                    fix["smokePct"] = 100 * fix["dSmokeSeconds"] / mean
        smoke_helps = (fix.get("dSmokeSeconds", 0) < 0 if "derivedFrom" in fix
                       else fix["smokePct"] is not None and fix["smokePct"] <= -5)
        fix["helps"] = bool(fix["n"] and (fix["dT90"] <= -1 or fix["dTrapped"] < 0 or smoke_helps))
        fix["why"] = _why(fix)
    result["fixes"] = sorted(fixes, key=lambda f: (not f["helps"], f["dT90"], f.get("dSmokeSeconds", 0)))
    return result
