# Team workflow and usage limits

## Workstreams (one plan per person)

| WS | Owns | Best fit |
| --- | --- | --- |
| A | Repo, contracts, FastAPI, LLM wrapper and features, demo, Devpost | Backend + LLM APIs (likely Tony) |
| B | IFC to building.json; tracing editor later | Python + geometry |
| C | JuPedSim crowd sim: floors, stairs, exit choice, fire coupling, waiting | Python + algorithms |
| D | Fire and smoke grid, metrics, batch runs, ranking, calibration | NumPy |
| E | 3D replay, dashboard, heatmaps, split screen, report panel | React / Three.js |

**How it holds together:**
- **Handoffs:** B joins E around H+10 (tracing editor, IFC rendering); D pairs with C at H+12 for fire coupling; A helps whoever is behind after H+14.
- **No waiting:** everyone codes against the contracts and example files. E renders the example run; C builds on `fire/stub.py`; A's API returns the example run until C lands.
- **Branches:** `ws-a` … `ws-e`, each in its own git worktree. Small PRs to `main` (A owns it); rebase at every sync point.

## Sync points (hours from kickoff)

| Hour | Everyone can see |
| --- | --- |
| H+3 | Example building → sim → run.json → 3D replay |
| H+8 | Real IFC building end to end (then sleep in shifts) |
| H+14 | Smoke slows people and closes routes; metrics on screen |
| H+20 | Risk map, report card, split screen |
| H+26 | Feature freeze; demo runs precomputed |
| H+30 | Devpost, video, slides |
| H+34 | Submit |

## Usage limits (official facts, checked Nov 13, 2026)

- **Limits:** Pro and Max have a five-hour session limit and a weekly limit, shared across claude.ai, Claude Code and Claude Desktop. Max has 5x Pro's usage every five hours and every week. The team's capacity is about 9 Pro-sized allowances, and Tony's account holds about 56% of it.
- **Weekly reset time:** fixed per account (Settings > Usage). Check it now, since a heavy weekend can use up a Pro weekly allowance.
- **Backstop:** Pro users can enable usage credits (pay at API rates) with a monthly spend limit.
- **Subagent cost:** every subagent sends its own requests against the same usage.
- **Model choice:** Sonnet costs less than Opus; medium effort reduces tokens.
- **Clearing context:** `/clear` costs nothing; `/compact` on a long session is itself a big request. `/status` and `/usage` show what's left.
- **Max monthly API credits ($100):** they don't cover interactive Claude Code. They do cover `claude -p` and the Agent SDK when run with an API key from the linked Console organization. They could pay for the app's own Claude calls or scripted boilerplate jobs.

## Strategy

- **Tony (Max):** subagent-driven runs for setup-heavy tasks: the API skeleton, multi-floor sim, fire grid and frontend skeleton, each in its own worktree, plus overnight jobs. Agree in chat which tasks he takes; owners pull, test and continue.
- **Pro accounts:**
  - Use Sonnet at medium effort, one plan task per session, then `/clear`.
  - Use `superpowers:executing-plans` instead of subagent-driven development, with no parallel subagents.
  - Avoid side chats on claude.ai.
- **When a limit hits:** switch to hands-on work (testing, data downloads, UI polish, Devpost) or hand the task to Tony. Spend the current five-hour window before sleeping, since it resets overnight.

## Gotchas

- If `ANTHROPIC_API_KEY` is set in the shell, Claude Code bills that key instead of the plan. Name the app's key `APP_ANTHROPIC_API_KEY` and load it from `.env` inside the app only.
- `contracts/run.example.json` is about 245 KB. Tell Claude to inspect it with `jq` instead of reading it whole.
- Claude Code applies a project's `.claude/settings.json` allow rules only after you accept the workspace trust dialog for that folder. Open Claude Code in the repo once before leaving anything running.

## Permissions for overnight runs (proposal, not applied)

Options from the Claude Code docs:
- **Modes:** `acceptEdits` auto-approves file edits and common filesystem commands. `auto` runs without routine prompts, with a background safety classifier, if available. Use `bypassPermissions` only in isolated containers or VMs.
- **Allow and deny rules:** use the `Tool(specifier)` syntax with `*` wildcards; deny rules win in every mode.
- **Unattended runs:** the user-level setting `permissions.denyInsteadOfPrompting` denies calls that would wait on a prompt, so an unattended session keeps working.
- **Fewer prompts:** `/fewer-permission-prompts` adds common read-only calls to the allowlist.

Draft `.claude/settings.json` to review before using:

```json
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "permissions": {
    "defaultMode": "acceptEdits",
    "allow": [
      "Bash(python *)", "Bash(python3 *)", "Bash(pip install *)", "Bash(uvicorn *)",
      "Bash(node *)", "Bash(npm *)", "Bash(npx *)", "Bash(jq *)",
      "Bash(curl *localhost*)",
      "Bash(git status*)", "Bash(git diff*)", "Bash(git log*)", "Bash(git add *)",
      "Bash(git commit *)", "Bash(git switch *)", "Bash(git fetch*)", "Bash(git pull*)",
      "Bash(git worktree *)", "Bash(git push origin ws-*)", "Bash(git push -u origin ws-*)"
    ],
    "deny": [
      "Read(./.env)", "Read(./.env.*)", "Bash(sudo *)", "Bash(rm -rf *)",
      "Bash(git reset --hard*)", "Bash(git push * main*)", "Bash(git push * --force*)", "Bash(git push * -f*)"
    ]
  }
}
```

## Set up before sleeping

- **GitHub:** repo created, invites accepted, `gh auth login` on every laptop.
- **Claude Code:** logged in with each person's plan, Superpowers installed (copy Tony's steps), trust dialog accepted in the repo.
- **Installs:** `pip install -r requirements.txt` (JuPedSim pulls in PySide6 and VTK); Node 20+; check that `ifcopenshell` imports.
- **Keys:** a Gemini key from Google AI Studio in `.env`. If the team picks Claude for the app, a Console API key from Tony's org as `APP_ANTHROPIC_API_KEY`.
- **Data:** download the IFC candidates (NIBS clinic and office, VTT office) into `data/raw/`.
- **MCP (optional):** a browser-automation MCP on Tony's account so Claude can screenshot the frontend. Pro accounts should skip MCPs.
- **Overnight runs:** keep the laptop awake and online (e.g., `caffeinate` on macOS) while sessions run.
