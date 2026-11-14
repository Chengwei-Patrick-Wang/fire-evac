"""Illustrative heat-release presets; power is in kW and time in seconds."""

GROWTH_ALPHA = {
    "slow": 0.00293, "medium": 0.01172, "fast": 0.04688,
    "ultra-fast": 0.1876, "instant": None,
}
PRESETS = {
    "kitchen": {"growth": "fast", "peakKw": 1500.0, "smokeFactor": 1.0},
    "bedroom": {"growth": "medium", "peakKw": 3000.0, "smokeFactor": 1.0},
    "battery": {"growth": "ultra-fast", "peakKw": 1000.0, "smokeFactor": 2.0},
    "trash": {"growth": "fast", "peakKw": 500.0, "smokeFactor": 1.0},
    "liquid": {"growth": "instant", "peakKw": 1500.0, "smokeFactor": 1.0},
}
SPRINKLER_CAP_KW = 500.0


def _name(value: str) -> str:
    return value.lower().replace("_", "-").replace(" ", "-")


def fire_params(fire: dict, sprinklers: bool = False) -> dict:
    kind = _name(fire["type"])
    if kind not in PRESETS:
        raise ValueError(f"Unknown fire type {kind!r}; valid names: {', '.join(PRESETS)}")
    preset = PRESETS[kind]
    growth = _name(fire.get("growth", preset["growth"]))
    if growth not in GROWTH_ALPHA:
        raise ValueError(f"Unknown growth {growth!r}; valid names: {', '.join(GROWTH_ALPHA)}")
    peak = preset["peakKw"]
    return {"alpha": GROWTH_ALPHA[growth],
            "peakKw": min(peak, SPRINKLER_CAP_KW) if sprinklers else peak,
            "smokeFactor": preset["smokeFactor"]}


def hrr_kw(params: dict, tau: float) -> float:
    if tau < 0:
        return 0.0
    alpha = params["alpha"]
    return float(params["peakKw"] if alpha is None else min(alpha * tau ** 2, params["peakKw"]))
