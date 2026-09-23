# Duebook

An MCP server that keeps a household's hard deadlines (visa, school, lease, insurance) in a
markdown vault. Built for the Amazon Developer Hackathon 2026, Alexa+ track.

- **Transport:** Streamable HTTP, MCP spec 2025-11-25 (`mcp==1.30.0`)
- **Storage:** `vault/*.md`. One file per deadline, YAML front-matter. The files are the
  database; nothing lives in memory between requests.

## Tools

| Tool | What it does |
|---|---|
| `list_due(window_days=30)` | Open deadlines due in the next N days, soonest first, with title, due, kind, source, confidence. |
| `add_deadline(title, due, kind, source, confidence=0.8)` | Writes `vault/<title-slug>-<due>.md`, returns its path. Refuses a duplicate title + due. `due` is `YYYY-MM-DD`; `kind` is `hard` or `soft`. |
| `find_conflicts(window_days=7)` | Pairs of open deadlines due within N days of each other, each with a one-sentence explanation. |

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
3. Click **Connect**, then **Tools → List Tools**. You should see `list_due`, `add_deadline`
   and `find_conflicts`.
4. Run `find_conflicts` with the default window. It should report the visa renewal colliding
   with the school fee.

## Connect from Claude Desktop

Claude Desktop's config file only starts **stdio** servers, and its Custom Connectors don't
accept `localhost` URLs. To reach this local Streamable HTTP server, it launches
[`mcp-remote`](https://www.npmjs.com/package/mcp-remote), a small stdio↔HTTP bridge.

1. Start the server (`uv run duebook`) and leave it running.
2. Open Claude Desktop → **Settings → Developer → Edit Config**. That opens
   `~/Library/Application Support/Claude/claude_desktop_config.json`. Add `duebook` under
   `mcpServers`, keeping any servers already there:

   ```json
   {
     "mcpServers": {
       "duebook": {
         "command": "npx",
         "args": ["-y", "mcp-remote@0.14.3", "http://127.0.0.1:8000/mcp"]
       }
     }
   }
   ```

   If Claude Desktop can't find `npx` (a GUI app doesn't always inherit your shell's `PATH`),
   replace `"npx"` with the full path from `which npx`.
3. Quit Claude Desktop fully (**⌘Q**, not just closing the window) and reopen it.
4. In a new chat, open the **+** menu → **Connectors**. `duebook` should be listed with its
   three tools.

If it doesn't connect, check the logs:

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
