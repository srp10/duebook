"""Demo state and write boundaries, with no network or model calls."""

import base64
from pathlib import Path
from types import SimpleNamespace

import pytest

from duebook.demo import DemoService, make_handler, seed_vault
from duebook.demo_agent import DemoError, TurnBudget, decode_result


class Bridge:
    def __init__(self):
        self.calls = []
        self.saved = []
        self.fail_snapshot = False

    def snapshot(self):
        if self.fail_snapshot:
            raise OSError("MCP disconnected")
        return {"deadlines": self.saved, "conflicts": []}

    def ingest(self, path, hint=None):
        self.calls.append((Path(path), hint))
        assert Path(path).exists()
        if hint is None:
            return {
                "status": "needs_confirmation",
                "question": "When did you receive it?",
                "candidate": {"title": "Insurance", "due": ""},
            }
        entry = {"title": "Insurance", "due": "2026-10-31"}
        self.saved.append(entry)
        return {"status": "saved", "entry": entry}

    def answer(self, history, message):
        self.calls.append((history.copy(), message))
        return {
            "text": "Here is what's saved.",
            "trace": [{"tool": "list_due", "status": "success"}],
        }


@pytest.fixture
def service(tmp_path):
    return DemoService(Bridge(), tmp_path / "uploads")


def upload(service, sid, filename="notice.txt"):
    return service.upload(
        sid, filename, base64.b64encode(b"Renew within 30 days of receipt.").decode()
    )


def test_pending_document_receives_exact_user_hint(service):
    sid = service.create()["session"]
    result = upload(service, sid)
    assert result["pending"]["question"] == "When did you receive it?"
    assert "path" not in result["pending"]
    assert not service.bridge.saved
    path = service.bridge.calls[0][0]
    result = service.confirm(sid, "2026-10-01")
    assert service.bridge.calls[-1] == (path, "2026-10-01")
    assert result["pending"] is None
    assert result["deadlines"][0]["due"] == "2026-10-31"
    assert not path.exists()


def test_new_conversation_reads_saved_deadlines_but_not_old_chat(service):
    first = service.create()["session"]
    upload(service, first)
    service.confirm(first, "2026-10-01")
    second = service.create()["session"]
    result = service.state(second)
    assert result["messages"] == []
    assert result["pending"] is None
    assert result["deadlines"][0]["due"] == "2026-10-31"


def test_chat_does_not_supply_pending_clarification(service):
    sid = service.create()["session"]
    upload(service, sid)
    before = len(service.bridge.saved)
    result = service.chat(sid, "What is due soon?")
    assert result["pending"]
    assert len(service.bridge.saved) == before


def test_uploaded_filename_cannot_escape_directory(service):
    sid = service.create()["session"]
    upload(service, sid, "../../outside.txt")
    path = service.bridge.calls[0][0]
    assert path.parent == service.uploads
    assert path.name != "outside.txt"
    service.cancel(sid)
    assert not path.exists()


def test_do_not_overwrite_pending_document(service):
    sid = service.create()["session"]
    upload(service, sid)
    with pytest.raises(DemoError, match="clarification"):
        upload(service, sid)
    assert len(list(service.uploads.iterdir())) == 1


@pytest.mark.parametrize(
    "filename,data", [("x.exe", "eA=="), ("x.pdf", "invalid"), ("x.txt", ""), (None, "eA==")]
)
def test_invalid_upload_never_calls_tool(service, filename, data):
    sid = service.create()["session"]
    with pytest.raises(DemoError):
        service.upload(sid, filename, data)
    assert service.bridge.calls == []
    assert not list(service.uploads.iterdir())


def test_snapshot_failure_does_not_erase_successful_save(service):
    sid = service.create()["session"]
    upload(service, sid)
    service.bridge.fail_snapshot = True
    result = service.confirm(sid, "2026-10-01")
    assert result["warning"]
    assert result["pending"] is None
    assert result["messages"][-1]["text"].startswith("Saved Insurance")
    assert len(service.bridge.saved) == 1


def test_no_confirmation_without_pending_document(service):
    sid = service.create()["session"]
    with pytest.raises(DemoError, match="no document"):
        service.confirm(sid, "2026-10-01")


def test_local_origin_and_host_restrictions(service):
    handler = make_handler(service)
    context = SimpleNamespace(
        server=SimpleNamespace(server_port=8080),
        headers={"Host": "127.0.0.1:8080", "Origin": "http://127.0.0.1:8080"},
    )
    assert handler.allowed(context)
    context.headers["Origin"] = "https://external.example"
    assert not handler.allowed(context)
    context.headers = {"Host": "attacker.example:8080"}
    assert not handler.allowed(context)


def test_seed_once_preserves_edits_and_does_not_restore_deletions(tmp_path):
    seed_vault(tmp_path)
    paths = list(tmp_path.glob("*.md"))
    assert len(paths) == 5
    paths[0].write_text("Edited record")
    paths[1].unlink()
    seed_vault(tmp_path)
    assert paths[0].read_text() == "Edited record"
    assert not paths[1].exists()


def test_turn_budget_and_tool_boundaries():
    budget = TurnBudget()
    for _ in range(5):
        budget.before_model(None)
    with pytest.raises(DemoError, match="limit"):
        budget.before_model(None)
    event = SimpleNamespace(tool_use={"name": "add_deadline", "input": {}}, cancel_tool=False)
    budget.before_tool(event)
    assert event.cancel_tool
    event = SimpleNamespace(
        tool_use={"name": "list_due", "input": {"window_days": 999}}, cancel_tool=False
    )
    budget.before_tool(event)
    assert event.cancel_tool


def test_mcp_errors_and_list_wrapping():
    assert decode_result({"status": "success", "structuredContent": {"result": [1, 2]}}) == [1, 2]
    with pytest.raises(DemoError, match="duplicate"):
        decode_result({"status": "error", "content": [{"text": "duplicate deadline"}]})


def test_plain_text_is_not_parsed_as_model_json():
    with pytest.raises(ValueError):
        decode_result({"status": "success", "content": [{"text": "Model prose"}]})


def test_conflict_gap_does_not_expand_to_the_planning_horizon():
    event = SimpleNamespace(
        tool_use={"name": "find_conflicts", "input": {"window_days": 60}}, cancel_tool=False
    )
    TurnBudget().before_tool(event)
    assert event.tool_use["input"]["window_days"] == 7
    assert not event.cancel_tool


@pytest.mark.parametrize(
    "raw,expected",
    [
        (
            "<thinking>Internal planning</thinking>\nIn this demo, two dates clash.",
            "In this demo, two dates clash.",
        ),
        ("An answer. <thinking>unfinished", "An answer."),
    ],
)
def test_only_public_answer_is_shown(raw, expected):
    from duebook.demo_agent import public_answer

    assert public_answer(raw) == expected


def test_thinking_only_response_is_not_an_answer():
    from duebook.demo_agent import public_answer

    with pytest.raises(DemoError, match="did not return an answer"):
        public_answer("<thinking>No final answer</thinking>")
