"""Run metrics v0 (spec 7.4): door queues, waiting time and density heatmaps.

compute(run, building) returns a copy of run["metrics"] plus
  doors:    [{id, floor, peakQueue, waitPersonSeconds, flow: None}]
  heatmaps: [{floor, origin, cell, cols, rows, d}]

Door queue: agents with status 1 (moving) within QUEUE_RADIUS m of the door midpoint on the
same floor, counted in every frame. peakQueue is the largest count and waitPersonSeconds is
the sum of the counts times run["frameInterval"].

Heatmap: agents whose status is in HEAT_STATUSES, counted per HEAT_CELL m cell over all frames,
scaled to 0-100 by the busiest cell of the whole run (so floors stay comparable) and stored as
base64 of a row-major uint8 array (row 0 = miny, origin = (minx, miny) of the floor's walkable
bounds). Agents that have not started moving yet (status 0) are left out, so the map shows
where crowding builds rather than where people stood when the alarm went off. To count every
status, set HEAT_STATUSES = (0, 1, 2, 3).

CLI: python -m fire.metrics RUN BUILDING   (prints the top 5 doors by waiting)
"""
import base64
import json
import math
import sys
from pathlib import Path

import numpy as np

QUEUE_RADIUS = 2.0     # m: how close to a door midpoint counts as queueing there
HEAT_CELL = 0.5        # m
HEAT_STATUSES = (1,)   # frame statuses that count towards the heatmap (1 = moving)


def _floor_bounds(floor: dict):
    """(minx, miny, maxx, maxy) of the outer rings of a floor's walkable area, or None."""
    pts = [p for poly in floor.get("walkable") or [] for p in poly["outer"]]
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _stack(frames: list):
    """All frame rows in one array: (frame number of each row, [idx, x, y, floorIdx, status])."""
    counts, parts = [], []
    for fr in frames:
        a = fr.get("a") or []
        counts.append(len(a))
        if a:
            parts.append(np.asarray(a, dtype=float))
    if not parts:
        return np.zeros(0, dtype=int), np.zeros((0, 5))
    return np.repeat(np.arange(len(frames)), counts), np.vstack(parts)


def compute(run: dict, building: dict) -> dict:
    dt = float(run.get("frameInterval", 0.5))
    frames = run.get("frames") or []
    n_frames = len(frames)
    floor_ids = list(run.get("floors") or [f["id"] for f in building["floors"]])

    fno, a = _stack(frames)
    x, y = a[:, 1], a[:, 2]
    fl, st = a[:, 3].astype(int), a[:, 4].astype(int)

    doors, grids = [], []
    for floor in building["floors"]:
        fi = floor_ids.index(floor["id"]) if floor["id"] in floor_ids else -1

        # Door queues: moving agents within QUEUE_RADIUS of each door midpoint, per frame.
        mov = (fl == fi) & (st == 1)
        mx_, my_, mf = x[mov], y[mov], fno[mov]
        for door in floor.get("doors") or []:
            cx = (door["a"][0] + door["b"][0]) / 2.0
            cy = (door["a"][1] + door["b"][1]) / 2.0
            near = np.hypot(mx_ - cx, my_ - cy) <= QUEUE_RADIUS
            per_frame = np.bincount(mf[near], minlength=n_frames)
            doors.append({
                "id": door["id"],
                "floor": floor["id"],
                "peakQueue": int(per_frame.max()) if n_frames else 0,
                "waitPersonSeconds": round(float(per_frame.sum()) * dt, 3),
                "flow": None,
            })

        # Heatmap counts on the floor's grid.
        b = _floor_bounds(floor)
        if b is None:
            continue
        ox, oy = round(b[0], 3), round(b[1], 3)
        cols = max(1, math.ceil(round((b[2] - ox) / HEAT_CELL, 6)))
        nrows = max(1, math.ceil(round((b[3] - oy) / HEAT_CELL, 6)))
        sel = (fl == fi) & np.isin(st, HEAT_STATUSES)
        c = np.clip(np.floor((x[sel] - ox) / HEAT_CELL).astype(int), 0, cols - 1)
        r = np.clip(np.floor((y[sel] - oy) / HEAT_CELL).astype(int), 0, nrows - 1)
        counts = np.bincount(r * cols + c, minlength=cols * nrows).reshape(nrows, cols)
        grids.append((floor["id"], ox, oy, cols, nrows, counts))

    top = max((int(g[5].max()) for g in grids), default=0)
    heatmaps = []
    for fid, ox, oy, cols, nrows, counts in grids:
        if top > 0:
            d = np.rint(counts * (100.0 / top)).astype(np.uint8)
        else:
            d = np.zeros((nrows, cols), dtype=np.uint8)
        heatmaps.append({
            "floor": fid,
            "origin": [ox, oy],
            "cell": HEAT_CELL,
            "cols": cols,
            "rows": nrows,
            "d": base64.b64encode(d.tobytes()).decode("ascii"),
        })

    out = dict(run.get("metrics") or {})
    out["doors"] = doors
    out["heatmaps"] = heatmaps
    return out


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
    print("  %-8s %-6s %9s %18s" % ("door", "floor", "peakQueue", "waitPersonSeconds"))
    for d in top:
        print("  %-8s %-6s %9d %18.1f" % (d["id"], d["floor"], d["peakQueue"], d["waitPersonSeconds"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
