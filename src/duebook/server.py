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


@mcp.tool()
def add_deadline(title: str, due: str, kind: str, source: str, confidence: float = 0.8) -> str:
    """Add a household deadline to the vault and return the path of the new file.

    Args:
        title: Short name, e.g. "Car registration renewal".
        due: Due date as YYYY-MM-DD.
        kind: "hard" (a real cut-off with consequences) or "soft" (flexible).
        source: Where the date came from, e.g. "DMV letter, 2026-09-01".
        confidence: 0-1, how sure we are of the date.

    Refuses a duplicate (same title and due date).
    """
    return str(vault.add_deadline(VAULT_DIR, title, due, kind, source, confidence))


def main() -> None:
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
