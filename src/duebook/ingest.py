"""Document -> validated candidate -> clarification or one persisted vault entry."""

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from duebook import vault
from duebook.bedrock import BedrockExtractor, validate
from duebook.loader import load_text


def ingest_document(
    vault_dir: Path,
    path_or_text: str,
    hint: str | None = None,
    *,
    extractor=None,
    confirmed_past_due: str | None = None,
    today: date | None = None,
) -> dict:
    document = load_text(path_or_text)
    candidate = validate((extractor or BedrockExtractor()).extract(document, hint), document)
    if (
        candidate["confidence"] < 0.7
        or candidate["ambiguities"]
        or not candidate["due"]
        or candidate["question"].strip()
    ):
        question = candidate["question"].strip()
        if not question:
            question = f"What exact due date (YYYY-MM-DD) should I use for {candidate['title']}?"
        return {"status": "needs_confirmation", "candidate": candidate, "question": question}
    current = today or datetime.now(ZoneInfo("Asia/Hong_Kong")).date()
    overdue = date.fromisoformat(candidate["due"]) < current
    if overdue and confirmed_past_due != candidate["due"]:
        return {
            "status": "needs_confirmation",
            "confirmation_type": "past_due",
            "candidate": candidate,
            "question": f"This gives a deadline of {candidate['due']}, which is in the past "
            f"(today is {current}). Correct the date or explicitly save it as overdue.",
        }
    notes = f"Classification: {candidate['kind_reason']}\n{candidate['notes']}".strip()
    if hint:
        notes += f"\nUser clarification: {hint}"
    if overdue:
        notes += f"\nUser explicitly confirmed saving overdue date: {candidate['due']}"
    vault_dir.mkdir(parents=True, exist_ok=True)
    path = vault.add_deadline(
        vault_dir,
        candidate["title"],
        candidate["due"],
        candidate["kind"],
        candidate["source"],
        candidate["confidence"],
        window_start=candidate["window_start"] or None,
        notes=notes,
    )
    return {"status": "saved", "path": str(path), "entry": candidate, "overdue": overdue}
