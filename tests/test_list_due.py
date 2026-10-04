from datetime import date

from conftest import REPO_VAULT, TODAY, write

from duebook.vault import Deadline, list_due, parse, render


def test_seed_vault_parses():
    deadlines = [
        parse((REPO_VAULT / name).read_text())
        for name in [
            "home-insurance-renewal-2026-10-05.md",
            "lease-renewal-notice-2026-10-20.md",
            "school-fee-term-2-2026-11-12.md",
            "school-trip-consent-form-2026-12-04.md",
            "visa-renewal-parent-a-2026-11-15.md",
        ]
    ]
    assert len(deadlines) == 5
    assert all(d.status == "open" for d in deadlines)


def test_render_parse_round_trip():
    d = Deadline(
        title="Visa renewal — Parent A",
        due=date(2026, 11, 15),
        window_start=date(2026, 11, 10),
        kind="hard",
        source="Letter, 2026-08-30",
        confidence=0.95,
        notes="Bring photos.",
    )
    back = parse(render(d))
    assert back == d


def test_returns_only_open_within_window_sorted(vault_dir):
    write(vault_dir, "later", title="Later", due=date(2026, 10, 20))
    write(vault_dir, "sooner", title="Sooner", due=date(2026, 10, 3))
    write(vault_dir, "outside", title="Outside", due=date(2026, 11, 30))
    write(vault_dir, "done", title="Done", due=date(2026, 10, 5), status="done")

    result = list_due(vault_dir, window_days=30, today=TODAY)

    assert [r["title"] for r in result] == ["Sooner", "Later"]


def test_overdue_open_items_come_first_most_overdue_first(vault_dir):
    write(vault_dir, "upcoming", title="Upcoming", due=date(2026, 10, 3))
    write(vault_dir, "yesterday", title="Yesterday", due=date(2026, 9, 30))
    write(vault_dir, "long-ago", title="Long ago", due=date(2026, 8, 1))
    write(vault_dir, "old-done", title="Old done", due=date(2026, 9, 1), status="done")

    result = list_due(vault_dir, window_days=30, today=TODAY)

    assert [(r["title"], r.get("days_overdue")) for r in result] == [
        ("Long ago", 61),
        ("Yesterday", 1),
        ("Upcoming", None),
    ]
    assert result[0]["overdue"] is True
    assert "overdue" not in result[2]


def test_overdue_items_ignore_the_window(vault_dir):
    write(vault_dir, "ancient", title="Ancient", due=date(2025, 1, 1))

    [r] = list_due(vault_dir, window_days=0, today=TODAY)
    assert r["overdue"] is True
    assert r["days_overdue"] == (TODAY - date(2025, 1, 1)).days


def test_window_edges_are_inclusive(vault_dir):
    write(vault_dir, "today", title="Today", due=TODAY)
    write(vault_dir, "edge", title="Edge", due=date(2026, 10, 8))

    assert [r["title"] for r in list_due(vault_dir, window_days=7, today=TODAY)] == [
        "Today",
        "Edge",
    ]


def test_result_fields(vault_dir):
    write(
        vault_dir,
        "a",
        title="A",
        due=date(2026, 10, 2),
        kind="soft",
        source="Email",
        confidence=0.7,
    )

    assert list_due(vault_dir, today=TODAY) == [
        {
            "title": "A",
            "due": "2026-10-02",
            "kind": "soft",
            "source": "Email",
            "confidence": 0.7,
            "confidence_note": "Confidence is not independent verification of supplied facts.",
            "notes": "",
            "window_start": None,
        }
    ]


def test_list_due_returns_saved_clarification_and_calculation(vault_dir):
    notes = "Calculated as receipt 2026-10-01 + 30 calendar days.\nUser clarification: 2026-10-01"
    write(
        vault_dir,
        "insurance",
        title="Insurance",
        due=date(2026, 10, 31),
        source="Renew within 30 days of receipt.",
        notes=notes,
        window_start=date(2026, 10, 1),
    )
    [result] = list_due(vault_dir, window_days=60, today=TODAY)
    assert result["notes"] == notes
    assert result["source"] == "Renew within 30 days of receipt."
    assert result["window_start"] == "2026-10-01"
    assert "not independent verification" in result["confidence_note"]
