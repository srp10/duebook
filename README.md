# Duebook

An MCP server that keeps a household's hard deadlines (visa, school, lease, insurance) in a
markdown vault. Built for the Amazon Developer Hackathon 2026, Alexa+ track.

- **Transport:** Streamable HTTP, MCP spec 2025-11-25 (`mcp==1.30.0`)
- **Storage:** `vault/*.md`. One file per deadline, YAML front-matter. The files are the
  database; nothing lives in memory between requests.

## Tools

| Tool | What it does |
|---|---|
| `list_due(window_days=30)` | Overdue open deadlines first, then the next N days; includes source and confidence. |
| `add_deadline(title, due, kind, source, confidence=0.8)` | Writes `vault/<title-slug>-<due>.md`, returns its path. Refuses a duplicate title + due. `due` is `YYYY-MM-DD`; `kind` is `hard` or `soft`. |
| `find_conflicts(window_days=7)` | Pairs of open deadlines due within N days of each other, each explaining why the clash matters. |

| `ingest_document(path_or_text, hint=None)` | Extract a document deadline through Bedrock; save or ask for clarification. |

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (`brew install uv`). It fetches Python 3.12 itself.
- Node.js 18+ (for `npx`). Needed only for the MCP Inspector and for the Claude Desktop bridge.

## Run the server

```bash
uv sync
uv run duebook
```

The server listens on **`http://127.0.0.1:8000/mcp`**. Leave it running in its own terminal.

Options (environment variables):

| Variable | Default | |
|---|---|---|
| `DUEBOOK_VAULT` | `<repo>/vault` | Vault directory. Point it at a copy to experiment without touching the seed data. |
| `DUEBOOK_PORT` | `8000` | |
| `DUEBOOK_HOST` | `127.0.0.1` | Keep it on localhost; there is no auth in this phase. |

Run the tests and linter:

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

## Connect from MCP Inspector

With the server running, in a second terminal:

```bash
npx @modelcontextprotocol/inspector@2.7.0
```

In the Inspector page that opens:

1. **Transport Type:** `Streamable HTTP`
2. **URL:** `http://127.0.0.1:8000/mcp`
3. Click **Connect**, then **Tools → List Tools**. You should see `list_due`, `add_deadline`,
   `find_conflicts` and `ingest_document`.
4. Run `find_conflicts` with the default window. It should report the visa renewal colliding
   with the school fee.

## Connect from Claude Desktop

Claude Desktop's config file only starts **stdio** servers, and its Custom Connectors don't
accept `localhost` URLs. To reach this local Streamable HTTP server, it launches
[`mcp-remote`](https://www.npmjs.com/package/mcp-remote), a small stdio↔HTTP bridge.

1. Start the server (`uv run duebook`) and leave it running in its own terminal.
2. Find where your Node.js is installed:

   ```bash
   dirname "$(which npx)"
   ```

   Claude Desktop doesn't inherit your shell's `PATH`, so a bare `npx` often isn't found,
   especially if Node came from nvm, asdf or volta. The config below uses this directory
   (`<NODE_BIN>`) for both the `npx` path and a `PATH` that includes `node`, since `npx` is
   itself a `#!/usr/bin/env node` script.
3. **Quit Claude Desktop fully (⌘Q).** If you edit the config while the app is running, it
   can overwrite your changes when it quits.
4. With the app closed, open the config:

   ```bash
   open -e ~/Library/Application\ Support/Claude/claude_desktop_config.json
   ```

   Add an `mcpServers` key next to whatever is already in the file (keep existing keys such
   as `preferences`), replacing `<NODE_BIN>` with the output of step 2:

   ```json
   "mcpServers": {
     "duebook": {
       "command": "<NODE_BIN>/npx",
       "args": ["-y", "mcp-remote@0.14.3", "http://127.0.0.1:8000/mcp"],
       "env": {
         "PATH": "<NODE_BIN>:/usr/bin:/bin"
       }
     }
   }
   ```

5. Check the edit was saved (this should print the `duebook` entry, not `None`):

   ```bash
   python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/Library/Application Support/Claude/claude_desktop_config.json'))).get('mcpServers'))"
   ```

6. Open Claude Desktop, start a new chat, and open the **+** menu → **Connectors**.
   `duebook` should be listed with its four tools.

If it doesn't connect, rerun the step 5 check (if it prints `None`, the app overwrote the
file, so quit it and add the entry again), then check the logs:

```bash
tail -n 50 -f ~/Library/Logs/Claude/mcp*.log
```

## Vault format

```yaml
---
title: Visa renewal — Parent A
due: 2026-11-15
window_start: 2026-11-10        # optional
kind: hard                      # hard | soft
source: "Immigration department letter, 2026-08-30"
confidence: 0.95                # 0–1
status: open                    # open | done | cancelled
---
Free-text notes.
```

The five seeded files in `vault/` are made-up examples with no real personal data.

## Licence

MIT. See [LICENSE](LICENSE).

## Document ingestion (Week 2)

`ingest_document(path_or_text, hint=None)` reads a local PDF, UTF-8 `.txt`/`.eml`,
or pasted text and sends extracted text to Amazon Bedrock. It returns either:

- `saved`: `path` and extracted `entry` with title, due, window, classification reason,
  source quote, confidence and notes. Duplicate title/date entries are refused.
- `needs_confirmation`: `candidate` and one `question`. Ask the user that question;
  call again with the **same document** and their answer in `hint`.

An invalid response or AWS error fails without saving. Scans need pasted text; no OCR.
The insurance fixture needs a receipt date: `I received it on 2026-10-01.` produces
`2026-10-31`. Self-reported model confidence is a heuristic, not a calibrated probability.
Schema and quote checks cannot prove that a semantically wrong date is correct.

### AWS setup

From the repository root (use `/usr/local/bin/aws` if the Homebrew CLI is broken):

```bash
uv sync
/usr/local/bin/aws login --profile duebook
export AWS_PROFILE=duebook
export AWS_REGION=ap-southeast-1
export DUEBOOK_MODEL_ID=apac.amazon.nova-lite-v1:0
```

Then run `uv run duebook` in that same terminal. `boto3[crt]` supports the browser-login
credential chain. Refresh expired sessions with the login command above. Clients that
start the server themselves must pass AWS_PROFILE and AWS_REGION in its environment.
The default model is APAC Nova Lite, using cross-region inference within APAC.

Nova returns the `extract_deadline` tool's JSON-schema payload through Converse;
we do not parse prose or Markdown-fenced JSON. Application checks require strict ISO
calendar dates, a 0–1 finite confidence, allowed fields, and a source quote found in the
submitted document (whitespace normalized). Missing dates, confidence below 0.7,
ambiguities or clarification questions prevent writes. Renewal windows and notes persist.

### Cost and input limits

One Converse request per ingestion attempt (at most two HTTP attempts on transient failures).
The document plus hint is capped at 12,000 characters before JSON serialization; fixed
prompt/schema overhead is additional. Hints are limited to 2,000 characters. Long documents
use head + tail and **always require clarification** with a shorter relevant section.
Output is capped at 1,400 tokens. Input/output token counts are logged to stderr without
document content. Calls are billable; the $20 AWS budget is an alert, not a spending cap.
Credentials stay in the standard AWS credential chain, never the repository.

### Verify without changing the demo vault

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
# One opt-in billable live test, immigration fixture only:
DUEBOOK_LIVE=1 uv run pytest tests/test_ingest.py -k live
# Four billable calls, three synthetic documents + clarification; temporary vault only:
uv run python scripts/check_ingestion.py
```

Offline regressions replay actual Nova Lite responses from synthetic fixtures in
`tests/fixtures/bedrock/`. To deliberately refresh these recordings, run
`uv run python scripts/check_ingestion.py --record` and review the resulting JSON changes.
Real personal documents must never be used to generate committed recordings.

Reference: [Nova tool choice for structured extraction](https://docs.aws.amazon.com/nova/latest/userguide/tool-choice.html).

For the supported `within N days of receipt` pattern, the application requires an explicit
receipt date in the hint and calculates the deadline itself. Missing year evidence also
requires confirmation. Opening windows require explicit opening language in the document;
discount and payment-plan paragraphs are retained as context. These guards cover known
failure cases, not every natural-language date expression. The school fixture's late-payment
penalty led Nova to classify it as hard; an invitation to request a payment plan does not
prove that an alternative deadline has been approved.
