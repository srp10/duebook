import copy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from duebook.cloud_worker import process

NOW = datetime(2026, 10, 5, 9, tzinfo=ZoneInfo("Asia/Hong_Kong"))


def preview():
    return {
        "key": "fixture",
        "from": "demo@example.test",
        "to": "demo@example.test",
        "subject": "Synthetic deadline",
        "body": "Synthetic test only",
        "expires": (NOW + timedelta(minutes=10)).isoformat(),
        "schedule": [(NOW + timedelta(minutes=2)).isoformat()],
    }


class Harness:
    def __init__(self):
        self.state = {}
        self.persisted = {}
        self.sent = []
        self.fail = False

    def save(self, state):
        self.persisted = copy.deepcopy(state)

    def send(self, subject, body):
        assert self.persisted["attempts"][-1]["status"] == "unknown"
        self.sent.append((subject, body))
        if self.fail:
            raise TimeoutError()
        return "test-message-id"

    def call(self, event, now=NOW):
        return process(
            self.state, event, self.save, self.send, now, "demo@example.test", "demo@example.test"
        )


def test_opt_in_due_claim_and_duplicate_tick():
    h = Harness()
    h.call({"action": "tick"})
    assert not h.sent
    h.call({"action": "enable", "preview": preview()})
    h.call({"action": "tick"})
    assert not h.sent
    h.call({"action": "tick"}, NOW + timedelta(minutes=3))
    h.state = copy.deepcopy(h.persisted)
    h.call({"action": "tick"}, NOW + timedelta(minutes=4))
    assert len(h.sent) == 1
    assert h.state["attempts"][0]["status"] == "accepted"


def test_ambiguous_send_pauses_and_does_not_retry():
    h = Harness()
    h.call({"action": "enable", "preview": preview()})
    h.fail = True
    h.call({"action": "tick"}, NOW + timedelta(minutes=3))
    h.call({"action": "tick"}, NOW + timedelta(minutes=4))
    assert len(h.sent) == 1
    assert h.state["plans"]["fixture"]["status"] == "paused"


@pytest.mark.parametrize("action", ["cancel", "done", "pause"])
def test_stop_prevents_delivery(action):
    h = Harness()
    h.call({"action": "enable", "preview": preview()})
    h.call({"action": action, "key": "fixture"})
    h.call({"action": "tick"}, NOW + timedelta(days=2))
    assert not h.sent


def test_snooze_moves_future_trigger_later():
    h = Harness()
    h.call({"action": "enable", "preview": preview()})
    h.call({"action": "snooze", "key": "fixture"})
    h.call({"action": "tick"}, NOW + timedelta(minutes=3))
    assert not h.sent
    h.call({"action": "tick"}, NOW + timedelta(days=1, minutes=3))
    assert len(h.sent) == 1


def test_recipient_and_expiry_are_enforced():
    h = Harness()
    p = preview()
    p["to"] = "other@example.test"
    with pytest.raises(ValueError, match="configuration"):
        h.call({"action": "test", "preview": p})
    with pytest.raises(ValueError, match="expired"):
        h.call({"action": "test", "preview": preview()}, NOW + timedelta(minutes=11))
    assert not h.sent


def test_test_send_does_not_enroll_and_cannot_repeat_immediately():
    h = Harness()
    h.call({"action": "test", "preview": preview()})
    assert not h.state["plans"]
    with pytest.raises(ValueError, match="already attempted"):
        h.call({"action": "test", "preview": preview()})
    assert len(h.sent) == 1


def test_cap_and_coalescing():
    h = Harness()
    p = preview()
    p["schedule"].append((NOW + timedelta(minutes=3)).isoformat())
    h.call({"action": "enable", "preview": p})
    h.call({"action": "tick"}, NOW + timedelta(minutes=4))
    assert len(h.sent) == 1
    assert h.state["plans"]["fixture"]["jobs"][0]["status"] == "superseded"
    h.state["attempts"] = [h.state["attempts"][0]] * 20
    with pytest.raises(ValueError, match="Daily limit"):
        h.call({"action": "test", "preview": p}, NOW + timedelta(minutes=6))


def test_deployment_recipient_change_pauses_old_approval():
    h = Harness()
    h.call({'action': 'enable', 'preview': preview()})
    process(h.state, {'action': 'tick'}, h.save, h.send, NOW + timedelta(minutes=3),
            'demo@example.test', 'changed@example.test')
    assert not h.sent
    assert h.state['plans']['fixture']['status'] == 'paused'
