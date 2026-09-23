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
