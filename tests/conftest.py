from datetime import date
from pathlib import Path

import pytest

from duebook.vault import Deadline, render

TODAY = date(2026, 10, 1)
REPO_VAULT = Path(__file__).resolve().parents[1] / "vault"


def write(vault_dir: Path, name: str, **fields) -> Path:
    fields.setdefault("kind", "hard")
    fields.setdefault("source", "Test fixture")
    fields.setdefault("confidence", 0.9)
    path = vault_dir / f"{name}.md"
    path.write_text(render(Deadline(**fields)), encoding="utf-8")
    return path


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    d = tmp_path / "vault"
    d.mkdir()
    return d
