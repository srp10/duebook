import importlib.util
from pathlib import Path

import pytest

from duebook.loader import LoadError, load_text

FIXTURES = Path(__file__).parent / "fixtures"
_spec = importlib.util.spec_from_file_location(
    "make_fixtures", Path(__file__).parents[1] / "scripts" / "make_fixtures.py"
)
make_fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_fixtures)


def test_pdf_fixture_text_layer():
    text = load_text(str(FIXTURES / "immigration-letter.pdf"))

    assert "no later than 15 November 2026" in text
    assert "Our ref: NDIS/RP/2026/004417" in text


def test_ambiguous_pdf_fixture_has_no_absolute_due_date():
    text = load_text(str(FIXTURES / "insurance-renewal-ambiguous.pdf"))

    assert "within 30 days of" in text
    assert "2026" not in text


def test_txt_fixture_read_directly():
    text = load_text(str(FIXTURES / "school-fee-email.txt"))

    assert text.startswith("From: Bursar")
    assert "due by 30 October 2026" in text


def test_eml_read_as_text(tmp_path):
    p = tmp_path / "note.eml"
    p.write_text("Subject: Fees\n\nPay by 1 Dec 2026.", encoding="utf-8")

    assert load_text(str(p)).endswith("Pay by 1 Dec 2026.")


def test_pasted_text_passes_through():
    text = "Your permit renewal is due 15 November 2026.\nThanks."

    assert load_text(text) == text


def test_short_pasted_text_without_file_suffix_passes_through():
    assert load_text("Pay the gas bill by 2026-10-10") == "Pay the gas bill by 2026-10-10"


def test_missing_file_is_an_error_not_text():
    with pytest.raises(LoadError, match="file not found"):
        load_text("/nowhere/letter.pdf")


def test_pdf_without_text_layer(tmp_path):
    p = tmp_path / "scan.pdf"
    p.write_bytes(make_fixtures.pdf(""))

    with pytest.raises(LoadError, match="no text layer"):
        load_text(str(p))


def test_corrupt_pdf(tmp_path):
    p = tmp_path / "broken.pdf"
    p.write_bytes(b"%PDF-1.4\nthis is not really a pdf")

    with pytest.raises(LoadError, match="not a readable PDF|no text layer"):
        load_text(str(p))


def test_binary_file(tmp_path):
    p = tmp_path / "photo.txt"
    p.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")

    with pytest.raises(LoadError, match="binary"):
        load_text(str(p))


def test_non_utf8_text(tmp_path):
    p = tmp_path / "latin.txt"
    p.write_bytes("Café fees due".encode("latin-1"))

    with pytest.raises(LoadError, match="UTF-8"):
        load_text(str(p))


def test_empty_document(tmp_path):
    p = tmp_path / "empty.txt"
    p.write_text("   \n", encoding="utf-8")

    with pytest.raises(LoadError, match="empty"):
        load_text(str(p))
