"""Uniform walking speeds and start delays; stair speeds in m/s.

Mobility ranges follow docs/context/03-research-findings.md. Assistance delay
is a scenario assumption, not a property of the wheelchair profile.
"""

PROFILES: dict[str, dict] = {
    "typical": {"v0": (1.0, 1.5), "startDelay": (10.0, 60.0), "radius": 0.2,
                "stairs": True, "stairSpeed": 0.55},
    "older": {"v0": (0.7, 1.1), "startDelay": (20.0, 90.0), "radius": 0.2,
              "stairs": True, "stairSpeed": 0.45},
    "visitor": {"v0": (1.0, 1.5), "startDelay": (5.0, 40.0), "radius": 0.2,
                "stairs": True, "stairSpeed": 0.55},
    "cane": {"v0": (0.7, 0.95), "startDelay": (20.0, 90.0), "radius": 0.2,
             "stairs": True, "stairSpeed": 0.45},
    "walker": {"v0": (0.6, 0.85), "startDelay": (20.0, 90.0), "radius": 0.2,
               "stairs": True, "stairSpeed": 0.4},
    "wheelchair": {"v0": (0.9, 1.1), "startDelay": (20.0, 90.0), "radius": 0.3,
                   "stairs": False, "stairSpeed": 0.2},
}
