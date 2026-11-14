"""Speed-based door queues, crossing flow and smoke-grid density heatmaps.

CLI: python -m fire.metrics RUN BUILDING (top five doors by waiting).
"""
import base64
import json
import math
import sys
from pathlib import Path

import numpy as np
import shapely

from fire.grid import grid_specs
from fire.model import FireModel, UNTENABLE_D, UNTENABLE_HOLD_S

DOSE_UNIT = UNTENABLE_D * UNTENABLE_HOLD_S
SMOKE_D = 10.0

QUEUE_RADIUS_M = 2.0
QUEUE_SPEED_MS = 0.3
DOOR_BOX_M = 3.0
CROSS_SIDE_M = 1.0
CROSS_MARGIN_M = 0.3
FLOW_MIN_SPAN_S = 30.0


def _stack(frames: list):
    """Rows, frame indexes, speeds, and indexes of the preceding frame's rows.

    Speed uses time since last appearance. Crossings require consecutive frames;
    a first appearance or floor transfer has unknown (infinite) speed.
    """
    rows, frame_numbers, speeds, previous_rows = [], [], [], []
    last = {}
    for k, frame in enumerate(frames):
        t = float(frame["t"])
        for row in frame.get("a") or []:
            idx, x, y, floor, _ = row
            speed, prior = float("inf"), -1
            if idx in last:
                old_k, old_t, old_row, old_index = last[idx]
                if old_row[3] == floor:
                    if t > old_t:
                        speed = np.hypot(x - old_row[1], y - old_row[2]) / (t - old_t)
                    if old_k == k - 1 and t > old_t:
                        prior = old_index
            last[idx] = (k, t, row, len(rows))
            rows.append(row)
            frame_numbers.append(k)
            speeds.append(speed)
            previous_rows.append(prior)
    return (np.asarray(rows, dtype=float).reshape(-1, 5),
            np.asarray(frame_numbers, dtype=int), np.asarray(speeds),
            np.asarray(previous_rows, dtype=int))


def _row_density(run: dict, building: dict, scenario: dict, rows: np.ndarray,
                 frame_numbers: np.ndarray) -> np.ndarray:
    """Sample density for each replay row; invalid positions/statuses have zero density."""
    model = FireModel(building, scenario)
    frames = run.get("frames") or []
    floor_ids = list(run.get("floors") or [f["id"] for f in building["floors"]])
    nodes = np.full(len(rows), -1, dtype=int)
    for fi, floor_id in enumerate(floor_ids):
        index = model.graph.floor_index.get(floor_id)
        if index is None:
            continue
        grid = model.graph.floors[index]
        selected = np.flatnonzero((rows[:, 3] == fi) & np.isfinite(rows[:, 1:3]).all(axis=1)
                                  & (rows[:, 4] >= 0) & (rows[:, 4] <= 3))
        cells = np.floor((rows[selected, 1:3] - grid.spec["origin"]) / grid.spec["cell"])
        inside = ((cells[:, 0] >= 0) & (cells[:, 0] < grid.spec["cols"]) &
                  (cells[:, 1] >= 0) & (cells[:, 1] < grid.spec["rows"]))
        selected, cells = selected[inside], cells[inside].astype(int)
        local = grid.snap[cells[:, 1], cells[:, 0]]
        valid = local >= 0
        nodes[selected[valid]] = model.graph.offset[index] + local[valid]

    times = [float(frame["t"]) for frame in frames]
    if any(not math.isfinite(t) or t < 0 for t in times) or times != sorted(times):
        raise ValueError("Exposure frame times must be finite, non-negative and ordered")
    density = np.zeros(len(rows))
    boundaries = np.searchsorted(frame_numbers, np.arange(len(frames) + 1))
    for k, t in enumerate(times):
        model.step(t)
        selected = np.arange(boundaries[k], boundaries[k + 1])
        selected = selected[nodes[selected] >= 0]
        density[selected] = model._density[nodes[selected]]
    return density


def exposure(run: dict, building: dict, scenario: dict) -> dict:
    """Integrate illustrative smoke density at replay positions, without removing people."""
    rows, frame_numbers, _, _ = _stack(run.get("frames") or [])
    density = _row_density(run, building, scenario, rows, frame_numbers)
    model = FireModel(building, scenario)
    stairs, stair_nodes = [], []
    for floor, grid, offset in zip(building["floors"], model.graph.floors, model.graph.offset):
        for stair in floor.get("stairs", []):
            inside = shapely.contains_xy(shapely.Polygon(stair["polygon"]), grid.xy[:, 0], grid.xy[:, 1])
            stairs.append({"floor": floor["id"], "group": stair["group"], "smokeAt": None})
            stair_nodes.append(offset + np.flatnonzero(inside))
    horizon = float(scenario["maxTime"])
    if not math.isfinite(horizon) or horizon < 0:
        raise ValueError("Exposure horizon must be finite and non-negative")
    for t in range(math.floor(horizon) + 1):
        model.step(t)
        for stair, indexes in zip(stairs, stair_nodes):
            if stair["smokeAt"] is None and (model._density[indexes] >= SMOKE_D).any():
                stair["smokeAt"] = float(t)

    dt = float(run.get("frameInterval", 0.5))
    indexes, inverse = np.unique(rows[:, 0].astype(int), return_inverse=True)
    doses = np.bincount(inverse, weights=density * dt / DOSE_UNIT, minlength=len(indexes))
    smoky = np.bincount(inverse, weights=(density >= SMOKE_D).astype(float), minlength=len(indexes))
    dosed = indexes[doses >= 1].tolist()
    count = len(run.get("agents") or [])
    return {"doseUnit": DOSE_UNIT, "smokeD": SMOKE_D,
            "personSecondsInSmoke": float(np.count_nonzero(density >= SMOKE_D) * dt),
            "agentsInSmoke": int(np.count_nonzero(smoky)),
            "meanDose": float(doses.sum() / count) if count else 0.0,
            "maxDose": float(doses.max()) if len(doses) else 0.0,
            "dosed": len(dosed), "dosedIdx": dosed, "stairs": stairs}


def compute(run: dict, building: dict, scenario: dict | None = None) -> dict:
    """Copy sim metrics and add every door's queues/flow and per-floor heatmaps.

    With a scenario, add smoke-only room ASET, clearance margins and exposure.
    """
    dt = float(run.get("frameInterval", 0.5))
    frames = run.get("frames") or []
    floor_ids = list(run.get("floors") or [f["id"] for f in building["floors"]])
    a, fno, speed, previous = _stack(frames)
    density = _row_density(run, building, scenario, a, fno) if scenario is not None else None
    xy = a[:, 1:3]
    fl, st = a[:, 3].astype(int), a[:, 4].astype(int)
    times = np.asarray([frame["t"] for frame in frames], dtype=float)
    doors, heatmaps = [], []
    for floor, spec in zip(building["floors"], grid_specs(building)):
        fi = floor_ids.index(floor["id"]) if floor["id"] in floor_ids else -1
        on_floor = np.flatnonzero(fl == fi) if fi >= 0 else np.array([], dtype=int)
        floor_xy = xy[on_floor]
        for door in floor.get("doors") or []:
            start, end = np.asarray(door["a"]), np.asarray(door["b"])
            # Only evaluate geometry for agents in the opening's +/-3 m box.
            near_box = np.all((floor_xy >= np.minimum(start, end) - DOOR_BOX_M) &
                              (floor_xy <= np.maximum(start, end) + DOOR_BOX_M), axis=1)
            candidates = on_floor[near_box]
            delta = end - start
            length = float(np.linalg.norm(delta))
            relative = xy[candidates] - start
            if length:
                along = relative @ (delta / length)
                closest = start + np.clip(along, 0, length)[:, None] * delta / length
            else:
                closest = start
            distance = np.linalg.norm(xy[candidates] - closest, axis=1)
            queued = candidates[(st[candidates] == 1) & (speed[candidates] < QUEUE_SPEED_MS) &
                                (distance <= QUEUE_RADIUS_M)]
            counts = np.bincount(fno[queued], minlength=len(frames))

            crossing_rows = np.array([], dtype=int)
            if length:
                current = candidates[previous[candidates] >= 0]
                old_xy = xy[previous[current]] - start
                new_xy = xy[current] - start
                tangent = delta / length
                normal = np.array([-tangent[1], tangent[0]])
                old_side, new_side = old_xy @ normal, new_xy @ normal
                old_along, new_along = old_xy @ tangent, new_xy @ tangent
                crossing_rows = current[(old_side * new_side < 0) &
                    (np.abs(old_side) <= CROSS_SIDE_M) & (np.abs(new_side) <= CROSS_SIDE_M) &
                    (old_along >= -CROSS_MARGIN_M) & (old_along <= length + CROSS_MARGIN_M) &
                    (new_along >= -CROSS_MARGIN_M) & (new_along <= length + CROSS_MARGIN_M)]
            crossed = len(np.unique(a[crossing_rows, 0]))
            flow = 0.0
            if crossed:
                crossing_times = times[fno[crossing_rows]]
                span = max(FLOW_MIN_SPAN_S, float(np.ptp(crossing_times)))
                flow = crossed * 60.0 / span
            doors.append({"id": door["id"], "floor": floor["id"],
                          "peakQueue": int(counts.max()) if len(counts) else 0,
                          "waitPersonSeconds": round(float(counts.sum()) * dt, 3),
                          "flow": float(flow), "crossed": crossed})
            if density is not None:
                doors[-1]["smokeWait"] = round(float(np.count_nonzero(density[queued] >= SMOKE_D)) * dt, 3)

        moving = on_floor[st[on_floor] == 1]
        cells = np.floor((xy[moving] - spec["origin"]) / spec["cell"]).astype(int)
        cols, rows = spec["cols"], spec["rows"]
        inside = ((cells[:, 0] >= 0) & (cells[:, 0] < cols) &
                  (cells[:, 1] >= 0) & (cells[:, 1] < rows))
        cells = cells[inside]
        counts = np.bincount(cells[:, 1] * cols + cells[:, 0], minlength=cols * rows)
        peak = int(counts.max()) if len(counts) else 0
        d = np.rint(counts * (100.0 / peak)).astype(np.uint8) if peak else np.zeros(cols * rows, dtype=np.uint8)
        heatmaps.append({"floor": floor["id"], **spec,
                         "d": base64.b64encode(d.tobytes()).decode("ascii")})
    result = {**(run.get("metrics") or {}), "doors": doors, "heatmaps": heatmaps}
    if scenario is not None:
        from fire.model import aset_by_room

        aset = aset_by_room(building, scenario, float(scenario["maxTime"]))
        exits, stairs = {}, {}
        for event in run.get("events", []):
            if event.get("idx") is not None and event.get("type") in ("exit", "stair"):
                times_by_agent = exits if event["type"] == "exit" else stairs
                idx = event["idx"]
                times_by_agent[idx] = max(times_by_agent.get(idx, 0.0), float(event["t"]))
        occupants = {}
        for agent in run.get("agents", []):
            occupants.setdefault(agent["room"], []).append(agent["idx"])
        rooms = []
        for room, indexes in occupants.items():
            clearance = [exits.get(idx, stairs.get(idx)) for idx in indexes]
            rset = max(clearance) if all(t is not None for t in clearance) else None
            available = aset.get(room)
            margin = available - rset if available is not None and rset is not None else None
            rooms.append({"id": room, "rset": rset, "aset": available, "margin": margin})
        result["rooms"] = rooms
        result["exposure"] = exposure(run, building, scenario)
    return result


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print("usage: python -m fire.metrics RUN BUILDING")
        return 2
    run = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    building = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    m = compute(run, building)
    print("agents={agents} evacuated={evacuated} trapped={trapped} t50={t50} t90={t90} t100={t100}".format(
        **{k: m.get(k) for k in ("agents", "evacuated", "trapped", "t50", "t90", "t100")}))
    top = sorted(m["doors"], key=lambda d: (-d["waitPersonSeconds"], -d["peakQueue"], d["id"]))[:5]
    print("Top 5 doors by waiting:")
    print("  %-8s %-6s %9s %18s %10s" % ("door", "floor", "peakQueue", "waitPersonSeconds", "flow/min"))
    for d in top:
        print("  %-8s %-6s %9d %18.1f %10.2f" %
              (d["id"], d["floor"], d["peakQueue"], d["waitPersonSeconds"], d["flow"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
