# CLAUDE.md — Life-Admin Deadlines Agent (working name TBD)

> Copy this file to the root of the new repo as `CLAUDE.md`. It scopes Claude Code to **Spike A only**. Later weeks get their own sections appended — do not build ahead of the current section.

## What this is
An MCP server that owns a household's hard deadlines (visa, school, lease, insurance) as a markdown vault. Built for the Amazon Developer Hackathon 2026, Alexa+ track. Public repo, MIT licence, real name.

## Stack (decided — don't relitigate)
- **Python 3.12**, `uv` for env/deps. (Reason: Strands Agents SDK and Bedrock tooling are Python-first; they arrive in Week 3.)
- **MCP Python SDK**, **Streamable HTTP** transport, spec **2025-11-25**. Not stdio — the hackathon requires Streamable HTTP.
- **Vault = markdown files with YAML front-matter** in `vault/`. Files are the database. No SQLite, no Postgres, no in-memory state that would be lost on restart.
- Tests: `pytest`. Formatting: `ruff`.
- No web UI, no auth, no cloud deployment in this phase.

## Vault format
One file per deadline: `vault/<slug>.md`
```yaml
---
title: Visa renewal — Parent A
due: 2026-11-15
window_start: 2026-11-10        # optional; for deadlines with a window
kind: hard | soft
source: "Immigration department letter, 2026-08-30"   # where the date came from
confidence: 0.95                # 0–1; how sure we are of the date
status: open | done | cancelled
---
Free-text notes.
```
Seed `vault/` with **5 sanitised examples**. Two must fall in the same 7-day window, one `hard` and one `soft`, so `find_conflicts` has something to find. No real personal data.

## Current phase: SPIKE A (time-boxed, ~2 h)
**Goal:** prove that the server can answer a vault query and remember an added deadline across two separate client sessions.

Build exactly three tools:
1. `list_due(window_days: int = 30)` → deadlines with `status: open` and `due` within the window, sorted by `due`. Return title, due, kind, source, confidence.
2. `add_deadline(title, due, kind, source, confidence=0.8)` → writes a new vault file, returns its path. Slug from title + due. Refuse duplicates (same title + due).
3. `find_conflicts(window_days: int = 7)` → pairs of open deadlines within `window_days` of each other, each with a one-sentence plain-English explanation ("Visa renewal (hard, 15 Nov) collides with school fee (soft, 12 Nov).").

Also: a `README.md` with the exact commands to run the server and connect it from Claude Desktop **and** from MCP Inspector.

**Done when:** in Claude Desktop, session 1 adds a deadline; the client is fully quit; session 2 lists it with its source. Record the time-to-first-tool-call in `FRICTION.md`.

## Not in this phase (do not build, do not scaffold)
Document ingestion · Bedrock · Strands/AgentCore · Alexa+ Agent Skill or simulated web surface · reminders/escalation · calendar sync · any UI · deployment.

## Working rules
- Small commits, one tool per commit.
- Every "ugh" — a doc gap, a transport surprise, a confusing error — goes into `FRICTION.md` as: task attempted · steps · expected vs actual · severity · workaround · suggestion. This file is part of the submission.
- Ask before adding a dependency beyond the MCP SDK, pyyaml, pytest, ruff.
- Never put real names, addresses or document numbers in `vault/` or tests.

## Week 2 notes (backlog — not in scope for Spike A)
- `list_due` should return overdue open items first, flagged as overdue (Spike A only returns today → today + window).
