# FRICTION.md

Every doc gap, transport surprise or confusing error hit while building this, logged as it happens.
Format: task attempted · steps · expected vs actual · severity · workaround · suggestion.

---

## 1. Picking an MCP Python SDK version for spec 2025-11-25

- **Task attempted:** Pin an MCP Python SDK version that speaks Streamable HTTP on spec 2025-11-25.
- **Steps:** Checked PyPI for `mcp`. Latest is `2.2.0` (2026-09-07), but a `1.x` line is still being released in parallel (`1.30.0`, same day). Downloaded both wheels and grepped for protocol constants.
- **Expected vs actual:** Expected one current SDK whose "latest protocol" matched the spec named in the hackathon brief. Actually found two maintained major lines:
  - `1.30.0`: `LATEST_PROTOCOL_VERSION = "2025-11-25"`, `FastMCP` API, types in `mcp/types.py`.
  - `2.2.0`: `LATEST_PROTOCOL_VERSION = "2026-07-28"` (a stateless, handshake-free revision). 2025-11-25 is still accepted but counted as a "handshake" (older) version. `FastMCP` renamed to `MCPServer`, types split into a separate `mcp-types` package, new `httpx2` dependency.
  Nothing on the PyPI page says which major version to use for which spec revision. I had to read the source to find out.
- **Severity:** Medium. Picking the wrong major version means a different API surface and possibly a different negotiated protocol than the brief requires.
- **Workaround:** Pinned `mcp==1.30.0`. Its newest protocol is exactly 2025-11-25, and most Claude Desktop examples and docs still use the 1.x `FastMCP` API.
- **Suggestion:** Add a "which SDK version for which spec revision" table to the SDK README and PyPI description, and say how long 1.x will stay maintained.

## 2. Local toolchain missing (uv, Python 3.12)

- **Task attempted:** Create the uv project on Python 3.12.
- **Steps:** `which uv python3.12`: neither found; system `python3` is 3.8.5.
- **Expected vs actual:** Expected to go straight to `uv init`. Actually had to install uv first (`brew install uv`), then `uv python install 3.12`.
- **Severity:** Low. It took about a minute, but it's a step the hackathon quick-start doesn't mention.
- **Workaround:** `brew install uv && uv python install 3.12`. uv-managed Python leaves the system Python alone.
- **Suggestion:** Hackathon starter docs should list `uv` as a prerequisite with the one-line install.

## 3. FastMCP defaults: stdio transport, and list results wrapped in `{"result": ...}`

- **Task attempted:** Serve `list_due` over Streamable HTTP and check what the client gets back.
- **Steps:** `FastMCP("duebook")` with a `@mcp.tool()` that returns `list[dict]`, then called it with the SDK's `streamablehttp_client`.
- **Expected vs actual:**
  - `FastMCP.run()` defaults to `transport="stdio"`. Streamable HTTP only runs if you pass `transport="streamable-http"` explicitly. If you forget, the process sits waiting on stdin with no error.
  - A tool returning a list comes back as `structuredContent = {"result": [...]}`, not the bare list. The wrapper key isn't in the tool docstring or the quick-start.
- **Severity:** Low.
- **Workaround:** Always pass the transport explicitly. Accept the `result` wrapper (clients see the same data in `content` text too).
- **Suggestion:** Log the active transport and URL at start-up. Document the structured-output wrapping rule next to the `@tool` decorator.

## 4. Claude Desktop can't connect to a local Streamable HTTP server directly

- **Task attempted:** Connect Claude Desktop to `http://127.0.0.1:8000/mcp` for the Spike A done-condition.
- **Steps:** Read the MCP "Connect to local MCP servers" guide and the Claude Desktop config docs. Looked for a `url` / `type: "http"` entry shape for `claude_desktop_config.json`.
- **Expected vs actual:** Expected Claude Desktop to accept a Streamable HTTP URL, since the hackathon *requires* Streamable HTTP. Actually, `claude_desktop_config.json` only launches stdio servers (`command` + `args`), and Custom Connectors (Settings → Connectors) don't accept `localhost` URLs. The official local-servers guide only shows stdio, and it doesn't say HTTP isn't supported. That came from community posts.
- **Severity:** High. The required transport and the named test client don't talk to each other without a third-party bridge.
- **Workaround:** Put the `mcp-remote` npm package (stdio↔Streamable HTTP proxy) in the Desktop config: `npx -y mcp-remote@0.14.3 http://127.0.0.1:8000/mcp`. The server itself stays pure Streamable HTTP. This adds a Node.js requirement on the client side, and there's one more process that can fail.
- **Suggestion:** Either let `claude_desktop_config.json` accept `{"type": "http", "url": ...}` for local servers, or say plainly in the local-servers guide that HTTP needs a bridge and link to the recommended one.

## 5. Claude Desktop overwrote `claude_desktop_config.json` edits made while it was running

- **Task attempted:** Add the `duebook` entry under `mcpServers` via Settings → Developer → Edit Config, then restart.
- **Steps:** Edited and saved the file with Claude Desktop open, quit with ⌘Q, reopened. No duebook connector. Checked the file: `mcpServers` was gone. Only `coworkUserFilesPath` and `preferences` remained, and the file's modified time matched the app restart.
- **Expected vs actual:** Expected the "Edit Config" button to be a safe way to edit while the app is open. Actually, the app rewrote the file from its in-memory settings, silently dropping the new key. No warning, and no log line mentioning duebook.
- **Severity:** Medium. The server looks broken when it isn't, and nothing points at the real cause.
- **Workaround:** Quit Claude Desktop fully first, edit the file, check it (`python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/Library/Application Support/Claude/claude_desktop_config.json'))).get('mcpServers'))"`), then reopen.
- **Suggestion:** Merge on write instead of overwriting, or watch the file and reload. At minimum, have "Edit Config" warn that edits need the app closed.

## 6. `npx` from nvm isn't on Claude Desktop's PATH

- **Task attempted:** Launch the `mcp-remote` bridge from `claude_desktop_config.json` with `"command": "npx"`.
- **Steps:** `which npx` → `~/.nvm/versions/node/v24.13.0/bin/npx`. GUI apps on macOS don't source `~/.zshrc`, so nvm's PATH isn't there.
- **Expected vs actual:** A bare `npx` in the config would fail to start. A full path to `npx` alone isn't enough either, because the `npx` script starts with `#!/usr/bin/env node` and `node` isn't on the GUI PATH either.
- **Severity:** Medium. It's common for anyone who installed Node with nvm, and the failure only shows in the logs.
- **Workaround:** Use the absolute `npx` path *and* set `"env": {"PATH": "<nvm node bin>:/usr/bin:/bin"}` on the server entry. With that, the connector appeared on the first restart after the config stuck.
- **Suggestion:** The local-servers guide should cover nvm/asdf/volta installs. Or Claude Desktop could resolve commands using the user's login-shell PATH.

---

## Time to first tool call

| Client | Measured from | Time | Notes |
|---|---|---|---|
| MCP Python SDK client (`streamablehttp_client`) | `git init` (23:44:22) → first successful `list_due` (≈23:48:24) | **≈4 min** | Excludes toolchain install (FRICTION #2) and SDK version research (#1). |
| Claude Desktop (via `mcp-remote`) | first config save (≈20:39) → `add_deadline` wrote the vault file (20:49:22, file mtime) | **≈10 min** | Most of it lost to the app overwriting the config (#5) and the nvm PATH fix (#6). Server was already running. |
