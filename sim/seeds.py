"""Rule-based evacuation ranges: one scenario, several possible nights."""
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
from statistics import median
import time

from sim.run import run


KEYS = ("t50", "t90", "t100", "evacuated", "trapped")


def _row(result, wall_s=0.0):
    return {"seed": result["seed"], "agents": result["metrics"]["agents"],
            **{key: result["metrics"][key] for key in KEYS}, "wallS": wall_s}


def _one(task):
    building, scenario = task
    started = time.perf_counter()
    result = run(building, scenario)
    return _row(result, time.perf_counter() - started)


def run_seeds(building, scenario, seeds, workers=1):
    """Return only metrics from workers, sorted by seed (including repeats)."""
    if not isinstance(workers, int) or workers < 1:
        raise ValueError("workers must be a positive integer")
    tasks = [(building, dict(scenario, seed=seed, brain="rules")) for seed in seeds]
    if workers == 1:
        rows = [_one(task) for task in tasks]
    elif tasks:
        with ProcessPoolExecutor(max_workers=workers,
                                 mp_context=multiprocessing.get_context("spawn")) as pool:
            rows = list(pool.map(_one, tasks))
    else:
        rows = []
    return sorted(rows, key=lambda row: row["seed"])


def summarize(rows):
    """Summarize attained values; missing evacuation times remain explicit."""
    result = {"seeds": sorted(row["seed"] for row in rows)}
    for key in KEYS:
        values = [row[key] for row in rows if row[key] is not None]
        stats = dict(zip(("min", "median", "max"),
                         (min(values), median(values), max(values)) if values else (None,) * 3))
        if key.startswith("t") and key != "trapped":
            stats = {name: round(value, 2) if value is not None else None
                     for name, value in stats.items()}
        result[key] = {**stats, "missing": len(rows) - len(values)}
    return result


def seed_range(building, scenario, n=10, workers=1, base=None):
    """Reuse a finished rule run for the first seed when supplied.

    Callers must supply a base from this same building and scenario. LLM-mode
    scenarios are rerun with rules, so their base cannot enter a seed range.
    """
    if not isinstance(n, int) or n < 1:
        raise ValueError("n must be a positive integer")
    first = int(scenario.get("seed", 0))
    seeds = list(range(first, first + n))
    rows = []
    if base is not None and scenario.get("brain", "rules") == "rules":
        if base["seed"] != first or base.get("buildingId") != building.get("id"):
            raise ValueError("base must match the scenario seed and building")
        rows.append(_row(base))
        seeds.pop(0)
    return summarize(rows + run_seeds(building, scenario, seeds, workers))
