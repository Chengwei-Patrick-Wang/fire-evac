"""Headline numbers pack (headlines/v0): the few numbers the demo, the report card and the Report tab quote.

It only reads a saved batch (and D17's sensitivity file when there is one); nothing reruns.
Run from the repo root: python -m fire.headlines BUILDING BATCH [--sensitivity PATH] [--out PATH]
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys

from fire.batch import door_label

NOTE = ("Illustrative fire model and rule-based simulated occupants; "
        "ideas for a fire protection engineer to check, not a compliance result.")
WHATIF_KEYS = ("id", "label", "n", "dT90", "slower", "faster", "dTrapped",
               "dSmokeSeconds", "baseSmokeSeconds", "smokePct", "dDosed", "why")
FIX_KEYS = ("id", "kind", "label", "helps", "n", "dT90", "dTrapped",
            "dSmokeSeconds", "smokePct", "derivedFrom", "why")


def _clean(fields: dict) -> dict:
    """Drop null and non-finite values: a missing field is left out, never null."""
    return {k: v for k, v in fields.items()
            if v is not None and not (isinstance(v, float) and not math.isfinite(v))}


def _pick(source: dict, keys) -> dict:
    return _clean({k: deepcopy(source.get(k)) for k in keys})


def _ascii(value):
    """Every string value as ASCII, as the other `why` texts are."""
    if isinstance(value, str):
        return value.encode("ascii", "replace").decode("ascii")
    if isinstance(value, list):
        return [_ascii(v) for v in value]
    if isinstance(value, dict):
        return {k: _ascii(v) for k, v in value.items()}
    return value


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _scenario(batch: dict) -> dict:
    base = batch.get("base") or {}
    occupants, fire = base.get("occupants") or {}, base.get("fire") or {}
    runs = batch.get("runs", [])
    return _clean({
        "id": base.get("id"), "occupants": occupants.get("total"), "mix": deepcopy(occupants.get("mix")),
        "fireType": fire.get("type"), "growth": fire.get("growth"), "sprinklers": base.get("sprinklers"),
        "alarmTime": base.get("alarmTime"), "maxTime": base.get("maxTime"),
        "doors": deepcopy(base.get("doors")), "exitChoice": base.get("exitChoice"),
        "seeds": sorted({r["seed"] for r in runs}),
        "rooms": len({(r["ignition"]["floor"], r["ignition"]["room"]) for r in runs}),
        "runs": len(runs), "failed": len(batch.get("failed", []))})


def _weak_spots(building: dict, batch: dict) -> list[dict]:
    rooms = {(r["floor"], r["id"]): r for r in batch.get("rooms", [])}
    doors = {(d["floor"], d["id"]): d for d in batch.get("doors", [])}
    names = {(f["id"], r["id"]): r.get("name")
             for f in building.get("floors", []) for r in f.get("rooms", [])}
    spots = []
    for rank, item in enumerate(batch.get("top", []), 1):
        key = (item["floor"], item["id"])
        if item["kind"] == "room":
            name = names.get(key)
            label = f"{name} ({item['id']})" if name and name != item["id"] else item["id"]
            ranges = {"riskT90Range": rooms.get(key, {}).get("riskT90Range")}
        else:
            label = door_label(building, item["floor"], item["id"])[1]
            ranges = {"scoreRange": doors.get(key, {}).get("scoreRange")}
        spots.append(_clean({"rank": rank, "kind": item["kind"], "id": item["id"], "floor": item["floor"],
                             "label": label, "score": item.get("score"), "why": item.get("why"),
                             **deepcopy(ranges), "seedsInTop3": item.get("seedsInTop3")}))
    return spots


def _what_if(batch: dict) -> list[dict]:
    runs = batch.get("runs", [])
    smoke = [r.get("smokeSeconds") for r in runs]
    entries = []
    for item in batch.get("whatIf", []):
        entry = _pick(item, WHATIF_KEYS)
        # Saved before the percent was written at the source: E's rule, only when every run is paired.
        if ("baseSmokeSeconds" not in entry and "smokePct" not in entry and "dSmokeSeconds" in entry
                and runs and item.get("n") == len(runs) and None not in smoke):
            mean = sum(smoke) / len(runs)
            if mean > 0:
                entry["smokePct"] = 100 * entry["dSmokeSeconds"] / mean
                entry = {k: entry[k] for k in WHATIF_KEYS if k in entry}  # the contract's order
        entries.append(entry)
    return entries


def _headline(whatif: list[dict], spots: list[dict]) -> str | None:
    live = [w for w in whatif if w.get("n", 0) > 0]
    chosen = next((w for w in live if w.get("id") == "proppedStairs"), live[0] if live else None)
    if chosen is None:
        return spots[0].get("why") if spots else None
    d_t90 = chosen.get("dT90", 0.0)
    when = f"90% out {abs(d_t90):.0f} s {'later' if d_t90 >= 0 else 'sooner'} on average"
    fires = f"{chosen['n']} paired fire{'' if chosen['n'] == 1 else 's'}"
    label = chosen.get("label", chosen.get("id", "What-if"))
    if "smokePct" in chosen:
        return f"{label}: {round(chosen['smokePct']):+d}% person-seconds in smoke across {fires}; {when}."
    if "dSmokeSeconds" in chosen:
        return (f"{label}: {chosen['dSmokeSeconds']:+,.0f} person-seconds in smoke per fire "
                f"across {fires}; {when}.")
    return f"{label}: {when} across {fires}."


def _sensitivity(sensitivity: dict | None) -> dict:
    if not sensitivity:
        return {}
    section = _pick(sensitivity, ("note", "why"))
    variants = [_pick(v, ("id", "why")) for v in sensitivity.get("variants", [])]
    if variants:
        section["variants"] = variants
    return section


def build_headlines(building: dict, batch: dict, sensitivity: dict | None = None,
                    sources: dict | None = None, generated: str | None = None) -> dict:
    """The headlines/v0 pack. Reads the batch only; sections it lacks are left out, never null."""
    spots = _weak_spots(building, batch)
    whatif = _what_if(batch)
    stability = _pick(batch.get("stability") or {}, ("why", "heldIn", "n"))
    sensitivity_section = _sensitivity(sensitivity)
    pack = {"version": "headlines/v0", "buildingId": building["id"]}
    pack.update(_clean({"buildingName": building.get("name")}))
    pack.update(generated=generated or _iso(datetime.now(timezone.utc)), note=NOTE)
    if sources:
        pack["sources"] = deepcopy(sources)
    pack["scenario"] = _scenario(batch)
    headline = _headline(whatif, spots)
    if headline:
        pack["headline"] = headline
    if spots:
        pack["weakSpots"] = spots
    if whatif:
        pack["whatIf"] = whatif
    fixes = [_pick(f, FIX_KEYS) for f in batch.get("fixes", [])]
    if fixes:
        pack["fixes"] = fixes
    if stability:
        pack["stability"] = stability
    if sensitivity_section:
        pack["sensitivity"] = sensitivity_section
    if batch.get("timing"):
        pack["timing"] = deepcopy(batch["timing"])
    return _ascii(pack)


def all_whys(pack: dict) -> list[str]:
    """Every `why` in the pack, in section order."""
    texts = [s["why"] for s in pack.get("weakSpots", []) if "why" in s]
    texts += [pack["stability"]["why"]] if "why" in pack.get("stability", {}) else []
    texts += [w["why"] for w in pack.get("whatIf", []) if "why" in w]
    texts += [f["why"] for f in pack.get("fixes", []) if "why" in f]
    sensitivity = pack.get("sensitivity", {})
    texts += [sensitivity["why"]] if "why" in sensitivity else []
    texts += [v["why"] for v in sensitivity.get("variants", []) if "why" in v]
    return texts


def _shown(path: Path) -> str:
    """The path as given, with forward slashes. The pack ships with the demo, so an absolute path
    is shown relative to the working directory, or by its file name when it lies elsewhere."""
    if path.is_absolute():
        try:
            path = path.relative_to(Path.cwd())
        except ValueError:
            path = Path(path.name)
    return path.as_posix()


def _modified(path: Path) -> str:
    return _iso(datetime.fromtimestamp(path.stat().st_mtime, timezone.utc))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("building", type=Path)
    parser.add_argument("batch", type=Path)
    parser.add_argument("--sensitivity", type=Path,
                        help="D17's file (default: data/runs/sensitivity-<buildingId>.json when it exists)")
    parser.add_argument("--out", type=Path, help="default: data/runs/headlines-<buildingId>.json")
    args = parser.parse_args(argv)
    if not args.batch.is_file():
        print(f"no batch at {args.batch.as_posix()}: run D15's command (fire/README.md) first", file=sys.stderr)
        return 1
    building = json.loads(args.building.read_text(encoding="utf-8"))
    batch = json.loads(args.batch.read_text(encoding="utf-8"))
    if batch.get("buildingId") != building["id"]:
        print(f"batch {args.batch.as_posix()} is for building {batch.get('buildingId')!r}, "
              f"but {args.building.as_posix()} is building {building['id']!r}", file=sys.stderr)
        return 2
    sources = {"batch": _clean({"file": _shown(args.batch), "id": batch.get("id"),
                                "modified": _modified(args.batch)})}
    sensitivity, path = None, args.sensitivity or Path("data/runs") / f"sensitivity-{building['id']}.json"
    if args.sensitivity is not None and not path.is_file():
        print(f"no sensitivity file at {path.as_posix()}", file=sys.stderr)
        return 1
    if path.is_file():
        sensitivity = json.loads(path.read_text(encoding="utf-8"))
        sources["sensitivity"] = {"file": _shown(path), "modified": _modified(path)}
    pack = build_headlines(building, batch, sensitivity, sources)
    out = args.out or Path("data/runs") / f"headlines-{building['id']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(pack, indent=1, allow_nan=False).encode("utf-8")
    out.write_bytes(data)  # bytes, so Windows keeps LF and the size below is the file's
    if "headline" in pack:
        print(pack["headline"], flush=True)
    for why in all_whys(pack):
        print(why, flush=True)
    print(f"wrote {out.as_posix()} ({len(data)} bytes)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
