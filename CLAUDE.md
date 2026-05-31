# CLAUDE.md

**Read `AGENTS.md` — it is the source of truth for this project** (architecture map,
run/restart instructions, conventions, and critical gotchas, plus the multi-agent
workflow rules shared with Cursor and Grok Build).

Quick reminders:
- After editing code, restart the launchd service: `launchctl kickstart -k gui/$UID/com.cole.ambientizer` and hard-refresh the browser.
- Commit + push to `main` at logical stopping points (auto, no need to ask).
- Never commit secrets / `output/` / `saved_jobs/`.
