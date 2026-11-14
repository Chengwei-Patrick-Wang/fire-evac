"""Tracer check: the TypeScript checks, then the exported plan through the normalizer.

    python tools/check_tracer.py

1. Runs `npx --yes tsx src/tracer/check.ts` in frontend/ (tsx needs no package.json). That script
   checks the pixel/meter geometry, the plan export and the validation, prints a good two-floor
   plan/v0 as JSON on stdout and "tracer check OK" on stderr.
2. Feeds the plan to buildings.normalize.plan_to_building and checks the result: 2 floors, one
   walkable polygon per floor, at least one exit, every stair group on both floors.

Prints "tracer check OK", then "tracer plan OK: 2 floors, N exits". Exit code 0 means all good.
Normalizer warnings (they start with "WARNING (normalize):") are shown as notes, not failures.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
SCRIPT = "src/tracer/check.ts"  # relative to frontend/
OK_LINE = "tracer check OK"  # what check.ts prints on stderr when every check passed
TIMEOUT = 300  # seconds; the first run may have to download tsx

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def fail(msg: str, detail: str = "") -> NoReturn:
    print(f"tracer check FAILED: {msg}", file=sys.stderr)
    if detail.strip():
        print(detail.rstrip(), file=sys.stderr)
    sys.exit(1)


def need(cond: object, msg: str, detail: str = "") -> None:
    if not cond:
        fail(msg, detail)


def kill_tree(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":  # /T takes node's children along
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        proc.kill()


def run_check_ts() -> tuple[bytes, str]:
    """(stdout as bytes, stderr as text) of check.ts; fails the whole check if it fails."""
    need((FRONTEND / SCRIPT).is_file(), f"frontend/{SCRIPT} is missing")
    npx = shutil.which("npx")  # npx.cmd on Windows
    need(npx, "npx is not on PATH (install Node 20 or newer)")
    group = {} if os.name == "nt" else {"start_new_session": True}  # POSIX: killpg needs a group
    proc = subprocess.Popen(
        [str(npx), "--yes", "tsx", SCRIPT], cwd=FRONTEND, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, **group,
    )
    try:
        out, err = proc.communicate(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        try:
            proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        fail(f"{SCRIPT} timed out after {TIMEOUT} s (is npx stuck downloading tsx?)")
    except BaseException:  # Ctrl+C: do not leave node running
        kill_tree(proc)
        raise
    text = err.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        fail(f"{SCRIPT} exited with code {proc.returncode}", text)
    return out, text


def main() -> int:
    for stream in (sys.stdout, sys.stderr):  # a Windows console may not encode every character
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    raw, log = run_check_ts()
    need(any(ln.strip() == OK_LINE for ln in log.splitlines()),
         f'{SCRIPT} did not report "{OK_LINE}"', log)
    try:
        # bytes in, decoded here as UTF-8: no shell redirect or console code page touches the plan
        plan = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        fail(f"{SCRIPT} did not print a plan as JSON on stdout ({exc})", raw[:300].decode("utf-8", "replace"))
    print(OK_LINE, flush=True)

    need(plan.get("version") == "plan/v0", f"plan.version must be 'plan/v0', got {plan.get('version')!r}")
    need(plan.get("source") == "trace", f"plan.source must be 'trace', got {plan.get('source')!r}")

    from buildings.normalize import plan_to_building  # needs the repo root on sys.path

    buf = io.StringIO()
    try:
        with contextlib.redirect_stderr(buf):
            building = plan_to_building(plan)
    except Exception as exc:
        fail(f"buildings.normalize rejected the exported plan: {type(exc).__name__}: {exc}", buf.getvalue())
    notes = [ln for ln in buf.getvalue().splitlines() if ln.strip()]

    floors = building["floors"]
    need(len(floors) == 2, f"expected 2 floors, got {len(floors)}")
    for f in floors:
        need(len(f["walkable"]) == 1,
             f"{f['id']}: expected one walkable polygon, got {len(f['walkable'])}", "\n".join(notes))
    exits = [e for f in floors for e in f["exits"]]
    need(exits, "no exits: the normalizer found no exterior door", "\n".join(notes))
    groups = [{s["group"] for s in f["stairs"]} for f in floors]
    every = set().union(*groups)
    need(every, "no stair groups")
    for f, g in zip(floors, groups):
        need(g == every, f"{f['id']}: stair groups {sorted(g)}, but the building has {sorted(every)}; "
                         "every group must be on both floors")
    # a door's `name` is its exit's name (the results panel shows it)
    named = {d["name"] for pf in plan["floors"] for d in pf["doors"] if d.get("name")}
    exit_names = {e["name"] for e in exits}
    need(named == exit_names, f"exit names {sorted(exit_names)} should be the named doors {sorted(named)}")

    for ln in notes:
        print(f"note: {ln}")
    print(f"tracer plan OK: {len(floors)} floors, {len(exits)} exits", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
