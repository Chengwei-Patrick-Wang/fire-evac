#!/usr/bin/env bash
# Overnight runner: works through one workstream plan unattended, one task per agent run.
#
#   tools/overnight/run.sh <claude|codex> <a|b|c|d|e> [hours=7]
#   tools/overnight/run.sh <claude|codex> <a|b|c|d|e> check    # verify setup, then exit
#
# Each round it:
#   1. saves leftover changes as a wip commit,
#   2. merges origin/main into your branch (skips if that conflicts),
#   3. runs your agent on the first unchecked task in your plan,
#   4. pushes your branch if anything was committed.
# A round with no commit (usage limit, crash, stuck) waits 20 minutes and retries.
# Stops after [hours], when the plan has no unchecked boxes, or after 15 empty rounds.
#
# Before you sleep: plug in and disable sleep (macOS: put `caffeinate -dims` in front of the
# command; Windows: Settings > System > Power > sleep when plugged in = Never). Run it in
# Terminal (macOS/Linux) or Git Bash (Windows). Progress log: debug/overnight-<letter>.log
set -u

TOOL="${1:?usage: tools/overnight/run.sh <claude|codex> <a-e> [hours]}"
WS="${2:?usage: tools/overnight/run.sh <claude|codex> <a-e> [hours]}"
MODE="${3:-7}"
if [ "$MODE" = check ]; then CHECK=1; HOURS=0; else CHECK=0; HOURS="$MODE"; fi
BRANCH="ws-$WS"
TASK_TIMEOUT=5400   # seconds before a single agent run is killed
WAIT_EMPTY=1200     # seconds to wait after a round with no commit
MAX_EMPTY=15

cd "$(git rev-parse --show-toplevel)" || exit 1
mkdir -p debug
LOG="debug/overnight-$WS.log"
log() { echo "$(date '+%a %H:%M:%S') $*" | tee -a "$LOG"; }

case "$TOOL" in claude|codex) ;; *) echo "tool must be claude or codex"; exit 1 ;; esac
command -v "$TOOL" >/dev/null || { echo "'$TOOL' is not on PATH"; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "Commit or stash your changes first."; exit 1; }

# Every python call the agent makes uses the repo venv.
if [ -d .venv/bin ]; then export PATH="$PWD/.venv/bin:$PATH"
elif [ -d .venv/Scripts ]; then export PATH="$PWD/.venv/Scripts:$PATH"; fi

git fetch -q origin
if git show-ref -q "refs/heads/$BRANCH"; then git switch -q "$BRANCH"
elif git show-ref -q "refs/remotes/origin/$BRANCH"; then git switch -q -c "$BRANCH" "origin/$BRANCH"
else git switch -q -c "$BRANCH" origin/main; fi

save_wip() {
  if [ -n "$(git status --porcelain)" ]; then
    git add -A && git commit -q -m "wip: save partial work" && log "saved leftover changes as a wip commit"
  fi
}

sync() {
  save_wip
  git fetch -q origin
  if git show-ref -q "refs/remotes/origin/$BRANCH"; then
    git merge -q --no-edit "origin/$BRANCH" >/dev/null 2>&1 \
      || { git merge --abort >/dev/null 2>&1; log "origin/$BRANCH did not merge cleanly; skipped"; }
  fi
  git merge -q --no-edit origin/main >/dev/null 2>&1 \
    || { git merge --abort >/dev/null 2>&1; log "main did not merge cleanly; continuing on $BRANCH"; }
}

run_agent() {
  if [ "$TOOL" = claude ]; then
    claude -p "$1" --model sonnet --permission-mode acceptEdits --max-turns 200 \
      --allowedTools "Read" "Edit" "Write" "Glob" "Grep" "TodoWrite" \
        "Bash(python:*)" "Bash(pip:*)" "Bash(npm:*)" "Bash(npx:*)" "Bash(node:*)" \
        "Bash(git add:*)" "Bash(git commit:*)" "Bash(git status:*)" "Bash(git diff:*)" "Bash(git log:*)" \
        "Bash(ls:*)" "Bash(cat:*)" "Bash(head:*)" "Bash(tail:*)" "Bash(wc:*)" "Bash(jq:*)" "Bash(mkdir:*)" "Bash(curl:*)" \
      --disallowedTools "Bash(git push:*)" "Bash(git pull:*)" "Bash(git reset:*)" "Bash(git checkout:*)" "Bash(rm -rf:*)"
  else
    codex exec --full-auto -c sandbox_workspace_write.network_access=true "$1"
  fi
}

with_timeout() {
  "$@" >>"$LOG" 2>&1 &
  local pid=$!
  ( sleep "$TASK_TIMEOUT"; kill "$pid" 2>/dev/null ) &
  local watcher=$!
  wait "$pid"; local rc=$?
  kill "$watcher" 2>/dev/null
  return $rc
}

sync

if [ "$CHECK" = 1 ]; then
  ok=1
  pass() { echo "  PASS  $*"; }
  fail() { echo "  FAIL  $*"; ok=0; }
  echo "Checking the overnight setup for $BRANCH with $TOOL:"
  if [ -n "$(git config user.email)" ]; then pass "git identity: $(git config user.email)"
  else fail "git identity missing: git config --global user.name 'You'; git config --global user.email you@example.com"; fi
  if git push -q -u origin "$BRANCH" 2>/dev/null; then pass "can push $BRANCH to GitHub"
  else fail "cannot push to GitHub: accept the repo invite, then log in (gh auth login, or the Git credential manager)"; fi
  if python -c "import jupedsim, shapely, numpy, fastapi" 2>/dev/null; then pass "Python venv has the requirements ($(python --version 2>&1))"
  else fail "Python: python -m venv .venv, activate it, pip install -r requirements.txt"; fi
  case "$WS" in a|e)
    if command -v node >/dev/null && [ "$(node -p 'process.versions.node.split(".")[0]')" -ge 20 ]; then pass "Node $(node --version)"
    else fail "Node 20 or newer is needed for the frontend"; fi ;;
  esac
  PLAN=$(ls docs/superpowers/plans/*-ws-"$WS"-*.md 2>/dev/null | head -1)
  if [ -n "$PLAN" ]; then pass "plan: $PLAN"; else echo "  WAIT  plan for $BRANCH is not on main yet (the real run waits for it)"; fi
  out="debug/overnight-$WS-check.txt"
  if [ "$TOOL" = claude ]; then claude -p "Reply with the single word READY." --model sonnet --max-turns 1 >"$out" 2>&1 &
  else codex exec "Reply with the single word READY." >"$out" 2>&1 & fi
  pid=$!; ( sleep 180; kill "$pid" 2>/dev/null ) & watcher=$!
  wait "$pid"; kill "$watcher" 2>/dev/null
  if grep -qi ready "$out"; then pass "$TOOL answers in headless mode (logged in, no prompts)"
  else fail "$TOOL did not answer (see $out): log in, and run '$TOOL' here once interactively to accept the folder prompt"; fi
  if [ "$ok" = 1 ]; then echo "All set. Start the real run: tools/overnight/run.sh $TOOL $WS"
  else echo "Fix the FAIL lines, then run the check again."; fi
  exit $((1 - ok))
fi

PLAN=""
for _ in $(seq 1 30); do
  PLAN=$(ls docs/superpowers/plans/*-ws-"$WS"-*.md 2>/dev/null | head -1)
  [ -n "$PLAN" ] && break
  log "no plan for $BRANCH on main yet; checking again in 2 min"
  sleep 120; sync
done
[ -n "$PLAN" ] || { log "still no plan after an hour; stopping"; exit 1; }

PROMPT="You are running unattended overnight on branch $BRANCH. Nobody will answer questions, so make reasonable calls and keep going.
Read AGENTS.md, then docs/overnight/STATUS.md (integration notes from the lead, newest first), then your plan $PLAN.
Pick the first task (a '### Task' heading) in $PLAN that still has an unchecked '- [ ]' box and no 'BLOCKED:' line under its heading. Do that one task completely, following AGENTS.md: stay in your workstream's folders, no TDD, and run your package's smoke test (or the task's verification step) before committing.
Tick that task's boxes in $PLAN as you finish its steps.
When the task is done, commit your work (git add, then git commit) with a short conventional commit message.
If something outside your folders blocks the task, add a line 'BLOCKED: <reason>' under the task heading, commit, and stop.
Do not push, pull, merge, rebase, reset or switch branches: the runner script does all git syncing."

END=$(( $(date +%s) + HOURS * 3600 ))
empty=0
log "runner started: $TOOL on $BRANCH, plan $PLAN, for $HOURS h"
while [ "$(date +%s)" -lt "$END" ]; do
  sync
  if ! grep -q -- '- \[ \]' "$PLAN"; then
    log "plan has no unchecked boxes left; done"; git push -q -u origin "$BRANCH"; exit 0
  fi
  before=$(git rev-parse HEAD)
  log "agent run starting"
  with_timeout run_agent "$PROMPT"; rc=$?
  save_wip
  if [ "$(git rev-parse HEAD)" != "$before" ]; then
    empty=0
    if git push -q -u origin "$BRANCH" 2>>"$LOG"; then log "pushed: $(git log --oneline -1)"; else log "push failed (will retry next round)"; fi
    sleep 30
  else
    empty=$((empty + 1))
    log "no commit this round (exit $rc, $empty in a row): usage limit, crash or stuck; waiting $((WAIT_EMPTY / 60)) min"
    [ "$empty" -ge "$MAX_EMPTY" ] && { log "stopping after $MAX_EMPTY empty rounds"; exit 1; }
    sleep "$WAIT_EMPTY"
  fi
done
log "time is up; stopping"
git push -q -u origin "$BRANCH"
