# Fire Evacuation Simulator — context handoff

Context and decisions from the planning session in the Claude app (Fri Nov 13, 2026, about 6:30–10:30 PM ET), for restarting the Superpowers process in Claude Code.

## How to use this folder

1. Put it in the repo as `docs/context/`.
2. In Claude Code: *"Read docs/context/README.md and every file it lists. Then use superpowers:brainstorming to settle the Open items in 02-decisions.md, confirm or change the Proposed items, and write the spec."*
3. Status labels in `02-decisions.md`:
   - **Decided:** the team said so. Treat as fixed.
   - **Proposed:** defaults from the planning session. Confirm or change.
   - **Open:** needs an answer.
4. `prior-drafts/` has a spec, five workstream plans and a CLAUDE.md drafted in the Claude app, already in Superpowers layout (`docs/superpowers/specs`, `docs/superpowers/plans`). Reuse, edit or discard them.

## Files

| File | Contents |
| --- | --- |
| `01-project-brief.md` | The idea, hackathon constraints, team, starting concerns |
| `02-decisions.md` | Decided / Proposed / Open, with reasons |
| `03-research-findings.md` | Answers to each concern, fire and occupant data, plan-reading limits, existing tools, ethics, prize fit |
| `04-architecture-contracts.md` | Architecture, repo layout, data contracts, module APIs |
| `05-agent-design.md` | How evacuee agents work, where LLMs fit, determinism |
| `06-formulas.md` | Fire growth, visibility, walking speed in smoke, door capacity, timeline, metrics, cost |
| `07-benchmarks-jupedsim.md` | Measured JuPedSim speed, flows, determinism, API facts and gotchas |
| `08-buildings-data.md` | UMass plan options, ready-made BIM models and datasets, licenses, IFC how-to |
| `09-demo-visuals.md` | Visuals, screen layout, 3-minute demo script |
| `10-team-workflow.md` | Five workstreams, sync points, Max vs Pro usage strategy, permissions, gotchas |
| `11-sources.md` | Links |
| `prior-drafts/` | Draft spec, five plans, CLAUDE.md |

## Other artifacts from the Claude app

- Feasibility report (Claude doc): https://claude.ai/artifact/1bLcqpjSNedSeXR7vmmRJU
- `fire-evac-starter.zip` (sent in the Claude app): the drafts above plus `contracts/*.example.json`, `tools/build_examples.py` (generates an example building and a real JuPedSim run), `tools/plot_building.py`, `fire/stub.py`, `requirements.txt`, `README.md`.
- Shelved idea, speech feedback coach (Claude doc): https://claude.ai/artifact/VweH8XQzdjZYNXmrjGnYm3
