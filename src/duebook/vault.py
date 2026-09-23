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


def add_deadline(
    vault_dir: Path,
    title: str,
    due: str,
    kind: str,
    source: str,
    confidence: float = 0.8,
) -> Path:
    """Write a new open deadline to the vault. Refuses a duplicate title + due."""
    title = title.strip()
    if not title:
        raise ValueError("title must not be empty")
    try:
        due_date = date.fromisoformat(due)
    except ValueError:
        raise ValueError(f"due must be an ISO date (YYYY-MM-DD), got {due!r}") from None
    if kind not in ("hard", "soft"):
        raise ValueError(f"kind must be 'hard' or 'soft', got {kind!r}")
    if not 0 <= confidence <= 1:
        raise ValueError(f"confidence must be between 0 and 1, got {confidence}")

    slug = slugify(title, due_date)
    for existing in read_all(vault_dir):
        if slugify(existing.title, existing.due) == slug:
            raise ValueError(
                f"duplicate: {existing.title!r} due {existing.due} already exists "
                f"at {existing.path.name}"
            )

    path = vault_dir / f"{slug}.md"
    d = Deadline(title=title, due=due_date, kind=kind, source=source, confidence=confidence)
    with path.open("x", encoding="utf-8") as f:  # "x" never overwrites an existing file
        f.write(render(d))
    return path


def list_due(vault_dir: Path, window_days: int = 30, today: date | None = None) -> list[dict]:
    """Open deadlines due between today and today + window_days, soonest first."""
    today = today or date.today()
    end = today + timedelta(days=window_days)
    due = [d for d in read_all(vault_dir) if d.status == "open" and today <= d.due <= end]
    return [d.summary() for d in sorted(due, key=lambda d: d.due)]


def find_conflicts(vault_dir: Path, window_days: int = 7) -> list[dict]:
    """Pairs of open deadlines due within `window_days` of each other, earliest pair first."""
    open_ = sorted((d for d in read_all(vault_dir) if d.status == "open"), key=lambda d: d.due)
    conflicts = []
    for i, a in enumerate(open_):
        for b in open_[i + 1 :]:
            gap = (b.due - a.due).days
            if gap > window_days:
                break  # sorted by due, so every later b is further away
            first, second = (b, a) if (b.kind, a.kind) == ("hard", "soft") else (a, b)
            conflicts.append(
                {
                    "a": first.summary(),
                    "b": second.summary(),
                    "days_apart": gap,
                    "explanation": f"{_label(first)} collides with {_label(second)}, {_gap(gap)}.",
                }
            )
    return conflicts


def _label(d: Deadline) -> str:
    return f"{d.title} ({d.kind}, {d.due.day} {d.due:%b})"


def _gap(n: int) -> str:
    if n == 0:
        return "both due the same day"
    return f"{n} day{'s' if n > 1 else ''} apart"
