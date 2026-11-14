# Research findings

## Answers to the starting concerns

**Fire start and extinguishers**
- The user clicks a room, or a batch run samples rooms, and picks a fire-type preset (growth rate, peak size, smoke amount).
- US fire departments respond to roughly 3,200–3,400 fires a year in dorms, fraternities, sororities and barracks. About 8 in 10 involve cooking, mostly starting in a kitchen or cooking area. Lithium-ion batteries are a growing concern.
- **Presets:**
  - kitchen (medium to fast)
  - bedroom at night (medium, long occupant delays)
  - lithium-ion battery (fast to ultra-fast, heavy smoke)
  - trash or furniture in a corridor (fast)
  - flammable liquid (instant)
- Extinguishers are a rule: an agent next to a small fire may try one, and success falls as the fire grows. A sprinkler toggle caps fire growth. A door-state toggle covers propped-open stair doors.

**Plan reading**
- Fully automatic reading isn't reliable. On AECV-Bench (2026), leading vision-language models scored about 0.40–0.55 exact match counting doors and windows, versus 0.70–0.95 reading printed text.
- CubiCasa5K-trained models do better, but mostly on plans like their training data (Finnish homes).
- So: IFC models (already labeled) first, and assisted tracing for images.

**Geometry**
- One building model gives three views: walkable polygons for the crowd engine, a 0.5 m grid for fire, smoke and heatmaps, and a room–door graph for routing and "only one way out" checks.
- Floors connect by stair transfer. Elevators are excluded, since standard guidance is not to use them in a fire.

**Congestion**
- Use JuPedSim's published models; queues come from agent interactions, not scripts.
- Calibration matters (see 07): with default settings, a real 1 m door passed 0.97 persons/s, but exit zones drawn without a door opening let people out about 4 times faster per meter.

**Performance and cost**
- Simulate first, replay afterward; hundreds to a few thousand agents are fine (see 07).
- The simulation is free. The LLM is the only metered cost:
  - one call per agent per step is about $20–60 of input per run, and far too slow;
  - targeted use costs cents per run.

**Occupant variability:** profiles with ranges.
- Typical adults follow IMO uniform speed ranges by age and sex (women under 30: 0.93–1.55 m/s).
- Field data (SFPE Europe): cane about 0.91, rollator about 1.07, electric wheelchair about 1.08 m/s. People with accessibility needs were about 33% slower on average.
- A lab study (PMC8904864): no aid 1.15, stick 0.82, four-wheel walker 0.69 m/s. The two datasets disagree, so test low and high values.
- UK government figures: about 0.5% of people can't use stairs at all and about 5% have difficulty.
- Start delay can exceed walking time.
- US rules don't require areas of refuge in buildings with supervised sprinklers throughout.

**Fire and smoke:** a ladder.
- MVP: own grid model.
- Stretch: CFAST (NIST two-zone model, free, validated).
- Out: FDS (CFD, hours per run).

**Dynamic conditions**
- Smoke lowers visibility, which slows walking (formula in 06).
- Untenable doors and stairs leave the route graph.
- Agents re-plan only when they see a hazard or are told about it.
- Queue switching between exits.
- Stretch: smoke-dose tracking (FED).

## Existing tools

| Tool | What it is | Cost |
| --- | --- | --- |
| Pathfinder (Thunderhead) | Agent egress simulator, 3D results, V&V suite; option to cap door flows at SFPE values | Commercial |
| MassMotion (Oasys) | Crowd simulation; test cases for movement disabilities and changing exits | Commercial |
| buildingEXODUS, STEPS | Long-standing evacuation models | Commercial |
| FDS + Smokeview, CFAST (NIST) | Fire models | Free |
| JuPedSim | Pedestrian dynamics library (Python over C++) | Free, open source |
| Vadere | Crowd simulation framework (Java) | Free, open source |

**Our angle:**
- a plan or photo becomes a runnable building without CAD;
- automatic sweeps over ignition points with a ranking of weak spots;
- accessibility built in;
- a plain-language report a non-engineer can act on.

## Ethics and credibility

- **Not a compliance tool.** Say so in the UI and the pitch. Real assessments use validated tools and a fire protection engineer.
- **Show that it's checked.** NIST TN 1822 groups verification tests into five components: pre-evacuation time, movement and navigation, exit usage, route availability, and flow conditions. IMO and RiMEA publish similar suites. Show the door-flow calibration and ranges across runs.
- **Weak-spot maps of real buildings are sensitive.** Keep them out of the public repo and Devpost, demo on a public or synthetic building, and share real findings privately with UMass Environmental Health & Safety.
- **Respect plan rights** (see 08).
- **Avoid false reassurance:** show the assumptions next to every result.
- **Disability:**
  - model assisted evacuation honestly;
  - frame long waits as a building and planning gap, not a trait of the person;
  - ask UMass Disability Services or disabled students to review the profiles if the project continues.
- **No "panic" mode.** Evacuation research finds mass panic is rare; delays come from slow starts, wayfinding and queues.
- **No personal data.**

## Prize fit (confirm criteria with organizers)

| Prize | Fit | Emphasis |
| --- | --- | --- |
| Best UMass Hack | Strong if a UMass building is shown | One concrete finding; offer it to campus safety privately |
| Best Accessibility Hack | Strong | Mobility profiles; who waits for help and where |
| Most Impactful AI Hack | Strong | AI proposes plan labels, writes the report; LLM agents; say what is rule-based |
| Best Software Hack | Strong | One working pipeline from plan to 3D replay |
| Best UI/UX | Good | Click-to-ignite, scrubber, heatmaps, readable 3D |
| Best Pitch | Good | Fast first look for campus safety offices, not an engineer replacement |
| Best Use of Gemini API (MLH) | Good if Gemini is used | Plan labeling and findings |
| Best Agentic Hack (Sentient OS) | Possible | Goal-driven evacuees; ask what counts as agentic |
| MongoDB Atlas or Tiger Data (MLH) | Possible, pick one | Run storage or occupancy time series |
| GoDaddy domain (MLH) | Easy add-on | Demo domain |
| Hardware, MedTech, Nessie, Solana | No fit | Skip |
