"""Backend smoke test. From the repo root: python -m backend.smoke_test [--live-llm]

Needs contracts/building.example.json and plan.example.json plus sim.run, fire.metrics and
fire.batch. Goes through the API with TestClient: buildings, from-plan (private and public), the
batch (a real two-ignition batch, maxTime 60, polled until saved), the report card and the LLM
client (offline: LLM_PROVIDER=off or a stubbed model), the trace route, and a real run (example
scenario, maxTime 60) polled until saved.
check_batch, check_report and check_trace are one function per route file, so A4, A7 and A8
each rewrite only their own (A7's other checks sit beside check_report, run by check_llm).
--live-llm runs only the LLM checks, plus one set of real model calls (GEMINI_API_KEY from .env).
"""
import io
import json
import os
import sys
import threading
import time
from contextlib import contextmanager, redirect_stderr
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


@contextmanager
def env(**values):
    """Set environment variables for the block (None unsets one), then put them back."""
    old = {k: os.environ.get(k) for k in values}

    def put(items):
        for k, v in items.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    put(values)
    try:
        yield
    finally:
        put(old)


def _examples() -> tuple[dict, dict, dict]:
    def load(name):
        return json.loads((ROOT / "contracts" / name).read_text(encoding="utf-8"))

    return load("batch.example.json"), load("run.example.json"), load("building.example.json")


def check_report(client):
    """A7, LLM_PROVIDER=off: the card is the template, with every top id and its why, the limits line
    ("Illustrative") and the writer line ("Template summary"); POST /api/report returns it and does
    not cache it; complete() returns None without raising; bad requests are refused."""
    from backend.llm import client as llm
    from backend.llm import features

    batch, _, building = _examples()
    saved = ROOT / "data" / "runs" / "batch-smoke-report-example.json"  # test-owned ids only: a real
    cache = ROOT / "data" / "runs" / "report-smoke-report-example.md"  # cached card is never touched
    cache.unlink(missing_ok=True)
    log = io.StringIO()
    with env(LLM_PROVIDER="off"), redirect_stderr(log):
        assert llm.complete("ping", schema={"type": "object"}) is None
        assert llm.complete("ping", image=b"\x89PNG\r\n") is None
        md = features.report(batch, building)
        spots = features._facts(batch, building)["spots"]
        assert len(spots) == len(batch["top"][:3]), spots
        for item, spot in zip(batch["top"][:3], spots):  # each spot under its name in words, D's numbers word for word
            assert f"**{spot['label']}**" in md and item["why"].split(": ", 1)[1] in md, (item, md)
        assert not features._Names(building).mentions_id(md), md  # no door id (an IFC code to a judge) anywhere
        assert "Illustrative" in md and "Template summary" in md, md
        assert features.LIMITS in md and md.rstrip().endswith("*Template summary (AI unavailable)*"), md[-300:]
        assert "panic" not in md.lower()

        # the endpoint: a saved batch gives exactly this card, uncached; the example id is served
        # too (from the demo index, whose copy may lag behind contracts/, or a cached AI card)
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_text(json.dumps(dict(batch, id="smoke-report-example")), encoding="utf-8")
        try:
            r = client.post("/api/report", json={"batchId": "smoke-report-example"})
            assert r.status_code == 200, r.text
            assert r.json() == {"markdown": md}, r.text[:300]
            assert not cache.exists(), "a template card was cached"
        finally:
            saved.unlink(missing_ok=True)
            cache.unlink(missing_ok=True)
        r = client.post("/api/report", json={"batchId": batch["id"]})
        assert r.status_code == 200 and "Illustrative fire model" in r.json()["markdown"], r.text[:300]

        for bad in (None, {}, {"runId": "a", "batchId": "b"}, {"batchId": "../x"}, {"batchId": 7}, {"run": "x"}):
            r = client.post("/api/report", json=bad) if bad is not None else client.post("/api/report")
            assert r.status_code == 422, (bad, r.status_code, r.text[:200])
        from backend.app import batch as batch_api

        if batch_api._fire_batch() is not None:  # S5's placeholder answers every batch id
            assert client.post("/api/report", json={"batchId": "no-such-batch"}).status_code == 404
        assert client.post("/api/report", json={"runId": "no-such-run"}).status_code == 404

        # never raises, whatever it is given
        for junk, building_junk in (({}, {}), (None, None), ({"version": "batch/v0", "runs": "x", "top": [None, 3]}, {"floors": "x"}),
                                    ({"version": "run/v0", "metrics": {"doors": [{"id": "D1", "waitPersonSeconds": "x"}]}}, [])):
            text = features.report(junk, building_junk)
            assert isinstance(text, str) and "Template summary" in text, text
    assert "LLM_PROVIDER=off" in log.getvalue(), log.getvalue()


def check_report_run(client):
    """A run's card: the 3 doors with the most person-seconds of waiting, each with its code-built why;
    the fire's room from fire.x, y; smoke exposure (D10's fields) before evacuation time; found by
    run id (demo index) and, as the frontend keys live runs, by scenario id in data/runs. A batch
    with smoke fields and what-ifs (D10, D11) leads each what-if line with exposure."""
    from backend.llm import features

    batch, run, building = _examples()
    m = run["metrics"]
    doors = sorted((d for d in m["doors"] if d["waitPersonSeconds"] > 0), key=lambda d: -d["waitPersonSeconds"])[:3]
    names = features._Names(building)

    def label(d):  # the door in words, never its id
        return names.label(names.door_kind(d["floor"], d["id"]), d["floor"], d["id"])[0]

    with env(LLM_PROVIDER="off"), redirect_stderr(io.StringIO()):
        md = features.report(run, building)
        for d in doors:
            why = f"{label(d)}: peak queue {d['peakQueue']:,.0f}; {d['waitPersonSeconds']:,.0f} person-seconds of waiting"
            assert why in md, (why, md)
        assert not names.mentions_id(md), md
        if m.get("t90") is not None:
            assert f"90% out at {m['t90']:,.0f} s" in md, md
        assert "Kitchen (R101)" in md, md  # the example fire is in the kitchen
        if "exposure" not in m:
            assert "Smoke:" not in md
        r = client.post("/api/report", json={"runId": run["id"]})  # the example: demo index (or a cached card)
        assert r.status_code == 200 and "Illustrative fire model" in r.json()["markdown"], r.text[:300]

        # D10 exposure (made-up values): it leads, evacuation second
        exposed = dict(run, metrics=dict(m, exposure={
            "doseUnit": 2700, "smokeD": 10.0, "personSecondsInSmoke": 2020.0, "agentsInSmoke": 57, "meanDose": 0.14,
            "maxDose": 1.9, "dosed": 4, "dosedIdx": [1, 2, 3, 4],
            "stairs": [{"floor": "F1", "group": "SA", "smokeAt": 62.0}, {"floor": "F2", "group": "SB", "smokeAt": None}]}))
        md2 = features.report(exposed, building)
        assert md2.index("Smoke:") < md2.index("Evacuation:"), md2
        assert "2,020 person-seconds in smoke" in md2 and "Stair A on F1 smoky from 62 s" in md2, md2
        assert f"57 of {m['agents']:,.0f} people in smoke at some point" in md2, md2

        # D10 + D11 on a batch: smoke before t90, in the numbers and in each what-if line
        b2 = json.loads(json.dumps(batch))
        for i, rr in enumerate(b2["runs"]):
            rr["smokeSeconds"], rr["dosed"] = 1000.0 + i, i % 3
        n = len(b2["runs"])
        b2["whatIf"] = [
            {"id": "proppedStairs", "label": "Stair doors propped open", "doors": {}, "sprinklers": False, "n": n,
             "dT90": 0.2, "dT90Min": -1.0, "dT90Max": 3.0, "slower": 3, "faster": 1, "dTrapped": 0.0,
             "dDosed": 0.5, "dSmokeSeconds": 366.0, "why": "t90 first, as D writes it"},
            {"id": "sprinklers", "label": "Sprinklers on", "doors": {}, "sprinklers": True, "n": n,
             "dT90": -0.5, "slower": 0, "faster": 2, "dTrapped": 0.0},
        ]
        md3 = features.report(b2, building)
        pct = f"{100 * 366.0 / (sum(1000.0 + i for i in range(n)) / n):+.0f}%"  # +35% for 66 runs
        assert md3.index("Smoke:") < md3.index("90% out:"), md3
        assert f"**Stair doors propped open: smoke exposure {pct} (+366 person-seconds in smoke per fire), while 90% out" in md3, md3
        propped = next(ln for ln in md3.splitlines() if ln.startswith("- **Stair doors propped open"))
        assert propped.index(f"smoke exposure {pct}") < propped.index("90% out 0.2 s later"), propped
        sprinklers = next(ln for ln in md3.splitlines() if "Sprinklers on" in ln)
        assert "90% out 0.5 s sooner on average (slower in 0 of" in sprinklers, sprinklers

        # A11, fire spread. A batch's card gets the sentence from fire.spread's schedule at the base's material (drywall
        # when it names none): the other rooms on fire by maxTime, per fire on average and at most (the first room in run
        # order wins a tie). A run's card gets it from its own fire.rooms and fire.material (C27), and without them it
        # is the card it always was.
        def hand_batch(*rooms, material="wood"):  # the example's fires in these rooms only, in this order
            hand = json.loads(json.dumps(batch))
            hand["runs"] = [rr for room in rooms for rr in hand["runs"] if rr["ignition"]["room"] == room]
            if material is None:
                hand["base"]["fire"].pop("material", None)
            else:
                hand["base"]["fire"]["material"] = material
            return hand

        wood = ("Fire spread at illustrative wood speeds: 14.0 other rooms per fire on average by 400 s, "
                "at most 14 rooms (fire in Kitchen (R101))")
        md_wood = features.report(hand_batch("R101", "L1"), building)
        assert f". {wood}." in md_wood and md_wood.index("90% out:") < md_wood.index(wood), md_wood
        lobby = names.room_label("F1", "L1")
        assert f"(fire in {lobby})" in features.report(hand_batch("L1", "R101"), building)  # a tie: the first one wins
        md_mixed = features.report(hand_batch("R101", "L1", "SA1"), building)  # the stair reaches all 23 other rooms
        assert ("Fire spread at illustrative wood speeds: 17.0 other rooms per fire on average by 400 s, "
                f"at most 23 rooms (fire in {names.room_label('F1', 'SA1')})") in md_mixed, md_mixed
        md_default = features.report(hand_batch("R101", "L1", material=None), building)  # no fire.material: drywall
        assert ("Fire spread at illustrative drywall speeds: 11.0 other rooms per fire on average by 400 s, "
                "at most 11 rooms (fire in Kitchen (R101))") in md_default, md_default
        md_steel = features.report(hand_batch("R101", material="steel"), building)  # unknown: no sentence, a card still
        assert "Fire spread" not in md_steel and "Template summary" in md_steel, md_steel
        had, spread_module = "fire.spread" in sys.modules, sys.modules.get("fire.spread")
        sys.modules["fire.spread"] = None  # the import fails
        try:
            assert "Fire spread" not in features.report(hand_batch("R101", "L1"), building)
        finally:
            if had:
                sys.modules["fire.spread"] = spread_module
            else:
                sys.modules.pop("fire.spread", None)

        def hand_run(material, *ignites):  # a run made by C27's sim: fire.rooms (the first is the ignition room), material
            rooms = [{"room": f"X{i}", "floor": "F1", "ignite": float(t)} for i, t in enumerate(ignites)]
            return dict(run, fire=dict(run["fire"], material=material, rooms=rooms))

        spread = "Fire spread at illustrative drywall speeds: 2 other rooms by 360 s"
        md_run = features.report(hand_run("drywall", 0, 180, 360), building)
        assert md_run.count(f". {spread}.") == 1 and md_run.index("Evacuation:") < md_run.index(spread), md_run
        plain = dict(run, fire={k: v for k, v in run["fire"].items() if k not in ("rooms", "material")})
        md_plain = features.report(plain, building)
        assert "Fire spread" not in md_plain and md_run.replace(f". {spread}.", ".", 1) == md_plain, md_plain
        assert "Fire spread at illustrative wood speeds: 1 other room by 90 s." in features.report(hand_run("wood", 0, 90), building)
        assert ("Fire spread at illustrative wood speeds: the fire stayed in its room."
                in features.report(hand_run("wood", 0), building))
        for fire_bad in ({"rooms": [{"room": "R101", "floor": "F1", "ignite": 0}]}, {"material": "wood"},
                         {"material": "wood", "rooms": "R101"}, {"material": "wood", "rooms": [None, 3, {"room": "A"}]},
                         {"material": "**", "rooms": [{"room": "R101", "floor": "F1", "ignite": 0}]}):
            assert "Fire spread" not in features.report(dict(plain, fire=dict(plain["fire"], **fire_bad)), building), fire_bad

        # a live run, asked for by its scenario id (what the frontend sends today)
        fake = {"version": "run/v0", "id": "smoke-report-run", "buildingId": "example-office",
                "scenarioId": "smoke-report-scenario", "seed": 1, "frameInterval": 0.5, "floors": ["F1", "F2"],
                "agents": [], "frames": [], "smoke": [], "fire": run["fire"], "events": [],
                "metrics": {k: m[k] for k in ("agents", "evacuated", "trapped", "t50", "t90", "t100", "exitCounts", "doors")}}
        path = ROOT / "data" / "runs" / "smoke-report-run.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(fake, separators=(",", ":")), encoding="utf-8")
        try:
            expected = features.report(fake, building)
            assert f"{label(doors[0])}: peak queue" in expected, expected
            for ref in ("smoke-report-scenario", "smoke-report-run"):
                r = client.post("/api/report", json={"runId": ref})
                assert r.status_code == 200 and r.json() == {"markdown": expected}, (ref, r.text[:300])
        finally:
            path.unlink(missing_ok=True)


def check_report_ai(client):
    """The AI path with a stubbed model (no network): its headline and fixes are used and the card
    ends "Written by Gemini"; a headline with a number not in the facts, a fix with an invented
    statistic and a fix for an unknown id fall back to the template; long fixes are cut to 25
    words; the endpoint caches AI cards until ?refresh=1; a private building never reaches the
    model."""
    from backend.app.store import PRIVATE_DIR
    from backend.llm import client as llm
    from backend.llm import features

    batch, _, building = _examples()
    top = batch["top"][:3]
    assert len(top) >= 2, "the example batch needs at least two top entries"
    first, second = top[0], top[1]
    n = len(batch["runs"])
    facts = features._facts(batch, building)
    template_headline = facts["headline"]
    spots, names = facts["spots"], features._Names(building)
    answers: list = []
    prompts: list = []

    def fake_complete(prompt, **kwargs):
        prompts.append((prompt, kwargs))
        return answers.pop(0) if answers else None

    def fix_lines(md: str) -> list[str]:
        return [ln.split("**Fix:**", 1)[1].strip() for ln in md.splitlines() if "**Fix:**" in ln]

    good = {"headline": f"{spots[0]['label']} is the worst spot across {n} simulated fires",
            "fixes": [{"id": first["id"], "fix": "Add a second stair route from the corridor so arrivals split between two doors."},
                      {"id": "NOT-A-SPOT", "fix": "Nothing."},
                      {"id": second["id"], "fix": "A wider door cuts the queue by 93.7%."}]}
    runs_dir = ROOT / "data" / "runs"
    saved = runs_dir / "batch-smoke-report-cache.json"  # the example batch under its own id
    cache = runs_dir / "report-smoke-report-cache.md"
    private_building = PRIVATE_DIR / "smoke-report-private.json"
    private_batch = runs_dir / "batch-smoke-report-private.json"
    real = llm.complete
    llm.complete = fake_complete
    cache.unlink(missing_ok=True)
    try:
        with env(LLM_PROVIDER="gemini"), redirect_stderr(io.StringIO()):
            answers.append(json.loads(json.dumps(good)))
            md, ai = features.report_card(batch, building)
            assert ai and md.rstrip().endswith("*Written by Gemini*"), md[-300:]
            assert f"**{good['headline']}**" in md, md
            fixes = fix_lines(md)  # the model's fix for spot 1; templates for the invented statistic and the missing one
            expected = ["Add a second stair route from the corridor so arrivals split between two doors."]
            expected += [features.TEMPLATE_FIX.get(str(item.get("kind")), features.TEMPLATE_FIX["door"]) for item in top[1:]]
            assert fixes == expected, (fixes, expected)
            assert "93.7" not in md and "NOT-A-SPOT" not in md and all(s["why"] in md for s in spots), md
            assert not names.mentions_id(md), md
            prompt, kwargs = prompts[-1]
            assert kwargs["schema"] == features.REPORT_SCHEMA and kwargs["timeout"] >= 30, kwargs
            assert spots[0]["why"] in prompt and building["name"] in prompt and "heatmaps" not in prompt, prompt[:500]
            # the model gets each spot's name and the id only as the key its fix comes back under
            assert spots[0]["label"] in prompt and not names.mentions_id(
                "\n".join(ln for ln in prompt.splitlines() if not ln.lstrip().startswith('"id":'))), prompt[:800]

            answers.append({"headline": "Stair B queues 9,871 people", "fixes": [{"id": first["id"], "fix": "Widen the stair door to 1.2 m."}]})
            md, ai = features.report_card(batch, building)
            assert ai and "9,871" not in md and f"**{template_headline}**" in md, md
            assert fix_lines(md)[0] == "Widen the stair door to 1.2 m.", md

            answers.append({"headline": "", "fixes": [{"id": first["id"], "fix": " ".join(["wide"] * 40)}]})
            md, ai = features.report_card(batch, building)
            fix = next(ln for ln in md.splitlines() if "wide wide" in ln).split("**Fix:**")[1].split()
            assert ai and len(fix) == features.FIX_WORDS and fix[-1] == "wide...", fix

            # a door id in the model's headline or fix (an IFC code to a judge) is dropped like an invented number
            answers.append({"headline": f"Door {first['id']} queues the most people",
                            "fixes": [{"id": first["id"], "fix": f"Widen {first['id']} to 1.2 m."}]})
            md, ai = features.report_card(batch, building)
            assert not ai and f"**{template_headline}**" in md and "Widen" not in md, md
            assert not names.mentions_id(md), md

            answers.append(["not", "an", "object"])
            md, ai = features.report_card(batch, building)
            assert not ai and md.rstrip().endswith("*Template summary (AI unavailable)*"), md[-200:]

            asked = len(prompts)
            md, ai = features.report_card(batch, building, allow_llm=False)
            assert not ai and len(prompts) == asked and "private building" in md, md[-200:]

            # the endpoint caches an AI card until ?refresh=1; a failed refresh keeps the cached one
            runs_dir.mkdir(parents=True, exist_ok=True)
            saved.write_text(json.dumps(dict(batch, id="smoke-report-cache")), encoding="utf-8")
            answers.append(json.loads(json.dumps(good)))
            r = client.post("/api/report", json={"batchId": "smoke-report-cache"})
            assert r.status_code == 200 and "Written by Gemini" in r.json()["markdown"], r.text[-300:]
            assert cache.is_file() and cache.read_text(encoding="utf-8") == r.json()["markdown"]
            asked = len(prompts)
            again = client.post("/api/report", json={"batchId": "smoke-report-cache"})
            assert again.json() == r.json() and len(prompts) == asked, "the cached card was not served"
            fresh = client.post("/api/report?refresh=1", json={"batchId": "smoke-report-cache"})  # the model says nothing now
            assert len(prompts) == asked + 1 and "Template summary" in fresh.json()["markdown"], fresh.text[-300:]
            assert cache.read_text(encoding="utf-8") == r.json()["markdown"]

            # a building in data/private never reaches the model, through the endpoint either
            PRIVATE_DIR.mkdir(parents=True, exist_ok=True)
            private_building.write_text(json.dumps(dict(building, id="smoke-report-private")), encoding="utf-8")
            private_batch.write_text(json.dumps(dict(batch, id="smoke-report-private", buildingId="smoke-report-private")), encoding="utf-8")
            asked = len(prompts)
            r = client.post("/api/report", json={"batchId": "smoke-report-private"})
            assert r.status_code == 200 and len(prompts) == asked, r.text[:300]
            assert "private building, not sent to AI" in r.json()["markdown"], r.text[-300:]
    finally:
        llm.complete = real
        for p in (saved, cache, private_building, private_batch, runs_dir / "report-smoke-report-private.md"):
            p.unlink(missing_ok=True)


def check_door_names():
    """D23, one source of truth for door names: the card calls a door, an exit or a stair door what
    fire.batch.door_label calls it (the example building and the two public ones, every door), words it from its
    rooms only where D's name would show the door's id (an exit with no name), swaps the id forms that batches
    saved before D23 carry, and numbers twin doors; checked on a made-up floor too, one branch of the rule each."""
    from backend.llm import features
    from fire.batch import door_label

    def load(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    shown = 0
    for path in (ROOT / "contracts" / "building.example.json", ROOT / "data" / "buildings" / "office.json",
                 ROOT / "data" / "buildings" / "clinic.json"):
        if not path.is_file():
            continue
        b = load(path)
        names = features._Names(b)
        for f in b["floors"]:
            for d in f["doors"]:
                kind, text = door_label(b, f["id"], d["id"])
                assert names.door_kind(f["id"], d["id"]) == kind, (path.name, d["id"])
                label = names.label(kind, f["id"], d["id"])[0]
                assert not names.mentions_id(label), (path.name, label)  # an IFC code means nothing to a judge
                if names.mentions_id(text):  # D's `Exit DIlsnHU`, an exit with no name: the card words it from its rooms
                    assert label != text, (path.name, text)
                else:
                    assert label == text, (path.name, text, label)  # D's name, word for word
                shown += 1
    example = features._Names(load(ROOT / "contracts" / "building.example.json"))
    assert example.label("door", "F1", "DL1")[0] == "Door between Lobby and Corridor 1"  # no room ids: no twin
    assert example.title("door", "F1", "DL1") == "the door between Lobby and Corridor 1 on F1"
    assert example.readable("Door DL1 (Lobby to Corridor 1): 23 people queued", "F1") == \
        "Door between Lobby and Corridor 1: 23 people queued"

    def room(rid, name=None, kind="office", **more):
        return {"id": rid, "type": kind, **({"name": name} if name else {}), **more}

    def door(did, *connects, x=0.0):
        return {"id": did, "connects": list(connects), "a": [x, 0.0], "b": [x + 1.0, 0.0], "width": 1.0}

    floor = {"id": "F1",
             "rooms": [room("A1", "Lab"), room("A2", "Lab"), room("B1", "Store"), room("B2", "Shop"),
                       room("C1", "Hall", "corridor"), room("S1", "Stair", "stair", group="SA")],
             "doors": [door("D1", "B1", "C1"), door("X1", "A1", "C1"), door("X2", "A1", "C1", x=5.0),
                       door("X3", "A2", "C1", x=9.0), door("D2", "B2"), door("D3"),
                       door("E1", "C1", "outside"), door("E2", "B1", "outside"), door("E3", "B2", "outside"),
                       door("DS1", "C1", "S1")],
             "exits": [{"id": "E1", "name": "Main entrance", "door": "E1"},
                       {"id": "E3", "name": "M_Single-Flush:0915 x 2134mm:184259", "door": "E3"}],
             "stairs": [{"id": "S1", "group": "SA", "room": "S1"}]}
    building = {"id": "t", "name": "T", "floors": [floor]}
    names = features._Names(building)
    label = {d["id"]: names.label(names.door_kind("F1", d["id"]), "F1", d["id"])[0] for d in floor["doors"]}
    assert label == {
        "D1": "Door between Store and Hall",  # no other door joins these two names: no room ids
        "X1": "Door between Lab (A1) and Hall (C1), 1 of 2",  # two doors join the same rooms, told apart by position
        "X2": "Door between Lab (A1) and Hall (C1), 2 of 2",
        "X3": "Door between Lab (A2) and Hall (C1)",  # another room of the same name: room ids, no number
        "D2": "Door from Shop",  # D's word for a door of one known room (the card used to say "Door of")
        "D3": "Door",  # joins no known room: D says `Door D3`, the card never shows the id
        "E1": "Exit Main entrance",
        "E2": "Exit from Store (B1)",  # D says `Exit E2`: the exit has no name
        "E3": "Exit from Shop (B2)",  # an IFC door family string is no name (D drops it too)
        "DS1": "Stair SA door"}, label
    assert names.title("door", "F1", "X1") == "the door between Lab (A1) and Hall (C1) on F1, 1 of 2"
    assert names.readable("Door D1 (Store to Hall): 5 queued; Exit E2 blocked; DS1 busy", "F1") == \
        "Door between Store and Hall: 5 queued; Exit from Store (B1) blocked; Stair SA door busy"
    batch = {"version": "batch/v0", "id": "t-batch", "buildingId": "t", "runs": [], "top": [
        {"kind": "door", "id": "X1", "floor": "F1", "why": "Door X1 (Lab to Hall): 9 people queued at peak; 40 person-seconds."},
        {"kind": "exit", "id": "E2", "floor": "F1", "why": "Exit E2: 4 people queued at peak; 12 person-seconds."},
        {"kind": "door", "id": "D1", "floor": "F1", "why": "Door between Store and Hall: 3 people queued; 8 person-seconds."}]}
    with env(LLM_PROVIDER="off"), redirect_stderr(io.StringIO()):
        md = features.report(batch, building)
        assert "1. **Door between Lab (A1) and Hall (C1), 1 of 2** · F1\n   - Door between Lab (A1) and Hall (C1), 1 of 2: 9 people" in md, md
        assert "2. **Exit from Store (B1)** · F1\n   - Exit from Store (B1): 4 people" in md, md
        assert "3. **Door between Store and Hall** · F1\n   - Door between Store and Hall: 3 people" in md, md
        assert "the door between Lab (A1) and Hall (C1) on F1, 1 of 2" in md and not names.mentions_id(md), md

        # D's code failing on a malformed building (a floor with no id) never fails the card: the rooms word the door
        broken = {"id": "t", "name": "T", "floors": [{"rooms": [], "doors": []}, floor]}
        worded = features._Names(broken)
        assert worded.label("door", "F1", "D1")[0] == "Door between Store (B1) and Hall (C1)"
        assert worded.label("door", "F1", "D2")[0] == "Door from Shop (B2)"
        assert "Door between Store (B1) and Hall (C1)" in features.report(dict(batch, top=batch["top"][2:]), broken)
    return shown


def check_decide():
    """decide / decide_batch for the sim (C7, C8), on sim/brain.py's obs shape: offline every entry is
    None; a stubbed model's decisions are checked against each obs (a known target, an action that
    fits `current`), extra or unknown entries are dropped, a failing model gives Nones and never an
    exception, and sim.brain.LLMBrain accepts the decisions without falling back."""
    import backend.llm as llm_pkg
    from backend.llm import client as llm
    from backend.llm import features
    from sim.brain import LLMBrain, RuleBrain

    obs = json.loads(json.dumps(features.SAMPLE_OBS))
    with env(LLM_PROVIDER="off"), redirect_stderr(io.StringIO()):
        assert features.decide(obs[0]) is None and llm_pkg.decide(obs[0]) is None
        assert features.decide_batch(obs) == [None, None, None] and features.decide_batch([]) == []

    calls: list = []
    answer: dict = {}

    def fake_complete(prompt, **kwargs):
        calls.append((prompt, kwargs))
        if isinstance(answer.get("raise"), BaseException):
            raise answer["raise"]
        return answer.get("value")

    real = llm.complete
    llm.complete = fake_complete
    try:
        with env(LLM_PROVIDER="gemini"), redirect_stderr(io.StringIO()):
            answer["value"] = {"decisions": [
                {"i": 0, "action": "reroute", "target": "E2", "reason": "E1 has a queue"},  # no current: go
                {"i": 1, "action": "go", "target": "SB", "reason": "Stair A is smoky and queued"},  # switch: reroute
                {"i": 1, "action": "wait", "target": "SA", "reason": "a second answer for i=1"},
                {"i": 2, "action": "go", "target": "E1", "reason": "E1 is not an option here"},
                {"i": 9, "action": "go", "target": "E1", "reason": "no such observation"},
            ]}
            out = features.decide_batch(obs)
            assert out == [{"target": "E2", "action": "go", "reason": "E1 has a queue"},
                           {"target": "SB", "action": "reroute", "reason": "Stair A is smoky and queued"},
                           None], out
            prompt, kwargs = calls[-1]
            assert len(calls) == 1 and kwargs["schema"] == features.DECISION_SCHEMA and kwargs["thinking"] == "minimal"
            assert kwargs["timeout"] >= 30 and all(f'"id":"{o["id"]}"' in prompt for x in obs for o in x["options"]), prompt

            answer["value"] = {"decisions": [{"i": 0, "action": "wait", "target": "SB", "reason": "keep going"}]}
            assert features.decide(obs[1]) == {"target": "SA", "action": "wait", "reason": "keep going"}
            assert llm_pkg.decide(obs[1]) == {"target": "SA", "action": "wait", "reason": "keep going"}

            answer["value"] = {"decisions": [{"i": 0, "action": "reroute", "target": "SB", "reason": "Stair B is clear"}]}
            decision = LLMBrain(RuleBrain(1), features.decide, timeout=5.0).decide(obs[1])
            assert decision == {"target": "SB", "action": "reroute", "reason": "Stair B is clear"}, decision

            for value in (None, {"decisions": "junk"}, {"no": "decisions"}, "text"):
                answer["value"] = value
                assert features.decide_batch(obs) == [None, None, None], value
            answer["raise"] = RuntimeError("smoke: the model call blew up")
            assert features.decide_batch(obs) == [None, None, None] and features.decide(obs[0]) is None
            answer.pop("raise")
            asked = len(calls)
            assert features.decide_batch([None, {}, {"options": []}, {"options": [{"name": "no id"}]}]) == [None] * 4
            assert len(calls) == asked, "malformed observations reached the model"
    finally:
        llm.complete = real


def check_llm_client():
    """The client's model chain and retry rules on a stubbed Gemini call (no network). The chain is
    GEMINI_MODEL, GEMINI_FALLBACK_MODEL (default gemini-2.5-flash), gemini-3.6-flash, gemini-3.7-flash,
    gemini-3.1-flash-lite. A 429 (a used-up quota or a rate limit) or a 503 goes straight to the next
    model, and the log names the model that answered; 500 and 502 retry the same model; a timeout, a
    404 or invalid JSON go to the next model; a busy model is skipped for the cooldown (a used-up
    quota for an hour); 401 stops at once; total failure is None and one stderr line, which never
    shows the key; missing keys and an unknown provider give None."""
    from backend.llm import client as llm

    class FakeAPIError(Exception):
        def __init__(self, code: int, message: str = "fake", details: dict | None = None):
            super().__init__(f"{code} {message}")
            self.code, self.details = code, details

    quota = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": [  # as measured Sat 3 AM
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
         "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier", "quotaValue": "20"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "84216s"}]}}

    script: list = []
    models: list = []

    def fake_once(model, prompt, image, image_mime, schema, timeout, thinking):
        models.append(model)
        step = script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step

    def ask(steps, cooled=False, **kwargs):
        script[:] = steps
        models.clear()
        if not cooled:
            llm._cooldown.clear()
        log = io.StringIO()
        with redirect_stderr(log):
            out = llm.complete("ping", timeout=30, **kwargs)
        assert not script, f"unused steps: {script}"
        return out, list(models), log.getvalue()

    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
    ok = '{"ok": true}'
    tail = ["gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.1-flash-lite"]
    with env(GEMINI_MODEL="primary-model", GEMINI_FALLBACK_MODEL=None):
        assert llm._models() == ["primary-model", "gemini-2.5-flash"] + tail, llm._models()
    with env(GEMINI_MODEL=None, GEMINI_FALLBACK_MODEL=None):
        assert llm._models() == ["gemini-2.5-flash"] + tail, llm._models()
    with env(GEMINI_MODEL="a, b", GEMINI_FALLBACK_MODEL="gemini-3.7-flash,c,a"):
        assert llm._models() == ["a", "b", "gemini-3.7-flash", "c", "gemini-3.6-flash", "gemini-3.1-flash-lite"], llm._models()

    p, f, t = ["primary-model"], ["fallback-model"], ["tail-model"]
    real_once, real_backoff, real_tail = llm._gemini_once, llm.BACKOFF, llm.CHAIN_TAIL
    llm._gemini_once, llm.BACKOFF, llm.CHAIN_TAIL = fake_once, 0.0, ("tail-model",)  # a short chain for the scripts
    try:
        with env(LLM_PROVIDER="gemini", GEMINI_API_KEY=os.environ.get("GEMINI_API_KEY") or "smoke-not-a-key",
                 GEMINI_MODEL="primary-model", GEMINI_FALLBACK_MODEL="fallback-model"):
            out, seen, log = ask([ok], schema=schema)
            assert (out, seen) == ({"ok": True}, p) and "answered by primary-model" in log, (out, seen, log)
            # 503 (busy) and 429 (quota or rate limit): the next model at once, no retry
            out, seen, log = ask([FakeAPIError(503), ok], schema=schema)
            assert (out, seen) == ({"ok": True}, p + f) and "answered by fallback-model" in log and "503" in log, (out, seen, log)
            assert ask([ok], cooled=True, schema=schema)[:2] == ({"ok": True}, f), "the busy model was not skipped"
            assert ask([FakeAPIError(429), ok], schema=schema)[:2] == ({"ok": True}, p + f)
            # down the chain: the primary's daily quota is used up (it rests for an hour, not 2
            # minutes), the fallback is busy, the tail answers
            out, seen, log = ask([FakeAPIError(429, "RESOURCE_EXHAUSTED", quota), FakeAPIError(503), ok], schema=schema)
            assert (out, seen) == ({"ok": True}, p + f + t) and "answered by tail-model" in log, (out, seen, log)
            assert "skipped for 3600 s" in log and log.count("\n") == 1, log
            assert llm._cooldown["primary-model"] - time.monotonic() > 3500, llm._cooldown
            # 500 and 502 retry the same model, then the next one
            assert ask([FakeAPIError(500), FakeAPIError(502), ok], schema=schema)[:2] == ({"ok": True}, p * 3)
            assert ask([FakeAPIError(500)] * 3 + [ok], schema=schema)[:2] == ({"ok": True}, p * 3 + f)
            assert ask([TimeoutError("read timed out"), ok], schema=schema)[:2] == ({"ok": True}, p + f)
            assert ask([FakeAPIError(404), ok], schema=schema)[:2] == ({"ok": True}, p + f)
            assert ask(["not json", ok], schema=schema)[:2] == ({"ok": True}, p + f)
            assert ask(['["a list"]'], schema={"type": "array"})[:2] == (["a list"], p)
            assert ask(["plain text"])[:2] == ("plain text", p)
            out, seen, log = ask([FakeAPIError(401)], schema=schema)
            assert (out, seen) == (None, p) and log.count("\n") == 1, (out, seen, log)
            out, seen, log = ask([FakeAPIError(404), FakeAPIError(503), FakeAPIError(429)], schema=schema)
            assert (out, seen) == (None, p + f + t) and log.count("\n") == 1 and "no answer" in log, (out, seen, log)
            # a caller's own chain for one call (the tracer's first pass)
            out, seen, log = ask([FakeAPIError(503), ok], schema=schema, models=["x-model", "y-model", "x-model"])
            assert (out, seen) == ({"ok": True}, ["x-model", "y-model"]) and "answered by y-model" in log, (out, seen, log)
        with env(LLM_PROVIDER="gemini", GEMINI_API_KEY=os.environ.get("GEMINI_API_KEY") or "smoke-not-a-key",
                 GEMINI_MODEL="primary-model", GEMINI_FALLBACK_MODEL="fallback-model, second-model,primary-model"):
            out, seen, log = ask([TimeoutError("slow"), FakeAPIError(404), ok], schema=schema)
            assert (out, seen) == ({"ok": True}, p + f + ["second-model"]), (out, seen, log)
        llm.CHAIN_TAIL = ()
        with env(LLM_PROVIDER="gemini", GEMINI_API_KEY="smoke-secret-key-0123456789", GEMINI_MODEL="m1", GEMINI_FALLBACK_MODEL="m1"):
            out, seen, log = ask([FakeAPIError(400, "bad request for smoke-secret-key-0123456789")], schema=schema)
            assert out is None and seen == ["m1"] and "smoke-secret-key" not in log and "***" in log, log
        models.clear()
        with redirect_stderr(io.StringIO()) as log:
            with env(LLM_PROVIDER="gemini", GEMINI_API_KEY=None):
                assert llm.complete("ping") is None
            with env(LLM_PROVIDER="claude", APP_ANTHROPIC_API_KEY=None):
                assert llm.complete("ping") is None
            with env(LLM_PROVIDER="nonsense"):
                assert llm.complete("ping") is None
        assert "GEMINI_API_KEY is not set" in log.getvalue() and "APP_ANTHROPIC_API_KEY" in log.getvalue()
        assert not models, "a model was called without a key"
    finally:
        llm._gemini_once, llm.BACKOFF, llm.CHAIN_TAIL = real_once, real_backoff, real_tail
        llm._cooldown.clear()


def check_llm_live():
    """Optional, behind --live-llm: the real model (GEMINI_API_KEY from .env): a JSON ping, the example
    batch's card written by the model, and decisions for the three sample agents."""
    from backend.llm import client as llm
    from backend.llm import features

    batch, _, building = _examples()
    name = llm.provider() if llm.provider() != "off" else "gemini"
    with env(LLM_PROVIDER=name):
        t0 = time.time()
        ping = llm.complete('Reply with {"ok": true}.', schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
                            thinking="minimal")
        assert ping == {"ok": True}, f"ping answered {ping!r}"
        t1 = time.time()
        md, ai = features.report_card(batch, building)
        assert ai and md.rstrip().endswith(f"*{features.WRITTEN_BY.get(name, 'Written by AI')}*"), md[-300:]
        t2 = time.time()
        decisions = features.decide_batch(features.SAMPLE_OBS)
        assert any(decisions), decisions
        t3 = time.time()
    print(md)
    print(f"OK  live LLM ({name}, last model {llm.last_model}): ping {t1 - t0:.1f} s, report {t2 - t1:.1f} s, "
          f"decide_batch {t3 - t2:.1f} s ({sum(d is not None for d in decisions)}/3 decided)")


def check_llm(client):
    """A7's checks in one call (all offline: LLM_PROVIDER=off or a stubbed model)."""
    t0 = time.time()
    check_report(client)
    check_report_run(client)
    check_report_ai(client)
    doors = check_door_names()
    check_decide()
    check_llm_client()
    print(f"OK  llm: report card (template, AI path stubbed, cache, private building), run card, "
          f"door names (D's, {doors} doors), decide_batch, client retries and fallback, {time.time() - t0:.1f} s")


def _png(width: int, height: int) -> bytes:
    """A blank white RGB PNG (no Pillow needed)."""
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    rows = b"".join(b"\x00" + b"\xff" * (3 * width) for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def check_trace(client):
    """A8, offline: sanitize_floor on a canned junk answer (a bow-tie, a 2-point polygon, type
    kitchenette, coordinates 1500, a closet under 1 m2, a point that is not a number) keeps only
    valid rooms with enum types, in floor meters (y up) snapped to 0.25 m, and at most 60; POST
    /api/trace/propose returns 503 "AI first pass unavailable" with LLM_PROVIDER=off, 413 above
    8 MB, 415 for a non-image, 422 for bad hints, and the sanitized floor from a stubbed model."""
    from shapely.geometry import Polygon

    from backend.llm import client as llm
    from backend.llm import features

    # 800 x 400 px at 0.05 m/px: a 40 x 20 m floor. On the model's 0-1000 grid x = 25 m per 1000
    # (1000 = 40 m) and y runs down from the top edge (y = 0 is 20 m north of the origin).
    hints = {"metersPerPixel": 0.05, "width": 800, "height": 400, "name": "Smoke floor", "level": 1}
    junk = {"rooms": [
        {"name": "Office 1", "type": "office", "polygon": [[101, 102], [299, 99], [302, 498], [99, 501]]},
        {"name": "Bow tie", "type": "office", "polygon": [[400, 100], [600, 500], [600, 100], [400, 500]]},
        {"name": "Two points", "type": "lab", "polygon": [[100, 600], [300, 900]]},
        {"name": "Kitchenette", "type": "kitchenette", "polygon": [[600, 600], [900, 600], [900, 900], [600, 900]]},
        {"name": "Off the edge", "type": "office", "polygon": [[700, 100], [1500, 100], [1500, 400], [700, 400]]},
        {"name": "Closet", "type": "storage", "polygon": [[950, 950], [960, 950], [960, 960], [950, 960]]},
        {"name": 7, "type": None, "polygon": [[10, 10], ["x", 20], [30, 30]]},
        "not a room",
        {"type": " Corridors ", "polygon": [[0, 500], [500, 500], [1000, 500], [1000, 600], [0, 600], [0, 500]]},
    ]}
    expected = [
        {"id": "AI1", "name": "Office 1", "type": "office", "polygon": [[4, 18], [12, 18], [12, 10], [4, 10]]},
        {"id": "AI2", "name": "Kitchenette", "type": "other", "polygon": [[24, 8], [36, 8], [36, 2], [24, 2]]},
        {"id": "AI3", "name": "Corridor", "type": "corridor", "polygon": [[0, 10], [40, 10], [40, 8], [0, 8]]},
    ]
    floor = features.sanitize_floor(json.loads(json.dumps(junk)), hints)
    assert floor["rooms"] == expected, json.dumps(floor["rooms"])
    assert {k: floor[k] for k in ("id", "level", "elevation", "height", "doors")} == \
        {"id": "F2", "level": 1, "elevation": 3.5, "height": 3.5, "doors": []}, floor
    for room in floor["rooms"]:  # what the tracer and the normalizer rely on
        poly = Polygon(room["polygon"])
        assert poly.is_valid and poly.area >= 1 and room["type"] in features.ROOM_TYPES, room
        assert all(v % 0.25 == 0 and 0 <= x <= 40 and 0 <= y <= 20 for x, y in room["polygon"] for v in (x, y)), room

    # at most 60 rooms; 2 x 2 m each, the first 60 kept in the model's order
    many = {"rooms": [{"name": f"R{i}", "type": "office",
                       "polygon": [[50 * (i % 20), 100 * (i // 20)], [50 * (i % 20) + 50, 100 * (i // 20)],
                                   [50 * (i % 20) + 50, 100 * (i // 20) + 100], [50 * (i % 20), 100 * (i // 20) + 100]]}
                      for i in range(80)]}
    rooms = features.sanitize_floor(many, hints)["rooms"]
    assert len(rooms) == 60 and rooms[-1]["id"] == "AI60" and rooms[-1]["name"] == "R59", (len(rooms), rooms[-1])
    for raw in (None, [], {"rooms": "x"}, {"rooms": [None, 3]}):
        assert features.sanitize_floor(raw, hints)["rooms"] == [], raw
    for bad in ({}, {"metersPerPixel": 0, "width": 800, "height": 400}, dict(hints, width=12.5), "x"):
        try:
            features.sanitize_floor(junk, bad)
        except ValueError:
            continue
        raise AssertionError(f"bad hints accepted: {bad}")

    # the endpoint
    png = _png(800, 400)
    form = {"hints": json.dumps(hints)}

    def post(data=png, fields=None, name="plan.png"):
        return client.post("/api/trace/propose", files={"image": (name, data, "image/png")},
                           data=form if fields is None else fields)

    log = io.StringIO()
    with env(LLM_PROVIDER="off"), redirect_stderr(log):
        r = post()
        assert r.status_code == 503 and r.json() == {"detail": "AI first pass unavailable"}, (r.status_code, r.text)
        assert features.propose_plan(png, hints) is None
        assert post(png[:16] + b"\0" * (8 * 2**20)).status_code == 413
        assert post(b"GIF89a not a plan", name="plan.gif").status_code == 415
        for fields in ({"hints": "not json"}, {"hints": "{}"}, {"hints": json.dumps(dict(hints, width=1600, height=800))}, {}):
            r = post(fields=fields)
            assert r.status_code == 422, (fields, r.status_code, r.text[:200])
        assert client.post("/api/trace/propose", data=form).status_code == 422  # no image
    assert "LLM_PROVIDER=off" in log.getvalue(), log.getvalue()

    calls: list = []
    answer: dict = {}

    def fake_complete(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return answer.get("value")

    # B's tidy_floor (buildings/tidy.py, task B10) runs after sanitize_floor once main has it; here it
    # is absent first (sys.modules None: the import fails), then a stand-in, then one that raises
    import types

    tidy_calls: list = []

    def fake_tidy(fl, grid=0.25, min_area=1.0, min_width=0.6):
        tidy_calls.append(json.loads(json.dumps(fl)))
        if fl.get("rooms") and fl["rooms"][0]["name"] == "boom":
            raise RuntimeError("smoke: tidy_floor failed on purpose")
        return dict(fl, rooms=fl["rooms"][:1]), ["AI2: dropped (smoke)"]

    stand_in = types.ModuleType("buildings.tidy")
    stand_in.tidy_floor = fake_tidy
    real_tidy = sys.modules.get("buildings.tidy")
    real = llm.complete
    llm.complete = fake_complete
    sys.modules["buildings.tidy"] = None
    try:
        with env(LLM_PROVIDER="gemini", GEMINI_MODEL="primary-model", GEMINI_FALLBACK_MODEL=None), redirect_stderr(io.StringIO()):
            answer["value"] = json.loads(json.dumps(junk))
            r = post()
            assert r.status_code == 200 and r.json()["floor"]["rooms"] == expected, r.text[:500]
            assert r.json()["floor"]["doors"] == [] and r.json()["floor"]["id"] == "F2", r.text[:300]
            assert r.json()["model"] is None or isinstance(r.json()["model"], str), r.text[:300]
            assert r.json()["notes"] == [] and isinstance(r.json()["seconds"], (int, float)), r.text[:300]
            prompt, kwargs = calls[-1]
            assert kwargs["image"] == png and kwargs["image_mime"] == "image/png", {k: kwargs[k] for k in ("image_mime",)}
            assert kwargs["schema"] == features.PROPOSE_SCHEMA and kwargs["timeout"] >= 60, kwargs["timeout"]
            # Gemini 2.x last: far worse at room geometry (IoU 0.39 against 1.00 for gemini-3.6-flash)
            assert kwargs["models"] == ["primary-model", "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.1-flash-lite",
                                        "gemini-2.5-flash"], kwargs["models"]
            assert "0-1000" in prompt and "800 x 400" in prompt and "stair" in prompt and "doors" in prompt, prompt
            for value in (None, "text", ["a list"]):
                answer["value"] = value
                r = post()
                assert r.status_code == 503 and r.json()["detail"] == "AI first pass unavailable", (value, r.text)
            answer["value"] = {"rooms": [junk["rooms"][1]]}  # only junk: a floor with no rooms, not an error
            r = post()
            assert r.status_code == 200 and r.json()["floor"]["rooms"] == [], r.text[:300]

            sys.modules["buildings.tidy"] = stand_in
            answer["value"] = json.loads(json.dumps(junk))
            r = post()
            assert r.status_code == 200 and r.json()["floor"]["rooms"] == expected[:1], r.text[:300]
            assert r.json()["notes"] == ["AI2: dropped (smoke)"] and tidy_calls[-1]["rooms"] == expected, r.text[:300]
            answer["value"] = {"rooms": [dict(junk["rooms"][0], name="boom")]}
            r = post()
            assert r.status_code == 200 and [x["name"] for x in r.json()["floor"]["rooms"]] == ["boom"], r.text[:300]
            assert r.json()["notes"] == [], r.text[:300]
    finally:
        llm.complete = real
        if real_tidy is None:
            sys.modules.pop("buildings.tidy", None)
        else:
            sys.modules["buildings.tidy"] = real_tidy

    # once B's real tidy_floor is here: it keeps the sanitized rooms valid and on the grid
    try:
        from buildings.tidy import tidy_floor
    except ImportError:
        tidy_floor = None
    if tidy_floor is not None:
        tidied, _ = tidy_floor(features.sanitize_floor(json.loads(json.dumps(junk)), hints))
        assert {x["id"] for x in tidied["rooms"]} <= {x["id"] for x in expected} and tidied["doors"] == [], tidied
        for room in tidied["rooms"]:
            assert Polygon(room["polygon"]).is_valid and all(v % 0.25 == 0 for p in room["polygon"] for v in p), room
    print(f"OK  trace: sanitize ({len(expected)} of {len(junk['rooms'])} junk rooms kept, 60-room cap), "
          f"propose 503 offline, 413, 415, 422, stubbed model, tidy_floor {'checked' if tidy_floor else 'not on this branch yet'}")


def post_run(client, scenario: dict) -> str:
    r = client.post("/api/runs", json=scenario)
    assert r.status_code == 200, r.text
    return r.json()["runId"]


def wait_run(client, run_id: str, timeout: float = POLL_TIMEOUT) -> dict:
    """GET /api/runs/ID until the job is done: the run/v0 itself (no status key), or {"status": "error", ...}."""
    t0 = time.time()
    while True:
        r = client.get(f"/api/runs/{run_id}")
        assert r.status_code == 200, r.text
        out = r.json()
        if out.get("status") != "running":
            return out
        assert time.time() - t0 < timeout, f"run not done after {timeout} s"
        time.sleep(1)


def check_run(client) -> str:
    """A real run: example scenario, maxTime 60. Returns the summary line. Two twins (A11) go in beside it and run in
    the pool at the same time: the same scenario with fire.material "wood", whose run says so, and with "steel", which
    the fire model refuses, so its job ends in an error that names the valid materials."""
    from backend.app import jobs

    assert client.get("/api/runs/doesnotexist").status_code == 404
    r = client.post("/api/runs", json={"buildingId": "no-such-building"})
    assert r.status_code == 404, r.text

    scenario = json.loads((ROOT / "contracts" / "scenario.example.json").read_text(encoding="utf-8"))
    scenario["maxTime"] = 60
    t0 = time.time()
    run_id = post_run(client, scenario)
    wood_id = post_run(client, dict(scenario, fire=dict(scenario["fire"], material="wood")))
    steel_id = post_run(client, dict(scenario, fire=dict(scenario["fire"], material="steel")))
    run = wait_run(client, run_id)
    if run.get("status") == "error":
        raise AssertionError(f"run failed: {run.get('error')}\n{run.get('traceback', '')}")
    elapsed = time.time() - t0

    assert run["id"] == run_id and run["version"].startswith("run/"), run.get("version")
    assert run["frames"], "run has no frames"
    doors = run["metrics"]["doors"]
    assert doors, "metrics.doors is empty"
    saved_run = ROOT / "data" / "runs" / f"{run_id}.json"
    assert saved_run.is_file(), f"{saved_run} was not written"
    assert run["fire"]["material"] == scenario["fire"]["material"] == "drywall", run["fire"]  # the example's own material

    twin = wait_run(client, wood_id)
    assert twin.get("status") != "error", f"wood run failed: {twin.get('error')}\n{twin.get('traceback', '')}"
    assert twin["fire"]["material"] == "wood" and twin["fire"]["rooms"][0]["room"] == scenario["fire"]["room"], twin["fire"]
    (ROOT / "data" / "runs" / f"{wood_id}.json").unlink(missing_ok=True)  # the twin's file is test noise
    refused = wait_run(client, steel_id)
    assert refused.get("status") == "error" and "concrete, drywall, wood" in refused.get("error", ""), refused

    # after a "restart" (no futures in memory) the run is read back from disk
    jobs._futures.clear()
    r = client.get(f"/api/runs/{run_id}")
    assert r.status_code == 200 and r.json()["id"] == run_id

    m = run["metrics"]
    return (
        f"OK  run {run_id}: {len(run['frames'])} frames, {len(doors)} doors, "
        f"evacuated {m.get('evacuated')}/{m.get('agents')}, trapped {m.get('trapped')}, "
        f"t90 {m.get('t90')}, t100 {m.get('t100')}, {saved_run.stat().st_size / 1e6:.1f} MB, "
        f"{elapsed:.1f} s through the API; twins: wood run says wood, steel refused ({refused['error'].split(':', 1)[0]})"
    )


def main(argv: list[str] | None = None) -> int:
    # Imported here, not at module level: pool workers re-import this module under spawn
    # (as __mp_main__) and should not pay for fastapi each time.
    from fastapi.testclient import TestClient

    from backend.app.main import app

    live = "--live-llm" in (sys.argv[1:] if argv is None else argv)
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        if live:  # only the LLM checks, then the real model
            check_llm(client)
            check_llm_live()
            return 0
        check_buildings(client)
        check_from_plan(client)
        check_batch(client)
        check_llm(client)
        check_trace(client)
        summary = check_run(client)
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
