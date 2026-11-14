"""Seeded queue-aware choices; observations are also the optional LLM boundary."""
from functools import lru_cache
import math

import jupedsim as jps
import numpy as np

SMOKE_BETA = 4.0
UNFAMILIAR_GAMMA = 30.0
TAU = 5.0
MIN_DWELL = 15
COMMIT_DIST = 3.0
TABU = 30
MAX_SWITCHES = 3
ROUTING_MODE = "RoutingEngine" if (hasattr(jps, "RoutingEngine") and
    hasattr(jps.RoutingEngine, "compute_waypoints")) else "straight line"


@lru_cache(maxsize=16)
def _router(floor_poly):
    return jps.RoutingEngine(floor_poly)


def route_points(floor_poly, p, q):
    """Walkable waypoints, with a straight-line fallback on routing failure."""
    if ROUTING_MODE == "RoutingEngine":
        try:
            points = _router(floor_poly).compute_waypoints(p, q)
            if len(points) >= 2:
                return points
        except Exception:
            pass
    return [p, q]


def route_length(floor_poly, p, q):
    points = route_points(floor_poly, p, q)
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def visible_smoke(points, sight, vis):
    """Score only the first visible, nonzero route leg in meter samples."""
    from sim.profiles import CUE_VIS_M
    for a, b in zip(points, points[1:]):
        length = math.dist(a, b)
        if length == 0:
            continue
        samples = np.arange(0.5, min(length, sight), 1.0)
        if not len(samples):
            return 0.0
        xy = np.asarray(a) + samples[:, None] * (np.asarray(b) - a) / length
        return float(np.clip((CUE_VIS_M - vis(xy[:, 0], xy[:, 1])) /
                             (CUE_VIS_M - 1), 0, 1).sum())
    return 0.0


def option_cost(o, speed, beta=SMOKE_BETA, gamma=UNFAMILIAR_GAMMA):
    return (o.get("dist", 0) / max(speed, 0.2) +
            o.get("queue", 0) / o.get("flow", 1) + o.get("tail", 0) +
            beta * o.get("smoke", 0) + gamma * o.get("unfamiliar", False))


def main_entrance(building, scenario):
    exits = [e for f in building["floors"] for e in f["exits"]]
    if "entrance" in scenario:
        if scenario["entrance"] not in {e["id"] for e in exits}:
            raise ValueError("entrance must be an exit id")
        return scenario["entrance"]
    if not building["floors"]:
        return None
    floor = min(building["floors"], key=lambda f: (f["level"], f["id"]))
    doors = {d["id"]: d for d in floor["doors"]}
    lobbies = {r["id"] for r in floor["rooms"] if r["type"] == "lobby"}
    preferred = [e for e in floor["exits"]
                 if lobbies.intersection(doors[e["door"]]["connects"])]
    choices = preferred or floor["exits"]
    return min(choices, key=lambda e: (-doors[e["door"]]["width"], e["id"]))["id"] if choices else None


def mobility_options(options, stairs=True):
    """Prefer same-floor exits for people who require stair assistance."""
    if stairs:
        return options
    exits = [o for o in options if o["kind"] == "exit"]
    return exits or [dict(o, assist=True) for o in options]


def should_switch(c_current, c_new):
    return c_new < 0.8 * c_current


class RuleBrain:
    def __init__(self, seed, beta=SMOKE_BETA, gamma=UNFAMILIAR_GAMMA):
        self.beta, self.gamma = beta, gamma
        self.rng = np.random.default_rng([seed, 1])
        self.last_choice = {}
        self.left = {}
        self.switches = {}

    def decide(self, obs):
        options = obs["options"]
        if not options:
            return None
        costs = np.array([option_cost(o, obs["speed"], self.beta, self.gamma) for o in options])
        finite = np.isfinite(costs)
        if not finite.any():
            return None
        weights = np.exp(-(costs - costs[finite].min()) / TAU)
        candidate = int(self.rng.choice(len(options), p=weights / weights.sum()))
        chosen = options[candidate]
        idx, t, current = obs["idx"], obs["t"], obs["current"]
        old = next((k for k, o in enumerate(options) if o["id"] == current), None)
        # Arrival is a fresh choice on another floor, not a voluntary reroute.
        if old is not None:
            if (chosen["id"] == current or not should_switch(costs[old], costs[candidate])
                or (obs["trigger"] != "smoke" and
                    t - self.last_choice.get(idx, -math.inf) < MIN_DWELL)
                or options[old]["dist"] <= COMMIT_DIST
                or t - self.left.get((idx, obs["floor"], chosen["id"]), -math.inf) < TABU
                or self.switches.get(idx, 0) >= MAX_SWITCHES):
                return None
        self.last_choice[idx] = t
        if current is not None:
            self.left[idx, obs["floor"], current] = t
            self.switches[idx] = self.switches.get(idx, 0) + 1
        description = "estimated travel and queue time"
        if self.beta * chosen.get("smoke", 0) or self.gamma * chosen.get("unfamiliar", False):
            description = "estimated travel, queue, smoke and familiarity cost"
        return {"target": chosen["id"], "action": "go" if current is None else "reroute",
                "reason": f"{obs['trigger']}: {description} {costs[candidate]:.1f} s"}


class LLMBrain:
    """Bounded model calls; a timed-out call is never queued behind another.

    Python cannot interrupt a running thread. The backend must also enforce its
    network timeout; shutdown here never waits for a slow provider.
    """
    def __init__(self, rule, decide=None, timeout=60.0, decide_batch=None):
        self.rule = rule
        self.provider = decide
        self.batch_provider = decide_batch
        self.timeout = timeout
        self.pending = None

    def decide(self, obs):
        from concurrent.futures import ThreadPoolExecutor
        from copy import deepcopy

        result = None
        if self.provider is not None and (self.pending is None or self.pending.done()):
            pool = ThreadPoolExecutor(max_workers=1)
            try:
                self.pending = pool.submit(self.provider, deepcopy(obs))
                result = self.pending.result(timeout=self.timeout)
            except Exception:
                pass
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
        return self._validated(obs, result)

    def decide_batch(self, observations):
        from concurrent.futures import ThreadPoolExecutor
        from copy import deepcopy

        if not observations:
            return []
        results = None
        if self.batch_provider is not None and (self.pending is None or self.pending.done()):
            pool = ThreadPoolExecutor(max_workers=1)
            try:
                self.pending = pool.submit(self.batch_provider, deepcopy(observations))
                results = self.pending.result(timeout=self.timeout)
            except Exception:
                pass
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
        if not isinstance(results, list) or len(results) != len(observations):
            results = [None] * len(observations)
        return [self._validated(obs, result) for obs, result in zip(observations, results)]

    def _validated(self, obs, result):
        if (isinstance(result, dict) and result.get("action") in ("go", "reroute", "wait")
            and result.get("target") in [o["id"] for o in obs["options"]]
            and isinstance(result.get("reason"), str)):
            return {key: result[key] for key in ("target", "action", "reason")}
        result = self.rule.decide(obs)
        return dict(result or {"target": obs["current"], "action": "wait",
                               "reason": "rules: keep current target"}, fallback=True)


def load_llm_decider():
    """Optional backend dependency, imported only for showcase runs."""
    try:
        from backend.llm.features import decide
        return decide
    except ImportError:
        import warnings
        warnings.warn("LLM decisions unavailable; using rules", RuntimeWarning)
        return None


def load_llm_batch_decider():
    """Optional batch provider, never imported by rule-only runs."""
    try:
        from backend.llm.features import decide_batch
        return decide_batch
    except ImportError:
        import warnings
        warnings.warn("LLM batch decisions unavailable; using rules", RuntimeWarning)
        return None
