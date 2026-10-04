"""Offline regressions replay synthetic Bedrock responses; live test is opt-in."""

import copy
import json
import os
from datetime import date
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from duebook.bedrock import MAX_INPUT, BedrockExtractor, ExtractionError, bounded_input
from duebook.ingest import ingest_document
from duebook.loader import load_text
from duebook.vault import read_all

FIXTURES = Path(__file__).parent / "fixtures"


class ReplayClient:
    def __init__(self, name="immigration", response=None):
        self.response = response or json.loads((FIXTURES / "bedrock" / f"{name}.json").read_text())
        self.requests = []

    def converse(self, **kwargs):
        self.requests.append(kwargs)
        return copy.deepcopy(self.response)


def extractor(name="immigration"):
    return BedrockExtractor(client=ReplayClient(name))


def test_ingest_pdf_persists_window_and_duplicate_refusal(vault_dir):
    path = str(FIXTURES / "immigration-letter.pdf")
    result = ingest_document(vault_dir, path, extractor=extractor())
    assert result["status"] == "saved"
    # Re-read from disk (nothing held in session memory).
    saved = read_all(vault_dir)[0]
    assert saved.due == date(2026, 11, 15)
    assert saved.window_start == date(2026, 11, 1)
    assert saved.kind == "hard"
    assert saved.source in load_text(path) or " ".join(saved.source.split()) in " ".join(
        load_text(path).split()
    )
    assert "Classification:" in saved.notes
    with pytest.raises(ValueError, match="duplicate"):
        ingest_document(vault_dir, path, extractor=extractor())
    assert len(read_all(vault_dir)) == 1


def test_school_real_due_date_and_discount_notes(vault_dir):
    ingest_document(
        vault_dir, str(FIXTURES / "school-fee-email.txt"), extractor=extractor("school")
    )
    saved = read_all(vault_dir)[0]
    assert saved.due == date(2026, 10, 30)
    assert saved.window_start is None
    assert "16" in saved.notes and "discount" in saved.notes.lower()


def test_ambiguous_no_write_then_hint_round_trip(vault_dir):
    path = str(FIXTURES / "insurance-renewal-ambiguous.pdf")
    result = ingest_document(vault_dir, path, extractor=extractor("ambiguous"))
    assert result["status"] == "needs_confirmation"
    assert result["question"]
    assert not list(vault_dir.iterdir())
    client = ReplayClient("confirmed")
    result = ingest_document(
        vault_dir, path, "I received it on 2026-10-01.", extractor=BedrockExtractor(client)
    )
    assert result["status"] == "saved"
    saved = read_all(vault_dir)[0]
    assert saved.due == date(2026, 10, 31)
    assert "2026-10-01" in saved.notes
    payload = json.loads(client.requests[0]["messages"][0]["content"][0]["text"])
    assert payload["user_hint"] == "I received it on 2026-10-01."


@pytest.mark.parametrize(
    "field,value",
    [
        ("due", "15 November 2026"),
        ("due", "2026-02-30"),
        ("due", "20261115"),
        ("window_start", "2027-01-01"),
        ("source", "A fabricated date quote"),
        ("confidence", True),
        ("confidence", float("nan")),
        ("confidence", 2),
        ("ambiguities", "none"),
        ("kind", "mandatory"),
        ("title", ""),
    ],
)
def test_invalid_model_output_never_writes(vault_dir, field, value):
    client = ReplayClient()
    client.response["output"]["message"]["content"][0]["toolUse"]["input"][field] = value
    with pytest.raises(ExtractionError):
        ingest_document(
            vault_dir, str(FIXTURES / "immigration-letter.pdf"), extractor=BedrockExtractor(client)
        )
    assert not list(vault_dir.iterdir())


@pytest.mark.parametrize(
    "change",
    [
        {"confidence": 0.69, "question": ""},
        {"due": "", "question": ""},
        {"ambiguities": ["Two possible dates"], "question": "Which date applies?"},
        {"question": "Please confirm the year?"},
    ],
)
def test_uncertainty_never_writes(vault_dir, change):
    client = ReplayClient()
    client.response["output"]["message"]["content"][0]["toolUse"]["input"].update(change)
    result = ingest_document(
        vault_dir, str(FIXTURES / "immigration-letter.pdf"), extractor=BedrockExtractor(client)
    )
    assert result["status"] == "needs_confirmation" and result["question"]
    assert not list(vault_dir.iterdir())


@pytest.mark.parametrize("mode", ["prose", "truncated", "wrong_tool", "extra_tool"])
def test_bad_response_envelope_rejected(vault_dir, mode):
    client = ReplayClient()
    content = client.response["output"]["message"]["content"]
    if mode == "prose":
        content[:] = [{"text": '```json {"due":"2026-11-15"} ```'}]
    elif mode == "truncated":
        client.response["stopReason"] = "max_tokens"
    elif mode == "wrong_tool":
        content[0]["toolUse"]["name"] = "delete_files"
    else:
        content.append(copy.deepcopy(content[0]))
    with pytest.raises(ExtractionError):
        ingest_document(
            vault_dir, str(FIXTURES / "immigration-letter.pdf"), extractor=BedrockExtractor(client)
        )
    assert not list(vault_dir.iterdir())


def test_bounded_input_and_truncation_requires_confirmation(vault_dir):
    document = load_text(str(FIXTURES / "immigration-letter.pdf")) + "\nx" * 10_000
    text, truncated = bounded_input(document, "hint")
    assert truncated and len(text) + len("hint") == MAX_INPUT
    assert text.startswith("Northaven") and text.endswith("\nx")
    result = ingest_document(vault_dir, document, extractor=extractor())
    assert result["status"] == "needs_confirmation"
    assert not list(vault_dir.iterdir())


def test_hint_length_and_request_schema(caplog):
    client = ReplayClient()
    model = BedrockExtractor(client)
    document = load_text(str(FIXTURES / "immigration-letter.pdf"))
    with pytest.raises(ValueError, match="hint"):
        model.extract(document, "x" * 2001)
    assert not client.requests
    model.extract(document)
    request = client.requests[0]
    assert request["toolConfig"]["toolChoice"] == {"tool": {"name": "extract_deadline"}}
    assert "input_tokens=" in caplog.text
    assert "Alex Example" not in caplog.text


def test_network_error_never_writes(vault_dir):
    class FailedClient:
        def converse(self, **kwargs):
            raise ClientError(
                {"Error": {"Code": "AccessDeniedException", "Message": "denied"}}, "Converse"
            )

    with pytest.raises(ExtractionError, match="AWS login"):
        ingest_document(
            vault_dir, "Fees due 2026-11-15", extractor=BedrockExtractor(FailedClient())
        )
    assert not list(vault_dir.iterdir())


def test_mcp_tool_registered():
    import asyncio

    from duebook.server import mcp

    assert "ingest_document" in [tool.name for tool in asyncio.run(mcp.list_tools())]


@pytest.mark.skipif(os.environ.get("DUEBOOK_LIVE") != "1", reason="opt-in billable Bedrock test")
def test_live_immigration(vault_dir):
    result = ingest_document(vault_dir, str(FIXTURES / "immigration-letter.pdf"))
    assert result["status"] == "saved"
    assert result["entry"]["due"] == "2026-11-15"
    assert result["entry"]["confidence"] >= 0.9


def test_confident_invented_receipt_date_is_blocked(vault_dir):
    client = ReplayClient("ambiguous")
    fields = client.response["output"]["message"]["content"][0]["toolUse"]["input"]
    fields.update(due="2023-09-24", confidence=0.99, ambiguities=[], question="")
    result = ingest_document(
        vault_dir,
        str(FIXTURES / "insurance-renewal-ambiguous.pdf"),
        extractor=BedrockExtractor(client),
    )
    assert result["status"] == "needs_confirmation"
    assert result["candidate"]["due"] == ""
    assert "receive" in result["question"]
    assert not list(vault_dir.iterdir())


@pytest.mark.parametrize(
    "hint", [None, "2026-10-01", "Received on 2026-02-30", "Received 2026-10-01 or 2026-10-02"]
)
def test_receipt_anchor_must_be_explicit_and_unambiguous(vault_dir, hint):
    result = ingest_document(
        vault_dir,
        str(FIXTURES / "insurance-renewal-ambiguous.pdf"),
        hint,
        extractor=extractor("confirmed"),
    )
    assert result["status"] == "needs_confirmation"
    assert not list(vault_dir.iterdir())


def test_receipt_arithmetic_is_not_left_to_model(vault_dir):
    client = ReplayClient("confirmed")
    client.response["output"]["message"]["content"][0]["toolUse"]["input"]["due"] = "2026-11-01"
    result = ingest_document(
        vault_dir,
        str(FIXTURES / "insurance-renewal-ambiguous.pdf"),
        "Received on 2026-10-01",
        extractor=BedrockExtractor(client),
    )
    assert result["entry"]["due"] == "2026-10-31"


def test_absent_year_requires_confirmation(vault_dir):
    client = ReplayClient("school")
    fields = client.response["output"]["message"]["content"][0]["toolUse"]["input"]
    fields["source"] = "School fees are due 30 October."
    fields["due"] = "2026-10-30"
    result = ingest_document(vault_dir, fields["source"], extractor=BedrockExtractor(client))
    assert result["status"] == "needs_confirmation"
    assert not list(vault_dir.iterdir())
