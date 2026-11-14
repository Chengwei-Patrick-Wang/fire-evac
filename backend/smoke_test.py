"""Backend smoke test. From the repo root: python -m backend.smoke_test

Needs contracts/building.example.json and plan.example.json plus sim.run, fire.metrics and
fire.batch. Goes through the API with TestClient: buildings, from-plan (private and public), the
batch (a real two-ignition batch, maxTime 60, polled until saved), report and trace routes, and a
real run (example scenario, maxTime 60) polled until saved.
check_batch, check_report and check_trace are one function per route file, so A4, A7 and A8
each rewrite only their own.
"""
import io
import json
import sys
import threading
import time
from contextlib import redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLL_TIMEOUT = 180  # seconds
BATCH_TIMEOUT = 300  # seconds


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


def poll_batch(client, batch_id: str, timeout: float = BATCH_TIMEOUT) -> dict:
    """GET /api/batch/{id} until it stops saying "running"; returns that body."""
    t0 = time.time()
    while True:
        r = client.get(f"/api/batch/{batch_id}")
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        if body.get("status") != "running":
            return body
        assert time.time() - t0 < timeout, f"batch {batch_id} not done after {timeout} s"
        time.sleep(1)


def check_batch_placeholder(client):
    """S5's placeholder, served while fire.batch does not import: the example batch for any request."""
    if not (ROOT / "contracts" / "batch.example.json").is_file():
        print("note: contracts/batch.example.json not generated yet, placeholder check skipped")
        assert client.post("/api/batch").status_code == 404
        return
    r = client.post("/api/batch")
    assert r.status_code == 200, r.text
    r = client.get(f"/api/batch/{r.json()['batchId']}")
    assert r.status_code == 200, r.text
    assert r.json().get("version", "").startswith("batch/") and r.json().get("placeholder") is True, r.text[:200]


def check_batch(client):
    """POST /api/batch on fire.batch.run_many: bad requests, the placeholder fallback, a short real
    batch (two ignitions, one seed, maxTime 60) and two that fail. Needs fire.batch to import;
    while the placeholder is served, only the placeholder is checked. The module is imported
    here, not at the top: pool workers re-import this file under spawn."""
    try:
        import fire.batch as fire_batch
    except ImportError:
        print("note: fire.batch does not import yet, the real batch check is skipped")
        return check_batch_placeholder(client)

    from backend.app import batch as batch_api

    # with fire.batch gone the API falls back to the placeholder
    sys.modules["fire.batch"] = None  # an import of it now fails, as before D's module landed
    try:
        check_batch_placeholder(client)
    finally:
        sys.modules["fire.batch"] = fire_batch

    base = json.loads((ROOT / "contracts" / "scenario.example.json").read_text(encoding="utf-8"))
    base["maxTime"] = 60
    base["brain"] = "llm"  # the API must force rules
    ignitions = [{"floor": "F1", "room": "R101"}, {"floor": "F1", "room": "R102"}]
    body = {"base": base, "ignitions": ignitions, "seeds": [1]}

    # bad requests
    assert client.post("/api/batch").status_code == 422  # no body
    assert client.post("/api/batch", json={}).status_code == 422  # no base
    assert client.post("/api/batch", json=dict(body, base=dict(base, buildingId=None))).status_code == 422
    assert client.post("/api/batch", json=dict(body, base=dict(base, fire={}))).status_code == 422
    r = client.post("/api/batch", json=dict(body, base=dict(base, buildingId="no-such-building")))
    assert r.status_code == 404, r.text
    for bad in (
        {"ignitions": [{"floor": "F1", "room": "no-such-room"}]},
        {"ignitions": []},
        {"ignitions": ["R101"]},
        {"seeds": []},
        {"seeds": ["1"]},
    ):
        r = client.post("/api/batch", json=dict(body, **bad))
        assert r.status_code == 422, (bad, r.status_code, r.text[:200])
    assert client.get("/api/batch/doesnotexist").status_code == 404

    # a real batch. The job is held until the check has seen it running (it runs off the request
    # thread), then released to run the real run_many: two fires, one seed, in run_many's own pool.
    real_run_many = fire_batch.run_many
    gate = threading.Event()

    def held(*args, **kwargs):
        assert gate.wait(60), "the batch was never released"
        return real_run_many(*args, **kwargs)

    fire_batch.run_many = held
    saved = None
    t0 = time.time()
    try:
        r = client.post("/api/batch", json=body)
        assert r.status_code == 200, r.text
        batch_id = r.json()["batchId"]
        saved = ROOT / "data" / "runs" / f"batch-{batch_id}.json"
        assert client.get(f"/api/batch/{batch_id}").json() == {"status": "running"}
        gate.set()
        batch = poll_batch(client, batch_id)
        elapsed = time.time() - t0
    finally:
        gate.set()
        fire_batch.run_many = real_run_many
    try:
        if batch.get("status") == "error":
            raise AssertionError(f"batch failed: {batch.get('error')}\n{batch.get('traceback', '')}")
        keys = ("version", "id", "buildingId", "base", "runs", "rooms", "doors", "heatmaps", "top")
        missing = [k for k in keys if k not in batch]
        assert not missing, f"batch/v0 keys missing: {missing}"
        assert batch["version"].startswith("batch/") and not batch.get("placeholder"), batch["version"]
        assert batch["id"] == batch_id and batch["buildingId"] == "example-office", (batch["id"], batch["buildingId"])
        assert batch["base"]["brain"] == "rules", batch["base"].get("brain")
        assert batch["base"]["maxTime"] == 60
        assert not batch.get("failed"), batch.get("failed")
        ran = {(r["ignition"]["floor"], r["ignition"]["room"]) for r in batch["runs"]}
        assert ran == {("F1", "R101"), ("F1", "R102")}, ran
        assert [r["seed"] for r in batch["runs"]] == [1, 1], batch["runs"]
        assert {r["id"] for r in batch["rooms"]} == {"R101", "R102"} and batch["doors"], batch["rooms"]
        assert batch["top"], "top is empty"
        for item in batch["top"]:
            missing = [k for k in ("kind", "id", "floor", "score", "why") if k not in item]
            assert not missing, f"top entry lacks {missing}: {item}"
            assert isinstance(item["why"], str) and item["why"], item
        assert saved.is_file(), f"{saved} was not written"

        # after a "restart" (no jobs in memory) the batch is read back from disk
        batch_api._jobs.clear()
        r = client.get(f"/api/batch/{batch_id}")
        assert r.status_code == 200 and r.json() == batch
    finally:
        if saved is not None:
            saved.unlink(missing_ok=True)

    # a run_many that raises, and one that returns nothing but failures: both end as status "error"
    def boom(*args, **kwargs):
        raise RuntimeError("smoke: run_many failed on purpose")

    def all_failed(*args, **kwargs):
        failed = [{"scenarioId": "x-R101-s1", "error": "KeyError('type')"}]
        return {"version": "batch/v0", "runs": [], "failed": failed}

    for fake, expect in ((boom, "failed on purpose"), (all_failed, "KeyError('type')")):
        fire_batch.run_many = fake
        try:
            r = client.post("/api/batch", json=body)
            assert r.status_code == 200, r.text
            failed_id = r.json()["batchId"]
            state = poll_batch(client, failed_id, 30)
        finally:
            fire_batch.run_many = real_run_many
        assert state.get("status") == "error" and expect in state.get("error", ""), state
        assert "version" not in state, state  # the frontend tells a pending state from a batch by `version`
        assert not (ROOT / "data" / "runs" / f"batch-{failed_id}.json").exists()

    top = batch["top"][0]
    print(
        f"OK  batch {batch_id}: {len(batch['runs'])} runs, {len(batch['rooms'])} rooms, {len(batch['doors'])} doors, "
        f"top {len(batch['top'])} (first: {top['kind']} {top['id']} {top['score']}), {elapsed:.1f} s through the API"
    )


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
