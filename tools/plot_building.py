"""Preview a building (and optionally a run frame) as one PNG per floor.

    python tools/plot_building.py BUILDING [--run RUN] [--t SECONDS] [--out debug]

Walkable area light grey, room outlines with names, doors blue, stairs orange,
exits green. With --run, agents at the frame nearest --t, colored by status.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import PathPatch, Polygon as MplPolygon  # noqa: E402
from matplotlib.path import Path as MplPath  # noqa: E402

STATUS_STYLE = {
    0: ("#555555", "not moving yet"),
    1: ("#d62728", "moving"),
    2: ("#9467bd", "waiting for help"),
    3: ("#ff7f0e", "in stairwell"),
}


def _ring_path(outer, holes) -> MplPath:
    verts, codes = [], []
    for ring in [outer, *holes]:
        if len(ring) < 3:
            continue
        verts += [tuple(p) for p in ring] + [tuple(ring[0])]
        codes += [MplPath.MOVETO] + [MplPath.LINETO] * (len(ring) - 1) + [MplPath.CLOSEPOLY]
    return MplPath(verts, codes)


def plot_floor(building: dict, floor: dict, out_dir: Path, run: dict | None, t: float | None) -> Path:
    xs, ys = [], []
    for w in floor["walkable"]:
        xs += [p[0] for p in w["outer"]]
        ys += [p[1] for p in w["outer"]]
    for r in floor["rooms"]:
        xs += [p[0] for p in r["polygon"]]
        ys += [p[1] for p in r["polygon"]]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    w_in = 14.0
    h_in = max(4.0, w_in * (maxy - miny + 2) / (maxx - minx + 2))
    fig, ax = plt.subplots(figsize=(w_in, h_in))

    for w in floor["walkable"]:
        ax.add_patch(PathPatch(_ring_path(w["outer"], w["holes"]), facecolor="#e6e6e6",
                               edgecolor="#333333", linewidth=1.2, zorder=1))
    for r in floor["rooms"]:
        ax.add_patch(MplPolygon(r["polygon"], closed=True, fill=False, edgecolor="#999999",
                                linewidth=0.5, linestyle=":", zorder=2))
        cx = sum(p[0] for p in r["polygon"]) / len(r["polygon"])
        cy = sum(p[1] for p in r["polygon"]) / len(r["polygon"])
        ax.text(cx, cy, f"{r['id']}\n{r['name']}", ha="center", va="center", fontsize=7,
                color="#444444", zorder=6)
    for s in floor["stairs"]:
        ax.add_patch(MplPolygon(s["polygon"], closed=True, facecolor="#ff7f0e", alpha=0.25,
                                edgecolor="#ff7f0e", zorder=3))
    for e in floor["exits"]:
        ax.add_patch(MplPolygon(e["polygon"], closed=True, facecolor="#2ca02c", alpha=0.6,
                                edgecolor="#2ca02c", zorder=3))
        ex = sum(p[0] for p in e["polygon"]) / len(e["polygon"])
        ey = sum(p[1] for p in e["polygon"]) / len(e["polygon"])
        ax.text(ex, ey, e["id"], ha="center", va="center", fontsize=8, color="#145214",
                fontweight="bold", zorder=7)
    for d in floor["doors"]:
        ax.add_patch(MplPolygon(d["rect"], closed=True, facecolor="#1f77b4", alpha=0.35,
                                edgecolor="none", zorder=4))
        ax.plot([d["a"][0], d["b"][0]], [d["a"][1], d["b"][1]], color="#1f77b4", linewidth=2.5, zorder=5)

    title = f"{building.get('name', building.get('id'))} | {floor['id']}"
    if run is not None and run.get("frames"):
        frame = min(run["frames"], key=lambda fr: abs(fr["t"] - (t or 0.0)))
        floor_idx = run["floors"].index(floor["id"]) if floor["id"] in run["floors"] else -1
        pts = [a for a in frame["a"] if a[3] == floor_idx]
        for status, (color, label) in STATUS_STYLE.items():
            sel = [a for a in pts if a[4] == status]
            if sel:
                ax.scatter([a[1] for a in sel], [a[2] for a in sel], s=14, c=color,
                           label=f"{label} ({len(sel)})", zorder=8, edgecolors="none")
        title += f" | t = {frame['t']:.1f} s | {len(pts)} agents on floor"
        if pts:
            ax.legend(loc="upper right", fontsize=8, framealpha=0.85)

    ax.set_title(title, fontsize=10)
    ax.set_xlim(minx - 1, maxx + 1)
    ax.set_ylim(miny - 1, maxy + 1)
    ax.set_aspect("equal")
    ax.grid(True, linewidth=0.3, alpha=0.5)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{floor['id']}.png"
    fig.savefig(out, dpi=110, bbox_inches="tight")
    plt.close(fig)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("building")
    ap.add_argument("--run", help="run/v0 JSON to draw agents from")
    ap.add_argument("--t", type=float, default=None, help="time in seconds (nearest frame)")
    ap.add_argument("--out", default="debug", help="output folder (default: debug)")
    args = ap.parse_args(argv)

    building = json.loads(Path(args.building).read_text(encoding="utf-8"))
    run = json.loads(Path(args.run).read_text(encoding="utf-8")) if args.run else None
    for floor in building["floors"]:
        print(f"wrote {plot_floor(building, floor, Path(args.out), run, args.t)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
