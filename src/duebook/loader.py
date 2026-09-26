"""Turn a document (file path or pasted text) into plain text for extraction.

PDFs go through pdfplumber; everything else is read as UTF-8 text. No OCR: a PDF
without a text layer (a scan) is an error, not a guess.
"""

from pathlib import Path

import pdfplumber
from pdfplumber.utils.exceptions import PdfminerException

FILE_SUFFIXES = {".pdf", ".txt", ".eml"}


class LoadError(ValueError):
    """The document can't be turned into usable text."""


def load_text(path_or_text: str) -> str:
    """Return the text of a file at `path_or_text`, or `path_or_text` itself if it isn't a path."""
    path = _as_path(path_or_text)
    if path is None:
        text = path_or_text
    elif path.suffix.lower() == ".pdf" or _starts_with(path, b"%PDF"):
        text = _pdf_text(path)
    else:
        text = _plain_text(path)
    if not text.strip():
        raise LoadError("document is empty")
    return text


def _as_path(value: str) -> Path | None:
    """A Path if `value` names a file; None if it's pasted text. Raises for a missing file."""
    if "\n" in value or len(value) > 1024:
        return None
    path = Path(value.strip()).expanduser()
    if path.is_file():
        return path
    if path.suffix.lower() in FILE_SUFFIXES:
        raise LoadError(f"file not found: {path}")
    return None


def _starts_with(path: Path, magic: bytes) -> bool:
    with path.open("rb") as f:
        return f.read(len(magic)) == magic


def _pdf_text(path: Path) -> str:
    try:
        with pdfplumber.open(path) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    except PdfminerException as e:  # pdfplumber wraps every pdfminer parse error in this
        raise LoadError(f"{path.name}: not a readable PDF ({e})") from None
    if not text.strip():
        raise LoadError(
            f"{path.name}: PDF has no text layer (probably a scan). OCR is not supported; "
            "paste the text instead."
        )
    return text


def _plain_text(path: Path) -> str:
    data = path.read_bytes()
    if b"\x00" in data[:8192]:
        raise LoadError(f"{path.name}: looks like a binary file, not text or PDF")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise LoadError(f"{path.name}: not UTF-8 text") from None
