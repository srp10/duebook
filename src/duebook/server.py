"""MCP server exposing the deadlines vault over Streamable HTTP."""

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from duebook import vault

# Default to the repo's vault/ so the server finds it regardless of cwd.
VAULT_DIR = Path(os.environ.get("DUEBOOK_VAULT", Path(__file__).resolve().parents[2] / "vault"))

mcp = FastMCP(
    "duebook",
    host=os.environ.get("DUEBOOK_HOST", "127.0.0.1"),
    port=int(os.environ.get("DUEBOOK_PORT", "8000")),
)


@mcp.tool()
def list_due(window_days: int = 30) -> list[dict]:
    """List open household deadlines due in the next `window_days` days, soonest first.

    Each result has title, due (ISO date), kind (hard/soft), source (where the date
    came from) and confidence (0-1).
    """
    return vault.list_due(VAULT_DIR, window_days)


def main() -> None:
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
