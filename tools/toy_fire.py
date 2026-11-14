"""Placeholder fire model for the scaffold (spec 7.3 API, same as fire.stub.NoFire).

Gives the sim and the frontend some smoke to work with until the real model (fire/model.py)
lands. Illustrative only, no physics: on the fire floor, smoke density is 80 inside a disk
around the fire point whose radius grows at 0.5 m/s, masked to the walkable area on a 0.5 m
grid. The scenario's fire type, growth and start are ignored; t is seconds since ignition.

    from tools.toy_fire import ToyFire
"""
import base64
import math

import numpy as np
import shapely
from shapely.geometry import Polygon

CELL = 0.5        # m, smoke grid cell
SPREAD = 0.5      # m/s, growth of the smoke disk radius
DENSITY = 80      # smoke density (0-100) inside the disk
CLEAR = 30.0      # m, visibility in clear air
ALPHA = 0.04688   # kW/s^2, fast growth class
Q_PEAK = 1500.0   # kW


class ToyFire:
    def __init__(self, building: dict, scenario: dict):
        self.building = building
        self.scenario = scenario
        fire = scenario["fire"]
        self.floor_id = fire["floor"]
        self.fx, self.fy = float(fire["x"]), float(fire["y"])
        floor = next((f for f in building["floors"] if f["id"] == self.floor_id), None)
        if floor is None:
            raise ValueError("fire floor %r is not in the building" % (self.floor_id,))

        # Grid over the floor's walkable bounds; origin = (minx, miny), row 0 = miny.
        outers = [w["outer"] for w in floor["walkable"]]
        xs = [p[0] for ring in outers for p in ring]
        ys = [p[1] for ring in outers for p in ring]
        self.origin = [round(min(xs), 3), round(min(ys), 3)]
        self.cols = max(1, math.ceil(round((max(xs) - self.origin[0]) / CELL, 6)))
        self.rows = max(1, math.ceil(round((max(ys) - self.origin[1]) / CELL, 6)))

        # Walkable mask at cell centers, and each cell center's distance from the fire.
        gx, gy = np.meshgrid(self.origin[0] + (np.arange(self.cols) + 0.5) * CELL,
                             self.origin[1] + (np.arange(self.rows) + 0.5) * CELL)
        self._mask = np.zeros(gx.shape, dtype=bool)
        for w in floor["walkable"]:
            self._mask |= shapely.contains_xy(Polygon(w["outer"], w.get("holes") or []), gx, gy)
        self._dist = np.hypot(gx - self.fx, gy - self.fy)
        self._d = np.zeros((self.rows, self.cols), dtype=np.uint8)

    def step(self, t: float) -> None:
        radius = SPREAD * max(0.0, float(t))
        self._d = np.where(self._mask & (self._dist <= radius), DENSITY, 0).astype(np.uint8)

    def visibility(self, floor_id: str, x: float, y: float) -> float:
        if floor_id != self.floor_id:
            return CLEAR
        col = int((x - self.origin[0]) // CELL)
        row = int((y - self.origin[1]) // CELL)
        if not (0 <= col < self.cols and 0 <= row < self.rows):
            return CLEAR
        d = float(self._d[row, col])
        return CLEAR if d <= 0 else min(CLEAR, 100.0 / d)

    def untenable(self, floor_id: str, x: float, y: float) -> bool:
        return False

    def blocked_doors(self) -> set[str]:
        return set()

    def snapshot(self, floor_id: str) -> dict | None:
        if floor_id != self.floor_id:
            return None
        return {
            "origin": list(self.origin),
            "cell": CELL,
            "cols": self.cols,
            "rows": self.rows,
            "d": base64.b64encode(self._d.tobytes()).decode("ascii"),
        }

    def hrr(self, t: float) -> float:
        t = max(0.0, float(t))
        return min(ALPHA * t * t, Q_PEAK)
