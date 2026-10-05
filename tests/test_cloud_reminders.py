from datetime import datetime
from types import SimpleNamespace

import pytest

from duebook import vault
from duebook.cloud_reminders import CloudReminders
from duebook.demo_agent import DemoError
from duebook.reminders import ZONE, key_for


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setattr("duebook.cloud_reminders.boto3.client", lambda *a, **k: None)
    directory = tmp_path / "vault"
    directory.mkdir()
    vault.add_deadline(directory, "Synthetic lease", "2026-10-20", "hard", "Synthetic quote")
    m = CloudReminders(
        directory,
        tmp_path,
        SimpleNamespace(sender="sender@example.test", recipient="recipient@example.test"),
        "test-function",
        clock=lambda: datetime(2026, 10, 5, 12, tzinfo=ZONE),
    )
    m.key = key_for(vault.read_all(directory)[0])
    return m


def test_cloud_failure_does_not_mark_local_deadline_done(manager):
    def fail(event):
        raise DemoError("Cloud unavailable")

    manager.remote = fail
    with pytest.raises(DemoError):
        manager.change(manager.key, "done")
    assert manager.record(manager.key).status == "open"


def test_done_cancels_cloud_before_writing_local_record(manager):
    calls = []

    def remote(event):
        assert manager.record(manager.key).status == "open"
        calls.append(event)

    manager.remote = remote
    manager.change(manager.key, "done")
    assert calls == [{"action": "done", "key": manager.key}]
    assert manager.record(manager.key).status == "done"


def test_changed_record_rejects_preview_and_local_tick_only_pauses(manager):
    preview = manager.preview(manager.key)
    d = manager.record(manager.key)
    d.path.write_text(d.path.read_text().replace("Synthetic quote", "Changed quote"))
    with pytest.raises(DemoError, match="changed"):
        manager.approve(preview, "enable")
    calls = []

    def remote(event):
        calls.append(event)
        return {"plans": {manager.key: preview | {"status": "active"}}}

    manager.remote = remote
    manager.tick()
    assert calls == [{"action": "state"}, {"action": "pause", "key": manager.key}]
