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

## Current phase: SPIKE A (time-boxed, ~2 h) - DONE 2026-09-25

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



## Phase: WEEK 2 — Ingest + conflicts + overdue (Sep 27 – Oct 3)

**Goal:** a forwarded document becomes a vault entry with a cited source and a confidence score, and the agent explains collisions like a person would. **Done when:** `ingest_document` on the three fixture documents produces three correct vault files without hand-editing; a low-confidence date triggers a question, not a guess; `list_due` shows overdue items first; `find_conflicts` explains *why* a clash matters, not just that it exists. Tests pass, ruff clean, FRICTION.md updated.

### Stack additions (decided)

- **Amazon Bedrock** for extraction, via `boto3`. Region **ap-southeast-1**. Model: **Claude Haiku on Bedrock** (or Amazon Nova Lite if Haiku isn't enabled in the account — check first, tell me which). Use the Converse API with a JSON schema for the response; never parse freeform prose.
- **pdfplumber** for PDF → text. Plain `.txt`/`.eml` read directly. No OCR — scanned PDFs are out of scope; return a clear "no text layer" error.
- Credentials from the standard AWS profile chain. Never in the repo. Add `.aws/` and `*.pem` to `.gitignore` if not already.
- **Cost guard:** cap extraction input at 12k characters (head + tail of the document); log token usage per call to stderr.

### New tool

`ingest_document(path_or_text: str, hint: str | None = None) -> IngestResult`

1. Load text (PDF via pdfplumber, else read as text). Fail clearly on binary/no-text.
2. Bedrock call with a fixed system prompt: extract `title`, `due` (ISO), optional `window_start`, `kind` (hard/soft with one-line reason), `source` (quote the exact phrase the date came from), `confidence` (0–1), `ambiguities` (list).
3. **If** `confidence < 0.7` **or** `ambiguities` **non-empty → do not write.** Return a `needs_confirmation` result with the candidate entry and one specific question ("The letter says 'within 30 days of receipt' — when did you receive it?"). The client (Claude Desktop today, Alexa+ later) asks the user; a second call with `hint` answers it.
4. Otherwise write via the existing `add_deadline` path (duplicate refusal still applies). Return the path and the extracted entry.

### Changes to existing tools

- `list_due`: return **overdue open items first**, each flagged `overdue: true` with `days_overdue`. Then upcoming as today. Remove the `TODO(week 2)`.
- `find_conflicts`: explanation must say why it matters — hard-vs-soft ("the visa is immovable; move the school payment"), both-hard ("two immovable deadlines 3 days apart — start the earlier one now"), and mention `window_start` when present. Keep it to one or two sentences. Still deterministic — no LLM call here.

### Fixtures (all synthetic — invent names, dates, institutions)

`tests/fixtures/`

1. `immigration-letter.pdf` — clear due date, `hard`. Expect confidence ≥ 0.9.
2. `school-fee-email.txt` — due date stated, `soft`, plus an early-payment discount date (a second, optional deadline — extract only the real one, mention the discount in notes).
3. `insurance-renewal-ambiguous.pdf` — "renew within 30 days of receipt", no absolute date. Expect `needs_confirmation`. Generate the PDFs in a script (`scripts/make_fixtures.py`) so they're reproducible; commit the script and the outputs.

### Tests

- Unit tests for text loading, overdue ordering, conflict explanations (no network).
- Bedrock calls behind a thin interface with a **recorded-response fake** for CI; one opt-in live test (`DUEBOOK_LIVE=1`) that hits Bedrock on fixture 1 only.

### Order of work, one commit each

1. Overdue in `list_due` + tests.
2. Conflict explanations upgrade + tests.
3. Fixture generator + the three fixtures.
4. Text loader (PDF/txt) + tests.
5. Bedrock client + schema + fake; confirm the model is enabled and log which one you used.
6. `ingest_document` happy path (fixtures 1, 2) + tests.
7. `needs_confirmation` path (fixture 3) + `hint` round-trip + tests.
8. README: new tool, AWS setup in five lines, cost note.

### Not in this phase

Alexa+ Agent Skill or simulated surface · Strands/AgentCore · reminders/escalation · email/calendar integration · OCR · any UI · deployment. If you finish early, **stop and tell me** — I'll pull the Alexa+ transport check forward rather than have you start it unscoped.

### Friction to watch for (log them)

Bedrock model access approval flow · region availability of the chosen model · Converse API JSON-schema quirks · pdfplumber on real-world PDFs.

