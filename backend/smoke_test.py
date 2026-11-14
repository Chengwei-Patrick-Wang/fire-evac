"""Backend smoke test. From the repo root: python -m backend.smoke_test

Needs contracts/building.example.json and plan.example.json plus sim.run and fire.metrics.
Goes through the API with TestClient: buildings, from-plan (private and public), the batch,
report and trace routes, and a real run (example scenario, maxTime 60) polled until saved.
check_batch, check_report and check_trace are one function per route file, so A4, A7 and A8
each rewrite only their own.
"""
import io
import json
import sys
import time
from contextlib import redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLL_TIMEOUT = 180  # seconds


def check_buildings(client):
    r = client.get("/api/buildings")
    assert r.status_code == 200, r.text
    ids = [b["id"] for b in r.json()]
    assert "example-office" in ids, f"example-office not in /api/buildings: {ids}"
    r = client.get("/api/buildings/example-office")
    assert r.status_code == 200 and len(r.json()["floors"]) >= 2, r.text[:200]
    assert client.get("/api/buildings/nope").status_code == 404


def check_from_plan(client):
    """Private by default (data/private), data/buildings only with public=true; 422 on a bad version."""
    import buildings.normalize
    from backend.app.store import BUILDINGS_DIR, PRIVATE_DIR

    plan = json.loads((ROOT / "contracts" / "plan.example.json").read_text(encoding="utf-8"))
    n_floors = len(plan["floors"])
    public_file = BUILDINGS_DIR / "smoke-public.json"
    private_file = PRIVATE_DIR / "smoke-private.json"
    real_normalize = buildings.normalize.plan_to_building

    def clean():  # both ids in both folders, so a file that landed in the wrong one cannot linger
        for folder in (BUILDINGS_DIR, PRIVATE_DIR):
            for name in ("smoke-public", "smoke-private", "smoke-bad"):
                (folder / f"{name}.json").unlink(missing_ok=True)

    clean()
    try:
        # public=true lands in data/buildings
        r = client.post("/api/buildings/from-plan?public=true", json=dict(plan, id="smoke-public"))
        assert r.status_code == 200, r.text
        assert r.json()["id"] == "smoke-public", r.text
        assert isinstance(r.json()["warnings"], list), r.text
        assert public_file.is_file() and not (PRIVATE_DIR / "smoke-public.json").exists()

        # the default lands in data/private
        r = client.post("/api/buildings/from-plan", json=dict(plan, id="smoke-private"))
        assert r.status_code == 200 and r.json()["id"] == "smoke-private", r.text
        assert isinstance(r.json()["warnings"], list), r.text
        assert private_file.is_file() and not (BUILDINGS_DIR / "smoke-private.json").exists()

        listed = {b["id"]: b for b in client.get("/api/buildings").json()}
        assert listed["smoke-private"].get("private") is True, listed["smoke-private"]
        assert not listed["smoke-public"].get("private"), listed["smoke-public"]
        assert listed["smoke-private"]["floors"] == listed["smoke-public"]["floors"] == n_floors
        for building_id in ("smoke-public", "smoke-private"):
            r = client.get(f"/api/buildings/{building_id}")
            assert r.status_code == 200 and r.json()["id"] == building_id, r.text[:200]

        # a plan that is not plan/v0 is refused and nothing is written
        no_version = {k: v for k, v in plan.items() if k != "version"}
        for bad in (dict(plan, version="plan/v1"), no_version):
            r = client.post("/api/buildings/from-plan", json=dict(bad, id="smoke-bad"))
            assert r.status_code == 422, (r.status_code, r.text)
        assert not (BUILDINGS_DIR / "smoke-bad.json").exists() and not (PRIVATE_DIR / "smoke-bad.json").exists()

        # warnings: only the normalizer's "WARNING (normalize):" stderr lines come back
        def noisy(p, wall=None):
            print("WARNING (normalize): smoke warning", file=sys.stderr)
            print("some other stderr line", file=sys.stderr)
            return real_normalize(p, wall)

        buildings.normalize.plan_to_building = noisy
        log = io.StringIO()  # the endpoint also echoes what it captured to the server log
        try:
            with redirect_stderr(log):
                r = client.post("/api/buildings/from-plan", json=dict(plan, id="smoke-private"))
        finally:
            buildings.normalize.plan_to_building = real_normalize
        assert r.status_code == 200, r.text
        warnings = r.json()["warnings"]  # (the real normalizer may add warnings of its own)
        assert "WARNING (normalize): smoke warning" in warnings, warnings
        assert "some other stderr line" not in warnings, warnings
        assert "some other stderr line" in log.getvalue(), log.getvalue()
    finally:
        clean()
    listed = [b["id"] for b in client.get("/api/buildings").json()]
    assert "smoke-public" not in listed and "smoke-private" not in listed, listed


def check_batch(client):
    if (ROOT / "contracts" / "batch.example.json").is_file():  # made in task S6
        r = client.post("/api/batch")
        assert r.status_code == 200, r.text
        r = client.get(f"/api/batch/{r.json()['batchId']}")
        assert r.status_code == 200, r.text
        assert r.json().get("version", "").startswith("batch/"), r.text[:200]
    else:
        print("note: contracts/batch.example.json not generated yet, batch check skipped")
        assert client.post("/api/batch").status_code == 404


def check_report(client):
    assert client.post("/api/report").status_code == 501


def check_trace(client):
    assert client.post("/api/trace/propose").status_code == 501


def check_run(client) -> str:
    """A real run: example scenario, maxTime 60. Returns the summary line."""
    from backend.app import jobs

    assert client.get("/api/runs/doesnotexist").status_code == 404
    r = client.post("/api/runs", json={"buildingId": "no-such-building"})
    assert r.status_code == 404, r.text

    scenario = json.loads((ROOT / "contracts" / "scenario.example.json").read_text(encoding="utf-8"))
    scenario["maxTime"] = 60
    t0 = time.time()
    r = client.post("/api/runs", json=scenario)
    assert r.status_code == 200, r.text
    run_id = r.json()["runId"]
    while True:
        r = client.get(f"/api/runs/{run_id}")
        assert r.status_code == 200, r.text
        run = r.json()
        status = run.get("status")
        if status == "error":
            raise AssertionError(f"run failed: {run.get('error')}\n{run.get('traceback', '')}")
        if status != "running":
            break  # no status key: this is the run/v0 itself
        assert time.time() - t0 < POLL_TIMEOUT, f"run not done after {POLL_TIMEOUT} s"
        time.sleep(1)
    elapsed = time.time() - t0

    assert run["id"] == run_id and run["version"].startswith("run/"), run.get("version")
    assert run["frames"], "run has no frames"
    doors = run["metrics"]["doors"]
    assert doors, "metrics.doors is empty"
    saved_run = ROOT / "data" / "runs" / f"{run_id}.json"
    assert saved_run.is_file(), f"{saved_run} was not written"

    # after a "restart" (no futures in memory) the run is read back from disk
    jobs._futures.clear()
    r = client.get(f"/api/runs/{run_id}")
    assert r.status_code == 200 and r.json()["id"] == run_id

    m = run["metrics"]
    return (
        f"OK  run {run_id}: {len(run['frames'])} frames, {len(doors)} doors, "
        f"evacuated {m.get('evacuated')}/{m.get('agents')}, trapped {m.get('trapped')}, "
        f"t90 {m.get('t90')}, t100 {m.get('t100')}, {saved_run.stat().st_size / 1e6:.1f} MB, "
        f"{elapsed:.1f} s through the API"
    )


def main() -> int:
    # Imported here, not at module level: pool workers re-import this module under spawn
    # (as __mp_main__) and should not pay for fastapi each time.
    from fastapi.testclient import TestClient

    from backend.app.main import app

    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        check_buildings(client)
        check_from_plan(client)
        check_batch(client)
        check_report(client)
        check_trace(client)
        summary = check_run(client)
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
