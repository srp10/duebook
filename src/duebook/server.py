"""MCP server exposing the deadlines vault over Streamable HTTP."""

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from duebook import ingest, vault

# Default to the repo's vault/ so the server finds it regardless of cwd.
VAULT_DIR = Path(os.environ.get("DUEBOOK_VAULT", Path(__file__).resolve().parents[2] / "vault"))

mcp = FastMCP(
    "duebook",
    host=os.environ.get("DUEBOOK_HOST", "127.0.0.1"),
    port=int(os.environ.get("DUEBOOK_PORT", "8000")),
)


@mcp.tool()
def list_due(window_days: int = 30) -> list[dict]:
    """List open household deadlines: overdue ones first, then those due in the next
    `window_days` days, soonest first.

    Each result has title, due (ISO date), kind (hard/soft), source (where the date
    came from), confidence (0-1), notes and window_start. Notes preserve user-supplied
    clarifications and date calculations. When explaining a derived deadline, distinguish
    the source quote from user-supplied inputs and the calculation; do not imply those
    inputs were independently verified. Confidence is not verification of supplied facts.
    Overdue items also have overdue: true and days_overdue; mention them first.
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


@mcp.tool()
def find_conflicts(window_days: int = 7) -> list[dict]:
    """Find pairs of open deadlines due within `window_days` of each other.

    Each result has the two deadlines (a, b), days_apart, and a one- or two-sentence
    plain-English explanation of the clash and what to do about it. Hard deadlines
    are listed first.
    """
    return vault.find_conflicts(VAULT_DIR, window_days)


@mcp.tool()
def ingest_document(path_or_text: str, hint: str | None = None) -> dict:
    """Extract one deadline from PDF/txt/eml path or pasted text using Amazon Bedrock.

    Sends document text to AWS. A clear, validated deadline is saved with a source quote.
    On needs_confirmation, ask the returned question and call again with the SAME
    document and the user's answer in hint. Never guess an answer for the user.
    Scans are unsupported. Duplicates are refused; uncertain results never write files.
    """
    return ingest.ingest_document(VAULT_DIR, path_or_text, hint)


def main() -> None:
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
