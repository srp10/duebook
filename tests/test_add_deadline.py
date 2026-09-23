from datetime import date

import pytest
from conftest import write

from duebook.vault import add_deadline, list_due, read_all


def test_writes_file_readable_by_list_due(vault_dir):
    path = add_deadline(
        vault_dir, "Car registration renewal", "2026-10-10", "hard", "DMV letter", 0.9
    )

    assert path == vault_dir / "car-registration-renewal-2026-10-10.md"
    assert list_due(vault_dir, today=date(2026, 10, 1)) == [
        {
            "title": "Car registration renewal",
            "due": "2026-10-10",
            "kind": "hard",
            "source": "DMV letter",
            "confidence": 0.9,
        }
    ]


def test_new_deadline_is_open_with_default_confidence(vault_dir):
    add_deadline(vault_dir, "Dentist", "2026-10-10", "soft", "Reminder card")

    [d] = read_all(vault_dir)
    assert d.status == "open"
    assert d.confidence == 0.8


def test_refuses_duplicate_title_and_due(vault_dir):
    add_deadline(vault_dir, "Dentist", "2026-10-10", "soft", "Reminder card")

    with pytest.raises(ValueError, match="duplicate"):
        add_deadline(vault_dir, "Dentist", "2026-10-10", "hard", "Other source")
    assert len(read_all(vault_dir)) == 1


def test_duplicate_check_ignores_case_and_punctuation(vault_dir):
    write(vault_dir, "hand-written-name", title="School fee — Term 2", due=date(2026, 11, 12))

    with pytest.raises(ValueError, match="duplicate"):
        add_deadline(vault_dir, "school fee: term 2", "2026-11-12", "soft", "Email")


def test_same_title_different_due_is_allowed(vault_dir):
    add_deadline(vault_dir, "Dentist", "2026-10-10", "soft", "Card")
    add_deadline(vault_dir, "Dentist", "2027-04-10", "soft", "Card")

    assert len(read_all(vault_dir)) == 2


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"title": "  "}, "title"),
        ({"due": "15 Nov 2026"}, "ISO date"),
        ({"kind": "urgent"}, "kind"),
        ({"confidence": 1.5}, "confidence"),
    ],
)
def test_rejects_invalid_input(vault_dir, kwargs, message):
    args = {"title": "X", "due": "2026-10-10", "kind": "hard", "source": "S"} | kwargs

    with pytest.raises(ValueError, match=message):
        add_deadline(vault_dir, **args)
    assert read_all(vault_dir) == []
