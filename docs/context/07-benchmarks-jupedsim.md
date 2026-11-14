# JuPedSim benchmarks and notes

All runs used JuPedSim 1.4.2 (`pip install jupedsim`), `CollisionFreeSpeedModel` with default parameters, 0.01 s steps, desired speed 1.2 m/s, radius 0.2 m, on a 2-core x86 cloud container.

## Speed

| Setup | Agents | Simulated | Computer time | Real-time factor |
| --- | --- | --- | --- | --- |
| 60 × 20 m floor, 1.2 m exit zones at each end (no door opening) | 300 | 38 s | 1.0 s | about 40× |
| Same | 1,000 | 109 s | 22.5 s | about 5× |
| Same | 2,000 | 217 s | 121 s | about 1.8× |
| Same floor, two real 1.0 m doors with 3 m corridor stubs | 300 | 157 s | 10.2 s | about 15× |

- Computer time grows faster than the agent count, because dense queues are the expensive part.
- Plan accordingly: simulate first, save positions at 5–10 frames per second, replay in the browser, and run batches in parallel across cores.
- A first try at 1,000 agents with real doors didn't finish within the 10-minute timeout. Expect jammed buildings to be much slower than open floors.

## Flow and calibration

- Real 1.0 m door: **0.97 persons/s**. Hand estimates are 0.91 (effective width) and 1.3 (IMO, clear width).
- Exit zones drawn against a wall, with no door opening: about **3.8 persons/s per meter**. That's an artifact: agents get absorbed along the zone's whole perimeter.
- **Lesson:** model doors as real openings, and check door, corridor and stair flows against design values before trusting a bottleneck.

## Determinism

- Seed 1, run three times: 3,837 steps each, with every position identical to 9 decimal places once agent ids are made relative.
- Seed 2: 39.63 s simulated, versus 38.37 s for seed 1.
- Gotcha: agent ids keep counting across simulations in the same Python process (first ids 1, 301, 601).

## API facts (checked on 1.4.2)

- **Simulation methods:** `add_agent`, `add_exit_stage`, `add_waypoint_stage`, `add_waiting_set_stage`, `add_queue_stage`, `add_direct_steering_stage`, `add_journey`, `switch_agent_journey`, `switch_geometry`, `agents`, `agent`, `agents_in_polygon`, `agents_in_range`, `mark_agent_for_removal`, `removed_agents`, `iterate`, `elapsed_time`, `iteration_count`.
- **Stage types:** `ExitStage`, `WaypointStage`, `WaitingSetStage`/`WaitingSetState`, `NotifiableQueueStage`, `JourneyDescription`, `Transition`.
- **Agent fields:** `id`, `journey_id`, `stage_id`, `position`, `orientation`, `target`, `model`.
- **CFSM agent model fields:** `desired_speed` (settable mid-run), `v0`, `radius`, `time_gap`.
- **Models in 1.4.2:** AnticipationVelocity, CollisionFreeSpeed (V1–V3), GeneralizedCentrifugalForce, SocialForce, WarpDriver.
- **Gotcha:** `removed_agents()` reports removals for the last iteration only. Check it every step, or you miss most exits; the first example run reported 118 of 120 agents "trapped" because of this.
- **Install:** pulls in PySide6 and VTK (large), so install early on every laptop. The PyPI license field is blank; check the repo.
