"""Occupant profiles (P0). v0 and startDelay are (min, max) ranges drawn uniformly.

P1 adds cane, walker and wheelchair. Unknown profiles fall back to "typical" in sim.run.
"""

PROFILES: dict[str, dict] = {
    "typical": {"v0": (1.0, 1.5), "startDelay": (10.0, 60.0), "radius": 0.2},
    "older": {"v0": (0.7, 1.1), "startDelay": (20.0, 90.0), "radius": 0.2},
    "visitor": {"v0": (1.0, 1.5), "startDelay": (5.0, 40.0), "radius": 0.2},
}
