"""Illustrative one-at-a-time smoke-model sensitivity sweeps."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from fire.batch import run_many
from fire.whatif import compare, _key

VARIANTS = (("speed", 0.5), ("speed", 1.5), ("density", 0.5), ("density", 1.5))
NOTE = ("Illustrative: one-at-a-time -50%/+50% changes to the smoke model's front speed "
        "and density. Not a calibration, a confidence interval or a compliance result.")


def _top3(batch):
    return [item["id"] for item in batch["top"]
            if item["kind"] in ("door", "stair", "exit")][:3]


def _mean(runs, field, fallback=None):
    values = [r.get(field) if r.get(field) is not None else fallback for r in runs]
    return sum(values) / len(values) if values and all(v is not None for v in values) else None


def sensitivity(building: dict, base: dict, ignitions, seeds=(1,), workers=None,
                timeout_s=3600, progress=True) -> dict:
    ignitions = list(ignitions)
    seeds = sorted(set(seeds))
    if not ignitions or not seeds:
        raise ValueError("sensitivity needs at least one ignition and seed")
    reference_base = deepcopy(base)
    reference_base.pop("smokeScale", None)
    reference = run_many(building, reference_base, ignitions, seeds, workers, timeout_s, progress)
    if not reference["runs"]:
        raise ValueError("sensitivity reference has no successful runs")
    top3 = _top3(reference)
    result = {"version": "sensitivity/v0", "buildingId": building["id"], "baseId": base["id"],
              "note": NOTE, "ignitions": deepcopy(ignitions), "seeds": seeds,
              "reference": {"top3": top3, "meanT90": _mean(reference["runs"], "t90", base["maxTime"]),
                            "meanSmokeSeconds": _mean(reference["runs"], "smokeSeconds"),
                            "meanDosed": _mean(reference["runs"], "dosed")}, "variants": []}
    for knob, factor in VARIANTS:
        scenario = deepcopy(reference_base)
        scenario.update(id=f"{base['id']}-{knob}{factor:g}", smokeScale={knob: factor})
        rerun = run_many(building, scenario, ignitions, seeds, workers, timeout_s, progress)
        stats = compare(base, reference["runs"], rerun["runs"])
        matched = {_key(r) for r in rerun["runs"] if r.get("ok", True)}
        mean_smoke = _mean([r for r in reference["runs"] if _key(r) in matched], "smokeSeconds")
        smoke_pct = (100 * stats["dSmokeSeconds"] / mean_smoke
                     if mean_smoke and "dSmokeSeconds" in stats else None)
        top = _top3(rerun)
        overlap = len(set(top3) & set(top))
        same_first = bool(top3 and top and top3[0] == top[0])
        label = (f"Smoke spreads 50% {'slower' if factor < 1 else 'faster'}" if knob == "speed"
                 else f"Smoke 50% {'thinner' if factor < 1 else 'thicker'}")
        text = (f"{label}: the top 3 weak spots keep {overlap} of {len(top3)} places and "
                f"{'the same' if same_first else 'a different'} top spot; ")
        if smoke_pct is not None:
            text += f"{abs(smoke_pct):.0f}% {'more' if smoke_pct >= 0 else 'less'} time in smoke; "
        elif "dSmokeSeconds" in stats:
            text += f"{stats['dSmokeSeconds']:+.0f} person-seconds in smoke; "
        text += (f"90% out {abs(stats['dT90']):.0f} s {'later' if stats['dT90'] >= 0 else 'sooner'}; "
                 f"{stats['dTrapped']:+.1f} trapped per fire ({stats['n']} fires).")
        if not stats["n"]:
            text = f"{label}: no successful matched fires (0 pairs); ranking comparison unavailable."
        result["variants"].append({"id": f"{knob}{factor:g}", "knob": knob, "factor": factor,
                                   "label": label, "top3": top, "topOverlap": overlap,
                                   "sameFirst": same_first, **stats, "smokePct": smoke_pct, "why": text})
    variants = result["variants"]
    result["why"] = ("With smoke 50% slower, faster, thinner or thicker, the top weak spot stays "
                     f"first in {sum(v['sameFirst'] for v in variants)} of {len(variants)} cases "
                     f"and the top 3 keep at least {min(v['topOverlap'] for v in variants)} "
                     f"of {len(top3)} places.")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("building", type=Path)
    parser.add_argument("batch", type=Path)
    parser.add_argument("--rooms", type=int, default=6)
    parser.add_argument("--seeds", default="1")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        seeds = sorted({int(s) for s in args.seeds.split(",")})
        if args.rooms < 1 or (args.workers is not None and args.workers < 1):
            raise ValueError("rooms and workers must be positive")
        building = json.loads(args.building.read_text())
        batch = json.loads(args.batch.read_text())
        if batch["buildingId"] != building["id"]:
            raise ValueError("batch and building ids differ")
        base = batch["base"]
        ranked = sorted(batch["rooms"], key=lambda r: -(
            r["riskT90"] if r["riskT90"] is not None else base["maxTime"]))[:args.rooms]
        result = sensitivity(building, base, [{"floor": r["floor"], "room": r["id"]} for r in ranked],
                             seeds, args.workers)
    except ValueError as error:
        parser.error(str(error))
    out = args.out or Path("data/runs") / f"sensitivity-{building['id']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, allow_nan=False, indent=2) + "\n")
    for variant in result["variants"]:
        print(variant["why"])
    print(result["why"])
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
