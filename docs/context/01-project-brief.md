# Project brief

## Event and team

- **HackUMass XIV**, a 36-hour hackathon. Hacking started about 8:30 PM Friday, Nov 13, 2026; check the official schedule for the end and judging times.
- **Team of 5.** Tony is on Claude Max ($100, 5x Pro usage); the four teammates are on Pro ($20). Superpowers is installed in Claude Code.
- **Requested working style:** keep design fast, no rigorous testing, speed things up with subagents and handoffs between teammates.

## The idea

A fire safety simulator:
- Take a blueprint, floor plan or photos of a building and build a 3D model of it.
- Deploy AI agents as evacuees.
- Start fires in different places and of different types.
- Watch how the agents evacuate, to find weak spots such as chokepoints and hard-to-reach stairwells.

UMass buildings would be ideal, but non-UMass buildings are fine.

**Pitch in one line:** give us a building, and we'll show where people get stuck before a fire does.

## Concerns we started from

`03-research-findings.md` answers each of these:
- How does the fire start? Are fire extinguishers considered?
- **Blueprint interpretation:** extracting walls, doors, hallways, stairs and exits from arbitrary floor plans.
- **Geometry conversion:** turning drawings into a navigable grid or graph.
- **Multi-agent interactions:** congestion, collisions and bottlenecks.
- **Performance:** hundreds or thousands of agents in real time, and the cost.
- **Occupant variability:** speed, mobility and assistance needs.
- **Fire and smoke propagation** without heavy physics.
- **Dynamic conditions:** changing visibility, blocked routes and hazards.

## Earlier idea (shelved)

A speech-analysis interview coach (filler words, pace, camera-based body language). The team switched to the fire simulator.
