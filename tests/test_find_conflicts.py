from datetime import date

from conftest import REPO_VAULT, write

from duebook.vault import find_conflicts


def test_seed_vault_has_exactly_the_visa_school_fee_conflict():
    [c] = find_conflicts(REPO_VAULT)

    assert c["explanation"] == (
        "Visa renewal — Parent A (hard, 15 Nov) collides with "
        "School fee — Term 2 (soft, 12 Nov), 3 days apart."
    )
    assert c["days_apart"] == 3
    assert c["a"]["title"] == "Visa renewal — Parent A"
    assert c["b"]["title"] == "School fee — Term 2"


def test_window_is_inclusive(vault_dir):
    write(vault_dir, "a", title="A", due=date(2026, 10, 1))
    write(vault_dir, "b", title="B", due=date(2026, 10, 8))
    write(vault_dir, "c", title="C", due=date(2026, 10, 16))

    assert [(c["a"]["title"], c["b"]["title"]) for c in find_conflicts(vault_dir, 7)] == [
        ("A", "B")
    ]


def test_ignores_closed_deadlines(vault_dir):
    write(vault_dir, "a", title="A", due=date(2026, 10, 1))
    write(vault_dir, "b", title="B", due=date(2026, 10, 2), status="done")
    write(vault_dir, "c", title="C", due=date(2026, 10, 3), status="cancelled")

    assert find_conflicts(vault_dir) == []


def test_every_pair_in_a_cluster_is_reported(vault_dir):
    write(vault_dir, "a", title="A", due=date(2026, 10, 1))
    write(vault_dir, "b", title="B", due=date(2026, 10, 3))
    write(vault_dir, "c", title="C", due=date(2026, 10, 5))

    pairs = {(c["a"]["title"], c["b"]["title"]) for c in find_conflicts(vault_dir, 7)}
    assert pairs == {("A", "B"), ("A", "C"), ("B", "C")}


def test_same_kind_orders_by_date_and_same_day_wording(vault_dir):
    write(vault_dir, "x", title="X", due=date(2026, 10, 1), kind="soft")
    write(vault_dir, "y", title="Y", due=date(2026, 10, 1), kind="soft")

    [c] = find_conflicts(vault_dir)
    assert c["explanation"].endswith("both due the same day.")


def test_custom_window(vault_dir):
    write(vault_dir, "a", title="A", due=date(2026, 10, 1))
    write(vault_dir, "b", title="B", due=date(2026, 10, 11))

    assert find_conflicts(vault_dir, 7) == []
    assert len(find_conflicts(vault_dir, 10)) == 1
