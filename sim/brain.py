"""Seeded queue-aware choices; observations are also the optional LLM boundary."""
from functools import lru_cache
import math

import jupedsim as jps
import numpy as np

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


def route_length(floor_poly, p, q):
    """Walkable path length, with a straight-line fallback on routing failure."""
    if ROUTING_MODE == "RoutingEngine":
        try:
            points = _router(floor_poly).compute_waypoints(p, q)
            if len(points) >= 2:
                return sum(math.dist(a, b) for a, b in zip(points, points[1:]))
        except Exception:
            pass
    return math.dist(p, q)


def mobility_options(options, stairs=True):
    """Prefer same-floor exits for people who require stair assistance."""
    if stairs:
        return options
    exits = [o for o in options if o["kind"] == "exit"]
    return exits or [dict(o, assist=True) for o in options]


def should_switch(c_current, c_new):
    return c_new < 0.8 * c_current


class RuleBrain:
    def __init__(self, seed):
        self.rng = np.random.default_rng([seed, 1])
        self.last_choice = {}
        self.left = {}
        self.switches = {}

    def decide(self, obs):
        options = obs["options"]
        if not options:
            return None
        costs = np.array([o["dist"] / max(obs["speed"], 0.2) +
                          o["queue"] / o["flow"] + o["tail"] for o in options])
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
                or t - self.last_choice.get(idx, -math.inf) < MIN_DWELL
                or options[old]["dist"] <= COMMIT_DIST
                or t - self.left.get((idx, obs["floor"], chosen["id"]), -math.inf) < TABU
                or self.switches.get(idx, 0) >= MAX_SWITCHES):
                return None
        self.last_choice[idx] = t
        if current is not None:
            self.left[idx, obs["floor"], current] = t
            self.switches[idx] = self.switches.get(idx, 0) + 1
        return {"target": chosen["id"], "action": "go" if current is None else "reroute",
                "reason": f"{obs['trigger']}: estimated travel and queue time {costs[candidate]:.1f} s"}


class LLMBrain:
    """Bounded model calls; a timed-out call is never queued behind another.

    Python cannot interrupt a running thread. The backend must also enforce its
    network timeout; shutdown here never waits for a slow provider.
    """
    def __init__(self, rule, decide, timeout=4.0):
        self.rule = rule
        self.provider = decide
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
