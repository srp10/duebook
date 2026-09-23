"""The vault: one markdown file per deadline, YAML front-matter as the record.

Files are the database. Every call re-reads the directory, so nothing is held
in memory between requests or across restarts.
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import yaml

FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)


@dataclass
class Deadline:
    title: str
    due: date
    kind: str
    source: str
    confidence: float
    status: str = "open"
    window_start: date | None = None
    notes: str = ""
    path: Path | None = None

    def summary(self) -> dict:
        """The fields tools return to the client."""
        return {
            "title": self.title,
            "due": self.due.isoformat(),
            "kind": self.kind,
            "source": self.source,
            "confidence": self.confidence,
        }


def parse(text: str, path: Path | None = None) -> Deadline:
    match = FRONT_MATTER.match(text)
    if not match:
        raise ValueError(f"{path}: no YAML front-matter")
    meta = yaml.safe_load(match.group(1)) or {}
    return Deadline(
        title=meta["title"],
        due=_as_date(meta["due"]),
        kind=meta["kind"],
        source=meta["source"],
        confidence=float(meta["confidence"]),
        status=meta.get("status", "open"),
        window_start=_as_date(meta["window_start"]) if meta.get("window_start") else None,
        notes=match.group(2).strip(),
        path=path,
    )


def render(d: Deadline) -> str:
    meta = {"title": d.title, "due": d.due}
    if d.window_start:
        meta["window_start"] = d.window_start
    meta |= {
        "kind": d.kind,
        "source": d.source,
        "confidence": d.confidence,
        "status": d.status,
    }
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)
    return f"---\n{front}---\n{d.notes}\n"


def read_all(vault_dir: Path) -> list[Deadline]:
    return [parse(p.read_text(encoding="utf-8"), p) for p in sorted(vault_dir.glob("*.md"))]


def slugify(title: str, due: date) -> str:
    words = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"{words}-{due.isoformat()}"


def _as_date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def list_due(vault_dir: Path, window_days: int = 30, today: date | None = None) -> list[dict]:
    """Open deadlines due between today and today + window_days, soonest first."""
    today = today or date.today()
    end = today + timedelta(days=window_days)
    due = [d for d in read_all(vault_dir) if d.status == "open" and today <= d.due <= end]
    return [d.summary() for d in sorted(due, key=lambda d: d.due)]
