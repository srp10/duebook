"""Deterministic scheduling and delivery boundaries; never sends real email."""

from datetime import datetime, timedelta

import pytest

from duebook import vault
from duebook.demo import DemoService
from duebook.demo_agent import DemoError
from duebook.reminders import ZONE, Reminders, key_for


class Sender:
    sender = "sender@example.test"
    recipient = "recipient@example.test"

    def __init__(self):
        self.sent = []
        self.fail = False

    def send(self, subject, body):
        self.sent.append((subject, body))
        if self.fail:
            raise TimeoutError("Unknown outcome")
        return "test-message-id"


@pytest.fixture
def setup(tmp_path):
    directory = tmp_path / "vault"
    directory.mkdir()
    vault.add_deadline(
        directory,
        "Insurance",
        "2026-10-31",
        "hard",
        "Renew within 30 days of receipt.",
        notes="Classification: the document gives October 1.\n\n"
        "Calculated as receipt 2026-10-01 + 30 calendar days.\n"
        "User clarification: 2026-10-01",
    )
    clock = [datetime(2026, 10, 5, 12, tzinfo=ZONE)]
    sender = Sender()
    manager = Reminders(directory, tmp_path, sender, lambda: clock[0])
    key = key_for(vault.read_all(directory)[0])
    return manager, clock, sender, key


def test_opt_in_preview_and_schedule(setup):
    manager, clock, sender, key = setup
    manager.tick()
    assert not sender.sent
    preview = manager.preview(key)
    assert preview["schedule"] == [f"2026-10-{day}T09:00:00+08:00" for day in (24, 30, 31)]
    assert "User clarification: 2026-10-01" in preview["body"]
    assert "Classification:" not in preview["body"]
    assert sender.sent == []
    manager.approve(preview, "enable")
    assert not sender.sent
    assert manager.overview()["items"][key]["status"] == "active"


def test_restart_and_repeated_tick_do_not_duplicate(setup):
    manager, clock, sender, key = setup
    manager.approve(manager.preview(key), "enable")
    clock[0] = datetime(2026, 10, 24, 9, tzinfo=ZONE)
    other = Reminders(manager.vault_dir, manager.data_dir, sender, manager.clock)
    other.tick()
    manager.tick()
    assert len(sender.sent) == 1
    assert other.overview()["items"][key]["last"]["status"] == "accepted"


def test_missed_triggers_coalesce_to_one_on_wake(setup):
    manager, clock, sender, key = setup
    manager.approve(manager.preview(key), "enable")
    clock[0] = datetime(2026, 11, 1, 10, tzinfo=ZONE)
    manager.tick()
    manager.tick()
    assert len(sender.sent) == 1
    assert [j["status"] for j in manager.load()["plans"][key]["jobs"]] == [
        "superseded",
        "superseded",
        "accepted",
    ]


def test_snooze_postpones_due_jobs_and_preserves_later_jobs(setup):
    manager, clock, sender, key = setup
    manager.approve(manager.preview(key), "enable")
    clock[0] = datetime(2026, 10, 24, 8, tzinfo=ZONE)
    manager.change(key, "snooze")
    clock[0] += timedelta(hours=24)
    manager.tick()
    assert not sender.sent
    clock[0] += timedelta(hours=1)
    manager.tick()
    assert len(sender.sent) == 1
    assert manager.overview()["items"][key]["next"] == "2026-10-30T09:00:00+08:00"


@pytest.mark.parametrize("action", ["cancel", "done"])
def test_cancel_and_done_prevent_future_sends(setup, action):
    manager, clock, sender, key = setup
    manager.approve(manager.preview(key), "enable")
    manager.change(key, action)
    clock[0] = datetime(2026, 11, 1, 10, tzinfo=ZONE)
    manager.tick()
    assert not sender.sent
    if action == "done":
        assert not vault.list_due(manager.vault_dir, today=clock[0].date())
        assert manager.overview()["completed"][0]["title"] == "Insurance"


def test_done_preserves_notes_and_extra_frontmatter(setup):
    manager, _, _, key = setup
    d = manager.record(key)
    text = d.path.read_text().replace("kind: hard", "kind: hard\ncustom: keep-me")
    d.path.write_text(text)
    manager.change(key, "done")
    after = d.path.read_text()
    assert "custom: keep-me" in after
    assert vault.parse(after).notes == vault.parse(text).notes
    assert vault.parse(after).status == "done"


def test_changed_record_pauses_delivery_and_invalidates_preview(setup):
    manager, clock, sender, key = setup
    preview = manager.preview(key)
    manager.approve(preview, "enable")
    path = manager.record(key).path
    path.write_text(path.read_text().replace("Renew within", "Please renew within"))
    with pytest.raises(DemoError, match="changed"):
        manager.approve(preview, "test")
    clock[0] = datetime(2026, 10, 24, 10, tzinfo=ZONE)
    manager.tick()
    assert not sender.sent
    assert manager.overview()["items"][key]["status"] == "paused"


def test_preview_expiry_and_no_past_schedules(setup):
    manager, clock, sender, key = setup
    preview = manager.preview(key)
    clock[0] += timedelta(minutes=11)
    with pytest.raises(DemoError, match="expired"):
        manager.approve(preview, "test")
    clock[0] = datetime(2026, 10, 31, 12, tzinfo=ZONE)
    assert manager.preview(key)["schedule"] == []
    with pytest.raises(DemoError, match="No future"):
        manager.approve(manager.preview(key), "enable")
    assert not sender.sent


def test_send_once_does_not_enroll_and_has_cooldown(setup):
    manager, _, sender, key = setup
    preview = manager.preview(key)
    manager.approve(preview, "test")
    assert sender.sent == [(preview["subject"], preview["body"])]
    assert manager.overview()["items"][key]["status"] == "off"
    with pytest.raises(DemoError, match="five minutes"):
        manager.approve(manager.preview(key), "test")
    assert len(sender.sent) == 1


def test_ambiguous_failure_is_not_automatically_retried(setup):
    manager, clock, sender, key = setup
    manager.approve(manager.preview(key), "enable")
    sender.fail = True
    clock[0] = datetime(2026, 10, 24, 10, tzinfo=ZONE)
    manager.tick()
    manager.tick()
    clock[0] = datetime(2026, 10, 31, 10, tzinfo=ZONE)
    manager.tick()
    assert len(sender.sent) == 1
    assert manager.overview()["items"][key]["status"] == "paused"
    assert manager.overview()["items"][key]["last"]["status"] == "unknown"


def test_crash_after_claim_pauses_without_sending_again(setup):
    manager, clock, sender, key = setup
    manager.approve(manager.preview(key), "enable")
    state = manager.load()
    state["plans"][key]["jobs"][0]["status"] = "unknown"
    manager.save(state)
    clock[0] = datetime(2026, 10, 31, 10, tzinfo=ZONE)
    manager.tick()
    assert not sender.sent
    assert manager.overview()["items"][key]["status"] == "paused"


def test_no_configuration_or_recipient_change_cannot_send(setup):
    manager, _, sender, key = setup
    preview = manager.preview(key)
    sender.recipient = "changed@example.test"
    with pytest.raises(DemoError, match="configuration changed"):
        manager.approve(preview, "test")
    manager.sender = None
    with pytest.raises(DemoError, match="setup is incomplete"):
        manager.preview(key)
    assert not sender.sent


def test_daily_attempt_cap(setup):
    manager, clock, sender, key = setup
    state = manager.load()
    state["attempts"] = [{"key": "other", "at": clock[0].isoformat()} for _ in range(20)]
    manager.save(state)
    with pytest.raises(DemoError, match="Daily limit"):
        manager.approve(manager.preview(key), "test")
    assert not sender.sent


def test_explicit_session_preview_token_required(setup, tmp_path):
    manager, _, sender, key = setup

    class Bridge:
        def snapshot(self):
            return {"deadlines": [], "conflicts": []}

    service = DemoService(Bridge(), tmp_path / "uploads", manager)
    sid = service.create()["session"]
    with pytest.raises(DemoError, match="Preview"):
        service.reminder_action(sid, "test", key, "made-up")
    result = service.reminder_action(sid, "preview", key)
    token = result["email_preview"]["token"]
    with pytest.raises(DemoError, match="Preview"):
        service.reminder_action(service.create()["session"], "test", key, token)
    service.reminder_action(sid, "test", key, token)
    with pytest.raises(DemoError, match="Preview"):
        service.reminder_action(sid, "test", key, token)
    assert len(sender.sent) == 1


def test_background_worker_delivers_without_browser_request(setup):
    import threading

    manager, clock, sender, key = setup
    manager.approve(manager.preview(key), "enable")
    delivered = threading.Event()
    original = sender.send

    def send(subject, body):
        value = original(subject, body)
        delivered.set()
        return value

    sender.send = send
    clock[0] = datetime(2026, 10, 24, 9, tzinfo=ZONE)
    manager.start()
    try:
        assert delivered.wait(2), "worker did not deliver without a browser request"
    finally:
        manager.close()
    assert len(sender.sent) == 1


def test_concurrent_workers_share_durable_claim(setup):
    from concurrent.futures import ThreadPoolExecutor

    manager, clock, sender, key = setup
    manager.approve(manager.preview(key), "enable")
    clock[0] = datetime(2026, 10, 24, 9, tzinfo=ZONE)
    other = Reminders(manager.vault_dir, manager.data_dir, sender, manager.clock)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(m.tick) for m in (manager, other)]
        for f in futures:
            f.result(timeout=3)
    assert len(sender.sent) == 1
