# Agent design

## Body and brain

- **Body (JuPedSim):** moves each agent every 0.01 s; handles collision avoidance and queues at doors and stairs. It never decides anything.
- **Brain (our Python):** runs about once a second or on events. It picks the exit, sets walking speed in smoke, and decides whether to wait for help.

## What each agent carries

- **Profile:** typical, older, cane/walker, wheelchair, visitor.
- **Movement:** free speed drawn from the profile's range; stair ability.
- **Start delay:** long for residents who are asleep.
- **Knowledge:** residents know all exits; visitors know only the door they came in by; hazards it has seen.
- **Ties:** group members; a helper paired with someone who needs help.
- **Status:** not moving yet, moving, queuing, waiting for help, out, trapped.

## Life cycle

1. Not moving yet: the start-delay countdown begins at the alarm, at the sight of smoke, or at seeing fire (seeing fire shortens it).
2. Evacuating: the route is a chain of waypoints ending at an exit.
3. Re-planning, triggered by:
   - reaching a junction;
   - smoke on the route coming into view;
   - the target door being blocked;
   - a long queue.
4. Waiting: wheelchair users on upper floors go to a refuge or stair landing; a timer (`assistDelay`, default 180 s) releases them.
5. Done: out, trapped, or (stretch) overcome by smoke.

## Exit choice

Cost for agent $i$ and exit $e$:

$$C_e = \frac{d_e}{v_i} + \frac{q_e}{F_e} + \beta\, s_e + \gamma\, u_{i,e}$$

- $d_e$: route length; $v_i$: current speed.
- $q_e$: people queued; $F_e$: exit flow (persons/s).
- $s_e$: smoke along the route; $u_{i,e}$: penalty for not knowing the exit.

Choice with randomness:

$$P_i(e) = \frac{e^{-C_e/\tau}}{\sum_k e^{-C_k/\tau}}$$

Switch only when clearly better:

$$C_{\text{new}} < (1 - h)\, C_{\text{current}}, \qquad h \approx 0.2$$

Agents score only what they know: hazards within their visibility distance, plus anything an alarm message or a warden tells them.

## Coupling with the fire (every ~1 s)

- Visibility at the agent's cell sets walking speed (formula in 06), via `agent.model.desired_speed`.
- An untenable cell marks the agent trapped.
- Untenable doors and stairs leave the route graph. Agents react when they see this or are told.

## Floors and stairs

- One JuPedSim simulation per floor, all stepped together.
- An agent entering a stair zone on floor $k$ is removed, then re-added at the same stair group on floor $k-1$ after a delay of stair length over stair speed.
- Each stair group has a FIFO queue with a throughput cap (about 1.1 persons/s per meter of stair width).
- Followers and helpers can use JuPedSim's direct-steering stage, with their target set near the leader each tick.

## Where LLMs fit

- **Personas:** one call writes occupant descriptions; code maps them to profile parameters.
- **Report card:** one call turns metrics into the top three weak spots, the numbers behind them and fixes.
- **Situation cache:** key each decision by (junction, smoke level, queue level, profile). Ask the LLM once per key and reuse the answer, so runs stay fast and repeatable.

$$50 \times 3 \times 2 \times 5 = 1{,}500 \text{ possible situations, computed once for all runs}$$

- **Live LLM agents:** 10–20 per run ask the model at junctions; fall back to rules on timeout; show their reasoning on hover. Agents passing on information ("east stairs are blocked") would be a strong demo moment.

## Why not make every agent a live LLM

- **Calls per run:**

$$300 \times 5 = 1{,}500 \text{ calls per run}$$

- **Calls for the risk map**, over 20–50 fire locations and about 10 seeds:

$$1{,}500 \times (200 \text{ to } 500) = 300{,}000 \text{ to } 750{,}000 \text{ calls}$$

- **Time:** at a guessed 0.2–1 s per small-model call, that's 5–25 minutes per run and about 17 hours to 9 days for the full set.
- **Repeatability:** answers vary between runs, which breaks "door open vs. closed" comparisons.
- **Validity:** no evidence LLM choices match real evacuees. One 2026 study had "neurotic" LLM agents panic, while evacuation research finds panic is rare.
- **Research exists:** LLM-in-the-loop evacuation research uses batching and parallelism, but these are research projects, not 36-hour builds.

## Determinism (measured)

- Same seed: identical trajectories.
- JuPedSim agent ids keep counting across simulations in one process, so key agents by our own `idx`.
- LLM output isn't repeatable, so log each decision and replay from the log, or turn LLM agents off for A/B comparisons.
- Bit-identical results hold on one machine and library version; precompute demo runs on one machine.
- One seed is one possible night: run 10–20 seeds per scenario and show the range; use the same seed for both sides of a comparison.
