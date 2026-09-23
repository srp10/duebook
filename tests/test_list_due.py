from datetime import date

from conftest import REPO_VAULT, TODAY, write

from duebook.vault import Deadline, list_due, parse, read_all, render


def test_seed_vault_parses():
    deadlines = read_all(REPO_VAULT)
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
    write(vault_dir, "past", title="Past", due=date(2026, 9, 30))
    write(vault_dir, "done", title="Done", due=date(2026, 10, 5), status="done")

    result = list_due(vault_dir, window_days=30, today=TODAY)

    assert [r["title"] for r in result] == ["Sooner", "Later"]


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
        {"title": "A", "due": "2026-10-02", "kind": "soft", "source": "Email", "confidence": 0.7}
    ]
