"""Run every check the team gates merges on: one PASS, FAIL or SKIP line each.

    python tools/check_all.py [name ...]

Without names all of these run, in this order:

    buildings  python -m buildings.smoke_test
    sim        python -m sim.smoke_test
    fire       python -m fire.smoke_test
    backend    python -m backend.smoke_test
    tracer     python tools/check_tracer.py
    frontend   npm run build, in frontend/
    privacy    nothing UMass in data/buildings or frontend/public/demo, nothing tracked in data/private

SKIP means the piece has not landed (its script, or frontend/package.json, is missing); it is not
a failure. A failed check prints the tail of its output. The last line is ALL OK, or FAILED and
the names of the failed checks. Exit code: 0 all good, 1 something failed, 2 an unknown name.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
TIMEOUT = 900  # seconds per command, then the check fails and its processes are killed
TAIL = 25  # lines of output shown for a failed check
PUBLIC = ["data/buildings", "frontend/public/demo"]  # no UMass-derived data here (spec §12)


class Result(NamedTuple):
    status: str  # PASS, FAIL or SKIP
    detail: str = ""
    output: str = ""  # its tail is printed when the check failed


def child_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(ROOT), env.get("PYTHONPATH")]))
    env["PYTHONUTF8"] = "1"  # piped output stays UTF-8 on Windows
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("LLM_PROVIDER", "off")  # a check never calls a model (.env does not override this)
    return env


def kill_tree(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":  # /T takes the process pool's workers and node's children too
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        proc.kill()


def run(cmd: list[str], cwd: Path = ROOT) -> tuple[int | None, str]:
    """(exit code, stdout and stderr together). The exit code is None after a timeout."""
    group = {} if os.name == "nt" else {"start_new_session": True}  # POSIX: killpg needs a group
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=child_env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", **group,
    )
    try:
        out, _ = proc.communicate(timeout=TIMEOUT)
        return proc.returncode, out
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        try:
            out, _ = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            out = ""
        return None, out
    except BaseException:  # Ctrl+C: do not leave the check running
        kill_tree(proc)
        raise


def from_exit(code: int | None, out: str) -> Result:
    if code == 0:
        return Result("PASS")
    return Result("FAIL", f"timed out after {TIMEOUT} s" if code is None else f"exit {code}", out)


def smoke(module: str):
    script = module.replace(".", "/") + ".py"

    def check() -> Result:
        if not (ROOT / script).is_file():
            return Result("SKIP", f"{script} has not landed")
        return from_exit(*run([sys.executable, "-m", module]))

    return check


def check_tracer() -> Result:
    script = "tools/check_tracer.py"
    if not (ROOT / script).is_file():
        return Result("SKIP", f"{script} has not landed")
    return from_exit(*run([sys.executable, script]))


def npm_deps_stale() -> bool:
    """node_modules missing, or older than package.json or package-lock.json (a merge may have
    brought new dependencies)."""
    stamp = FRONTEND / "node_modules" / ".package-lock.json"
    if not stamp.is_file():
        return True
    manifests = [p for p in (FRONTEND / "package.json", FRONTEND / "package-lock.json") if p.is_file()]
    return any(p.stat().st_mtime > stamp.stat().st_mtime for p in manifests)


def check_frontend() -> Result:
    if not (FRONTEND / "package.json").is_file():
        return Result("SKIP", "frontend/package.json has not landed")
    npm = shutil.which("npm")  # npm.cmd on Windows
    if npm is None:
        return Result("FAIL", "npm is not on PATH")
    log, note = "", ""
    if npm_deps_stale():  # ci leaves package-lock.json alone; install is for a repo without one
        install = "ci" if (FRONTEND / "package-lock.json").is_file() else "install"
        code, log = run([npm, install, "--no-audit", "--no-fund"], FRONTEND)
        if code != 0:
            note = f" (npm {install} failed first)"
    res = from_exit(*run([npm, "run", "build"], FRONTEND))
    if res.status == "PASS":
        return res
    return Result("FAIL", res.detail + note, log + res.output)


def check_privacy() -> Result:
    git = shutil.which("git")
    if git is None:
        return Result("FAIL", "git is not on PATH")
    found: list[str] = []
    # --untracked: also catch a file nobody has `git add`ed yet, such as a fresh public export
    code, out = run([git, "grep", "-il", "--untracked", "umass", "--", *PUBLIC])
    if code == 0:
        found += [f"{ln}: mentions UMass" for ln in out.splitlines() if ln.strip()]
    elif code != 1:  # 1 means no match
        return Result("FAIL", f"git grep failed (exit {code})", out)
    code, out = run([git, "ls-files", "--cached", "--others", "--exclude-standard", "--", *PUBLIC])
    if code != 0:
        return Result("FAIL", f"git ls-files failed (exit {code})", out)
    found += [f"{ln}: named after UMass" for ln in out.splitlines() if "umass" in ln.lower()]
    code, out = run([git, "ls-files", "--", "data/private"])
    if code != 0:
        return Result("FAIL", f"git ls-files failed (exit {code})", out)
    found += [f"{ln}: tracked, but data/private stays out of git" for ln in out.splitlines() if ln.strip()]
    if found:
        return Result("FAIL", f"{len(found)} problem(s)", "\n".join(found))
    return Result("PASS")


CHECKS = {
    "buildings": smoke("buildings.smoke_test"),
    "sim": smoke("sim.smoke_test"),
    "fire": smoke("fire.smoke_test"),
    "backend": smoke("backend.smoke_test"),
    "tracer": check_tracer,
    "frontend": check_frontend,
    "privacy": check_privacy,
}


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):  # a Windows console may not encode every character
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    if any(a in ("-h", "--help") for a in argv):
        print(__doc__)
        return 0
    names = [a.lower() for a in argv] or list(CHECKS)
    unknown = [n for n in names if n not in CHECKS]
    if unknown:
        print(f"unknown check: {' '.join(unknown)} (choose from: {' '.join(CHECKS)})", file=sys.stderr)
        return 2

    failed = []
    for name in CHECKS:  # always in the order above
        if name not in names:
            continue
        t0 = time.time()
        try:
            res = CHECKS[name]()
        except Exception:
            res = Result("FAIL", "check crashed", traceback.format_exc())
        if res.status == "SKIP":
            print(f"SKIP  {name:<10}{res.detail}", flush=True)
            continue
        line = f"{res.status}  {name:<10}{time.time() - t0:6.1f} s"
        print(line + (f"  {res.detail}" if res.detail else ""), flush=True)
        if res.status == "FAIL":
            failed.append(name)
            for ln in res.output.strip().splitlines()[-TAIL:]:
                print(f"    | {ln}")
            print(flush=True)

    if failed:
        print("FAILED: " + " ".join(failed))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
