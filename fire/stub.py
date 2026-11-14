"""No-op fire model with the full FireModel API (spec §7.3).

The sim uses this until fire.model lands. Keep method names and signatures
identical in fire/model.py so the sim only swaps the import.
"""


class NoFire:
    def __init__(self, building: dict, scenario: dict):
        self.building = building
        self.scenario = scenario

    def step(self, t: float) -> None:
        """Advance the fire and smoke to time t (seconds since ignition)."""

    def visibility(self, floor_id: str, x: float, y: float) -> float:
        """Visibility in meters at a point (30 = clear air)."""
        return 30.0

    def untenable(self, floor_id: str, x: float, y: float) -> bool:
        """True if a person at this point can no longer survive or pass."""
        return False

    def blocked_doors(self) -> set[str]:
        """Ids of doors that smoke or fire has made impassable."""
        return set()

    def snapshot(self, floor_id: str) -> dict | None:
        """Smoke grid for one floor, or None for no smoke output.

        Shape: {"origin": [x, y], "cell": float, "cols": int, "rows": int,
                "d": base64 of a row-major Uint8 array, values 0-100}.
        The sim adds "t" and stores it in run["smoke"].
        """
        return None

    def hrr(self, t: float) -> float:
        """Heat release rate in kW at time t."""
        return 0.0

    def burning_rooms(self, t: float) -> set:
        """(floor id, room id) of every room on fire at time t: none. FireModel also lists the ignition room.
        NoFire has no `material` attribute, so a run made with it carries no fire.rooms or fire.material."""
        return set()

    def ignition_times(self) -> list:
        """[{"room", "floor", "ignite"}] for the rooms that ignite by maxTime: none. FireModel lists the ignition
        room first, then every room the fire spreads to."""
        return []
