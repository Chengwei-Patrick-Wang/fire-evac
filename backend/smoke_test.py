"""Backend smoke test. From the repo root: python -m backend.smoke_test

Needs contracts/building.example.json plus sim.run and fire.metrics. Runs the example
scenario (maxTime 60) through the API, polls until it is saved, and checks the result.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLL_TIMEOUT = 180  # seconds


def main() -> int:
    # Imported here, not at module level: pool workers re-import this module under spawn
    # (as __mp_main__) and should not pay for fastapi each time.
    from fastapi.testclient import TestClient

    from backend.app import jobs
    from backend.app.main import PRIVATE_DIR, app

    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200

        # buildings
        r = client.get("/api/buildings")
        assert r.status_code == 200, r.text
        ids = [b["id"] for b in r.json()]
        assert "example-office" in ids, f"example-office not in /api/buildings: {ids}"
        r = client.get("/api/buildings/example-office")
        assert r.status_code == 200 and len(r.json()["floors"]) >= 2, r.text[:200]
        assert client.get("/api/buildings/nope").status_code == 404

        # from-plan round trip (saved to data/private, removed again below)
        plan_path = ROOT / "contracts" / "plan.example.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["id"] = "smoke-from-plan"
        saved = PRIVATE_DIR / "smoke-from-plan.json"
        try:
            r = client.post("/api/buildings/from-plan", json=plan)
            assert r.status_code == 200 and r.json() == {"id": "smoke-from-plan"}, r.text
            listed = {b["id"]: b for b in client.get("/api/buildings").json()}
            assert listed["smoke-from-plan"].get("private") is True, listed["smoke-from-plan"]
            assert listed["smoke-from-plan"]["floors"] == len(plan["floors"])
        finally:
            saved.unlink(missing_ok=True)
        assert "smoke-from-plan" not in [b["id"] for b in client.get("/api/buildings").json()]

        # placeholders and errors
        assert client.post("/api/report").status_code == 501
        assert client.post("/api/trace/propose").status_code == 501
        if (ROOT / "contracts" / "batch.example.json").is_file():  # made in task S6
            r = client.post("/api/batch")
            assert r.status_code == 200, r.text
            r = client.get(f"/api/batch/{r.json()['batchId']}")
            assert r.status_code == 200, r.text
            assert r.json().get("version", "").startswith("batch/"), r.text[:200]
        else:
            print("note: contracts/batch.example.json not generated yet, batch check skipped")
            assert client.post("/api/batch").status_code == 404
        assert client.get("/api/runs/doesnotexist").status_code == 404
        r = client.post("/api/runs", json={"buildingId": "no-such-building"})
        assert r.status_code == 404, r.text

        # a real run: example scenario, maxTime 60
        scenario = json.loads(
            (ROOT / "contracts" / "scenario.example.json").read_text(encoding="utf-8")
        )
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
    print(
        f"OK  run {run_id}: {len(run['frames'])} frames, {len(doors)} doors, "
        f"evacuated {m.get('evacuated')}/{m.get('agents')}, trapped {m.get('trapped')}, "
        f"t90 {m.get('t90')}, t100 {m.get('t100')}, {saved_run.stat().st_size / 1e6:.1f} MB, "
        f"{elapsed:.1f} s through the API"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
