"""Uniform walking speeds and start delays; stair speeds in m/s.

Mobility ranges follow docs/context/03-research-findings.md. Assistance delay
is a scenario assumption, not a property of the wheelchair profile.
"""

CUE_VIS_M = 10.0
CUE_DELAY = (0.0, 10.0)

# Social following (C28). Someone still waiting for the alarm who can see people walking to a way out starts early,
# and someone choosing a way out leans a little toward the one most of those people are heading to.
SOCIAL_RADIUS_M = 8.0         # how far a person registers others leaving
SOCIAL_MIN_MOVERS = 2         # people in view, moving to an exit or stair, that make a social cue (and a herd bonus)
SOCIAL_NEAREST = 12           # a person checks the line of sight to the nearest this many movers within range, no more
SOCIAL_DELAY = (2.0, 5.0)     # s of reaction, drawn per person from the seed, between seeing others leave and starting
HERD_S_PER_PERSON = 1.0       # exit-choice bonus per person in view heading to the same way out ...
HERD_MAX_S = 3.0              # ... at most this many seconds off its cost (illustrative, like the other weights)

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
