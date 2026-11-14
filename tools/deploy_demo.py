"""One-command static deploy of the demo to Netlify (task A5). Nothing is published unless you say --deploy.

    python tools/deploy_demo.py                       check the demo data, build frontend/dist, print the deploy command
    python tools/deploy_demo.py --deploy              also a Netlify DRAFT deploy: a preview URL to open on a phone
    python tools/deploy_demo.py --deploy --prod       the same, to the live site

What it does, in order:
    1. privacy: tools/check_all.py's check (nothing UMass in data/buildings or frontend/public/demo, nothing
       tracked in data/private) and every building in the demo folder must be public (spec 12);
    2. npm ci when node_modules is missing or stale, then `npm run build` in frontend/ (its prebuild step
       runs sync-demo.mjs and check-demo.mjs, so the index and every file it lists are verified);
    3. the same privacy scan on frontend/dist/demo, which is what the site serves, and the payload sizes;
    4. with --deploy: `npx netlify-cli deploy --dir frontend/dist` (add --prod for the live site).

Deploying needs the Netlify CLI to be logged in: set NETLIFY_AUTH_TOKEN, or run `npx netlify-cli login` once; and
a site: --site SITE_ID (or NETLIFY_SITE_ID), or `npx netlify-cli link` once. Without --deploy none of that is needed.
--site-url https://NAME.netlify.app puts the site's address into this local build (the About overlay's QR code);
a build made by Netlify itself takes it from $URL when VITE_SITE_URL is empty (see netlify.toml).
Continuous deploys need none of this: the Netlify site linked to the GitHub repo rebuilds on every push to main.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FRONTEND = ROOT / "frontend"
DEMO = FRONTEND / "public" / "demo"
DIST = FRONTEND / "dist"
MB = 1_000_000


def say(message: str = "") -> None:
    print(message, flush=True)


def fail(message: str, code: int = 1):
    print(f"ERROR: {message}", file=sys.stderr, flush=True)
    raise SystemExit(code)


def run(cmd: list[str], cwd: Path = ROOT, env: dict | None = None) -> None:
    say("$ " + " ".join(cmd))
    code = subprocess.run(cmd, cwd=cwd, env=env).returncode
    if code != 0:
        fail(f"{' '.join(cmd[:3])} failed (exit {code})")


def scan_demo(folder: Path) -> list[str]:
    """Problems in a folder of demo files: a private building, or any file that mentions UMass."""
    problems = []
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        name = path.relative_to(folder).as_posix()
        if "umass" in name.lower():
            problems.append(f"{name}: named after UMass")
        if path.suffix.lower() not in (".json", ".md", ".txt"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "umass" in text.lower():
            problems.append(f"{name}: mentions UMass")
        if path.suffix == ".json" and path.name.startswith("building"):
            try:
                if json.loads(text).get("private") is True:
                    problems.append(f"{name}: a private building")
            except (ValueError, AttributeError):
                problems.append(f"{name}: not valid JSON")
    return problems


def payload(folder: Path) -> tuple[int, int, list[tuple[str, int]]]:
    """(bytes, gzipped bytes, the biggest files) of the demo folder: the gzip size is what travels over the wire."""
    raw = gz = 0
    sizes = []
    for path in folder.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            raw += len(data)
            gz += len(gzip.compress(data, 6))
            sizes.append((path.relative_to(folder).as_posix(), len(data)))
    return raw, gz, sorted(sizes, key=lambda x: -x[1])[:5]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--deploy", action="store_true", help="really publish: a Netlify draft deploy (a preview URL)")
    p.add_argument("--prod", action="store_true", help="with --deploy: publish to the live site instead of a draft")
    p.add_argument("--site", metavar="SITE_ID", help="Netlify site id or name (else NETLIFY_SITE_ID, else the linked site)")
    p.add_argument("--site-url", metavar="URL", help="the site's https URL, baked into this build for the QR code")
    p.add_argument("--skip-build", action="store_true", help="use the existing frontend/dist")
    args = p.parse_args(argv)
    if args.prod and not args.deploy:
        p.error("--prod only makes sense with --deploy")
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    # 1. privacy, before anything is built
    from tools.check_all import check_privacy, npm_deps_stale

    result = check_privacy()
    if result.status != "PASS":
        fail(f"privacy check {result.status}: {result.detail}\n{result.output}")
    problems = scan_demo(DEMO)
    if problems:
        fail("frontend/public/demo is not safe to publish:\n  " + "\n  ".join(problems))
    say("privacy: ok (frontend/public/demo)")

    # 2. build
    npm = shutil.which("npm")
    if npm is None:
        fail("npm is not on PATH (Node 22 is needed)")
    if not args.skip_build:
        env = dict(os.environ)
        if args.site_url:
            env["VITE_SITE_URL"] = args.site_url
        if npm_deps_stale():
            run([npm, "ci", "--no-audit", "--no-fund"], FRONTEND, env)
        run([npm, "run", "build"], FRONTEND, env)
    if not (DIST / "index.html").is_file():
        fail("frontend/dist/index.html is missing: build first (drop --skip-build)")

    # 3. what the site would serve
    problems = scan_demo(DIST / "demo")
    if problems:
        fail("frontend/dist/demo is not safe to publish:\n  " + "\n  ".join(problems))
    raw, gz, biggest = payload(DIST / "demo")
    say("privacy: ok (frontend/dist/demo)")
    say(f"demo payload: {raw / MB:.1f} MB on disk, {gz / MB:.1f} MB gzipped (Netlify compresses JSON on the wire)")
    for name, size in biggest:
        say(f"  {size / MB:6.2f} MB  {name}")

    # 4. deploy
    cmd = ["npx", "--yes", "netlify-cli", "deploy", "--dir", "frontend/dist"]
    if args.prod:
        cmd.append("--prod")
    if args.site:
        cmd += ["--site", args.site]
    if not args.deploy:
        say("\nBuilt, nothing published. To publish a draft (preview URL), then the live site:")
        say("  " + " ".join(cmd))
        say("  " + " ".join(cmd + ([] if args.prod else ["--prod"])))
        say("or: python tools/deploy_demo.py --deploy [--prod] [--site SITE_ID] [--site-url https://NAME.netlify.app]")
        return 0
    npx = shutil.which("npx")
    if npx is None:
        fail("npx is not on PATH")
    run([npx, *cmd[1:]], ROOT)
    say(f"\nDeployed{'' if args.prod else ' as a draft'}. Open the URL above on a phone: the building loads, a click "
        "loads the nearest run, no console errors.")
    say("Then: curl -sI <that URL>/demo/index.json   (the first line should say 200)")
    if not args.prod:
        say("Happy with it? Run the same command with --prod to publish it to the live site.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
