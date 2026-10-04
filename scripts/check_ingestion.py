"""Live synthetic-fixture check; writes only to a temporary vault.

Run with AWS_PROFILE=duebook uv run python scripts/check_ingestion.py.
Use --record to capture synthetic Bedrock responses for offline regression tests.
"""

import json
import sys
import tempfile
from pathlib import Path

import boto3

from duebook.bedrock import BedrockExtractor
from duebook.ingest import ingest_document
from duebook.vault import read_all

ROOT = Path(__file__).resolve().parents[1]


class RecordingClient:
    def __init__(self):
        self.client = boto3.Session().client("bedrock-runtime", region_name="ap-southeast-1")
        self.response = None

    def converse(self, **kwargs):
        self.response = self.client.converse(**kwargs)
        return self.response


def main():
    client = RecordingClient()
    extractor = BedrockExtractor(client=client)
    cases = [
        ("immigration", "immigration-letter.pdf", None, "saved", "2026-11-15"),
        ("school", "school-fee-email.txt", None, "saved", "2026-10-30"),
        ("ambiguous", "insurance-renewal-ambiguous.pdf", None, "needs_confirmation", ""),
        (
            "confirmed",
            "insurance-renewal-ambiguous.pdf",
            "I received it on 2026-10-01.",
            "saved",
            "2026-10-31",
        ),
    ]
    with tempfile.TemporaryDirectory(prefix="duebook-live-") as temp:
        vault = Path(temp)
        for name, filename, hint, status, due in cases:
            result = ingest_document(
                vault, str(ROOT / "tests/fixtures" / filename), hint, extractor=extractor
            )
            assert result["status"] == status, result
            entry = result.get("entry", result.get("candidate"))
            assert entry["due"] == due, result
            if name == "immigration":
                assert entry["window_start"] == "2026-11-01", result
                assert entry["confidence"] >= 0.9, result
            if name == "ambiguous":
                assert len(read_all(vault)) == 2
            if "--record" in sys.argv:
                dest = ROOT / "tests/fixtures/bedrock" / f"{name}.json"
                dest.parent.mkdir(exist_ok=True)
                # Strip request/account metadata; only synthetic content + usage are retained.
                payload = {key: client.response[key] for key in ("output", "stopReason", "usage")}
                dest.write_text(json.dumps(payload, indent=2) + "\n")
            print(f"{name}: {status}, due={entry['due'] or 'unresolved'}")
        assert len(read_all(vault)) == 3
        print("All three documents passed, including the clarification round-trip.")


if __name__ == "__main__":
    main()
