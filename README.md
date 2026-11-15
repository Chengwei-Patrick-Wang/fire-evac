# Fire Evacuation Simulator (HackUMass XIV)

Give us a building, and we'll show where people get stuck before a fire does.

Load a building (a traced floor plan or an open IFC model), start a fire, simulate a few hundred evacuees, and see the chokepoints: a 3D replay with smoke and queues, a risk map over many fire locations, and a ranked list of weak spots.

**Not a compliance tool.** The fire and smoke model is illustrative; real assessments need validated tools and a fire protection engineer.

## Where things are

- Design spec: [`docs/superpowers/specs/2026-11-13-fire-evac-sim-design.md`](docs/superpowers/specs/2026-11-13-fire-evac-sim-design.md)
- One plan per workstream: [`docs/superpowers/plans/`](docs/superpowers/plans/)
- Rules for every agent and person: [`AGENTS.md`](AGENTS.md)
- Research, numbers and sources: [`docs/context/`](docs/context/)
- Data contracts (examples are the source of truth): [`contracts/`](contracts/)

## Quick start

Python 3.12 and Node 20+.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt  # JuPedSim pulls in PySide6 and VTK; this takes a while
cp .env.example .env             # add GEMINI_API_KEY, or APP_ANTHROPIC_API_KEY and LLM_PROVIDER=claude
python tools/build_examples.py   # regenerate contracts/*.example.json
uvicorn backend.app.main:app --reload
```

Frontend: `cd frontend && npm install && npm run dev`.

## Workstreams

| WS | Owns |
| --- | --- |
| A | Repo, contracts, API, Gemini features, tracer page, integration, demo |
| B | Buildings: plan normalizer, IFC import |
| C | Crowd simulation (JuPedSim) |
| D | Fire and smoke, metrics, batch risk map |
| E | Frontend: 3D replay, dashboard, risk map |

## Credits

Data sources and their licenses are listed in `docs/context/08-buildings-data.md` and `docs/context/11-sources.md`.
