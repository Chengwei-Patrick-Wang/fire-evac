# Overnight status

Integration notes from the lead's machine, newest first. Read this before each task: it says what's merged into `main`, what failed, and anything your workstream should know. Only the lead's machine edits this file.

## Sat 00:20: notes from plan review

- **C:** sim v0 writes rows with status `-1` in the frame where an agent exits. run/v0 allows only 0–3 and says exited agents disappear, so drop those rows when you touch the frame writer. E already hides `-1`, so nothing breaks meanwhile.
- **A:** pin `NODE_VERSION = "22"` in `netlify.toml`, because current Vite needs Node 20.19+ or 22.12+.
- **Everyone:** all five plans are on `main`. Batch `top[].kind` may be `stair` with a door id, so look items up by id, not by kind.

## Sat 00:30: kickoff

- `main` has the walking skeleton:
  - plan normalizer v0 (`buildings/`);
  - per-floor sim v0, where upper-floor stairs are sinks so F2 agents never exit and t90/t100 stay null until C's stair transfer lands (`sim/`);
  - metrics v0 and a placeholder smoke source (`fire/metrics.py`, `tools/toy_fire.py`);
  - API (`backend/`);
  - generated examples (`contracts/`).
- About every 45 minutes the lead's machine merges each `ws-*` branch into `main` if all smoke tests pass on the merged result. Nothing is ever force-pushed.
- If your branch fails a check, the reason appears here under your workstream letter.
